"""Generator for batch_summary.csv."""
from __future__ import annotations

import csv
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from solution.reporting.bucket_evaluator import evaluate_lead_bucket
from solution.reporting.call_facts import CallFact


def generate_batch_summary_csv(
    conn: sqlite3.Connection,
    all_calls: List[CallFact],
    out_dir: Path,
) -> Path:
    """
    Generate batch_summary.csv sorted by workflow_id, batch_id.
    
    Format:
    workflow_id,batch_id,total_leads,yet_to_reach_out,in_progress_telephony_failed,in_progress_dialed,completed
    """
    out_file = out_dir / "batch_summary.csv"

    # Map calls by lead_id
    calls_by_lead: Dict[int, List[CallFact]] = defaultdict(list)
    for c in all_calls:
        calls_by_lead[c.lead_id].append(c)

    # Fetch all leads
    query = """
    SELECT id, workflow_id, batch_id 
    FROM leads 
    ORDER BY workflow_id ASC, batch_id ASC;
    """
    leads = conn.execute(query).fetchall()

    # Aggregate buckets per (workflow_id, batch_id)
    # Counts: { (workflow_id, batch_id): {bucket: count} }
    counts: Dict[tuple[str, str], Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    totals: Dict[tuple[str, str], int] = defaultdict(int)

    for lead in leads:
        lead_id = lead["id"]
        wf = lead["workflow_id"]
        batch = lead["batch_id"]
        key = (wf, batch)

        lead_calls = calls_by_lead.get(lead_id, [])
        bucket = evaluate_lead_bucket(lead_calls)

        counts[key][bucket] += 1
        totals[key] += 1

    # Sort keys by workflow_id, batch_id ascending
    sorted_keys = sorted(counts.keys())

    headers = [
        "workflow_id",
        "batch_id",
        "total_leads",
        "yet_to_reach_out",
        "in_progress_telephony_failed",
        "in_progress_dialed",
        "completed",
    ]

    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for wf, batch in sorted_keys:
            key = (wf, batch)
            bucket_counts = counts[key]
            total = totals[key]
            writer.writerow([
                wf,
                batch,
                total,
                bucket_counts["yet_to_reach_out"],
                bucket_counts["in_progress_telephony_failed"],
                bucket_counts["in_progress_dialed"],
                bucket_counts["completed"],
            ])

    return out_file

