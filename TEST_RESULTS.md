# Automated Test Results: Agentic Universe Assignment A
**Candidate:** Sonu Kumar  
**Execution Environment:** Windows | Python 3.14.2 | pytest 9.2.0 | SQLite (WAL mode)  
*(Note: Python 3.11 was not tested in this local environment; execution logs reflect Python 3.14.2)*  
**Execution Date:** 2026-11-12  

---

## 1. Test Execution Summary

```powershell
pytest -v
```

```text
============================= test session starts =============================
platform win32 -- Python 3.14.2, pytest-9.2.0, pluggy-1.7.0 -- .venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\Sonu\OneDrive\Desktop\sde-assignment-junior-2026
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.16.0
collecting ... collected 45 items

tests/test_cli_workflow.py::test_cli_first_drop_ingestion PASSED         [  2%]
tests/test_cli_workflow.py::test_cli_second_drop_ingestion_and_orphan_reconciliation PASSED [  4%]
tests/test_cli_workflow.py::test_cli_reingesting_first_drop_is_idempotent PASSED [  6%]
tests/test_cli_workflow.py::test_cli_report_generation_after_both_drops PASSED [  8%]
tests/test_cli_workflow.py::test_sequential_vs_all_in_one_parity PASSED  [ 11%]
tests/test_cli_workflow.py::test_recovery_from_partially_processed_drop PASSED [ 13%]
tests/test_cli_workflow.py::test_duplicate_events_and_duplicate_leads_across_drops PASSED [ 15%]
tests/test_event_ingestion.py::test_timestamp_parsing_all_three_formats PASSED [ 17%]
tests/test_event_ingestion.py::test_malformed_json_and_missing_event_id PASSED [ 20%]
tests/test_event_ingestion.py::test_duplicate_events_across_drops PASSED [ 22%]
tests/test_event_ingestion.py::test_in_file_duplicate_events PASSED      [ 24%]
tests/test_event_ingestion.py::test_orphan_event_and_late_lead_reconciliation PASSED [ 26%]
tests/test_event_ingestion.py::test_disposition_override_linked_via_call_id PASSED [ 28%]
tests/test_event_ingestion.py::test_append_only_ledger_preserves_original_events PASSED [ 31%]
tests/test_event_ingestion.py::test_unknown_disposition_counted PASSED   [ 33%]
tests/test_event_ingestion.py::test_idempotent_event_reingestion PASSED  [ 35%]
tests/test_foundation.py::test_database_initialization PASSED            [ 37%]
tests/test_foundation.py::test_encryption_decryption_round_trip PASSED   [ 40%]
tests/test_foundation.py::test_tampered_ciphertext_fails_decryption PASSED [ 42%]
tests/test_foundation.py::test_blind_index_different_inputs PASSED       [ 44%]
tests/test_foundation.py::test_blind_index_deterministic_with_same_key PASSED [ 46%]
tests/test_foundation.py::test_missing_or_invalid_encryption_key_fails_safely PASSED [ 48%]
tests/test_foundation.py::test_plaintext_pii_not_written_to_database PASSED [ 51%]
tests/test_foundation.py::test_phone_masking PASSED                      [ 53%]
tests/test_foundation.py::test_cli_init_db PASSED                        [ 55%]
tests/test_lead_ingestion.py::test_phone_valid_formats PASSED            [ 57%]
tests/test_lead_ingestion.py::test_phone_invalid_formats PASSED          [ 60%]
tests/test_lead_ingestion.py::test_date_valid_formats_day_first PASSED   [ 62%]
tests/test_lead_ingestion.py::test_date_invalid_and_impossible PASSED    [ 64%]
tests/test_lead_ingestion.py::test_decimal_currency_formats PASSED       [ 66%]
tests/test_lead_ingestion.py::test_decimal_invalid PASSED                [ 68%]
tests/test_lead_ingestion.py::test_enum_case_insensitivity PASSED        [ 71%]
tests/test_lead_ingestion.py::test_header_normalization_and_alias_mapping PASSED [ 73%]
tests/test_lead_ingestion.py::test_blank_rows_skipped_and_not_counted PASSED [ 75%]
tests/test_lead_ingestion.py::test_rejection_order_and_zero_pii_in_rejections PASSED [ 77%]
tests/test_lead_ingestion.py::test_optional_invalid_fields_warn_not_reject PASSED [ 80%]
tests/test_lead_ingestion.py::test_duplicate_lead_merging_and_permanent_batch_id PASSED [ 82%]
tests/test_lead_ingestion.py::test_idempotent_reingestion PASSED         [ 84%]
tests/test_reporting.py::test_bucket_precedence_yet_to_reach_out PASSED  [ 86%]
tests/test_reporting.py::test_bucket_precedence_completed PASSED         [ 88%]
tests/test_reporting.py::test_bucket_precedence_in_progress_telephony_failed PASSED [ 91%]
tests/test_reporting.py::test_bucket_precedence_in_progress_dialed PASSED [ 93%]
tests/test_reporting.py::test_lead_stats_current_disposition_from_most_recent_call_that_has_one PASSED [ 95%]
tests/test_reporting.py::test_lead_stats_ever_success PASSED             [ 97%]
tests/test_reporting.py::test_all_five_reports_generation PASSED         [100%]

============================= 45 passed in 6.67s ==============================
```

---

## 2. Test Breakdown by Domain

### 1. CLI & Workflow Integration (`tests/test_cli_workflow.py` — 7 tests)
- `test_cli_first_drop_ingestion`: Verifies `drop_1` ingestion creates completed run status and ledger entries.
- `test_cli_second_drop_ingestion_and_orphan_reconciliation`: Verifies sequential `drop_2` ingestion and automatic resolution of previously quarantined orphans.
- `test_cli_reingesting_first_drop_is_idempotent`: Verifies re-ingesting `drop_1` changes 0 rows, adds 0 records, and leaves metrics identical.
- `test_cli_report_generation_after_both_drops`: Verifies existence, non-emptiness, sorting, and structure of all 5 report outputs.
- `test_sequential_vs_all_in_one_parity`: Verifies byte-for-byte equality between `drop_1 -> drop_2` sequential run vs `data/` all-in-one run.
- `test_recovery_from_partially_processed_drop`: Verifies clean transaction rollback and resumption after an interrupted or corrupted drop.
- `test_duplicate_events_and_duplicate_leads_across_drops`: Asserts uniqueness of leads and events across multi-drop lifecycles.

### 2. Event Ledger & Ingestion (`tests/test_event_ingestion.py` — 9 tests)
- `test_timestamp_parsing_all_three_formats`: Verifies UTC (`Z`), offset (`+05:30`), and naive ("naive means IST") parsing.
- `test_malformed_json_and_missing_event_id`: Verifies malformed JSON lines and missing `event_id` are counted and skipped.
- `test_duplicate_events_across_drops`: Verifies duplicate `event_id` records across drops are counted in `duplicate_events_dropped` and dropped.
- `test_in_file_duplicate_events`: Verifies duplicate `event_id` records within the *same* JSONL file are counted and dropped.
- `test_orphan_event_and_late_lead_reconciliation`: Verifies events arriving before leads are quarantined and resolved when the lead arrives.
- `test_disposition_override_linked_via_call_id`: Verifies supervisor overrides without phone numbers link to leads via `call_id`.
- `test_append_only_ledger_preserves_original_events`: Verifies overrides append new rows and never modify original records.
- `test_unknown_disposition_counted`: Verifies uncatalogued dispositions are counted in `unknown_disposition_events`.
- `test_idempotent_event_reingestion`: Verifies duplicate event file ingestion is skipped via SHA-256 hash.

### 3. Foundation & Cryptography (`tests/test_foundation.py` — 9 tests)
- `test_database_initialization`: Verifies schema creation, foreign keys, and WAL mode.
- `test_encryption_decryption_round_trip`: Verifies AES-256-GCM encryption/decryption fidelity.
- `test_tampered_ciphertext_fails_decryption`: Verifies authentication tag rejection on modified ciphertext.
- `test_blind_index_different_inputs`: Verifies different phones yield distinct blind indexes.
- `test_blind_index_deterministic_with_same_key`: Verifies deterministic matching for identical phone numbers.
- `test_missing_or_invalid_encryption_key_fails_safely`: Verifies safe failure in strict mode when secret key is absent.
- `test_plaintext_pii_not_written_to_database`: Asserts no plaintext customer names or phones exist in `leads`.
- `test_phone_masking`: Verifies canonical display masking as `+91******XXXX`.
- `test_cli_init_db`: Verifies CLI command `python -m solution init-db`.

### 4. Lead Ingestion & Normalization (`tests/test_lead_ingestion.py` — 13 tests)
- `test_phone_valid_formats`: Tests all 10 standard and extended phone formats (`9876543210`, `+919876543210`, `+91-98765-43210`, `+91 98765 43210`, `919876543210`, `00919876543210`, `(91) 9876543210`, `09876543210`, `91-98765-43210`, `(+91) 9876543210`).
- `test_phone_invalid_formats`: Tests 24 invalid, incomplete, international, malformed formatting, repeated plus, misplaced plus, and unbalanced parenthesis formats (`+441234567890`, `+14155550134`, `+1 415 555 0134`, `1234567890`, `987654321`, `98765432100`, `00911234567890`, `++919876543210`, `+91++9876543210`, `91+9876543210`, `+91-98765-(43210`, `(91 9876543210`, `""`, `None`, `98765ABCDE`, `987654321a`, `N/A`, `unknown`, `0091`, `5987654321`, `022-2345-6789`, `)91( 9876543210`, `+91--98765-43210`, `(+91)) 9876543210`).
- `test_date_valid_formats_day_first`: Tests day-first date variations (`YYYY-MM-DD`, `DD/MM/YYYY`, `DD-MM-YYYY`, `DD-Mon-YYYY`).
- `test_date_invalid_and_impossible`: Tests rejection of impossible calendar dates (e.g. `31/02/2026`).
- `test_decimal_currency_formats`: Tests currency prefixes (`₹`, `Rs`, `Rs.`, `INR`), comma stripping, rounding to 2 decimals.
- `test_decimal_invalid`: Tests negative numbers and malformed decimal strings.
- `test_enum_case_insensitivity`: Tests case-insensitive matching against schema `values`.
- `test_header_normalization_and_alias_mapping`: Tests lowercase, trim, regex underscore collapse, and alias mapping.
- `test_blank_rows_skipped_and_not_counted`: Tests skipping empty/whitespace lines without incrementing data row count.
- `test_rejection_order_and_zero_pii_in_rejections`: Tests schema-order rejection and verifies zero PII in `rejections.csv`.
- `test_optional_invalid_fields_warn_not_reject`: Tests storing `NULL` and counting warnings for optional invalid fields on accepted rows.
- `test_duplicate_lead_merging_and_permanent_batch_id`: Tests non-null merging, permanent `batch_id`, and post-merge defaults.
- `test_idempotent_reingestion`: Tests skipping already processed lead CSVs.

### 5. Reporting Engine (`tests/test_reporting.py` — 7 tests)
- `test_bucket_precedence_yet_to_reach_out`: Verifies bucket 1 (0 counted calls).
- `test_bucket_precedence_completed`: Verifies bucket 2 (terminal effective disposition).
- `test_bucket_precedence_in_progress_telephony_failed`: Verifies bucket 3 (all calls failed at telephony).
- `test_bucket_precedence_in_progress_dialed`: Verifies bucket 4 (fallback).
- `test_lead_stats_current_disposition_from_most_recent_call_that_has_one`: Verifies current disposition from most recent call.
- `test_lead_stats_ever_success`: Verifies `ever_success` across multiple calls.
- `test_all_five_reports_generation`: Verifies end-to-end report generation contract.

---

## 3. Automated PII Scan Results

*Note: These findings reflect the output of the automated scanner script (`tests/verify_pii.py`) using pattern matching (Indian phone regex and generator name dictionary) against the tested SQLite database (`au_ledger.db`) and generated output report files (`reports/`).*

```powershell
python tests/verify_pii.py --db au_ledger.db --reports reports
```
```text
=== PII AUDIT SUMMARY (au_ledger.db, reports) ===
Database violations: 0
Report files violations: 0
Total PII violations: 0
PASS: Zero PII detected across all database tables and report artifacts!
```

---

## 4. Large Dataset Benchmark (`--scale large`)

Generated via `python assignment-a-data/tools/generate_data.py --seed 42 --scale large --out data_large`:
- Dataset Size: 143,990 leads, 632,602 events
- Ingestion Drop 1: 150.54s (4 lead files, 62 event files)
- Ingestion Drop 2: 338.04s (2 lead files, 65 event files, 70,739 orphans reconciled)
- Report Generation: 32.76s (all 5 reports generated)
- **Total Pipeline Execution: 521.35s (~8.7 minutes)**

