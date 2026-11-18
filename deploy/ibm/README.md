# IBM watsonx Orchestrate — Deployment Guide

> **This document is grounded in the
> [GSA-TTS mcp-hackathon-template `deploy/ibm/`](https://github.com/GSA-TTS/mcp-hackathon-template/tree/main/deploy/ibm)
> reference.** It adapts that reference for the `gsa_graj_tools` and
> `gsa_graj_viz` servers and their agents in this workspace.

Four self-contained paths get the `gsa_graj_tools` MCP server into
**watsonx Orchestrate**, ordered from lowest to highest infrastructure overhead.

| Path | Transport / where it runs | Infra needed | Best for |
|---|---|---|---|
| **[A — ICR prebuilt image (current)](#path-a--icr-prebuilt-image-current)** | streamable-HTTP on IBM Code Engine (image pushed to `ca.icr.io`) | Code Engine + IBM Container Registry | Current setup — already running |
| **[B — GHCR prebuilt image](#path-b--ghcr-prebuilt-image)** | streamable-HTTP on IBM Code Engine (public image, no ICR auth) | Code Engine + public image on GHCR | No ICR authority — point CE at a public image |
| **[C — Local stdio toolkit](#path-c--local-stdio-toolkit)** | stdio, runs inside Orchestrate | None (ADK + repo) | Fastest to register; no cloud deploy needed |
| **[D — Build-from-Git](#path-d--build-from-git-code-engine)** | streamable-HTTP on IBM Code Engine (CE builds from Git server-side) | Code Engine + ICR (no local Docker) | No local Docker/podman — CE clones, builds, deploys |

---

## Prerequisites (all paths)

```bash
# 1. IBM Cloud CLI + plugins
ibmcloud version                         # confirm installed
ibmcloud plugin install code-engine      # for Path A/B
ibmcloud plugin install container-registry  # for Path A only

# 2. Orchestrate ADK
pip install --upgrade ibm-watsonx-orchestrate
orchestrate --version

# 3. Log in
ibmcloud login --sso           # or --apikey "$IBM_CLOUD_API_KEY"
ibmcloud target                # confirm account / region
```

Your watsonx Orchestrate instance URL and API key are on the wxO service page in
IBM Cloud (Resource List → your watsonx Orchestrate instance).

---

## Path A — ICR prebuilt image (current)

This is the **currently running setup**.

| Item | Value |
|---|---|
| Code Engine project | `gsa-graj-ce` (region `ca-tor`) |
| App name | `gsa-graj-tools` |
| Image | `ca.icr.io/gsa-graj-wxo/gsa-graj-tools:latest` |
| ICR registry secret | `icr-secret` |
| Public URL | `https://gsa-graj-tools.2h721savdmhn.ca-tor.codeengine.appdomain.cloud` |
| MCP endpoint | `…/mcp` |
| Health endpoint | `…/health` |
| Toolkit name in wxO | `gsa_graj_tools` |
| Agent name in wxO | `gsa_graj_agent` |

### A.1 Build & push the image

```bash
# From the repo root
podman build -t ca.icr.io/gsa-graj-wxo/gsa-graj-tools:latest \
  toolkits/gsa_graj_tools/

ibmcloud cr login
podman push ca.icr.io/gsa-graj-wxo/gsa-graj-tools:latest
```

> **PORT env var:** Code Engine injects `PORT` automatically (Knative reserved).
> `server.py` reads `PORT` to decide HTTP vs stdio — do not set `PORT` in the
> Dockerfile or as a CE literal env var (CE will reject it). The `ENV PORT=8000`
> line in the Dockerfile is only for local `docker run` / testing.

### A.2 Rotate the ICR registry secret (when it expires)

The registry secret must be valid or Code Engine can't pull the image.

```bash
# Create a fresh IAM API key
ibmcloud iam api-key-create ce-icr-key --output json

# Select the CE project
ibmcloud ce project select --name gsa-graj-ce

# Replace the registry secret
ibmcloud ce registry delete --name icr-secret --force
ibmcloud ce registry create \
  --name icr-secret \
  --server ca.icr.io \
  --username iamapikey \
  --password "<new-api-key>"
```

### A.3 Deploy / redeploy the app

```bash
ibmcloud ce project select --name gsa-graj-ce

# If the app already exists (update):
ibmcloud ce app update --name gsa-graj-tools --env-rm TRANSPORT   # remove stale env if present

# If creating from scratch:
ibmcloud ce app create \
  --name gsa-graj-tools \
  --image ca.icr.io/gsa-graj-wxo/gsa-graj-tools:latest \
  --registry-secret icr-secret \
  --port 8000 \
  --min-scale 1 \
  --cpu 0.25 \
  --memory 500M \
  --secret-ref postgres-secret

# Verify status
ibmcloud ce app get --name gsa-graj-tools
```

> **`--min-scale 1`** keeps one instance warm so the first tool call doesn't hit
> a cold-start timeout during an eval run.

### A.4 Smoke-test

```bash
BASE=https://gsa-graj-tools.2h721savdmhn.ca-tor.codeengine.appdomain.cloud

# Health check
curl -s "${BASE}/health" | python3 -m json.tool

# MCP endpoint reachable (a "Missing session ID" response is expected — a real
# MCP client performs the initialize handshake; a raw curl does not)
curl -s "${BASE}/mcp" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

### A.5 Register the toolkit and agent in watsonx Orchestrate

```bash
# Activate the ADK environment (replace key when it expires)
.venv/bin/orchestrate env activate gsa-hackathon \
  --api-key "<YOUR_ORCHESTRATE_API_KEY>"

# Re-import toolkit (not idempotent — must remove first)
.venv/bin/orchestrate toolkits remove --name gsa_graj_tools
.venv/bin/orchestrate toolkits import -f toolkits/gsa_graj_tools/toolkit_spec.yaml

# Re-import agent (idempotent — updates in place)
.venv/bin/orchestrate agents import -f agents/gsa_graj_agent.agent.yaml
```

---

## Path B — GHCR prebuilt image

Use this path when you don't have ICR write authority — point Code Engine at a
**public image on GitHub Container Registry** (or any public registry).

> Reference: [`deploy/ibm/prebuilt-image/`](prebuilt-image/README.md) — full runbook with `.env.example`, `deploy.sh`, and `smoke-test.sh`.

### B.1 Publish the image to GHCR

```bash
# Build
docker build -t ghcr.io/<GITHUB_USER>/gsa-graj-tools:latest \
  toolkits/gsa_graj_tools/

# Push (GitHub PAT with packages:write scope)
echo "$GITHUB_PAT" | docker login ghcr.io -u <GITHUB_USER> --password-stdin
docker push ghcr.io/<GITHUB_USER>/gsa-graj-tools:latest
```

Then make the package **public** in your GitHub account:
GitHub → Settings → Packages → `gsa-graj-tools` → Make public.

### B.2 Deploy to Code Engine (prebuilt image)

```bash
ibmcloud login --sso
ibmcloud target -r ca-tor -g Default

# Select or create a CE project
ibmcloud ce project select --name gsa-graj-ce   # or create if needed

# Create or update the app
ibmcloud ce app create \
  --name gsa-graj-tools \
  --image ghcr.io/<GITHUB_USER>/gsa-graj-tools:latest \
  --port 8000 \
  --min-scale 1 \
  --cpu 0.25 \
  --memory 500M

# Confirm the URL
ibmcloud ce app get --name gsa-graj-tools
```

### B.3 Smoke-test and register

Same as [A.4](#a4-smoke-test) and [A.5](#a5-register-the-toolkit-and-agent-in-watsonx-orchestrate)
above — the URL will be the same if reusing the same CE project and app name.

---

## Path C — Local stdio toolkit

The lowest-overhead path: ship `server.py` + `requirements.txt` to watsonx
Orchestrate, which runs the server **over stdio inside the Orchestrate runtime**.
No HTTP, no container, no Code Engine.

> Reference: [`deploy/ibm/local-mcp-toolkit/`](local-mcp-toolkit/README.md) — full runbook with `toolkit_local.yaml` and `stage.sh`.

> **Trade-off:** no public endpoint; runs inside Orchestrate with ~100–300 ms
> process-startup cost per call. Fine for a hackathon, not for high-frequency use.

### C.1 Stage a minimal package root

Orchestrate uploads a `package_root`, installs its `requirements.txt`, and runs
`python server.py` over stdio. Avoid uploading the whole repo (causes a 413).

```bash
STAGE=deploy/ibm/local-mcp-toolkit/_stage
rm -rf "${STAGE}" && mkdir -p "${STAGE}"

# Flat copy — no src/ prefix, importable at runtime
cp toolkits/gsa_graj_tools/server.py     "${STAGE}/server.py"
cp toolkits/gsa_graj_tools/db_config.py  "${STAGE}/db_config.py"
cp toolkits/gsa_graj_tools/requirements.txt "${STAGE}/requirements.txt"
```

### C.2 Create the toolkit spec

Create `deploy/ibm/local-mcp-toolkit/toolkit_local.yaml`:

```yaml
spec_version: v1
kind: mcp
name: gsa_graj_tools_local
description: >
  gsa_graj_tools local stdio toolkit — weather, jokes, unit conversion,
  and PostgreSQL tools (connect_sl_db, read_from_sl, write_to_sl,
  aggregate_operational_tbl, count_records).
command: python server.py
env: []
tools:
  - "*"
package_root: deploy/ibm/local-mcp-toolkit/_stage
```

### C.3 Register

```bash
.venv/bin/orchestrate env activate gsa-hackathon \
  --api-key "<YOUR_ORCHESTRATE_API_KEY>"

# Remove if previously imported under this name
.venv/bin/orchestrate toolkits remove --name gsa_graj_tools_local || true

.venv/bin/orchestrate toolkits import -f deploy/ibm/local-mcp-toolkit/toolkit_local.yaml

# Verify
.venv/bin/orchestrate toolkits list
```

---

## gsa_graj_viz Toolkit — Deploy / Register

The visualization toolkit is deployed as a separate Code Engine app alongside
`gsa_graj_tools`. It reuses the same ICR namespace, CE project, and PostgreSQL
secret.

| Item | Value |
|---|---|
| CE app name | `gsa-graj-viz` |
| Image | `ca.icr.io/gsa-graj-wxo/gsa-graj-viz:latest` |
| Public URL | `https://gsa-graj-viz.2h721savdmhn.ca-tor.codeengine.appdomain.cloud` |
| MCP endpoint | `…/mcp` |
| Health endpoint | `…/health` |
| Toolkit name in wxO | `gsa_graj_viz` |
| Agent name in wxO | `gsa_graj_viz_agent` |

### V.1 Build & push the image

```bash
podman build -t ca.icr.io/gsa-graj-wxo/gsa-graj-viz:latest \
  toolkits/gsa_graj_viz/

ibmcloud cr login
podman push ca.icr.io/gsa-graj-wxo/gsa-graj-viz:latest
```

### V.2 Deploy to Code Engine

```bash
ibmcloud ce project select --name gsa-graj-ce

# Create (first time):
ibmcloud ce app create \
  --name gsa-graj-viz \
  --image ca.icr.io/gsa-graj-wxo/gsa-graj-viz:latest \
  --registry-secret icr-secret \
  --port 8000 \
  --min-scale 1 \
  --cpu 0.25 \
  --memory 500M \
  --env-from-secret postgres-secret

# Update (redeploy):
ibmcloud ce app update \
  --name gsa-graj-viz \
  --image ca.icr.io/gsa-graj-wxo/gsa-graj-viz:latest

ibmcloud ce app get --name gsa-graj-viz
```

> **Optional viz-specific env vars** (set via `--env` or a separate CE secret):
> - `VIZ_ROW_LIMIT` — max rows per query (default `2000`)
> - `VIZ_QUERY_TIMEOUT_MS` — server-side statement timeout ms (default `30000`)
> - `VIZ_ALLOWED_SCHEMAS` — comma-separated schemas (default `public`)

### V.3 Smoke-test

```bash
BASE=https://gsa-graj-viz.2h721savdmhn.ca-tor.codeengine.appdomain.cloud
curl -sf "${BASE}/health"   # → {"status":"ok","service":"gsa_graj_viz"}
```

### V.4 Register in watsonx Orchestrate

```bash
.venv/bin/orchestrate env activate gsa-hackathon --api-key "<YOUR_ORCHESTRATE_API_KEY>"

# Toolkit (not idempotent — remove first if already imported)
.venv/bin/orchestrate toolkits remove --name gsa_graj_viz || true
.venv/bin/orchestrate toolkits import -f toolkits/gsa_graj_viz/toolkit_spec.yaml

# Agent (idempotent — updates in place)
.venv/bin/orchestrate agents import -f agents/gsa_graj_viz_agent.agent.yaml

# Verify
.venv/bin/orchestrate toolkits list
.venv/bin/orchestrate agents list
```

---

## Teardown

```bash
# Remove from watsonx Orchestrate
.venv/bin/orchestrate toolkits remove --name gsa_graj_tools
.venv/bin/orchestrate toolkits remove --name gsa_graj_viz
.venv/bin/orchestrate agents remove --name gsa_graj_agent --kind native
.venv/bin/orchestrate agents remove --name gsa_graj_viz_agent --kind native

# Remove Code Engine apps (optional — leaves project intact)
ibmcloud ce project select --name gsa-graj-ce
ibmcloud ce app delete --name gsa-graj-tools --force
ibmcloud ce app delete --name gsa-graj-viz --force

# Remove ICR images (optional)
ibmcloud cr image-rm ca.icr.io/gsa-graj-wxo/gsa-graj-tools:latest
ibmcloud cr image-rm ca.icr.io/gsa-graj-wxo/gsa-graj-viz:latest
```

---

## Environment variables reference

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes (prod) | Full Neon PostgreSQL connection string with `sslmode=require` |
| `PG_HOST` / `PG_PORT` / `PG_DB` / `PG_USER` / `PG_PASS` | Yes (local dev) | Individual PG connection params (fallback when `DATABASE_URL` not set) |
| `PGSSL` | No | Set to `true` to force SSL when using individual PG vars |
| `PGSSLROOTCERT` | No | Path to custom CA cert file for `DATABASE_URL` SSL |
| `PORT` | Injected by CE | CE/Knative injects this automatically — do **not** set as a CE literal env var |

Credentials are stored in the Code Engine secret `postgres-secret` and
referenced via `--env-from-secret postgres-secret` on the app.

Additional viz-specific variables for `gsa_graj_viz`:

| Variable | Required | Description |
|---|---|---|
| `VIZ_ROW_LIMIT` | No | Max rows returned per query (default `2000`) |
| `VIZ_QUERY_TIMEOUT_MS` | No | Server-side statement timeout in ms (default `30000`) |
| `VIZ_ALLOWED_SCHEMAS` | No | Comma-separated schemas to expose (default `public`) |

---

## Toolkit spec reference

[`toolkits/gsa_graj_tools/toolkit_spec.yaml`](../../toolkits/gsa_graj_tools/toolkit_spec.yaml):

```yaml
spec_version: v1
kind: mcp
name: gsa_graj_tools
description: >
  General-purpose toolkit: weather, jokes, unit conversion, and PostgreSQL
  database tools (connect_sl_db, read_from_sl, write_to_sl,
  aggregate_operational_tbl, count_records).
url: https://gsa-graj-tools.2h721savdmhn.ca-tor.codeengine.appdomain.cloud/mcp
transport: streamable_http
tools:
  - "*"
```

[`toolkits/gsa_graj_viz/toolkit_spec.yaml`](../../toolkits/gsa_graj_viz/toolkit_spec.yaml):

```yaml
spec_version: v1
kind: mcp
name: gsa_graj_viz
description: >
  Read-only visualization toolkit: discovers PostgreSQL schemas, validates and
  executes SELECT queries, and returns interactive HTML charts (bar, line,
  scatter, histogram, heatmap, table) plus CSV exports.
url: https://gsa-graj-viz.2h721savdmhn.ca-tor.codeengine.appdomain.cloud/mcp
transport: streamable_http
tools:
  - "*"
```

---

## Troubleshooting

### Code Engine app `Not Ready` / `ErrImagePull`

The ICR registry secret has expired. Follow [A.2](#a2-rotate-the-icr-registry-secret-when-it-expires)
to create a new IAM API key and replace `icr-secret`.

### `orchestrate env activate` fails — "API key is disabled"

Your IBM Cloud IAM key was deactivated. Generate a new one at
[cloud.ibm.com/iam/apikeys](https://cloud.ibm.com/iam/apikeys).

### `orchestrate env activate` fails — "Key secret is not valid"

Your MCSP v2 `ApiKey-...` was rotated or created by another session. Regenerate
it in the watsonx Orchestrate UI (Profile → API Keys → delete old → create new).

### `orchestrate toolkits import` times out

The gateway probes the `/mcp` endpoint at import time. If the CE app is `Not
Ready`, the import will time out. Fix the app first (check `ibmcloud ce app get
--name gsa-graj-tools`), then retry the import.

### `PORT is a reserved environment variable`

Code Engine (Knative) owns `PORT`. Do not pass `--env PORT=…` to `ce app create`
or `ce app update` — it will be rejected. The `ENV PORT=8000` in the Dockerfile
is only for local container runs and is overridden at runtime by CE.

### TLS interception on a GSA-managed network

If `orchestrate env activate` fails with
`SSLCertVerificationError: unable to get local issuer certificate`, a TLS proxy
(e.g. Zscaler) is re-signing HTTPS with a private CA. Fix:

```bash
# 1. Export the proxy root from the macOS System keychain
security find-certificate -a -c "Zscaler" -p /Library/Keychains/System.keychain \
  > /tmp/proxy-roots.pem

# 2. Merge with certifi
CERTIFI="$(python -c 'import certifi; print(certifi.where())')"
cat "$CERTIFI" /tmp/proxy-roots.pem > /tmp/wxo-ca-bundle.pem

# 3. Export in this shell before running any orchestrate command
export SSL_CERT_FILE=/tmp/wxo-ca-bundle.pem
export REQUESTS_CA_BUNDLE=/tmp/wxo-ca-bundle.pem
```

---

## Path D — Build-from-Git (Code Engine)

Code Engine clones this Git repo server-side, builds the Dockerfile, pushes the
image to ICR, and deploys — **no local Docker or podman required**.

> Full runbook: [`deploy/ibm/code-engine-git-build/README.md`](code-engine-git-build/README.md)

```bash
cp deploy/ibm/code-engine-git-build/.env.example \
   deploy/ibm/code-engine-git-build/.env
# Edit .env — set GIT_REPO_URL to your GitHub fork

set -a; source deploy/ibm/code-engine-git-build/.env; set +a
export IBMCLOUD_API_KEY="<your-iam-api-key>"
bash deploy/ibm/code-engine-git-build/deploy-build-from-git.sh
```

---

## Files in this directory

| File / Directory | Purpose |
|---|---|
| `README.md` | This top-level runbook (paths A, B, C, D) |
| `local-mcp-toolkit/` | **Path C** — stdio local toolkit; `toolkit_local.yaml`, `stage.sh`, `README.md` |
| `prebuilt-image/` | **Path B** — GHCR prebuilt image; `.env.example`, `deploy.sh`, `smoke-test.sh`, `README.md` |
| `code-engine-git-build/` | **Path D** — CE build-from-Git; `.env.example`, `deploy-build-from-git.sh`, `smoke-test.sh`, `README.md` |
