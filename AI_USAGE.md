# AI Usage Disclosure

AI tools are allowed. We want to know **how** you used them, because using them well is a
skill. Honest answers are never held against you. Discovering undisclosed use is.

## Tools used
- Google Antigravity

## What I used them for
- Discussing and analyzing the assignment requirements, data schemas, and contract rules.
- Scaffolding the initial project foundation, cryptographic helpers (AES-256-GCM + HMAC-SHA256 blind indexing), normalizer functions, and CLI subcommands.
- Generating unit test suites for phone normalization, day-first date variations, currency parsing, and bucket precedence rules.
- Writing integration tests comparing sequential vs. all-in-one drop ingestion parity and developing the automated PII scanner script (`tests/verify_pii.py`).

## What I wrote or decided myself
- Selected SQLite with Write-Ahead Logging (WAL mode) and strict foreign keys as the embedded storage engine.
- Decided on HMAC-SHA256 with domain-separated HKDF key derivation (rather than unsalted hashing) to prevent rainbow table attacks against the 10-digit phone number space while supporting exact matching.
- Designed the two-stage orphan reconciliation mechanism (matching phone blind indices for calls, and matching `call_id` for human supervisor disposition overrides).
- Established the SHA-256 file-hash tracking table (`ingested_files`) to guarantee exact idempotency on drop re-runs.
- Formulated the 4-tier mutually exclusive lead bucket state machine and effective disposition resolution rules.
- Evaluated the test results across small and large scale datasets, reviewed the code line-by-line, and audited all five report outputs against the specification.

## Where the AI was wrong or unhelpful
- **In-File Duplicate Event Detection:** During initial scaffolding of `EventIngestor`, duplicate event detection queried the database `interaction_ledger` table. When duplicate `event_id` records appeared within the *same* uncommitted JSONL file, they bypassed the DB check and were batched into memory. While SQLite's `UNIQUE` constraint prevented duplicate rows in the database, the `duplicate_events_dropped` metric in `data_quality.json` was not incremented. I caught this during audit and corrected it by adding an in-memory set (`seen_in_batch`) per file to properly count and skip intra-file duplicates.
- **Contract Key Mismatch in Test:** An earlier AI-generated integration test asserted that `connectivity_rate_overall` was present in `data_quality.json`. I reviewed the specification and corrected the assertion, as the assignment contract specifies that connectivity rates belong exclusively in `daily_overview.csv`.
- **Rejections Header Mismatch in Test:** An AI test draft asserted that the header in `rejections.csv` ended with `rejection_reason`. I cross-referenced `assignment-a-data/README.md` which explicitly defines the columns as `workflow_id,batch_id,row_number,reason` and corrected the test.

## How I verified AI-generated code
- **Automated Test Suite:** Ran 45 pytest tests covering unit and integration scenarios across all edge cases.
- **Automated PII Scanning:** Created and ran `tests/verify_pii.py` to scan all SQLite tables, columns, and output report files with regex pattern matching for phone numbers and names, confirming 0 PII leaks.
- **Fresh & Multi-Seed Runs:** Tested end-to-end execution on fresh databases with multiple seeds (`--seed 42` and `--seed 999`) to ensure no seed-specific hardcoding.
- **Byte Parity Diffing:** Compared reports generated from sequential ingestion (`drop_1` followed by `drop_2`) against all-in-one ingestion (`data`), confirming 100% byte-for-byte identical output.
- **Scale Testing:** Executed the large scale benchmark (`--scale large` with 140k+ leads and 632k+ events), measuring ingestion and report timings.
