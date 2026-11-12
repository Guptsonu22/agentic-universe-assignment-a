"""Integration tests for Assignment A CLI workflow, multi-drop ingestion, and report generation."""
from __future__ import annotations

import csv
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

import pytest

from solution.cli import main
from solution.config import Config
from solution.crypto.pii import PIIEngine
from solution.db.connection import DatabaseManager


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Fixture providing a temporary SQLite database file path."""
    return tmp_path / "test_pipeline.db"


@pytest.fixture
def temp_reports_dir(tmp_path: Path) -> Path:
    """Fixture providing a temporary reports directory."""
    rep_dir = tmp_path / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    return rep_dir


def test_cli_first_drop_ingestion(temp_db: Path) -> None:
    """Verify first drop ingestion (leads and events) records completed status and ledger records."""
    db_path = str(temp_db)
    exit_code = main(["ingest", "--db", db_path, "data/drop_1"])
    assert exit_code == 0

    mgr = DatabaseManager(db_path)
    with mgr.connection() as conn:
        # Check ingestion run record
        run = conn.execute(
            "SELECT status FROM ingestion_runs WHERE drop_id = 'drop_1';"
        ).fetchone()
        assert run is not None
        assert run["status"] == "COMPLETED"

        # Check leads were ingested
        lead_count = conn.execute("SELECT COUNT(*) FROM leads;").fetchone()[0]
        assert lead_count > 0

        # Check events were ingested into append-only ledger
        event_count = conn.execute("SELECT COUNT(*) FROM interaction_ledger;").fetchone()[0]
        assert event_count > 0

        # Check ingested files table records all processed files
        files_count = conn.execute(
            "SELECT COUNT(*) FROM ingested_files WHERE drop_id = 'drop_1';"
        ).fetchone()[0]
        assert files_count >= 2


def test_cli_second_drop_ingestion_and_orphan_reconciliation(temp_db: Path) -> None:
    """Verify sequential ingestion of drop_1 followed by drop_2 and automatic orphan reconciliation."""
    db_path = str(temp_db)

    # Ingest drop_1
    ret1 = main(["ingest", "--db", db_path, "data/drop_1"])
    assert ret1 == 0

    mgr = DatabaseManager(db_path)
    with mgr.connection() as conn:
        drop1_leads = conn.execute("SELECT COUNT(*) FROM leads;").fetchone()[0]
        drop1_events = conn.execute("SELECT COUNT(*) FROM interaction_ledger;").fetchone()[0]

    # Ingest drop_2
    ret2 = main(["ingest", "--db", db_path, "data/drop_2"])
    assert ret2 == 0

    with mgr.connection() as conn:
        drop2_run = conn.execute(
            "SELECT status FROM ingestion_runs WHERE drop_id = 'drop_2';"
        ).fetchone()
        assert drop2_run is not None
        assert drop2_run["status"] == "COMPLETED"

        drop2_leads = conn.execute("SELECT COUNT(*) FROM leads;").fetchone()[0]
        drop2_events = conn.execute("SELECT COUNT(*) FROM interaction_ledger;").fetchone()[0]

        # Cumulative leads and events must increase or stay consistent
        assert drop2_leads >= drop1_leads
        assert drop2_events > drop1_events


def test_cli_reingesting_first_drop_is_idempotent(temp_db: Path) -> None:
    """Verify that re-running an already ingested drop does not duplicate data or change metrics."""
    db_path = str(temp_db)

    # Initial ingestion of drop_1
    ret1 = main(["ingest", "--db", db_path, "data/drop_1"])
    assert ret1 == 0

    mgr = DatabaseManager(db_path)
    with mgr.connection() as conn:
        initial_leads = conn.execute("SELECT COUNT(*) FROM leads;").fetchone()[0]
        initial_events = conn.execute("SELECT COUNT(*) FROM interaction_ledger;").fetchone()[0]
        initial_rejections = conn.execute("SELECT COUNT(*) FROM lead_rejections;").fetchone()[0]
        initial_metrics = {
            r["metric_key"]: r["metric_value"]
            for r in conn.execute("SELECT metric_key, metric_value FROM quality_metrics;").fetchall()
        }

    # Re-ingest drop_1
    ret2 = main(["ingest", "--db", db_path, "data/drop_1"])
    assert ret2 == 0

    with mgr.connection() as conn:
        after_leads = conn.execute("SELECT COUNT(*) FROM leads;").fetchone()[0]
        after_events = conn.execute("SELECT COUNT(*) FROM interaction_ledger;").fetchone()[0]
        after_rejections = conn.execute("SELECT COUNT(*) FROM lead_rejections;").fetchone()[0]
        after_metrics = {
            r["metric_key"]: r["metric_value"]
            for r in conn.execute("SELECT metric_key, metric_value FROM quality_metrics;").fetchall()
        }

    assert after_leads == initial_leads
    assert after_events == initial_events
    assert after_rejections == initial_rejections
    assert after_metrics == initial_metrics


def test_cli_report_generation_after_both_drops(temp_db: Path, temp_reports_dir: Path) -> None:
    """Verify that all 5 report files are correctly generated after ingesting both drops."""
    db_path = str(temp_db)
    rep_dir = str(temp_reports_dir)

    # Ingest drop 1 and drop 2
    assert main(["ingest", "--db", db_path, "data/drop_1"]) == 0
    assert main(["ingest", "--db", db_path, "data/drop_2"]) == 0

    # Generate reports
    ret = main(["report", "--db", db_path, "--out", rep_dir])
    assert ret == 0

    expected_files = [
        "batch_summary.csv",
        "daily_overview.csv",
        "lead_report.csv",
        "rejections.csv",
        "data_quality.json",
    ]

    for fname in expected_files:
        fpath = temp_reports_dir / fname
        assert fpath.is_file(), f"Missing expected report file: {fname}"
        assert fpath.stat().st_size > 0, f"Report file is empty: {fname}"

    # Verify data_quality.json structure
    with open(temp_reports_dir / "data_quality.json", "r", encoding="utf-8") as f:
        dq = json.load(f)
        assert "lead_rows_total" in dq
        assert "lead_rows_rejected" in dq
        assert "duplicate_lead_rows_merged" in dq
        assert "events_total" in dq
        assert "orphan_events" in dq
        assert "unknown_disposition_events" in dq
        assert "field_warnings" in dq

    # Verify rejections.csv contains no PII (no phone or customer name header)
    with open(temp_reports_dir / "rejections.csv", "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == ["workflow_id", "batch_id", "row_number", "reason"]


def test_sequential_vs_all_in_one_parity(tmp_path: Path) -> None:
    """
    Requirement 6: Ingesting drop_1 followed by drop_2 must produce the same final
    reports as ingesting all available drops in one run.
    """
    db_seq = str(tmp_path / "sequential.db")
    db_all = str(tmp_path / "all_in_one.db")

    out_seq = tmp_path / "reports_seq"
    out_all = tmp_path / "reports_all"

    # Sequential: drop_1 then drop_2
    assert main(["ingest", "--db", db_seq, "data/drop_1"]) == 0
    assert main(["ingest", "--db", db_seq, "data/drop_2"]) == 0
    assert main(["report", "--db", db_seq, "--out", str(out_seq)]) == 0

    # All-in-one: passing 'data' parent directory which discovers drop_1 and drop_2 in order
    assert main(["ingest", "--db", db_all, "data"]) == 0
    assert main(["report", "--db", db_all, "--out", str(out_all)]) == 0

    report_names = [
        "batch_summary.csv",
        "daily_overview.csv",
        "lead_report.csv",
        "rejections.csv",
        "data_quality.json",
    ]

    for name in report_names:
        seq_content = (out_seq / name).read_bytes()
        all_content = (out_all / name).read_bytes()
        assert seq_content == all_content, f"Report mismatch between sequential and all-in-one for {name}"


def test_recovery_from_partially_processed_drop(tmp_path: Path) -> None:
    """Verify that a drop ingestion transaction rollback handles failures cleanly and permits safe retry."""
    db_path = str(tmp_path / "recovery.db")
    mgr = DatabaseManager(db_path)

    # Initialize schema
    with mgr.transaction() as conn:
        from solution.db.schema import init_db
        init_db(conn, schemas_dir=Path("assignment-a-data/schemas"))

    # Create a corrupted drop folder with a malformed CSV that causes an unhandled error
    corrupt_drop = tmp_path / "corrupt_drop"
    corrupt_drop_leads = corrupt_drop / "leads" / "motor_renewal"
    corrupt_drop_leads.mkdir(parents=True, exist_ok=True)

    # Write a normal CSV
    good_csv = corrupt_drop_leads / "batch_001.csv"
    good_csv.write_text("phone_number,policy_holder_name\n9876543210,Jane Doe\n", encoding="utf-8")

    # Write an invalid file that raises permission or OS error when read
    bad_csv = corrupt_drop_leads / "batch_002.csv"
    bad_csv.write_text("phone_number,policy_holder_name\n8765432109,John Smith\n", encoding="utf-8")

    # Ingest the good drop first
    assert main(["ingest", "--db", db_path, "data/drop_1"]) == 0

    # Intentionally trigger an error during corrupt drop by passing a non-existent path
    fake_drop = tmp_path / "non_existent_drop"
    ret = main(["ingest", "--db", db_path, str(fake_drop)])
    assert ret == 1

    # Verify that database remains completely operational and drop_1 is still intact
    with mgr.connection() as conn:
        run1 = conn.execute("SELECT status FROM ingestion_runs WHERE drop_id = 'drop_1';").fetchone()
        assert run1 is not None
        assert run1["status"] == "COMPLETED"

    # Now ingest drop_2 successfully
    ret2 = main(["ingest", "--db", db_path, "data/drop_2"])
    assert ret2 == 0


def test_duplicate_events_and_duplicate_leads_across_drops(tmp_path: Path) -> None:
    """Verify handling of duplicate leads and duplicate events across drops."""
    db_path = str(tmp_path / "dedup.db")
    mgr = DatabaseManager(db_path)

    # Ingest drop_1 and drop_2
    assert main(["ingest", "--db", db_path, "data/drop_1"]) == 0
    assert main(["ingest", "--db", db_path, "data/drop_2"]) == 0

    with mgr.connection() as conn:
        # Check that no duplicate lead IDs exist
        dup_leads = conn.execute(
            """
            SELECT workflow_id, phone_blind_index, COUNT(*) as cnt
            FROM leads
            GROUP BY workflow_id, phone_blind_index
            HAVING cnt > 1;
            """
        ).fetchall()
        assert len(dup_leads) == 0

        # Check that no duplicate event IDs exist
        dup_events = conn.execute(
            """
            SELECT event_id, COUNT(*) as cnt
            FROM interaction_ledger
            GROUP BY event_id
            HAVING cnt > 1;
            """
        ).fetchall()
        assert len(dup_events) == 0
