"""
gsa_graj_eval_correctness.py — watsonx Orchestrate tool that scores whether
the agent's response matches the expected output (keyword correctness judge).

Uses comma-separated keyword matching (AND logic): all keywords in
expected_output must be found (case-insensitive substring) in agent_response
for the score to be 1.0 (CORRECT). Used as the primary judge alongside
gsa_graj_eval_scope in the eval harness.

Score: 1.0 = CORRECT, 0.0 = INCORRECT.
"""

from ibm_watsonx_orchestrate.agent_builder.tools import tool


@tool
def gsa_graj_eval_correctness(
    question: str,
    expected_output: str,
    agent_response: str,
) -> str:
    """Score whether the agent's response matches the expected output (correctness judge).

    Uses keyword/substring matching to decide if the agent_response satisfies
    the expected_output. Returns a JSON-formatted score report with:
      - score: 1.0 (CORRECT) or 0.0 (INCORRECT)
      - label: "CORRECT" or "INCORRECT"
      - reason: brief explanation

    Args:
        question: The original question that was asked to the agent.
        expected_output: The expected keyword, phrase, or value that should appear
            in the response (case-insensitive substring match).
        agent_response: The actual response returned by the agent.
    """
    import json

    # Split expected on commas — all keywords must be present (AND logic)
    keywords = [kw.strip().lower() for kw in expected_output.split(",") if kw.strip()]
    response_lower = agent_response.lower()

    matched   = [kw for kw in keywords if kw in response_lower]
    missing   = [kw for kw in keywords if kw not in response_lower]
    all_found = len(missing) == 0

    score = 1.0 if all_found else 0.0
    label = "CORRECT" if all_found else "INCORRECT"

    if all_found:
        reason = f"All {len(matched)} expected keyword(s) found in response."
    elif matched:
        reason = (
            f"Partial match: found {matched}, missing {missing}."
        )
    else:
        reason = f"None of the expected keywords found. Expected: {keywords}."

    result = {
        "score":    score,
        "label":    label,
        "reason":   reason,
        "question": question,
        "expected": expected_output,
        "keywords_checked": keywords,
        "keywords_matched": matched,
        "keywords_missing": missing,
    }
    return json.dumps(result, indent=2)
