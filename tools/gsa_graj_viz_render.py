"""
gsa_graj_viz_render.py
======================
Native WXO Python tools that render chart and CSV output with audience=user,
bypassing LLM summarization so the markdown renders verbatim in the chat UI.

These two tools complement the gsa_graj_viz MCP toolkit:
  - gsa_graj_viz_run_query executes queries and returns structured JSON (MCP).
  - gsa_graj_viz_render_chart (this file) converts that JSON to rendered markdown.

Import with:
    orchestrate tools import -k python -f tools/gsa_graj_viz_render.py
"""

from __future__ import annotations

import csv
import io
import json

from ibm_watsonx_orchestrate.agent_builder.tools import tool


# ── Shared rendering helpers ──────────────────────────────────────────────────

def _make_markdown_table(rows: list[dict], columns: list[str]) -> str:
    if not rows or not columns:
        return "_No data to display._"
    header = "| " + " | ".join(str(c) for c in columns) + " |"
    sep    = "| " + " | ".join("---" for _ in columns) + " |"
    body   = ["| " + " | ".join(str(r.get(c, "")) for c in columns) + " |" for r in rows]
    return "\n".join([header, sep] + body)


def _make_text_barchart(
    rows: list[dict], x_col: str, y_col: str, title: str, width: int = 28
) -> str:
    if not rows:
        return ""
    vals = []
    for r in rows:
        try:
            vals.append(float(r.get(y_col, 0) or 0))
        except (TypeError, ValueError):
            vals.append(0.0)
    max_val = max(vals) if vals else 1
    if max_val == 0:
        max_val = 1
    lines = [f"**{title}**", "```"]
    for r, v in zip(rows, vals):
        label   = str(r.get(x_col, ""))[:18].ljust(18)
        filled  = int((v / max_val) * width)
        bar     = "█" * filled + "░" * (width - filled)
        lines.append(f"{label} {bar}  {v:,.0f}")
    lines.append("```")
    return "\n".join(lines)


# ── Tool 1: render chart ──────────────────────────────────────────────────────

@tool
def gsa_graj_viz_render_chart(
    query_result_json: str,
    chart_type: str = "bar",
    x_column: str = "",
    y_column: str = "",
    chart_title: str = "",
) -> str:
    """Render query results as a markdown chart and data table in the chat UI.

    Use this tool AFTER gsa_graj_viz_run_query to display results visually.
    Pass the full JSON string returned by gsa_graj_viz_run_query.

    Args:
        query_result_json: JSON string from gsa_graj_viz_run_query (contains columns, rows, sql, warnings).
        chart_type: bar | line | scatter | histogram | heatmap | table. Default: bar.
        x_column: Column for X axis. Defaults to first column.
        y_column: Column for Y axis / values. Defaults to second column.
        chart_title: Chart title. Auto-generated if omitted.

    Returns:
        str: Rendered markdown table and bar chart for display in chat.
    """
    from ibm_watsonx_orchestrate.run import ToolResult, TextContent, Annotations, Role

    def _make_result(text: str):
        return ToolResult(content=[TextContent(
            text=text, annotations=Annotations(audience=[Role.USER])
        )])

    try:
        payload = json.loads(query_result_json)
    except json.JSONDecodeError as exc:
        return _make_result(f"❌ Invalid query_result_json: {exc}")

    if "error" in payload:
        return _make_result(f"❌ Query error: {payload['error']}")

    rows: list[dict]    = payload.get("rows", [])
    columns: list[str]  = payload.get("columns", [])
    sql: str            = payload.get("sql", "")
    warnings: list[str] = list(payload.get("warnings", []))

    if not rows:
        return _make_result("⚠ Query returned no rows — nothing to chart.")

    x_col = x_column  or (columns[0] if columns else "")
    y_col = y_column  or (columns[1] if len(columns) > 1 else "")
    title = chart_title or (f"{y_col} by {x_col}" if x_col and y_col else "Query Results")
    ctype = chart_type.lower().strip()

    warn_md    = ("\n".join(f"> ⚠ {w}" for w in warnings) + "\n\n") if warnings else ""
    text_chart = (_make_text_barchart(rows[:20], x_col, y_col, title) + "\n\n") if ctype in ("bar", "line") and x_col and y_col else ""
    trunc_note = f"> Showing first 50 of {len(rows)} rows.\n\n" if len(rows) > 50 else ""
    md_table   = _make_markdown_table(rows[:50], columns)
    sql_block  = f"**SQL used:**\n```sql\n{sql}\n```\n"

    output = (
        f"### {title}\n\n"
        f"{warn_md}{text_chart}{trunc_note}"
        f"{md_table}\n\n"
        f"{sql_block}\n*{len(rows)} rows · {ctype}*"
    )
    return _make_result(output)


# ── Tool 2: render CSV ────────────────────────────────────────────────────────

@tool
def gsa_graj_viz_render_csv(
    query_result_json: str,
) -> str:
    """Render query results as a CSV block in the chat UI.

    Use this tool AFTER gsa_graj_viz_run_query when the user asks to export data.
    Pass the full JSON string returned by gsa_graj_viz_run_query.

    Args:
        query_result_json: JSON string from gsa_graj_viz_run_query (contains columns and rows).

    Returns:
        str: CSV data displayed in chat as a code block.
    """
    from ibm_watsonx_orchestrate.run import ToolResult, TextContent, Annotations, Role

    def _make_result(text: str):
        return ToolResult(content=[TextContent(
            text=text, annotations=Annotations(audience=[Role.USER])
        )])

    try:
        payload = json.loads(query_result_json)
    except json.JSONDecodeError as exc:
        return _make_result(f"❌ Invalid query_result_json: {exc}")

    if "error" in payload:
        return _make_result(f"❌ Query error: {payload['error']}")

    rows: list[dict]   = payload.get("rows", [])
    columns: list[str] = payload.get("columns", [])

    if not columns:
        return _make_result("⚠ No columns found in query results.")

    buf = io.StringIO()
    csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore", lineterminator="\r\n").writeheader()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore", lineterminator="\r\n")
    writer.writerows(rows)

    return _make_result(
        f"**CSV export** · {len(rows)} rows · {len(columns)} columns\n\n"
        f"```csv\n{buf.getvalue()}```"
    )
