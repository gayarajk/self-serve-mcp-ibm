import sqlite3
from pathlib import Path
from typing import Optional

from ibm_watsonx_orchestrate.agent_builder.tools import tool


@tool()
def gsa_graj_create_sqlite_db(
    db_filename: Optional[str] = "excel_data.db",
    table_name: Optional[str] = "excel_data",
    columns: Optional[str] = "id INTEGER PRIMARY KEY, name TEXT, value TEXT",
) -> str:
    """Create a SQLite database in the Downloads folder with a specified table schema.

    Creates a new SQLite database file in the user's Downloads directory and
    initialises it with a single table using the provided column definitions.
    If the database already exists, it is reused and the table is created only
    if it does not already exist.

    Args:
        db_filename (str, optional): Name of the SQLite database file to create
            inside the Downloads folder. Defaults to 'excel_data.db'.
        table_name (str, optional): Name of the table to create inside the database.
            Defaults to 'excel_data'.
        columns (str, optional): SQL column definitions for the table, e.g.
            'id INTEGER PRIMARY KEY, name TEXT, value TEXT'.
            Defaults to 'id INTEGER PRIMARY KEY, name TEXT, value TEXT'.

    Returns:
        str: A summary message confirming the database and table were created,
             along with the full path to the database file.
    """
    downloads_dir = Path.home() / "Downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)

    db_path = downloads_dir / db_filename

    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute(
            f'CREATE TABLE IF NOT EXISTS "{table_name}" ({columns})'
        )
        con.commit()
    finally:
        con.close()

    return (
        f"SQLite database ready.\n"
        f"  Database : {db_path}\n"
        f"  Table    : {table_name}\n"
        f"  Columns  : {columns}"
    )
