"""Comprehensive test suite for the reporting engine, bucket logic, and report output contracts."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from solution.db.connection import DatabaseManager
from solution.db.schema import init_db
from solution.reporting.bucket_evaluator import compute_lead_stats, evaluate_lead_bucket
from solution.reporting.call_facts import CallFact, extract_call_facts
from solution.reporting.report_generator import ReportGenerator


# ============================================================================
# 1. BUCKET EVALUATION UNIT TESTS
# ============================================================================


def make_call(
    call_id: str,
    initiated_ist: str,
    is_connected: bool = True,
    has_telephony_failed: bool = False,
    effective_disp: str | None = None,
    is_terminal: bool = False,
    is_success: bool = False,
) -> CallFact:
    """Helper creating a test CallFact."""
    return CallFact(
        call_id=call_id,
        lead_id=1,
        workflow_id="motor_renewal",
        initiated_at_ist=initiated_ist,
        initiated_at_utc=initiated_ist.replace("+05:30", "Z"),
        ist_date=initiated_ist[:10],
        is_connected=is_connected,
        has_telephony_failed=has_telephony_failed,
        effective_disposition=effective_disp,
        is_terminal=is_terminal,
        is_success=is_success,
    )


def test_bucket_precedence_yet_to_reach_out() -> None:
    """Bucket 1: Zero calls -> yet_to_reach_out."""
    assert evaluate_lead_bucket([]) == "yet_to_reach_out"


def test_bucket_precedence_completed() -> None:
    """Bucket 2: Any call's effective disposition is terminal -> completed."""
    # Terminal renewed call + telephony failed call -> completed takes precedence over telephony failed!
    c1 = make_call("c1", "2026-10-01T10:00:00+05:30", effective_disp="renewed", is_terminal=True, is_success=True)
    c2 = make_call("c2", "2026-10-01T11:00:00+05:30", is_connected=False, has_telephony_failed=True)

    assert evaluate_lead_bucket([c1, c2]) == "completed"


def test_bucket_precedence_in_progress_telephony_failed() -> None:
    """Bucket 3: Every call has telephony_failed -> in_progress_telephony_failed."""
    c1 = make_call("c1", "2026-10-01T10:00:00+05:30", is_connected=False, has_telephony_failed=True)
    c2 = make_call("c2", "2026-10-02T10:00:00+05:30", is_connected=False, has_telephony_failed=True)

    assert evaluate_lead_bucket([c1, c2]) == "in_progress_telephony_failed"


def test_bucket_precedence_in_progress_dialed() -> None:
    """Bucket 4: Everything else -> in_progress_dialed."""
    # Case A: One telephony failed, one rang out (not every call telephony failed)
    c1 = make_call("c1", "2026-10-01T10:00:00+05:30", is_connected=False, has_telephony_failed=True)
    c2 = make_call("c2", "2026-10-02T10:00:00+05:30", is_connected=False, has_telephony_failed=False)
    assert evaluate_lead_bucket([c1, c2]) == "in_progress_dialed"

    # Case B: Call connected with non-terminal disposition (callback_requested)
    c3 = make_call("c3", "2026-10-03T10:00:00+05:30", is_connected=True, effective_disp="callback_requested", is_terminal=False)
    assert evaluate_lead_bucket([c3]) == "in_progress_dialed"


# ============================================================================
# 2. LEAD STATS UNIT TESTS
# ============================================================================


def test_lead_stats_current_disposition_from_most_recent_call_that_has_one() -> None:
    """Verify current_disposition comes from the most recent call (by initiated time) that has one."""
    # Call 1: 10:00 AM, effective disp = 'callback_requested'
    c1 = make_call("c1", "2026-10-01T10:00:00+05:30", effective_disp="callback_requested")
    # Call 2: 02:00 PM, telephony failed, no disposition set
    c2 = make_call("c2", "2026-10-01T14:00:00+05:30", is_connected=False, has_telephony_failed=True)

    stats = compute_lead_stats([c1, c2])

    assert stats.total_calls == 2
    assert stats.connected_calls == 1
    assert stats.last_call_at == "2026-10-01T14:00:00+05:30"
    # Even though c2 was later, c1 is the most recent call *that has an effective disposition*!
    assert stats.current_disposition == "callback_requested"
    assert stats.ever_success is False


def test_lead_stats_ever_success() -> None:
    """Verify ever_success is True if ANY call was successful."""
    c1 = make_call("c1", "2026-10-01T10:00:00+05:30", effective_disp="renewed", is_terminal=True, is_success=True)
    c2 = make_call("c2", "2026-10-02T10:00:00+05:30", effective_disp="payment_link_sent", is_terminal=False, is_success=False)

    stats = compute_lead_stats([c1, c2])
    assert stats.ever_success is True


# ============================================================================
# 3. REPORT OUTPUT CONTRACT INTEGRATION TESTS
# ============================================================================


@pytest.fixture
def populated_db(tmp_path: Path) -> DatabaseManager:
    """Create a test database populated with known leads, calls, rejections, and metrics."""
    db_file = tmp_path / "test_report_data.db"
    mgr = DatabaseManager(db_file)

    with mgr.transaction() as conn:
        init_db(conn, schemas_dir=Path("assignment-a-data/schemas"))

        # Ingestion run
        conn.execute("INSERT INTO ingestion_runs (drop_id, status) VALUES ('drop_1', 'COMPLETED');")

        # Insert 3 Leads across 2 batches
        conn.execute(
            """
            INSERT INTO leads (
                id, workflow_id, phone_blind_index, phone_masked, phone_encrypted,
                customer_name_encrypted, external_ref, batch_id, preferred_language, attributes_json
            ) VALUES 
            (1, 'motor_renewal', 'hash1', '+91******1111', 'enc1', 'name1', 'MOT/2026/001', 'batch_001', 'en', '{}'),
            (2, 'motor_renewal', 'hash2', '+91******2222', 'enc2', 'name2', 'MOT/2026/002', 'batch_001', 'hi', '{}'),
            (3, 'motor_renewal', 'hash3', '+91******3333', 'enc3', 'name3', 'MOT/2026/003', 'batch_002', 'ta', '{}');
            """
        )

        # Lead 1: 2 calls on 2026-10-01
        # Call 1: connected, disposition.set 'callback_requested', then supervisor OVERRIDE to 'renewed'
        conn.execute(
            """
            INSERT INTO interaction_ledger (
                event_id, event_type, workflow_id, call_id, occurred_at_utc, occurred_at_ist,
                disposition_code, payload_json, lead_id, is_orphan, drop_id
            ) VALUES 
            ('e1', 'call.initiated', 'motor_renewal', 'c1', '2026-10-01T04:30:00Z', '2026-10-01T10:00:00+05:30', NULL, '{}', 1, 0, 'drop_1'),
            ('e2', 'call.connected', 'motor_renewal', 'c1', '2026-10-01T04:30:05Z', '2026-10-01T10:00:05+05:30', NULL, '{}', 1, 0, 'drop_1'),
            ('e3', 'disposition.set', 'motor_renewal', 'c1', '2026-10-01T04:31:00Z', '2026-10-01T10:01:00+05:30', 'callback_requested', '{"disposition_code": "callback_requested"}', 1, 0, 'drop_1'),
            ('e4', 'disposition.override', 'motor_renewal', 'c1', '2026-10-01T05:00:00Z', '2026-10-01T10:30:00+05:30', 'renewed', '{"disposition_code": "renewed"}', 1, 0, 'drop_1');
            """
        )

        # Lead 2: 1 call on 2026-10-01: telephony failed
        conn.execute(
            """
            INSERT INTO interaction_ledger (
                event_id, event_type, workflow_id, call_id, occurred_at_utc, occurred_at_ist,
                disposition_code, payload_json, lead_id, is_orphan, drop_id
            ) VALUES 
            ('e5', 'call.initiated', 'motor_renewal', 'c2', '2026-10-01T06:00:00Z', '2026-10-01T11:30:00+05:30', NULL, '{}', 2, 0, 'drop_1'),
            ('e6', 'call.telephony_failed', 'motor_renewal', 'c2', '2026-10-01T06:00:05Z', '2026-10-01T11:30:05+05:30', NULL, '{"reason": "carrier_rejected"}', 2, 0, 'drop_1');
            """
        )

        # Lead 3: 0 calls (yet_to_reach_out)

        # 1 Rejection
        conn.execute(
            """
            INSERT INTO lead_rejections (workflow_id, batch_id, row_number, reason, drop_id)
            VALUES ('motor_renewal', 'batch_001', 5, 'invalid_phone', 'drop_1');
            """
        )

        # 1 Orphan event
        conn.execute(
            """
            INSERT INTO interaction_ledger (
                event_id, event_type, workflow_id, call_id, occurred_at_utc, occurred_at_ist,
                disposition_code, payload_json, lead_id, is_orphan, drop_id
            ) VALUES 
            ('e_orphan', 'call.initiated', 'motor_renewal', 'c_orphan', '2026-10-01T07:00:00Z', '2026-10-01T12:30:00+05:30', NULL, '{}', NULL, 1, 'drop_1');
            """
        )

        # Quality metrics
        metrics = [
            ("lead_rows_total", 4),
            ("lead_rows_rejected", 1),
            ("duplicate_lead_rows_merged", 0),
            ("field_warnings", 1),
            ("events_total", 7),
            ("malformed_events", 0),
            ("duplicate_events_dropped", 0),
            ("unknown_disposition_events", 0),
        ]
        conn.executemany(
            "INSERT INTO quality_metrics (scope, metric_key, metric_value) VALUES ('global', ?, ?);",
            metrics,
        )

    return mgr


def test_all_five_reports_generation(populated_db: DatabaseManager, tmp_path: Path) -> None:
    """Verify that all 5 report files are created matching the exact contracts and calculations."""
    reports_dir = tmp_path / "reports"
    generator = ReportGenerator(populated_db)
    generated = generator.generate_reports(reports_dir)

    assert len(generated) == 5

    # 1. Verify batch_summary.csv
    batch_csv = reports_dir / "batch_summary.csv"
    assert batch_csv.exists()
    with open(batch_csv, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    assert lines[0] == "workflow_id,batch_id,total_leads,yet_to_reach_out,in_progress_telephony_failed,in_progress_dialed,completed"
    # batch_001 has 2 leads: Lead 1 (completed because renewed is terminal), Lead 2 (in_progress_telephony_failed)
    assert lines[1] == "motor_renewal,batch_001,2,0,1,0,1"
    # batch_002 has 1 lead: Lead 3 (yet_to_reach_out)
    assert lines[2] == "motor_renewal,batch_002,1,1,0,0,0"

    # 2. Verify daily_overview.csv
    daily_csv = reports_dir / "daily_overview.csv"
    assert daily_csv.exists()
    with open(daily_csv, "r", encoding="utf-8") as f:
        dlines = [line.strip() for line in f if line.strip()]

    assert dlines[0] == "workflow_id,date,total_calls,connected_calls,connectivity_rate,success_leads"
    # On 2026-10-01: 2 counted calls (c1 and c2). 1 connected (c1). Rate = 1/2 = 0.5000.
    # Success leads: 1 (Lead 1 had c1 which had override to renewed, which is_success=True)
    assert dlines[1] == "motor_renewal,2026-10-01,2,1,0.5000,1"

    # 3. Verify lead_report.csv
    lead_csv = reports_dir / "lead_report.csv"
    assert lead_csv.exists()
    with open(lead_csv, "r", encoding="utf-8") as f:
        llines = [line.strip() for line in f if line.strip()]

    assert llines[0] == "workflow_id,external_ref,batch_id,phone_masked,bucket,total_calls,connected_calls,last_call_at,current_disposition,ever_success"
    # Lead 1: MOT/2026/001, batch_001, +91******1111, completed, 1 call, 1 connected, last_call_at 2026-10-01T10:00:00+05:30, current_disposition renewed, ever_success true
    assert llines[1] == "motor_renewal,MOT/2026/001,batch_001,+91******1111,completed,1,1,2026-10-01T10:00:00+05:30,renewed,true"
    # Lead 2: MOT/2026/002, in_progress_telephony_failed, 1 call, 0 connected, last_call_at 2026-10-01T11:30:00+05:30, current_disposition '', ever_success false
    assert llines[2] == "motor_renewal,MOT/2026/002,batch_001,+91******2222,in_progress_telephony_failed,1,0,2026-10-01T11:30:00+05:30,,false"
    # Lead 3: MOT/2026/003, yet_to_reach_out, 0 calls, 0 connected, last_call_at '', current_disposition '', ever_success false
    assert llines[3] == "motor_renewal,MOT/2026/003,batch_002,+91******3333,yet_to_reach_out,0,0,,,false"

    # 4. Verify rejections.csv (Zero PII)
    rej_csv = reports_dir / "rejections.csv"
    assert rej_csv.exists()
    with open(rej_csv, "r", encoding="utf-8") as f:
        rlines = [line.strip() for line in f if line.strip()]

    assert rlines[0] == "workflow_id,batch_id,row_number,reason"
    assert rlines[1] == "motor_renewal,batch_001,5,invalid_phone"

    # 5. Verify data_quality.json
    dq_json = reports_dir / "data_quality.json"
    assert dq_json.exists()
    with open(dq_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["lead_rows_total"] == 4
    assert data["lead_rows_rejected"] == 1
    assert data["rejections_by_reason"] == {"invalid_phone": 1}
    assert data["duplicate_lead_rows_merged"] == 0
    assert data["field_warnings"] == 1
    assert data["events_total"] == 7
    assert data["malformed_events"] == 0
    assert data["duplicate_events_dropped"] == 0
    assert data["orphan_events"] == 1  # 1 orphan event
    assert data["unknown_disposition_events"] == 0
