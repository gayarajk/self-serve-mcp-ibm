# gsa_graj — Phoenix Evaluation Harness

LLM-as-judge evaluation harness for the `gsa_graj_agent`, using
[Arize Phoenix](https://phoenix.arize.com/) as the experiment tracking backend.

---

## Directory layout

```
eval/phoenix/
├── agent.py              — GsaGrajAgent: drives MCP server + LLM in a ReAct loop
├── create_dataset.py     — Upload gsa-graj-eval-0 CSV to Phoenix
├── run_experiment.py     — Run experiments and upload scores to Phoenix
├── datasets.yaml         — Dataset registry
├── README.md             — This file
│
├── judges/
│   ├── __init__.py
│   ├── correctness_judge.py   — LLM judge: does response match expected output?
│   └── relevance_judge.py     — LLM judge: did agent stay in scope?
│
├── prompts/
│   ├── system_prompt_v1.txt   — Basic analyst prompt
│   └── system_prompt_v2.txt   — Strict scope-boundary prompt
│
├── datasets/
│   └── gsa-graj-eval-0/
│       └── examples/
│       └── gsa-graj-eval-0.csv   — 10 evaluation examples
│
└── results/              — JSON result files written by run_experiment.py (gitignored)
```

---

## Prerequisites

### 1. Install dependencies

```bash
pip install -e ".[dev]"
```

Or manually:

```bash
pip install openai mcp arize-phoenix
```

### 2. Start Arize Phoenix locally

```bash
python -m phoenix.server.main serve
# Phoenix UI → http://localhost:6006
```

Or set `PHOENIX_BASE_URL` + `PHOENIX_API_KEY` for a hosted Phoenix instance.

### 3. Set environment variables

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
# edit .env
```

Required variables:

| Variable          | Description                                          |
|-------------------|------------------------------------------------------|
| `USAI_API_KEY`    | API key for the LLM provider                         |
| `USAI_BASE_URL`   | OpenAI-compatible base URL                           |
| `AGENT_MODEL`     | Model for the agent, e.g. `openai/gpt-4o`            |
| `JUDGE_MODEL`     | Model for judges (defaults to `AGENT_MODEL`)         |
| `PG_HOST`         | PostgreSQL host (default: `localhost`)               |
| `PG_PORT`         | PostgreSQL port (default: `5432`)                    |
| `PG_DB`           | Database name (default: `wxodb`)                     |
| `PG_USER`         | Database user (default: `wxouser`)                   |
| `PG_PASS`         | Database password (default: `wxopass`)               |
| `PHOENIX_BASE_URL`| Phoenix URL (default: `http://localhost:6006`)       |
| `PHOENIX_API_KEY` | Phoenix API key (omit for local Phoenix)             |

---

## Quick start

### Step 1 — Upload the dataset to Phoenix

```bash
python eval/phoenix/create_dataset.py
```

### Step 2 — Run an experiment (prompt v1)

```bash
python eval/phoenix/run_experiment.py --prompt v1
```

### Step 3 — Run with the stricter scope-boundary prompt

```bash
python eval/phoenix/run_experiment.py --prompt v2
```

Results are saved to `eval/phoenix/results/gsa-graj-eval-prompt-<v1|v2>.json`
and uploaded to Phoenix automatically.

---

## Judges

### `match_expected_response` (correctness)
Asks the judge LLM whether the agent's response satisfies the expected output.
The expected output is a keyword or phrase that must appear in the response —
it does not need to match word-for-word. Returns `score=1.0` (CORRECT) or `score=0.0` (INCORRECT).

### `check_answer_scope` (relevance / scope)
Asks the judge LLM whether the agent stayed within its allowed scope:
- Must use tools — never fabricate data
- Must not answer from general healthcare knowledge
- Must not perform arithmetic itself

Returns `score=1.0` (IN-SCOPE) or `score=0.0` (OUT-OF-SCOPE).

---

## Dataset — gsa-graj-eval-0

10 stable, read-only, multi-tool-call examples covering:
- Schema inspection + COUNT_DISTINCT
- Filtered reads (discharge_status, city)
- Single-column aggregates: SUM / AVG / MIN / MAX / COUNT_DISTINCT
- Grouped aggregates (by ward, by discharge_status, by city)
- Unit conversion (kg→lbs, celsius→fahrenheit)
- Monthly aggregate + count (January 2024)

All questions require at least two tool calls to answer correctly and use
keyword-based expected outputs (column names, function names) so the dataset
remains stable as row counts change.

---

## Adding new examples

Edit `eval/phoenix/datasets/gsa-graj-eval-0/examples/gsa-graj-eval-0.csv`
and re-run `create_dataset.py`. The dataset will be overwritten in Phoenix.
