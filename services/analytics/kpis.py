"""Business KPI framework. Values are measured from the database where a defensible measure exists.

Targets and traditional baselines come from the product framework rule. They are illustrative ambition levels.
A KPI with no data or no source is reported as not measured. It is never filled with a made-up number.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from services.claims.models import (
    AgentExecutionRecord,
    Approval,
    Claim,
    ClaimTask,
    Estimate,
    FraudAlert,
    Payment,
    Settlement,
    SLATimer,
)
from services.evaluation.cost_latency import cost_latency_report
from services.rules_engine.product import product_framework
from services.workflow.sla_engine import compute_timer_status

OPEN_ALERT_STATUSES = {"new", "assigned", "investigating"}
FALSE_POSITIVE_STATUSES = {"not_substantiated"}
NOTE = "Measured from DEMO / SYNTHETIC data in the database. Targets are illustrative, not results. A KPI without data is shown as not measured."


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _hours(start: datetime, end: datetime) -> float:
    return (_aware(end) - _aware(start)).total_seconds() / 3600


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _result(value: float | None, n: int, basis: str) -> dict[str, Any]:
    if value is None or n == 0:
        return {"value": None, "n": 0, "basis": f"not measured: {basis}"}
    return {"value": value, "n": n, "basis": basis}


def _pct(num: int | float, den: int | float) -> float | None:
    return round(100.0 * num / den, 1) if den else None


def measure(db: Session, tenant_id: str) -> dict[str, dict[str, Any]]:
    claims = db.query(Claim).filter(Claim.tenant_id == tenant_id).all()
    timers = db.query(SLATimer).filter(SLATimer.tenant_id == tenant_id).all()
    approvals = db.query(Approval).filter(Approval.tenant_id == tenant_id).all()
    payments = db.query(Payment).filter(Payment.tenant_id == tenant_id).all()
    tasks = db.query(ClaimTask).filter(ClaimTask.tenant_id == tenant_id).all()
    traces = db.query(AgentExecutionRecord).filter(AgentExecutionRecord.tenant_id == tenant_id).all()
    estimates = db.query(Estimate).filter(Estimate.tenant_id == tenant_id).all()
    alerts = db.query(FraudAlert).filter(FraudAlert.tenant_id == tenant_id).all()
    out: dict[str, dict[str, Any]] = {}

    closed = [c for c in claims if c.status == "CLOSED"]
    out["avg_processing_time"] = _result(_avg([_hours(c.created_at, c.updated_at) for c in closed]), len(closed), "closed claims, created to last update")

    def stage_hours(stage: str) -> list[float]:
        return [_hours(t.started_at, t.completed_at) for t in timers if t.stage == stage and t.completed_at and t.started_at]

    for key, stage in (("fnol_to_registration", "fnol_acknowledgement"), ("registration_to_survey", "surveyor_allocation"), ("survey_to_approval", "claim_decision")):
        vals = stage_hours(stage)
        out[key] = _result(_avg(vals), len(vals), f"completed '{stage}' SLA timers (proxy)")
    approved_at = {a.claim_id: a.decided_at for a in approvals if a.decision == "approved" and a.decided_at}
    gaps = [_hours(approved_at[p.claim_id], p.created_at) for p in payments if p.claim_id in approved_at]
    out["approval_to_payment"] = _result(_avg([g for g in gaps if g >= 0]), len([g for g in gaps if g >= 0]), "approval decision to payment record")

    handlers = {c.assigned_handler_id for c in claims if c.assigned_handler_id}
    out["claims_per_handler"] = _result(round(len([c for c in claims if c.assigned_handler_id]) / len(handlers), 2) if handlers else None, len(handlers), "claims with an assigned handler")

    ai_claims = {t.claim_id for t in traces}
    tasks_by_claim = Counter(t.claim_id for t in tasks)
    approvals_by_claim = Counter(a.claim_id for a in approvals)
    stp = [c for c in ai_claims if tasks_by_claim[c] == 0 and approvals_by_claim[c] == 0]
    out["stp_rate"] = _result(_pct(len(stp), len(ai_claims)), len(ai_claims), "claims with AI activity and no human task or approval")
    touches = [tasks_by_claim[c] + approvals_by_claim[c] for c in ai_claims]
    out["human_touchpoints"] = _result(_avg([float(x) for x in touches]), len(touches), "human tasks plus approvals per claim with AI activity")

    breached = sum(1 for t in timers if compute_timer_status(t.due_at, t.completed_at, t.paused) == "breached")
    out["sla_breach_rate"] = _result(_pct(breached, len(timers)), len(timers), "SLA timers in breached state")

    latest: dict[str, Settlement] = {}
    for s in db.query(Settlement).filter(Settlement.tenant_id == tenant_id).order_by(Settlement.version).all():
        latest[s.claim_id] = s
    nets = [float(Decimal(str(s.net_payable_inr))) for s in latest.values()]
    out["avg_settlement"] = _result(_avg(nets), len(nets), "latest settlement version per claim")

    var = [abs(float(e.total_claimed_inr) - float(e.total_approved_inr)) / float(e.total_claimed_inr) * 100 for e in estimates if e.total_claimed_inr and float(e.total_claimed_inr) > 0 and e.total_approved_inr and float(e.total_approved_inr) > 0]
    out["estimate_variance"] = _result(_avg(var), len(var), "mean gap between claimed and approved totals on reviewed estimates")

    closed_alerts = [a for a in alerts if a.status not in OPEN_ALERT_STATUSES]
    fp = sum(1 for a in closed_alerts if a.status in FALSE_POSITIVE_STATUSES)
    out["false_positive_rate"] = _result(_pct(fp, len(closed_alerts)), len(closed_alerts), "closed alerts dispositioned as not substantiated")
    out["fraud_yield"] = _result(_pct(len(closed_alerts) - fp, len(closed_alerts)), len(closed_alerts), "closed alerts that were not dismissed")

    real = [t for t in traces if t.agent_name]
    reworked = sum(1 for t in real if t.rework_requests)
    out["rework_rate"] = _result(_pct(reworked, len(real)), len(real), "agent executions that requested rework")

    cl = cost_latency_report(db, tenant_id)
    out["ai_cost_per_claim"] = _result(float(cl["cost_per_claim_inr"]) if cl["claims_with_ai_activity"] else None, cl["claims_with_ai_activity"], "estimated token cost from the trace store")
    return out


def kpi_framework(db: Session, tenant_id: str) -> dict[str, Any]:
    spec = product_framework(db)
    measured = measure(db, tenant_id)
    rows = []
    for k in spec["kpis"]:
        m = measured.get(k["measure"]) if k["measure"] else None
        m = m or {"value": None, "n": 0, "basis": "not measured: no data source in this platform"}
        rows.append({**{x: k[x] for x in ("id", "name", "why", "unit", "direction")}, "traditional_illustrative": k["traditional_illustrative"], "agentic_target_illustrative": k["agentic_target_illustrative"], **m})
    return {
        "kpis": rows,
        "measured_count": sum(1 for r in rows if r["value"] is not None),
        "total_count": len(rows),
        "outcome_targets": spec["outcome_targets"],
        "before_after": spec["before_after"],
        "targets_note": spec["targets_note"],
        "note": NOTE,
    }
