---
name: mcp-builder
description: >
  Guide for building, extending, or debugging the gsa_graj_tools MCP server
  in this workspace — adding new tools to server.py, wiring db_config,
  updating toolkit_spec.yaml, deploying to IBM Code Engine, and re-importing
  into watsonx Orchestrate. Activate for phrases like "add a new tool",
  "extend the MCP server", "new gsa_graj tool", "deploy the toolkit",
  "re-import the toolkit", or "update the MCP server".
---

# MCP Server Development Guide — gsa_graj_tools

This skill covers adding tools to, testing, and deploying the
`gsa_graj_tools` MCP toolkit that is already live in this workspace.

---

## Project Layout

```
wxo-agentic-workflow/
├── toolkits/
│   └── gsa_graj_tools/
│       ├── server.py          ← ALL tools live here (single-file server)
│       ├── db_config.py       ← PostgreSQL connection helper (shared)
│       ├── requirements.txt   ← fastmcp, requests, openpyxl, pg8000
│       ├── Dockerfile         ← python:3.12-slim, ENV PORT=8000 (CE injects PORT)
│       └── toolkit_spec.yaml  ← watsonx Orchestrate remote MCP spec
├── tools/
│   └── gsa_graj_bulk_excel_to_sl.py   ← standalone WXOFile upload tool
├── agents/
│   └── gsa_graj_agent.agent.yaml      ← agent spec (tools list here too)
└── eval/phoenix/                      ← LLM-as-judge evaluation harness
```

---

## Phase 1 — Add a New Tool to server.py

### 1.1  Understand the existing pattern

Every tool in [`toolkits/gsa_graj_tools/server.py`](toolkits/gsa_graj_tools/server.py)
follows this exact shape:

```python
@mcp.tool()
def gsa_graj_<tool_name>(
    param_one: str,
    param_two: Optional[int] = None,
) -> str:
    """One-sentence summary.

    Longer description if needed.

    Args:
        param_one: What it is, e.g. 'operational_tbl'.
        param_two: Optional filter. Omit to return everything.
    """
    # implementation — always return a plain str
    ...
```

**Rules already established in this project:**
- Prefix: always `gsa_graj_`
- Return type: always `str` (plain text or `json.dumps(...)`)
- DB access: always via `con = _get_conn()` / `finally: con.close()`
- Logging: `print("...", file=sys.stderr)` only — stdout is the MCP wire
- `Optional` is imported from `typing` at the top of the file

### 1.2  Imports already available in server.py

```python
import json          # json.dumps for structured output
import os            # os.environ
import sys           # sys.stderr logging
from typing import Optional

import requests      # HTTP calls (weather, joke tools)
from fastmcp import FastMCP
from db_config import get_conn as _get_conn, PG_DB as _PG_DB, PG_HOST as _PG_HOST
```

If a new tool needs an additional library, add it to
[`toolkits/gsa_graj_tools/requirements.txt`](toolkits/gsa_graj_tools/requirements.txt).

### 1.3  Database access pattern (copy-paste template)

```python
@mcp.tool()
def gsa_graj_<tool_name>(table_name: str, where_clause: Optional[str] = None) -> str:
    """Short description of what this tool does.

    Args:
        table_name: Table to query, e.g. 'operational_tbl'.
        where_clause: SQL filter without WHERE keyword. Omit for all rows.
    """
    con = _get_conn()
    try:
        # run your SQL here — pg8000 native API
        rows = con.run(f'SELECT * FROM "{table_name}" LIMIT 10')
        result = [dict(zip(["col1", "col2"], r)) for r in rows]
    finally:
        con.close()   # always close in finally

    return json.dumps(result, indent=2, default=str)
```

**DB connection resolution order** (from `db_config.py`):
1. `DATABASE_URL` env var — full connection string (Neon PostgreSQL / IBM ICD)
2. `PG_HOST` / `PG_PORT` / `PG_DB` / `PG_USER` / `PG_PASS` — local dev fallbacks
3. Set `PGSSL=true` to force SSL with individual env vars
4. Set `PGSSLROOTCERT=/path/to/cert` for custom CA (IBM ICD)

### 1.4  External HTTP call pattern (weather / joke style)

```python
@mcp.tool()
def gsa_graj_<tool_name>(query: str) -> str:
    """Call an external public API and return a formatted result.

    Args:
        query: Search term or parameter, e.g. 'Toronto'.
    """
    url = f"https://api.example.com/endpoint?q={requests.utils.quote(query)}"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()
    # Extract what you need and return a human-readable string
    return f"Result for {query}: {data['key']}"
```

### 1.5  Register the tool in the health route

After adding the function, also add its name to the `tools` list inside
`_add_health_route()` near the bottom of `server.py`:

```python
"tools": [
    "gsa_graj_current_weather",
    ...
    "gsa_graj_<your_new_tool>",   # ← add here
],
```

---

## Phase 2 — Wire the Tool into the Agent

Open [`agents/gsa_graj_agent.agent.yaml`](agents/gsa_graj_agent.agent.yaml).

### 2.1  Add to the tools list

```yaml
tools:
  - gsa_graj_tools:gsa_graj_current_weather
  - gsa_graj_tools:gsa_graj_programming_joke
  - gsa_graj_tools:gsa_graj_unit_converter
  - gsa_graj_tools:gsa_graj_connect_sl_db
  - gsa_graj_tools:gsa_graj_read_from_sl
  - gsa_graj_tools:gsa_graj_write_to_sl
  - gsa_graj_tools:gsa_graj_aggregate_operational_tbl
  - gsa_graj_tools:gsa_graj_count_records
  - gsa_graj_tools:gsa_graj_<your_new_tool>   # ← add here
  - gsa_graj_bulk_excel_to_sl                  # standalone python tool (no toolkit prefix)
```

### 2.2  Add a routing instruction to the instructions block

Follow the established style — one header per tool category, concrete trigger
phrases, parameter names, and examples:

```yaml
  ### <What the tool does>
  - User asks "<trigger phrase>" → MUST call gsa_graj_<tool_name>.
  - Parameters:
    - param_one: description
    - param_two: description (default: X)
  - Examples:
    - "<example question>" → param_one='value'
  - NEVER answer this category of question from memory.
```

---

## Phase 3 — Local Test Before Deploy

### 3.1  Syntax check

```bash
cd toolkits/gsa_graj_tools
python -m py_compile server.py && echo "OK"
```

### 3.2  Run the server locally (stdio mode)

```bash
cd toolkits/gsa_graj_tools
TRANSPORT=stdio python server.py
```

The server prints `gsa_graj_tools MCP server starting (PostgreSQL backend)` to
stderr and then waits for JSON-RPC messages on stdin.

### 3.3  Inspect with MCP Inspector

```bash
cd toolkits/gsa_graj_tools
npx @modelcontextprotocol/inspector python server.py
# Opens http://localhost:5173 — browse tools, call them manually
```

### 3.4  Test DB connectivity locally

Ensure your `.env` or environment has:

```bash
export PG_HOST="ep-weathered-mountain-bc6svyf6-pooler.c-16.us-east-1.aws.neon.tech"
export PG_PORT=5432
export PG_DB=neondb
export PG_USER=<user>
export PG_PASS=<password>
export PGSSL=true
```

Or use the full `DATABASE_URL` form:

```bash
export DATABASE_URL="postgresql://<user>:<pass>@<host>:5432/neondb?sslmode=verify-full"
```

---

## Phase 4 — Deploy to IBM Code Engine

The server runs as a container on Code Engine behind the URL registered in
[`toolkit_spec.yaml`](toolkits/gsa_graj_tools/toolkit_spec.yaml):

```
https://gsa-graj-tools.2h721savdmhn.ca-tor.codeengine.appdomain.cloud/mcp
```

### 4.1  Build and push the image

```bash
# From workspace root
IMAGE="icr.io/<namespace>/gsa-graj-tools:latest"

docker build -t "$IMAGE" toolkits/gsa_graj_tools/
docker push "$IMAGE"
```

The [`Dockerfile`](toolkits/gsa_graj_tools/Dockerfile) already sets:
```dockerfile
ENV PORT=8000   # for local docker run only; Code Engine overrides this
EXPOSE 8000
CMD ["python", "server.py"]
```

> **Note:** `PORT` is a Knative-reserved env var — Code Engine injects it
> automatically. Do not pass `--env PORT=…` to `ce app create/update`.
> See [`deploy/ibm/README.md`](../../deploy/ibm/README.md) for the full runbook.

### 4.2  Update the Code Engine application

```bash
ibmcloud ce project select --name wxo-agentic-workflow

ibmcloud ce application update \
  --name gsa-graj-tools \
  --image "$IMAGE"

# Verify
ibmcloud ce application get --name gsa-graj-tools --output json | jq '.status'
```

### 4.3  Inject PostgreSQL credentials as a secret

```bash
# Create or update the secret
ibmcloud ce secret create --name postgres-secret \
  --from-literal DATABASE_URL="postgresql://<user>:<pass>@<host>:5432/neondb?sslmode=verify-full"

# Bind to the app
ibmcloud ce application update \
  --name gsa-graj-tools \
  --env-from-secret postgres-secret
```

### 4.4  Confirm the endpoint is live

```bash
curl -s https://gsa-graj-tools.2h721savdmhn.ca-tor.codeengine.appdomain.cloud/ | jq .
# Should return: { "status": "ok", "tools": [...] }
```

---

## Phase 5 — Re-import into watsonx Orchestrate

### 5.1  Remove the old toolkit (import is not idempotent)

```bash
cd /home/itzuser/wxo-agentic-workflow
.venv/bin/orchestrate toolkits remove --name gsa_graj_tools
```

### 5.2  Re-import from the spec

```bash
.venv/bin/orchestrate toolkits import -f toolkits/gsa_graj_tools/toolkit_spec.yaml
```

The [`toolkit_spec.yaml`](toolkits/gsa_graj_tools/toolkit_spec.yaml) pulls the
tool list directly from the live Code Engine endpoint:

```yaml
spec_version: v1
kind: mcp
name: gsa_graj_tools
url: https://gsa-graj-tools.2h721savdmhn.ca-tor.codeengine.appdomain.cloud/mcp
transport: streamable_http
tools:
  - "*"
```

### 5.3  Re-import the agent

```bash
.venv/bin/orchestrate agents import -f agents/gsa_graj_agent.agent.yaml
```

### 5.4  Verify

```bash
.venv/bin/orchestrate tools list   | grep gsa_graj
.venv/bin/orchestrate agents list  | grep gsa_graj
```

---

## Checklist — Before Calling a Tool Done

- [ ] Function named `gsa_graj_<name>`, returns `str`
- [ ] Docstring has: one-line summary, `Args:` block with every parameter
- [ ] DB connections closed in `finally` block
- [ ] Added to `_add_health_route` tools list in `server.py`
- [ ] Added to `tools:` list in `gsa_graj_agent.agent.yaml`
- [ ] Added routing instruction in agent `instructions:` block
- [ ] `python -m py_compile server.py` passes with no errors
- [ ] Toolkit removed and re-imported in watsonx Orchestrate
- [ ] Agent re-imported in watsonx Orchestrate
- [ ] `orchestrate tools list | grep <name>` shows the new tool

---

## Existing Tools — Quick Reference

| Tool name | Purpose | Key params |
|---|---|---|
| `gsa_graj_current_weather` | Live weather via wttr.in | `city` |
| `gsa_graj_programming_joke` | Random joke via JokeAPI | — |
| `gsa_graj_unit_converter` | Local unit conversion | `value`, `from_unit`, `to_unit` |
| `gsa_graj_connect_sl_db` | Schema inspection | — |
| `gsa_graj_read_from_sl` | SELECT rows | `table_name`, `where_clause`, `limit` |
| `gsa_graj_write_to_sl` | INSERT one row | `table_name`, `row_data` (JSON str) |
| `gsa_graj_aggregate_operational_tbl` | Multi-column monthly aggregate | `month`, `year`, `date_column` |
| `gsa_graj_count_records` | Flexible aggregate (COUNT/SUM/AVG/MIN/MAX/COUNT_DISTINCT) | `table_name`, `aggregate_function`, `aggregate_column`, `where_clause`, `group_by_column` |
| `gsa_graj_bulk_excel_to_sl` *(standalone)* | Bulk-load Excel via WXOFile | `excel_file`, `table_name`, `sheet_name`, `if_exists` |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Toolkit import fails with "already exists" | WXO does not support upsert | `orchestrate toolkits remove --name gsa_graj_tools` first |
| Tool not visible after import | Toolkit endpoint unreachable | `curl .../mcp` — check Code Engine app status |
| `pg8000` connection error | Missing env vars | Check `DATABASE_URL` or `PG_*` vars; set `PGSSL=true` for Neon |
| Tool returns wrong column names | Schema mismatch | Call `gsa_graj_connect_sl_db` to inspect live schema |
| Agent ignores the new tool | Not listed in agent YAML | Add to `tools:` list and re-import agent |
| `server.py` syntax error | Python parse failure | Run `python -m py_compile server.py` before deploying |
