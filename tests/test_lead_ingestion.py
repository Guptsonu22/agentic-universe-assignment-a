"""Comprehensive test suite for lead CSV ingestion, normalization, rejection, and merging."""
from __future__ import annotations

import csv
import json
import secrets
from pathlib import Path

import pytest

from solution.config import Config
from solution.crypto.pii import PIIEngine
from solution.db.connection import DatabaseManager
from solution.db.schema import init_db
from solution.domain.schemas import load_workflow_schemas, normalize_header
from solution.ingestion.lead_ingestor import IngestionSummary, LeadIngestor
from solution.ingestion.normalizers import (
    normalize_date,
    normalize_decimal,
    normalize_enum,
    normalize_phone,
    normalize_string,
)


@pytest.fixture
def secret_key() -> bytes:
    """Generate a clean 32-byte secret key."""
    return secrets.token_bytes(32)


@pytest.fixture
def pii_engine(secret_key: bytes) -> PIIEngine:
    return PIIEngine(secret_key)


@pytest.fixture
def ingestor(tmp_path: Path, pii_engine: PIIEngine) -> LeadIngestor:
    db_file = tmp_path / "test_leads.db"
    db_mgr = DatabaseManager(db_file)
    with db_mgr.connection() as conn:
        init_db(conn, schemas_dir=Path("assignment-a-data/schemas"))
    return LeadIngestor(
        db_manager=db_mgr,
        pii_engine=pii_engine,
        schemas_dir=Path("assignment-a-data/schemas"),
    )


# ============================================================================
# 1. PHONE NORMALIZATION TESTS
# ============================================================================


def test_phone_valid_formats() -> None:
    """Verify phone normalization for all documented and newly introduced formats."""
    phones = [
        "9876543210",
        "+919876543210",
        "+91-98765-43210",
        "+91 98765 43210",
        "919876543210",
        "00919876543210",
        "(91) 9876543210",
        "(+91) 9876543210",
        "09876543210",
        "91-98765-43210",
    ]
    for p in phones:
        is_valid, canon = normalize_phone(p)
        assert is_valid is True, f"Failed for phone format: {p}"
        assert canon == "+919876543210"

    # Prefixes starting with 6, 7, 8, 9
    for first_digit in ["6", "7", "8", "9"]:
        p = f"{first_digit}123456789"
        is_valid, canon = normalize_phone(p)
        assert is_valid is True
        assert canon == f"+91{p}"


def test_phone_invalid_formats() -> None:
    """Verify rejection of invalid lengths, unsupported country codes, bad prefixes, non-numeric inputs, malformed formatting, repeated pluses, and unbalanced parentheses."""
    invalid_phones = [
        # Explicit rejected cases from security review
        "+441234567890",        # Non-Indian country code (+44 UK)
        "+14155550134",         # Non-Indian country code (+1 US)
        "+1 415 555 0134",      # Non-Indian country code formatted (+1 US)
        "1234567890",           # Starts with 1 (not in 6, 7, 8, 9)
        "987654321",            # 9 digits (too short)
        "98765432100",          # 11 digits without valid prefix
        "00911234567890",       # 0091 followed by invalid number starting with 1
        "++919876543210",       # Repeated plus signs
        "+91++9876543210",      # Repeated plus signs
        "91+9876543210",        # Misplaced plus sign
        "+91-98765-(43210",     # Unbalanced parenthesis (missing closing)
        "(91 9876543210",       # Unbalanced parenthesis (missing closing)
        "",                     # Empty string
        None,                   # None input
        "98765ABCDE",           # Alphabetic input
        "987654321a",           # Trailing alphabetic character
        "N/A",                  # Non-numeric text
        "unknown",              # Non-numeric text
        # Additional edge cases
        "0091",                 # Prefix only
        "5987654321",           # Bad prefix (starts with 5)
        "022-2345-6789",        # Landline
        ")91( 9876543210",      # Reversed parentheses
        "+91--98765-43210",     # Consecutive hyphens
        "(+91)) 9876543210",    # Unbalanced closing parenthesis
    ]
    for p in invalid_phones:
        is_valid, canon = normalize_phone(p)
        assert is_valid is False, f"Expected invalid for phone: {p}"
        assert canon is None


# ============================================================================
# 2. DATE NORMALIZATION TESTS (DAY-FIRST)
# ============================================================================


def test_date_valid_formats_day_first() -> None:
    """Verify day-first parsing across all 4 documented date formats."""
    # 1. YYYY-MM-DD
    assert normalize_date("2026-10-31") == (True, "2026-10-31")

    # 2. DD/MM/YYYY (Day-first: 05/10/2026 is 5th October)
    assert normalize_date("05/10/2026") == (True, "2026-10-05")

    # 3. DD-MM-YYYY
    assert normalize_date("21-11-2026") == (True, "2026-11-21")

    # 4. DD-Mon-YYYY (case-insensitive month)
    assert normalize_date("01-Dec-2026") == (True, "2026-12-01")
    assert normalize_date("15-oct-2026") == (True, "2026-10-15")
    assert normalize_date("04-SEP-2026") == (True, "2026-09-04")


def test_date_invalid_and_impossible() -> None:
    """Verify rejection of impossible calendar dates and malformed strings."""
    invalid_dates = [
        "31/02/2026",    # Impossible February day
        "2026-13-01",    # Month 13
        "32-10-2026",    # Day 32
        "soon",          # Unstructured string
        "TBD",
        "N/A",
        "2026/10/15",    # Slash with year first
        "",
        None,
    ]
    for d in invalid_dates:
        is_valid, norm = normalize_date(d)
        assert is_valid is False, f"Expected invalid for date: {d}"
        assert norm is None


# ============================================================================
# 3. DECIMAL / CURRENCY NORMALIZATION TESTS
# ============================================================================


def test_decimal_currency_formats() -> None:
    """Verify stripping of prefixes (₹, Rs, Rs., INR), commas, and 2-decimal rounding."""
    cases = [
        ("₹27,554", 27554.0),
        ("₹ 38,000", 38000.0),
        ("Rs. 31629", 31629.0),
        ("Rs. 31629.50", 31629.50),
        ("Rs 4000", 4000.0),
        ("INR 25301.4", 25301.4),
        ("INR 12,345.678", 12345.68),
        ("4985.75", 4985.75),
        ("11349", 11349.0),
        ("0", 0.0),
    ]
    for raw, expected in cases:
        is_valid, val = normalize_decimal(raw)
        assert is_valid is True, f"Failed for decimal: {raw}"
        assert val == expected


def test_decimal_invalid() -> None:
    """Verify rejection of negative numbers and non-numeric strings."""
    invalid = [
        "-100",
        "₹-500",
        "N/A",
        "-",
        "twelve thousand",
        "",
        None,
    ]
    for raw in invalid:
        is_valid, val = normalize_decimal(raw)
        assert is_valid is False, f"Expected invalid decimal for: {raw}"
        assert val is None


# ============================================================================
# 4. ENUM & HEADER NORMALIZATION TESTS
# ============================================================================


def test_enum_case_insensitivity() -> None:
    """Verify enum matching is case-insensitive and stores lowercase."""
    allowed = ["en", "hi", "ta", "kn", "te", "mr"]
    assert normalize_enum("EN", allowed) == (True, "en")
    assert normalize_enum(" HI ", allowed) == (True, "hi")
    assert normalize_enum("Ta", allowed) == (True, "ta")

    # Invalid values
    assert normalize_enum("Hindi", allowed) == (False, None)
    assert normalize_enum("english", allowed) == (False, None)
    assert normalize_enum("fr", allowed) == (False, None)


def test_header_normalization_and_alias_mapping() -> None:
    """Verify header normalization rules and alias matching."""
    schemas = load_workflow_schemas(Path("assignment-a-data/schemas"))
    mr_schema = schemas["motor_renewal"]

    raw_headers = [
        "Language",
        "Insured Name",
        "Policy No",
        "Mobile No",
        "Expiry Date",
        "Premium",
        "agent_notes",  # unknown column
    ]
    mapped = mr_schema.map_headers(raw_headers)

    assert "Insured Name" in mapped
    assert mapped["Insured Name"].name == "customer_name"

    assert "Mobile No" in mapped
    assert mapped["Mobile No"].name == "phone"

    assert "Policy No" in mapped
    assert mapped["Policy No"].name == "policy_number"

    assert "Expiry Date" in mapped
    assert mapped["Expiry Date"].name == "policy_expiry"

    assert "Premium" in mapped
    assert mapped["Premium"].name == "premium_amount"

    assert "Language" in mapped
    assert mapped["Language"].name == "preferred_language"

    assert "agent_notes" not in mapped, "Unknown column must be ignored"


# ============================================================================
# 5. LEAD INGESTION PIPELINE INTEGRATION TESTS
# ============================================================================


def write_test_csv(path: Path, rows: list[list[str]], header: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for r in rows:
            writer.writerow(r)


def test_blank_rows_skipped_and_not_counted(ingestor: LeadIngestor, tmp_path: Path) -> None:
    """Verify that blank rows are skipped and not counted in row numbers or total rows."""
    drop_dir = tmp_path / "drop_1"
    csv_file = drop_dir / "leads" / "motor_renewal" / "batch_001.csv"

    header = ["customer_name", "phone", "policy_number"]
    rows = [
        ["Aarav Sharma", "+919876543210", "POL-001"],
        ["", "", ""],            # Blank row (empty)
        ["   ", "  ", " "],      # Blank row (whitespace)
        ["Priya Nair", "+919876543211", "POL-002"],
    ]
    write_test_csv(csv_file, rows, header)

    summary = ingestor.ingest_drop(drop_dir)

    assert summary.lead_rows_total == 2, "Only non-blank data rows must be counted"
    assert summary.lead_rows_rejected == 0

    with ingestor.db_mgr.connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM leads;").fetchone()[0]
        assert count == 2


def test_rejection_order_and_zero_pii_in_rejections(ingestor: LeadIngestor, tmp_path: Path) -> None:
    """Verify rejections happen in strict schema order and contain no PII."""
    drop_dir = tmp_path / "drop_1"
    csv_file = drop_dir / "leads" / "motor_renewal" / "batch_001.csv"

    header = ["customer_name", "phone", "policy_number", "premium_amount"]
    rows = [
        # Row 1: Valid
        ["Aarav Sharma", "9876543210", "POL-001", "1000"],
        # Row 2: Missing customer_name (first in schema order)
        ["", "9876543211", "POL-002", "2000"],
        # Row 3: Missing phone
        ["Sneha Patel", "", "POL-003", "3000"],
        # Row 4: Invalid phone (9 digits)
        ["Karthik Rao", "987654321", "POL-004", "4000"],
        # Row 5: Missing policy_number (reference field)
        ["Pooja Gupta", "9876543212", "", "5000"],
        # Row 6: Missing both name and policy -> schema order means missing name rejected first
        ["", "9876543213", "", "6000"],
    ]
    write_test_csv(csv_file, rows, header)

    summary = ingestor.ingest_drop(drop_dir)

    assert summary.lead_rows_total == 6
    assert summary.lead_rows_rejected == 5

    assert summary.rejections_by_reason == {
        "missing_required:customer_name": 2,
        "missing_required:phone": 1,
        "invalid_phone": 1,
        "missing_required:policy_number": 1,
    }

    # Inspect rejections table
    with ingestor.db_mgr.connection() as conn:
        rejections = conn.execute(
            "SELECT row_number, reason FROM lead_rejections ORDER BY row_number;"
        ).fetchall()
        rejections_dict = {r["row_number"]: r["reason"] for r in rejections}

        assert rejections_dict[2] == "missing_required:customer_name"
        assert rejections_dict[3] == "missing_required:phone"
        assert rejections_dict[4] == "invalid_phone"
        assert rejections_dict[5] == "missing_required:policy_number"
        assert rejections_dict[6] == "missing_required:customer_name"


def test_optional_invalid_fields_warn_not_reject(ingestor: LeadIngestor, tmp_path: Path) -> None:
    """Verify invalid optional fields become null and count warnings on accepted rows only."""
    drop_dir = tmp_path / "drop_1"
    csv_file = drop_dir / "leads" / "motor_renewal" / "batch_001.csv"

    header = ["customer_name", "phone", "policy_number", "policy_expiry", "premium_amount", "preferred_language"]
    rows = [
        # Row 1: Valid row with invalid optional fields: date 'soon', amount '-', language 'Hindi'
        ["Aarav Sharma", "9876543210", "POL-001", "soon", "-", "Hindi"],
        # Row 2: Rejected row (invalid phone) with invalid date '31/02/2026' -> warnings MUST NOT count!
        ["Priya Iyer", "5555555555", "POL-002", "31/02/2026", "5000", "en"],
    ]
    write_test_csv(csv_file, rows, header)

    summary = ingestor.ingest_drop(drop_dir)

    assert summary.lead_rows_total == 2
    assert summary.lead_rows_rejected == 1
    # 3 warnings on Row 1; Row 2 was rejected so its invalid date must not count as a warning!
    assert summary.field_warnings == 3

    with ingestor.db_mgr.connection() as conn:
        lead = conn.execute("SELECT * FROM leads WHERE external_ref = 'POL-001';").fetchone()
        attrs = json.loads(lead["attributes_json"])
        assert "policy_expiry" not in attrs or attrs["policy_expiry"] is None
        assert "premium_amount" not in attrs or attrs["premium_amount"] is None
        # preferred_language default was 'en' after merging since it became null
        assert lead["preferred_language"] == "en"


def test_duplicate_lead_merging_and_permanent_batch_id(ingestor: LeadIngestor, tmp_path: Path) -> None:
    """Verify that duplicate leads update non-null fields, preserve batch_id, and increment merge count."""
    drop1_dir = tmp_path / "drop_1"
    csv1 = drop1_dir / "leads" / "motor_renewal" / "batch_001.csv"
    h1 = ["customer_name", "phone", "policy_number", "premium_amount", "preferred_language"]
    r1 = [["Rahul Bose", "9799840767", "POL-001", "35000", ""]]
    write_test_csv(csv1, r1, h1)

    s1 = ingestor.ingest_drop(drop1_dir)
    assert s1.lead_rows_total == 1
    assert s1.duplicate_lead_rows_merged == 0

    with ingestor.db_mgr.connection() as conn:
        lead1 = conn.execute("SELECT * FROM leads WHERE external_ref = 'POL-001';").fetchone()
        assert lead1["batch_id"] == "batch_001"
        assert lead1["preferred_language"] == "en"  # Default applied
        attrs1 = json.loads(lead1["attributes_json"])
        assert attrs1["premium_amount"] == 35000.0

    # Drop 2: Duplicate row with new premium and explicit language 'HI'
    drop2_dir = tmp_path / "drop_2"
    csv2 = drop2_dir / "leads" / "motor_renewal" / "batch_002.csv"
    h2 = ["Insured Name", "Mobile No", "Policy No", "Premium", "Language"]
    r2 = [["Rahul Bose", "+91 97998 40767", "POL-001", "34000.50", "HI"]]
    write_test_csv(csv2, r2, h2)

    s2 = ingestor.ingest_drop(drop2_dir)
    assert s2.lead_rows_total == 1
    assert s2.duplicate_lead_rows_merged == 1

    with ingestor.db_mgr.connection() as conn:
        leads = conn.execute("SELECT * FROM leads;").fetchall()
        assert len(leads) == 1, "Duplicate row must update existing lead, not create a second row"

        lead2 = leads[0]
        # Permanent batch_id must still be batch_001!
        assert lead2["batch_id"] == "batch_001"
        # preferred_language updated to 'hi'
        assert lead2["preferred_language"] == "hi"
        attrs2 = json.loads(lead2["attributes_json"])
        assert attrs2["premium_amount"] == 34000.50


def test_idempotent_reingestion(ingestor: LeadIngestor, tmp_path: Path) -> None:
    """Verify that re-ingesting the same drop does not re-process files or duplicate records."""
    drop_dir = tmp_path / "drop_1"
    csv_file = drop_dir / "leads" / "motor_renewal" / "batch_001.csv"
    h = ["customer_name", "phone", "policy_number"]
    r = [["Aarav Sharma", "9876543210", "POL-001"]]
    write_test_csv(csv_file, r, h)

    s1 = ingestor.ingest_drop(drop_dir)
    assert s1.files_processed == 1
    assert s1.lead_rows_total == 1

    # Re-ingest same drop
    s2 = ingestor.ingest_drop(drop_dir)
    assert s2.files_skipped == 1
    assert s2.lead_rows_total == 0

    with ingestor.db_mgr.connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM leads;").fetchone()[0]
        assert count == 1

