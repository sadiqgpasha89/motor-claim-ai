"""Workflow recovery sweeper.

Orchestration state is stored in the database, so a crash loses no task. This sweeper finds open claims that have
runnable tasks that sat idle, and sends each one a recovery event. The event id contains the claim and the hour,
so running the sweeper twice in one hour is safe: the orchestrator ignores the second event as a duplicate.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from packages.security.auth import UserContext
from services.claims.models import Claim, OrchestrationTask
from services.workflow.orchestrator import ClaimOrchestrator

RUNNABLE_STATUSES = ("pending", "scheduled", "timed_out", "requeued")
TERMINAL_CLAIM_STATUSES = ("CLOSED", "REJECTED", "WITHDRAWN", "CANCELLED")


def recover_stalled_workflows(
    db: Session, user: UserContext, *, now: datetime | None = None, stall_minutes: int = 15, limit: int = 25,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=stall_minutes)
    candidates = (
        db.query(OrchestrationTask.claim_id)
        .filter(OrchestrationTask.tenant_id == user.tenant_id, OrchestrationTask.status.in_(RUNNABLE_STATUSES), OrchestrationTask.scheduled_at <= cutoff)
        .distinct()
        .limit(limit)
        .all()
    )
    swept: list[dict[str, Any]] = []
    orch = ClaimOrchestrator(db, user)
    for (claim_id,) in candidates:
        claim = db.query(Claim).filter(Claim.id == claim_id, Claim.tenant_id == user.tenant_id).first()
        if claim is None or claim.status in TERMINAL_CLAIM_STATUSES:
            continue
        res = orch.handle_event(
            claim,
            event_id=f"recovery:{claim.id}:{now:%Y%m%d%H}",
            event_type="WorkflowRecoverySweep",
            source="recovery_sweeper",
            payload={"stall_minutes": stall_minutes},
            auto_advance=True,
        )
        swept.append({"claim_id": claim.id, "claim_number": claim.claim_number, "duplicate_ignored": bool(res.get("duplicate_ignored")), "claim_status": claim.status})
    db.commit()
    return {"claims_swept": len(swept), "details": swept, "stall_minutes": stall_minutes}
