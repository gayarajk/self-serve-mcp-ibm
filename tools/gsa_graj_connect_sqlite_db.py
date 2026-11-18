from ibm_watsonx_orchestrate.agent_builder.tools import tool
from db_config import get_conn, PG_DB, PG_HOST


@tool()
def gsa_graj_connect_sqlite_db() -> str:
    """Connect to the PostgreSQL database and return its schema.

    Connects to the wxodb PostgreSQL database and retrieves the list of all
    tables in the public schema along with their column definitions.

    Returns:
        str: A summary showing the database name, all table names, and their
             column definitions.
    """
    con = get_conn()
    try:
        rows = con.run("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        tables = [r[0] for r in rows]

        if not tables:
            return (
                f"Connected to PostgreSQL database '{PG_DB}' @ {PG_HOST}.\n"
                "No tables found yet. Use gsa_graj_bulk_excel_to_sl to load data."
            )

        schema_lines = []
        for table in tables:
            cols = con.run("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :table
                ORDER BY ordinal_position
            """, table=table)
            col_desc = ", ".join(f"{c[0]} ({c[1]})" for c in cols)
            schema_lines.append(f"  [{table}]  {col_desc}")

        schema_str = "\n".join(schema_lines)
    finally:
        con.close()

    return (
        f"Connected to PostgreSQL database '{PG_DB}' @ {PG_HOST}.\n"
        f"Tables found ({len(tables)}):\n{schema_str}"
    )
