"""
Correctness judge — LLM-as-judge that scores whether the agent's response
matches the expected output for each evaluation example.

Score: 1.0 = correct, 0.0 = incorrect.
"""

from __future__ import annotations

import os
from openai import OpenAI

_JUDGE_PROMPT = """\
You are an impartial judge evaluating an AI assistant's response.

Question asked to the assistant:
{question}

Expected output (or substring/keyword that must appear):
{expected}

Actual response from the assistant:
{response}

Does the assistant's response satisfy the expected output?
The expected output may be a keyword, phrase, or partial text that should
appear in the response. It does not need to match exactly word-for-word.

Reply with ONLY one of:
  CORRECT
  INCORRECT

Then on the next line, one sentence explaining your reasoning.
"""


def _judge_client() -> OpenAI:
    return OpenAI(
        api_key=os.environ["USAI_API_KEY"],
        base_url=os.environ["USAI_BASE_URL"],
    )


def _judge_model() -> str:
    return os.environ.get("JUDGE_MODEL", os.environ.get("AGENT_MODEL", "openai/gpt-4o"))


def match_expected_response(
    *,
    question: str,
    expected_output: str,
    response: str,
) -> dict:
    """LLM judge: does *response* satisfy *expected_output* for *question*?

    Returns a dict with keys:
      - score (float): 1.0 if correct, 0.0 if incorrect
      - label (str): "CORRECT" or "INCORRECT"
      - explanation (str): one-sentence reasoning from the judge
    """
    client = _judge_client()
    model  = _judge_model()

    prompt = _JUDGE_PROMPT.format(
        question=question,
        expected=expected_output,
        response=response,
    )

    completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=128,
    )
    raw = (completion.choices[0].message.content or "").strip()
    lines = raw.splitlines()
    label = lines[0].strip().upper() if lines else "INCORRECT"
    explanation = lines[1].strip() if len(lines) > 1 else ""

    # Normalise to CORRECT / INCORRECT regardless of extra words
    if "CORRECT" in label and "INCORRECT" not in label:
        label = "CORRECT"
        score = 1.0
    else:
        label = "INCORRECT"
        score = 0.0

    return {"score": score, "label": label, "explanation": explanation}
