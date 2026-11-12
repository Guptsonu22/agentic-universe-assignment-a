"""Command Line Interface (CLI) entry point for Assignment A."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Sequence

# Ensure repository root is in sys.path when invoked directly as a script
_repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from solution.config import Config, setup_logging
from solution.db.connection import DatabaseManager
from solution.db.schema import init_db
from solution.ingestion.event_ingestor import EventIngestor
from solution.ingestion.lead_ingestor import LeadIngestor
from solution.reporting.report_generator import ReportGenerator


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser with subcommands and flexible option placement."""
    db_parent = argparse.ArgumentParser(add_help=False)
    db_parent.add_argument(
        "--db",
        dest="database_path",
        default=argparse.SUPPRESS,
        help="Path to SQLite database file (defaults to DATABASE_PATH env var or au_ledger.db)",
    )

    parser = argparse.ArgumentParser(
        prog="au-pipeline",
        parents=[db_parent],
        description="Agentic Universe - Interaction Ledger & Reporting Pipeline (Assignment A)",
    )

    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # 1. init-db
    init_parser = subparsers.add_parser(
        "init-db",
        parents=[db_parent],
        help="Initialize database tables, constraints, indexes, and reference catalogues",
    )
    init_parser.add_argument(
        "--schemas",
        dest="schemas_dir",
        default="assignment-a-data/schemas",
        help="Directory containing workflow JSON schemas and dispositions.csv",
    )

    # 2. ingest <drop_paths>
    ingest_parser = subparsers.add_parser(
        "ingest",
        parents=[db_parent],
        help="Ingest daily data drop(s) (leads and events)",
    )
    ingest_parser.add_argument(
        "drop_paths",
        nargs="+",
        type=str,
        help="Path(s) to drop folder(s) (e.g. data/drop_1) or parent directory containing drops (e.g. data)",
    )
    ingest_parser.add_argument(
        "--schemas",
        dest="schemas_dir",
        default="assignment-a-data/schemas",
        help="Directory containing workflow JSON schemas and dispositions.csv",
    )

    # 3. report --out <dir>
    report_parser = subparsers.add_parser(
        "report",
        parents=[db_parent],
        help="Generate the 5 required report files",
    )
    report_parser.add_argument(
        "--out",
        dest="out_dir",
        required=True,
        help="Output directory where report CSVs and JSON will be saved",
    )

    return parser


def handle_init_db(args: argparse.Namespace, cfg: Config) -> int:
    """Initialize SQLite database tables and seed metadata."""
    logger = setup_logging(cfg.log_level)
    db_mgr = DatabaseManager(cfg.database_path)
    raw_schemas = getattr(args, "schemas_dir", "assignment-a-data/schemas")
    schemas_path = Path(raw_schemas)
    if not schemas_path.exists():
        candidate = Path(_repo_root) / raw_schemas
        if candidate.exists():
            schemas_path = candidate

    logger.info("Initializing database at: %s", cfg.database_path)
    with db_mgr.connection() as conn:
        init_db(conn, schemas_dir=schemas_path if schemas_path.exists() else None)

    logger.info("Database initialized successfully.")
    return 0


def resolve_drop_directories(inputs: Sequence[str]) -> List[Path]:
    """
    Resolve given input paths to a deterministic, ordered list of drop directories.
    - If a path contains 'leads' or 'events', it is directly a drop directory.
    - If a path contains subdirectories that have 'leads' or 'events', its children are sorted and returned.
    """
    resolved: List[Path] = []
    for raw_input in inputs:
        p = Path(raw_input)
        if not p.exists():
            raise FileNotFoundError(f"Drop path does not exist: {p}")
        if not p.is_dir():
            raise NotADirectoryError(f"Drop path is not a directory: {p}")

        if (p / "leads").is_dir() or (p / "events").is_dir():
            if p not in resolved:
                resolved.append(p)
            continue

        child_drops = sorted([
            child for child in p.iterdir()
            if child.is_dir() and ((child / "leads").is_dir() or (child / "events").is_dir())
        ])
        if child_drops:
            for child in child_drops:
                if child not in resolved:
                    resolved.append(child)
        else:
            raise ValueError(f"No valid drops found in '{p}' (expected 'leads' or 'events' directory)")
    return resolved


def handle_ingest(args: argparse.Namespace, cfg: Config) -> int:
    """Ingest one or more data drops (leads and events) in deterministic order."""
    logger = setup_logging(cfg.log_level)

    try:
        drop_dirs = resolve_drop_directories(args.drop_paths)
    except Exception as exc:
        logger.error("Failed to resolve drop paths: %s", exc)
        return 1

    raw_schemas = getattr(args, "schemas_dir", "assignment-a-data/schemas")
    schemas_dir = Path(raw_schemas)
    if not schemas_dir.exists():
        candidate = Path(_repo_root) / raw_schemas
        if candidate.exists():
            schemas_dir = candidate
    db_mgr = DatabaseManager(cfg.database_path)

    for drop_path in drop_dirs:
        logger.info("Starting ingestion for drop: %s", drop_path)
        try:
            lead_ingestor = LeadIngestor(
                db_manager=db_mgr,
                pii_engine=LeadIngestor.from_config(cfg).pii,
                schemas_dir=schemas_dir,
            )
            lead_summary = lead_ingestor.ingest_drop(drop_path)

            event_ingestor = EventIngestor(
                db_manager=db_mgr,
                pii_engine=EventIngestor.from_config(cfg).pii,
                schemas_dir=schemas_dir,
            )
            event_summary = event_ingestor.ingest_drop(drop_path)

            with db_mgr.transaction() as conn:
                conn.execute(
                    "UPDATE ingestion_runs SET status = 'COMPLETED' WHERE drop_id = ?;",
                    (drop_path.name,),
                )

            logger.info(
                "Ingestion completed for drop %s: "
                "Leads: [%d files, %d total, %d rejected, %d merged, %d warnings] | "
                "Events: [%d files, %d total, %d malformed, %d duplicates dropped, %d orphans, %d unknown dispositions]",
                drop_path.name,
                lead_summary.files_processed,
                lead_summary.lead_rows_total,
                lead_summary.lead_rows_rejected,
                lead_summary.duplicate_lead_rows_merged,
                lead_summary.field_warnings,
                event_summary.files_processed,
                event_summary.events_total,
                event_summary.malformed_events,
                event_summary.duplicate_events_dropped,
                event_summary.orphan_events,
                event_summary.unknown_disposition_events,
            )
        except Exception as exc:
            logger.error("Ingestion failed for drop %s: %s", drop_path.name, exc)
            try:
                with db_mgr.transaction() as conn:
                    conn.execute(
                        "UPDATE ingestion_runs SET status = 'FAILED' WHERE drop_id = ?;",
                        (drop_path.name,),
                    )
            except Exception:
                pass
            return 1

    return 0


def handle_report(args: argparse.Namespace, cfg: Config) -> int:
    """Generate the 5 required reporting files."""
    logger = setup_logging(cfg.log_level)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting report generation to directory: %s", out_dir)
    db_mgr = DatabaseManager(cfg.database_path)
    generator = ReportGenerator(db_mgr)
    results = generator.generate_reports(out_dir)

    logger.info("Successfully wrote reports: %s", ", ".join(results.keys()))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    db_path = getattr(args, "database_path", None)
    try:
        cfg = Config.load(database_path=db_path)
    except Exception as exc:
        sys.stderr.write(f"Configuration error: {exc}\n")
        return 1

    if args.subcommand == "init-db":
        return handle_init_db(args, cfg)
    elif args.subcommand == "ingest":
        return handle_ingest(args, cfg)
    elif args.subcommand == "report":
        return handle_report(args, cfg)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
