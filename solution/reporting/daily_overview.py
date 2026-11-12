"""Generator for daily_overview.csv."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set

from solution.reporting.call_facts import CallFact


def generate_daily_overview_csv(
    all_calls: List[CallFact],
    out_dir: Path,
) -> Path:
    """
    Generate daily_overview.csv.
    
    Rules:
    - One row per workflow per IST date that has at least one call.
    - Sorted by workflow_id, date.
    - connectivity_rate = connected_calls / total_calls, formatted with exactly 4 decimals (e.g. 0.5625).
    - success_leads = distinct leads with at least one call on that date whose effective disposition has is_success=true.
    """
    out_file = out_dir / "daily_overview.csv"

    # Group calls by (workflow_id, ist_date)
    grouped_calls: Dict[tuple[str, str], List[CallFact]] = defaultdict(list)
    for c in all_calls:
        grouped_calls[(c.workflow_id, c.ist_date)].append(c)

    # Sort groups by workflow_id, date ascending
    sorted_keys = sorted(grouped_calls.keys())

    headers = [
        "workflow_id",
        "date",
        "total_calls",
        "connected_calls",
        "connectivity_rate",
        "success_leads",
    ]

    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for wf, date_str in sorted_keys:
            calls = grouped_calls[(wf, date_str)]
            total_calls = len(calls)
            if total_calls == 0:
                continue

            connected_calls = sum(1 for c in calls if c.is_connected)
            rate = connected_calls / total_calls
            rate_formatted = f"{rate:.4f}"

            # Distinct leads with at least one successful call on that date
            success_lead_ids: Set[int] = {c.lead_id for c in calls if c.is_success}
            success_leads_count = len(success_lead_ids)

            writer.writerow([
                wf,
                date_str,
                total_calls,
                connected_calls,
                rate_formatted,
                success_leads_count,
            ])

    return out_file

