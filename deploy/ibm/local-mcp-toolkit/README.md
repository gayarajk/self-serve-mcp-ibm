# GSA GRAJ — Local stdio Toolkit (Path C)

Deploy `gsa_graj_tools` as a **local stdio toolkit** that runs **inside the
watsonx Orchestrate runtime** — no Code Engine, no container, no HTTP server.

> **Which path is this?**  Path C — stdio local toolkit.  Other paths are in
> the sibling [`../README.md`](../README.md):
>
> - **Path A** — ICR prebuilt image (live setup, `podman build` locally)
> - **Path B** — GHCR prebuilt image (public image, no ICR auth)
> - **Path D** — Build-from-Git on Code Engine (no local Docker)

---

## Trade-offs vs. the Code Engine paths

| | Path C — stdio (this) | Path A/D — Code Engine |
|---|---|---|
| Infrastructure | None | Code Engine project + ICR |
| Cold-start | ~100–300 ms per call (subprocess) | Near-zero (always-warm app) |
| File upload (WXOFile) | ✗ Not available in stdio mode | ✓ Available |
| Secrets | Injected via a `key_value` connection | CE secret `postgres-secret` |
| Best for | Quick registration / hackathon demos | Production / high-frequency |

> **Note:** `gsa_graj_load_excel_to_postgres` uses `WXOFile` (chat file upload)
> and is a **standalone Python tool**, not part of this MCP server.  It is not
> affected by the transport choice here.

---

## Prerequisites

```bash
# Orchestrate ADK
pip install --upgrade ibm-watsonx-orchestrate
orchestrate --version

# Logged into the right Orchestrate environment
orchestrate env activate gsa-hackathon --api-key "<YOUR_ORCHESTRATE_API_KEY>"
```

---

## Step 1 — Stage the package root

Orchestrate uploads a `package_root` directory, installs its `requirements.txt`,
and runs `python server.py` over stdio.  Uploading the whole repo causes a 413
error — `stage.sh` copies only what the server needs.

```bash
bash deploy/ibm/local-mcp-toolkit/stage.sh
```

This creates `deploy/ibm/local-mcp-toolkit/_stage/` with three files:

```
_stage/
  server.py         ← gsa_graj_tools MCP server
  db_config.py      ← PostgreSQL connection helper
  requirements.txt  ← fastmcp, pg8000, httpx, openpyxl, python-dotenv
```

---

## Step 2 — Provide database credentials via a key_value connection

The server reads `PG_HOST`, `PG_PORT`, `PG_DB`, `PG_USER`, `PG_PASS`
(or `DATABASE_URL`) from environment variables.  In stdio mode these must come
from a `key_value` connection in watsonx Orchestrate.

```bash
# Create the connection (once)
orchestrate connections create --name postgres-kv --kind key_value

# Set the credentials
orchestrate connections credentials set --name postgres-kv \
  --key PG_HOST --value "<neon-host>" \
  --key PG_PORT --value "5432" \
  --key PG_DB   --value "wxodb" \
  --key PG_USER --value "<user>" \
  --key PG_PASS --value "<password>"
```

Then reference the connection in `toolkit_local.yaml` by adding:

```yaml
app_id: postgres-kv
```

---

## Step 3 — Import the toolkit

```bash
# Remove any previously imported version under this name
orchestrate toolkits remove --name gsa_graj_tools_local || true

# Import (uploads _stage/ and registers over stdio)
orchestrate toolkits import -f deploy/ibm/local-mcp-toolkit/toolkit_local.yaml

# Verify
orchestrate toolkits list
```

---

## Step 4 — Attach to an agent

Add `gsa_graj_tools_local` to any agent's `tools` list in its YAML and
re-import:

```yaml
# agents/gsa_graj_agent.agent.yaml  — tools section
tools:
  - gsa_graj_tools_local/gsa_graj_current_weather
  - gsa_graj_tools_local/gsa_graj_read_from_sl
  # … other tools
```

```bash
orchestrate agents import -f agents/gsa_graj_agent.agent.yaml
```

---

## Re-stage after code changes

Whenever `toolkits/gsa_graj_tools/server.py` or `db_config.py` changes:

```bash
bash deploy/ibm/local-mcp-toolkit/stage.sh

orchestrate toolkits remove --name gsa_graj_tools_local
orchestrate toolkits import -f deploy/ibm/local-mcp-toolkit/toolkit_local.yaml
```

Toolkit imports are **not idempotent** — always remove before re-importing.

---

## Teardown

```bash
orchestrate toolkits remove --name gsa_graj_tools_local
```

---

## Files in this directory

| File | Purpose |
|---|---|
| `toolkit_local.yaml` | Toolkit spec pointing at `_stage/` |
| `stage.sh` | Copies `server.py`, `db_config.py`, `requirements.txt` into `_stage/` |
| `README.md` | This runbook |
| `_stage/` | Generated at run time by `stage.sh` — not committed to Git |
