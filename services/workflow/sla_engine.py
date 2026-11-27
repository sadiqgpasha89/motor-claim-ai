from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from services.claims.audit import emit_outbox_event
from services.claims.models import ClaimTask, SLATimer
from services.rules_engine.loader import get_active_rule
from services.workflow.state_specs import WORKFLOW_STATE_SPECS


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

    state_spec = next(
        (s for s in WORKFLOW_STATE_SPECS.values() if s.sla.stage == stage),
        None,
    )
    reg_hours = (
        int(defn["regulatory_hours"])
        if defn
        else (state_spec.sla.target_hours if state_spec else 24)
    )
    due_at = start_dt + timedelta(hours=reg_hours)
    penalty = (
        Decimal(str(defn.get("breach_daily_penalty_inr", "0.00")))
        if defn
        else Decimal(state_spec.sla.daily_penalty_inr if state_spec else "0.00")
    )
    owner_role = (
        defn["owner_role"]
        if defn
        else (state_spec.sla.escalation_role if state_spec else "claims_handler")
    )

    existing_active = (
        db.query(SLATimer)
        .filter(SLATimer.claim_id == claim_id, SLATimer.stage == stage, SLATimer.completed_at.is_(None))
        .first()
    )
    if existing_active:
        return existing_active

    timer = SLATimer(
        tenant_id=tenant_id,
        claim_id=claim_id,
        stage=stage,
        start_event=defn["start_event"] if defn else f"StateEntered:{stage}",
        stop_event=defn["stop_event"] if defn else f"StateExited:{stage}",
        started_at=start_dt,
        due_at=due_at,
        owner_role=owner_role,
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


def transition_state_sla_timer(
    db: Session,
    *,
    tenant_id: str,
    claim_id: str,
    from_state: str,
    to_state: str,
) -> SLATimer | None:
    """Completes the outgoing state's SLA timer and starts the incoming state's SLA timer."""
    from_spec = WORKFLOW_STATE_SPECS.get(from_state)
    to_spec = WORKFLOW_STATE_SPECS.get(to_state)
    if from_spec and (not to_spec or from_spec.sla.stage != to_spec.sla.stage):
        complete_stage_sla_timer(db, claim_id=claim_id, stage=from_spec.sla.stage)
    if to_spec and to_state != "CLOSED":
        return create_stage_sla_timer(
            db,
            tenant_id=tenant_id,
            claim_id=claim_id,
            stage=to_spec.sla.stage,
        )
    if to_state == "CLOSED":
        open_timers = db.query(SLATimer).filter(SLATimer.claim_id == claim_id, SLATimer.completed_at.is_(None)).all()
        now = datetime.now(timezone.utc)
        for t in open_timers:
            t.completed_at = now
            t.status = "completed"
    return None


def pause_active_sla_timers(db: Session, *, claim_id: str, reason: str) -> int:
    timers = db.query(SLATimer).filter(SLATimer.claim_id == claim_id, SLATimer.completed_at.is_(None)).all()
    count = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for t in timers:
        if not t.paused:
            t.paused = True
            t.pause_reason = f"{reason} (paused_at={now_iso})"[:240]
            t.status = "paused"
            count += 1
    return count


def resume_paused_sla_timers(db: Session, *, claim_id: str) -> int:
    timers = (
        db.query(SLATimer)
        .filter(SLATimer.claim_id == claim_id, SLATimer.completed_at.is_(None), SLATimer.paused.is_(True))
        .all()
    )
    count = 0
    for t in timers:
        t.paused = False
        t.pause_reason = None
        t.status = compute_timer_status(t.due_at, t.completed_at, False)
        count += 1
    return count


def sweep_sla_breaches(db: Session, *, tenant_id: str, claim_id: str | None = None) -> dict[str, Any]:
    """Scans open SLA timers, records breach escalations, and emits SLABreached events."""
    q = db.query(SLATimer).filter(SLATimer.tenant_id == tenant_id, SLATimer.completed_at.is_(None))
    if claim_id:
        q = q.filter(SLATimer.claim_id == claim_id)
    timers = q.all()
    breached_ids: list[str] = []
    warning_ids: list[str] = []

    for t in timers:
        live_status = compute_timer_status(t.due_at, t.completed_at, t.paused)
        t.status = live_status
        if live_status == "breached":
            breached_ids.append(t.id)
            reason_code = f"RC_SLA_BREACH_{t.stage.upper()}"[:64]
            existing_task = (
                db.query(ClaimTask)
                .filter(
                    ClaimTask.claim_id == t.claim_id,
                    ClaimTask.task_type == "sla_breach_escalation",
                    ClaimTask.reason_code == reason_code,
                    ClaimTask.status.in_(["open", "in_progress"]),
                )
                .first()
            )
            if not existing_task:
                db.add(
                    ClaimTask(
                        tenant_id=t.tenant_id,
                        claim_id=t.claim_id,
                        task_type="sla_breach_escalation",
                        title=f"SLA Breached: {t.stage}",
                        description=f"Timer {t.id} breached due_at {t.due_at.isoformat()} (owner={t.owner_role}).",
                        assigned_role="claims_manager",
                        created_by_agent="orchestrator",
                        priority="critical",
                        status="open",
                        reason_code=reason_code,
                        due_at=datetime.now(timezone.utc) + timedelta(hours=2),
                    )
                )
                emit_outbox_event(
                    db,
                    tenant_id=t.tenant_id,
                    aggregate_id=t.claim_id,
                    event_type="SLABreached",
                    payload={"timer_id": t.id, "stage": t.stage, "owner_role": t.owner_role},
                    idempotency_key=f"SLABreached:{t.id}",
                )
        elif live_status == "warning":
            warning_ids.append(t.id)
    db.flush()
    return {
        "scanned": len(timers),
        "breached_count": len(breached_ids),
        "warning_count": len(warning_ids),
        "breached_timer_ids": breached_ids,
        "warning_timer_ids": warning_ids,
    }
