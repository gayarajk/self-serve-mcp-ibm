---
name: mcp-eval
description: >
  Guide for running, extending, and debugging the Phoenix-based LLM-as-judge
  evaluation harness for the gsa_graj_agent in this workspace. Use when you
  need to run an evaluation experiment, add new dataset examples, update judge
  prompts, compare system prompt versions, or interpret evaluation results.
  Activate for phrases like "run eval", "evaluate the agent", "add eval
  questions", "LLM-as-judge", "Phoenix experiment", "how is the agent doing",
  or "update the dataset".
---

# Evaluation Harness Guide — gsa_graj_agent

The measure of `gsa_graj_agent` quality is not how many tools it has — it is
whether the agent correctly answers realistic hospital data questions using only
those tools, without fabricating data. This harness automates that measurement.

---

## Module Layout

```
eval/phoenix/
├── agent.py                        ← GsaGrajAgent — drives MCP server over stdio
├── create_dataset.py               ← CLI: upload CSV to Phoenix
├── run_experiment.py               ← CLI: run experiment + upload results to Phoenix
├── datasets.yaml                   ← dataset registry
├── README.md                       ← usage docs
├── judges/
│   ├── __init__.py                 ← re-exports match_expected_response, check_answer_scope
│   ├── correctness_judge.py        ← LLM judge: does response match expected?
│   └── relevance_judge.py          ← LLM judge: did agent stay in scope?
├── prompts/
│   ├── system_prompt_v1.txt        ← basic analyst prompt (tool-use rules only)
│   └── system_prompt_v2.txt        ← strict scope-boundary prompt
└── datasets/
    └── gsa-graj-eval-0/
        └── examples/
            └── gsa-graj-eval-0.csv ← 20 evaluation examples
```

---

## Environment Variables

All vars come from the root `.env` (see `.env.example`). Run from the workspace
root so `.env` is found automatically.

| Variable | Required | Purpose |
|---|---|---|
| `USAI_API_KEY` | ✅ | API key — used by agent AND judges |
| `USAI_BASE_URL` | ✅ | OpenAI-compatible base URL |
| `AGENT_MODEL` | ✅ | Model driving the agent, e.g. `openai/gpt-4o` |
| `JUDGE_MODEL` | recommended | Model for judges — defaults to `AGENT_MODEL` if unset. Use a different (stronger) model to reduce self-preference bias |
| `PHOENIX_BASE_URL` | optional | Phoenix URL — defaults to `http://localhost:6006` |
| `PHOENIX_API_KEY` | optional | Omit for local Phoenix |
| `PG_HOST` / `PG_PORT` / `PG_DB` / `PG_USER` / `PG_PASS` | ✅ | PostgreSQL — forwarded to the MCP server subprocess |

**Keep `AGENT_MODEL` ≠ `JUDGE_MODEL`.** Judging with a different model prevents the
agent from grading its own outputs.

---

## How the Harness Works

```
run_experiment.py
  └─ loads dataset from Phoenix
  └─ for each example:
       ├─ GsaGrajAgent.run(question)   ← agent.py
       │    └─ spawns server.py over stdio (toolkits/gsa_graj_tools/)
       │    └─ OpenAI ReAct loop (up to 10 tool-call rounds)
       │    └─ returns final text response
       ├─ match_expected_response(...)  ← correctness_judge.py
       └─ check_answer_scope(...)       ← relevance_judge.py
  └─ writes results/gsa-graj-eval-prompt-<v>.json
  └─ uploads experiment + annotations to Phoenix
```

The MCP server is launched as a **subprocess over stdio** — `agent.py` sets:
```python
SERVER_CWD  = REPO_ROOT / "toolkits" / "gsa_graj_tools"
SERVER_CMD  = "python"
SERVER_ARGS = ["server.py"]
```
This means the server runs with `TRANSPORT=stdio` (default) and the PostgreSQL
env vars are forwarded from the parent process.

---

## Running an Experiment

### Step 1 — Start Phoenix locally

```bash
# From workspace root
python -m phoenix.server.main serve
# UI: http://localhost:6006   OTLP: http://localhost:4317
```

Or set `PHOENIX_BASE_URL` + `PHOENIX_API_KEY` for a hosted instance.

### Step 2 — Upload the dataset (once per new dataset)

```bash
cd eval/phoenix
python create_dataset.py
# Loaded 20 examples from datasets/gsa-graj-eval-0/examples/gsa-graj-eval-0.csv
# Dataset 'gsa-graj-eval-0' uploaded — id: ...
```

### Step 3 — Run an experiment

```bash
# Default: prompt v1, dataset gsa-graj-eval-0
python run_experiment.py

# Stricter scope-boundary prompt
python run_experiment.py --prompt v2

# Different dataset
python run_experiment.py --dataset gsa-graj-eval-0 --prompt v1
```

Progress is printed per-question:
```
[01/20] Connect to the database and show me the sc ... CORRECT / IN-SCOPE  (3.2s)
[02/20] How many rows are in operational_tbl?       ... CORRECT / IN-SCOPE  (2.1s)
```

Results are saved to `eval/phoenix/results/gsa-graj-eval-prompt-<v>.json` and
uploaded to Phoenix automatically.

### Step 4 — Review in Phoenix UI

Open `http://localhost:6006`, navigate to the experiment, and inspect:
- Per-question correctness and scope scores
- Full traces showing which tools were called and in what order
- Failing examples to identify whether the fix belongs in:
  - **tool docstring / parameter names** (agent can't find the right tool)
  - **system prompt** (agent misroutes the question)
  - **the question itself** (ambiguous or unstable expected answer)

---

## The Two Judges

Both judges live in [`eval/phoenix/judges/`](eval/phoenix/judges/) and use the
same `USAI_API_KEY` / `USAI_BASE_URL` as the agent, but read `JUDGE_MODEL`.

### `match_expected_response` — correctness

File: [`correctness_judge.py`](eval/phoenix/judges/correctness_judge.py)

Compares the agent's response to the `expected_output` field in the CSV.
Expected values are **keywords or substrings**, not exact strings — e.g.:
- `"operational_tbl"` — must appear in the response
- `"605"` — the row count must appear
- `"aggregate,january,2024"` — all three must appear (AND logic in the
  built-in `gsa_graj_eval_correctness` tool; LLM logic here is more flexible)

Returns `{"score": 1.0|0.0, "label": "CORRECT"|"INCORRECT", "explanation": "..."}`.

**When the judge marks a correct answer wrong:** the prompt template is too strict.
Edit `_JUDGE_PROMPT` in `correctness_judge.py` to allow reasonable formatting
differences (units, surrounding prose, numeric rounding).

### `check_answer_scope` — relevance / scope

File: [`relevance_judge.py`](eval/phoenix/judges/relevance_judge.py)

Checks whether the agent answered using real tool output or hallucinated from
general knowledge. The judge prompt encodes the agent's exact forbidden behaviours:

> The assistant is FORBIDDEN from:
> 1. Answering healthcare questions from general knowledge
> 2. Performing arithmetic itself (must use tools)
> 3. Fabricating or guessing database values
> 4. Claiming it cannot connect without first attempting a tool call

Returns `{"score": 1.0|0.0, "label": "IN-SCOPE"|"OUT-OF-SCOPE", "explanation": "..."}`.

---

## The Dataset — `gsa-graj-eval-0`

20 examples in [`eval/phoenix/datasets/gsa-graj-eval-0/examples/gsa-graj-eval-0.csv`](eval/phoenix/datasets/gsa-graj-eval-0/examples/gsa-graj-eval-0.csv).

| Tag | Examples | What it tests |
|---|---|---|
| `schema,connect` | 2 | `gsa_graj_connect_sl_db` returns table names |
| `read,sample` | 1 | `gsa_graj_read_from_sl` returns rows |
| `filter,city` | 2 | `where_clause` with city filter |
| `filter,age` | 1 | `where_clause` with numeric condition |
| `filter,diagnosis` | 1 | `where_clause` with LIKE pattern |
| `aggregate` | 5 | `gsa_graj_aggregate_operational_tbl` by month/year |
| `count,read` | 1 | row count — `gsa_graj_count_records` |
| `count,distinct` | 1 | `COUNT_DISTINCT` on city column |
| `unit_conversion` | 1 | `gsa_graj_unit_converter` (100 km → 62.1371 miles) |
| `weather` | 1 | `gsa_graj_current_weather` for Toronto |
| `joke` | 1 | `gsa_graj_programming_joke` |
| `write` | 1 | `gsa_graj_write_to_sl` inserts a row |

### Adding new examples

1. Edit the CSV directly:
   ```
   eval/phoenix/datasets/gsa-graj-eval-0/examples/gsa-graj-eval-0.csv
   ```
   Add a row: `"question text","expected_keyword_or_phrase","tag1,tag2"`

2. Re-upload to Phoenix:
   ```bash
   cd eval/phoenix
   python create_dataset.py
   ```
   Phoenix will overwrite the existing dataset with the same name.

### Adding a new dataset

1. Create a new CSV at:
   ```
   eval/phoenix/datasets/<name>/examples/<name>.csv
   ```
   Columns: `input`, `expected_output`, `tags`

2. Register it in [`eval/phoenix/datasets.yaml`](eval/phoenix/datasets.yaml):
   ```yaml
   datasets:
     - name: <name>
       description: One-line description.
       csv: datasets/<name>/examples/<name>.csv
       columns:
         input: input
         expected_output: expected_output
         tags: tags
       tags:
         - schema
         - aggregate
         # ... list the tags used in this dataset
   ```

3. Upload and run:
   ```bash
   python create_dataset.py   # hardcode or update DATASET_NAME if needed
   python run_experiment.py --dataset <name>
   ```

---

## The Two System Prompts

| Version | File | Character |
|---|---|---|
| `v1` | [`prompts/system_prompt_v1.txt`](eval/phoenix/prompts/system_prompt_v1.txt) | Basic analyst — tells the agent which tool to call for each category. No explicit scope refusal. |
| `v2` | [`prompts/system_prompt_v2.txt`](eval/phoenix/prompts/system_prompt_v2.txt) | Strict scope boundary — adds "ONLY answer from tool output, NEVER from general knowledge, return verbatim". |

**When to add a v3:** when you change the agent's available tools (e.g. after adding
`gsa_graj_count_records` upgrades) and want to A/B whether the new instructions
improve correctness on aggregation examples.

A new prompt file must be named `system_prompt_v<n>.txt` and added to `PROMPTS` dict
in [`run_experiment.py`](eval/phoenix/run_experiment.py):

```python
PROMPTS = {
    "v1": Path(__file__).parent / "prompts" / "system_prompt_v1.txt",
    "v2": Path(__file__).parent / "prompts" / "system_prompt_v2.txt",
    "v3": Path(__file__).parent / "prompts" / "system_prompt_v3.txt",  # ← new
}
```

And add `"v3"` to the `--prompt` argument choices in `main()`.

---

## Interpreting Results

Results JSON is at `eval/phoenix/results/gsa-graj-eval-prompt-<v>.json`.

```json
{
  "experiment":       "gsa-graj-eval-prompt-v1",
  "dataset":          "gsa-graj-eval-0",
  "agent_model":      "openai/gpt-4o",
  "judge_model":      "...",
  "n":                20,
  "errors":           0,
  "correctness_avg":  0.85,
  "scope_avg":        0.90,
  "results": [...]
}
```

| Score | What to look at |
|---|---|
| `correctness_avg` low on `aggregate` tag | `gsa_graj_aggregate_operational_tbl` docstring — are month/year param descriptions clear? Or update system prompt to be more explicit. |
| `correctness_avg` low on `count` tag | Was `gsa_graj_count_records` upgraded? Add prompt v3 with the new `aggregate_function` parameter examples. |
| `scope_avg` low | Agent answered from memory. Tighten system prompt v2 scope rules. |
| High `errors` | Server failed to start — check `PG_*` env vars and that `server.py` syntax passes `python -m py_compile`. |
| Correct answer, low correctness score | Judge prompt is too strict — edit `_JUDGE_PROMPT` in `correctness_judge.py` to allow numeric rounding or phrasing variation. |

---

## Checklist — Before Running an Experiment

- [ ] `.env` has `USAI_API_KEY`, `USAI_BASE_URL`, `AGENT_MODEL`, `JUDGE_MODEL`
- [ ] `.env` has `PG_HOST` / `PG_PORT` / `PG_DB` / `PG_USER` / `PG_PASS` (or `DATABASE_URL`)
- [ ] `python -m py_compile toolkits/gsa_graj_tools/server.py` passes
- [ ] Phoenix is running (`python -m phoenix.server.main serve`) or `PHOENIX_BASE_URL` is set
- [ ] Dataset exists in Phoenix (`python eval/phoenix/create_dataset.py` if first run)
- [ ] `python eval/phoenix/run_experiment.py` runs without import errors

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ValueError: Dataset 'gsa-graj-eval-0' not found` | Dataset not uploaded yet | Run `python create_dataset.py` first |
| `KeyError: 'USAI_API_KEY'` | `.env` not loaded | Ensure `.env` is at workspace root; run from workspace root |
| `ConnectionRefusedError` on pg8000 | DB env vars wrong or missing | Check `PG_HOST`, `PG_PASS`, `PGSSL` in `.env` |
| Agent always returns empty string | Server failed silently | Run `TRANSPORT=stdio python toolkits/gsa_graj_tools/server.py` manually and check stderr |
| Judge marks correct answer INCORRECT | Judge prompt too strict | Add "allow rounding/formatting differences" to `_JUDGE_PROMPT` in `correctness_judge.py` |
| `scope_avg` unexpectedly low | v1 prompt lacks scope instructions | Switch to `--prompt v2` or write v3 |
| Experiment uploads to wrong Phoenix project | `PHOENIX_BASE_URL` mismatch | Check env var; default is `http://localhost:6006` |
| `run_experiment.py` missing `--prompt v3` | Choices list not updated | Add `"v3"` to `PROMPTS` dict and `choices=` in `argparse` |
