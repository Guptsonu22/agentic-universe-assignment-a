"""Orphan reconciliation engine for resolving late-arriving leads and event linking."""
from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger("agentic_universe.reconciler")


def reconcile_orphans(conn: sqlite3.Connection) -> int:
    """
    Reconcile previously orphaned events in the interaction ledger against leads.
    
    Resolves:
    1. Events with phone_blind_index whose lead was ingested later.
    2. Disposition overrides (which have no phone) whose sibling call events are now linked.
    
    Returns:
        Total number of newly linked events.
    """
    # 1. Link orphan events that have a phone_blind_index to matching leads
    cur1 = conn.execute(
        """
        UPDATE interaction_ledger
        SET lead_id = (
            SELECT l.id FROM leads l
            WHERE l.workflow_id = interaction_ledger.workflow_id
              AND l.phone_blind_index = interaction_ledger.phone_blind_index
        ),
        is_orphan = 0
        WHERE is_orphan = 1
          AND phone_blind_index IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM leads l
            WHERE l.workflow_id = interaction_ledger.workflow_id
              AND l.phone_blind_index = interaction_ledger.phone_blind_index
          );
        """
    )
    linked_phone_events = cur1.rowcount

    # 2. Link orphan overrides (which lack phone numbers) via call_id of linked sibling events
    cur2 = conn.execute(
        """
        UPDATE interaction_ledger
        SET lead_id = (
            SELECT sibling.lead_id FROM interaction_ledger sibling
            WHERE sibling.call_id = interaction_ledger.call_id
              AND sibling.lead_id IS NOT NULL
            LIMIT 1
        ),
        is_orphan = 0
        WHERE is_orphan = 1
          AND lead_id IS NULL
          AND EXISTS (
            SELECT 1 FROM interaction_ledger sibling
            WHERE sibling.call_id = interaction_ledger.call_id
              AND sibling.lead_id IS NOT NULL
          );
        """
    )
    linked_overrides = cur2.rowcount
    total_linked = linked_phone_events + linked_overrides

    if total_linked > 0:
        logger.info(
            "Orphan reconciliation completed: resolved %d events (%d by phone, %d overrides by call_id)",
            total_linked,
            linked_phone_events,
            linked_overrides,
        )

    return total_linked

