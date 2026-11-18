"""
create_dataset.py — upload the gsa-graj-eval-0 CSV to an Arize Phoenix instance.

Usage:
  python eval/phoenix/create_dataset.py

Environment variables required:
  PHOENIX_API_KEY   — Phoenix API key (omit for local Phoenix on localhost:6006)
  PHOENIX_BASE_URL  — Phoenix base URL (default: http://localhost:6006)

The dataset is named "gsa-graj-eval-0" and will be created or overwritten.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import phoenix as px
from phoenix.client import Client as PhoenixClient

DATASET_NAME = "gsa-graj-eval-0"
CSV_PATH = (
    Path(__file__).parent
    / "datasets"
    / "gsa-graj-eval-0"
    / "examples"
    / "gsa-graj-eval-0.csv"
)


def _phoenix_client() -> PhoenixClient:
    base_url = os.environ.get("PHOENIX_BASE_URL", "http://localhost:6006")
    api_key  = os.environ.get("PHOENIX_API_KEY")
    if api_key:
        return PhoenixClient(endpoint=base_url, api_key=api_key)
    return PhoenixClient(endpoint=base_url)


def load_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader)


def main() -> None:
    rows = load_csv(CSV_PATH)
    print(f"Loaded {len(rows)} examples from {CSV_PATH}")

    client = _phoenix_client()

    # Build examples list for Phoenix dataset
    examples = [
        {
            "input":  {"question": row["input"]},
            "output": {"expected": row["expected_output"]},
            "metadata": {"tags": row.get("tags", "")},
        }
        for row in rows
    ]

    dataset = client.datasets.upload(
        dataset_name=DATASET_NAME,
        inputs=[ex["input"]  for ex in examples],
        outputs=[ex["output"] for ex in examples],
        metadata=[ex["metadata"] for ex in examples],
    )
    print(f"Dataset '{DATASET_NAME}' uploaded — id: {dataset.id}")
    print(f"  Examples: {len(examples)}")


if __name__ == "__main__":
    main()
