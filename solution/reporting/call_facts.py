"""Call facts extraction and effective disposition resolution."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class CallFact:
    """Represents a counted call and its derived interaction facts."""

    call_id: str
    lead_id: int
    workflow_id: str
    initiated_at_ist: str  # ISO-8601 in IST, e.g. '2026-10-14T17:55:24+05:30'
    initiated_at_utc: str
    ist_date: str  # 'YYYY-MM-DD'
    is_connected: bool
    has_telephony_failed: bool
    effective_disposition: Optional[str]
    is_terminal: bool
    is_success: bool


def extract_call_facts(conn: sqlite3.Connection) -> List[CallFact]:
    """
    Extract and derive facts for all counted calls in the interaction ledger.
    
    Rules:
    - A call is counted ONLY if its call.initiated event is present (and linked).
    - The call's date is the IST date of call.initiated.
    - A call is connected if it has a call.connected event.
    - Effective disposition is the latest disposition.override by occurred_at;
      if none, the latest disposition.set.
    """
    # Fetch all linked events ordered chronologically
    query = """
    SELECT 
        il.call_id,
        il.lead_id,
        il.workflow_id,
        il.event_type,
        il.occurred_at_utc,
        il.occurred_at_ist,
        il.disposition_code,
        dc.is_terminal,
        dc.is_success
    FROM interaction_ledger il
    LEFT JOIN disposition_catalogue dc 
        ON il.workflow_id = dc.workflow_id AND il.disposition_code = dc.code
    WHERE il.is_orphan = 0 AND il.lead_id IS NOT NULL
    ORDER BY il.call_id, il.occurred_at_utc ASC;
    """
    rows = conn.execute(query).fetchall()

    # Group events by call_id
    call_events: Dict[str, List[sqlite3.Row]] = {}
    for r in rows:
        cid = r["call_id"]
        if cid not in call_events:
            call_events[cid] = []
        call_events[cid].append(r)

    call_facts: List[CallFact] = []

    for cid, events in call_events.items():
        # Rule: Call is counted ONLY if call.initiated event is present
        init_event = next((e for e in events if e["event_type"] == "call.initiated"), None)
        if init_event is None:
            continue

        lead_id = init_event["lead_id"]
        workflow_id = init_event["workflow_id"]
        initiated_at_ist = init_event["occurred_at_ist"]
        initiated_at_utc = init_event["occurred_at_utc"]
        ist_date = initiated_at_ist[:10]  # Extract 'YYYY-MM-DD'

        is_connected = any(e["event_type"] == "call.connected" for e in events)
        has_telephony_failed = any(e["event_type"] == "call.telephony_failed" for e in events)

        # Resolve effective disposition
        # Overrides have precedence over set; latest by occurred_at wins
        overrides = [
            e for e in events 
            if e["event_type"] == "disposition.override" and e["is_terminal"] is not None
        ]
        sets = [
            e for e in events 
            if e["event_type"] == "disposition.set" and e["is_terminal"] is not None
        ]

        effective_event = None
        if overrides:
            # Latest override by occurred_at_utc
            effective_event = max(overrides, key=lambda e: e["occurred_at_utc"])
        elif sets:
            # Latest disposition.set by occurred_at_utc
            effective_event = max(sets, key=lambda e: e["occurred_at_utc"])

        if effective_event:
            eff_disp = effective_event["disposition_code"]
            is_term = bool(effective_event["is_terminal"])
            is_succ = bool(effective_event["is_success"])
        else:
            eff_disp = None
            is_term = False
            is_succ = False

        call_facts.append(
            CallFact(
                call_id=cid,
                lead_id=lead_id,
                workflow_id=workflow_id,
                initiated_at_ist=initiated_at_ist,
                initiated_at_utc=initiated_at_utc,
                ist_date=ist_date,
                is_connected=is_connected,
                has_telephony_failed=has_telephony_failed,
                effective_disposition=eff_disp,
                is_terminal=is_term,
                is_success=is_succ,
            )
        )

    return call_facts

