"""Field type normalizers with strict validation per assignment specification."""
from __future__ import annotations

import datetime
import re
from typing import List, Optional, Tuple

MONTH_MAP = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

# Regex to strip currency prefixes: ₹, Rs, Rs., INR (case-insensitive, optional space)
CURRENCY_PREFIX_REGEX = re.compile(r"^\s*(?:₹|rs\.?|inr)\s*", re.IGNORECASE)


def normalize_string(raw: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Normalise a string value.
    Returns (is_valid, value). Empty or whitespace-only is treated as missing.
    """
    if raw is None:
        return False, None
    val = raw.strip()
    if not val:
        return False, None
    return True, val


def normalize_phone(raw: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Normalise an Indian mobile number.

    Accepts:
    - 10-digit mobile number starting with 6, 7, 8, 9 (e.g. 9876543210)
    - 11-digit number with leading 0 (e.g. 09876543210)
    - With country code 91, +91, 0091, (91), or (+91)
    - Formatting characters: spaces, hyphens, parentheses

    Rejects:
    - Non-Indian international country codes (e.g. +44..., +1...)
    - Numbers with first digit not in [6, 7, 8, 9]
    - Incomplete or overlong numbers
    - Alphabetic or invalid characters
    - Repeated or misplaced plus signs (e.g. ++91..., +91++..., 91+...)
    - Unbalanced or misplaced parentheses (e.g. (91..., +91-98765-(43210)
    - Malformed formatting

    Canonical format: +91XXXXXXXXXX
    """
    if raw is None:
        return False, None

    cleaned = str(raw).strip()
    if not cleaned:
        return False, None

    # Check for invalid characters: only digits, +, -, (, ), and whitespace permitted
    if re.search(r"[^\d\+\-\(\)\s]", cleaned):
        return False, None

    # 1. Parentheses balance and structure checks
    num_open = cleaned.count("(")
    num_close = cleaned.count(")")
    if num_open != num_close:
        # Unbalanced parentheses (e.g. '(91 9876543210' or '+91-98765-(43210')
        return False, None
    if num_open > 1:
        # Multiple pairs of parentheses not permitted
        return False, None
    if num_open == 1:
        open_idx = cleaned.find("(")
        close_idx = cleaned.find(")")
        if open_idx > close_idx:
            # Misplaced parentheses: ')' before '('
            return False, None
        inside_paren = cleaned[open_idx + 1:close_idx].strip()
        # Inside parentheses must only be valid country/prefix code e.g. '91' or '+91'
        if inside_paren not in ("91", "+91", "091", "0091"):
            return False, None

    # 2. Plus sign checks
    num_plus = cleaned.count("+")
    if num_plus > 1:
        # Repeated plus signs (e.g. '++919876543210', '+91++9876543210')
        return False, None
    if num_plus == 1:
        # Plus must appear strictly at the beginning of the prefix:
        # e.g. '+91...', or '(+91)...'
        # Misplaced plus like '91+9876543210' or '98765+43210' is rejected
        if not (cleaned.startswith("+") or cleaned.startswith("(+")):
            return False, None

    # 3. Hyphen checks (reject consecutive hyphens '--')
    if "--" in cleaned:
        return False, None

    # 4. Extract digits and validate country code
    has_plus = (num_plus == 1)
    if has_plus:
        digits = re.sub(r"[\s\-\(\)\+]", "", cleaned)
        if not digits.startswith("91"):
            # Unsupported international country code (e.g. +44..., +1...)
            return False, None
        digits = digits[2:]
        if len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
    else:
        # Strip permitted formatting characters
        digits = re.sub(r"[\s\-\(\)]", "", cleaned)
        # Handle 0091 international dialing prefix first
        if digits.startswith("0091"):
            digits = digits[4:]
            if len(digits) == 11 and digits.startswith("0"):
                digits = digits[1:]
        # Handle 91 country code prefix if 12 digits
        elif len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        # Handle leading 0 (11 digits)
        elif len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]

    # Must be exactly 10 digits
    if len(digits) != 10 or not digits.isdigit():
        return False, None

    # Must start with 6, 7, 8, or 9
    if digits[0] not in ("6", "7", "8", "9"):
        return False, None

    return True, f"+91{digits}"


def normalize_date(raw: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Normalise a date string.
    Rules:
    - Accept YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY and DD-Mon-YYYY (e.g. 01-Dec-2026).
    - Dates are day-first.
    - Impossible dates (like 31/02) are invalid.
    - Returns canonical ISO YYYY-MM-DD.
    """
    if raw is None:
        return False, None

    cleaned = raw.strip()
    if not cleaned:
        return False, None

    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None

    # 1. YYYY-MM-DD
    m1 = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", cleaned)
    if m1:
        year = int(m1.group(1))
        month = int(m1.group(2))
        day = int(m1.group(3))

    # 2. DD/MM/YYYY
    elif re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", cleaned):
        m2 = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", cleaned)
        if m2:
            day = int(m2.group(1))
            month = int(m2.group(2))
            year = int(m2.group(3))

    # 3. DD-MM-YYYY
    elif re.match(r"^(\d{1,2})-(\d{1,2})-(\d{4})$", cleaned):
        m3 = re.match(r"^(\d{1,2})-(\d{1,2})-(\d{4})$", cleaned)
        if m3:
            day = int(m3.group(1))
            month = int(m3.group(2))
            year = int(m3.group(3))

    # 4. DD-Mon-YYYY (e.g. 01-Dec-2026)
    elif re.match(r"^(\d{1,2})-([a-zA-Z]{3})-(\d{4})$", cleaned):
        m4 = re.match(r"^(\d{1,2})-([a-zA-Z]{3})-(\d{4})$", cleaned)
        if m4:
            day = int(m4.group(1))
            mon_str = m4.group(2).lower()
            year = int(m4.group(3))
            month = MONTH_MAP.get(mon_str)

    if year is None or month is None or day is None:
        return False, None

    try:
        parsed_date = datetime.date(year, month, day)
        return True, parsed_date.isoformat()
    except (ValueError, OverflowError):
        # Impossible date like 31/02
        return False, None


def normalize_decimal(raw: Optional[str]) -> Tuple[bool, Optional[float]]:
    """
    Normalise a decimal / currency value.
    Rules:
    - Optionally prefixed by ₹, Rs, Rs. or INR (case-insensitive, optional space).
    - Commas are thousands separators.
    - Must be >= 0.
    - Round to 2 places.
    """
    if raw is None:
        return False, None

    cleaned = raw.strip()
    if not cleaned:
        return False, None

    # Strip prefix
    without_prefix = CURRENCY_PREFIX_REGEX.sub("", cleaned).strip()

    # Strip commas
    without_commas = without_prefix.replace(",", "")

    try:
        val = float(without_commas)
        if val < 0:
            return False, None
        return True, round(val, 2)
    except ValueError:
        return False, None


def normalize_enum(raw: Optional[str], allowed_values: List[str]) -> Tuple[bool, Optional[str]]:
    """
    Normalise an enum value.
    Rules:
    - Compared case-insensitively against allowed values.
    - Stored lower-case.
    """
    if raw is None:
        return False, None

    cleaned = raw.strip().lower()
    if not cleaned:
        return False, None

    allowed_lower = {v.lower(): v.lower() for v in allowed_values}
    if cleaned in allowed_lower:
        return True, allowed_lower[cleaned]

    return False, None

