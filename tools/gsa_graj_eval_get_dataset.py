"""
gsa_graj_eval_get_dataset.py — watsonx Orchestrate tool that returns the
built-in gsa-graj-eval-0 evaluation dataset as JSON.

Dataset: gsa-graj-eval-0 (13 examples)
  - All questions are read-only, stable, and require at least two tool calls.
  - Covers: schema inspection, filtered reads, single-column aggregates
    (SUM/AVG/MIN/MAX/COUNT_DISTINCT), grouped aggregates, unit conversion,
    Excel upload to PostgreSQL, PII redaction before chart display, and
    yearly date-granularity aggregation (regression test for the "too many
    calls" refusal bug).
  - Expected outputs are keyword-based (column names, function names) so the
    dataset does not become stale as row counts change.

Canonical CSV source:
    eval/phoenix/datasets/gsa-graj-eval-0/examples/gsa-graj-eval-0.csv
"""

from ibm_watsonx_orchestrate.agent_builder.tools import tool


# The built-in evaluation dataset — 13 stable read-only multi-tool examples.
# Mirrors eval/phoenix/datasets/gsa-graj-eval-0/examples/gsa-graj-eval-0.csv
_EVAL_DATASET = [
    {
        "id": 1,
        "question": "What columns does operational_tbl have, and how many distinct cities are in it?",
        "expected": "city,COUNT_DISTINCT",
        "tags": "schema,count,multi_tool",
    },
    {
        "id": 2,
        "question": "Which city has the highest total treatment cost in operational_tbl?",
        "expected": "treatment_cost_usd",
        "tags": "aggregate,filter,multi_tool",
    },
    {
        "id": 3,
        "question": "What is the average age at admission for patients in operational_tbl who were discharged (discharge_status = 'Discharged')?",
        "expected": "avg,age_at_admission",
        "tags": "aggregate,filter,multi_tool",
    },
    {
        "id": 4,
        "question": "Show me the schema of the database, then read 3 rows from operational_tbl where discharge_status = 'ICU'",
        "expected": "discharge_status,ICU",
        "tags": "schema,read,multi_tool",
    },
    {
        "id": 5,
        "question": "What is 72 kg in lbs, and what is 36 celsius in fahrenheit?",
        "expected": "158.7326,96.8",
        "tags": "unit_conversion,multi_tool",
    },
    {
        "id": 6,
        "question": "Which ward has the highest average length of stay in operational_tbl?",
        "expected": "ward,avg,length_of_stay",
        "tags": "aggregate,multi_tool",
    },
    {
        "id": 7,
        "question": "What are the minimum and maximum treatment costs recorded in operational_tbl?",
        "expected": "min,max,treatment_cost_usd",
        "tags": "aggregate,multi_tool",
    },
    {
        "id": 8,
        "question": "List the distinct discharge statuses in operational_tbl and the count of records for each one",
        "expected": "Discharged,count",
        "tags": "aggregate,multi_tool",
    },
    {
        "id": 9,
        "question": "Show me the schema of operational_tbl, then give me the total treatment cost for city = 'Toronto'",
        "expected": "Toronto,treatment_cost_usd",
        "tags": "schema,aggregate,filter,multi_tool",
    },
    {
        "id": 10,
        "question": "What is the average length of stay for patients admitted in January 2024, and how many such patients were there?",
        "expected": "avg,length_of_stay,january,2024",
        "tags": "aggregate,multi_tool",
    },
    {
        "id": 11,
        "question": "I am uploading an Excel file called patients.xlsx — load it into a new PostgreSQL table called uploaded_patients, replacing any existing rows.",
        "expected": "gsa_graj_load_excel_to_postgres,uploaded_patients,replace",
        "tags": "excel_upload,postgres,multi_tool",
    },
    {
        "id": 12,
        "question": "Show me the first 10 rows from operational_tbl but redact any personally identifiable information before displaying the results.",
        "expected": "gsa_graj_viz_redact_pii,REDACTED,name,patient_id",
        "tags": "pii_redact,read,multi_tool",
    },
    {
        "id": 13,
        "question": "What is the total treatment cost for each admission year across all years in operational_tbl?",
        "expected": "2022,2023,2024,2025,2026,treatment_cost_usd",
        "tags": "aggregate,date_granularity,multi_tool",
    },
]


@tool
def gsa_graj_eval_get_dataset(tag_filter: str = "") -> str:
    """Return the gsa-graj-eval-0 evaluation dataset as JSON.

    Returns the 13 stable, read-only, multi-tool-call examples from the
    built-in evaluation dataset. Each example has: id, question,
    expected (keyword hints), and tags.

    Args:
        tag_filter: Optional tag to filter examples, e.g. "aggregate",
            "schema", "read", "filter", "unit_conversion", "excel_upload",
            "pii_redact", "date_granularity", "multi_tool".
            Leave empty to return all 13 examples.
    """
    import json

    examples = _EVAL_DATASET
    if tag_filter.strip():
        tag = tag_filter.strip().lower()
        examples = [e for e in examples if tag in e["tags"].lower()]

    return json.dumps({
        "dataset":  "gsa-graj-eval-0",
        "total":    len(examples),
        "filter":   tag_filter or "none",
        "examples": examples,
    }, indent=2)
