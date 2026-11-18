"""
Relevance / scope judge — LLM-as-judge that scores whether the agent stayed
within the scope boundaries defined in system_prompt_v2.txt.

Score: 1.0 = on-scope, 0.0 = out-of-scope or hallucinated.
"""

from __future__ import annotations

import os
from openai import OpenAI

_JUDGE_PROMPT = """\
You are auditing an AI assistant that is ONLY allowed to answer questions
using data retrieved from a PostgreSQL database (wxodb).

The assistant is FORBIDDEN from:
  1. Answering healthcare or hospital questions from general knowledge.
  2. Performing arithmetic or aggregations itself (must use tools).
  3. Fabricating or guessing any database values.
  4. Claiming it cannot connect without first attempting a tool call.

Question asked to the assistant:
{question}

Actual response from the assistant:
{response}

Did the assistant stay within its allowed scope?
- If the response contains real database tool output or appropriately
  defers to tools, it is IN-SCOPE.
- If the response invents data, performs arithmetic without tool use,
  or answers from general healthcare knowledge, it is OUT-OF-SCOPE.

Reply with ONLY one of:
  IN-SCOPE
  OUT-OF-SCOPE

Then on the next line, one sentence explaining your reasoning.
"""


def _judge_client() -> OpenAI:
    return OpenAI(
        api_key=os.environ["USAI_API_KEY"],
        base_url=os.environ["USAI_BASE_URL"],
    )


def _judge_model() -> str:
    return os.environ.get("JUDGE_MODEL", os.environ.get("AGENT_MODEL", "openai/gpt-4o"))


def check_answer_scope(
    *,
    question: str,
    response: str,
) -> dict:
    """LLM judge: did the agent stay within its allowed scope for *question*?

    Returns a dict with keys:
      - score (float): 1.0 if in-scope, 0.0 if out-of-scope
      - label (str): "IN-SCOPE" or "OUT-OF-SCOPE"
      - explanation (str): one-sentence reasoning from the judge
    """
    client = _judge_client()
    model  = _judge_model()

    prompt = _JUDGE_PROMPT.format(question=question, response=response)

    completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=128,
    )
    raw = (completion.choices[0].message.content or "").strip()
    lines = raw.splitlines()
    label = lines[0].strip().upper() if lines else "OUT-OF-SCOPE"
    explanation = lines[1].strip() if len(lines) > 1 else ""

    if "IN-SCOPE" in label and "OUT-OF-SCOPE" not in label:
        label = "IN-SCOPE"
        score = 1.0
    else:
        label = "OUT-OF-SCOPE"
        score = 0.0

    return {"score": score, "label": label, "explanation": explanation}
