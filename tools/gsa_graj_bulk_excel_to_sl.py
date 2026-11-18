"""
gsa_graj_bulk_excel_to_sl.py — watsonx Orchestrate tool that bulk-loads an
uploaded Excel file into a PostgreSQL table.

The user attaches an .xlsx file directly in the wxO chat. The tool reads it
in-memory, creates the target table automatically (TEXT columns) if it does
not exist, and inserts all data rows.

Deployed as a standalone WXO Python tool (not part of the MCP server).
Credentials are read from environment variables via db_config.get_conn().

Dependencies: ibm-watsonx-orchestrate, openpyxl, pg8000 (see tools/requirements.txt)
"""

from io import BytesIO
from typing import Optional

from ibm_watsonx_orchestrate.agent_builder.tools import tool, WXOFile
from db_config import get_conn, PG_DB, PG_HOST


@tool()
def gsa_graj_bulk_excel_to_sl(
    excel_file: WXOFile,
    table_name: str,
    sheet_name: Optional[str] = None,
    if_exists: Optional[str] = "append",
) -> str:
    """Bulk-load all rows from an uploaded Excel file into a PostgreSQL table.

    The user attaches the Excel file directly in the chat. The tool reads it
    in-memory, creates the PostgreSQL table automatically from the column
    headers if it does not exist, and inserts all data rows. Data is stored
    permanently in the PostgreSQL database (wxodb).

    Args:
        excel_file (WXOFile): The Excel (.xlsx) file uploaded by the user in
            the chat.
        table_name (str): Name of the PostgreSQL table to load data into.
            Created automatically with TEXT columns if it does not exist.
        sheet_name (str, optional): Sheet name to read. Defaults to the active
            (first) sheet.
        if_exists (str, optional): 'append' adds rows (default); 'replace'
            clears the table first and reloads from scratch.

    Returns:
        str: A summary message with the number of rows inserted.
    """
    if if_exists not in ("append", "replace"):
        raise ValueError(
            f"Invalid if_exists value: '{if_exists}'. Use 'append' or 'replace'."
        )

    # ── Read uploaded file bytes ───────────────────────────────────────────────
    file_bytes = WXOFile.get_content(excel_file)
    file_name = WXOFile.get_file_name(excel_file) or "uploaded_file.xlsx"

    import openpyxl
    wb = openpyxl.load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)

    if sheet_name:
        if sheet_name not in wb.sheetnames:
            wb.close()
            raise ValueError(
                f"Sheet '{sheet_name}' not found. "
                f"Available sheets: {', '.join(wb.sheetnames)}"
            )
        ws = wb[sheet_name]
    else:
        ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        raise ValueError(f"The uploaded file '{file_name}' is empty.")

    headers = [
        str(c).strip() if c is not None else f"col_{i}"
        for i, c in enumerate(rows[0])
    ]
    pg_headers = [h.lower().replace(" ", "_").replace("-", "_") for h in headers]

    data_rows = [
        tuple(str(c) if c is not None else None for c in row)
        for row in rows[1:]
        if any(c is not None for c in row)
    ]

    if not data_rows:
        return f"No data rows found in '{file_name}'. Nothing inserted."

    col_list     = ", ".join(f'"{h}"' for h in pg_headers)
    placeholders = ", ".join(f"${i+1}" for i in range(len(pg_headers)))

    # ── Write to PostgreSQL ───────────────────────────────────────────────────
    con = get_conn()
    try:
        col_defs = ", ".join(f'"{h}" TEXT' for h in pg_headers)
        con.run(f'CREATE TABLE IF NOT EXISTS "{table_name}" ({col_defs})')
        if if_exists == "replace":
            con.run(f'DELETE FROM "{table_name}"')
        for row in data_rows:
            con.run(
                f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})',
                *row,
            )
    finally:
        con.close()

    used_sheet = sheet_name or "active sheet"
    return (
        f"Successfully inserted {len(data_rows)} row(s) into table '{table_name}'.\n"
        f"  Excel source  : {file_name}  (sheet: {used_sheet})\n"
        f"  PostgreSQL DB : {PG_DB} @ {PG_HOST}\n"
        f"  Mode          : {if_exists}"
    )
