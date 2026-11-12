"""Database DDL definitions, indexing, and schema initialization strategy."""
from __future__ import annotations

import csv
import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger("agentic_universe.schema")

SCHEMA_DDL = """
-- ============================================================================
-- 1. WORKFLOWS & REFERENCE CATALOGUES
-- ============================================================================

CREATE TABLE IF NOT EXISTS workflows (
    workflow_id VARCHAR(50) PRIMARY KEY,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS disposition_catalogue (
    workflow_id VARCHAR(50) NOT NULL REFERENCES workflows(workflow_id),
    code VARCHAR(50) NOT NULL,
    label VARCHAR(100) NOT NULL,
    is_terminal BOOLEAN NOT NULL CHECK (is_terminal IN (0, 1)),
    is_success BOOLEAN NOT NULL CHECK (is_success IN (0, 1)),
    PRIMARY KEY (workflow_id, code)
);

-- ============================================================================
-- 2. INGESTION RUNS & IDEMPOTENCY TRACKING
-- ============================================================================

CREATE TABLE IF NOT EXISTS ingestion_runs (
    drop_id VARCHAR(100) PRIMARY KEY,
    status VARCHAR(20) NOT NULL CHECK (status IN ('IN_PROGRESS', 'COMPLETED', 'FAILED')),
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ingested_files (
    file_path VARCHAR(255) PRIMARY KEY,
    drop_id VARCHAR(100) NOT NULL REFERENCES ingestion_runs(drop_id),
    file_type VARCHAR(20) NOT NULL CHECK (file_type IN ('lead_csv', 'event_jsonl')),
    file_hash CHAR(64) NOT NULL,
    record_count INTEGER NOT NULL DEFAULT 0,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 3. LEADS & REJECTIONS (ENCRYPTED PII)
-- ============================================================================

CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id VARCHAR(50) NOT NULL REFERENCES workflows(workflow_id),
    phone_blind_index CHAR(64) NOT NULL,
    phone_masked VARCHAR(20) NOT NULL,
    phone_encrypted TEXT NOT NULL,
    customer_name_encrypted TEXT NOT NULL,
    external_ref VARCHAR(100) NOT NULL,
    batch_id VARCHAR(50) NOT NULL,
    preferred_language VARCHAR(10) DEFAULT 'en',
    attributes_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (workflow_id, phone_blind_index)
);

CREATE TABLE IF NOT EXISTS lead_rejections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id VARCHAR(50) NOT NULL REFERENCES workflows(workflow_id),
    batch_id VARCHAR(50) NOT NULL,
    row_number INTEGER NOT NULL,
    reason VARCHAR(100) NOT NULL,
    drop_id VARCHAR(100) NOT NULL REFERENCES ingestion_runs(drop_id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (workflow_id, batch_id, row_number)
);

-- ============================================================================
-- 4. APPEND-ONLY INTERACTION LEDGER
-- ============================================================================

CREATE TABLE IF NOT EXISTS interaction_ledger (
    event_id VARCHAR(50) PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    workflow_id VARCHAR(50) NOT NULL REFERENCES workflows(workflow_id),
    call_id VARCHAR(50) NOT NULL,
    occurred_at_utc TIMESTAMP NOT NULL,
    occurred_at_ist TIMESTAMP NOT NULL,
    phone_blind_index CHAR(64),
    disposition_code VARCHAR(50),
    payload_json TEXT NOT NULL,
    lead_id INTEGER REFERENCES leads(id),
    is_orphan BOOLEAN NOT NULL DEFAULT 1 CHECK (is_orphan IN (0, 1)),
    drop_id VARCHAR(100) NOT NULL REFERENCES ingestion_runs(drop_id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 5. DATA QUALITY METRICS
-- ============================================================================

CREATE TABLE IF NOT EXISTS quality_metrics (
    scope VARCHAR(50) NOT NULL,
    metric_key VARCHAR(100) NOT NULL,
    metric_value INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (scope, metric_key)
);

-- ============================================================================
-- 6. PERFORMANCE & REPORT INDEXES
-- ============================================================================

-- Accelerates lead_report.csv sorting: ORDER BY workflow_id, external_ref
CREATE INDEX IF NOT EXISTS idx_leads_report_order 
ON leads (workflow_id, external_ref);

-- Accelerates batch_summary.csv grouping: GROUP BY workflow_id, batch_id
CREATE INDEX IF NOT EXISTS idx_leads_batch_grouping 
ON leads (workflow_id, batch_id);

-- Accelerates rejections.csv sorting: ORDER BY workflow_id, batch_id, row_number
CREATE INDEX IF NOT EXISTS idx_rejections_order 
ON lead_rejections (workflow_id, batch_id, row_number);

-- Accelerates call-level lookup and overrides linking
CREATE INDEX IF NOT EXISTS idx_ledger_call_id 
ON interaction_ledger (call_id);

-- Accelerates chronologically ordered call event facts extraction for reporting
CREATE INDEX IF NOT EXISTS idx_ledger_call_events 
ON interaction_ledger (is_orphan, call_id, occurred_at_utc);

-- Partial index for high-speed orphan reconciliation
CREATE INDEX IF NOT EXISTS idx_ledger_orphan_matching 
ON interaction_ledger (workflow_id, phone_blind_index) 
WHERE is_orphan = 1;

-- Accelerates lead-level event queries in reports
CREATE INDEX IF NOT EXISTS idx_ledger_lead_event 
ON interaction_ledger (lead_id, event_type);

-- Accelerates daily overview call aggregation
CREATE INDEX IF NOT EXISTS idx_ledger_ist_date 
ON interaction_ledger (workflow_id, date(occurred_at_ist), event_type);
"""


def init_db(conn: sqlite3.Connection, schemas_dir: Optional[Path] = None) -> None:
    """
    Initialize database schema, constraints, and indexes idempotently.
    Optionally seeds workflow metadata and disposition catalogue from assignment schemas.
    """
    with conn:
        conn.executescript(SCHEMA_DDL)

    if schemas_dir and schemas_dir.is_dir():
        seed_catalogues(conn, schemas_dir)


def seed_catalogues(conn: sqlite3.Connection, schemas_dir: Path) -> None:
    """Seed workflow definitions and disposition catalog from assignment-a-data/schemas."""
    # Seed workflows from JSON schema files
    for schema_file in schemas_dir.glob("*.json"):
        try:
            with open(schema_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                wf_id = data.get("workflow_id")
                desc = data.get("description", "")
                if wf_id:
                    with conn:
                        conn.execute(
                            "INSERT OR IGNORE INTO workflows (workflow_id, description) VALUES (?, ?);",
                            (wf_id, desc),
                        )
        except Exception as exc:
            logger.warning("Could not read schema file %s: %s", schema_file, exc)

    # Seed dispositions from dispositions.csv
    disp_file = schemas_dir / "dispositions.csv"
    if disp_file.is_file():
        try:
            with open(disp_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                with conn:
                    for row in reader:
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO disposition_catalogue 
                            (workflow_id, code, label, is_terminal, is_success) 
                            VALUES (?, ?, ?, ?, ?);
                            """,
                            (
                                row["workflow_id"].strip(),
                                row["code"].strip(),
                                row["label"].strip(),
                                1 if row["is_terminal"].strip().lower() == "true" else 0,
                                1 if row["is_success"].strip().lower() == "true" else 0,
                            ),
                        )
        except Exception as exc:
            logger.warning("Could not load dispositions catalogue from %s: %s", disp_file, exc)

