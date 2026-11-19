"""
gsa_graj_viz — Visualization MCP toolkit (Python / FastMCP).

Exposes 5 read-only tools that let an LLM agent translate natural-language
chart requests into safe PostgreSQL queries and self-contained HTML charts.

Tools:
  gsa_graj_viz_inspect_schema  : Discover allowed tables, columns, and types
  gsa_graj_viz_preview_query   : Validate & EXPLAIN a proposed SELECT
  gsa_graj_viz_run_query       : Execute a SELECT and return JSON rows + SQL
  gsa_graj_viz_build_chart     : Turn query results into an interactive HTML chart
  gsa_graj_viz_export_csv      : Return query results as a CSV string

Security model
--------------
* Only SELECT / WITH / EXPLAIN statements pass the _assert_safe_sql() guard.
* Multi-statement injection (semicolon-chained) is blocked.
* All queries run under the ambient DB credentials — if you need a dedicated
  read-only Postgres role, point PG_USER / DATABASE_URL at it.
* A server-side statement_timeout is set on every connection (default 30 s).
* Rows returned are hard-capped at VIZ_ROW_LIMIT (default 2 000).
* Only schemas listed in ALLOWED_SCHEMAS (default: public) are enumerated.
* Credentials are never echoed in tool output or server logs.

Transport
---------
  PORT set   → streamable-http on that port  (Code Engine / remote)
  PORT unset → stdio                          (local / watsonx Orchestrate)
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import textwrap
from typing import Annotated, Optional

from dotenv import load_dotenv
from fastmcp import FastMCP
from pydantic import Field

# Load .env BEFORE importing db_config — db_config reads env vars at module level.
load_dotenv()

from db_config import (
    ALLOWED_SCHEMAS,
    PG_DB,
    PG_HOST,
    VIZ_ROW_LIMIT,
    _assert_safe_sql,
    get_ro_conn,
)

print("gsa_graj_viz MCP server starting", file=sys.stderr)

mcp = FastMCP(
    "gsa_graj_viz",
    instructions=textwrap.dedent("""\
        gsa_graj_viz — natural-language chart generation over PostgreSQL.

        DATABASE: wxodb (Neon / IBM Cloud Databases).
        Main table: operational_tbl — synthetic paediatric hospital admissions.

        TOOL SELECTION:
          1. gsa_graj_viz_inspect_schema  — first step; always call this to discover tables/columns.
          2. gsa_graj_viz_preview_query   — validate a proposed SELECT before running it.
          3. gsa_graj_viz_run_query       — execute a safe SELECT and get JSON rows + SQL.
          4. gsa_graj_viz_build_chart     — convert the rows JSON into an interactive HTML chart.
          5. gsa_graj_viz_export_csv      — produce a downloadable CSV of the query results.
          6. gsa_graj_viz_redact_pii      — scan and mask PII/sensitive data before display.

        SAFETY:
          - Only SELECT / WITH queries are allowed.
          - Results are capped at VIZ_ROW_LIMIT rows (default 2 000).
          - Always show the SQL used to the user — do not hide it.
          - Never fabricate data; call the tools and show the actual results.

        CHART TYPES: bar, line, scatter, histogram, heatmap, table.
        For unknown column meanings ask the user for clarification before guessing.
    """),
)

# ── Shared helpers ─────────────────────────────────────────────────────────────

_NUMERIC_TYPES = frozenset(
    {
        "integer", "bigint", "smallint", "numeric", "real",
        "double precision", "decimal", "float", "money",
        "integer[]", "numeric[]",
    }
)

_CHART_TYPES = frozenset({"bar", "line", "scatter", "histogram", "heatmap", "table"})

_SAFE_IDENTIFIER_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_$]*$')


def _safe_identifier(name: str, label: str = "identifier") -> str:
    """Return *name* if it is a safe SQL identifier, otherwise raise ValueError."""
    if not _SAFE_IDENTIFIER_RE.match(name):
        raise ValueError(
            f"Invalid {label} '{name}': only letters, digits, underscores, "
            "and dollar signs are allowed."
        )
    return name


def _schema_placeholder(schemas: frozenset[str]) -> str:
    """Return a pg8000 IN-list placeholder for the allowed schema set."""
    return ", ".join(f"'{s}'" for s in sorted(schemas))


# ── Tool 1: inspect schema ─────────────────────────────────────────────────────

@mcp.tool(
    name="gsa_graj_viz_inspect_schema",
    annotations={
        "title": "Inspect Database Schema",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def gsa_graj_viz_inspect_schema(
    table_filter: Annotated[
        Optional[str],
        Field(
            description=(
                "Optional substring to filter table names, e.g. 'operational'. "
                "Leave blank to list all allowed tables."
            )
        ),
    ] = None,
) -> str:
    """Discover tables, views, columns, data types, and row counts in the allowed schemas.

    Use when: 'What tables exist?', 'Show me the schema', 'What columns does operational_tbl have?'

    Returns a structured JSON object with one entry per table containing:
      - columns: list of {name, type, nullable}
      - sample_values: up to 3 distinct non-null values per column (for categorical guidance)
      - approx_row_count: reltuples estimate from pg_class

    Error responses:
    - Connection errors — check PG_* / DATABASE_URL env vars.
    """
    schema_list = _schema_placeholder(ALLOWED_SCHEMAS)
    con = get_ro_conn()
    try:
        # List all base tables and views in allowed schemas.
        table_rows = con.run(
            f"""
            SELECT table_schema, table_name, table_type
            FROM information_schema.tables
            WHERE table_schema IN ({schema_list})
              AND table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY table_schema, table_name
            """
        )

        tables = [
            (r[0], r[1], r[2])
            for r in table_rows
            if table_filter is None or table_filter.lower() in r[1].lower()
        ]

        if not tables:
            hint = f" matching filter '{table_filter}'" if table_filter else ""
            return json.dumps(
                {
                    "database": PG_DB,
                    "host": PG_HOST,
                    "allowed_schemas": sorted(ALLOWED_SCHEMAS),
                    "tables": [],
                    "note": f"No tables found{hint}.",
                }
            )

        result: dict = {
            "database": PG_DB,
            "host": PG_HOST,
            "allowed_schemas": sorted(ALLOWED_SCHEMAS),
            "tables": [],
        }

        for schema, tname, ttype in tables:
            col_rows = con.run(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = :s AND table_name = :t
                ORDER BY ordinal_position
                """,
                s=schema,
                t=tname,
            )

            columns = [
                {"name": c[0], "type": c[1], "nullable": c[2] == "YES"}
                for c in col_rows
            ]

            # Approximate row count from pg_class (fast, no sequential scan).
            rc_rows = con.run(
                """
                SELECT reltuples::bigint
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = :s AND c.relname = :t
                """,
                s=schema,
                t=tname,
            )
            approx_rows = int(rc_rows[0][0]) if rc_rows else -1

            # Collect up to 3 sample values for every column (categorical hint).
            sample_values: dict[str, list] = {}
            for col in columns:
                cname = col["name"]
                try:
                    srows = con.run(
                        f'SELECT DISTINCT "{cname}" FROM "{schema}"."{tname}" '
                        f'WHERE "{cname}" IS NOT NULL LIMIT 3'
                    )
                    sample_values[cname] = [r[0] for r in srows]
                except Exception:  # noqa: BLE001
                    sample_values[cname] = []

            result["tables"].append(
                {
                    "schema": schema,
                    "name": tname,
                    "type": ttype,
                    "approx_row_count": approx_rows,
                    "columns": columns,
                    "sample_values": sample_values,
                }
            )
    finally:
        con.close()

    return json.dumps(result, indent=2, default=str)


# ── Tool 2: preview / validate a query ────────────────────────────────────────

@mcp.tool(
    name="gsa_graj_viz_preview_query",
    annotations={
        "title": "Validate & Preview SQL Query",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def gsa_graj_viz_preview_query(
    sql: Annotated[
        str,
        Field(
            description=(
                "The SELECT query to validate. Must be a plain SELECT / WITH statement. "
                "Use $1, $2 … placeholders for any parameterized values."
            ),
            min_length=6,
        ),
    ],
) -> str:
    """Validate a proposed SELECT query without executing it.

    Uses PostgreSQL EXPLAIN to verify the query parses and the referenced
    tables exist without touching any rows.

    Returns:
      - 'valid': true/false
      - 'explain_plan': first line of the EXPLAIN output (plan type + cost)
      - 'detected_tables': table names found in the EXPLAIN node list
      - 'warnings': any safety or access warnings

    Error responses:
    - "Only SELECT / WITH …" — non-SELECT statement submitted.
    - PostgreSQL syntax error from EXPLAIN.
    """
    warnings: list[str] = []
    try:
        _assert_safe_sql(sql)
    except ValueError as exc:
        return json.dumps({"valid": False, "error": str(exc)})

    # Warn if the query does not contain a LIMIT clause.
    if not re.search(r'\bLIMIT\b', sql, re.IGNORECASE):
        warnings.append(
            f"No LIMIT clause detected. Results will be capped server-side at "
            f"{VIZ_ROW_LIMIT} rows."
        )

    con = get_ro_conn()
    try:
        explain_rows = con.run(f"EXPLAIN {sql}")
    except Exception as exc:  # noqa: BLE001
        return json.dumps(
            {
                "valid": False,
                "error": f"PostgreSQL rejected the query: {exc}",
                "sql": sql,
            }
        )
    finally:
        con.close()

    plan_lines = [r[0] for r in explain_rows]

    # Extract table names mentioned in the EXPLAIN plan.
    table_hits = re.findall(r'on\s+(\S+)', "\n".join(plan_lines), re.IGNORECASE)

    return json.dumps(
        {
            "valid": True,
            "sql": sql,
            "explain_plan": plan_lines[:5],
            "detected_tables": list(dict.fromkeys(table_hits)),
            "warnings": warnings,
        },
        indent=2,
    )


# ── Tool 3: execute a read-only query ─────────────────────────────────────────

@mcp.tool(
    name="gsa_graj_viz_run_query",
    annotations={
        "title": "Execute Visualization Query",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def gsa_graj_viz_run_query(
    sql: Annotated[
        str,
        Field(
            description=(
                "A validated SELECT / WITH query. Must NOT contain semicolons "
                "except at the end. Parameterized values should be inlined "
                "(the tool handles its own quoting at the Python layer). "
                "Example: SELECT city, COUNT(*) AS n FROM operational_tbl "
                "GROUP BY city ORDER BY n DESC LIMIT 20"
            ),
            min_length=6,
        ),
    ],
    description: Annotated[
        Optional[str],
        Field(
            description=(
                "One-sentence description of what this query computes, "
                "e.g. 'Monthly admissions by city for 2024'. "
                "Included in the response for transparency."
            )
        ),
    ] = None,
    chart_type: Annotated[
        str,
        Field(
            description=(
                "Chart type for rendering: bar | line | scatter | histogram | heatmap | table. "
                "Default is bar. Choose based on the data shape: "
                "bar/line for time-series or categories, scatter for two numerics, "
                "histogram for distributions, heatmap for two categories × one metric, "
                "table for browsable rows."
            )
        ),
    ] = "bar",
    x_column: Annotated[
        Optional[str],
        Field(description="Column for the X axis. Defaults to the first column if omitted.")
    ] = None,
    y_column: Annotated[
        Optional[str],
        Field(description="Column for the Y axis / values. Defaults to the second column if omitted.")
    ] = None,
    chart_title: Annotated[
        Optional[str],
        Field(description="Chart title shown above the results. Auto-generated if omitted.")
    ] = None,
) -> str:
    """Execute a read-only SELECT query and render the results as a markdown chart.

    Use when: you have a validated SQL query and want to show the data visually.
    This tool runs the query AND renders the results in one step — no extra tool call needed.

    Returns a rendered markdown response containing:
      - A Unicode bar chart (for bar/line types)
      - A markdown data table
      - The SQL used
      - Row count and any warnings

    Error responses:
    - Safety validation errors (non-SELECT, semicolons, etc.)
    - PostgreSQL runtime errors (bad column names, type mismatches, etc.)
    """
    try:
        _assert_safe_sql(sql)
    except ValueError as exc:
        return f"❌ SQL rejected: {exc}\n\n```sql\n{sql}\n```"

    # Inject a LIMIT if none is present.
    sql_with_limit = sql.rstrip().rstrip(";")
    if not re.search(r'\bLIMIT\b', sql_with_limit, re.IGNORECASE):
        sql_with_limit += f" LIMIT {VIZ_ROW_LIMIT}"

    warnings: list[str] = []

    con = get_ro_conn()
    try:
        raw = con.run(sql_with_limit)
        col_meta = con.columns
        columns = [c["name"] for c in col_meta] if col_meta else []
    except Exception as exc:  # noqa: BLE001
        return f"❌ Query execution failed: {exc}\n\n```sql\n{sql}\n```"
    finally:
        con.close()

    truncated = len(raw) == VIZ_ROW_LIMIT
    if truncated:
        warnings.append(
            f"Results were truncated to {VIZ_ROW_LIMIT} rows. "
            "Add a LIMIT clause or a more specific WHERE filter."
        )

    rows = [dict(zip(columns, r)) for r in raw]

    null_cols = [c for c in columns if any(r[c] is None for r in rows)]
    if null_cols:
        warnings.append(f"Null values present in columns: {', '.join(null_cols)}.")

    if not rows:
        return f"⚠ Query returned 0 rows.\n\n```sql\n{sql}\n```"

    # ── Render directly to markdown ──────────────────────────────────────────
    x_col  = x_column   or (columns[0] if columns else "")
    y_col  = y_column   or (columns[1] if len(columns) > 1 else "")
    title  = chart_title or description or (f"{y_col} by {x_col}" if x_col and y_col else "Query Results")
    ctype  = chart_type.lower().strip()

    warn_md    = ("\n".join(f"> ⚠ {w}" for w in warnings) + "\n\n") if warnings else ""
    text_chart = (_make_text_barchart(rows[:20], x_col, y_col, title) + "\n\n") if ctype in ("bar", "line") and x_col and y_col else ""
    trunc_note = f"> Showing first 50 of {len(rows)} rows.\n\n" if len(rows) > 50 else ""
    md_table   = _make_markdown_table(rows[:50], columns)
    sql_block  = f"**SQL used:**\n```sql\n{sql}\n```"

    return (
        f"### {title}\n\n"
        f"{warn_md}"
        f"{text_chart}"
        f"{trunc_note}"
        f"{md_table}\n\n"
        f"{sql_block}\n\n"
        f"*{len(rows)} rows returned*"
    )


# ── Tool 4: build an HTML chart ───────────────────────────────────────────────

# ── Markdown rendering helpers (WXO chat is markdown-only) ────────────────────

def _make_markdown_table(rows: list[dict], columns: list[str]) -> str:
    """Render rows as a GitHub-flavoured markdown table."""
    if not rows or not columns:
        return "_No data to display._"
    header = "| " + " | ".join(str(c) for c in columns) + " |"
    sep    = "| " + " | ".join("---" for _ in columns) + " |"
    body_lines = []
    for r in rows:
        cells = " | ".join(str(r.get(c, "")) for c in columns)
        body_lines.append(f"| {cells} |")
    return "\n".join([header, sep] + body_lines)


def _make_text_barchart(
    rows: list[dict], x_col: str, y_col: str, title: str, width: int = 30
) -> str:
    """Render a compact Unicode bar chart for bar/line data (up to 20 rows)."""
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
    bars = "▁▂▃▄▅▆▇█"
    lines = [f"**{title}**", "```"]
    for r, v in zip(rows, vals):
        label = str(r.get(x_col, ""))[:18].ljust(18)
        filled = int((v / max_val) * width)
        bar = "█" * filled + "░" * (width - filled)
        lines.append(f"{label} {bar}  {v:,.0f}")
    lines.append("```")
    return "\n".join(lines)


_ECHARTS_CDN_INLINE = "https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"

# ECharts palette (matches IBM Carbon Blue 70)
_PALETTE = [
    "#0043ce", "#0072c3", "#1192e8", "#33b1ff", "#82cfff",
    "#6929c4", "#9f1853", "#198038", "#b28600", "#005d5d",
]


def _make_bar_line_option(
    rows: list[dict],
    x_col: str,
    y_col: str,
    chart_type: str,
    title: str,
) -> dict:
    x_vals = [str(r.get(x_col, "")) for r in rows]
    y_vals = [r.get(y_col) for r in rows]
    series_type = "bar" if chart_type == "bar" else "line"
    return {
        "title": {"text": title, "left": "center", "textStyle": {"fontSize": 15}},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": x_vals, "axisLabel": {"rotate": 30}},
        "yAxis": {"type": "value", "name": y_col},
        "series": [
            {
                "name": y_col,
                "type": series_type,
                "data": y_vals,
                "smooth": True,
                "itemStyle": {"color": _PALETTE[0]},
            }
        ],
        "toolbox": {
            "feature": {
                "saveAsImage": {"title": "Save PNG"},
                "dataView": {"readOnly": True, "title": "Data"},
            }
        },
        "color": _PALETTE,
    }


def _make_scatter_option(
    rows: list[dict], x_col: str, y_col: str, title: str
) -> dict:
    data = [[r.get(x_col), r.get(y_col)] for r in rows]
    return {
        "title": {"text": title, "left": "center"},
        "tooltip": {
            "trigger": "item",
            "formatter": f"{x_col}: {{c0}}<br/>{y_col}: {{c1}}",
        },
        "xAxis": {"type": "value", "name": x_col},
        "yAxis": {"type": "value", "name": y_col},
        "series": [
            {
                "type": "scatter",
                "data": data,
                "symbolSize": 7,
                "itemStyle": {"color": _PALETTE[1]},
            }
        ],
        "toolbox": {"feature": {"saveAsImage": {"title": "Save PNG"}}},
    }


def _make_histogram_option(
    rows: list[dict], value_col: str, bins: int, title: str
) -> dict:
    """Compute histogram bins in Python and render as a bar chart."""
    values = [
        float(r[value_col]) for r in rows if r.get(value_col) is not None
    ]
    if not values:
        return {}
    mn, mx = min(values), max(values)
    if mn == mx:
        mx = mn + 1
    step = (mx - mn) / bins
    counts = [0] * bins
    for v in values:
        idx = min(int((v - mn) / step), bins - 1)
        counts[idx] += 1
    labels = [f"{mn + i * step:.1f}–{mn + (i + 1) * step:.1f}" for i in range(bins)]
    return {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": labels, "axisLabel": {"rotate": 30}},
        "yAxis": {"type": "value", "name": "count"},
        "series": [
            {
                "type": "bar",
                "data": counts,
                "barMaxWidth": 40,
                "itemStyle": {"color": _PALETTE[2]},
            }
        ],
        "toolbox": {"feature": {"saveAsImage": {"title": "Save PNG"}}},
    }


def _make_heatmap_option(
    rows: list[dict], x_col: str, y_col: str, value_col: str, title: str
) -> dict:
    x_cats = sorted({str(r[x_col]) for r in rows if r.get(x_col) is not None})
    y_cats = sorted({str(r[y_col]) for r in rows if r.get(y_col) is not None})
    xi = {v: i for i, v in enumerate(x_cats)}
    yi = {v: i for i, v in enumerate(y_cats)}
    data = []
    for r in rows:
        xv, yv, val = r.get(x_col), r.get(y_col), r.get(value_col)
        if xv is not None and yv is not None and val is not None:
            data.append([xi[str(xv)], yi[str(yv)], float(val)])
    return {
        "title": {"text": title, "left": "center"},
        "tooltip": {"position": "top"},
        "xAxis": {
            "type": "category",
            "data": x_cats,
            "splitArea": {"show": True},
            "axisLabel": {"rotate": 30},
        },
        "yAxis": {"type": "category", "data": y_cats, "splitArea": {"show": True}},
        "visualMap": {
            "min": min(d[2] for d in data) if data else 0,
            "max": max(d[2] for d in data) if data else 1,
            "calculable": True,
            "orient": "horizontal",
            "left": "center",
            "bottom": "5%",
        },
        "series": [
            {
                "type": "heatmap",
                "data": data,
                "label": {"show": True},
                "emphasis": {"itemStyle": {"shadowBlur": 10}},
            }
        ],
        "toolbox": {"feature": {"saveAsImage": {"title": "Save PNG"}}},
    }


def _make_table_option(rows: list[dict], columns: list[str], title: str) -> str:
    """Return a plain HTML table string (no ECharts required)."""
    th = "".join(f"<th>{c}</th>" for c in columns)
    tbody_rows = []
    for row in rows[:500]:  # hard cap for inline table
        tds = "".join(f"<td>{row.get(c, '')}</td>" for c in columns)
        tbody_rows.append(f"<tr>{tds}</tr>")
    return (
        f"<h3 style='text-align:center'>{title}</h3>"
        "<div style='overflow:auto'>"
        "<table border='1' cellpadding='4' cellspacing='0' "
        "style='border-collapse:collapse;width:100%;font-size:13px'>"
        f"<thead style='background:#f0f4ff'><tr>{th}</tr></thead>"
        f"<tbody>{''.join(tbody_rows)}</tbody>"
        "</table></div>"
    )


def _build_html(
    chart_option_json: str,
    title: str,
    sql: str,
    warnings: list[str],
    is_table: bool = False,
    table_html: str = "",
) -> str:
    """Wrap an ECharts option in a self-contained HTML page."""
    warning_html = ""
    if warnings:
        items = "".join(f"<li>{w}</li>" for w in warnings)
        warning_html = (
            f"<div style='background:#fff8e1;border:1px solid #f9a825;"
            f"padding:8px 12px;margin:8px 0;border-radius:4px'>"
            f"<strong>⚠ Notes:</strong><ul style='margin:4px 0 0'>{items}</ul></div>"
        )

    sql_block = (
        f"<details style='margin:8px 0'>"
        f"<summary style='cursor:pointer;color:#0043ce'>View SQL</summary>"
        f"<pre style='background:#f7f8fa;padding:10px;border-radius:4px;"
        f"white-space:pre-wrap;font-size:12px'>{sql}</pre>"
        f"</details>"
    )

    if is_table:
        body_content = table_html
        chart_script = ""
    else:
        body_content = "<div id='chart' style='width:100%;height:460px'></div>"
        chart_script = (
            f"<script src='{_ECHARTS_CDN_INLINE}'></script>\n"
            f"<script>\n"
            f"  var chart = echarts.init(document.getElementById('chart'));\n"
            f"  chart.setOption({chart_option_json});\n"
            f"  window.addEventListener('resize', function() {{ chart.resize(); }});\n"
            f"</script>"
        )

    return textwrap.dedent(f"""\
        <!DOCTYPE html>
        <html lang="en">
        <head>
          <meta charset="UTF-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>{title}</title>
          <style>
            body {{ font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
                   max-width: 920px; margin: 24px auto; padding: 0 16px;
                   color: #1f2328; background: #fff; }}
            h2   {{ text-align: center; color: #0043ce; margin-bottom: 4px; }}
            .meta {{ font-size: 12px; color: #57606a; text-align: center; margin-bottom: 8px; }}
          </style>
        </head>
        <body>
          <h2>{title}</h2>
          {warning_html}
          {sql_block}
          {body_content}
          {chart_script}
        </body>
        </html>
    """)


@mcp.tool(
    name="gsa_graj_viz_build_chart",
    annotations={
        "title": "Build Interactive Chart",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def gsa_graj_viz_build_chart(
    query_result_json: Annotated[
        str,
        Field(
            description=(
                "The JSON string returned by gsa_graj_viz_run_query. "
                "Must contain 'columns', 'rows', 'sql', and optionally 'warnings'."
            ),
            min_length=2,
        ),
    ],
    chart_type: Annotated[
        str,
        Field(
            description=(
                "Chart type: bar | line | scatter | histogram | heatmap | table. "
                "Default is bar."
            ),
        ),
    ] = "bar",
    x_column: Annotated[
        Optional[str],
        Field(
            description=(
                "Column to use for the X axis (bar/line) or scatter X axis. "
                "For histogram, this is the numeric column to distribute. "
                "For heatmap, this is the row-axis column. "
                "If omitted, defaults to the first column."
            )
        ),
    ] = None,
    y_column: Annotated[
        Optional[str],
        Field(
            description=(
                "Column to use for the Y axis (bar/line) or scatter Y axis. "
                "For heatmap, this is the column-axis column. "
                "If omitted, defaults to the second column."
            )
        ),
    ] = None,
    value_column: Annotated[
        Optional[str],
        Field(
            description=(
                "For heatmap only: the numeric column whose value determines cell colour. "
                "Defaults to the third column."
            )
        ),
    ] = None,
    chart_title: Annotated[
        Optional[str],
        Field(
            description=(
                "Human-readable chart title, e.g. 'Monthly Admissions by City 2024'. "
                "If omitted, an auto-generated title is used."
            )
        ),
    ] = None,
    histogram_bins: Annotated[
        int,
        Field(description="Number of bins for histogram charts. Defaults to 20.", ge=2, le=100),
    ] = 20,
) -> str:
    """Convert query results (from gsa_graj_viz_run_query) into a self-contained HTML chart.

    Use when: you have run a query and want to visualise the results.
    Supported chart types: bar, line, scatter, histogram, heatmap, table.

    Returns:
      - 'chart_type': the type used
      - 'title': the chart title
      - 'x_column' / 'y_column': columns mapped to axes
      - 'row_count': number of data points rendered
      - 'html': complete self-contained HTML string (save as .html to open in browser)
      - 'warnings': any notes about the chart

    Error responses:
    - "Invalid chart_type" — unsupported type name.
    - "query_result_json is not valid JSON" — malformed input.
    - "Required column '…' not found" — column name mismatch.
    """
    # Parse input.
    try:
        payload = json.loads(query_result_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"query_result_json is not valid JSON: {exc}"})

    ctype = chart_type.lower().strip()
    if ctype not in _CHART_TYPES:
        return json.dumps(
            {
                "error": f"Invalid chart_type '{chart_type}'. "
                f"Choose from: {', '.join(sorted(_CHART_TYPES))}."
            }
        )

    rows: list[dict] = payload.get("rows", [])
    columns: list[str] = payload.get("columns", [])
    sql: str = payload.get("sql", "")
    warnings: list[str] = list(payload.get("warnings", []))

    if not rows:
        return json.dumps(
            {"error": "No rows in query_result_json — cannot build a chart."}
        )

    # Resolve axis columns.
    x_col = x_column or (columns[0] if columns else "")
    y_col = y_column or (columns[1] if len(columns) > 1 else "")
    val_col = value_column or (columns[2] if len(columns) > 2 else "")

    for col, label in [(x_col, "x_column"), (y_col, "y_column")]:
        if col and col not in columns:
            return json.dumps(
                {
                    "error": f"Required column '{col}' not found in result. "
                    f"Available: {columns}"
                }
            )

    title = chart_title or f"{y_col or ''} by {x_col or ''}"

    # Build ECharts option.
    chart_option: dict = {}
    is_table = ctype == "table"
    table_html_str = ""

    if ctype in ("bar", "line"):
        chart_option = _make_bar_line_option(rows, x_col, y_col, ctype, title)
    elif ctype == "scatter":
        chart_option = _make_scatter_option(rows, x_col, y_col, title)
    elif ctype == "histogram":
        if x_col not in columns:
            return json.dumps({"error": f"Column '{x_col}' not found for histogram."})
        chart_option = _make_histogram_option(rows, x_col, histogram_bins, title)
    elif ctype == "heatmap":
        if val_col not in columns:
            return json.dumps(
                {"error": f"value_column '{val_col}' not found for heatmap."}
            )
        chart_option = _make_heatmap_option(rows, x_col, y_col, val_col, title)
    elif is_table:
        table_html_str = _make_table_option(rows, columns, title)

    # ── Render as markdown (WXO chat renders markdown, not HTML) ──────────────
    warn_lines = ""
    if warnings:
        warn_lines = "\n".join(f"> ⚠ {w}" for w in warnings) + "\n\n"

    sql_block = f"**SQL used:**\n```sql\n{sql}\n```\n\n"

    # Build a markdown table of the data.
    display_rows = rows[:50]   # cap inline table at 50 rows for readability
    truncated_note = ""
    if len(rows) > 50:
        truncated_note = f"> Showing first 50 of {len(rows)} rows.\n\n"

    md_table = _make_markdown_table(display_rows, columns)

    # For bar/line charts also render a simple text bar visualisation.
    text_chart = ""
    if ctype in ("bar", "line") and x_col and y_col:
        text_chart = _make_text_barchart(rows[:20], x_col, y_col, title) + "\n\n"

    result_md = (
        f"### {title}\n\n"
        f"{warn_lines}"
        f"{text_chart}"
        f"{truncated_note}"
        f"{md_table}\n\n"
        f"{sql_block}"
        f"*{len(rows)} rows · {ctype} · "
        f"Ask me to export as CSV or change the chart type.*"
    )
    return result_md


# ── Tool 5: export CSV ─────────────────────────────────────────────────────────

@mcp.tool(
    name="gsa_graj_viz_export_csv",
    annotations={
        "title": "Export Query Results as CSV",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def gsa_graj_viz_export_csv(
    query_result_json: Annotated[
        str,
        Field(
            description=(
                "The JSON string returned by gsa_graj_viz_run_query. "
                "Must contain 'columns' and 'rows'."
            ),
            min_length=2,
        ),
    ],
) -> str:
    """Convert query results into a CSV string.

    Use when: 'Export to CSV', 'Download the data', 'Give me a spreadsheet'.

    Returns:
      - 'row_count': number of data rows
      - 'column_count': number of columns
      - 'csv': the full CSV text (UTF-8, RFC 4180)
      - 'note': instructions for saving
    """
    try:
        payload = json.loads(query_result_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"query_result_json is not valid JSON: {exc}"})

    rows: list[dict] = payload.get("rows", [])
    columns: list[str] = payload.get("columns", [])

    if not columns:
        return json.dumps({"error": "No columns found in query_result_json."})

    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=columns,
        extrasaction="ignore",
        lineterminator="\r\n",
    )
    writer.writeheader()
    writer.writerows(rows)

    # Return CSV directly so it is readable inline and can be copy-pasted.
    csv_text = buf.getvalue()
    header = (
        f"**CSV export** · {len(rows)} rows · {len(columns)} columns\n"
        f"Copy the data below or ask me to save it.\n\n"
        f"```csv\n"
    )
    return header + csv_text + "\n```"


# ── Tool 6: redact PII / sensitive data ───────────────────────────────────────

# Column name patterns that likely carry PII
_PII_COL_RE = re.compile(
    r'(name|email|e_mail|phone|mobile|ssn|social_security|dob|birth|'
    r'passport|license|licence|address|street|postcode|zip|nhs|mrn|'
    r'patient_id|national_id|card|account|iban|credit|salary|income|'
    r'gender|race|ethnicity|religion|biometric|ip_address|mac_address)',
    re.IGNORECASE,
)

# Value-level regex patterns → (label, compiled pattern)
_PII_VALUE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("email",        re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')),
    ("phone",        re.compile(r'(\+?\d[\d\s\-().]{7,}\d)')),
    ("ssn",          re.compile(r'\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b')),
    ("credit_card",  re.compile(r'\b(?:\d[ \-]?){13,16}\b')),
    ("ip_address",   re.compile(r'\b\d{1,3}(\.\d{1,3}){3}\b')),
    ("dob_date",     re.compile(r'\b\d{4}[-/]\d{2}[-/]\d{2}\b')),
    ("uk_nhs",       re.compile(r'\b\d{3}[ \-]?\d{3}[ \-]?\d{4}\b')),
    ("postcode_uk",  re.compile(r'\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b')),
    ("zipcode_us",   re.compile(r'\b\d{5}(?:-\d{4})?\b')),
]

_MASK = "***REDACTED***"


def _redact_value(val: object) -> tuple[object, str | None]:
    """Return (possibly-masked value, label-or-None).

    Returns the original value unchanged when no PII is detected.
    """
    if val is None:
        return val, None
    s = str(val)
    for label, pat in _PII_VALUE_PATTERNS:
        if pat.search(s):
            return _MASK, label
    return val, None


@mcp.tool(
    name="gsa_graj_viz_redact_pii",
    annotations={
        "title": "Redact PII / Sensitive Data",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def gsa_graj_viz_redact_pii(
    query_result_json: Annotated[
        str,
        Field(
            description=(
                "The JSON string returned by gsa_graj_viz_run_query. "
                "Must contain 'columns' and 'rows'."
            ),
            min_length=2,
        ),
    ],
    sensitive_columns: Annotated[
        Optional[str],
        Field(
            description=(
                "Comma-separated list of additional column names to treat as "
                "sensitive and fully mask, e.g. 'attending_doctor,patient_id'. "
                "Combined with the built-in PII column-name detection."
            )
        ),
    ] = None,
    scan_values: Annotated[
        bool,
        Field(
            description=(
                "When True (default), each cell value is also scanned for PII "
                "patterns (email, phone, SSN, credit card, IP, date-of-birth, etc.) "
                "and masked if matched. Set to False to only mask by column name."
            )
        ),
    ] = True,
) -> str:
    """Scan query results for PII and sensitive data, redact them, and return safe output.

    Use BEFORE displaying or charting any data that might contain personal
    identifiers: names, emails, phone numbers, dates of birth, SSNs, patient IDs,
    addresses, financial figures, biometrics, or other sensitive values.

    Detection works on two levels:
      1. Column names — any column whose name matches a built-in PII pattern
         (name, email, dob, ssn, phone, address, patient_id, etc.) is fully masked.
      2. Cell values — when scan_values=True each cell is checked against regex
         patterns for email addresses, phone numbers, SSNs, credit cards, IPs, etc.

    You may supply extra column names via sensitive_columns to force-mask fields
    the built-in rules would not catch (e.g. a bespoke 'ref_code' column).

    Returns a JSON string with:
      - 'columns': original column list
      - 'rows': redacted rows (safe to display)
      - 'redacted_columns': columns that were fully masked by name
      - 'redacted_cells': count of individual cells masked by value scan
      - 'warnings': advisory notes about what was found
      - 'sql': passed through from input unchanged
    """
    try:
        payload = json.loads(query_result_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"query_result_json is not valid JSON: {exc}"})

    columns: list[str] = payload.get("columns", [])
    rows: list[dict]   = payload.get("rows", [])
    sql: str           = payload.get("sql", "")
    warnings: list[str] = list(payload.get("warnings", []))

    if not columns:
        return json.dumps({"error": "No columns found in query_result_json."})

    # ── Determine which columns are PII by name ────────────────────────────────
    extra_cols: set[str] = set()
    if sensitive_columns:
        extra_cols = {c.strip() for c in sensitive_columns.split(",") if c.strip()}

    pii_cols: set[str] = {
        c for c in columns
        if _PII_COL_RE.search(c) or c in extra_cols
    }

    # ── Redact rows ───────────────────────────────────────────────────────────
    redacted_cell_count = 0
    clean_rows: list[dict] = []

    for row in rows:
        clean: dict = {}
        for col in columns:
            val = row.get(col)

            # Mask by column name
            if col in pii_cols:
                clean[col] = _MASK
                continue

            # Mask by value pattern
            if scan_values:
                masked_val, label = _redact_value(val)
                if label:
                    redacted_cell_count += 1
                    if label not in [w.split()[0].lower() for w in warnings]:
                        warnings.append(
                            f"{label}: sensitive value pattern detected and redacted."
                        )
                clean[col] = masked_val
            else:
                clean[col] = val

        clean_rows.append(clean)

    # ── Build advisory warnings ───────────────────────────────────────────────
    if pii_cols:
        warnings.insert(
            0,
            f"PII columns masked by name: {', '.join(sorted(pii_cols))}."
        )
    if redacted_cell_count:
        warnings.insert(
            1 if pii_cols else 0,
            f"{redacted_cell_count} cell(s) masked by value-pattern scan."
        )
    if not pii_cols and not redacted_cell_count:
        warnings.append("No PII detected — data returned as-is.")

    result = {
        "columns":          columns,
        "rows":             clean_rows,
        "redacted_columns": sorted(pii_cols),
        "redacted_cells":   redacted_cell_count,
        "sql":              sql,
        "warnings":         warnings,
    }
    return json.dumps(result, default=str)


# ── Health endpoint (HTTP mode only) ──────────────────────────────────────────

def _add_health_route(app):
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def health(request: Request):
        return JSONResponse({"status": "ok", "service": "gsa_graj_viz"})

    app.routes.insert(0, Route("/health", health, methods=["GET"]))
    app.routes.insert(0, Route("/", health, methods=["GET"]))


# ── Entry point ────────────────────────────────────────────────────────────────

port_env = os.environ.get("PORT")
if port_env:
    port = int(port_env)
    starlette_app = mcp.http_app()
    _add_health_route(starlette_app)

    import uvicorn
    uvicorn.run(starlette_app, host="0.0.0.0", port=port)
else:
    mcp.run()
