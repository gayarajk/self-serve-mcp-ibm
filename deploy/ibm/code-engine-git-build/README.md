# GSA GRAJ — Code Engine Build-from-Git Deployment

Deploy the `gsa_graj_tools` and `gsa_graj_viz` MCP servers to **IBM Cloud Code
Engine** by building **directly from this Git repo** — Code Engine clones the
repo, builds the `Dockerfile` **server-side**, pushes the resulting image to your
IBM Container Registry (ICR) namespace, and deploys it.
**No local Docker or podman required.**

> **Which path is this?** Path D — build-from-Git. Code Engine pulls, builds,
> and deploys entirely on IBM Cloud. Requires ICR write authority.
>
> Other deployment paths are in the sibling [`../README.md`](../README.md):
> - **Path A** — ICR prebuilt image (current live setup, local `podman build`)
> - **Path B** — GHCR prebuilt image (public image, no ICR auth needed)
> - **Path C** — Local stdio toolkit (no cloud deploy)

---

## How it differs from Path A (prebuilt image)

| | Path D — this kit | Path A — prebuilt image |
|---|---|---|
| Local Docker / podman | **Not needed** | Required for build + push |
| Build location | **IBM Code Engine server-side** | Local machine |
| Image registry | Pushed to **your ICR namespace** | Pushed to ICR (same) |
| Trigger rebuild | Re-run script (or `ce app update`) | `podman build && push && app update` |
| Extra IBM authority | ICR namespace + push API key | Same |

---

## Project values (this workspace)

| Setting | Value |
|---|---|
| IBM Cloud region | `ca-tor` |
| Resource group | `Default` |
| Code Engine project | `gsa-graj-ce` |
| ICR region | `ca-tor` → `ca.icr.io` |
| ICR namespace | `gsa-graj-wxo` |
| `gsa_graj_tools` app | `gsa-graj-tools` · context: `toolkits/gsa_graj_tools/` |
| `gsa_graj_viz` app | `gsa-graj-viz` · context: `toolkits/gsa_graj_viz/` |
| Live tools URL | `https://gsa-graj-tools.2h721savdmhn.ca-tor.codeengine.appdomain.cloud` |
| Live viz URL | `https://gsa-graj-viz.2h721savdmhn.ca-tor.codeengine.appdomain.cloud` |

---

## Part 1 — Prerequisites

### 1.1 IBM Cloud CLI + plugins

```bash
ibmcloud version
ibmcloud plugin install code-engine       # already installed if using Path A
ibmcloud plugin install container-registry
```

### 1.2 Log in

```bash
ibmcloud login --sso           # or --apikey "$IBM_CLOUD_API_KEY"
ibmcloud target                # confirm: ca-tor / Default
```

### 1.3 Configure the env file

```bash
cp deploy/ibm/code-engine-git-build/.env.example \
   deploy/ibm/code-engine-git-build/.env

# Edit .env — set GIT_REPO_URL to your GitHub fork (must be public)
set -a; source deploy/ibm/code-engine-git-build/.env; set +a
```

### 1.4 Provide an IBM Cloud API key for the ICR push secret

```bash
export IBMCLOUD_API_KEY="$(ibmcloud iam api-key-create ce-icr-push \
    -d 'Code Engine ICR push' --output json | jq -r .apikey)"
```

If `IBMCLOUD_API_KEY` is unset the script prompts (input hidden) and never
writes it to disk. Delete when finished:

```bash
ibmcloud iam api-key-delete ce-icr-push
```

### 1.5 Ensure the postgres-secret exists in Code Engine

Both apps require a `postgres-secret` CE secret at runtime:

```bash
ibmcloud ce project select --name gsa-graj-ce

# Option 1 — full DATABASE_URL
ibmcloud ce secret create --name postgres-secret \
  --from-literal DATABASE_URL="postgresql://user:pass@host:port/db?sslmode=require"

# Option 2 — individual PG_* vars
ibmcloud ce secret create --name postgres-secret \
  --from-literal PG_HOST=... \
  --from-literal PG_PORT=5432 \
  --from-literal PG_DB=wxodb \
  --from-literal PG_USER=wxouser \
  --from-literal PG_PASS=...
```

---

## Part 2 — Deploy

### Deploy both apps (default)

```bash
set -a; source deploy/ibm/code-engine-git-build/.env; set +a
export IBMCLOUD_API_KEY="<your-iam-api-key>"
bash deploy/ibm/code-engine-git-build/deploy-build-from-git.sh
```

The script is **idempotent** — safe to re-run. On each run it:

1. Targets `ca-tor` / `Default`.
2. Ensures `gsa-graj-wxo` ICR namespace exists (reuses if present).
3. Creates / updates the `icr-push-secret` CE registry secret.
4. Selects the `gsa-graj-ce` CE project.
5. Runs `ce app create/update --build-source …` for each app — Code Engine
   clones, builds, pushes to ICR, and deploys.
6. Prints the public URLs and ICR image references.

### Deploy one app only

```bash
set -a; source deploy/ibm/code-engine-git-build/.env; set +a
export IBMCLOUD_API_KEY="<your-iam-api-key>"

# gsa_graj_viz only:
export CE_APP_NAME=gsa-graj-viz
export GIT_CONTEXT_DIR=toolkits/gsa_graj_viz
export GIT_DOCKERFILE=toolkits/gsa_graj_viz/Dockerfile
bash deploy/ibm/code-engine-git-build/deploy-build-from-git.sh
```

---

## Part 3 — Smoke-test

```bash
# Test both apps
bash deploy/ibm/code-engine-git-build/smoke-test.sh

# Test one app
bash deploy/ibm/code-engine-git-build/smoke-test.sh \
  https://gsa-graj-tools.2h721savdmhn.ca-tor.codeengine.appdomain.cloud
```

Expected output:

```
PASS: health check HTTP 200
PASS: /mcp is reachable and speaking JSON-RPC.
```

> A `Missing session ID` response from `/mcp` is **expected** for a raw curl
> request — watsonx Orchestrate performs the full `initialize` handshake.

Confirm the image landed in ICR:

```bash
ibmcloud cr region-set ca-tor
ibmcloud cr images --restrict gsa-graj-wxo
```

---

## Part 4 — Re-register in watsonx Orchestrate

After any rebuild, the toolkit import must be re-run (toolkits are not idempotent):

```bash
source .venv/bin/activate
orchestrate env activate gsa-hackathon --api-key "<WXO_API_KEY>"

orchestrate toolkits remove --name gsa_graj_tools || true
orchestrate toolkits remove --name gsa_graj_viz   || true
orchestrate toolkits import -f toolkits/gsa_graj_tools/toolkit_spec.yaml
orchestrate toolkits import -f toolkits/gsa_graj_viz/toolkit_spec.yaml

orchestrate agents import -f agents/gsa_graj_agent.agent.yaml
orchestrate agents import -f agents/gsa_graj_viz_agent.agent.yaml
orchestrate agents import -f agents/gsa_graj_eval_agent.agent.yaml
```

---

## Teardown

```bash
set -a; source deploy/ibm/code-engine-git-build/.env; set +a
ibmcloud ce project select --name gsa-graj-ce

ibmcloud ce app delete --name gsa-graj-tools --force
ibmcloud ce app delete --name gsa-graj-viz   --force

# Optional — remove the registry secret and project
# ibmcloud ce registry delete --name icr-push-secret --force
# ibmcloud ce project delete  --name gsa-graj-ce --force

# Optional — remove ICR images
ibmcloud cr region-set ca-tor
# ibmcloud cr image-rm ca.icr.io/gsa-graj-wxo/gsa-graj-tools:latest
# ibmcloud cr image-rm ca.icr.io/gsa-graj-wxo/gsa-graj-viz:latest

# Rotate the ICR push API key
# ibmcloud iam api-key-delete ce-icr-push
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `FATAL: not logged in` | `ibmcloud login` not done | `ibmcloud login --sso` |
| `namespace-add` permission denied | Trial account lacks ICR create | Reuse existing namespace (`ibmcloud cr namespace-list`) or use Path A/B |
| Build fails in Code Engine | Dockerfile error or bad context dir | Check `ibmcloud ce buildrun logs --name <app>-build-*` |
| App `Not Ready` after build | First build can take 3–5 min | Wait and retry: `ibmcloud ce app get --name gsa-graj-tools` |
| `PORT is a reserved environment variable` | Tried to set `--env PORT=…` | Do not set PORT — CE / Knative injects it automatically |
| Toolkit import times out | CE app not `Ready` at import time | Wait for app to be Ready, then retry import |

---

## Files in this directory

| File | Purpose |
|---|---|
| `.env.example` | Deployment coordinates (copy to `.env`, no secrets) |
| `deploy-build-from-git.sh` | Idempotent build-from-Git deploy for both apps |
| `smoke-test.sh` | Live `/health` + `/mcp` verification |
| `README.md` | This runbook |
