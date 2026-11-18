- WORKFLOW — Prebuilt Image Deployment (Path B)

Deploy `gsa_graj_tools` and `gsa_graj_viz` to IBM Code Engine using a
**pre-built public image** from GitHub Container Registry (GHCR).  No local
Docker socket or ICR write authority required — you build the image once,
publish it publicly to GHCR, and then point Code Engine at it.

> **Which path is this?**  Path B — GHCR prebuilt image.  Other paths are in
> the sibling [`../README.md`](../README.md):
>
> - **Path A** — ICR prebuilt image (live setup, `podman build` locally, ICR push)
> - **Path C** — Local stdio toolkit (no cloud deploy)
> - **Path D** — Build-from-Git on Code Engine (server-side build, ICR auth)

---

## When to use this path

| Situation | Use Path B? |
|---|---|
| No ICR write authority | ✓ Yes — GHCR is public, no IBM auth needed |
| No local Docker / podman | ✗ No — still needs a build host (CI or local) |
| Want server-side build (no local Docker at all) | Use Path D instead |

---

## Project values

| Setting | Value |
|---|---|
| IBM Cloud region | `ca-tor` |
| Resource group | `Default` |
| Code Engine project | `gsa-graj-ce` |
| `gsa_graj_tools` app | `gsa-graj-tools` |
| `gsa_graj_viz` app | `gsa-graj-viz` |
| Tools Dockerfile | `toolkits/gsa_graj_tools/Dockerfile` |
| Viz Dockerfile | `toolkits/gsa_graj_viz/Dockerfile` |
| Live tools URL | `https://gsa-graj-tools.2h721savdmhn.ca-tor.codeengine.appdomain.cloud` |
| Live viz URL | `https://gsa-graj-viz.2h721savdmhn.ca-tor.codeengine.appdomain.cloud` |

---

## Prerequisites

### IBM Cloud CLI

```bash
ibmcloud version
ibmcloud plugin install code-engine     # if not already installed
```

### GitHub PAT with `packages:write`

Create a classic PAT at **GitHub → Settings → Developer settings → Personal
access tokens → Tokens (classic)** with scope `write:packages` (which includes
`read:packages`).

---

## Part 1 — Build & publish images to GHCR

Replace `<GITHUB_USER>` with your GitHub username or org throughout.

### 1.1 Build both images

```bash
# From the repo root
docker build -t ghcr.io/<GITHUB_USER>/gsa-graj-tools:latest \
  toolkits/gsa_graj_tools/

docker build -t ghcr.io/<GITHUB_USER>/gsa-graj-viz:latest \
  toolkits/gsa_graj_viz/
```

> **PORT note:** The `ENV PORT=8000` line in each Dockerfile is for local
> testing only.  Code Engine (Knative) injects `PORT` at runtime and overrides
> it.  Do **not** set `--env PORT=…` on the CE app — it will be rejected.

### 1.2 Push to GHCR

```bash
echo "$GITHUB_PAT" | docker login ghcr.io -u <GITHUB_USER> --password-stdin

docker push ghcr.io/<GITHUB_USER>/gsa-graj-tools:latest
docker push ghcr.io/<GITHUB_USER>/gsa-graj-viz:latest
```

### 1.3 Make the packages public

Go to **GitHub → Your profile → Packages**, open each package, and set
visibility to **Public** so Code Engine can pull without credentials.

---

## Part 2 — Configure and deploy to Code Engine

### 2.1 Set up the env file

```bash
cp deploy/ibm/prebuilt-image/.env.example deploy/ibm/prebuilt-image/.env
# Edit .env — set TOOLS_IMAGE and VIZ_IMAGE to your GHCR image references
set -a; source deploy/ibm/prebuilt-image/.env; set +a
```

### 2.2 Ensure the postgres-secret CE secret exists

```bash
ibmcloud login --sso
ibmcloud target -r ca-tor -g Default
ibmcloud ce project select --name gsa-graj-ce

# Option 1 — full DATABASE_URL
ibmcloud ce secret create --name postgres-secret \
  --from-literal DATABASE_URL="postgresql://user:pass@host:port/db?sslmode=require"

# Option 2 — individual PG_* vars
ibmcloud ce secret create --name postgres-secret \
  --from-literal PG_HOST=... \
  --from-literal PG_PORT=5432 \
  --from-literal PG_DB=wxodb \
  --from-literal PG_USER=... \
  --from-literal PG_PASS=...
```

Skip this step if the secret already exists (e.g. from a previous deploy).

### 2.3 Deploy

```bash
set -a; source deploy/ibm/prebuilt-image/.env; set +a
bash deploy/ibm/prebuilt-image/deploy.sh
```

The script is **idempotent** — safe to re-run.  On each run it:

1. Targets `ca-tor` / `Default`.
2. Selects the `gsa-graj-ce` CE project.
3. Creates the CE app if it doesn't exist, or updates the image if it does.
4. Prints the public URL for each app.

> No `--registry-secret` is needed because the GHCR images are public.

---

## Part 3 — Smoke-test

```bash
# Test both apps
bash deploy/ibm/prebuilt-image/smoke-test.sh

# Test one app directly
bash deploy/ibm/prebuilt-image/smoke-test.sh \
  https://gsa-graj-tools.2h721savdmhn.ca-tor.codeengine.appdomain.cloud
```

Expected output:

```
── Checking: gsa-graj-tools
   PASS: /health → HTTP 200
   PASS: /mcp is reachable and speaking JSON-RPC.
── Checking: gsa-graj-viz
   PASS: /health → HTTP 200
   PASS: /mcp is reachable and speaking JSON-RPC.
──────────────────────────────────────────
  Results: 4 passed / 0 failed
──────────────────────────────────────────
```

> A `Missing session ID` response from `/mcp` is **expected** for a raw curl
> request — watsonx Orchestrate performs the full `initialize` handshake.

---

## Part 4 — Re-register in watsonx Orchestrate

Toolkit imports are **not idempotent** — always remove before re-importing.

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

orchestrate toolkits list
orchestrate agents list
```

> If the toolkit spec files still reference the old Code Engine URL, update the
> `url:` field in each `toolkit_spec.yaml` to match the new app URL before
> importing.

---

## Redeploy after a code change

```bash
# Rebuild and push
docker build -t ghcr.io/<GITHUB_USER>/gsa-graj-tools:latest toolkits/gsa_graj_tools/
docker push ghcr.io/<GITHUB_USER>/gsa-graj-tools:latest

# Update the CE app (pulls the new image)
set -a; source deploy/ibm/prebuilt-image/.env; set +a
bash deploy/ibm/prebuilt-image/deploy.sh

# Re-register
orchestrate toolkits remove --name gsa_graj_tools
orchestrate toolkits import -f toolkits/gsa_graj_tools/toolkit_spec.yaml
```

---

## Teardown

```bash
ibmcloud ce project select --name gsa-graj-ce
ibmcloud ce app delete --name gsa-graj-tools --force
ibmcloud ce app delete --name gsa-graj-viz   --force

# Optionally remove the CE project
# ibmcloud ce project delete --name gsa-graj-ce --force

# Deregister from watsonx Orchestrate
orchestrate toolkits remove --name gsa_graj_tools
orchestrate toolkits remove --name gsa_graj_viz
orchestrate agents remove --name gsa_graj_agent     --kind native
orchestrate agents remove --name gsa_graj_viz_agent --kind native
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ErrImagePull` / app `Not Ready` | GHCR package is private | Make both packages public (GitHub → Packages → Visibility) |
| `PORT is a reserved environment variable` | Tried `--env PORT=…` | Do not set PORT — CE / Knative injects it automatically |
| Toolkit import times out | CE app not `Ready` at import time | Wait for app Ready (`ibmcloud ce app get`), retry import |
| `orchestrate env activate` fails — "Key secret is not valid" | MCSP v2 key rotated | Regenerate in wxO UI → Profile → API Keys |

---

## Files in this directory

| File | Purpose |
|---|---|
| `.env.example` | Deployment coordinates — copy to `.env`, fill in image references |
| `deploy.sh` | Idempotent create-or-update CE app for both GHCR images |
| `smoke-test.sh` | Live `/health` + `/mcp` verification for both apps |
| `README.md` | This runbook |
