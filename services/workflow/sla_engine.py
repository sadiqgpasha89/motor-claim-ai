from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from services.claims.models import SLATimer
from services.rules_engine.loader import get_active_rule


def create_stage_sla_timer(
    db: Session,
    *,
    tenant_id: str,
    claim_id: str,
    stage: str,
    started_at: datetime | None = None,
) -> SLATimer:
    sla_cfg = get_active_rule(db, "COMMON-SLA-CATALOGUE-V1")
    defn = next((t for t in sla_cfg["timers"] if t["stage"] == stage), None)
    start_dt = started_at or datetime.now(timezone.utc)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)

    reg_hours = int(defn["regulatory_hours"]) if defn else 24
    due_at = start_dt + timedelta(hours=reg_hours)
    penalty = Decimal(str(defn.get("breach_daily_penalty_inr", "0.00"))) if defn else Decimal("0.00")

    timer = SLATimer(
        tenant_id=tenant_id,
        claim_id=claim_id,
        stage=stage,
        start_event=defn["start_event"] if defn else "StageStarted",
        stop_event=defn["stop_event"] if defn else "StageCompleted",
        started_at=start_dt,
        due_at=due_at,
        owner_role=defn["owner_role"] if defn else "claims_handler",
        daily_penalty_inr=penalty,
        status=compute_timer_status(due_at, None, False),
    )
    db.add(timer)
    return timer


def compute_timer_status(due_at: datetime, completed_at: datetime | None, paused: bool) -> str:
    if completed_at is not None:
        return "completed"
    if paused:
        return "paused"
    now = datetime.now(timezone.utc)
    d = due_at.replace(tzinfo=timezone.utc) if due_at.tzinfo is None else due_at
    if now > d:
        return "breached"
    if (d - now).total_seconds() <= 6 * 3600:
        return "warning"
    return "on_track"


def complete_stage_sla_timer(db: Session, *, claim_id: str, stage: str) -> None:
    timers = (
        db.query(SLATimer)
        .filter(SLATimer.claim_id == claim_id, SLATimer.stage == stage, SLATimer.completed_at.is_(None))
        .all()
    )
    now = datetime.now(timezone.utc)
    for t in timers:
        t.completed_at = now
        t.status = "completed"
