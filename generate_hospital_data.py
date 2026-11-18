"""
generate_hospital_data.py — synthetic paediatric hospital data generator.

Generates randomised admission records for 'kidsfields_hospital' spanning
January 2022 through April 2026 (~8–14 records per month) and writes them
to an Excel file at:
    /home/itzuser/Documents/wxo_db/kidsfields_hospital.xlsx

The Excel sheet (tab: 'operational_tbl') has 15 columns:
    patient_id, name, gender, dob, age_at_admission, city, blood_group,
    date_admitted, health_issue, ward, attending_doctor, discharge_date,
    length_of_stay_days, discharge_status, treatment_cost_usd

Usage:
    python generate_hospital_data.py

Output file is git-ignored (lives outside the repo). The same seed (42) is
used every run so output is deterministic. Run load_hospital_to_postgres.py
afterwards to load the generated file into PostgreSQL.

Dependencies: openpyxl (see tools/requirements.txt)
"""

import random
from datetime import date, timedelta
import openpyxl
from pathlib import Path

random.seed(42)

# ── Sample data pools ─────────────────────────────────────────────────────────
first_names = [
    "Liam", "Emma", "Noah", "Olivia", "Aiden", "Sophia", "Lucas", "Isabella",
    "Mason", "Mia", "Ethan", "Charlotte", "Logan", "Amelia", "Jackson", "Harper",
    "Sebastian", "Evelyn", "James", "Abigail", "Benjamin", "Emily", "Elijah",
    "Elizabeth", "Oliver", "Sofia", "William", "Avery", "Henry", "Ella",
    "Alexander", "Scarlett", "Michael", "Grace", "Daniel", "Chloe", "Matthew",
    "Victoria", "Joseph", "Riley", "David", "Aria", "Carter", "Lily", "Owen",
    "Zoey", "Wyatt", "Penelope", "John", "Layla", "Jack", "Nora", "Luke",
    "Luna", "Jayden", "Hannah", "Dylan", "Ellie", "Grayson", "Aurora",
]

last_names = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Wilson", "Taylor", "Anderson", "Thomas", "Jackson", "White",
    "Harris", "Martin", "Thompson", "Martinez", "Robinson", "Clark", "Lewis",
    "Lee", "Walker", "Hall", "Allen", "Young", "Hernandez", "King", "Wright",
    "Lopez", "Hill", "Scott", "Green", "Adams", "Baker", "Nelson", "Carter",
    "Mitchell", "Perez", "Roberts", "Turner", "Phillips", "Campbell", "Parker",
]

cities = [
    "Toronto", "Vancouver", "Montreal", "Calgary", "Ottawa", "Edmonton",
    "Winnipeg", "Hamilton", "Quebec City", "Halifax", "Victoria", "Saskatoon",
    "Regina", "Kelowna", "London", "Windsor", "Barrie", "Kingston", "Guelph",
]

health_issues = [
    "Heart Problem", "Cancer", "Asthma", "Pneumonia", "Diabetes",
    "Appendicitis", "Fracture", "Ear Infection", "Tonsillitis", "Anemia",
    "Leukemia", "Bronchitis", "Epilepsy", "Kidney Infection", "Migraine",
    "Meningitis", "Chickenpox", "Measles", "RSV", "Gastroenteritis",
]

# Weighted so common conditions appear more often
weights = [
    8, 5, 12, 10, 6,
    9, 11, 14, 10, 7,
    4, 9, 5, 6, 8,
    4, 7, 5, 10, 11,
]

genders = ["Male", "Female"]

blood_groups = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]

doctors = [
    "Dr. Sarah Mitchell", "Dr. James Patel", "Dr. Emily Chen",
    "Dr. Robert Kim", "Dr. Laura Stevens", "Dr. Ahmed Hassan",
    "Dr. Maria Garcia", "Dr. David Okonkwo", "Dr. Rachel Wong",
    "Dr. Michael Torres",
]

wards = ["Pediatric ICU", "General Pediatrics", "Cardiology", "Oncology",
         "Emergency", "Neurology", "Orthopedics", "Respiratory"]

statuses = ["Discharged", "Discharged", "Discharged", "Discharged",
            "Discharged", "Transferred", "Deceased"]   # mostly discharged


def rand_date(start: date, end: date) -> date:
    return start + timedelta(days=random.randint(0, (end - start).days))


def rand_dob(admitted: date) -> date:
    """Children aged 0–17 at admission."""
    age_days = random.randint(0, 17 * 365)
    return admitted - timedelta(days=age_days)


# ── Generate records: ~8–12 per month, Jan 2022 – Dec 2026 ────────────────────
records = []
for year in range(2022, 2027):
    for month in range(1, 13):
        # Skip future months beyond Apr 2026 realistically
        if year == 2026 and month > 4:
            n_records = random.randint(3, 6)
        else:
            n_records = random.randint(8, 14)

        month_start = date(year, month, 1)
        if month == 12:
            month_end = date(year, 12, 31)
        else:
            month_end = date(year, month + 1, 1) - timedelta(days=1)

        for _ in range(n_records):
            fname = random.choice(first_names)
            lname = random.choice(last_names)
            name = f"{fname} {lname}"

            admitted = rand_date(month_start, month_end)
            dob = rand_dob(admitted)
            age_years = (admitted - dob).days // 365

            stay_days = random.randint(1, 21)
            discharged = admitted + timedelta(days=stay_days)

            issue = random.choices(health_issues, weights=weights, k=1)[0]
            city = random.choice(cities)
            gender = random.choice(genders)
            blood = random.choice(blood_groups)
            doctor = random.choice(doctors)
            ward = random.choice(wards)
            status = random.choice(statuses)
            cost = round(random.uniform(800, 45000), 2)

            records.append({
                "patient_id": f"PED-{year}-{len(records)+1:05d}",
                "name": name,
                "gender": gender,
                "dob": dob.strftime("%Y-%m-%d"),
                "age_at_admission": age_years,
                "city": city,
                "blood_group": blood,
                "date_admitted": admitted.strftime("%Y-%m-%d"),
                "health_issue": issue,
                "ward": ward,
                "attending_doctor": doctor,
                "discharge_date": discharged.strftime("%Y-%m-%d"),
                "length_of_stay_days": stay_days,
                "discharge_status": status,
                "treatment_cost_usd": cost,
            })

# ── Write to Excel ─────────────────────────────────────────────────────────────
output_path = Path("/home/itzuser/Documents/wxo_db/kidsfields_hospital.xlsx")
output_path.parent.mkdir(parents=True, exist_ok=True)

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "operational_tbl"

headers = list(records[0].keys())
ws.append(headers)

# Header styling
from openpyxl.styles import Font, PatternFill, Alignment
header_font = Font(bold=True, color="FFFFFF")
header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
for cell in ws[1]:
    cell.font = header_font
    cell.fill = header_fill
    cell.alignment = Alignment(horizontal="center")

for rec in records:
    ws.append(list(rec.values()))

# Auto-width columns
for col in ws.columns:
    max_len = max(len(str(cell.value or "")) for cell in col)
    ws.column_dimensions[col[0].column_letter].width = min(max_len + 3, 30)

wb.save(output_path)
print(f"Generated {len(records)} records")
print(f"Saved to: {output_path}")
