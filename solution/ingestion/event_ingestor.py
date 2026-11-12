"""Event ingestion pipeline: append-only ledger, deduplication, timestamp normalization, and orphan tracking."""
from __future__ import annotations

import csv
import datetime
import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from solution.config import IST, Config
from solution.crypto.pii import PIIEngine
from solution.db.connection import DatabaseManager
from solution.db.schema import init_db
from solution.ingestion.normalizers import normalize_phone
from solution.ingestion.reconciler import reconcile_orphans

logger = logging.getLogger("agentic_universe.event_ingestor")


@dataclass
class EventIngestionSummary:
    """Summary of metrics for an event ingestion run."""

    files_processed: int = 0
    files_skipped: int = 0
    events_total: int = 0
    malformed_events: int = 0
    duplicate_events_dropped: int = 0
    orphan_events: int = 0
    unknown_disposition_events: int = 0


def parse_event_timestamp(ts_str: str) -> Tuple[str, str]:
    """
    Parse an event timestamp into normalized (occurred_at_utc, occurred_at_ist) ISO strings.
    
    Rules:
    - UTC: '...Z'
    - Offset: '...+05:30'
    - Naive: 'YYYY-MM-DD HH:MM:SS' -> 'Naive means IST.'
    """
    cleaned = ts_str.strip()
    try:
        dt = datetime.datetime.fromisoformat(cleaned)
    except ValueError as exc:
        # Fallback for standard formats if fromisoformat fails
        if cleaned.endswith("Z"):
            dt = datetime.datetime.strptime(cleaned, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=datetime.timezone.utc
            )
        else:
            dt = datetime.datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S")

    if dt.tzinfo is None:
        # Per specification: "Naive means IST."
        ist_dt = dt.replace(tzinfo=IST)
        utc_dt = ist_dt.astimezone(datetime.timezone.utc)
    else:
        utc_dt = dt.astimezone(datetime.timezone.utc)
        ist_dt = dt.astimezone(IST)

    utc_iso = utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    ist_iso = ist_dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")

    return utc_iso, ist_iso


class EventIngestor:
    """Ingests JSONL call events into an append-only interaction ledger."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        pii_engine: PIIEngine,
        schemas_dir: Path = Path("assignment-a-data/schemas"),
    ) -> None:
        self.db_mgr = db_manager
        self.pii = pii_engine
        self.schemas_dir = schemas_dir
        self.valid_dispositions = self._load_dispositions_catalogue()

    @classmethod
    def from_config(cls, cfg: Config) -> EventIngestor:
        """Factory method constructing EventIngestor from configuration."""
        db_mgr = DatabaseManager(cfg.database_path)
        pii = PIIEngine(cfg.pii_secret_key)
        return cls(db_manager=db_mgr, pii_engine=pii)

    def _load_dispositions_catalogue(self) -> Dict[str, Set[str]]:
        """Load valid disposition codes per workflow from dispositions.csv."""
        catalogue: Dict[str, Set[str]] = {}
        disp_file = self.schemas_dir / "dispositions.csv"
        if disp_file.is_file():
            with open(disp_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    wf = row["workflow_id"].strip()
                    code = row["code"].strip()
                    if wf not in catalogue:
                        catalogue[wf] = set()
                    catalogue[wf].add(code)
        return catalogue

    def ingest_drop(self, drop_path: Path) -> EventIngestionSummary:
        """
        Ingest all JSONL event files in a given drop directory in filename order.
        """
        summary = EventIngestionSummary()
        events_dir = drop_path / "events"
        if not events_dir.is_dir():
            logger.info("No events directory found in %s; skipping event ingestion.", drop_path)
            return summary

        drop_id = drop_path.name

        with self.db_mgr.transaction() as conn:
            init_db(conn, schemas_dir=self.schemas_dir)
            conn.execute(
                "INSERT OR IGNORE INTO ingestion_runs (drop_id, status) VALUES (?, 'IN_PROGRESS');",
                (drop_id,),
            )

            # Discover event files in strict alphabetical filename order
            event_files = sorted([f for f in events_dir.glob("*.jsonl") if f.is_file()])

            for event_file in event_files:
                file_summary = self._ingest_single_file(conn, drop_id, event_file)
                if file_summary is None:
                    summary.files_skipped += 1
                    continue

                summary.files_processed += 1
                summary.events_total += file_summary.events_total
                summary.malformed_events += file_summary.malformed_events
                summary.duplicate_events_dropped += file_summary.duplicate_events_dropped
                summary.unknown_disposition_events += file_summary.unknown_disposition_events

            # Run orphan reconciliation after loading all events in the drop
            reconcile_orphans(conn)

            # Count final orphan events in ledger
            cur = conn.execute("SELECT COUNT(*) FROM interaction_ledger WHERE is_orphan = 1;")
            summary.orphan_events = cur.fetchone()[0]

            # Update quality_metrics in database
            self._save_quality_metrics(conn, summary)

        return summary

    def _ingest_single_file(
        self,
        conn: sqlite3.Connection,
        drop_id: str,
        event_file: Path,
    ) -> Optional[EventIngestionSummary]:
        """Ingest a single event JSONL file line-by-line in strict specification order."""
        file_path_str = str(event_file).replace("\\", "/")
        file_hash = self._compute_file_hash(event_file)

        # Check idempotency: If already ingested with same hash, skip
        existing = conn.execute(
            "SELECT file_hash FROM ingested_files WHERE file_path = ?;",
            (file_path_str,),
        ).fetchone()
        if existing and existing["file_hash"] == file_hash:
            logger.info("Event file %s already ingested; skipping.", event_file.name)
            return None

        summary = EventIngestionSummary()
        ledger_batch: List[Tuple] = []
        seen_in_batch: Set[str] = set()

        with open(event_file, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    # Skip empty lines (blank lines not counted)
                    continue

                # Count every non-empty line read
                summary.events_total += 1

                # 1. Malformed check: not valid JSON, or has no event_id
                try:
                    data = json.loads(stripped)
                except Exception:
                    summary.malformed_events += 1
                    continue

                if not isinstance(data, dict):
                    summary.malformed_events += 1
                    continue

                raw_event_id = data.get("event_id")
                if not raw_event_id or not str(raw_event_id).strip():
                    summary.malformed_events += 1
                    continue

                event_id = str(raw_event_id).strip()

                # 2. Duplicate check: event_id already seen in this batch or in any drop
                if event_id in seen_in_batch or self._event_exists(conn, event_id):
                    summary.duplicate_events_dropped += 1
                    continue
                seen_in_batch.add(event_id)

                event_type = str(data.get("event_type", "")).strip()
                workflow_id = str(data.get("workflow_id", "")).strip()
                call_id = str(data.get("call_id", "")).strip()
                occurred_at_raw = str(data.get("occurred_at", "")).strip()
                payload = data.get("payload", {})
                if not isinstance(payload, dict):
                    payload = {}

                # 4. Unknown disposition check: disposition.* with code not in catalogue
                disposition_code = None
                if event_type in ("disposition.set", "disposition.override"):
                    raw_code = payload.get("disposition_code")
                    if raw_code:
                        disposition_code = str(raw_code).strip()
                        wf_catalog = self.valid_dispositions.get(workflow_id, set())
                        if disposition_code not in wf_catalog:
                            summary.unknown_disposition_events += 1

                # Parse timestamp
                try:
                    utc_iso, ist_iso = parse_event_timestamp(occurred_at_raw)
                except Exception:
                    # If timestamp cannot be parsed, treat as malformed
                    summary.malformed_events += 1
                    continue

                # 3. Orphan check: link to valid lead
                raw_phone = data.get("phone")
                phone_blind_index: Optional[str] = None
                lead_id: Optional[int] = None
                is_orphan: int = 1

                if raw_phone:
                    is_valid, canon_phone = normalize_phone(str(raw_phone))
                    if is_valid and canon_phone:
                        phone_blind_index = self.pii.compute_blind_index(canon_phone)
                        # Query lead
                        lead_row = conn.execute(
                            "SELECT id FROM leads WHERE workflow_id = ? AND phone_blind_index = ?;",
                            (workflow_id, phone_blind_index),
                        ).fetchone()
                        if lead_row:
                            lead_id = lead_row["id"]
                            is_orphan = 0
                elif event_type == "disposition.override":
                    # Overrides have no phone, only call_id; link via existing call sibling
                    call_lead = conn.execute(
                        """
                        SELECT lead_id FROM interaction_ledger 
                        WHERE call_id = ? AND lead_id IS NOT NULL 
                        LIMIT 1;
                        """,
                        (call_id,),
                    ).fetchone()
                    if call_lead:
                        lead_id = call_lead["lead_id"]
                        is_orphan = 0

                # Note: Zero plaintext PII is stored. Raw phone is excluded from payload_json!
                sanitized_payload = {k: v for k, v in payload.items() if k != "phone"} if isinstance(payload, dict) else {}
                payload_json = json.dumps(sanitized_payload)

                ledger_batch.append(
                    (
                        event_id,
                        event_type,
                        workflow_id,
                        call_id,
                        utc_iso,
                        ist_iso,
                        phone_blind_index,
                        disposition_code,
                        payload_json,
                        lead_id,
                        is_orphan,
                        drop_id,
                    )
                )

        # Batch insert into append-only interaction ledger
        if ledger_batch:
            conn.executemany(
                """
                INSERT OR IGNORE INTO interaction_ledger (
                    event_id, event_type, workflow_id, call_id,
                    occurred_at_utc, occurred_at_ist, phone_blind_index,
                    disposition_code, payload_json, lead_id, is_orphan, drop_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                ledger_batch,
            )

        # Record file audit
        conn.execute(
            """
            INSERT OR REPLACE INTO ingested_files 
            (file_path, drop_id, file_type, file_hash, record_count) 
            VALUES (?, ?, 'event_jsonl', ?, ?);
            """,
            (file_path_str, drop_id, file_hash, summary.events_total),
        )

        return summary

    @staticmethod
    def _event_exists(conn: sqlite3.Connection, event_id: str) -> bool:
        """Check if an event_id already exists in the interaction ledger."""
        row = conn.execute(
            "SELECT 1 FROM interaction_ledger WHERE event_id = ?;",
            (event_id,),
        ).fetchone()
        return row is not None

    def _save_quality_metrics(self, conn: sqlite3.Connection, summary: EventIngestionSummary) -> None:
        """Update quality_metrics table with cumulative event metrics."""
        # Incremental metrics
        incremental_metrics = {
            "events_total": summary.events_total,
            "malformed_events": summary.malformed_events,
            "duplicate_events_dropped": summary.duplicate_events_dropped,
            "unknown_disposition_events": summary.unknown_disposition_events,
        }
        for k, v in incremental_metrics.items():
            conn.execute(
                """
                INSERT INTO quality_metrics (scope, metric_key, metric_value)
                VALUES ('global', ?, ?)
                ON CONFLICT (scope, metric_key) DO UPDATE SET
                    metric_value = quality_metrics.metric_value + excluded.metric_value,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (k, v),
            )

        # Orphan count reflects the current final state in interaction_ledger
        cur = conn.execute("SELECT COUNT(*) FROM interaction_ledger WHERE is_orphan = 1;")
        orphan_count = cur.fetchone()[0]
        conn.execute(
            """
            INSERT INTO quality_metrics (scope, metric_key, metric_value)
            VALUES ('global', 'orphan_events', ?)
            ON CONFLICT (scope, metric_key) DO UPDATE SET
                metric_value = excluded.metric_value,
                updated_at = CURRENT_TIMESTAMP;
            """,
            (orphan_count,),
        )

    @staticmethod
    def _compute_file_hash(filepath: Path) -> str:
        """Compute SHA-256 hash of a file for idempotency tracking."""
        hasher = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

