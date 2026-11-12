"""Generator for data_quality.json."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict


def generate_data_quality_json(conn: sqlite3.Connection, out_dir: Path) -> Path:
    """
    Generate data_quality.json matching the exact assignment specification.
    
    Reflects the final state across all ingested drops.
    """
    out_file = out_dir / "data_quality.json"

    # 1. Fetch cumulative quality metrics
    metrics_rows = conn.execute(
        "SELECT metric_key, metric_value FROM quality_metrics WHERE scope = 'global';"
    ).fetchall()
    metrics: Dict[str, int] = {r["metric_key"]: r["metric_value"] for r in metrics_rows}

    # 2. Count actual rejections and breakdown by reason
    rejection_rows = conn.execute(
        "SELECT reason, COUNT(*) as cnt FROM lead_rejections GROUP BY reason ORDER BY reason ASC;"
    ).fetchall()
    rejections_by_reason: Dict[str, int] = {r["reason"]: r["cnt"] for r in rejection_rows}
    lead_rows_rejected = sum(rejections_by_reason.values())

    # 3. Final orphan events count directly from interaction ledger
    cur = conn.execute("SELECT COUNT(*) FROM interaction_ledger WHERE is_orphan = 1;")
    orphan_events = cur.fetchone()[0]

    report_data: Dict[str, Any] = {
        "lead_rows_total": metrics.get("lead_rows_total", 0),
        "lead_rows_rejected": lead_rows_rejected,
        "rejections_by_reason": rejections_by_reason,
        "duplicate_lead_rows_merged": metrics.get("duplicate_lead_rows_merged", 0),
        "field_warnings": metrics.get("field_warnings", 0),
        "events_total": metrics.get("events_total", 0),
        "malformed_events": metrics.get("malformed_events", 0),
        "duplicate_events_dropped": metrics.get("duplicate_events_dropped", 0),
        "orphan_events": orphan_events,
        "unknown_disposition_events": metrics.get("unknown_disposition_events", 0),
    }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    return out_file

