import json
from typing import Optional

from ibm_watsonx_orchestrate.agent_builder.tools import tool
from db_config import get_conn, PG_DB


@tool()
def gsa_graj_read_from_sqlite(
    table_name: str,
    where_clause: Optional[str] = None,
    limit: Optional[int] = 100,
) -> str:
    """Read rows from a table in the PostgreSQL database.

    Executes a SELECT query against the given table in the wxodb PostgreSQL
    database. An optional WHERE clause can be provided to filter results.

    Args:
        table_name (str): Name of the table to read from.
        where_clause (str, optional): A SQL WHERE clause (without the 'WHERE'
            keyword) to filter rows, e.g. "city = 'Toronto' AND age_at_admission > 5".
            If omitted, all rows are returned up to the limit.
        limit (int, optional): Maximum number of rows to return. Defaults to 100.

    Returns:
        str: A JSON-formatted string containing the list of rows as objects,
             plus a summary of how many rows were returned.
    """
    con = get_conn()
    try:
        # Get column names first
        col_rows = con.run("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = :tbl
            ORDER BY ordinal_position
        """, tbl=table_name)
        columns = [c[0] for c in col_rows]

        sql = f'SELECT * FROM "{table_name}"'
        if where_clause:
            sql += f" WHERE {where_clause}"
        if limit is not None:
            sql += f" LIMIT {limit}"

        data = con.run(sql)
        rows = [dict(zip(columns, row)) for row in data]
    finally:
        con.close()

    result = json.dumps(rows, indent=2, default=str)
    return (
        f"Read {len(rows)} row(s) from table '{table_name}' in PostgreSQL '{PG_DB}'.\n\n"
        f"{result}"
    )
