"""Comprehensive test suite for event ingestion, append-only ledger, and orphan reconciliation."""
from __future__ import annotations

import json
import secrets
from pathlib import Path

import pytest

from solution.config import IST
from solution.crypto.pii import PIIEngine
from solution.db.connection import DatabaseManager
from solution.db.schema import init_db
from solution.ingestion.event_ingestor import EventIngestor, parse_event_timestamp
from solution.ingestion.lead_ingestor import LeadIngestor


@pytest.fixture
def secret_key() -> bytes:
    return secrets.token_bytes(32)


@pytest.fixture
def pii_engine(secret_key: bytes) -> PIIEngine:
    return PIIEngine(secret_key)


@pytest.fixture
def db_mgr(tmp_path: Path) -> DatabaseManager:
    db_file = tmp_path / "test_events.db"
    mgr = DatabaseManager(db_file)
    with mgr.connection() as conn:
        init_db(conn, schemas_dir=Path("assignment-a-data/schemas"))
    return mgr


@pytest.fixture
def event_ingestor(db_mgr: DatabaseManager, pii_engine: PIIEngine) -> EventIngestor:
    return EventIngestor(
        db_manager=db_mgr,
        pii_engine=pii_engine,
        schemas_dir=Path("assignment-a-data/schemas"),
    )


@pytest.fixture
def lead_ingestor(db_mgr: DatabaseManager, pii_engine: PIIEngine) -> LeadIngestor:
    return LeadIngestor(
        db_manager=db_mgr,
        pii_engine=pii_engine,
        schemas_dir=Path("assignment-a-data/schemas"),
    )


def write_test_jsonl(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ============================================================================
# 1. TIMESTAMP NORMALIZATION TESTS
# ============================================================================


def test_timestamp_parsing_all_three_formats() -> None:
    """Verify UTC ('Z'), offset ('+05:30'), and naive (interpreted as IST) timestamps."""
    # 1. UTC format
    utc_iso, ist_iso = parse_event_timestamp("2026-10-05T13:20:21Z")
    assert utc_iso == "2026-10-05T13:20:21Z"
    assert ist_iso == "2026-10-05T18:50:21+05:30"

    # 2. Offset format (+05:30)
    utc_iso2, ist_iso2 = parse_event_timestamp("2026-10-05T18:50:21+05:30")
    assert utc_iso2 == "2026-10-05T13:20:21Z"
    assert ist_iso2 == "2026-10-05T18:50:21+05:30"

    # 3. Naive format -> "Naive means IST" per specification
    utc_iso3, ist_iso3 = parse_event_timestamp("2026-10-03 10:01:00")
    assert ist_iso3 == "2026-10-03T10:01:00+05:30"
    assert utc_iso3 == "2026-10-03T04:31:00Z"


# ============================================================================
# 2. MALFORMED & DUPLICATE EVENT TESTS
# ============================================================================


def test_malformed_json_and_missing_event_id(
    event_ingestor: EventIngestor, db_mgr: DatabaseManager, tmp_path: Path
) -> None:
    """Verify malformed JSON or missing event_id lines are counted and skipped."""
    drop_dir = tmp_path / "drop_1"
    event_file = drop_dir / "events" / "events_0001.jsonl"

    lines = [
        "not a valid json {",
        '{"workflow_id": "motor_renewal", "call_id": "call_1"}',  # missing event_id
        '{"event_id": "   ", "event_type": "call.initiated"}',     # empty event_id
        "",                                                         # blank line (skipped and not counted)
        json.dumps({
            "event_id": "evt_valid_001",
            "event_type": "call.initiated",
            "workflow_id": "motor_renewal",
            "call_id": "call_0001",
            "occurred_at": "2026-10-01T10:00:00Z",
            "phone": "9876543210",
        }),
    ]
    write_test_jsonl(event_file, lines)

    summary = event_ingestor.ingest_drop(drop_dir)

    assert summary.events_total == 4, "Every non-empty line must be counted in events_total"
    assert summary.malformed_events == 3
    assert summary.duplicate_events_dropped == 0

    with db_mgr.connection() as conn:
        rows = conn.execute("SELECT event_id FROM interaction_ledger;").fetchall()
        assert len(rows) == 1
        assert rows[0]["event_id"] == "evt_valid_001"


def test_duplicate_events_across_drops(
    event_ingestor: EventIngestor, db_mgr: DatabaseManager, tmp_path: Path
) -> None:
    """Verify duplicate event IDs are dropped and counted across drops."""
    # Drop 1: evt_001 and evt_002
    drop1_dir = tmp_path / "drop_1"
    f1 = drop1_dir / "events" / "events_0001.jsonl"
    e1 = {
        "event_id": "evt_001",
        "event_type": "call.initiated",
        "workflow_id": "motor_renewal",
        "call_id": "call_01",
        "occurred_at": "2026-10-01T10:00:00Z",
        "phone": "9876543210",
    }
    e2 = {
        "event_id": "evt_002",
        "event_type": "call.connected",
        "workflow_id": "motor_renewal",
        "call_id": "call_01",
        "occurred_at": "2026-10-01T10:00:10Z",
        "phone": "9876543210",
    }
    write_test_jsonl(f1, [json.dumps(e1), json.dumps(e2)])

    s1 = event_ingestor.ingest_drop(drop1_dir)
    assert s1.events_total == 2
    assert s1.duplicate_events_dropped == 0

    # Drop 2: duplicate delivery of evt_002 and fresh evt_003
    drop2_dir = tmp_path / "drop_2"
    f2 = drop2_dir / "events" / "events_0002.jsonl"
    e3 = {
        "event_id": "evt_003",
        "event_type": "call.ended",
        "workflow_id": "motor_renewal",
        "call_id": "call_01",
        "occurred_at": "2026-10-01T10:01:00Z",
        "phone": "9876543210",
    }
    write_test_jsonl(f2, [json.dumps(e2), json.dumps(e3)])

    s2 = event_ingestor.ingest_drop(drop2_dir)
    assert s2.events_total == 2
    assert s2.duplicate_events_dropped == 1

    with db_mgr.connection() as conn:
        events = conn.execute("SELECT event_id FROM interaction_ledger ORDER BY event_id;").fetchall()
        event_ids = [e["event_id"] for e in events]
        assert event_ids == ["evt_001", "evt_002", "evt_003"]


def test_in_file_duplicate_events(
    event_ingestor: EventIngestor, db_mgr: DatabaseManager, tmp_path: Path
) -> None:
    """Verify duplicate event IDs appearing multiple times within the SAME file are caught."""
    drop_dir = tmp_path / "drop_in_file_dups"
    f = drop_dir / "events" / "events.jsonl"
    e1 = {
        "event_id": "evt_repeat",
        "event_type": "call.initiated",
        "workflow_id": "motor_renewal",
        "call_id": "call_rep_1",
        "occurred_at": "2026-10-01T10:00:00Z",
        "phone": "9876543210",
    }
    e2 = {
        "event_id": "evt_repeat",  # Exactly same event_id
        "event_type": "call.initiated",
        "workflow_id": "motor_renewal",
        "call_id": "call_rep_1",
        "occurred_at": "2026-10-01T10:00:00Z",
        "phone": "9876543210",
    }
    e3 = {
        "event_id": "evt_distinct",
        "event_type": "call.connected",
        "workflow_id": "motor_renewal",
        "call_id": "call_rep_1",
        "occurred_at": "2026-10-01T10:00:05Z",
        "phone": "9876543210",
    }
    write_test_jsonl(f, [json.dumps(e1), json.dumps(e2), json.dumps(e3)])

    summary = event_ingestor.ingest_drop(drop_dir)
    assert summary.events_total == 3
    assert summary.duplicate_events_dropped == 1

    with db_mgr.connection() as conn:
        stored = conn.execute("SELECT event_id FROM interaction_ledger WHERE event_id = 'evt_repeat';").fetchall()
        assert len(stored) == 1


# ============================================================================
# 3. ORPHAN HANDLING & LATE-ARRIVING LEADS RECONCILIATION
# ============================================================================


def test_orphan_event_and_late_lead_reconciliation(
    event_ingestor: EventIngestor, lead_ingestor: LeadIngestor, db_mgr: DatabaseManager, tmp_path: Path
) -> None:
    """
    Verify events arriving before their leads are flagged as orphans,
    and then automatically linked once the lead arrives in a later drop.
    """
    # Drop 1: Event arrives for a lead not yet uploaded
    drop1_dir = tmp_path / "drop_1"
    f1 = drop1_dir / "events" / "events_0001.jsonl"
    e1 = {
        "event_id": "evt_late_01",
        "event_type": "call.initiated",
        "workflow_id": "motor_renewal",
        "call_id": "call_late_01",
        "occurred_at": "2026-10-01T10:00:00Z",
        "phone": "+91 98765 43210",
    }
    write_test_jsonl(f1, [json.dumps(e1)])

    s1 = event_ingestor.ingest_drop(drop1_dir)
    assert s1.orphan_events == 1

    with db_mgr.connection() as conn:
        row = conn.execute("SELECT is_orphan, lead_id FROM interaction_ledger WHERE event_id = 'evt_late_01';").fetchone()
        assert row["is_orphan"] == 1
        assert row["lead_id"] is None

    # Drop 2: The lead is now uploaded!
    drop2_dir = tmp_path / "drop_2"
    csv2 = drop2_dir / "leads" / "motor_renewal" / "batch_001.csv"
    csv2.parent.mkdir(parents=True, exist_ok=True)
    with open(csv2, "w", newline="", encoding="utf-8") as f:
        f.write("customer_name,phone,policy_number\n")
        f.write("Aarav Sharma,9876543210,MOT/2026/001\n")

    lead_ingestor.ingest_drop(drop2_dir)

    # Verify that the previously orphaned event is now linked!
    with db_mgr.connection() as conn:
        lead = conn.execute("SELECT id FROM leads WHERE external_ref = 'MOT/2026/001';").fetchone()
        assert lead is not None
        lead_id = lead["id"]

        ev = conn.execute("SELECT is_orphan, lead_id FROM interaction_ledger WHERE event_id = 'evt_late_01';").fetchone()
        assert ev["is_orphan"] == 0, "Event must be resolved from orphan state"
        assert ev["lead_id"] == lead_id, "Event must link to the newly created lead"

        # Check quality_metrics orphan_events count
        qm = conn.execute("SELECT metric_value FROM quality_metrics WHERE metric_key = 'orphan_events';").fetchone()
        assert qm["metric_value"] == 0, "Final orphan count must be 0"


# ============================================================================
# 4. DISPOSITION OVERRIDE LINKING VIA CALL_ID
# ============================================================================


def test_disposition_override_linked_via_call_id(
    event_ingestor: EventIngestor, lead_ingestor: LeadIngestor, db_mgr: DatabaseManager, tmp_path: Path
) -> None:
    """Verify that disposition.override (which has no phone) links to the lead via call_id."""
    drop_dir = tmp_path / "drop_1"

    # 1. Lead CSV
    csv_file = drop_dir / "leads" / "motor_renewal" / "batch_001.csv"
    csv_file.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        f.write("customer_name,phone,policy_number\n")
        f.write("Sneha Pillai,91-82493-21495,MOT/2026/002\n")

    lead_ingestor.ingest_drop(drop_dir)

    # 2. Events: initiated (has phone) and override (NO phone)
    e_init = {
        "event_id": "evt_init_01",
        "event_type": "call.initiated",
        "workflow_id": "motor_renewal",
        "call_id": "call_override_01",
        "occurred_at": "2026-10-02T10:00:00Z",
        "phone": "8249321495",
    }
    e_override = {
        "event_id": "evt_ovr_01",
        "event_type": "disposition.override",
        "workflow_id": "motor_renewal",
        "call_id": "call_override_01",  # No 'phone' key!
        "occurred_at": "2026-10-02T12:00:00Z",
        "payload": {
            "disposition_code": "renewed",
            "overridden_by": "supervisor_1",
            "reason": "qa_review",
        },
    }
    event_file = drop_dir / "events" / "events_0001.jsonl"
    write_test_jsonl(event_file, [json.dumps(e_init), json.dumps(e_override)])

    event_ingestor.ingest_drop(drop_dir)

    with db_mgr.connection() as conn:
        lead = conn.execute("SELECT id FROM leads WHERE external_ref = 'MOT/2026/002';").fetchone()
        lead_id = lead["id"]

        ovr = conn.execute("SELECT is_orphan, lead_id FROM interaction_ledger WHERE event_id = 'evt_ovr_01';").fetchone()
        assert ovr["is_orphan"] == 0, "Override must not be an orphan"
        assert ovr["lead_id"] == lead_id, "Override must link to the lead through call_id"


def test_append_only_ledger_preserves_original_events(
    event_ingestor: EventIngestor, db_mgr: DatabaseManager, tmp_path: Path
) -> None:
    """Verify that overrides do not update or delete previous disposition events."""
    drop_dir = tmp_path / "drop_1"
    event_file = drop_dir / "events" / "events_0001.jsonl"

    e_set = {
        "event_id": "evt_set_01",
        "event_type": "disposition.set",
        "workflow_id": "motor_renewal",
        "call_id": "call_append_01",
        "occurred_at": "2026-10-02T10:30:00Z",
        "phone": "9876543210",
        "payload": {"disposition_code": "not_interested"},
    }
    e_ovr = {
        "event_id": "evt_ovr_02",
        "event_type": "disposition.override",
        "workflow_id": "motor_renewal",
        "call_id": "call_append_01",
        "occurred_at": "2026-10-02T11:00:00Z",
        "payload": {"disposition_code": "renewed", "overridden_by": "qa", "reason": "misclassified"},
    }
    write_test_jsonl(event_file, [json.dumps(e_set), json.dumps(e_ovr)])

    event_ingestor.ingest_drop(drop_dir)

    with db_mgr.connection() as conn:
        events = conn.execute(
            "SELECT event_id, event_type, disposition_code FROM interaction_ledger WHERE call_id = 'call_append_01' ORDER BY occurred_at_utc;"
        ).fetchall()
        assert len(events) == 2, "Append-only ledger must retain both original event and override"
        assert events[0]["event_id"] == "evt_set_01"
        assert events[0]["disposition_code"] == "not_interested"
        assert events[1]["event_id"] == "evt_ovr_02"
        assert events[1]["disposition_code"] == "renewed"


# ============================================================================
# 5. UNKNOWN DISPOSITION TESTS
# ============================================================================


def test_unknown_disposition_counted(
    event_ingestor: EventIngestor, db_mgr: DatabaseManager, tmp_path: Path
) -> None:
    """Verify that unknown disposition codes are counted and tracked."""
    drop_dir = tmp_path / "drop_1"
    event_file = drop_dir / "events" / "events_0001.jsonl"

    e_unknown = {
        "event_id": "evt_unk_01",
        "event_type": "disposition.set",
        "workflow_id": "motor_renewal",
        "call_id": "call_01",
        "occurred_at": "2026-10-02T10:30:00Z",
        "phone": "9876543210",
        "payload": {"disposition_code": "RENEWD"},  # Typo! Not in dispositions.csv
    }
    e_valid = {
        "event_id": "evt_val_01",
        "event_type": "disposition.set",
        "workflow_id": "motor_renewal",
        "call_id": "call_01",
        "occurred_at": "2026-10-02T10:35:00Z",
        "phone": "9876543210",
        "payload": {"disposition_code": "renewed"},  # Valid in catalogue
    }
    write_test_jsonl(event_file, [json.dumps(e_unknown), json.dumps(e_valid)])

    summary = event_ingestor.ingest_drop(drop_dir)
    assert summary.unknown_disposition_events == 1


# ============================================================================
# 6. IDEMPOTENT EVENT RE-INGESTION
# ============================================================================


def test_idempotent_event_reingestion(
    event_ingestor: EventIngestor, db_mgr: DatabaseManager, tmp_path: Path
) -> None:
    """Verify that re-ingesting event files is completely idempotent."""
    drop_dir = tmp_path / "drop_1"
    event_file = drop_dir / "events" / "events_0001.jsonl"
    e = {
        "event_id": "evt_001",
        "event_type": "call.initiated",
        "workflow_id": "motor_renewal",
        "call_id": "call_01",
        "occurred_at": "2026-10-01T10:00:00Z",
        "phone": "9876543210",
    }
    write_test_jsonl(event_file, [json.dumps(e)])

    s1 = event_ingestor.ingest_drop(drop_dir)
    assert s1.files_processed == 1
    assert s1.events_total == 1

    s2 = event_ingestor.ingest_drop(drop_dir)
    assert s2.files_skipped == 1
    assert s2.events_total == 0

    with db_mgr.connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM interaction_ledger;").fetchone()[0]
        assert count == 1

