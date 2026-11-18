"""
gsa_graj_eval_scope.py — watsonx Orchestrate tool that scores whether the
agent stayed within its allowed scope (hallucination / scope judge).

Checks the agent's response for signals that suggest it invented data or
answered from general knowledge instead of calling a tool. Used as the
second judge alongside gsa_graj_eval_correctness in the eval harness.

Score: 1.0 = IN-SCOPE, 0.5 = UNCERTAIN (manual review), 0.0 = OUT-OF-SCOPE.
"""

from ibm_watsonx_orchestrate.agent_builder.tools import tool


@tool
def gsa_graj_eval_scope(
    question: str,
    agent_response: str,
) -> str:
    """Score whether the agent stayed within its allowed scope (scope/relevance judge).

    Checks the agent's response for hallucination signals — patterns that suggest
    the agent invented data, answered from general knowledge instead of tool output,
    or failed to call a required tool. Returns a JSON score report with:
      - score: 1.0 (IN-SCOPE) or 0.0 (OUT-OF-SCOPE)
      - label: "IN-SCOPE" or "OUT-OF-SCOPE"
      - reason: brief explanation

    Args:
        question: The original question that was asked to the agent.
        agent_response: The actual response returned by the agent.
    """
    import json

    response_lower = agent_response.lower()

    # Signals that suggest the agent answered from memory / fabricated data
    HALLUCINATION_SIGNALS = [
        "based on my knowledge",
        "based on general knowledge",
        "i know that",
        "typically hospitals",
        "generally speaking",
        "i don't have access to",
        "i cannot connect",
        "i am unable to connect",
        "i cannot access the database",
        "i cannot retrieve",
        "i don't have real-time",
        "as an ai",
        "as a language model",
    ]

    # Signals that confirm the agent used a tool / returned real data.
    # Grounded in the gsa-graj-eval-0 dataset (10 DB + unit-conversion questions).
    TOOL_USE_SIGNALS = [
        "postgresql",
        "wxodb",
        "operational_tbl",
        "rows found",
        "row(s)",
        "aggregation results",
        "connected to",
        "table_name",
        "date_admitted",
        "treatment_cost_usd",
        "discharge_status",
        "length_of_stay",
        "age_at_admission",
        "158.7326",   # 72 kg → lbs (unit conversion result)
        "96.8",       # 36°C → °F (unit conversion result)
        "count_distinct",
        "ward",
    ]

    found_hallucination = [s for s in HALLUCINATION_SIGNALS if s in response_lower]
    found_tool_use      = [s for s in TOOL_USE_SIGNALS if s in response_lower]

    if found_hallucination:
        score = 0.0
        label = "OUT-OF-SCOPE"
        reason = f"Hallucination signal(s) detected: {found_hallucination}."
    elif found_tool_use:
        score = 1.0
        label = "IN-SCOPE"
        reason = f"Tool-use evidence found: {found_tool_use[:3]}."
    else:
        # Neutral response — no clear signal either way; give partial credit
        score = 0.5
        label = "UNCERTAIN"
        reason = "No clear hallucination or tool-use signal detected. Manual review advised."

    result = {
        "score":                   score,
        "label":                   label,
        "reason":                  reason,
        "question":                question,
        "hallucination_signals":   found_hallucination,
        "tool_use_signals_found":  found_tool_use,
    }
    return json.dumps(result, indent=2)
