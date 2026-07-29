"""download_url — fetch a URL's raw bytes into the workspace (agentic).

Distinct from ``scrape_url`` (which returns condensed *text* of a page): this
saves the raw *bytes* to the workspace so the agent can run binary analyzers
(``file`` / ``binwalk`` / ``exiftool`` / ``strings`` / ``foremost``) on the
artifact. The fetched bytes are untrusted — only a summary (size, type, hash,
path) is returned to the model; the bytes never enter model context directly.

Downloads are hard-capped (default 25 MiB) with a Content-Length pre-check and
a streaming write so a multi-GB body cannot OOM the process or fill the
workspace in one call.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field

from cairn.execution.base import BasePlugin, PluginContext, PluginInput, PluginOutput
from cairn.execution.http_util import http_client
from cairn.execution.workspace import Deny, authorize, resolve_in_workspace

# Default hard cap for a single download (bytes). Override per call via max_bytes.
_DEFAULT_MAX_BYTES = 25 * 1024 * 1024  # 25 MiB
_CHUNK = 64 * 1024


class DownloadUrlInput(PluginInput):
    target: str = Field(..., description="URL to download (http/https).")
    dest: str = Field(
        "", description="Workspace-relative filename (default: derived from the URL)."
    )
    max_bytes: int = Field(
        default=_DEFAULT_MAX_BYTES,
        ge=1024,
        le=500 * 1024 * 1024,
        description="Hard size cap in bytes (default 25 MiB). Abort if exceeded.",
    )


class DownloadUrlOutput(PluginOutput):
    url: str = ""
    dest: str = ""
    bytes_saved: int = 0
    content_type: str = ""
    sha256: str = ""


class DownloadUrlPlugin(BasePlugin[DownloadUrlInput, DownloadUrlOutput]):
    name = "download_url"
    category = "agentic"
    requires_key = None
    input_model = DownloadUrlInput
    output_model = DownloadUrlOutput

    __doc__ = (
        "Download a URL's raw bytes to the workspace (target = url; dest = "
        "workspace-relative filename, default from the URL). Hard-capped at "
        "25 MiB by default (max_bytes). For reading a page as text, prefer "
        "scrape_url. Use this for binaries/zip/pcap/images, then analyze with "
        "run_command (file/binwalk/exiftool/strings). Returns size, content-type, "
        "sha256, and the saved path — not the bytes."
    )

    async def run(self, inp: DownloadUrlInput, ctx: PluginContext) -> DownloadUrlOutput:
        url = (inp.target or "").strip()
        if not url:
            return DownloadUrlOutput(
                source=self.name, url=url, summary_markdown="**download_url error**: no URL given."
            )
        if not url.lower().startswith(("http://", "https://")):
            return DownloadUrlOutput(
                source=self.name,
                url=url,
                summary_markdown=(
                    "**download_url error**: only http(s) URLs are allowed "
                    f"(got scheme from `{urlparse(url).scheme or 'none'}`)."
                ),
            )
        ws = getattr(ctx, "workspace", None)
        if ws is None:
            return DownloadUrlOutput(
                source=self.name,
                url=url,
                summary_markdown=(
                    "**download_url error**: no scratch workspace configured "
                    "(set CAIRN_WORKSPACE_DIR)."
                ),
            )
        ws_path = Path(ws).expanduser()
        roots = [ws_path]
        dest_name = (inp.dest or "").strip() or _default_name(url)
        # Route the dest through the SAME audited gate as read/write/list (not a
        # bespoke check): resolve_in_workspace safely collapses ../ + symlinks and
        # never raises on a symlink loop, and authorize() is the single deny path —
        # so a future interactive PermissionUI could approve an out-of-workspace
        # dest symmetrically with the other file ops.
        candidate = ws_path / dest_name
        decision = await authorize("write", candidate, roots, getattr(ctx, "permission", None))
        if isinstance(decision, Deny):
            return DownloadUrlOutput(
                source=self.name,
                url=url,
                summary_markdown=f"**download_url denied**: {decision.reason}",
            )
        dest_path = resolve_in_workspace(candidate, roots)
        assert dest_path is not None  # authorize() returned Allow → inside the ws
        max_bytes = int(inp.max_bytes)

        async with http_client(ctx) as http:
            try:
                async with http.stream("GET", url) as r:
                    if r.status_code >= 400:
                        return DownloadUrlOutput(
                            source=self.name,
                            url=url,
                            summary_markdown=(
                                f"**download_url failed**: HTTP {r.status_code} for {url}"
                            ),
                        )
                    cl = r.headers.get("content-length")
                    if cl and cl.isdigit() and int(cl) > max_bytes:
                        return DownloadUrlOutput(
                            source=self.name,
                            url=url,
                            summary_markdown=(
                                f"**download_url aborted**: Content-Length {int(cl)} bytes "
                                f"exceeds cap of {max_bytes} bytes."
                            ),
                        )
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    h = hashlib.sha256()
                    total = 0
                    try:
                        with dest_path.open("wb") as fh:
                            async for chunk in r.aiter_bytes(_CHUNK):
                                if not chunk:
                                    continue
                                total += len(chunk)
                                if total > max_bytes:
                                    fh.close()
                                    dest_path.unlink(missing_ok=True)
                                    return DownloadUrlOutput(
                                        source=self.name,
                                        url=url,
                                        summary_markdown=(
                                            f"**download_url aborted**: body exceeded cap of "
                                            f"{max_bytes} bytes (streamed {total} before stop)."
                                        ),
                                    )
                                fh.write(chunk)
                                h.update(chunk)
                    except Exception:
                        dest_path.unlink(missing_ok=True)
                        raise
                    ct = r.headers.get("content-type", "")
                    digest = h.hexdigest()
                    return DownloadUrlOutput(
                        source=self.name,
                        url=url,
                        dest=str(dest_path),
                        bytes_saved=total,
                        content_type=ct,
                        sha256=digest,
                        summary_markdown=(
                            f"Downloaded **{total} bytes** from `{url}` → `{dest_path}`.\n"
                            f"- content-type: `{ct or 'unknown'}`\n"
                            f"- sha256: `{digest}`\n"
                            f"- Next: `run_command` `file {dest_path}` / `binwalk` / "
                            f"`exiftool` / `strings`."
                        ),
                    )
            except Exception as exc:
                return DownloadUrlOutput(
                    source=self.name, url=url, summary_markdown=f"**download_url error**: {exc}"
                )


def _default_name(url: str) -> str:
    path = urlparse(url).path
    base = Path(path).name or "download"
    base = "".join(c if (c.isalnum() or c in "-._") else "_" for c in base) or "download"
    return base[:80]
