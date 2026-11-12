# Agentic Universe: Interaction Ledger & Reporting Pipeline (Assignment A)

Production-ready backend data ingestion and reporting pipeline built for high-throughput voice campaigns, strictly compliant with Assignment A specifications.

---

## 1. Clean-Clone Setup Instructions

### Prerequisites
- Python: Tested on Python 3.14.2 (developed with syntax intended for Python 3.11+, but Python 3.11 runtime compatibility has not been verified in this environment)
- SQLite3 (included with Python standard library)

### Step 1: Create Virtual Environment
```bash
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate

# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# On Windows (cmd.exe):
.\.venv\Scripts\activate.bat
```

### Step 2: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 3: Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
# On Linux/macOS:
cp .env.example .env

# On Windows:
copy .env.example .env
```
Key configuration parameters in `.env`:
- `PII_SECRET_KEY`: 32-byte (64 hex characters) cryptographic key used for HMAC blind indexing and AES-256-GCM encryption.
- `DATABASE_PATH`: Path to SQLite database file (defaults to `au_ledger.db`).
- `LOG_LEVEL`: Logging verbosity (`INFO`, `DEBUG`, `WARNING`, `ERROR`).
- `STRICT_SECURITY`: If `true`, requires an explicit `PII_SECRET_KEY` and rejects default dev keys.

---

## 2. Running the Pipeline

### Data Generation
Generate test drops using the provided synthetic generator:
```bash
# Standard test dataset:
python assignment-a-data/tools/generate_data.py --seed 42 --scale small --out data

# Large dataset benchmark (~140k leads, ~600k events):
python assignment-a-data/tools/generate_data.py --seed 42 --scale large --out data_large
```

### Ingestion Workflow
The pipeline supports sequential single-drop ingestion, re-ingestion, and multi-drop batch ingestion:
```bash
# Ingest Drop 1
python -m solution ingest data/drop_1

# Ingest Drop 2 (automatically reconciles previously orphaned events)
python -m solution ingest data/drop_2

# Re-running an already ingested drop is safe and idempotent (skips identical files):
python -m solution ingest data/drop_1

# Alternatively, ingest all drops in a directory at once:
python -m solution ingest data
```

### Report Generation
Generate the 5 required audit reports into the target directory:
```bash
python -m solution report --out reports/
```

Generated reports:
1. `reports/batch_summary.csv`
2. `reports/daily_overview.csv`
3. `reports/lead_report.csv`
4. `reports/rejections.csv`
5. `reports/data_quality.json`

---

## 3. Architecture & Data Model

```
                    ┌───────────────────────────┐
                    │ Raw Inputs (CSVs, JSONLs) │
                    └─────────────┬─────────────┘
                                  │
                   ┌──────────────┴──────────────┐
                   │                             │
                   ▼                             ▼
        ┌─────────────────────┐       ┌─────────────────────┐
        │    Lead Ingestor    │       │   Event Ingestor    │
        │ - Header map/alias  │       │ - Append-only ledger│
        │ - PII AES-256-GCM   │       │ - In-file & cross   │
        │ - Phone blind-index │       │   drop deduplication│
        │ - Merge duplicates  │       │ - IST normalization │
        └──────────┬──────────┘       └──────────┬──────────┘
                   │                             │
                   ▼                             ▼
        ┌───────────────────────────────────────────────────┐
        │            SQLite Interaction Ledger              │
        │  - leads (blind index, masked, AES encrypted)     │
        │  - interaction_ledger (immutable audit events)    │
        │  - lead_rejections (zero PII)                     │
        │  - ingested_files (SHA-256 idempotency index)     │
        └─────────────────────────┬─────────────────────────┘
                                  │
                                  ▼
        ┌───────────────────────────────────────────────────┐
        │            Orphan Reconciler                      │
        │  - Phone blind index linking                      │
        │  - Call-id disposition override linking           │
        └─────────────────────────┬─────────────────────────┘
                                  │
                                  ▼
        ┌───────────────────────────────────────────────────┐
        │            Reporting Engine                       │
        │  - Mutually exclusive lead bucket state machine   │
        │  - Effective disposition resolution               │
        │  - 4-decimal daily connectivity rates             │
        │  - Strict CSV/JSON contract formatting            │
        └───────────────────────────────────────────────────┘
```

### PII Protection Strategy
- **Recoverable Fields:** `phone` and `customer_name` are encrypted at rest with AES-256-GCM using 96-bit random nonces.
- **Deterministic Blind Index:** Phone numbers are hashed using HMAC-SHA256 with a domain-separated derived key (`au-hmac-blind-index-v1`). This permits exact-match lookups between leads and events without ever storing plaintext phone numbers.
- **Display Masking:** Masked canonically as `+91******XXXX` in reports and database views.
- **Zero PII Leakage:** `rejections.csv`, application logs, and database diagnostic tables contain zero PII.

---

## 4. Running Tests

Run the complete test suite with one command:
```bash
pytest -v
```

Automated test coverage includes:
- Phone, date, currency, enum, and header normalization
- Cryptographic round-trip, tamper resistance, and blind indexing
- Append-only ledger immutability and override precedence
- Out-of-order and cross-drop orphan reconciliation
- Mutually exclusive lead bucket state machine
- Full CLI sequential vs. all-in-one report parity
- Automated PII scanning of database tables and report artifacts
