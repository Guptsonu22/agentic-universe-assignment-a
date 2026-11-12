"""Reporting package for Assignment A."""
from .batch_summary import generate_batch_summary_csv
from .bucket_evaluator import compute_lead_stats, evaluate_lead_bucket
from .call_facts import CallFact, extract_call_facts
from .daily_overview import generate_daily_overview_csv
from .data_quality import generate_data_quality_json
from .lead_report import generate_lead_report_csv
from .rejections_report import generate_rejections_csv
from .report_generator import ReportGenerator

__all__ = [
    "ReportGenerator",
    "CallFact",
    "extract_call_facts",
    "evaluate_lead_bucket",
    "compute_lead_stats",
    "generate_batch_summary_csv",
    "generate_daily_overview_csv",
    "generate_lead_report_csv",
    "generate_rejections_csv",
    "generate_data_quality_json",
]

