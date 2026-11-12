"""Generator for lead_report.csv."""
from __future__ import annotations

import csv
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from solution.reporting.bucket_evaluator import compute_lead_stats
from solution.reporting.call_facts import CallFact


def generate_lead_report_csv(
    conn: sqlite3.Connection,
    all_calls: List[CallFact],
    out_dir: Path,
) -> Path:
    """
    Generate lead_report.csv sorted by workflow_id, external_ref.
    
    Format:
    workflow_id,external_ref,batch_id,phone_masked,bucket,total_calls,connected_calls,last_call_at,current_disposition,ever_success
    """
    out_file = out_dir / "lead_report.csv"

    # Map calls by lead_id
    calls_by_lead: Dict[int, List[CallFact]] = defaultdict(list)
    for c in all_calls:
        calls_by_lead[c.lead_id].append(c)

    # Fetch all leads sorted by workflow_id, external_ref ascending
    query = """
    SELECT id, workflow_id, external_ref, batch_id, phone_masked 
    FROM leads 
    ORDER BY workflow_id ASC, external_ref ASC;
    """
    leads = conn.execute(query).fetchall()

    headers = [
        "workflow_id",
        "external_ref",
        "batch_id",
        "phone_masked",
        "bucket",
        "total_calls",
        "connected_calls",
        "last_call_at",
        "current_disposition",
        "ever_success",
    ]

    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for lead in leads:
            lead_id = lead["id"]
            lead_calls = calls_by_lead.get(lead_id, [])
            stats = compute_lead_stats(lead_calls)

            writer.writerow([
                lead["workflow_id"],
                lead["external_ref"],
                lead["batch_id"],
                lead["phone_masked"],
                stats.bucket,
                stats.total_calls,
                stats.connected_calls,
                stats.last_call_at,
                stats.current_disposition,
                "true" if stats.ever_success else "false",
            ])

    return out_file

