# Submission

## Candidate
- **Name:** Sonu Kumar
- **Assignment chosen:** A (Data)
- **Time spent (honest estimate):** 6h

## How to run
From a clean clone:
```bash
# 1. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .\.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Setup environment configuration
cp .env.example .env       # On Windows: copy .env.example .env

# 4. Generate data
python assignment-a-data/tools/generate_data.py --seed 42 --scale small --out data

# 5. Ingest drops sequentially
python -m solution ingest data/drop_1
python -m solution ingest data/drop_2

# 6. Generate reports
python -m solution report --out reports/

# 7. Run test suite
pytest -v
```

## Design

### Architecture Overview
The pipeline is designed with clean modular boundaries separating configuration, cryptography, schema parsing, lead ingestion, append-only event recording, orphan reconciliation, and report generation:

- **PII Protection & Cryptography (`solution/crypto/pii.py`):**
  Uses HKDF (RFC 5869) to derive two isolated 256-bit subkeys from a master secret (`PII_SECRET_KEY`):
  1. An HMAC-SHA256 key for computing deterministic blind indexes (`phone_blind_index`). This allows fast $O(\log N)$ indexed B-tree phone matching between incoming leads and call events without decrypting or storing plaintext numbers.
  2. An AES-256-GCM key for authenticated encryption of recoverable fields (`phone_encrypted`, `customer_name_encrypted`) with a fresh 96-bit random nonce per record.
  Masked phone numbers (`+91******XXXX`) are precomputed for display. No plaintext PII is ever written to logs, tables, rejections, or reports.

- **Storage Engine & Ledger (`solution/db/schema.py`):**
  Relational SQLite with WAL mode (`PRAGMA journal_mode = WAL`) and foreign key constraints enabled.
  - `leads`: Stores lead identity, blind index, encrypted PII, masked phone, permanent `batch_id`, and non-PII attributes in JSON.
  - `interaction_ledger`: An append-only immutable ledger. Overrides append new records; original events are never modified or deleted.
  - `lead_rejections`: Records row-level rejections without PII.
  - `ingested_files`: Tracks file SHA-256 hashes to guarantee exact idempotency.
  - `quality_metrics`: Key-value quality metric accumulators.

- **Two-Stage Orphan Reconciliation (`solution/ingestion/reconciler.py`):**
  Events arriving before their matching leads are quarantined (`is_orphan = 1`). Whenever a new drop of leads is ingested, the reconciler resolves orphaned events via `(workflow_id, phone_blind_index)`. In addition, human supervisor overrides (`disposition.override`), which lack phone numbers, are linked to their call sibling's lead via `call_id`.

- **Reporting Engine (`solution/reporting/`):**
  Extracts counted calls (calls with `call.initiated`) and resolves effective dispositions (latest override by `occurred_at`, otherwise latest `disposition.set`). Implements a strict 4-tier lead bucket state machine (`yet_to_reach_out` $\rightarrow$ `completed` $\rightarrow$ `in_progress_telephony_failed` $\rightarrow$ `in_progress_dialed`). Generates all 5 specified CSV/JSON reports adhering to exact column ordering, formatting (e.g. 4 decimal places for connectivity rates), and sorting contracts.

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

## Decisions & assumptions

| Decision | Why | Alternative considered |
|---|---|---|
| **HMAC-SHA256 Blind Indexing** | Allows deterministic exact-match phone joins between leads and events without storing or exposing plaintext phone numbers. Standard unsalted SHA256 is vulnerable to rainbow table attacks on a 10-digit phone space ($10^9$ possibilities). | Storing plaintext phones in database (violates PII rules) or decrypting all leads into memory for in-memory joins ($O(N \times M)$ overhead). |
| **Two-Phase Orphan Resolution** | Phone-based events reconcile by phone blind index; override events (which have only `call_id`) reconcile by finding their call sibling's `lead_id`. | Single pass resolution (would fail to link overrides when their call's initial events arrived prior to the lead). |
| **In-Memory Duplicate Tracking During Ingestion** | In-file duplicate events within the same uncommitted batch must be counted in `duplicate_events_dropped` rather than silently rejected by DB constraints. | Relying solely on `INSERT OR IGNORE` (fails to increment `duplicate_events_dropped` counter for intra-file duplicates). |
| **Day-First Calendar Date Parsing** | Indian business context mandates day-first date interpretation (e.g. `02/03/2026` is 2nd March, not 3rd February). | `dateutil.parser` with default US month-first format (would misclassify ambiguous dates). |
| **Transactions per Drop with File-Hash Checkpoints** | Ensures atomicity while allowing safe restarts if interrupted; already ingested files are skipped by SHA-256 hash check. | Single massive transaction for all drops (fails incremental ingestion requirement) or autocommit per row (slow and non-atomic). |

## Failure modes considered

### Handled:
- **Crashes during ingestion:** Ingestion occurs within transactional boundaries (`DatabaseManager.transaction()`). If a process terminates midway, the uncommitted transaction rolls back cleanly; `ingestion_runs` retains failure status. On retry, `ingested_files` ensures previously committed files are skipped.
- **Malformed and missing data:** Malformed JSON lines and missing `event_id` rows are counted in `malformed_events` and skipped without aborting the pipeline.
- **Out-of-order events:** Events arriving before leads are flagged `is_orphan = 1`. When the matching lead arrives, `reconcile_orphans()` retroactively resolves them.
- **Unknown dispositions:** Dispositions not present in `dispositions.csv` are counted in `unknown_disposition_events` and excluded from effective disposition resolution.
- **Corrupted ciphertext:** Any tampered or truncated ciphertext raises `DecryptionError` via AES-GCM tag verification.

### Not handled:
- **Distributed multi-writer SQLite concurrency:** SQLite supports single-writer concurrency. Running multiple parallel ingestion worker processes simultaneously against a single SQLite file across network mounts (e.g., NFS) is not supported without moving to PostgreSQL.
- **Dynamic key rotation without data backfill:** If `PII_SECRET_KEY` is changed, old blind indexes and ciphertexts must be migrated via an offline re-keying migration script.
- **Streaming event ingestion:** The current architecture is optimized for micro-batch file drops (`data/drop_N`). Direct webhook ingestion requires an event bus adapter (e.g., Kafka / HTTP ingest endpoint).

## Testing

### Testing Performed:
- **Unit Tests:**
  - Phone normalisation (valid formats, invalid prefixes, character stripping).
  - Date parsing (valid day-first formats, leap years, impossible dates like 31/02).
  - Currency normalisation (prefixes `₹`, `Rs`, `Rs.`, `INR`, comma separators, rounding).
  - Enum normalization (case-insensitivity, default fallback).
  - PII encryption, decryption round-trip, tamper resistance, and blind index determinism.
  - Bucket precedence rules (state machine short-circuit evaluation).
  - Effective disposition override precedence.
- **Integration Tests:**
  - Sequential ingestion (`drop_1` followed by `drop_2`) vs. all-in-one ingestion (`data` parent directory) asserting 100% byte-for-byte report parity.
  - Drop re-ingestion idempotency (zero data mutations, unchanged metrics).
  - Rollback and recovery from partially processed or corrupted drops.
  - In-file duplicate event tracking and deduplication.
  - Automated PII scanning of database tables, columns, and report artifacts.
  - Multi-seed validation (`--seed 42` and `--seed 999`).
  - Large dataset execution (`--scale large` with 140k leads and 632k events).

### Testing Not Performed:
- Execution on Python 3.11 runtime (the pipeline was developed and tested on Python 3.14.2 on Windows; syntax is intended for Python 3.11+ but Python 3.11 was not tested locally).
- Distributed multi-node concurrency testing (due to SQLite single-node deployment).
- Live telephony carrier API network simulation.

## Results
- **Small Dataset (`--scale small`):**
  - Drop 1 Ingestion: ~1.1s (1,515 leads, 4,247 events)
  - Drop 2 Ingestion: ~0.9s (542 leads, 4,498 events, 910 orphans resolved)
  - Report Generation: ~0.3s (all 5 reports)
  - Full Pipeline: ~2.3s
- **Large Dataset Benchmark (`--scale large` — 143,990 leads, 632,602 events):**
  - Drop 1 Ingestion: 150.54s (4 lead files, 106,748 leads, 62 event files, 308,063 events)
  - Drop 2 Ingestion: 338.04s (2 lead files, 37,242 leads, 65 event files, 324,539 events, 70,739 orphans resolved)
  - Total Ingestion: 488.58s (~8.1 minutes)
  - Report Generation: 32.76s (all 5 reports)
  - Total Pipeline Duration: 521.35s (~8.7 minutes)
- **Observations in Data:**
  - Over 20% of Drop 1 events arrive before their leads and are safely quarantined until Drop 2 arrives, where 902 phone-linked events and 8 call overrides are reconciled in the small scale dataset (70,739 reconciled in large scale).
  - Duplicate events appear both across drops and repeated within the same JSONL file.

## If I had another day
1. **PostgreSQL / DuckDB Adapter:** Abstract database connections behind an interface to support high-throughput analytical engines for 1M+ events/day.
2. **Streaming Event Pipeline:** Integrate with Apache Kafka / Redpanda to process call events in real-time rather than micro-batches.
3. **Automated Key Rotation:** Implement versioned HMAC blind indexes and envelope encryption with AWS KMS or HashiCorp Vault.
