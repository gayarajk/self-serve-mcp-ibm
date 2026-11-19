"""
gsa_graj_tools — MCP toolkit (Python / FastMCP).

Supports two transports selected via the PORT env var:
  PORT set   → streamable-http on that port  (Code Engine / remote)
  PORT unset → stdio                          (local / watsonx Orchestrate)

Tools exposed:
  gsa_graj_current_weather           : live weather via wttr.in
  gsa_graj_programming_joke          : random joke via jokeapi.dev
  gsa_graj_unit_converter            : pure local unit conversion
  gsa_graj_connect_sl_db             : connect to PostgreSQL and return schema
  gsa_graj_read_from_sl              : SELECT rows from a PostgreSQL table
  gsa_graj_write_to_sl               : INSERT a single row into a PostgreSQL table
  gsa_graj_aggregate_operational_tbl : aggregate operational_tbl by month/year
  gsa_graj_count_records             : flexible aggregate (COUNT/SUM/AVG/MIN/MAX/COUNT_DISTINCT)
  Note: bulk Excel load is a standalone Python tool (supports WXOFile upload)
"""

from __future__ import annotations

import json
import os
import sys
from typing import Annotated, Optional

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP
from pydantic import Field

# Load .env BEFORE importing db_config — db_config reads env vars at module level.
load_dotenv()

from db_config import get_conn as _get_conn, PG_DB as _PG_DB, PG_HOST as _PG_HOST

# All server-side logging MUST go to stderr — stdout is the MCP protocol channel.
print("gsa_graj_tools MCP server starting (PostgreSQL backend)", file=sys.stderr)

mcp = FastMCP(
    "gsa_graj_tools",
    instructions=(
        "This server provides tools for the gsa_graj hospital analytics workflow.\n"
        "It connects to a live PostgreSQL database (wxodb / Neon) containing\n"
        "operational_tbl — 605 hospital patient records (2022–2026).\n\n"
        "TOOL SELECTION GUIDE:\n"
        "- Inspect tables or column names → gsa_graj_connect_sl_db\n"
        "- Read / filter / browse rows → gsa_graj_read_from_sl\n"
        "- Insert a single row → gsa_graj_write_to_sl\n"
        "- Monthly multi-column summary (SUM/AVG/MIN/MAX all numeric cols) → gsa_graj_aggregate_operational_tbl\n"
        "- Any single aggregate (COUNT/SUM/AVG/MIN/MAX/COUNT_DISTINCT) with optional grouping → gsa_graj_count_records\n"
        "- Current weather for a city → gsa_graj_current_weather\n"
        "- Random programming joke → gsa_graj_programming_joke\n"
        "- Unit conversion (km↔miles, kg↔lbs, etc.) → gsa_graj_unit_converter\n\n"
        "CONVENTIONS:\n"
        "- Main table: operational_tbl. Date column: date_admitted.\n"
        "- where_clause is SQL without the WHERE keyword, e.g. \"city = 'Toronto'\".\n"
        "- row_data for writes is a JSON object string, e.g. '{\"name\": \"Alice\"}'.\n"
        "- aggregate_function values: COUNT, SUM, AVG, MIN, MAX, COUNT_DISTINCT.\n\n"
        "AUTHENTICATION: Requires PG_HOST/PG_PORT/PG_DB/PG_USER/PG_PASS or DATABASE_URL."
    ),
)


# ── Shared HTTP helper ─────────────────────────────────────────────────────────

async def _http_get(url: str) -> dict:
    """GET a fixed approved URL and return parsed JSON.

    Uses httpx with no redirects, no env proxy, and an explicit timeout.
    """
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(10.0),
        trust_env=False,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


def _http_error(exc: Exception) -> str:
    """Return a safe, actionable error string without leaking upstream details."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Error: upstream service returned HTTP {exc.response.status_code}. Try again later."
    if isinstance(exc, httpx.TimeoutException):
        return "Error: request timed out. Try again later."
    return "Error: unexpected upstream service failure."


# ── Tool 1: current weather ────────────────────────────────────────────────────

@mcp.tool(
    name="gsa_graj_current_weather",
    annotations={
        "title": "Current Weather",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def gsa_graj_current_weather(
    city: Annotated[str, Field(description="City name, e.g. 'Toronto' or 'London'.", min_length=1, max_length=100)],
) -> str:
    """Return current weather for a city using the wttr.in public API.

    Use when: "What is the weather in <city>?", "Current temperature in <city>".
    Returns temperature (°C/°F), feels-like, description, and humidity.

    Error responses:
    - "Error: upstream service returned HTTP …" — wttr.in unreachable
    - "Error: request timed out." — network timeout
    """
    try:
        url = f"https://wttr.in/{httpx.URL(city).path}?format=j1"
        # wttr.in is a fixed approved origin — no caller-controlled host
        url = f"https://wttr.in/{city.strip().replace(' ', '+')}?format=j1"
        data = await _http_get(url)
        current = data["current_condition"][0]
        return (
            f"Weather in {city}: {current['weatherDesc'][0]['value']}. "
            f"Temperature: {current['temp_C']}\u00b0C ({current['temp_F']}\u00b0F), "
            f"feels like {current['FeelsLikeC']}\u00b0C. "
            f"Humidity: {current['humidity']}%."
        )
    except Exception as exc:
        return _http_error(exc)


# ── Tool 2: programming joke ───────────────────────────────────────────────────

@mcp.tool(
    name="gsa_graj_programming_joke",
    annotations={
        "title": "Programming Joke",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def gsa_graj_programming_joke() -> str:
    """Fetch a random programming joke from the JokeAPI public endpoint.

    Use when: "Tell me a joke", "Give me a programming joke".
    Returns a single-line joke string.

    Error responses:
    - "Error: upstream service returned HTTP …" — JokeAPI unreachable
    - "Sorry, no joke could be fetched right now." — API returned an error flag
    """
    try:
        data = await _http_get("https://v2.jokeapi.dev/joke/Programming?type=single")
        if data.get("error"):
            return "Sorry, no joke could be fetched right now."
        return data["joke"]
    except Exception as exc:
        return _http_error(exc)


# ── Tool 3: unit converter ─────────────────────────────────────────────────────

_CONVERSIONS: dict = {
    ("km", "miles"):             lambda v: v * 0.621371,
    ("miles", "km"):             lambda v: v * 1.60934,
    ("kg", "lbs"):               lambda v: v * 2.20462,
    ("lbs", "kg"):               lambda v: v * 0.453592,
    ("celsius", "fahrenheit"):   lambda v: v * 9 / 5 + 32,
    ("fahrenheit", "celsius"):   lambda v: (v - 32) * 5 / 9,
    ("liters", "gallons"):       lambda v: v * 0.264172,
    ("gallons", "liters"):       lambda v: v * 3.78541,
    ("meters", "feet"):          lambda v: v * 3.28084,
    ("feet", "meters"):          lambda v: v * 0.3048,
}

_SUPPORTED_PAIRS = ", ".join(f"{f}→{t}" for f, t in _CONVERSIONS)


@mcp.tool(
    name="gsa_graj_unit_converter",
    annotations={
        "title": "Unit Converter",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def gsa_graj_unit_converter(
    value: Annotated[float, Field(description="Numeric value to convert, e.g. 100.0.")],
    from_unit: Annotated[str, Field(description="Source unit, e.g. 'km', 'kg', 'celsius'.", min_length=1, max_length=20)],
    to_unit: Annotated[str, Field(description="Target unit, e.g. 'miles', 'lbs', 'fahrenheit'.", min_length=1, max_length=20)],
) -> str:
    """Convert a numeric value between supported unit pairs (pure local logic, no network).

    Use when: "What is 100 km in miles?", "Convert 70 kg to lbs".
    Supported pairs: km↔miles, kg↔lbs, celsius↔fahrenheit, liters↔gallons, meters↔feet.

    Error responses:
    - "Unsupported conversion: … Supported pairs: …" — unknown unit pair
    """
    key = (from_unit.lower().strip(), to_unit.lower().strip())
    if key not in _CONVERSIONS:
        return (
            f"Unsupported conversion: '{from_unit}' to '{to_unit}'. "
            f"Supported pairs: {_SUPPORTED_PAIRS}."
        )
    result = _CONVERSIONS[key](value)
    return f"{value} {from_unit} = {result:.4f} {to_unit}"


# ── Tool 4: connect to PostgreSQL DB ──────────────────────────────────────────

@mcp.tool(
    name="gsa_graj_connect_sl_db",
    annotations={
        "title": "Inspect Database Schema",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def gsa_graj_connect_sl_db() -> str:
    """Connect to the wxodb PostgreSQL database and return all table schemas.

    Use when: "What tables exist?", "Show me the schema", "List columns in operational_tbl".
    Returns database name, host, table names, and column name + type for each table.

    Error responses:
    - pg8000 connection error — check PG_* or DATABASE_URL environment variables.
    """
    con = _get_conn()
    try:
        tables_rows = con.run("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        tables = [r[0] for r in tables_rows]

        if not tables:
            return (
                f"Connected to PostgreSQL '{_PG_DB}' @ {_PG_HOST}.\n"
                "No tables found yet. Load data using gsa_graj_bulk_excel_to_sl."
            )

        schema_lines = []
        for table in tables:
            cols = con.run("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :t
                ORDER BY ordinal_position
            """, t=table)
            col_desc = ", ".join(f"{c[0]} ({c[1]})" for c in cols)
            schema_lines.append(f"  [{table}]  {col_desc}")
    finally:
        con.close()

    return (
        f"Connected to PostgreSQL '{_PG_DB}' @ {_PG_HOST}.\n"
        f"Tables found ({len(tables)}):\n" + "\n".join(schema_lines)
    )


# ── Tool 5: read rows from PostgreSQL ─────────────────────────────────────────

@mcp.tool(
    name="gsa_graj_read_from_sl",
    annotations={
        "title": "Read Rows from Database",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def gsa_graj_read_from_sl(
    table_name: Annotated[str, Field(description="Table to read from, e.g. 'operational_tbl'.", min_length=1, max_length=63)],
    where_clause: Annotated[Optional[str], Field(description="SQL WHERE clause without the WHERE keyword, e.g. \"city = 'Toronto' AND age_at_admission > 5\". Omit to return all rows.")] = None,
    limit: Annotated[int, Field(description="Maximum rows to return. Defaults to 100.", ge=1, le=1000)] = 100,
) -> str:
    """Read rows from a PostgreSQL table with optional filtering.

    Use when: "Show me rows from …", "Filter admissions where …", "List patients in …".
    Returns JSON array of row objects, with column names as keys.

    Error responses:
    - pg8000 error — check table name and where_clause syntax.
    """
    con = _get_conn()
    try:
        col_rows = con.run("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = :t
            ORDER BY ordinal_position
        """, t=table_name)
        columns = [c[0] for c in col_rows]

        sql = f'SELECT * FROM "{table_name}"'
        if where_clause:
            sql += f" WHERE {where_clause}"
        sql += f" LIMIT {limit}"

        data = con.run(sql)
        rows = [dict(zip(columns, row)) for row in data]
    finally:
        con.close()

    result = json.dumps(rows, indent=2, default=str)
    return (
        f"Read {len(rows)} row(s) from table '{table_name}' "
        f"in PostgreSQL '{_PG_DB}'.\n\n{result}"
    )


# ── Tool 6: write a single row to PostgreSQL ──────────────────────────────────

@mcp.tool(
    name="gsa_graj_write_to_sl",
    annotations={
        "title": "Insert Row into Database",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def gsa_graj_write_to_sl(
    table_name: Annotated[str, Field(description="Table to insert into, e.g. 'operational_tbl'.", min_length=1, max_length=63)],
    row_data: Annotated[str, Field(description="JSON object string mapping column names to values, e.g. '{\"name\": \"Alice\", \"city\": \"Toronto\"}'.", min_length=2)],
) -> str:
    """Insert a single row into a PostgreSQL table.

    Use when: "Insert a new record …", "Add a row to …".
    row_data must be a non-empty JSON object whose keys match table column names.

    Error responses:
    - "row_data is not valid JSON: …" — malformed JSON input.
    - "row_data must be a non-empty JSON object." — wrong type.
    - pg8000 error — column name mismatch or constraint violation.
    """
    try:
        record = json.loads(row_data)
    except json.JSONDecodeError as exc:
        raise ValueError(f"row_data is not valid JSON: {exc}.") from exc

    if not isinstance(record, dict) or not record:
        raise ValueError("row_data must be a non-empty JSON object.")

    columns = list(record.keys())
    values  = list(record.values())
    col_list     = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join(f"${i+1}" for i in range(len(columns)))

    con = _get_conn()
    try:
        con.run(
            f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})',
            *values,
        )
    finally:
        con.close()

    return (
        f"Successfully inserted 1 row into table '{table_name}' "
        f"in PostgreSQL '{_PG_DB}'.\n"
        f"  Data: {json.dumps(record, default=str)}"
    )


# ── Tool 7: aggregate operational_tbl by month/year ───────────────────────────

@mcp.tool(
    name="gsa_graj_aggregate_operational_tbl",
    annotations={
        "title": "Monthly Aggregate Summary",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def gsa_graj_aggregate_operational_tbl(
    month: Annotated[int, Field(description="Month number 1–12.", ge=1, le=12)],
    year: Annotated[int, Field(description="Four-digit year, e.g. 2024.", ge=1900, le=2100)],
    date_column: Annotated[str, Field(description="Date column to filter on. Defaults to 'date_admitted'.", min_length=1, max_length=63)] = "date_admitted",
) -> str:
    """Aggregate ALL numeric columns in operational_tbl for a given month and year.

    Use when: "Summarise January 2024", "Show totals for March 2023".
    Computes SUM, AVG, MIN, MAX, COUNT for every numeric column in one call.
    For a single aggregate on one column, prefer gsa_graj_count_records instead.

    Returns JSON with period, rows_matched, and per-column aggregations.

    Error responses:
    - "Invalid month/year" — out-of-range inputs.
    - "Table 'operational_tbl' does not exist." — table not yet loaded.
    - "Date column '…' not found." — wrong date_column name.
    """
    con = _get_conn()
    try:
        exists = con.run("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'operational_tbl'
        """)
        if not exists:
            raise ValueError(
                "Table 'operational_tbl' does not exist. "
                "Load data first using gsa_graj_bulk_excel_to_sl."
            )

        all_cols = con.run("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'operational_tbl'
            ORDER BY ordinal_position
        """)
        col_names = [c[0] for c in all_cols]

        if date_column not in col_names:
            raise ValueError(
                f"Date column '{date_column}' not found. "
                f"Available columns: {', '.join(col_names)}"
            )

        numeric_types = {"integer", "bigint", "smallint", "numeric", "real",
                         "double precision", "decimal", "float"}
        numeric_cols = [
            c[0] for c in all_cols
            if c[1].lower() in numeric_types and c[0] != date_column
        ]

        count_result = con.run(
            f'SELECT COUNT(*) FROM "operational_tbl" '
            f'WHERE EXTRACT(MONTH FROM "{date_column}") = :m '
            f'  AND EXTRACT(YEAR  FROM "{date_column}") = :y',
            m=month, y=year,
        )
        row_count = count_result[0][0]

        if row_count == 0:
            from datetime import date
            month_name = date(year, month, 1).strftime("%B")
            return (
                f"No rows found in 'operational_tbl' for {month_name} {year}.\n"
                f"Date column used: '{date_column}'"
            )

        aggregation = {}
        for col in numeric_cols:
            agg = con.run(
                f'SELECT SUM("{col}"), AVG("{col}"), MIN("{col}"), '
                f'MAX("{col}"), COUNT("{col}") FROM "operational_tbl" '
                f'WHERE EXTRACT(MONTH FROM "{date_column}") = :m '
                f'  AND EXTRACT(YEAR  FROM "{date_column}") = :y',
                m=month, y=year,
            )
            s, a, mn, mx, cnt = agg[0]
            if cnt:
                aggregation[col] = {
                    "sum":   round(float(s),  4) if s  is not None else None,
                    "avg":   round(float(a),  4) if a  is not None else None,
                    "min":   round(float(mn), 4) if mn is not None else None,
                    "max":   round(float(mx), 4) if mx is not None else None,
                    "count": cnt,
                }
    finally:
        con.close()

    from datetime import date as _date
    month_name = _date(year, month, 1).strftime("%B")
    result = {
        "period":       f"{month_name} {year}",
        "rows_matched": row_count,
        "date_column":  date_column,
        "aggregations": aggregation,
    }
    return (
        f"Aggregation results for 'operational_tbl' — {month_name} {year}:\n\n"
        + json.dumps(result, indent=2)
    )


# ── Tool 8: flexible aggregate / count query ──────────────────────────────────

_ALLOWED_AGGREGATES = {"COUNT", "SUM", "AVG", "MIN", "MAX", "COUNT_DISTINCT"}


@mcp.tool(
    name="gsa_graj_count_records",
    annotations={
        "title": "Flexible Aggregate Query",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def gsa_graj_count_records(
    table_name: Annotated[str, Field(description="Table to query, e.g. 'operational_tbl'.", min_length=1, max_length=63)],
    aggregate_function: Annotated[str, Field(description="Aggregation: COUNT, SUM, AVG, MIN, MAX, or COUNT_DISTINCT. Defaults to COUNT.")] = "COUNT",
    aggregate_column: Annotated[Optional[str], Field(description="Column to aggregate. Required for SUM/AVG/MIN/MAX/COUNT_DISTINCT, e.g. 'treatment_cost_usd', 'age_at_admission'.")] = None,
    where_clause: Annotated[Optional[str], Field(description="SQL WHERE clause without WHERE keyword. Combine with AND/OR, e.g. \"discharge_status = 'Discharged' AND city = 'Toronto'\".")] = None,
    group_by_column: Annotated[Optional[str], Field(description="Column to group results by, e.g. 'discharge_status', 'city', 'ward'. Returns one row per distinct value, ordered by result DESC.")] = None,
) -> str:
    """Run any single aggregation query on a PostgreSQL table with optional filtering and grouping.

    Use when: "How many patients?", "Total cost by city", "Average age in Toronto",
              "Count by discharge status", "Max length of stay in 2024".
    Supports COUNT, SUM, AVG, MIN, MAX, COUNT_DISTINCT on any column.

    For a full multi-column monthly summary, use gsa_graj_aggregate_operational_tbl instead.

    Returns the scalar result or a JSON array of {group, <agg_label>} objects when group_by_column is set.

    Error responses:
    - "Unsupported aggregate_function '…'" — unknown function name.
    - "aggregate_column is required when aggregate_function is '…'" — missing column.
    """
    func = aggregate_function.strip().upper()
    if func not in _ALLOWED_AGGREGATES:
        return (
            f"Unsupported aggregate_function '{aggregate_function}'. "
            f"Allowed values: {', '.join(sorted(_ALLOWED_AGGREGATES))}."
        )

    if func != "COUNT" and not aggregate_column:
        return (
            f"aggregate_column is required when aggregate_function is '{func}'. "
            "Provide the column name to aggregate (e.g. 'treatment_cost_usd')."
        )

    if func == "COUNT_DISTINCT":
        agg_expr  = f'COUNT(DISTINCT "{aggregate_column}")'
        agg_label = f"COUNT(DISTINCT {aggregate_column})"
    elif func == "COUNT":
        agg_expr  = "COUNT(*)"
        agg_label = "COUNT(*)"
    else:
        agg_expr  = f'{func}("{aggregate_column}")'
        agg_label = f"{func}({aggregate_column})"

    con = _get_conn()
    try:
        if group_by_column:
            sql = (
                f'SELECT "{group_by_column}", {agg_expr} AS result '
                f'FROM "{table_name}"'
            )
            if where_clause:
                sql += f" WHERE {where_clause}"
            sql += f' GROUP BY "{group_by_column}" ORDER BY result DESC'
            rows = con.run(sql)
            results = [
                {"group": r[0], agg_label: float(r[1]) if r[1] is not None else None}
                for r in rows
            ]
            label_parts = [f"{agg_label} from '{table_name}'"]
            label_parts.append(f"grouped by '{group_by_column}'")
            if where_clause:
                label_parts.append(f"where {where_clause}")
            return (
                " ".join(label_parts) + ":\n\n"
                + json.dumps(results, indent=2, default=str)
            )
        else:
            sql = f'SELECT {agg_expr} FROM "{table_name}"'
            if where_clause:
                sql += f" WHERE {where_clause}"
            value = con.run(sql)[0][0]
            if isinstance(value, float):
                value = round(value, 4)
            label_parts = [f"{agg_label} from '{table_name}'"]
            if where_clause:
                label_parts.append(f"where {where_clause}")
            return " ".join(label_parts) + f": {value}"
    finally:
        con.close()


# ── Tool 9: flexible slice/aggregate query on operational_tbl ─────────────────

# Columns that exist in operational_tbl and may be used in queries.
# This allowlist prevents injection via column-name parameters.
_OT_ALLOWED_COLUMNS: frozenset[str] = frozenset({
    "patient_id", "name", "gender", "dob", "age_at_admission", "city",
    "blood_group", "date_admitted", "health_issue", "ward",
    "attending_doctor", "discharge_date", "length_of_stay_days",
    "discharge_status", "treatment_cost_usd",
})

# Columns that are numeric and may be used with SUM / AVG / MIN / MAX.
_OT_NUMERIC_COLUMNS: frozenset[str] = frozenset({
    "age_at_admission", "length_of_stay_days", "treatment_cost_usd",
})

# Aggregate functions supported by this tool.
_OT_ALLOWED_AGGREGATES: frozenset[str] = frozenset({
    "COUNT", "COUNT_DISTINCT", "SUM", "AVG", "MIN", "MAX",
})

# Date granularities for GROUP BY on date columns.
_OT_DATE_GRANULARITIES: frozenset[str] = frozenset({
    "day", "week", "month", "quarter", "year",
})

# Date columns in operational_tbl.
_OT_DATE_COLUMNS: frozenset[str] = frozenset({
    "dob", "date_admitted", "discharge_date",
})

# Maximum rows a single call may return (guards against accidental full-table dumps).
_OT_MAX_ROWS: int = 500


def _ot_validate_column(col: str, label: str = "column") -> str:
    """Return col if it is in the allowlist, else raise ValueError."""
    if col not in _OT_ALLOWED_COLUMNS:
        raise ValueError(
            f"Unknown {label} '{col}'. "
            f"Allowed columns: {', '.join(sorted(_OT_ALLOWED_COLUMNS))}"
        )
    return col


def _ot_validate_aggregate(func: str) -> str:
    """Return the uppercased function if allowed, else raise ValueError."""
    up = func.strip().upper()
    if up not in _OT_ALLOWED_AGGREGATES:
        raise ValueError(
            f"Unsupported aggregate_function '{func}'. "
            f"Allowed: {', '.join(sorted(_OT_ALLOWED_AGGREGATES))}"
        )
    return up


def _ot_build_agg_expr(func: str, col: Optional[str]) -> tuple[str, str]:
    """Return (sql_expression, human_label) for an aggregate.

    Raises ValueError for numeric-only functions applied to non-numeric columns.
    """
    if func == "COUNT":
        return "COUNT(*)", "COUNT(*)"
    if not col:
        raise ValueError(
            f"aggregate_column is required when aggregate_function is '{func}'."
        )
    _ot_validate_column(col, "aggregate_column")
    if func in {"SUM", "AVG"} and col not in _OT_NUMERIC_COLUMNS:
        raise ValueError(
            f"aggregate_function '{func}' cannot be applied to non-numeric "
            f"column '{col}'. Numeric columns: {', '.join(sorted(_OT_NUMERIC_COLUMNS))}"
        )
    if func == "COUNT_DISTINCT":
        return f'COUNT(DISTINCT "{col}")', f"COUNT(DISTINCT {col})"
    return f'{func}("{col}")', f"{func}({col})"


def _ot_date_group_expr(col: str, granularity: str) -> tuple[str, str]:
    """Return (GROUP BY expression, SELECT alias) for date truncation."""
    gran = granularity.lower()
    if gran not in _OT_DATE_GRANULARITIES:
        raise ValueError(
            f"Unsupported date_granularity '{granularity}'. "
            f"Allowed: {', '.join(sorted(_OT_DATE_GRANULARITIES))}"
        )
    if col not in _OT_DATE_COLUMNS:
        raise ValueError(
            f"date_granularity requires a date column. "
            f"Date columns: {', '.join(sorted(_OT_DATE_COLUMNS))}"
        )
    if gran == "year":
        expr = f'EXTRACT(YEAR FROM "{col}")::int'
        alias = f"year_{col}"
    elif gran == "quarter":
        expr = f"TO_CHAR(\"{col}\", 'YYYY-\"Q\"Q')"
        alias = f"quarter_{col}"
    elif gran == "month":
        expr = f"TO_CHAR(\"{col}\", 'YYYY-MM')"
        alias = f"month_{col}"
    elif gran == "week":
        expr = f"TO_CHAR(DATE_TRUNC('week', \"{col}\"), 'IYYY-IW')"
        alias = f"week_{col}"
    else:  # day
        expr = f'CAST("{col}" AS text)'
        alias = f"day_{col}"
    return expr, alias


@mcp.tool(
    name="gsa_graj_query_operational_tbl",
    annotations={
        "title": "Flexible Slice & Aggregate on operational_tbl",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def gsa_graj_query_operational_tbl(
    # ── What to return ────────────────────────────────────────────────────────
    select_columns: Annotated[
        Optional[str],
        Field(
            description=(
                "Comma-separated list of columns to SELECT for data-slice mode, "
                "e.g. 'patient_id,name,city,treatment_cost_usd'. "
                "Omit when using aggregate_function. "
                "Never use '*' — list columns explicitly."
            )
        ),
    ] = None,
    aggregate_function: Annotated[
        Optional[str],
        Field(
            description=(
                "Aggregation to compute: COUNT, COUNT_DISTINCT, SUM, AVG, MIN, MAX. "
                "Omit for a data-slice (row-level) result. "
                "SUM/AVG require a numeric column in aggregate_column. "
                "MIN/MAX work on numeric, date, and text columns."
            )
        ),
    ] = None,
    aggregate_column: Annotated[
        Optional[str],
        Field(
            description=(
                "Column to aggregate when aggregate_function is not COUNT. "
                "Must be from the allowed column list."
            )
        ),
    ] = None,
    # ── Grouping ──────────────────────────────────────────────────────────────
    group_by_columns: Annotated[
        Optional[str],
        Field(
            description=(
                "Comma-separated columns to GROUP BY, e.g. 'ward,discharge_status'. "
                "Use with aggregate_function. "
                "For date grouping by period, combine with date_granularity."
            )
        ),
    ] = None,
    date_granularity: Annotated[
        Optional[str],
        Field(
            description=(
                "Apply date truncation on group_by_columns that are date columns. "
                "One of: day, week, month, quarter, year. "
                "Only used when group_by_columns contains a date column."
            )
        ),
    ] = None,
    # ── Filtering ─────────────────────────────────────────────────────────────
    where_clause: Annotated[
        Optional[str],
        Field(
            description=(
                "SQL WHERE clause without the WHERE keyword. "
                "Combine conditions with AND/OR. "
                "Use parameterized literals inline, e.g.: "
                "\"city = 'Boston' AND age_at_admission > 60 "
                "AND date_admitted BETWEEN '2025-01-01' AND '2025-12-31'\". "
                "Null checks: \"discharge_date IS NULL\"."
            )
        ),
    ] = None,
    having_clause: Annotated[
        Optional[str],
        Field(
            description=(
                "SQL HAVING clause without the HAVING keyword. "
                "Applied after GROUP BY. Example: "
                "\"COUNT(*) > 100 AND AVG(treatment_cost_usd) > 5000\"."
            )
        ),
    ] = None,
    # ── Sorting & pagination ──────────────────────────────────────────────────
    order_by: Annotated[
        Optional[str],
        Field(
            description=(
                "ORDER BY expression without the ORDER BY keyword, e.g. "
                "'treatment_cost_usd DESC' or 'city ASC, date_admitted DESC'. "
                "For aggregate results use the aggregate alias 'result'."
            )
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(description=f"Maximum rows to return (1–{_OT_MAX_ROWS}). Default 100.", ge=1, le=_OT_MAX_ROWS),
    ] = 100,
    offset: Annotated[
        int,
        Field(description="Row offset for pagination. Default 0.", ge=0),
    ] = 0,
) -> str:
    """Run any read-only slice or aggregate query on operational_tbl.

    Covers all requests that the existing gsa_graj_count_records tool handles
    for one-column grouping, plus:
      • Multi-column GROUP BY                 (group_by_columns)
      • HAVING filters on aggregates          (having_clause)
      • Date-period grouping (month/quarter)  (date_granularity)
      • Explicit column selection             (select_columns)
      • Deterministic pagination              (offset)
      • Percentage distributions              (compute from returned counts)

    Use when:
      "Show record counts by gender and blood group"
      "Total and average cost by ward"
      "Monthly record counts for 2024"
      "Wards with more than 100 records and average cost above $5000"
      "Top 5 cities by total treatment cost"
      "Records for patients older than 60 in Boston admitted in 2025"
      "Records with missing discharge dates"
      "Compare quarterly costs for 2024 and 2025"

    Column allowlist (enforced server-side):
      patient_id, name, gender, dob, age_at_admission, city, blood_group,
      date_admitted, health_issue, ward, attending_doctor, discharge_date,
      length_of_stay_days, discharge_status, treatment_cost_usd

    Numeric columns (SUM/AVG only):
      age_at_admission, length_of_stay_days, treatment_cost_usd

    Returns JSON with:
      sql, row_count, columns, rows, warnings, notes

    Error responses:
      - Unknown column name → allowlist error.
      - SUM/AVG on non-numeric column → type error.
      - Both select_columns and aggregate_function set → usage error.
      - PostgreSQL runtime error → exact pg8000 message.
    """
    warnings_list: list[str] = []
    notes_list: list[str] = []

    # ── Mutual-exclusion guard ────────────────────────────────────────────────
    if select_columns and aggregate_function:
        return json.dumps({
            "error": (
                "Specify either select_columns (data-slice mode) "
                "or aggregate_function (aggregate mode), not both."
            )
        })

    # ── Validate & parse group_by_columns ─────────────────────────────────────
    parsed_groups: list[str] = []
    if group_by_columns:
        raw_groups = [c.strip() for c in group_by_columns.split(",") if c.strip()]
        for g in raw_groups:
            try:
                _ot_validate_column(g, "group_by column")
            except ValueError as exc:
                return json.dumps({"error": str(exc)})
            parsed_groups.append(g)

    # ── Build SELECT expressions for group-by columns (with date granularity) ─
    select_group_exprs: list[str] = []  # SQL fragments in SELECT
    group_by_exprs: list[str] = []      # SQL fragments in GROUP BY
    result_col_aliases: list[str] = []  # human-readable column names in result

    for g in parsed_groups:
        if g in _OT_DATE_COLUMNS and date_granularity:
            try:
                trunc_expr, alias = _ot_date_group_expr(g, date_granularity)
            except ValueError as exc:
                return json.dumps({"error": str(exc)})
            select_group_exprs.append(f"{trunc_expr} AS {alias}")
            group_by_exprs.append(trunc_expr)
            result_col_aliases.append(alias)
        else:
            select_group_exprs.append(f'"{g}"')
            group_by_exprs.append(f'"{g}"')
            result_col_aliases.append(g)

    # ── Build the aggregate or slice SELECT list ───────────────────────────────
    is_aggregate = bool(aggregate_function)

    if is_aggregate:
        func_up = aggregate_function.strip().upper()
        try:
            agg_expr, agg_label = _ot_build_agg_expr(func_up, aggregate_column)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

        if select_group_exprs:
            select_list = ", ".join(select_group_exprs) + f", {agg_expr} AS result"
            result_columns = result_col_aliases + ["result"]
        else:
            select_list = f"{agg_expr} AS result"
            result_columns = ["result"]

        notes_list.append(f"Aggregate: {agg_label}")

        if func_up == "COUNT" and not aggregate_column:
            notes_list.append(
                "COUNT(*) counts all matched rows including those with NULLs."
            )
        elif func_up == "COUNT_DISTINCT":
            notes_list.append(
                f"COUNT(DISTINCT {aggregate_column}) counts distinct non-NULL "
                f"values in '{aggregate_column}'."
            )
        else:
            notes_list.append(
                f"{func_up} is computed over non-NULL values in '{aggregate_column}'."
            )

    else:
        # Data-slice mode: validate explicitly listed columns.
        if select_columns:
            raw_sel = [c.strip() for c in select_columns.split(",") if c.strip()]
            for c in raw_sel:
                try:
                    _ot_validate_column(c, "select column")
                except ValueError as exc:
                    return json.dumps({"error": str(exc)})
            select_list = ", ".join(f'"{c}"' for c in raw_sel)
            result_columns = raw_sel
        else:
            # Default: return all allowed columns (never SELECT *).
            default_cols = sorted(_OT_ALLOWED_COLUMNS)
            select_list = ", ".join(f'"{c}"' for c in default_cols)
            result_columns = default_cols
            notes_list.append(
                "No select_columns specified — returning all authorized columns. "
                "Specify select_columns to request only the fields you need."
            )

    # ── Assemble SQL ──────────────────────────────────────────────────────────
    sql_parts = [f'SELECT {select_list} FROM "operational_tbl"']

    if where_clause:
        sql_parts.append(f"WHERE {where_clause}")

    if group_by_exprs:
        sql_parts.append("GROUP BY " + ", ".join(group_by_exprs))

    if having_clause:
        if not group_by_exprs:
            return json.dumps({
                "error": "having_clause requires group_by_columns to be set."
            })
        sql_parts.append(f"HAVING {having_clause}")

    if order_by:
        sql_parts.append(f"ORDER BY {order_by}")
    elif is_aggregate and group_by_exprs:
        # Default: highest aggregate value first for readability.
        sql_parts.append("ORDER BY result DESC")

    sql_parts.append(f"LIMIT {limit}")
    if offset:
        sql_parts.append(f"OFFSET {offset}")

    sql = "\n".join(sql_parts)

    # ── Execute ───────────────────────────────────────────────────────────────
    con = _get_conn()
    try:
        raw_rows = con.run(sql)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"Query failed: {exc}", "sql": sql})
    finally:
        con.close()

    rows = [dict(zip(result_columns, r)) for r in raw_rows]

    # ── Null-value disclosure ─────────────────────────────────────────────────
    null_cols = [c for c in result_columns if any(r.get(c) is None for r in rows)]
    if null_cols:
        warnings_list.append(
            f"NULL values present in: {', '.join(null_cols)}. "
            "Aggregate functions (SUM/AVG/MIN/MAX/COUNT(col)) exclude NULLs."
        )

    if limit == len(raw_rows):
        warnings_list.append(
            f"Result was capped at the requested limit of {limit} rows. "
            "Use offset= for pagination or add more WHERE filters."
        )

    # ── Scalar result shortcut ────────────────────────────────────────────────
    if is_aggregate and not group_by_exprs and rows:
        scalar = rows[0].get("result")
        if isinstance(scalar, float):
            scalar = round(scalar, 4)
        summary = f"{agg_label} from 'operational_tbl'"
        if where_clause:
            summary += f" WHERE {where_clause}"
        summary += f": {scalar}"
        return json.dumps(
            {
                "sql": sql,
                "result": scalar,
                "summary": summary,
                "notes": notes_list,
                "warnings": warnings_list,
            },
            indent=2,
            default=str,
        )

    return json.dumps(
        {
            "sql": sql,
            "row_count": len(rows),
            "columns": result_columns,
            "rows": rows,
            "notes": notes_list,
            "warnings": warnings_list,
        },
        indent=2,
        default=str,
    )


# ── Health / root endpoint (HTTP mode only) ────────────────────────────────────

def _add_health_route(app):
    """Attach a simple GET / and GET /health route to the Starlette app."""
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def health(request: Request):
        return JSONResponse({
            "status": "ok",
            "service": "gsa_graj_tools",
            "mcp_endpoint": "/mcp",
            "tools": [
                "gsa_graj_current_weather",
                "gsa_graj_programming_joke",
                "gsa_graj_unit_converter",
                "gsa_graj_connect_sl_db",
                "gsa_graj_read_from_sl",
                "gsa_graj_write_to_sl",
                "gsa_graj_aggregate_operational_tbl",
                "gsa_graj_count_records",
                "gsa_graj_query_operational_tbl",
            ],
        })

    app.routes.insert(0, Route("/", health, methods=["GET"]))
    app.routes.insert(1, Route("/health", health, methods=["GET"]))


# ── Entry-point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port_env = os.environ.get("PORT")
    if port_env:
        port = int(port_env)
        print(f"gsa_graj_tools starting HTTP transport on port {port}", file=sys.stderr)
        import uvicorn
        starlette_app = mcp.http_app()
        _add_health_route(starlette_app)
        uvicorn.run(starlette_app, host="0.0.0.0", port=port)
    else:
        mcp.run(transport="stdio")
