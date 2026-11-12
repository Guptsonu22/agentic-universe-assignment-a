# Final Submission Verification: Agentic Universe Assignment A

**Candidate:** Sonu Kumar  
**Assignment:** Assignment A – Interaction Ledger & Reporting Pipeline  
**Verification Date:** 2026-11-12  
**Verification Tool / Assistant:** Google Antigravity (AI-assisted verification; no independent third-party audit was performed)  

---

## 1. Verification Environment

- **Operating System:** Windows 11 (PowerShell / Windows Subsystem)
- **Python Version:** Python 3.14.2 (Official Windows x86_64 build, `C:\Users\Sonu\AppData\Local\Programs\Python\Python314\python.exe`)
- **pytest Version:** pytest 9.2.0 (pluggy 1.7.0, anyio 4.16.0)
- **SQLite Version:** 3.50.4 (WAL mode enabled: `PRAGMA journal_mode = WAL`)
- **Compatibility Qualification:** Execution was performed and validated exclusively under Python 3.14.2. Although the codebase adheres to standard library features and typing annotations designed for Python 3.11+, execution on an actual Python 3.11 runtime has **not** been tested in this local environment.

---

## 2. Git Repository Integrity

### 2.1 Original File Immutability Check
```powershell
git diff -- assignment-a-data/ assignment-b-workflow/ docs/ README.md
git diff --cached -- assignment-a-data/ assignment-b-workflow/ docs/ README.md
```
- **Result:** **0 lines modified, 0 staged changes.** All original assignment specification files, schemas, generator tools, and repo root `README.md` remain 100% byte-for-byte identical to the upstream clone.

### 2.2 Modified Files Tracking
- `.gitignore`: Updated to exclude temporary environments (`.venv*/`), generated data (`data_*/`), and generated reports (`reports_*/`).
- `AI_USAGE.md`: Completed with an honest disclosure of Google Antigravity assistance, personal architectural decisions, and specific AI errors caught and corrected.
- `SUBMISSION.md`: Completed with candidate info, accurate setup and execution commands, architecture walkthrough, design decisions, failure modes, benchmark timings, and unverified Python 3.11 disclosure.
- `requirements.txt`: Added `cryptography>=42.0.0` and `python-dotenv>=1.0.0`.
- `solution/README.md`: Added clean-clone setup, execution workflows, and testing instructions.

### 2.3 Untracked Files Check
The following non-interfering solution deliverables exist as untracked files ready for staging:
- `.env.example`: Safe configuration template with non-production development fallback key.
- `IMPLEMENTATION_AUDIT.md`: Traceability matrix across all 34 requirements.
- `INTERVIEW_READINESS.md`: Technical interview preparation guide with 2-minute overview and defensive Q&A.
- `TEST_RESULTS.md`: Detailed test breakdown and execution log.
- `pytest.ini`: Test configuration specifying `testpaths = tests`.
- `solution/`: Full solution source tree (`__main__.py`, `cli.py`, `config.py`, `crypto/`, `db/`, `domain/`, `ingestion/`, `reporting/`).
- `tests/`: 45 automated regression and unit test suite.

### 2.4 Sensitive Data & Secrets Check
- **Secrets:** Zero plaintext secrets or production `.env` files are tracked or staged.
- **Databases:** Local SQLite databases (`au_ledger.db`, `au_ledger_final.db`) are excluded by `*.db` in `.gitignore`.
- **Generated Data:** `data/`, `data_large/`, `data_final/`, `reports/`, `reports_final/` are excluded by `.gitignore`.

### 2.5 Remote Repository Check
- Current remote `origin` points to the upstream template: `https://github.com/AryamannNingombam/sde-assignment-junior-2026.git`.
- **Warning:** The candidate has not yet created their own private GitHub/GitLab repository or switched the remote. Pushing to upstream is prohibited.

---

## 3. Fresh Environment Test

A temporary clean verification environment (`.venv-final`) was created from scratch using Python 3.14.2 to confirm clean-clone execution without disturbing existing local state.

### 3.1 Execution Workflow Commands & Output
```powershell
# 1. Environment creation and dependency installation
& 'C:\Users\Sonu\AppData\Local\Programs\Python\Python314\python.exe' -m venv .venv-final --clear
.\.venv-final\Scripts\pip.exe install -r requirements.txt
# Result: Successfully installed all 27 dependencies with exit code 0.

# 2. Fresh synthetic data generation
.\.venv-final\Scripts\python.exe assignment-a-data/tools/generate_data.py --seed 42 --scale small --out data_final
# Result: Generated seed=42 scale=small (drop_1: 4,247 events; drop_2: 4,498 events).

# 3. Drop 1 Ingestion
$env:DATABASE_PATH="au_ledger_final.db"; .\.venv-final\Scripts\python.exe -m solution ingest data_final/drop_1
# Result: Leads: [4 files, 1515 total, 71 rejected, 29 merged, 83 warnings]
#         Events: [1 files, 4247 total, 4 malformed, 83 duplicates dropped, 1123 orphans, 10 unknown dispositions]
#         Reconciliation: 12 events linked by call_id.

# 4. Drop 2 Ingestion
$env:DATABASE_PATH="au_ledger_final.db"; .\.venv-final\Scripts\python.exe -m solution ingest data_final/drop_2
# Result: Leads: [2 files, 542 total, 37 rejected, 28 merged, 39 warnings]
#         Events: [1 files, 4498 total, 4 malformed, 154 duplicates dropped, 462 orphans, 9 unknown dispositions]
#         Reconciliation: 910 events linked (902 by phone blind index, 8 overrides by call_id) + 36 overrides.

# 5. Idempotent Re-Ingest of Drop 1
$env:DATABASE_PATH="au_ledger_final.db"; .\.venv-final\Scripts\python.exe -m solution ingest data_final/drop_1
# Result: 0 files processed, 0 rows inserted, 0 mutations (SHA-256 hash match).

# 6. Report Generation
$env:DATABASE_PATH="au_ledger_final.db"; .\.venv-final\Scripts\python.exe -m solution report --out reports_final/
# Result: All 5 reports generated successfully in reports_final/.
```

### 3.2 Regression Test Suite Execution
```powershell
.\.venv-final\Scripts\pytest.exe -v
```
- **Result:** **45 passed in 9.71s** (0 failures, 0 warnings).
  - CLI & Multi-Drop Ingestion: 7 tests passed (including parity and recovery).
  - Event Ingestion & Ledger: 9 tests passed.
  - Cryptography & Foundation: 9 tests passed.
  - Lead Ingestion & Normalization: 13 tests passed.
  - Reporting & Bucket Logic: 7 tests passed.

### 3.3 Automated PII Scanner Results
```powershell
.\.venv-final\Scripts\python.exe tests/verify_pii.py --db au_ledger_final.db --reports reports_final
```
```text
=== PII AUDIT SUMMARY (au_ledger_final.db, reports_final) ===
Database violations: 0
Report files violations: 0
Total PII violations: 0
PASS: Zero PII detected across all database tables and report artifacts!
```
*Note: Findings are qualified as the output of pattern matching (Indian phone regex and synthetic name dictionary) against the tested database and reports.*

### 3.4 Report Formatting & Sorting Verification
Inspected headers and row structures of all 5 deliverables in `reports_final/`:
1. `batch_summary.csv`: `workflow_id,batch_id,total_leads,yet_to_reach_out,in_progress_telephony_failed,in_progress_dialed,completed` (exact order, sorted by `workflow_id, batch_id`).
2. `daily_overview.csv`: `workflow_id,date,total_calls,connected_calls,connectivity_rate,success_leads` (exact order, connectivity rate formatted to 4 decimals, sorted by `workflow_id, date`).
3. `lead_report.csv`: `workflow_id,external_ref,batch_id,phone_masked,bucket,total_calls,connected_calls,last_call_at,current_disposition,ever_success` (exact order, masked phone `+91******XXXX`, sorted by `workflow_id, external_ref`).
4. `rejections.csv`: `workflow_id,batch_id,row_number,reason` (exact order, sorted by `workflow_id, batch_id, row_number`, 0 PII).
5. `data_quality.json`: All 10 keys present (`lead_rows_total`, `lead_rows_rejected`, `rejections_by_reason`, `duplicate_lead_rows_merged`, `field_warnings`, `events_total`, `malformed_events`, `duplicate_events_dropped`, `orphan_events`, `unknown_disposition_events`).

---

## 4. Submission Requirements Checklist

| Requirement | Specification | Status | Evidence / Notes |
| :--- | :--- | :---: | :--- |
| **Assignment Chosen** | Choose A (Data) or B (Workflow). Do not do both. | **PASS** | Assignment A chosen. Assignment B is unbuilt. |
| **SUBMISSION.md** | Completed template with design, trade-offs, and timings. | **PASS** | Fully completed; reflects Sonu Kumar. |
| **AI_USAGE.md** | Complete and honest disclosure of AI tools and personal decisions. | **PASS** | Discloses Google Antigravity; details corrected errors. |
| **Clean Clone Commands** | Exact setup, run, and test commands from clean clone. | **PASS** | Documented in `SUBMISSION.md` and `solution/README.md`. |
| **Single-Command Tests** | Tests runnable with `pytest -v`. | **PASS** | 45/45 tests pass in one command. |
| **Synthetic Data Only** | No real customer data. | **PASS** | Only synthetic data used from `generate_data.py`. |
| **Git Exclusions** | Do not commit databases, `.env`, or generated data. | **PASS** | Excluded in `.gitignore`. |
| **Private Repository** | Submit work via a private GitHub/GitLab repo. | **PENDING CANDIDATE** | Candidate must create private repo and push. |
| **Reviewer Access** | Give read access to `[[REVIEWER_HANDLES]]`. | **PENDING CANDIDATE** | Placeholders in README. Candidate must obtain handles from email. |
| **Submission Email** | Email link to `[[SUBMISSION_EMAIL]]`. | **PENDING CANDIDATE** | Placeholders in README. Candidate must obtain email from invite. |

---

## 5. Phone Normalization Verification

Tested via `.\.venv-final\Scripts\pytest.exe tests/test_lead_ingestion.py -k test_phone -v`:
- **10 Valid Format Vectors (All normalize to `+919876543210`):**
  `9876543210`, `+919876543210`, `+91-98765-43210`, `+91 98765 43210`, `919876543210`, `00919876543210`, `(91) 9876543210`, `(+91) 9876543210`, `09876543210`, `91-98765-43210`.
- **24 Invalid / Malformed Vectors (All return `(False, None)`):**
  `+441234567890` (UK), `+14155550134` (US), `1234567890` (bad prefix), `987654321` (9 digits), `98765432100` (11 digits), `00911234567890` (bad subscriber), `++919876543210` (repeated +), `+91++9876543210` (multiple +), `91+9876543210` (misplaced +), `+91-98765-(43210` (dangling open paren), `(91 9876543210` (missing close paren), `)91( 9876543210` (reversed parens), `+91--98765-43210` (consecutive hyphens), `022-2345-6789` (landline), `""` (empty), `None`, `98765ABCDE` (alphabetic), etc.
- **Result:** **All phone normalization tests PASSED.**

---

## 6. Issues Found and Resolved

1. **Phone Normalizer Formatting Security Bypass:**
   - *Issue:* Permissive regex character stripping allowed inputs with repeated plus signs (`++91...`, `+91++...`) or unbalanced parentheses (`+91-98765-(43210`) to pass validation.
   - *Fix:* Enforced explicit balance checks (`count("(") == count(")") <= 1`), strictly leading plus checks (`count("+") <= 1`), and paren-enclosed country code validation.
   - *Verification:* Tested across 24 invalid test vectors; all correctly rejected.
2. **Indexed Lookup Complexity Correction:**
   - *Issue:* Documentation claimed "$O(1)$ database joins" on phone blind indices.
   - *Fix:* Corrected to fast indexed B-tree $O(\log N)$ joins, distinguishing disk-based B-tree traversal from in-memory hash tables.
3. **Ledger Immutability vs Linkage Metadata Distinction:**
   - *Issue:* Earlier documentation did not delineate raw event immutability from orphan linkage updates.
   - *Fix:* Clarified that original event payloads and audit columns are strictly immutable; only relational foreign key metadata (`lead_id`, `is_orphan`) is mutable during reconciliation.
4. **Python Version Qualification:**
   - *Issue:* Documentation implied tested compatibility across Python 3.11+.
   - *Fix:* Disclosed that testing was conducted exclusively under Python 3.14.2 on Windows; Python 3.11 was not tested locally.

---

## 7. Outstanding Candidate Action Items

The following actions cannot be automated and must be performed personally by candidate Sonu Kumar:

1. **Create Private Git Repository:**
   - Go to GitHub or GitLab and create a **private** repository (e.g. `agentic-universe-assignment-a`).
2. **Change Git Remote:**
   - Do **not** push to `AryamannNingombam/sde-assignment-junior-2026.git`.
   - Update your remote:
     ```powershell
     git remote set-url origin <YOUR_PRIVATE_REPO_URL>
     ```
3. **Stage and Commit Cleanly:**
   - Review untracked files and commit solution code:
     ```powershell
     git add .gitignore requirements.txt SUBMISSION.md AI_USAGE.md solution/ tests/ .env.example pytest.ini IMPLEMENTATION_AUDIT.md INTERVIEW_READINESS.md TEST_RESULTS.md FINAL_SUBMISSION_VERIFICATION.md
     git commit -m "Complete Assignment A: Interaction Ledger & Reporting Pipeline"
     git push -u origin main
     ```
4. **Retrieve Hiring Team Placeholders:**
   - Check the original interview invitation email from Agentic Universe to identify:
     - The reviewer GitHub/GitLab usernames (replacing `[[REVIEWER_HANDLES]]`).
     - The submission email address (replacing `[[SUBMISSION_EMAIL]]`).
5. **Grant Access & Submit:**
   - Grant read access to the reviewer handles under Repository Settings $\rightarrow$ Collaborators.
   - Email the private repository URL to the submission email before your 72-hour deadline expires.

---

## 8. Final Readiness Decision

### Decision: **READY AFTER CANDIDATE ACTION**

### Detailed Justification:
- **Code & Test Correctness:** 100% complete. All 45 regression tests pass in the clean-clone verification environment (`.venv-final`).
- **Data & Contract Integrity:** All five output reports match the assignment specifications, headers, data quality metrics, masking rules, and sorting orders.
- **PII & Ledger Security:** AES-256-GCM AEAD encryption and HMAC-SHA256 blind indexing verified with 0 PII leaks on tested artifacts.
- **Repository Cleanliness:** Original assignment files are completely unmodified. Generated databases, caches, and test data are properly ignored by `.gitignore`.
- **Sole Blocking Dependency:** The submission is ready for delivery as soon as the candidate creates their private repository, commits, pushes, and grants collaborator access to the reviewers.

