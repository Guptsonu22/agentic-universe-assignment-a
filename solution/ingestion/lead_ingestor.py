"""Lead ingestion pipeline: CSV parsing, schema validation, deduplication, and merging."""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from solution.config import Config
from solution.crypto.pii import PIIEngine, mask_phone
from solution.db.connection import DatabaseManager
from solution.db.schema import init_db
from solution.domain.schemas import FieldSchema, WorkflowSchema, load_workflow_schemas
from solution.ingestion.normalizers import (
    normalize_date,
    normalize_decimal,
    normalize_enum,
    normalize_phone,
    normalize_string,
)
from solution.ingestion.reconciler import reconcile_orphans

logger = logging.getLogger("agentic_universe.lead_ingestor")


@dataclass
class IngestionSummary:
    """Summary of metrics for a lead ingestion run."""

    files_processed: int = 0
    files_skipped: int = 0
    lead_rows_total: int = 0
    lead_rows_rejected: int = 0
    rejections_by_reason: Dict[str, int] = field(default_factory=dict)
    duplicate_lead_rows_merged: int = 0
    field_warnings: int = 0


class LeadIngestor:
    """Ingests and reconciles messy lead CSV batches against workflow schemas."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        pii_engine: PIIEngine,
        schemas_dir: Path = Path("assignment-a-data/schemas"),
    ) -> None:
        self.db_mgr = db_manager
        self.pii = pii_engine
        self.schemas_dir = schemas_dir
        self.schemas = load_workflow_schemas(schemas_dir)

    @classmethod
    def from_config(cls, cfg: Config) -> LeadIngestor:
        """Factory method constructing LeadIngestor from configuration."""
        db_mgr = DatabaseManager(cfg.database_path)
        pii = PIIEngine(cfg.pii_secret_key)
        return cls(db_manager=db_mgr, pii_engine=pii)

    def ingest_drop(self, drop_path: Path) -> IngestionSummary:
        """
        Ingest all lead CSV files in a given drop directory.
        Files are processed in strict filename order per workflow.
        """
        summary = IngestionSummary()
        leads_dir = drop_path / "leads"
        if not leads_dir.is_dir():
            logger.info("No leads directory found in %s; skipping lead ingestion.", drop_path)
            return summary

        drop_id = drop_path.name

        with self.db_mgr.transaction() as conn:
            # Initialize schema & ensure drop record exists
            init_db(conn, schemas_dir=self.schemas_dir)
            conn.execute(
                "INSERT OR IGNORE INTO ingestion_runs (drop_id, status) VALUES (?, 'IN_PROGRESS');",
                (drop_id,),
            )

            # Discover workflow directories in alphabetical order
            wf_dirs = sorted([d for d in leads_dir.iterdir() if d.is_dir()])
            for wf_dir in wf_dirs:
                wf_id = wf_dir.name
                if wf_id not in self.schemas:
                    logger.warning("Unrecognized workflow '%s'; skipping directory.", wf_id)
                    continue

                schema = self.schemas[wf_id]
                csv_files = sorted([f for f in wf_dir.glob("*.csv") if f.is_file()])

                for csv_file in csv_files:
                    file_summary = self._ingest_single_file(conn, drop_id, schema, csv_file)
                    if file_summary is None:
                        summary.files_skipped += 1
                        continue

                    summary.files_processed += 1
                    summary.lead_rows_total += file_summary.lead_rows_total
                    summary.lead_rows_rejected += file_summary.lead_rows_rejected
                    summary.duplicate_lead_rows_merged += file_summary.duplicate_lead_rows_merged
                    summary.field_warnings += file_summary.field_warnings
                    for reason, count in file_summary.rejections_by_reason.items():
                        summary.rejections_by_reason[reason] = (
                            summary.rejections_by_reason.get(reason, 0) + count
                        )

            # Reconcile previously orphaned events against newly ingested leads
            reconcile_orphans(conn)

            # Persist updated cumulative metrics to database
            self._save_quality_metrics(conn, summary)

            # Update orphan events count in quality metrics to reflect final state
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

        return summary

    def _ingest_single_file(
        self,
        conn: sqlite3.Connection,
        drop_id: str,
        schema: WorkflowSchema,
        csv_file: Path,
    ) -> Optional[IngestionSummary]:
        """Process a single lead CSV file."""
        file_path_str = str(csv_file).replace("\\", "/")
        file_hash = self._compute_file_hash(csv_file)
        batch_id = csv_file.stem

        # Check idempotency: If already ingested with same hash, skip
        existing = conn.execute(
            "SELECT file_hash FROM ingested_files WHERE file_path = ?;",
            (file_path_str,),
        ).fetchone()
        if existing and existing["file_hash"] == file_hash:
            logger.info("File %s already ingested; skipping.", csv_file.name)
            return None

        summary = IngestionSummary()

        with open(csv_file, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header_row = next(reader, None)
            if not header_row:
                return summary

            header_map = schema.map_headers(header_row)

            row_number = 0
            for raw_row in reader:
                # 1. Blank row check: all cells empty or whitespace
                if not raw_row or all(not cell.strip() for cell in raw_row):
                    continue

                # Count non-blank data rows starting at 1
                row_number += 1
                summary.lead_rows_total += 1

                # Build row map {field_name: raw_value_str}
                row_values: Dict[str, Optional[str]] = {}
                for idx, cell in enumerate(raw_row):
                    if idx < len(header_row):
                        raw_col = header_row[idx]
                        if raw_col in header_map:
                            field_schema = header_map[raw_col]
                            trimmed = cell.strip()
                            row_values[field_schema.name] = trimmed if trimmed else None

                # 2. Validation in Schema Order
                rejection_reason = self._validate_row_in_schema_order(schema, row_values)
                if rejection_reason:
                    summary.lead_rows_rejected += 1
                    summary.rejections_by_reason[rejection_reason] = (
                        summary.rejections_by_reason.get(rejection_reason, 0) + 1
                    )
                    # Record rejection (zero PII)
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO lead_rejections 
                        (workflow_id, batch_id, row_number, reason, drop_id) 
                        VALUES (?, ?, ?, ?, ?);
                        """,
                        (schema.workflow_id, batch_id, row_number, rejection_reason, drop_id),
                    )
                    continue

                # 3. Normalize values and record warnings (only for accepted rows)
                normalized_row, warnings_count = self._normalize_accepted_row(schema, row_values)
                summary.field_warnings += warnings_count

                # 4. Identity & Upsert (Merge duplicates)
                is_duplicate = self._upsert_lead(conn, schema, batch_id, normalized_row)
                if is_duplicate:
                    summary.duplicate_lead_rows_merged += 1

        # Record file ingestion audit
        conn.execute(
            """
            INSERT OR REPLACE INTO ingested_files 
            (file_path, drop_id, file_type, file_hash, record_count) 
            VALUES (?, ?, 'lead_csv', ?, ?);
            """,
            (file_path_str, drop_id, file_hash, summary.lead_rows_total),
        )

        return summary

    def _validate_row_in_schema_order(
        self,
        schema: WorkflowSchema,
        row_values: Dict[str, Optional[str]],
    ) -> Optional[str]:
        """
        Validate row fields in the exact order specified in schema.
        Returns the first rejection reason, or None if valid.
        """
        for field in schema.fields:
            val = row_values.get(field.name)

            # Check required
            if field.required and not val:
                return f"missing_required:{field.name}"

            # Check phone if present
            if field.type == "phone" and val:
                is_valid, _ = normalize_phone(val)
                if not is_valid:
                    return "invalid_phone"

        return None

    def _normalize_accepted_row(
        self,
        schema: WorkflowSchema,
        row_values: Dict[str, Optional[str]],
    ) -> Tuple[Dict[str, Any], int]:
        """
        Normalise all fields for an accepted row.
        Invalid optional fields become None and increment warning count.
        """
        normalized: Dict[str, Any] = {}
        warnings = 0

        for field in schema.fields:
            raw_val = row_values.get(field.name)

            if not raw_val:
                normalized[field.name] = None
                continue

            if field.type == "phone":
                _, canon_phone = normalize_phone(raw_val)
                normalized[field.name] = canon_phone
            elif field.type == "date":
                is_valid, norm_date = normalize_date(raw_val)
                if is_valid:
                    normalized[field.name] = norm_date
                else:
                    normalized[field.name] = None
                    warnings += 1
            elif field.type == "decimal":
                is_valid, norm_dec = normalize_decimal(raw_val)
                if is_valid:
                    normalized[field.name] = norm_dec
                else:
                    normalized[field.name] = None
                    warnings += 1
            elif field.type == "enum":
                is_valid, norm_enum = normalize_enum(raw_val, field.values)
                if is_valid:
                    normalized[field.name] = norm_enum
                else:
                    normalized[field.name] = None
                    warnings += 1
            elif field.type == "string":
                is_valid, norm_str = normalize_string(raw_val)
                normalized[field.name] = norm_str if is_valid else None

        return normalized, warnings

    def _upsert_lead(
        self,
        conn: sqlite3.Connection,
        schema: WorkflowSchema,
        batch_id: str,
        normalized_row: Dict[str, Any],
    ) -> bool:
        """
        Insert a new lead or merge into an existing lead.
        Returns True if this was a duplicate merged row, False if newly created.
        """
        canon_phone = normalized_row["phone"]
        phone_blind_index = self.pii.compute_blind_index(canon_phone)
        phone_masked = mask_phone(canon_phone)
        phone_encrypted = self.pii.encrypt(canon_phone)

        customer_name = normalized_row["customer_name"]
        customer_name_encrypted = self.pii.encrypt(customer_name)

        ref_field = schema.reference_field
        if not ref_field:
            raise ValueError(f"Schema for workflow '{schema.workflow_id}' lacks a reference field.")
        external_ref = str(normalized_row[ref_field.name])

        preferred_language = normalized_row.get("preferred_language")

        # Collect workflow-specific attributes (excluding primary columns)
        attributes: Dict[str, Any] = {}
        for f in schema.fields:
            if f.name not in ("phone", "customer_name", ref_field.name, "preferred_language"):
                if normalized_row.get(f.name) is not None:
                    attributes[f.name] = normalized_row[f.name]

        # Check existing lead
        existing = conn.execute(
            """
            SELECT id, batch_id, phone_masked, phone_encrypted, customer_name_encrypted,
                   external_ref, preferred_language, attributes_json 
            FROM leads 
            WHERE workflow_id = ? AND phone_blind_index = ?;
            """,
            (schema.workflow_id, phone_blind_index),
        ).fetchone()

        if existing is None:
            # First valid record creates the lead. Apply defaults to null fields.
            for f in schema.fields:
                if f.default is not None:
                    if f.name == "preferred_language" and preferred_language is None:
                        preferred_language = f.default
                    elif f.name in attributes and attributes[f.name] is None:
                        attributes[f.name] = f.default

            conn.execute(
                """
                INSERT INTO leads (
                    workflow_id, phone_blind_index, phone_masked, phone_encrypted,
                    customer_name_encrypted, external_ref, batch_id, preferred_language,
                    attributes_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    schema.workflow_id,
                    phone_blind_index,
                    phone_masked,
                    phone_encrypted,
                    customer_name_encrypted,
                    external_ref,
                    batch_id,  # Permanent batch_id
                    preferred_language,
                    json.dumps(attributes),
                ),
            )
            return False
        else:
            # Duplicate lead: merge non-null fields; retain original batch_id
            existing_lang = existing["preferred_language"]
            new_lang = preferred_language if preferred_language is not None else existing_lang

            # Merge customer_name and external_ref if provided (last write wins)
            new_name_enc = (
                customer_name_encrypted
                if customer_name is not None
                else existing["customer_name_encrypted"]
            )
            new_ref = external_ref if external_ref is not None else existing["external_ref"]

            # Merge attributes
            existing_attrs = json.loads(existing["attributes_json"] or "{}")
            for k, v in attributes.items():
                if v is not None:
                    existing_attrs[k] = v

            # Apply defaults after merging to any fields still null
            for f in schema.fields:
                if f.default is not None:
                    if f.name == "preferred_language" and new_lang is None:
                        new_lang = f.default
                    elif f.name in existing_attrs and existing_attrs[f.name] is None:
                        existing_attrs[f.name] = f.default

            conn.execute(
                """
                UPDATE leads SET
                    phone_masked = ?,
                    phone_encrypted = ?,
                    customer_name_encrypted = ?,
                    external_ref = ?,
                    preferred_language = ?,
                    attributes_json = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?;
                """,
                (
                    phone_masked,
                    phone_encrypted,
                    new_name_enc,
                    new_ref,
                    new_lang,
                    json.dumps(existing_attrs),
                    existing["id"],
                ),
            )
            return True

    def _save_quality_metrics(self, conn: sqlite3.Connection, summary: IngestionSummary) -> None:
        """Update the quality_metrics table with cumulative lead counts."""
        metrics = {
            "lead_rows_total": summary.lead_rows_total,
            "lead_rows_rejected": summary.lead_rows_rejected,
            "duplicate_lead_rows_merged": summary.duplicate_lead_rows_merged,
            "field_warnings": summary.field_warnings,
        }
        for k, v in metrics.items():
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

    @staticmethod
    def _compute_file_hash(filepath: Path) -> str:
        """Compute SHA-256 hash of a file for idempotency tracking."""
        hasher = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
