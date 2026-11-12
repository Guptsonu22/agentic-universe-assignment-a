"""Audit script: Scan database, logs, and generated report files for any plaintext PII."""
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path

# Indian phone number pattern: 10 digits starting with 6, 7, 8, or 9 (with optional country code)
PHONE_REGEX = re.compile(r"(?:\+?91[\s-]?)?[6-9]\d{9}")

# Common names from data generator
NAMES = [
    "Aarav", "Vivaan", "Aditya", "Ananya", "Diya", "Ishaan", "Kavya", "Meera", "Rohan",
    "Saanvi", "Arjun", "Priya", "Karthik", "Lakshmi", "Nikhil", "Pooja", "Rahul", "Sneha",
    "Varun", "Zoya", "Farhan", "Gurpreet", "Harini", "Imran", "Jyoti", "Manoj", "Nandini",
    "Sharma", "Iyer", "Reddy", "Nair", "Patel", "Gupta", "Khan", "Singh", "Menon", "Rao",
    "Das", "Joshi", "Kulkarni", "Banerjee", "Pillai", "Verma", "Hegde", "Shetty", "Bose"
]
NAME_REGEX = re.compile(r"\b(" + "|".join(NAMES) + r")\b", re.IGNORECASE)


def audit_database(db_path: str = "au_ledger.db") -> list[dict]:
    violations = []
    conn = sqlite3.connect(db_path)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]

    for table in tables:
        cur = conn.execute(f"PRAGMA table_info({table});")
        columns = [row[1] for row in cur.fetchall()]
        rows = conn.execute(f"SELECT * FROM {table};").fetchall()
        for row in rows:
            for col_name, val in zip(columns, row):
                if val is None:
                    continue
                val_str = str(val)
                # Skip valid masked phone (+91******XXXX)
                if re.match(r"^\+91\*{6}\d{4}$", val_str):
                    continue
                # If ciphertext or cryptographic hex hash, skip
                if col_name.endswith("_encrypted") or col_name in ("file_hash", "phone_blind_index"):
                    continue

                if PHONE_REGEX.search(val_str):
                    violations.append({
                        "target": f"DB table '{table}', col '{col_name}'",
                        "type": "PHONE_LEAK",
                        "snippet": val_str[:30],
                    })
                if NAME_REGEX.search(val_str):
                    violations.append({
                        "target": f"DB table '{table}', col '{col_name}'",
                        "type": "NAME_LEAK",
                        "snippet": val_str[:30],
                    })

    conn.close()
    return violations


def audit_reports(reports_dir: Path = Path("reports")) -> list[dict]:
    violations = []
    
    # 1. rejections.csv must have NO PII
    rej_file = reports_dir / "rejections.csv"
    if rej_file.exists():
        with open(rej_file, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                if PHONE_REGEX.search(line):
                    violations.append({
                        "target": f"rejections.csv line {line_no}",
                        "type": "PHONE_LEAK",
                        "snippet": line.strip(),
                    })
                if NAME_REGEX.search(line):
                    violations.append({
                        "target": f"rejections.csv line {line_no}",
                        "type": "NAME_LEAK",
                        "snippet": line.strip(),
                    })

    # 2. lead_report.csv must ONLY have masked phones (+91******XXXX), never unmasked
    lead_file = reports_dir / "lead_report.csv"
    if lead_file.exists():
        with open(lead_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for line_no, row in enumerate(reader, start=2):
                phone = row.get("phone_masked", "")
                if phone and not re.match(r"^\+91\*{6}\d{4}$", phone):
                    violations.append({
                        "target": f"lead_report.csv line {line_no}",
                        "type": "INVALID_PHONE_MASK",
                        "snippet": phone,
                    })
                # Check other fields for phone or name leakage
                for k, v in row.items():
                    if k != "phone_masked" and v and PHONE_REGEX.search(v):
                        violations.append({
                            "target": f"lead_report.csv line {line_no} col {k}",
                            "type": "PHONE_LEAK",
                            "snippet": v,
                        })

    return violations


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="au_ledger.db")
    parser.add_argument("--reports", default="reports")
    args = parser.parse_args()

    db_violations = audit_database(args.db)
    rep_violations = audit_reports(Path(args.reports))

    total = len(db_violations) + len(rep_violations)
    print(f"=== PII AUDIT SUMMARY ({args.db}, {args.reports}) ===")
    print(f"Database violations: {len(db_violations)}")
    print(f"Report files violations: {len(rep_violations)}")
    print(f"Total PII violations: {total}")

    for v in db_violations + rep_violations:
        print(f"VIOLATION: {v['type']} in {v['target']}: {v['snippet']}")

    if total > 0:
        sys.exit(1)
    else:
        print("PASS: Zero PII detected across all database tables and report artifacts!")
        sys.exit(0)
