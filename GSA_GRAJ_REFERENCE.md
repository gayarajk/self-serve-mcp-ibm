# GSA GRAJ — Tech Stack, Tools & Deployment Reference

> IBM watsonx Orchestrate · 3 Agents · 2 MCP Toolkits (FastMCP) · 5 Standalone Tools · Neon PostgreSQL · IBM Code Engine · Python 3.12

---

## 1 · Technology Stack

| Layer | Technology | Key details |
|---|---|---|
| **AI / Orchestration** | IBM watsonx Orchestrate | react_core agents · ADK (`ibm-watsonx-orchestrate`) · `groq/openai/gpt-oss-120b` · MCP streamable_http · WXOFile (chat upload) |
| **MCP Server Framework** | FastMCP ≥ 4.2 | Python 3.12 · async/await · `Annotated + pydantic Field` · Starlette + uvicorn (HTTP) · stdio (local dev) |
| **Database** | PostgreSQL — Neon / ICD | pg8000 ≥ 1.31.6 · `DATABASE_URL` (SSL) · `PG_*` env vars (dev) · wxodb · operational_tbl · ~605 synthetic records |
| **Container & Cloud** | IBM Code Engine | python:3.12-slim Docker · IBM Container Registry (ICR) · podman build/push · region: ca-tor · min-scale 1 · 0.25 CPU · 500 MB |
| **Excel Ingestion** | openpyxl ≥ 3.1.5 | WXOFile (chat attach) · BytesIO in-memory read · Auto CREATE TABLE · append / replace modes · header normalisation |
| **Evaluation Harness** | Arize Phoenix + LLM-as-judge | 12-example dataset · keyword correctness judge · scope/hallucination judge · `gsa-graj-eval-0.csv` · tags: aggregate · pii_redact · excel_upload … |

### Python dependencies (runtime)

```
fastmcp>=4.2.0        httpx>=0.28.1          pg8000>=1.31.6
openpyxl>=3.1.5       python-dotenv>=1.2.4   uvicorn>=0.29.0
pydantic (via fastmcp) starlette (via fastmcp) ibm-watsonx-orchestrate (ADK)
pip>=26.3 (CVE hardened)
```

---

## 2 · All Tools (21 total)

### gsa_graj_tools MCP Toolkit — 9 tools

> Hosted: `https://gsa-graj-tools.2h721savdmhn.ca-tor.codeengine.appdomain.cloud/mcp`  
> Transport: `streamable_http`

| # | Tool name | Type | Description |
|---|---|---|---|
| 1 | `gsa_graj_current_weather` | UTIL | Live weather for any city via wttr.in. httpx GET · no auth. |
| 2 | `gsa_graj_programming_joke` | UTIL | Random programming joke via icanhazdadjoke.com. httpx GET. |
| 3 | `gsa_graj_unit_converter` | UTIL | Convert km↔miles, kg↔lbs, °C↔°F, L↔gal, m↔ft, cm↔in. |
| 4 | `gsa_graj_connect_sl_db` | READ | Inspect wxodb schema — tables, column names, data types. |
| 5 | `gsa_graj_read_from_sl` | READ | SELECT * from any table with optional WHERE clause + LIMIT. |
| 6 | `gsa_graj_write_to_sl` | WRITE | INSERT one row (JSON object) into any table. |
| 7 | `gsa_graj_aggregate_operational_tbl` | READ | Monthly SUM/AVG/MIN/MAX/COUNT across all numeric columns in one call. |
| 8 | `gsa_graj_count_records` | READ | Single aggregate (COUNT/SUM/AVG/MIN/MAX/COUNT_DISTINCT) with one-column GROUP BY. |
| 9 | `gsa_graj_query_operational_tbl` | READ | Full analytical query: multi-column GROUP BY, HAVING, date granularity, pagination, top-N. |

---

### gsa_graj_viz MCP Toolkit — 6 tools

> Hosted: `https://gsa-graj-viz.2h721savdmhn.ca-tor.codeengine.appdomain.cloud/mcp`  
> Transport: `streamable_http` · Read-only (SELECT / EXPLAIN only)

| # | Tool name | Type | Description |
|---|---|---|---|
| 1 | `gsa_graj_viz_inspect_schema` | READ | Discover tables, columns, types, row counts, and sample values. |
| 2 | `gsa_graj_viz_preview_query` | READ | Validate SQL via EXPLAIN — no rows touched, confirms query is safe. |
| 3 | `gsa_graj_viz_run_query` | READ | Execute SELECT → returns JSON rows + SQL + markdown chart in one step. |
| 4 | `gsa_graj_viz_build_chart` | READ | Convert rows JSON → markdown chart (bar/line/scatter/histogram/heatmap/table). |
| 5 | `gsa_graj_viz_export_csv` | READ | Convert rows JSON → RFC 4180 CSV for download. |
| 6 | `gsa_graj_viz_redact_pii` | **PII** | Scan column names + cell values for PII patterns; mask with `***REDACTED***`. Called by **both** agents. |

#### PII Redaction — two detection levels

| Level | What is detected |
|---|---|
| **Column name** | `name` · `email` · `phone` · `dob` · `ssn` · `patient_id` · `address` · `gender` · `attending_doctor` · `salary` · `national_id` · `iban` · `passport` · `license` · `race` · `ethnicity` · `biometric` · `ip_address` · `mac_address` |
| **Cell value** | Email addresses · phone numbers · SSNs · credit card numbers · IP addresses · ISO dates (DOB) · UK NHS numbers · UK postcodes · US ZIP codes |

---

### Standalone Python Tools — 6 tools

> Deployed directly into WXO (not via MCP). Python files in `tools/`.

| # | Tool name | Type | Description |
|---|---|---|---|
| 1 | `gsa_graj_bulk_excel_to_sl` | WRITE | Chat-attached `.xlsx` → PostgreSQL. WXOFile · openpyxl · pg8000. append/replace. |
| 2 | `gsa_graj_load_excel_to_postgres` | WRITE | Chat-attached `.xlsx` → PostgreSQL. Same flow. Normalises headers to `lowercase_underscore`. |
| 3 | `gsa_graj_eval_get_dataset` | EVAL | Returns the gsa-graj-eval-0 dataset (12 examples) as JSON. Supports `tag_filter`. |
| 4 | `gsa_graj_eval_correctness` | EVAL | Keyword judge: all expected keywords must appear in agent response. Score 1.0 / 0.0. |
| 5 | `gsa_graj_eval_scope` | EVAL | Scope judge: detects hallucination signals vs tool-use evidence. Score 1.0 / 0.5 / 0.0. |

---

## 3 · Agents

| Agent | File | LLM | Description |
|---|---|---|---|
| `gsa_graj_agent` | `agents/gsa_graj_agent.agent.yaml` | groq/openai/gpt-oss-120b | Primary analytics agent — weather, DB queries, Excel upload, PII redaction |
| `gsa_graj_viz_agent` | `agents/gsa_graj_viz_agent.agent.yaml` | groq/openai/gpt-oss-120b | Visualisation agent — natural-language charts, PII redaction before display |
| `gsa_graj_eval_agent` | `agents/gsa_graj_eval_agent.agent.yaml` | groq/openai/gpt-oss-120b | Evaluation harness — runs 12-example benchmark, collaborates with gsa_graj_agent |

---

## 4 · Environment Variables

### Common (both toolkits + standalone tools)

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Prod | Full Neon / ICD PostgreSQL connection string with `sslmode=require` |
| `PG_HOST` / `PG_PORT` / `PG_DB` / `PG_USER` / `PG_PASS` | Local dev | Individual PG params — used when `DATABASE_URL` is not set |
| `PGSSL` | No | Set to `true` to force SSL with individual PG vars |
| `PGSSLROOTCERT` | No | Path to CA cert file for `sslmode=verify-full` (ICD) |
| `PORT` | Injected by CE | Code Engine / Knative injects this — **do NOT set manually in CE** |

### gsa_graj_viz only

| Variable | Default | Description |
|---|---|---|
| `VIZ_ROW_LIMIT` | `2000` | Max rows returned per query |
| `VIZ_QUERY_TIMEOUT_MS` | `30000` | Server-side statement timeout in ms |
| `VIZ_ALLOWED_SCHEMAS` | `public` | Comma-separated schemas to expose |

### Evaluation harness only

| Variable | Required | Description |
|---|---|---|
| `USAI_API_KEY` / `USAI_BASE_URL` | Yes | LLM provider credentials (OpenAI-compatible) |
| `AGENT_MODEL` | Yes | Model for the agent under test, e.g. `openai/gpt-4o` |
| `JUDGE_MODEL` | No | LLM judge model (defaults to `AGENT_MODEL`) |
| `PHOENIX_BASE_URL` | No | Arize Phoenix URL (default: `http://localhost:6006`) |
| `PHOENIX_API_KEY` | No | Phoenix API key (omit for local Phoenix) |

Setup:

```bash
cp .env.example .env
# Edit .env — set DATABASE_URL, USAI_API_KEY, USAI_BASE_URL
```

---

## 5 · IBM Code Engine Deployment

### Infrastructure overview

| Item | gsa_graj_tools | gsa_graj_viz |
|---|---|---|
| CE project | `gsa-graj-ce` (ca-tor) | `gsa-graj-ce` (ca-tor) |
| App name | `gsa-graj-tools` | `gsa-graj-viz` |
| Image | `ca.icr.io/gsa-graj-wxo/gsa-graj-tools:latest` | `ca.icr.io/gsa-graj-wxo/gsa-graj-viz:latest` |
| Registry secret | `icr-secret` | `icr-secret` |
| Resources | 0.25 CPU · 500 MB · min-scale 1 | 0.25 CPU · 500 MB · min-scale 1 |
| PG secret | `--secret-ref postgres-secret` | `--env-from-secret postgres-secret` |
| MCP endpoint | `…/mcp` | `…/mcp` |
| Health endpoint | `…/health` | `…/health` |

---

### Step-by-step deploy

#### Step 1 — Prerequisites

```bash
ibmcloud version
ibmcloud plugin install code-engine
ibmcloud plugin install container-registry
pip install --upgrade ibm-watsonx-orchestrate
ibmcloud login --sso
ibmcloud target -r ca-tor -g Default
```

#### Step 2 — Build the container image

```bash
# gsa_graj_tools
podman build -t ca.icr.io/gsa-graj-wxo/gsa-graj-tools:latest \
  toolkits/gsa_graj_tools/

# gsa_graj_viz
podman build -t ca.icr.io/gsa-graj-wxo/gsa-graj-viz:latest \
  toolkits/gsa_graj_viz/
```

#### Step 3 — Push to IBM Container Registry

```bash
ibmcloud cr login
podman push ca.icr.io/gsa-graj-wxo/gsa-graj-tools:latest
podman push ca.icr.io/gsa-graj-wxo/gsa-graj-viz:latest
```

#### Step 4 — Deploy to Code Engine

```bash
ibmcloud ce project select --name gsa-graj-ce

# gsa_graj_tools — first time
ibmcloud ce app create \
  --name gsa-graj-tools \
  --image ca.icr.io/gsa-graj-wxo/gsa-graj-tools:latest \
  --registry-secret icr-secret \
  --port 8000 \
  --min-scale 1 \
  --cpu 0.25 \
  --memory 500M \
  --secret-ref postgres-secret

# gsa_graj_viz — first time
ibmcloud ce app create \
  --name gsa-graj-viz \
  --image ca.icr.io/gsa-graj-wxo/gsa-graj-viz:latest \
  --registry-secret icr-secret \
  --port 8000 \
  --min-scale 1 \
  --cpu 0.25 \
  --memory 500M \
  --env-from-secret postgres-secret

# Redeploy existing apps
ibmcloud ce app update --name gsa-graj-tools \
  --image ca.icr.io/gsa-graj-wxo/gsa-graj-tools:latest
ibmcloud ce app update --name gsa-graj-viz \
  --image ca.icr.io/gsa-graj-wxo/gsa-graj-viz:latest
```

#### Step 5 — Smoke-test endpoints

```bash
BASE_T=https://gsa-graj-tools.2h721savdmhn.ca-tor.codeengine.appdomain.cloud
BASE_V=https://gsa-graj-viz.2h721savdmhn.ca-tor.codeengine.appdomain.cloud

curl -sf "${BASE_T}/health"   # → {"status":"ok","service":"gsa_graj_tools"}
curl -sf "${BASE_V}/health"   # → {"status":"ok","service":"gsa_graj_viz"}
```

#### Step 6 — Activate the watsonx Orchestrate ADK environment

```bash
.venv/bin/orchestrate env activate gsa-hackathon \
  --api-key "<YOUR_IBM_IAM_API_KEY>"
```

#### Step 7 — Import toolkits (not idempotent — remove first)

```bash
.venv/bin/orchestrate toolkits remove --name gsa_graj_tools || true
.venv/bin/orchestrate toolkits remove --name gsa_graj_viz   || true

.venv/bin/orchestrate toolkits import \
  -f toolkits/gsa_graj_tools/toolkit_spec.yaml
.venv/bin/orchestrate toolkits import \
  -f toolkits/gsa_graj_viz/toolkit_spec.yaml
```

#### Step 8 — Import agents (idempotent — updates in place)

```bash
.venv/bin/orchestrate agents import -f agents/gsa_graj_agent.agent.yaml
.venv/bin/orchestrate agents import -f agents/gsa_graj_viz_agent.agent.yaml
.venv/bin/orchestrate agents import -f agents/gsa_graj_eval_agent.agent.yaml
```

#### Step 9 — Import standalone Python tools

```bash
.venv/bin/orchestrate tools import -k python \
  tools/gsa_graj_bulk_excel_to_sl.py \
  --package-root tools/ \
  --requirements tools/requirements.txt

.venv/bin/orchestrate tools import -k python \
  tools/gsa_graj_load_excel_to_postgres.py \
  --package-root tools/ \
  --requirements tools/requirements.txt

.venv/bin/orchestrate tools import -k python \
  tools/gsa_graj_eval_get_dataset.py

.venv/bin/orchestrate tools import -k python \
  tools/gsa_graj_eval_correctness.py

.venv/bin/orchestrate tools import -k python \
  tools/gsa_graj_eval_scope.py
```

#### Step 10 — Verify everything is registered

```bash
.venv/bin/orchestrate toolkits list
.venv/bin/orchestrate agents list
.venv/bin/orchestrate tools list
```

---

### Key Dockerfile notes

- **Base image:** `python:3.12-slim` — minimal attack surface
- **CVE hardening:** `apt-get upgrade` + `pip ≥ 26.3` applied at build time (8 CVEs patched)
- **Layer cache:** `requirements.txt` copied and installed before `server.py`
- **Transport selection:** `PORT` env var selects HTTP (Code Engine) vs stdio (local dev)  
  ⚠️ **Never set `PORT` as a CE literal env var** — Code Engine / Knative injects it automatically and will reject it
- **Secrets:** PostgreSQL credentials injected via `--secret-ref postgres-secret` — never baked into image

---

### ICR registry secret rotation (when it expires)

```bash
# Create a fresh IAM API key
ibmcloud iam api-key-create ce-icr-key --output json

# Select CE project
ibmcloud ce project select --name gsa-graj-ce

# Replace the registry secret
ibmcloud ce registry delete --name icr-secret --force
ibmcloud ce registry create \
  --name icr-secret \
  --server ca.icr.io \
  --username iamapikey \
  --password "<new-api-key>"
```

---

### Teardown

```bash
# Remove from watsonx Orchestrate
.venv/bin/orchestrate toolkits remove --name gsa_graj_tools
.venv/bin/orchestrate toolkits remove --name gsa_graj_viz
.venv/bin/orchestrate agents remove --name gsa_graj_agent --kind native
.venv/bin/orchestrate agents remove --name gsa_graj_viz_agent --kind native
.venv/bin/orchestrate agents remove --name gsa_graj_eval_agent --kind native

# Remove Code Engine apps
ibmcloud ce project select --name gsa-graj-ce
ibmcloud ce app delete --name gsa-graj-tools --force
ibmcloud ce app delete --name gsa-graj-viz --force

# Remove ICR images
ibmcloud cr image-rm ca.icr.io/gsa-graj-wxo/gsa-graj-tools:latest
ibmcloud cr image-rm ca.icr.io/gsa-graj-wxo/gsa-graj-viz:latest
```

---

## 6 · Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| CE app `Not Ready` / `ErrImagePull` | ICR registry secret expired | Rotate `icr-secret` — see **ICR registry secret rotation** above |
| `orchestrate env activate` → "API key is disabled" | IBM Cloud IAM key deactivated | Generate a new one at [cloud.ibm.com/iam/apikeys](https://cloud.ibm.com/iam/apikeys) |
| `orchestrate env activate` → "Key secret is not valid" | MCSP v2 `ApiKey-...` rotated | Regenerate in wxO UI → Profile → API Keys |
| `orchestrate toolkits import` times out | CE app `Not Ready` at import time | Fix the CE app first (`ibmcloud ce app get --name gsa-graj-tools`), then retry |
| `PORT is a reserved environment variable` | Tried to set `PORT` as a CE env var | Remove it — CE injects `PORT` automatically via Knative |
| `SSLCertVerificationError` on GSA network | TLS proxy (Zscaler) re-signing HTTPS | Export proxy root cert to `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` |

---

## 7 · Sample Demo Questions

### gsa_graj_agent — Analytics

```
# Schema
"What tables exist in the database and what columns does operational_tbl have?"

# Aggregate + filter
"Which city has the highest total treatment cost? Show the top 5."

# Multi-column group by
"Show record counts grouped by gender and blood group."

# Date period grouping
"Show monthly admission counts for 2024 ordered by month."

# HAVING filter
"Which wards have more than 100 records and average cost above $5,000?"

# Filtered read
"Show me the first 10 rows from operational_tbl where discharge_status = 'ICU'."

# Pagination
"Show the next page of results."

# Unit conversion
"Convert 72 kg to lbs and 36 Celsius to Fahrenheit."

# Weather
"What is the current weather in Toronto?"
```

### gsa_graj_agent — Excel Upload

```
# Load into new table (replace mode)
[attach patients.xlsx]
"Load this file into a new table called uploaded_patients, replacing any existing data."

# Append to existing table
[attach new_admissions.xlsx]
"Append these rows to the existing uploaded_patients table."

# Specific sheet
[attach hospital_data.xlsx]
"Load the 'Q1_2025' sheet into the admissions_q1 table."
```

### gsa_graj_agent — PII Redaction

```
# Auto-detect PII columns
"Show me the first 10 rows from operational_tbl but redact any personally identifiable information."

# Force-mask extra columns
"Read 20 rows from operational_tbl and mask the attending_doctor and patient_id columns as well."

# Scan values too
"Show 5 rows from the uploaded_patients table with all sensitive data masked."
```

### gsa_graj_viz_agent — Charts

```
# Line chart — time series
"Show monthly admissions trend for 2024 as a line chart."

# Bar chart — ranking
"Compare average treatment cost by city — bar chart, top 10 cities."

# Histogram — distribution
"Show the distribution of length of stay in days as a histogram."

# Heatmap — two categories
"Heatmap of patient counts by ward and discharge status."

# Scatter — correlation
"Is there a correlation between age at admission and treatment cost? Scatter chart."

# CSV export
"Run the previous query and export the results as CSV."

# PII-safe chart
"Show attending doctor admission counts but redact any sensitive data before displaying."
```

### gsa_graj_eval_agent — Benchmarking

```
# Full benchmark
"Run the full evaluation on gsa_graj_agent and show me a results table."

# Tag-filtered run
"Run only the pii_redact examples and score them."
"Run only the aggregate tag examples and show correctness + scope scores."

# Single example
"Evaluate example 11 (Excel upload) and tell me if the agent passed."

# Summary
"What is the overall correctness percentage across all 12 examples?"
```

---

## 8 · Eval Dataset — gsa-graj-eval-0 (13 examples)

| ID | Tags | Question (summary) | Expected keywords |
|---|---|---|---|
| 1 | schema, count, multi_tool | Column names + distinct city count | `city, COUNT_DISTINCT` |
| 2 | aggregate, filter, multi_tool | Highest total treatment cost by city | `treatment_cost_usd` |
| 3 | aggregate, filter, multi_tool | Avg age for Discharged patients | `avg, age_at_admission` |
| 4 | schema, read, multi_tool | Schema + read rows where status=ICU | `discharge_status, ICU` |
| 5 | unit_conversion, multi_tool | 72 kg → lbs, 36°C → °F | `158.7326, 96.8` |
| 6 | aggregate, multi_tool | Ward with highest avg length of stay | `ward, avg, length_of_stay` |
| 7 | aggregate, multi_tool | Min and max treatment costs | `min, max, treatment_cost_usd` |
| 8 | aggregate, multi_tool | Distinct discharge statuses + counts | `Discharged, count` |
| 9 | schema, aggregate, filter, multi_tool | Schema + total cost for Toronto | `Toronto, treatment_cost_usd` |
| 10 | aggregate, multi_tool | Avg LOS + count for Jan 2024 | `avg, length_of_stay, january, 2024` |
| 11 | excel_upload, postgres, multi_tool | Upload Excel → new table with replace | `gsa_graj_load_excel_to_postgres, uploaded_patients, replace` |
| 12 | pii_redact, read, multi_tool | Read rows with PII masked | `gsa_graj_viz_redact_pii, REDACTED, name, patient_id` |
| 13 | aggregate, date_granularity, multi_tool | Total treatment cost grouped by admission year (all years, single call) | `2022, 2023, 2024, 2025, 2026, treatment_cost_usd` |

> **Example 13 — verified output (live run):**
>
> | Admission Year | Total Treatment Cost (USD) |
> |---|---|
> | 2022 | 2,987,147.37 |
> | 2023 | 2,765,052.81 |
> | 2024 | 2,877,242.99 |
> | 2025 | 2,991,483.03 |
> | 2026 | 1,859,969.44 |
>
> *(2026 lower as data runs to April 2026 only. Single `gsa_graj_query_operational_tbl` call with `date_granularity="year"`.)*

### Scoring

| Judge | Score | Label | Meaning |
|---|---|---|---|
| Correctness | 1.0 | CORRECT | All expected keywords found in response |
| Correctness | 0.0 | INCORRECT | One or more keywords missing |
| Scope | 1.0 | IN-SCOPE | Tool-use evidence found (e.g. `postgresql`, `wxodb`, `row(s)`) |
| Scope | 0.5 | UNCERTAIN | No clear signal either way — manual review advised |
| Scope | 0.0 | OUT-OF-SCOPE | Hallucination signal detected (e.g. "based on my knowledge") |

---

## 9 · Known Issues & Fixes

| Symptom | Root cause | Fix applied |
|---|---|---|
| Agent refuses yearly cost breakdown: *"would require too many calls"* | (1) Duplicate `── 6.` tool number confused routing. (2) No `date_granularity="year"` example in mapping section. (3) No absolute rule against refusing date-grouping requests. | Fixed numbering (Excel=6, analytics=7). Added yearly example to mapping. Added two ABSOLUTE RULES banning the refusal pattern. |

---

*Source files: `agents/` · `tools/` · `toolkits/` · `eval/phoenix/datasets/` · `deploy/ibm/README.md`*
