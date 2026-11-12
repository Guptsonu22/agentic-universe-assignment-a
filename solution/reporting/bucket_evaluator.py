"""Lead bucket evaluation and interaction metrics calculation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from solution.reporting.call_facts import CallFact


@dataclass(frozen=True)
class LeadStats:
    """Aggregated call metrics for a single lead."""

    total_calls: int
    connected_calls: int
    bucket: str
    last_call_at: str
    current_disposition: str
    ever_success: bool


def evaluate_lead_bucket(calls: List[CallFact]) -> str:
    """
    Evaluate lead bucket strictly following precedence order:
    1. yet_to_reach_out: no calls.
    2. completed: any call's effective disposition is terminal (is_terminal=true).
    3. in_progress_telephony_failed: every call has a call.telephony_failed event.
    4. in_progress_dialed: everything else.
    """
    if not calls:
        return "yet_to_reach_out"

    # Precedence 2: any call's effective disposition is terminal
    if any(c.is_terminal for c in calls):
        return "completed"

    # Precedence 3: every call has a telephony_failed event
    if all(c.has_telephony_failed for c in calls):
        return "in_progress_telephony_failed"

    # Precedence 4: everything else
    return "in_progress_dialed"


def compute_lead_stats(calls: List[CallFact]) -> LeadStats:
    """
    Compute lead metrics across all counted calls for a lead.
    
    Rules:
    - total_calls: count of counted calls (calls with call.initiated).
    - connected_calls: count of calls with call.connected.
    - bucket: bucket classification.
    - last_call_at: latest call.initiated time as ISO-8601 in IST, or empty string.
    - current_disposition: effective disposition of the most recent call (by initiated time)
      that has an effective disposition, or empty string.
    - ever_success: whether any call's effective disposition has is_success=true.
    """
    if not calls:
        return LeadStats(
            total_calls=0,
            connected_calls=0,
            bucket="yet_to_reach_out",
            last_call_at="",
            current_disposition="",
            ever_success=False,
        )

    # Sort calls by initiated time ascending
    sorted_calls = sorted(calls, key=lambda c: c.initiated_at_utc)

    total_calls = len(sorted_calls)
    connected_calls = sum(1 for c in sorted_calls if c.is_connected)
    bucket = evaluate_lead_bucket(sorted_calls)
    last_call_at = sorted_calls[-1].initiated_at_ist

    # Find the most recent call (by initiated time) that has an effective disposition
    current_disposition = ""
    for c in reversed(sorted_calls):
        if c.effective_disposition:
            current_disposition = c.effective_disposition
            break

    ever_success = any(c.is_success for c in sorted_calls)

    return LeadStats(
        total_calls=total_calls,
        connected_calls=connected_calls,
        bucket=bucket,
        last_call_at=last_call_at,
        current_disposition=current_disposition,
        ever_success=ever_success,
    )

