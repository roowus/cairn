#!/usr/bin/env bash
# Convert the user's research RTFs into Markdown under docs/research/.
# Uses macOS-native `textutil` (no extra dependencies).
# Portable: works on macOS system bash 3.2 (no associative arrays).
#
# Usage:  bash scripts/import_research_docs.sh [source_dir]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
SRC_DIR="${1:-$HOME/Downloads}"
DEST_SRC="$ROOT/docs/research/_source"
DEST_MD="$ROOT/docs/research"

# "source RTF filename|short-slug" pairs. The slug is used for both
# _source/<slug>.rtf and <slug>.md.
PAIRS=(
  "AI OSINT Agent Architecture Design.rtf|agent-architecture"
  "AI OSINT Development Research.rtf|dev-research"
  "AI OSINT CLI Tool Architecture.rtf|cli-architecture"
)

mkdir -p "$DEST_SRC" "$DEST_MD"

if ! command -v textutil >/dev/null 2>&1; then
  echo "ERROR: 'textutil' not found. This script is macOS-native." >&2
  exit 1
fi

converted=0
for pair in "${PAIRS[@]}"; do
  rtf="${pair%%|*}"
  slug="${pair##*|}"
  src="$SRC_DIR/$rtf"
  if [[ ! -f "$src" ]]; then
    echo "  skip (not found): $src"
    continue
  fi
  cp "$src" "$DEST_SRC/$slug.rtf"
  textutil -convert txt -stdout "$DEST_SRC/$slug.rtf" > "$DEST_MD/$slug.md"
  echo "  converted: $rtf -> docs/research/$slug.md"
  converted=$((converted + 1))
done

if [[ "$converted" -eq 0 ]]; then
  echo "WARNING: no RTFs found in $SRC_DIR" >&2
  echo "  Pass the source dir as an argument: bash scripts/import_research_docs.sh /path/to/rtfs" >&2
  exit 0
fi

cat <<'NOTE'

  TODO (manual cleanup, optional):
    - These .md files are raw textutil output. Review headings/tables/lists
      and tidy formatting where RTF artifacts remain.
    - Add a front-matter title + source line at the top of each.
  Originals are preserved verbatim in docs/research/_source/*.rtf.
NOTE
echo "Done. $converted document(s) converted."
