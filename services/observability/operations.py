"""Operations console queries: what the AI system is doing, not just where a claim ended up (item 16)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from services.agent_runtime.gateway import ModelGateway
from services.claims.models import (
    AgentExecutionRecord,
    Approval,
    Claim,
    ClaimTask,
    DeadLetterRecord,
    FraudAlert,
    OrchestrationTask,
    Payment,
    SLATimer,
)
from services.integrations.adapters import IntegrationAdapterRegistry
from services.observability.traces import FAILED_OUTCOMES
from services.workflow.sla_engine import compute_timer_status

STUCK_AFTER_HOURS = 24
TERMINAL_STATUSES = {"CLOSED", "DECLINED_PARTIAL"}
PAYMENT_RECON_FAILURE_STATUSES = {"timeout_reconcile_pending", "failed", "reconciliation_failed", "mismatch"}
OPEN_FRAUD_STATUSES = {"new", "assigned", "investigating"}
HUMAN_TASK_STATUSES = {"open", "waiting_human"}
NOTE = "Values are computed live from the agent trace store over DEMO / SYNTHETIC data. Token counts are estimated."


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _iso(dt: datetime | None) -> str | None:
    d = _aware(dt)
    return d.isoformat() if d else None


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _pct(num: int | float, den: int | float) -> float:
    return round(100.0 * num / den, 1) if den else 0.0


def serialize_trace(rec: AgentExecutionRecord) -> dict[str, Any]:
    return {
        "id": rec.id,
        "claim_id": rec.claim_id,
        "workflow_id": rec.workflow_run_id,
        "agent_name": rec.agent_name,
        "agent_version": rec.agent_version,
        "model_name": rec.model_name,
        "model_version": rec.model_version,
        "prompt_version": rec.prompt_version,
        "task_input_ref": rec.task_input_ref,
        "tool_calls": rec.tool_calls or [],
        "tool_outputs": rec.tool_outputs or [],
        "started_at": _iso(rec.started_at or rec.created_at),
        "ended_at": _iso(rec.ended_at or rec.created_at),
        "token_usage": {
            "input": rec.tokens_input,
            "output": rec.tokens_output,
            "total": rec.tokens_input + rec.tokens_output,
            "source": rec.usage_source,
        },
        "cost_inr": _money(Decimal(str(rec.cost_inr or 0))),
        "latency_ms": rec.duration_ms,
        "retry_count": rec.retry_count,
        "attempt_number": rec.attempt_number,
        "status": rec.status,
        "outcome": rec.outcome,
        "confidence": float(rec.confidence) if rec.confidence is not None else None,
        "error_details": rec.error_details,
        "human_intervention": rec.human_intervention,
        "final_action": rec.final_action,
        "stage_order": rec.stage_order,
        "depends_on": rec.depends_on or [],
        "reason_codes": (rec.decision or {}).get("reason_codes", []),
        "explanation": (rec.decision or {}).get("explanation", ""),
    }


def _cost_rollup(rows: list[tuple[AgentExecutionRecord, Claim | None]]) -> dict[str, Any]:
    by_claim: dict[str, dict[str, Any]] = {}
    by_agent: dict[str, dict[str, Any]] = {}
    by_complexity: dict[str, dict[str, Any]] = {}

    def add(bucket: dict[str, dict[str, Any]], key: str, rec: AgentExecutionRecord, **extra: Any) -> None:
        b = bucket.setdefault(key, {"cost_inr": Decimal("0"), "executions": 0, "tokens": 0, **extra})
        b["cost_inr"] += Decimal(str(rec.cost_inr or 0))
        b["executions"] += 1
        b["tokens"] += rec.tokens_input + rec.tokens_output

    claims_per_tier: dict[str, set[str]] = defaultdict(set)
    for rec, claim in rows:
        add(by_claim, rec.claim_id, rec, claim_number=claim.claim_number if claim else rec.claim_id)
        add(by_agent, rec.agent_name, rec)
        tier = (claim.risk_tier if claim else "UNKNOWN") or "UNKNOWN"
        add(by_complexity, tier, rec)
        claims_per_tier[tier].add(rec.claim_id)

    def fmt(bucket: dict[str, dict[str, Any]], *, key_name: str, per: dict[str, int] | None = None) -> list[dict[str, Any]]:
        out = []
        for key, b in sorted(bucket.items(), key=lambda kv: kv[1]["cost_inr"], reverse=True):
            item = {key_name: key, **{k: v for k, v in b.items() if k != "cost_inr"}, "cost_inr": _money(b["cost_inr"])}
            if per is not None:
                item["claims"] = per.get(key, 0)
                item["avg_cost_per_claim_inr"] = _money(b["cost_inr"] / max(per.get(key, 1), 1))
            out.append(item)
        return out

    return {
        "by_claim": fmt(by_claim, key_name="claim_id")[:25],
        "by_agent": fmt(by_agent, key_name="agent_name"),
        "by_claim_complexity": fmt(by_complexity, key_name="complexity", per={k: len(v) for k, v in claims_per_tier.items()}),
        "complexity_basis": "claims.risk_tier (LOW=simple, MEDIUM=standard, HIGH=complex)",
    }


def build_operations_dashboard(db: Session, *, tenant_id: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    claims = {c.id: c for c in db.query(Claim).filter(Claim.tenant_id == tenant_id).all()}
    traces = db.query(AgentExecutionRecord).filter(AgentExecutionRecord.tenant_id == tenant_id).order_by(AgentExecutionRecord.created_at.asc()).all()
    rows = [(t, claims.get(t.claim_id)) for t in traces]
    real = [t for t in traces if t.outcome != "blocked"]

    # Latest execution per (workflow run, agent) decides whether a workflow succeeded.
    latest: dict[tuple[str, str], AgentExecutionRecord] = {}
    for t in real:
        latest[(t.workflow_run_id, t.agent_name)] = t
    runs: dict[str, list[AgentExecutionRecord]] = defaultdict(list)
    for (run_id, _), t in latest.items():
        runs[run_id].append(t)
    ok_runs = sum(1 for ts in runs.values() if not any(x.outcome in FAILED_OUTCOMES for x in ts))
    escalated = sum(1 for t in real if t.outcome == "escalated_to_human" or (t.human_intervention or {}).get("required"))
    total_ms_per_run = [sum(x.duration_ms for x in ts) for ts in runs.values()]
    total_cost = sum((Decimal(str(t.cost_inr or 0)) for t in traces), Decimal("0"))
    claims_with_ai = {t.claim_id for t in traces}

    kpis = {
        "workflow_success_rate_pct": _pct(ok_runs, len(runs)),
        "human_escalation_rate_pct": _pct(escalated, len(real)),
        "avg_ai_execution_time_ms": round(sum(total_ms_per_run) / len(total_ms_per_run)) if total_ms_per_run else 0,
        "avg_ai_execution_time_min": round((sum(total_ms_per_run) / len(total_ms_per_run)) / 60000, 4) if total_ms_per_run else 0.0,
        "ai_cost_per_claim_inr": _money(total_cost / max(len(claims_with_ai), 1)),
        "workflow_runs": len(runs),
        "agent_executions": len(traces),
        "claims_with_ai_activity": len(claims_with_ai),
        "total_tokens_estimated": sum(t.tokens_input + t.tokens_output for t in traces),
        "basis": "measured_from_trace_store",
    }

    failed = [
        {**serialize_trace(t), "claim_number": claims[t.claim_id].claim_number if t.claim_id in claims else t.claim_id}
        for t in reversed(traces)
        if t.outcome in FAILED_OUTCOMES
    ][:25]

    # Stuck workflows: paused, dead-lettered, or no movement for STUCK_AFTER_HOURS on a non-terminal claim.
    open_dlq = db.query(DeadLetterRecord).filter(DeadLetterRecord.tenant_id == tenant_id, DeadLetterRecord.status == "open").all()
    dlq_claims = {d.claim_id for d in open_dlq}
    stuck: list[dict[str, Any]] = []
    for c in claims.values():
        if c.status in TERMINAL_STATUSES:
            continue
        paused = bool((c.workflow_state or {}).get("paused"))
        idle_h = (now - (_aware(c.updated_at) or now)).total_seconds() / 3600
        reasons = []
        if paused:
            reasons.append("workflow_paused")
        if c.id in dlq_claims:
            reasons.append("dead_letter_open")
        if idle_h >= STUCK_AFTER_HOURS:
            reasons.append(f"no_movement_{int(idle_h)}h")
        if reasons:
            stuck.append({"claim_id": c.id, "claim_number": c.claim_number, "status": c.status, "reasons": reasons,
                          "idle_hours": round(idle_h, 1), "next_expected_action": c.next_expected_action})
    stuck.sort(key=lambda s: s["idle_hours"], reverse=True)

    timers = db.query(SLATimer).filter(SLATimer.tenant_id == tenant_id).all()
    sla_breaches = [
        {"claim_id": t.claim_id, "claim_number": claims[t.claim_id].claim_number if t.claim_id in claims else t.claim_id,
         "stage": t.stage, "due_at": _iso(t.due_at), "owner_role": t.owner_role}
        for t in timers
        if compute_timer_status(t.due_at, t.completed_at, t.paused) == "breached"
    ]

    pending_approvals = db.query(Approval).filter(Approval.tenant_id == tenant_id, Approval.decision == "pending").all()
    human_tasks = db.query(ClaimTask).filter(ClaimTask.tenant_id == tenant_id, ClaimTask.status.in_(HUMAN_TASK_STATUSES)).all()
    approval_backlog = {
        "pending_approvals": [
            {"approval_id": a.id, "claim_id": a.claim_id, "claim_number": claims[a.claim_id].claim_number if a.claim_id in claims else a.claim_id,
             "action_type": a.action_type, "amount_inr": _money(Decimal(str(a.amount_inr))),
             "age_hours": round((now - (_aware(a.created_at) or now)).total_seconds() / 3600, 1)}
            for a in pending_approvals
        ],
        "open_human_tasks": len(human_tasks),
        "claims_in_human_review": sum(1 for c in claims.values() if c.status == "HUMAN_REVIEW"),
    }

    alerts = db.query(FraudAlert).filter(FraudAlert.tenant_id == tenant_id, FraudAlert.status.in_(OPEN_FRAUD_STATUSES)).all()
    fraud_queue = {
        "open_alerts": len(alerts),
        "claims_in_investigation": sum(1 for c in claims.values() if c.status == "INVESTIGATION_REQUIRED"),
        "alerts": [
            {"alert_id": a.id, "claim_id": a.claim_id, "claim_number": claims[a.claim_id].claim_number if a.claim_id in claims else a.claim_id,
             "indicator_code": a.indicator_code, "severity_band": a.severity_band, "status": a.status}
            for a in alerts[:25]
        ],
    }

    payments = db.query(Payment).filter(Payment.tenant_id == tenant_id).all()
    recon_failures = [
        {"payment_id": p.id, "claim_id": p.claim_id, "claim_number": claims[p.claim_id].claim_number if p.claim_id in claims else p.claim_id,
         "status": p.status, "amount_inr": _money(Decimal(str(p.amount_inr))), "gateway_reference": p.gateway_reference}
        for p in payments
        if p.status in PAYMENT_RECON_FAILURE_STATUSES
    ]

    outage_traces = [t for t in traces if "RC_MODEL_GATEWAY_OUTAGE" in ((t.decision or {}).get("reason_codes") or [])]
    adapters = IntegrationAdapterRegistry().health_report()
    outages = {
        "model_gateway_outage_active": ModelGateway.is_outage_active(),
        "executions_degraded_by_outage": len(outage_traces),
        "degraded_adapters": [a for a in adapters if a.get("status") != "healthy"],
        "adapters_checked": len(adapters),
    }

    open_tasks = db.query(OrchestrationTask).filter(OrchestrationTask.tenant_id == tenant_id, OrchestrationTask.status.in_(["dlq", "waiting_human", "rework_required"])).count()

    return {
        "kpis": kpis,
        "failed_agent_executions": failed,
        "stuck_workflows": stuck,
        "claims_breaching_sla": sla_breaches,
        "human_approval_backlog": approval_backlog,
        "fraud_investigation_queue": fraud_queue,
        "payment_reconciliation_failures": recon_failures,
        "model_api_outages": outages,
        "cost": _cost_rollup(rows),
        "orchestration_tasks_needing_attention": open_tasks,
        "stuck_threshold_hours": STUCK_AFTER_HOURS,
        "is_synthetic_demo": True,
        "note": NOTE,
        "generated_at": now.isoformat(),
    }


def list_traces(
    db: Session,
    *,
    tenant_id: str,
    claim_id: str | None = None,
    agent_name: str | None = None,
    outcome: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    q = db.query(AgentExecutionRecord).filter(AgentExecutionRecord.tenant_id == tenant_id)
    if claim_id:
        q = q.filter(AgentExecutionRecord.claim_id == claim_id)
    if agent_name:
        q = q.filter(AgentExecutionRecord.agent_name == agent_name)
    if outcome:
        q = q.filter(AgentExecutionRecord.outcome == outcome)
    rows = q.order_by(AgentExecutionRecord.created_at.desc()).limit(max(1, min(limit, 500))).all()
    return [serialize_trace(r) for r in rows]


__all__ = ["build_operations_dashboard", "list_traces", "serialize_trace"]
