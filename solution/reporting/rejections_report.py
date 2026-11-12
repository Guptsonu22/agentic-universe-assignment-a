"""Generator for rejections.csv."""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


def generate_rejections_csv(conn: sqlite3.Connection, out_dir: Path) -> Path:
    """
    Generate rejections.csv sorted by workflow_id, batch_id, row_number.
    
    Format:
    workflow_id,batch_id,row_number,reason
    
    Constraint: Strictly zero PII.
    """
    out_file = out_dir / "rejections.csv"

    query = """
    SELECT workflow_id, batch_id, row_number, reason 
    FROM lead_rejections 
    ORDER BY workflow_id ASC, batch_id ASC, row_number ASC;
    """
    rows = conn.execute(query).fetchall()

    headers = ["workflow_id", "batch_id", "row_number", "reason"]

    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for r in rows:
            writer.writerow([
                r["workflow_id"],
                r["batch_id"],
                r["row_number"],
                r["reason"],
            ])

    return out_file

