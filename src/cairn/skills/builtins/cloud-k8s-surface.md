---
name: cloud-k8s-surface
description: Map cloud + container attack surface — bucket permutation/probe, serverless + K8s/etcd/kubelet + CI/CD platform exposure.
usage: /cloud-k8s-surface <org-or-domain>
---

# Cloud + Container Attack Surface

Map a target's cloud-native footprint: storage buckets (S3/GCS/Azure Blob), serverless/managed
platforms (Lambda/Cloud Run/Azure Functions/Vercel/Netlify/Workers), container registries,
Kubernetes/etcd/kubelet exposure, and CI/CD platforms (Jenkins/GitLab/TeamCity/ArgoCD).

## AUTHORIZATION GATE — READ FIRST

Active probing (HTTP HEAD/GET against bucket candidates, K8s API endpoints, CI/CD paths, container
registry pulls) is **OFFENSIVE RECON**. It requires **CAIRN_MODE=challenge AND explicit user
authorization on an owned/in-scope target**. Cairn's default `investigate` mode is **passive-only**:
in that mode, restrict yourself to the passive steps below (certificate transparency, DNS, web
search, archive lookups) and STOP before any curl/probe. Confirm scope out loud before switching to
the probe plan.

The cloud-native tradecraft below is included as KNOWLEDGE so the brain knows the techniques and
when they apply — it is never auto-run against a third party.

## Confidence levels

- TENTATIVE — permutation candidate exists by name pattern (unprobed).
- FIRM — HEAD/probe returned a definitive status (200/301/403 on bucket; banner on K8s endpoint).
- CONFIRMED — object listing or readable secret retrieved and corroborated.

## PLAN

Passive phase (investigate mode, always allowed):

1. `crtsh <domain>` — pull subdomains from CT logs; many cloud assets (`*.s3-website`,
   `*.lambda-url`, `*.run.app`, `*.azurewebsites.net`, `*.vercel.app`) appear as SANs/CNAMEs.
2. `dns_lookup <domain> CNAME` (and A) on each candidate subdomain — CNAMEs that point at
   `*.amazonaws.com`, `*.storage.googleapis.com`, `*.blob.core.windows.net`,
   `*.cloudfront.net`, `*.azurewebsites.net`, `*.run.app`, `*.workers.dev`, `*.vercel.app`,
   `*.netlify.app`, `*.herokuapp.com` reveal the cloud platform and (for buckets/CDN) the bucket
   name. This is passive and high-signal.
3. `web_search` — dork the target + platform domains for leaked references:
   `site:s3.amazonaws.com "<org>"`, `site:storage.googleapis.com "<org>"`,
   `site:blob.core.windows.net "<org>"`, `site:hub.docker.com "<org>"`,
   `site:atlassian.net "<org>" wiki`, `site:vercel.app "<org>"`.
4. `scrape_url` the target homepage + JS bundles — extract hardcoded cloud endpoints and bucket
   URLs (regex tiers below). Mark matches TENTATIVE until probed.
5. `wayback_cdx <domain>` — historical snapshots often reference decommissioned buckets and
   function URLs whose names are still valid permutation stems.
6. `github <org-login>` — commit-mine for bucket names, registry paths, `~/.kube/config` leaks,
   Terraform state refs, CI workflow secrets; pivot into repos via the github plugin's output.

Active phase (challenge mode + explicit authorization ONLY):

7. `run_command` — curl HEAD/GET each bucket candidate (template below). 200/301 = exists;
   403 = exists-private; 404 = skip. On exists, GET root: if XML/JSON object listing returns →
   CRITICAL `PUBLIC_CLOUD_BUCKET`; object reads without listing → HIGH
   `PUBLIC_CLOUD_BUCKET_OBJECT_READ`.
8. `run_command` — curl the K8s/etcd/kubelet and CI/CD probe paths on confirmed in-scope hosts.
9. `download_url` / `read_file` — pull listable bucket contents / public registry blobs / kubelet
   pod manifests into the workspace; then run `secret_scan <file-or-dir>` (48-pattern catalog)
   across everything retrieved.

## A. Cloud bucket permutation (§16.8)

**6 prefixes:** `""`, `backup-`, `assets-`, `static-`, `dev-`, `prod-`
**15 suffixes:** `""`, `-backup`, `-assets`, `-static`, `-media`, `-data`, `-uploads`, `-dev`,
`-prod`, `-staging`, `-logs`, `-private`, `-public`, `-dump`, `-archive`

**Stems (combine with a target token — org name, product name, brand abbreviation):**
`www, mail, app, web, cdn, static, assets, media, img, images, videos, download, uploads, data,
files, docs, blog, dev, test, staging, stg, qa, uat, sandbox, preprod, vpn, backups, logs`. Pair
stems with the org token in both orders: `<org>-<stem>`, `<stem>-<org>`, `<org><stem>`.

**Provider URL templates:**
```
# S3
https://{cand}.s3.amazonaws.com/
https://{cand}.s3-{region}.amazonaws.com/    # us-east-1, us-west-2, eu-west-1, ap-southeast-1
https://s3.{region}.amazonaws.com/{cand}/
# GCS
https://{cand}.storage.googleapis.com/
https://storage.googleapis.com/{cand}/
# Azure Blob
https://{cand}.blob.core.windows.net/
https://{cand}.blob.core.windows.net/?comp=list
```

**Probe recipe (challenge mode):**
```bash
B="candidate-name"
curl -sk -m 10 -I "https://${B}.s3.amazonaws.com/" -w 'STATUS:%{http_code}\n'
# 200/301 → list objects
curl -sk -m 10 "https://${B}.s3.amazonaws.com/?list-type=2" | head -50
# region sweep
for r in us-east-1 us-west-2 eu-west-1 ap-southeast-1; do
  curl -sk -m 10 -I "https://${B}.s3-${r}.amazonaws.com/" -w "${r}: %{http_code}\n"
done
# GCS / Azure
curl -sk -m 10 -I "https://${B}.storage.googleapis.com/"
curl -sk -m 10 -I "https://${B}.blob.core.windows.net/"
curl -sk -m 10    "https://${B}.blob.core.windows.net/?comp=list&restype=container"
```

## B. Cloud-native platform fingerprints (§16.17)

When a CNAME or JS URL matches one of these, you have the platform — pivot to its auth posture.

| Platform | Pattern | What to check |
|---|---|---|
| AWS Lambda Function URL | `*.lambda-url.<region>.on.aws` | IAM auth vs anonymous (anonymous = HIGH) |
| AWS App Runner | `*.<region>.awsapprunner.com` | Usually behind auth |
| AWS API Gateway | `*.execute-api.<region>.amazonaws.com` | Authorizer config |
| AWS CloudFront | `d{14}.cloudfront.net` | Origin behind it (bucket or EC2) |
| AWS ALB/ELB | `*.elb.<region>.amazonaws.com` | EC2/ECS behind |
| AWS Amplify | `*.amplifyapp.com` | Static + Lambda |
| Google Cloud Run | `*.run.app` | IAM auth vs public |
| Google Cloud Functions | `*.cloudfunctions.net` | IAM auth vs public |
| Google App Engine | `*.appspot.com` | Older serverless |
| Azure Functions / App Service | `*.azurewebsites.net` | Auth level (anonymous/function/admin) |
| Azure Container Apps | `*.azurecontainerapps.io` | Ingress auth |
| Azure Static Web Apps | `*.azurestaticapps.net` | Functions + roles |
| Vercel | `*.vercel.app`, `*.now.sh` | `/api/*` serverless |
| Netlify | `*.netlify.app` | Functions under `/.netlify/functions/*` |
| Cloudflare Workers | `*.workers.dev` | Edge function |
| Cloudflare Pages | `*.pages.dev` | Functions under `/api/*` (or `/<_worker>`) |
| Heroku | `*.herokuapp.com` | Dyno |
| Render | `*.onrender.com` | Container/static |
| Fly.io | `*.fly.dev` | Edge container |
| Railway | `*.railway.app` | App platform |
| DigitalOcean App Platform | `*.ondigitalocean.app` | Static + container |

For each: confirm public vs auth-required (HEAD/GET), check CORS posture, and for static+function
hybrids enumerate `/api/*` paths via JS extraction (Tier 2 regex below).

**JS extraction (run on scraped JS bundles):**
```regex
# Tier 1 — generic quoted paths
['"`](/[A-Za-z0-9_\-./{}\[\]?=&%:]+)['"`]
# Tier 2 — API-ish bias
['"`](/(?:api|graphql|v\d+|rest|internal|admin|auth|oauth|users|upload|download|webhook)/[A-Za-z0-9_\-./?=&%]+)['"`]
```

## C. Container & Kubernetes exposure (§16.18)

| Target | Port | Probe (challenge) | Severity |
|---|---|---|---|
| Docker API (unencrypted) | 2375 | `curl -sk -m 5 http://${IP}:2375/v1.40/info` | CRITICAL |
| Docker API (TLS) | 2376 | `curl -sk -m 5 https://${IP}:2376/v1.40/info` | HIGH |
| K8s API server | 6443/8443 | `curl -sk -m 5 https://${IP}:6443/api` | HIGH if `system:anonymous` ≠ 403 |
| K8s Dashboard | 8001/9090/30000+ | `curl -sk -m 5 http://${IP}:8001/api/v1/namespaces/kube-system/services/kubernetes-dashboard` | HIGH |
| kubelet (HTTPS) | 10250 | `curl -sk -m 5 https://${IP}:10250/pods` | CRITICAL (no auth = pod exec) |
| kubelet (HTTP, deprecated) | 10255 | `curl -sk -m 5 http://${IP}:10255/pods` | HIGH |
| etcd (client) | 2379 | `curl -sk -m 5 https://${IP}:2379/v2/keys/` or `etcdctl --endpoints=${IP}:2379 get /` | CRITICAL (cluster state + secrets) |
| etcd (peer) | 2380 | (fingerprint only) | — |
| kube-controller-manager | 10257 | `curl -sk -m 5 https://${IP}:10257/metrics` | MEDIUM |
| kube-scheduler | 10259 | `curl -sk -m 5 https://${IP}:10259/metrics` | MEDIUM |
| Helm Tiller (Helm 2, deprecated) | 44134 | `helm --host ${IP}:44134 list` | HIGH (cluster-admin) |

**Public container registries (passive search — no auth needed):**
| Registry | Search URL |
|---|---|
| Docker Hub | `https://hub.docker.com/search?q=<keyword>&type=image` |
| Quay | `https://quay.io/search?q=<keyword>` |
| GHCR | GitHub API: `https://api.github.com/orgs/<org>/packages?package_type=container` (via `github` plugin) |
| Amazon ECR Public | `https://gallery.ecr.aws/?searchTerm=<keyword>` |

**Per-image workflow (challenge, on a pulled public image only):**
1. `run_command`: `docker pull <registry>/<image>:<tag>` (or `skopeo inspect`).
2. `run_command`: `docker save <image> -o /tmp/img.tar`.
3. `list_files` / `read_file` extract layers into workspace.
4. `secret_scan <extracted-dir>` — 48-pattern catalog catches AWS/GCP/Azure keys, npm/PyPI/Docker
   Hub tokens, Anthropic/OpenAI keys, Postman PMAK, Slack, Atlassian, DataDog, Sentry, ngrok.
5. Inspect `Dockerfile` history (`docker history <image>`) — sometimes reveals build args or
   `COPY` of secrets into a layer.

## D. CI/CD platform exposure (§16.19)

| Platform | Probe (challenge) | Finding |
|---|---|---|
| Jenkins | `curl -sk -m 10 "${T}/script"` (Groovy console = RCE if no auth), `/asynchPeople/api/json`, `/computer/`, `/job/<name>/api/json` | HIGH–CRITICAL |
| GitLab self-hosted | `curl -sk -m 10 "${T}/api/v4/version"` (version), `/users/sign_in` (HTML version), `/-/snippets/<id>/raw` | HIGH (CVE-2021-22205 etc.) |
| TeamCity | `curl -sk -m 10 "${T}/login.html" | grep -i TeamCity` | HIGH (CVE-2024-27198 KEV) |
| Argo CD | `curl -sk -m 10 "${T}/api/version"`; check anonymous-auth | HIGH |
| Bamboo | `curl -sk -m 10 "${T}/rest/api/latest/info"` | MEDIUM |
| Drone CI | `curl -sk -m 10 "${T}/api/info"` | MEDIUM |
| Spinnaker | `curl -sk -m 10 "${T}/gate/info"` | MEDIUM |
| Tekton (K8s native) | enumerate via K8s API `/apis/tekton.dev/v1beta1/pipelineruns` | MEDIUM |

**GitHub Actions secret-leak patterns (passive, via `github` code search on public repos):**
```yaml
# Anti-pattern: secret echoed to log
run: echo "${{ secrets.MY_API_KEY }}"
# Anti-pattern: pull_request_target + checkout of fork code
on: pull_request_target
jobs:
  test:
    steps:
      - uses: actions/checkout@v3
        with:
          ref: ${{ github.event.pull_request.head.sha }}   # runs fork code with secrets in env
```
Search dorks (feed to `web_search` or `github`): `path:.github/workflows extension:yml secrets`,
`path:.circleci/config.yml`, `path:.travis.yml`. Repo-local config files (`.circleci/`,
`.github/workflows/`, `.travis.yml`) pulled into workspace are scanned by `secret_scan`.

## PIVOTS

- Bucket CNAME → bucket name → permutation expansion (same name in other regions/providers).
- CloudFront distribution `d{14}` → brute the 14-hex space is NOT allowed (active); instead pivot
  via SAN certs (`crtsh`) and JS references.
- Container registry image → `secret_scan` its layers → leaked cloud keys → (separate authorized
  workflow) key triage.
- K8s API server exposed → kubelet `/pods` → etcd keys → cluster secrets (CRITICAL chain).
- CI/CD platform version → cross-reference CISA KEV via `h1_reference <keyword>` for disclosed
  exploit context.
- Serverless function URL with anonymous invocation → enumerate `/api/*` via JS → parameter
  fuzzing (challenge + authorization only).

## OUTPUT FORMAT

For each finding, emit:
- `id`, `module: cloud-k8s-surface`, `asset_key` (bucket name / host:port / image ref)
- `category`: `PUBLIC_CLOUD_BUCKET` | `PUBLIC_CLOUD_BUCKET_OBJECT_READ` | `K8S_EXPOSURE` |
  `ETCD_EXPOSURE` | `KUBELET_EXPOSURE` | `DOCKER_API_EXPOSURE` | `REGISTRY_LEAK` |
  `CICD_EXPOSURE` | `CICD_VERSION_DISCLOSURE` | `SERVERLESS_ANON_AUTH` | `INFO_DISCLOSURE`
- `severity`: info / low / medium / high / critical
- `confidence`: TENTATIVE / FIRM / CONFIRMED
- `evidence`: URL + UTC timestamp + sha256 of raw response (cap body at 2 KiB) + HTTP status
- `remediation`: bucket ACL private + block-public-access; K8s API authn/authz + NetworkPolicy;
  kubelet anonymous-auth=false; etcd client TLS + firewall; CI/CD upgrade + auth on console;
  registry image rescan + key rotation.

## PAID / EXCLUDED SOURCES (do not call)

SecurityTrails, DomainTools, WhoisXML API, RiskIQ (beyond free), Censys (beyond free 250/mo),
GrayhatWarfare bucket search, BuckHacker, IntelX (paid) are EXCLUDED as paid platforms. If a
technique would need one, treat as **note-only / requires your own key** and use the free
alternative: `crtsh` (CT logs), `dns_lookup` (CNAME → platform), `wayback_cdx` (historical refs),
`web_search` (dork-driven discovery), Shodan InternetDB via `shodan_internetdb` (keyless, IP only,
1 req/sec) for port/service banners on confirmed in-scope IPs. Bucket enumeration by permutation +
HEAD/GET is free and is the primary technique.

> Tradecraft adapted from [Claude-OSINT](https://github.com/elementalsouls/Claude-OSINT) by ElementalSoul (MIT). Active techniques gated to authorized/challenge use.
