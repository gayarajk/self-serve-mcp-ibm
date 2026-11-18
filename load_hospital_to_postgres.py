"""
load_hospital_to_postgres.py — one-shot loader for the generated hospital Excel file.

Reads kidsfields_hospital.xlsx (produced by generate_hospital_data.py) and
bulk-inserts all rows into the 'operational_tbl' table in a local PostgreSQL
database. Uses ON CONFLICT DO NOTHING on patient_id so it is safe to re-run.

Usage:
    python load_hospital_to_postgres.py

Prerequisites:
    - PostgreSQL running locally with the wxodb database and operational_tbl
      table already created (or rely on the INSERT to auto-fail on first run
      without the table — create it manually or via db_config helpers first).
    - psycopg2 installed:  pip install psycopg2-binary
    - openpyxl installed:  pip install openpyxl

WARNING: This script uses HARDCODED local dev credentials (wxouser/wxopass).
         It is a one-time local data-loading utility — NOT for production use.
         For production, use gsa_graj_bulk_excel_to_sl (tools/) which reads
         credentials from environment variables via db_config.get_conn().
"""

import openpyxl
import psycopg2
from pathlib import Path

conn = psycopg2.connect(
    host="localhost",
    port=5432,
    dbname="wxodb",
    user="wxouser",
    password="wxopass",
)
conn.autocommit = False
cur = conn.cursor()

wb = openpyxl.load_workbook("/home/itzuser/Documents/wxo_db/kidsfields_hospital.xlsx", read_only=True, data_only=True)
ws = wb.active
rows = list(ws.iter_rows(values_only=True))
wb.close()

headers = rows[0]
data = rows[1:]

insert_sql = """
INSERT INTO operational_tbl (
    patient_id, name, gender, dob, age_at_admission, city, blood_group,
    date_admitted, health_issue, ward, attending_doctor, discharge_date,
    length_of_stay_days, discharge_status, treatment_cost_usd
) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (patient_id) DO NOTHING;
"""

inserted = 0
for row in data:
    cur.execute(insert_sql, row)
    inserted += 1

conn.commit()
cur.close()
conn.close()

print(f"Inserted {inserted} rows into operational_tbl in wxodb (PostgreSQL)")
