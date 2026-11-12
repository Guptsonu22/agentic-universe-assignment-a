"""Reporting engine orchestrator: Generates all 5 required reports."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

from solution.db.connection import DatabaseManager
from solution.reporting.batch_summary import generate_batch_summary_csv
from solution.reporting.call_facts import extract_call_facts
from solution.reporting.daily_overview import generate_daily_overview_csv
from solution.reporting.data_quality import generate_data_quality_json
from solution.reporting.lead_report import generate_lead_report_csv
from solution.reporting.rejections_report import generate_rejections_csv

logger = logging.getLogger("agentic_universe.reporting")


class ReportGenerator:
    """Orchestrates generation of the 5 required pipeline reports."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_mgr = db_manager

    def generate_reports(self, out_dir: Path) -> Dict[str, Path]:
        """
        Generate all five report files into out_dir.
        
        Outputs:
        1. batch_summary.csv
        2. daily_overview.csv
        3. lead_report.csv
        4. rejections.csv
        5. data_quality.json
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        results: Dict[str, Path] = {}

        with self.db_mgr.connection() as conn:
            from solution.db.schema import init_db
            init_db(conn)
            logger.info("Extracting call facts and derived metrics from ledger...")
            all_calls = extract_call_facts(conn)

            logger.info("Generating batch_summary.csv...")
            results["batch_summary"] = generate_batch_summary_csv(conn, all_calls, out_dir)

            logger.info("Generating daily_overview.csv...")
            results["daily_overview"] = generate_daily_overview_csv(all_calls, out_dir)

            logger.info("Generating lead_report.csv...")
            results["lead_report"] = generate_lead_report_csv(conn, all_calls, out_dir)

            logger.info("Generating rejections.csv...")
            results["rejections"] = generate_rejections_csv(conn, out_dir)

            logger.info("Generating data_quality.json...")
            results["data_quality"] = generate_data_quality_json(conn, out_dir)

        logger.info("All 5 reports generated successfully in %s", out_dir)
        return results

