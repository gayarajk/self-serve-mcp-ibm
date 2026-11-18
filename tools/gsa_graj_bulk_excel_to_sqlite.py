import sqlite3
from pathlib import Path
from typing import Optional

from ibm_watsonx_orchestrate.agent_builder.tools import tool


@tool()
def gsa_graj_bulk_excel_to_sqlite(
    excel_filename: str,
    table_name: str,
    db_filename: Optional[str] = "ucdata.db",
    sheet_name: Optional[str] = None,
    if_exists: Optional[str] = "append",
) -> str:
    """Bulk-load all rows from an Excel sheet into a SQLite table in the Downloads folder.

    Reads the specified sheet (or the active sheet if none is given) from an Excel
    file, treats the first row as column headers, and inserts all data rows into
    the target SQLite table. If the table does not exist it is created automatically
    with all columns typed as TEXT. Both files must reside in the user's Downloads
    folder.

    Args:
        excel_filename (str): Name of the Excel file in the Downloads folder,
            e.g. 'employees.xlsx'.
        table_name (str): Name of the SQLite table to load data into.
        db_filename (str, optional): Name of the SQLite database file in the
            Downloads folder. Defaults to 'ucdata.db'.
        sheet_name (str, optional): Name of the sheet to read. If omitted the
            active (first) sheet is used.
        if_exists (str, optional): What to do when the table already contains
            rows. 'append' adds the new rows (default); 'replace' deletes all
            existing rows before inserting.

    Returns:
        str: A summary message with the number of rows inserted and skipped.
    """
    if if_exists not in ("append", "replace"):
        raise ValueError(
            f"Invalid value for if_exists: '{if_exists}'. Use 'append' or 'replace'."
        )

    _DB_DIR = Path("/home/itzuser/Documents/wxo_db")
    _DB_DIR.mkdir(parents=True, exist_ok=True)

    excel_path = _DB_DIR / excel_filename
    if not excel_path.exists():
        raise FileNotFoundError(
            f"Excel file not found: {excel_path}. "
            "Make sure the file is in /home/itzuser/Documents/wxo_db/."
        )

    db_path = _DB_DIR / db_filename
    # SQLite creates the file automatically on connect — no pre-existence check needed

    # ── Read Excel ────────────────────────────────────────────────────────────
    import openpyxl  # lazy import — available at runtime via requirements.txt
    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)

    if sheet_name:
        if sheet_name not in wb.sheetnames:
            wb.close()
            raise ValueError(
                f"Sheet '{sheet_name}' not found in '{excel_filename}'. "
                f"Available sheets: {', '.join(wb.sheetnames)}"
            )
        ws = wb[sheet_name]
    else:
        ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        raise ValueError(f"The Excel file '{excel_filename}' is empty.")

    headers = [
        str(c).strip() if c is not None else f"col_{i}"
        for i, c in enumerate(rows[0])
    ]

    data_rows = [
        tuple(str(c) if c is not None else "" for c in row)
        for row in rows[1:]
        if any(c is not None for c in row)   # skip fully-blank rows
    ]

    if not data_rows:
        return f"No data rows found in '{excel_filename}'. Nothing was inserted."

    col_list = ", ".join(f'"{h}"' for h in headers)
    placeholders = ", ".join("?" for _ in headers)

    # ── Write to SQLite ───────────────────────────────────────────────────────
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()

        # Auto-create table if it does not exist (all columns TEXT)
        col_defs = ", ".join(f'"{h}" TEXT' for h in headers)
        cur.execute(
            f'CREATE TABLE IF NOT EXISTS "{table_name}" ({col_defs})'
        )

        if if_exists == "replace":
            cur.execute(f'DELETE FROM "{table_name}"')

        con.executemany(
            f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})',
            data_rows,
        )
        con.commit()
    finally:
        con.close()

    used_sheet = sheet_name or "active sheet"
    return (
        f"Successfully inserted {len(data_rows)} row(s) into table '{table_name}'.\n"
        f"  Excel source : {excel_path}  (sheet: {used_sheet})\n"
        f"  SQLite DB    : {db_path}\n"
        f"  Mode         : {if_exists}"
    )
