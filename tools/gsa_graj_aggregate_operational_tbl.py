"""gsa_graj_aggregate_operational_tbl — standalone WXO tool.

BACKWARD COMPATIBILITY: The original three parameters (month, year,
date_column) are unchanged.  New optional parameters extend the tool
without breaking existing callers.

Extended capabilities (new optional parameters):
  select_columns   — explicit column list for data-slice mode
  aggregate_function / aggregate_column — single aggregate in addition to
                     the existing full multi-column summary
  group_by_columns — comma-separated GROUP BY columns (multi-column support)
  date_granularity — day | week | month | quarter | year truncation for dates
  having_clause    — HAVING filter applied after GROUP BY
  where_clause     — arbitrary WHERE filter (overrides month/year when set)
  order_by         — ORDER BY expression
  limit            — maximum rows returned (default 100, max 500)
  offset           — pagination offset

When all new parameters are omitted the tool behaves exactly as before:
  - Filters operational_tbl by month+year on date_column.
  - Computes SUM, AVG, MIN, MAX, COUNT for every numeric column.
  - Returns a JSON summary keyed by column.

Column allowlist (all modes):
  patient_id, name, gender, dob, age_at_admission, city, blood_group,
  date_admitted, health_issue, ward, attending_doctor, discharge_date,
  length_of_stay_days, discharge_status, treatment_cost_usd

Numeric columns (SUM/AVG only):
  age_at_admission, length_of_stay_days, treatment_cost_usd
"""

from __future__ import annotations

import json
from datetime import date as _date
from typing import Optional

from ibm_watsonx_orchestrate.agent_builder.tools import tool
from db_config import get_conn


# ── Allowlists ────────────────────────────────────────────────────────────────

_ALLOWED_COLUMNS: frozenset[str] = frozenset({
    "patient_id", "name", "gender", "dob", "age_at_admission", "city",
    "blood_group", "date_admitted", "health_issue", "ward",
    "attending_doctor", "discharge_date", "length_of_stay_days",
    "discharge_status", "treatment_cost_usd",
})

_NUMERIC_COLUMNS: frozenset[str] = frozenset({
    "age_at_admission", "length_of_stay_days", "treatment_cost_usd",
})

_NUMERIC_TYPES: frozenset[str] = frozenset({
    "integer", "bigint", "smallint", "numeric", "real",
    "double precision", "decimal", "float",
})

_ALLOWED_AGGREGATES: frozenset[str] = frozenset({
    "COUNT", "COUNT_DISTINCT", "SUM", "AVG", "MIN", "MAX",
})

_DATE_GRANULARITIES: frozenset[str] = frozenset({
    "day", "week", "month", "quarter", "year",
})

_DATE_COLUMNS: frozenset[str] = frozenset({
    "dob", "date_admitted", "discharge_date",
})

_MAX_ROWS: int = 500


# ── Internal helpers ──────────────────────────────────────────────────────────

def _validate_column(col: str, label: str = "column") -> str:
    if col not in _ALLOWED_COLUMNS:
        raise ValueError(
            f"Unknown {label} '{col}'. "
            f"Allowed columns: {', '.join(sorted(_ALLOWED_COLUMNS))}"
        )
    return col


def _build_agg_expr(func: str, col: Optional[str]) -> tuple[str, str]:
    """Return (sql_expression, human_label). Raises ValueError on type mismatch."""
    if func == "COUNT":
        return "COUNT(*)", "COUNT(*)"
    if not col:
        raise ValueError(
            f"aggregate_column is required when aggregate_function is '{func}'."
        )
    _validate_column(col, "aggregate_column")
    if func in {"SUM", "AVG"} and col not in _NUMERIC_COLUMNS:
        raise ValueError(
            f"aggregate_function '{func}' cannot be applied to non-numeric "
            f"column '{col}'. Numeric columns: {', '.join(sorted(_NUMERIC_COLUMNS))}"
        )
    if func == "COUNT_DISTINCT":
        return f'COUNT(DISTINCT "{col}")', f"COUNT(DISTINCT {col})"
    return f'{func}("{col}")', f"{func}({col})"


def _date_group_expr(col: str, granularity: str) -> tuple[str, str]:
    """Return (GROUP BY SQL expression, alias) for date truncation."""
    gran = granularity.lower()
    if gran not in _DATE_GRANULARITIES:
        raise ValueError(
            f"Unsupported date_granularity '{granularity}'. "
            f"Allowed: {', '.join(sorted(_DATE_GRANULARITIES))}"
        )
    if col not in _DATE_COLUMNS:
        raise ValueError(
            f"date_granularity requires a date column. "
            f"Date columns: {', '.join(sorted(_DATE_COLUMNS))}"
        )
    if gran == "year":
        return f'EXTRACT(YEAR FROM "{col}")::int', f"year_{col}"
    if gran == "quarter":
        return f"TO_CHAR(\"{col}\", 'YYYY-\"Q\"Q')", f"quarter_{col}"
    if gran == "month":
        return f"TO_CHAR(\"{col}\", 'YYYY-MM')", f"month_{col}"
    if gran == "week":
        return f"TO_CHAR(DATE_TRUNC('week', \"{col}\"), 'IYYY-IW')", f"week_{col}"
    # day
    return f'CAST("{col}" AS text)', f"day_{col}"


# ── Tool ──────────────────────────────────────────────────────────────────────

@tool()
def gsa_graj_aggregate_operational_tbl(
    # ── Original parameters (unchanged — backward compatible) ─────────────────
    month: int,
    year: int,
    date_column: Optional[str] = "date_admitted",
    # ── Extended parameters (all optional, default to None / legacy behaviour) ─
    select_columns: Optional[str] = None,
    aggregate_function: Optional[str] = None,
    aggregate_column: Optional[str] = None,
    group_by_columns: Optional[str] = None,
    date_granularity: Optional[str] = None,
    having_clause: Optional[str] = None,
    where_clause: Optional[str] = None,
    order_by: Optional[str] = None,
    limit: Optional[int] = 100,
    offset: Optional[int] = 0,
) -> str:
    """Aggregate or slice operational_tbl — full multi-column summary or flexible query.

    ── ORIGINAL behaviour (backward compatible) ─────────────────────────────
    When only month, year, and optionally date_column are supplied, the tool
    behaves exactly as before: it filters operational_tbl to the given
    month+year and returns SUM, AVG, MIN, MAX, COUNT for every numeric column.

    Args:
        month (int): Month number to filter on (1–12).
        year (int): Four-digit year to filter on (e.g. 2024).
        date_column (str, optional): Date column for the month+year filter.
            Defaults to 'date_admitted'. Ignored when where_clause is set.

    ── EXTENDED behaviour (new optional parameters) ─────────────────────────
    Supply any combination of the extended parameters to run a custom query.

    Args:
        select_columns (str, optional): Comma-separated columns for a data
            slice, e.g. 'patient_id,city,treatment_cost_usd'.
            Cannot be combined with aggregate_function.
        aggregate_function (str, optional): One of COUNT, COUNT_DISTINCT,
            SUM, AVG, MIN, MAX.  SUM/AVG require a numeric aggregate_column.
        aggregate_column (str, optional): Column to aggregate.
        group_by_columns (str, optional): Comma-separated GROUP BY columns,
            e.g. 'ward,discharge_status'.
        date_granularity (str, optional): day | week | month | quarter | year.
            Applied to date columns in group_by_columns.
        having_clause (str, optional): HAVING expression without the keyword,
            e.g. "COUNT(*) > 100 AND AVG(treatment_cost_usd) > 5000".
            Requires group_by_columns.
        where_clause (str, optional): SQL WHERE clause without the keyword.
            When supplied, overrides the month+year filter entirely.
        order_by (str, optional): ORDER BY expression without the keyword.
        limit (int, optional): Maximum rows (1–500). Default 100.
        offset (int, optional): Pagination offset. Default 0.

    Returns:
        str: JSON string — either the original monthly summary or a structured
             query result with sql, row_count, columns, rows, notes, warnings.
    """

    # ── Input validation ──────────────────────────────────────────────────────
    if not (1 <= month <= 12):
        raise ValueError(f"Invalid month: {month}. Must be between 1 and 12.")
    if year < 1900 or year > 2100:
        raise ValueError(f"Invalid year: {year}.")

    effective_limit = max(1, min(int(limit or 100), _MAX_ROWS))
    effective_offset = max(0, int(offset or 0))

    # ── ORIGINAL MODE: no extended parameters supplied ────────────────────────
    # Detect by checking whether the caller touched any of the new params.
    _using_extended = any([
        select_columns, aggregate_function, aggregate_column,
        group_by_columns, date_granularity, having_clause,
        where_clause, order_by,
    ])

    if not _using_extended:
        return _legacy_monthly_summary(month, year, date_column)

    # ── EXTENDED MODE ─────────────────────────────────────────────────────────

    warnings_list: list[str] = []
    notes_list: list[str] = []

    # Mutual-exclusion guard.
    if select_columns and aggregate_function:
        return json.dumps({
            "error": (
                "Specify either select_columns (data-slice mode) "
                "or aggregate_function (aggregate mode), not both."
            )
        })

    # Validate & parse group_by_columns.
    parsed_groups: list[str] = []
    if group_by_columns:
        for g in [c.strip() for c in group_by_columns.split(",") if c.strip()]:
            try:
                _validate_column(g, "group_by column")
            except ValueError as exc:
                return json.dumps({"error": str(exc)})
            parsed_groups.append(g)

    # Build SELECT / GROUP BY expressions with optional date truncation.
    select_group_exprs: list[str] = []
    group_by_exprs: list[str] = []
    result_col_aliases: list[str] = []

    for g in parsed_groups:
        if g in _DATE_COLUMNS and date_granularity:
            try:
                trunc_expr, alias = _date_group_expr(g, date_granularity)
            except ValueError as exc:
                return json.dumps({"error": str(exc)})
            select_group_exprs.append(f"{trunc_expr} AS {alias}")
            group_by_exprs.append(trunc_expr)
            result_col_aliases.append(alias)
        else:
            select_group_exprs.append(f'"{g}"')
            group_by_exprs.append(f'"{g}"')
            result_col_aliases.append(g)

    is_aggregate = bool(aggregate_function)

    if is_aggregate:
        func_up = aggregate_function.strip().upper()
        if func_up not in _ALLOWED_AGGREGATES:
            return json.dumps({
                "error": (
                    f"Unsupported aggregate_function '{aggregate_function}'. "
                    f"Allowed: {', '.join(sorted(_ALLOWED_AGGREGATES))}"
                )
            })
        try:
            agg_expr, agg_label = _build_agg_expr(func_up, aggregate_column)
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
            notes_list.append("COUNT(*) counts all matched rows including NULLs.")
        elif func_up == "COUNT_DISTINCT":
            notes_list.append(
                f"COUNT(DISTINCT {aggregate_column}) counts distinct non-NULL values."
            )
        else:
            notes_list.append(
                f"{func_up} excludes NULL values in '{aggregate_column}'."
            )
    else:
        # Data-slice mode.
        if select_columns:
            raw_sel = [c.strip() for c in select_columns.split(",") if c.strip()]
            for c in raw_sel:
                try:
                    _validate_column(c, "select column")
                except ValueError as exc:
                    return json.dumps({"error": str(exc)})
            select_list = ", ".join(f'"{c}"' for c in raw_sel)
            result_columns = raw_sel
        else:
            default_cols = sorted(_ALLOWED_COLUMNS)
            select_list = ", ".join(f'"{c}"' for c in default_cols)
            result_columns = default_cols
            notes_list.append(
                "No select_columns specified — returning all authorized columns."
            )

    # Build the WHERE clause.
    # If the caller did not supply where_clause, fall back to month+year filter.
    effective_where = where_clause
    if not effective_where and date_column:
        try:
            _validate_column(date_column, "date_column")
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        effective_where = (
            f'EXTRACT(MONTH FROM "{date_column}") = {month} '
            f'AND EXTRACT(YEAR FROM "{date_column}") = {year}'
        )
        notes_list.append(
            f"Month+year filter applied: {date_column} in "
            f"{_date(year, month, 1).strftime('%B %Y')}."
        )

    # Assemble SQL.
    sql_parts = [f'SELECT {select_list} FROM "operational_tbl"']
    if effective_where:
        sql_parts.append(f"WHERE {effective_where}")
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
        sql_parts.append("ORDER BY result DESC")
    sql_parts.append(f"LIMIT {effective_limit}")
    if effective_offset:
        sql_parts.append(f"OFFSET {effective_offset}")

    sql = "\n".join(sql_parts)

    # Execute.
    con = get_conn()
    try:
        raw_rows = con.run(sql)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"Query failed: {exc}", "sql": sql})
    finally:
        con.close()

    rows = [dict(zip(result_columns, r)) for r in raw_rows]

    # Null-value disclosure.
    null_cols = [c for c in result_columns if any(r.get(c) is None for r in rows)]
    if null_cols:
        warnings_list.append(
            f"NULL values present in: {', '.join(null_cols)}. "
            "Aggregate functions exclude NULLs."
        )
    if effective_limit == len(raw_rows):
        warnings_list.append(
            f"Result capped at {effective_limit} rows. "
            "Use offset for pagination."
        )

    # Scalar shortcut for un-grouped aggregates.
    if is_aggregate and not group_by_exprs and rows:
        scalar = rows[0].get("result")
        if isinstance(scalar, float):
            scalar = round(scalar, 4)
        summary = f"{agg_label} from 'operational_tbl'"
        if effective_where:
            summary += f" WHERE {effective_where}"
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


# ── Original implementation (preserved for backward compatibility) ─────────────

def _legacy_monthly_summary(month: int, year: int, date_column: str) -> str:
    """Original full multi-column monthly summary — called when no extended
    parameters are used so the return format is identical to the previous version.
    """
    con = get_conn()
    try:
        exists = con.run("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'operational_tbl'
        """)
        if not exists:
            raise ValueError(
                "Table 'operational_tbl' does not exist in PostgreSQL. "
                "Load your Excel file first using gsa_graj_bulk_excel_to_sl."
            )

        all_cols = con.run("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'operational_tbl'
            ORDER BY ordinal_position
        """)
        col_names = [c[0] for c in all_cols]

        if date_column not in col_names:
            raise ValueError(
                f"Date column '{date_column}' not found in operational_tbl. "
                f"Available columns: {', '.join(col_names)}"
            )

        numeric_cols = [
            c[0] for c in all_cols
            if c[1].lower() in _NUMERIC_TYPES and c[0] != date_column
        ]

        count_rows = con.run(
            f'SELECT COUNT(*) FROM "operational_tbl" '
            f'WHERE EXTRACT(MONTH FROM "{date_column}") = :m '
            f'  AND EXTRACT(YEAR  FROM "{date_column}") = :y',
            m=month, y=year,
        )
        row_count = count_rows[0][0]

        if row_count == 0:
            month_name = _date(year, month, 1).strftime("%B")
            return (
                f"No rows found in 'operational_tbl' for {month_name} {year}.\n"
                f"Date column used: '{date_column}'"
            )

        aggregation = {}
        for col in numeric_cols:
            agg = con.run(
                f'SELECT SUM("{col}"), AVG("{col}"), MIN("{col}"), MAX("{col}"), '
                f'COUNT("{col}") FROM "operational_tbl" '
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
