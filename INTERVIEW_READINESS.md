# Interview Readiness Guide: Agentic Universe Junior SDE
**Candidate:** Sonu Kumar  
**Assignment:** A – Interaction Ledger & Reporting Pipeline  
**Role Target:** Junior / Mid-Level Backend & Data Engineer (Python / SQLite / Cryptography)

---

## 1. System Walkthrough & Core Code Architecture

### 1.1 Project Architecture
The solution is organized into modular Python packages adhering to clean code boundaries:
- `solution/config.py`: Environment-based settings (`PII_SECRET_KEY`, `DATABASE_PATH`, `STRICT_SECURITY`), IST timezone definition (`UTC+05:30`), and logging configuration.
- `solution/crypto/pii.py`: `PIIEngine` handling HKDF key derivation, HMAC-SHA256 blind indexing, AES-256-GCM AEAD encryption/decryption, and display phone masking (`+91******XXXX`).
- `solution/db/`:
  - `connection.py`: Thread-safe SQLite connection factory with WAL mode, foreign keys, and transaction management (`with db_mgr.transaction() as conn:`).
  - `schema.py`: Schema DDL, table constraints, and 8 performance/query indexes.
- `solution/domain/schemas.py`: Schema parser (`WorkflowSchema`, `FieldSchema`) with regex header normalization and alias resolution.
- `solution/ingestion/`:
  - `normalizers.py`: Pure type normalizers for phone, day-first dates, decimal currency, and enums.
  - `lead_ingestor.py`: Deterministic CSV parser, schema-order validation, lead deduplication and non-null attribute merging.
  - `event_ingestor.py`: 4-step event parser, append-only ledger insertion, and intra-file duplicate tracking.
  - `reconciler.py`: Two-stage orphan reconciliation engine (phone-based and override call-id based).
- `solution/reporting/`: Call facts extraction, 4-tier bucket precedence state machine, and CSV/JSON generators.
- `solution/cli.py` & `solution/__main__.py`: CLI interface supporting `python -m solution ingest` and `report`.

---

## 2. Key Engineering Concepts (Explain in Simple Technical Language)

### 2.1 Why Not Ordinary SHA-256 for Phone Numbers?
**Explanation:**  
An Indian mobile number is strictly 10 digits starting with 6, 7, 8, or 9. That represents only $4 \times 10^9$ possible numbers. On modern hardware, an attacker can compute SHA-256 hashes for all 4 billion combinations in under an hour, creating a complete rainbow table. Unkeyed hashing provides virtually zero protection for low-entropy phone numbers.

### 2.2 How HMAC-SHA256 Blind Indexing Works
**Explanation:**  
We use a keyed hash: $\text{HMAC}(K_{\text{blind}}, \text{phone})$. The 256-bit key $K_{\text{blind}}$ is derived from an environment secret using HKDF. Without the secret key, precomputed rainbow tables are useless. Because the function is deterministic for that key, it produces the exact same 64-character hex string for both lead uploads and call events, enabling fast $O(\log N)$ indexed B-tree database joins without storing or exposing plaintext phone numbers.

### 2.3 AES-256-GCM Authenticated Encryption
**Explanation:**  
Recoverable fields (`phone`, `customer_name`) are encrypted using AES-256 in Galois/Counter Mode (GCM). Every encryption generates a fresh, random 96-bit nonce (`os.urandom(12)`). The stored payload is `base64url(nonce || ciphertext || tag)`. During decryption, GCM verifies the 16-byte authentication tag; any bit-level modification or database tampering raises a `DecryptionError`.

### 2.4 Append-Only Interaction Ledger & Linkage Metadata
**Explanation:**  
In regulated telephony systems, audit trails must be immutable. Original raw event records in `interaction_ledger` (`event_id`, `event_type`, `workflow_id`, `call_id`, `occurred_at_utc`, `occurred_at_ist`, `phone_blind_index`, `disposition_code`, `payload_json`, `drop_id`, `created_at`) are strictly immutable and never updated or deleted.  
Relational linkage metadata (`lead_id`, `is_orphan`) is mutable: it is initially set to `lead_id = NULL, is_orphan = 1` for quarantined events, and updated by the reconciler when matching leads arrive in later drops.  
When a human supervisor changes an AI classification via `disposition.override`, it is appended as an independent event. The reporting engine derives the call's effective disposition by picking the latest override by timestamp, preserving historical truth.

### 2.5 Two-Stage Orphan Reconciliation
**Explanation:**  
Call events frequently arrive in Drop 1 before the corresponding customer leads are uploaded in Drop 2.
1. *Quarantine:* Unmatched events are stored with `lead_id = NULL` and `is_orphan = 1`, keeping them out of report metrics.
2. *Stage 1 Reconciliation (Phone Matching):* When new leads arrive in a later drop, SQL joins match `(workflow_id, phone_blind_index)`, updating `lead_id` and setting `is_orphan = 0`.
3. *Stage 2 Reconciliation (Override Matching):* Supervisor overrides contain only `call_id` (no phone). The reconciler matches the `call_id` against sibling events in the ledger that already have a `lead_id`, linking the override.

### 2.6 The 4-Tier Lead Bucket State Machine
**Explanation:**  
Evaluated in strict short-circuit precedence:
1. `yet_to_reach_out`: Lead has 0 counted calls (calls with `call.initiated`).
2. `completed`: Any call's effective disposition has `is_terminal = true`.
3. `in_progress_telephony_failed`: Every counted call has a `call.telephony_failed` event.
4. `in_progress_dialed`: All remaining leads that were dialed.

---

## 3. High-Value Interview Q&A Bank

#### Q1: How do you guarantee exact idempotency if a drop is re-ingested?
> *"Before opening any lead CSV or event JSONL file, `_compute_file_hash()` computes its SHA-256 checksum. If the file path and hash exist in `ingested_files`, the ingestor skips the file entirely. Re-ingesting a drop processes 0 files, writes 0 duplicate rows, and leaves quality counters and reports completely unchanged."*

#### Q2: What defines a counted 'call' in your pipeline?
> *"Per specification: a call is counted only if its `call.initiated` event is present and linked. If an event stream contains telephony errors or disconnects without an initiation event, it is not counted. The call's date is strictly the IST calendar date of `call.initiated`."*

#### Q3: How do you handle naive timestamps vs UTC timestamps?
> *"Event timestamps arrive in UTC (`Z`), explicit offset (`+05:30`), or naive string (`2026-10-03 10:01:00`). Per specification: 'Naive means IST.' Naive timestamps are assigned `tzinfo = IST` (`UTC+05:30`). Both UTC (for chronological sorting) and IST (for report dates) are stored in the ledger."*

#### Q4: What happens if a lead CSV has missing or invalid optional fields?
> *"If an optional field is invalid (e.g. malformed expiry date), it is stored as `NULL` and increments `field_warnings` by 1. Crucially, field warnings are counted only for accepted leads. If a required field is missing or the phone is invalid, the entire row is rejected to `rejections.csv` and no warnings are counted."*

#### Q5: How do you handle non-null lead attribute merging?
> *"The first valid lead record creates the lead, and its file stem (e.g., `batch_001`) becomes its permanent `batch_id`. Each subsequent valid upload for the same `(workflow_id, phone_blind_index)` counts as a merged duplicate. Only fields where the new record has a non-null value overwrite existing attributes (*last write wins*). Schema defaults apply after merging to any fields that remain null."*

---

## 4. Live Coding Requirement Walkthrough

### Requirement Introduced: Extended Phone Normalization
**Requirement:** Operations onboarded aggregators sending international prefixes `+91-`, `+91 `, `0091`, `(91)`, and numbers with leading `0`. All valid Indian mobile numbers must normalize to `+919876543210`. Unsupported international codes (`+44...`, `+1...`) and invalid formats must be rejected.

### Implementation Solution (`solution/ingestion/normalizers.py`):
```python
def normalize_phone(raw: Optional[str]) -> Tuple[bool, Optional[str]]:
    if raw is None:
        return False, None

    cleaned = str(raw).strip()
    if not cleaned or re.search(r"[^\d\+\-\(\)\s]", cleaned):
        return False, None

    # 1. Parentheses balance and structure checks
    num_open = cleaned.count("(")
    num_close = cleaned.count(")")
    if num_open != num_close or num_open > 1:
        return False, None
    if num_open == 1:
        open_idx = cleaned.find("(")
        close_idx = cleaned.find(")")
        if open_idx > close_idx:
            return False, None
        inside_paren = cleaned[open_idx + 1:close_idx].strip()
        if inside_paren not in ("91", "+91", "091", "0091"):
            return False, None

    # 2. Plus sign checks (must be single and leading)
    num_plus = cleaned.count("+")
    if num_plus > 1:
        return False, None
    if num_plus == 1 and not (cleaned.startswith("+") or cleaned.startswith("(+")):
        return False, None

    # 3. Reject consecutive hyphens
    if "--" in cleaned:
        return False, None

    # 4. Handle international plus prefix (+91 or (+91))
    has_plus = (num_plus == 1)
    if has_plus:
        digits = re.sub(r"[\s\-\(\)\+]", "", cleaned)
        if not digits.startswith("91"):
            return False, None  # Reject unsupported country codes (e.g. +44...)
        digits = digits[2:]
        if len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
    else:
        digits = re.sub(r"[\s\-\(\)]", "", cleaned)
        if digits.startswith("0091"):
            digits = digits[4:]
            if len(digits) == 11 and digits.startswith("0"):
                digits = digits[1:]
        elif len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        elif len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]

    # Validate exactly 10 digits starting with 6, 7, 8, or 9
    if len(digits) != 10 or not digits.isdigit() or digits[0] not in ("6", "7", "8", "9"):
        return False, None

    return True, f"+91{digits}"
```
- **Tested in `tests/test_lead_ingestion.py`:** 10 valid test formats and 24 invalid/malformed formats tested and passing.

