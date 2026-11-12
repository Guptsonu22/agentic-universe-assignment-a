"""Initial unit test suite for foundation, cryptographic PII protection, and database layer."""
from __future__ import annotations

import os
import secrets
import sqlite3
from pathlib import Path

import pytest

from solution.cli import main
from solution.config import Config, ConfigurationError
from solution.crypto.pii import (
    DecryptionError,
    PIIEngine,
    compute_blind_index,
    decrypt_pii,
    encrypt_pii,
    mask_phone,
)
from solution.db.connection import DatabaseManager
from solution.db.schema import init_db


@pytest.fixture
def test_key() -> bytes:
    """Generate a clean 32-byte cryptographic key for testing."""
    return secrets.token_bytes(32)


@pytest.fixture
def pii_engine(test_key: bytes) -> PIIEngine:
    """Instantiate PIIEngine with a test key."""
    return PIIEngine(test_key)


def test_database_initialization(tmp_path: Path) -> None:
    """Verify database schema creation, table constraints, and pragmas."""
    db_file = tmp_path / "test_init.db"
    db_mgr = DatabaseManager(db_file)

    schemas_dir = Path("assignment-a-data/schemas")

    with db_mgr.connection() as conn:
        init_db(conn, schemas_dir=schemas_dir)

        # 1. Verify PRAGMAs
        cursor = conn.execute("PRAGMA foreign_keys;")
        assert cursor.fetchone()[0] == 1, "Foreign keys must be enabled"

        cursor = conn.execute("PRAGMA journal_mode;")
        assert cursor.fetchone()[0].lower() == "wal", "WAL journal mode must be active"

        # 2. Verify all core tables exist
        tables_query = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        tables = [row[0] for row in conn.execute(tables_query).fetchall()]

        expected_tables = [
            "disposition_catalogue",
            "ingested_files",
            "ingestion_runs",
            "interaction_ledger",
            "lead_rejections",
            "leads",
            "quality_metrics",
            "workflows",
        ]
        for tbl in expected_tables:
            assert tbl in tables, f"Expected table '{tbl}' was not created."

        # 3. Verify workflow & disposition seeding
        if schemas_dir.is_dir():
            wf_count = conn.execute("SELECT COUNT(*) FROM workflows;").fetchone()[0]
            assert wf_count >= 2, "Default workflows must be seeded"

            disp_count = conn.execute("SELECT COUNT(*) FROM disposition_catalogue;").fetchone()[0]
            assert disp_count >= 14, "Dispositions catalogue must be seeded"


def test_encryption_decryption_round_trip(pii_engine: PIIEngine, test_key: bytes) -> None:
    """Verify AES-256-GCM encryption and decryption round trips and tamper detection."""
    test_values = [
        "Aarav Sharma",
        "+919876543210",
        "Priya Iyer-Menon",
        "Special chars: &<>'\" / @!#₹",
    ]

    for val in test_values:
        ciphertext = pii_engine.encrypt(val)
        assert ciphertext != val, "Ciphertext must not match plaintext"
        assert len(ciphertext) > 28, "Ciphertext must contain nonce and tag"

        decrypted = pii_engine.decrypt(ciphertext)
        assert decrypted == val, "Decrypted value must exactly match plaintext"

    # Test module-level convenience functions
    ct = encrypt_pii("+919988776655", test_key)
    assert decrypt_pii(ct, test_key) == "+919988776655"


def test_tampered_ciphertext_fails_decryption(pii_engine: PIIEngine) -> None:
    """Verify that tampering with any bit of AES-GCM ciphertext fails authentication."""
    ciphertext = pii_engine.encrypt("Secret Customer")

    # Flip characters in the base64 payload
    tampered = ciphertext[:-4] + "AAAA"

    with pytest.raises(DecryptionError):
        pii_engine.decrypt(tampered)


def test_blind_index_different_inputs(pii_engine: PIIEngine) -> None:
    """Verify that distinct phone numbers produce distinct blind indexes."""
    phone_a = "+919876543210"
    phone_b = "+919876543211"

    index_a = pii_engine.compute_blind_index(phone_a)
    index_b = pii_engine.compute_blind_index(phone_b)

    assert index_a != index_b
    assert len(index_a) == 64
    assert len(index_b) == 64


def test_blind_index_deterministic_with_same_key(test_key: bytes) -> None:
    """Verify that the same phone produces the exact same blind index across instances."""
    phone = "+917718750036"

    engine1 = PIIEngine(test_key)
    engine2 = PIIEngine(test_key)

    index1 = engine1.compute_blind_index(phone)
    index2 = engine2.compute_blind_index(phone)
    index3 = compute_blind_index(phone, test_key)

    assert index1 == index2 == index3
    assert len(index1) == 64

    # With a different key, the blind index MUST differ
    other_key = secrets.token_bytes(32)
    engine_other = PIIEngine(other_key)
    assert engine_other.compute_blind_index(phone) != index1


def test_missing_or_invalid_encryption_key_fails_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that missing, invalid, or low-entropy encryption keys fail fast."""
    # 1. Missing key under strict mode
    monkeypatch.delenv("PII_SECRET_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="PII_SECRET_KEY environment variable is missing"):
        Config.load(require_explicit_key=True)

    # 2. Non-hex key
    monkeypatch.setenv("PII_SECRET_KEY", "not-a-valid-hex-string")
    with pytest.raises(ConfigurationError, match="must be a valid hex string"):
        Config.load(require_explicit_key=True)

    # 3. Too short key (< 32 bytes = 64 hex chars)
    short_key_hex = secrets.token_hex(16)  # only 16 bytes
    monkeypatch.setenv("PII_SECRET_KEY", short_key_hex)
    with pytest.raises(ConfigurationError, match="at least 32 bytes"):
        Config.load(require_explicit_key=True)


def test_plaintext_pii_not_written_to_database(tmp_path: Path, pii_engine: PIIEngine) -> None:
    """Verify that plaintext customer name and phone numbers are never stored in the database."""
    db_file = tmp_path / "test_pii_safety.db"
    db_mgr = DatabaseManager(db_file)

    plaintext_name = "Vikram Aditya Malhotra"
    plaintext_phone = "+919876543210"

    phone_blind_index = pii_engine.compute_blind_index(plaintext_phone)
    phone_encrypted = pii_engine.encrypt(plaintext_phone)
    customer_name_encrypted = pii_engine.encrypt(plaintext_name)
    masked = mask_phone(plaintext_phone)

    with db_mgr.connection() as conn:
        init_db(conn, schemas_dir=Path("assignment-a-data/schemas"))

        # Insert drop run
        conn.execute(
            "INSERT INTO ingestion_runs (drop_id, status) VALUES ('drop_1', 'COMPLETED');"
        )
        # Insert test lead
        conn.execute(
            """
            INSERT INTO leads (
                workflow_id, phone_blind_index, phone_masked, phone_encrypted,
                customer_name_encrypted, external_ref, batch_id, preferred_language, attributes_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                "motor_renewal",
                phone_blind_index,
                masked,
                phone_encrypted,
                customer_name_encrypted,
                "POL-999999",
                "batch_001",
                "en",
                '{"premium_amount": 12500.0}',
            ),
        )

        # 1. Query raw database row
        row = conn.execute("SELECT * FROM leads WHERE external_ref = 'POL-999999';").fetchone()
        row_dict = dict(row)

        # Ensure plaintext name and phone do not appear in any column
        for col_name, col_val in row_dict.items():
            str_val = str(col_val)
            assert plaintext_name not in str_val, f"Plaintext name leaked into column '{col_name}'!"
            assert "9876543210" not in str_val or col_name == "phone_masked", (
                f"Plaintext phone leaked into column '{col_name}'!"
            )

        # Check masked phone contains only last 4 digits
        assert row_dict["phone_masked"] == "+91******3210"

    # 2. Inspect raw bytes of the SQLite database file on disk
    with open(db_file, "rb") as f:
        raw_db_bytes = f.read()

    assert plaintext_name.encode("utf-8") not in raw_db_bytes, "Plaintext customer name found in raw SQLite disk file!"
    assert b"9876543210" not in raw_db_bytes, "Plaintext phone found in raw SQLite disk file!"


def test_phone_masking() -> None:
    """Verify phone masking matches the exact contract '+91******' followed by last 4 digits."""
    assert mask_phone("+919876543210") == "+91******3210"
    assert mask_phone("+917718750036") == "+91******0036"
    assert mask_phone("+916234509871") == "+91******9871"


def test_cli_init_db(tmp_path: Path) -> None:
    """Verify CLI init-db command creates the database successfully."""
    db_file = tmp_path / "cli_test.db"
    exit_code = main(["--db", str(db_file), "init-db"])
    assert exit_code == 0
    assert db_file.exists(), "CLI init-db must create the SQLite file."
