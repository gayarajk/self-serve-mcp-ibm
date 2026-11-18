import json

from ibm_watsonx_orchestrate.agent_builder.tools import tool
from db_config import get_conn, PG_DB


@tool()
def gsa_graj_write_to_sqlite(
    table_name: str,
    row_data: str,
) -> str:
    """Insert a single row into a table in the PostgreSQL database.

    Opens a connection to the wxodb PostgreSQL database and inserts one row
    into the given table. The row data must be supplied as a JSON object whose
    keys match the column names of the target table.

    Args:
        table_name (str): Name of the table to insert the row into.
        row_data (str): A JSON object string mapping column names to values,
            e.g. '{"name": "Alice", "age": 30, "city": "Toronto"}'.

    Returns:
        str: A confirmation message including the inserted row data.
    """
    try:
        record = json.loads(row_data)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"row_data is not valid JSON: {exc}. "
            'Example: \'{"name": "Alice", "age": 30}\''
        ) from exc

    if not isinstance(record, dict) or not record:
        raise ValueError(
            "row_data must be a non-empty JSON object, e.g. "
            '\'{"column1": "value1", "column2": "value2"}\''
        )

    columns = list(record.keys())
    values  = list(record.values())

    col_list     = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join(f"${i+1}" for i in range(len(columns)))

    con = get_conn()
    try:
        con.run(
            f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})',
            *values,
        )
    finally:
        con.close()

    return (
        f"Successfully inserted 1 row into table '{table_name}' "
        f"in PostgreSQL '{PG_DB}'.\n"
        f"  Data: {json.dumps(record, default=str)}"
    )
