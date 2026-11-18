"""
run_experiment.py — run LLM-as-judge evaluation against Phoenix.

Usage:
  python eval/phoenix/run_experiment.py [--prompt v1|v2] [--dataset gsa-graj-eval-0]

Environment variables required:
  USAI_API_KEY      — API key for the LLM provider
  USAI_BASE_URL     — Base URL for the LLM provider (OpenAI-compatible)
  AGENT_MODEL       — Model for the agent, e.g. "openai/gpt-4o"
  JUDGE_MODEL       — Model for judges (defaults to AGENT_MODEL)
  PHOENIX_BASE_URL  — Phoenix base URL (default: http://localhost:6006)
  PHOENIX_API_KEY   — Phoenix API key (omit for local Phoenix)
  PG_HOST / PG_PORT / PG_DB / PG_USER / PG_PASS  — PostgreSQL credentials
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from phoenix.client import Client as PhoenixClient

from agent import GsaGrajAgent
from judges import check_answer_scope, match_expected_response

# ── Constants ─────────────────────────────────────────────────────────────────

DATASET_NAME    = "gsa-graj-eval-0"
EXPERIMENT_NAME = "gsa-graj-eval"

PROMPTS = {
    "v1": Path(__file__).parent / "prompts" / "system_prompt_v1.txt",
    "v2": Path(__file__).parent / "prompts" / "system_prompt_v2.txt",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _phoenix_client() -> PhoenixClient:
    base_url = os.environ.get("PHOENIX_BASE_URL", "http://localhost:6006")
    api_key  = os.environ.get("PHOENIX_API_KEY")
    if api_key:
        return PhoenixClient(endpoint=base_url, api_key=api_key)
    return PhoenixClient(endpoint=base_url)


def _load_dataset(client: PhoenixClient, name: str) -> list[dict]:
    """Fetch dataset examples from Phoenix."""
    datasets = list(client.datasets.list())
    dataset  = next((d for d in datasets if d.name == name), None)
    if dataset is None:
        raise ValueError(
            f"Dataset '{name}' not found in Phoenix. "
            "Run create_dataset.py first."
        )
    examples = list(client.datasets.get_examples(dataset.id))
    return examples


def _run_one(agent: GsaGrajAgent, question: str, expected: str) -> dict:
    """Run the agent on one question and apply both judges."""
    t0 = time.time()
    try:
        response = agent.run(question)
        error    = None
    except Exception as exc:  # noqa: BLE001
        response = ""
        error    = str(exc)
    latency = round(time.time() - t0, 3)

    correctness = match_expected_response(
        question=question,
        expected_output=expected,
        response=response,
    )
    scope = check_answer_scope(
        question=question,
        response=response,
    )

    return {
        "question":           question,
        "expected":           expected,
        "response":           response,
        "error":              error,
        "latency_s":          latency,
        "correctness_score":  correctness["score"],
        "correctness_label":  correctness["label"],
        "correctness_reason": correctness["explanation"],
        "scope_score":        scope["score"],
        "scope_label":        scope["label"],
        "scope_reason":       scope["explanation"],
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main(prompt_version: str = "v1", dataset_name: str = DATASET_NAME) -> None:
    prompt_path = PROMPTS[prompt_version]
    system_prompt = prompt_path.read_text()
    print(f"Using system prompt: {prompt_path.name}")
    print(f"Agent model:  {os.environ.get('AGENT_MODEL', 'openai/gpt-4o')}")
    print(f"Judge model:  {os.environ.get('JUDGE_MODEL', '(same as agent)')}")

    client   = _phoenix_client()
    examples = _load_dataset(client, dataset_name)
    print(f"Loaded {len(examples)} examples from dataset '{dataset_name}'")

    agent   = GsaGrajAgent(system_prompt=system_prompt)
    results = []

    for i, ex in enumerate(examples, 1):
        question = ex.input.get("question", "")
        expected = ex.output.get("expected", "")
        print(f"[{i:02d}/{len(examples):02d}] {question[:60]}", end=" ... ", flush=True)
        result = _run_one(agent, question, expected)
        results.append(result)
        status = f"{result['correctness_label']} / {result['scope_label']}"
        print(f"{status}  ({result['latency_s']}s)")

    # ── Summary ───────────────────────────────────────────────────────────────
    n = len(results)
    correctness_avg = sum(r["correctness_score"] for r in results) / n
    scope_avg       = sum(r["scope_score"]       for r in results) / n
    errors          = sum(1 for r in results if r["error"])

    exp_name = f"{EXPERIMENT_NAME}-prompt-{prompt_version}"
    print(f"\n{'─'*60}")
    print(f"Experiment : {exp_name}")
    print(f"Examples   : {n}")
    print(f"Errors     : {errors}")
    print(f"Correctness: {correctness_avg:.2%}")
    print(f"Scope      : {scope_avg:.2%}")
    print(f"{'─'*60}")

    # ── Write results JSON ────────────────────────────────────────────────────
    out_dir  = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"{exp_name}.json"
    with out_file.open("w", encoding="utf-8") as fh:
        json.dump(
            {
                "experiment":       exp_name,
                "dataset":          dataset_name,
                "prompt_version":   prompt_version,
                "agent_model":      os.environ.get("AGENT_MODEL"),
                "judge_model":      os.environ.get("JUDGE_MODEL"),
                "n":                n,
                "errors":           errors,
                "correctness_avg":  correctness_avg,
                "scope_avg":        scope_avg,
                "results":          results,
            },
            fh,
            indent=2,
            default=str,
        )
    print(f"Results written to {out_file}")

    # ── Upload experiment to Phoenix ──────────────────────────────────────────
    try:
        dataset_obj = next(
            d for d in client.datasets.list() if d.name == dataset_name
        )
        client.experiments.upload(
            dataset_id=dataset_obj.id,
            experiment_name=exp_name,
            examples=[
                {
                    "example_id":    ex.id,
                    "result":        {"response": r["response"]},
                    "annotations":   [
                        {
                            "name":  "correctness",
                            "score": r["correctness_score"],
                            "label": r["correctness_label"],
                            "explanation": r["correctness_reason"],
                        },
                        {
                            "name":  "scope",
                            "score": r["scope_score"],
                            "label": r["scope_label"],
                            "explanation": r["scope_reason"],
                        },
                    ],
                }
                for ex, r in zip(examples, results)
            ],
        )
        print(f"Experiment '{exp_name}' uploaded to Phoenix.")
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: could not upload to Phoenix: {exc}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run gsa_graj evaluation experiment")
    parser.add_argument("--prompt", choices=["v1", "v2"], default="v1",
                        help="System prompt version to use (default: v1)")
    parser.add_argument("--dataset", default=DATASET_NAME,
                        help=f"Phoenix dataset name (default: {DATASET_NAME})")
    args = parser.parse_args()
    main(prompt_version=args.prompt, dataset_name=args.dataset)
