"""Portal section data. Every figure is computed live from the database over DEMO / SYNTHETIC data."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from services.analytics.kpis import kpi_framework
from services.claims.models import (
    AgentExecutionRecord,
    Approval,
    Claim,
    ClaimTask,
    DamageAssessment,
    Estimate,
    Evidence,
    ExtractedFact,
    FraudAlert,
    Payment,
    Settlement,
)
from services.evaluation.cost_latency import cost_latency_report
from services.evaluation.overrides import human_override_report
from services.rules_engine.product import product_framework

NOTE = "Computed live from DEMO / SYNTHETIC data. Targets are illustrative."
LOW_CONFIDENCE = 0.8
OPEN_ALERT_STATUSES = {"new", "assigned", "investigating"}
HEADLINE_KPIS = ("avg_processing_time", "stp_rate", "sla_breach_rate", "human_touchpoints", "ai_cost_per_claim", "rework_rate")


def _num(value: Any) -> float:
    return float(Decimal(str(value or 0)))


def _age_hours(dt: datetime | None) -> float:
    if dt is None:
        return 0.0
    aware = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    return round((datetime.now(timezone.utc) - aware).total_seconds() / 3600, 1)


def _numbers(db: Session, tenant_id: str) -> dict[str, str]:
    return {c.id: c.claim_number for c in db.query(Claim).filter(Claim.tenant_id == tenant_id).all()}


def executive_dashboard(db: Session, tenant_id: str) -> dict[str, Any]:
    claims = db.query(Claim).filter(Claim.tenant_id == tenant_id).all()
    kpis = {k["id"]: k for k in kpi_framework(db, tenant_id)["kpis"]}
    alerts = db.query(FraudAlert).filter(FraudAlert.tenant_id == tenant_id).all()
    settlements = db.query(Settlement).filter(Settlement.tenant_id == tenant_id).all()
    return {
        "claims_total": len(claims),
        "by_status": dict(Counter(c.status for c in claims)),
        "by_risk_tier": dict(Counter(c.risk_tier or "UNSCORED" for c in claims)),
        "by_claim_type": dict(Counter(c.claim_type for c in claims)),
        "settlement_net_total_inr": round(sum(_num(s.net_payable_inr) for s in settlements), 2),
        "fraud_alerts_open": sum(1 for a in alerts if a.status in OPEN_ALERT_STATUSES),
        "fraud_alerts_total": len(alerts),
        "human_tasks_open": db.query(ClaimTask).filter(ClaimTask.tenant_id == tenant_id, ClaimTask.status.in_(["open", "waiting_human"])).count(),
        "headline_kpis": [kpis[k] for k in HEADLINE_KPIS if k in kpis],
        "note": NOTE,
    }


def evidence_intelligence(db: Session, tenant_id: str) -> dict[str, Any]:
    evidence = db.query(Evidence).filter(Evidence.tenant_id == tenant_id).all()
    facts = db.query(ExtractedFact).filter(ExtractedFact.tenant_id == tenant_id).all()
    numbers = _numbers(db, tenant_id)
    sha_counts = Counter(e.sha256 for e in evidence)
    confidences = [_num(f.confidence) for f in facts if f.confidence is not None]
    low = sorted((f for f in facts if f.confidence is not None and _num(f.confidence) < LOW_CONFIDENCE), key=lambda f: _num(f.confidence))[:10]
    return {
        "evidence_total": len(evidence),
        "by_doc_type": dict(Counter(e.doc_type for e in evidence)),
        "by_doc_status": dict(Counter(e.doc_status for e in evidence)),
        "image_quality": dict(Counter(e.image_quality_status for e in evidence if e.image_quality_status)),
        "integrity": {
            "duplicate_files": sum(1 for n in sha_counts.values() if n > 1),
            "prompt_injection_flagged": sum(1 for e in evidence if e.prompt_injection_flagged),
            "malware_scan": dict(Counter(e.malware_scan_status for e in evidence)),
            "legal_hold": sum(1 for e in evidence if e.legal_hold),
        },
        "extracted_facts": {
            "total": len(facts),
            "avg_confidence": round(sum(confidences) / len(confidences), 3) if confidences else None,
            "by_validation_status": dict(Counter(f.validation_status for f in facts)),
            "low_confidence": [
                {"claim_number": numbers.get(f.claim_id, f.claim_id), "field": f.field_name, "confidence": _num(f.confidence), "validation_status": f.validation_status}
                for f in low
            ],
        },
        "note": NOTE,
    }


def damage_assessment(db: Session, tenant_id: str) -> dict[str, Any]:
    rows = db.query(DamageAssessment).filter(DamageAssessment.tenant_id == tenant_id).all()
    estimates = db.query(Estimate).filter(Estimate.tenant_id == tenant_id).all()
    numbers = _numbers(db, tenant_id)
    conf = [_num(r.confidence) for r in rows if r.confidence is not None]
    flagged = [e for e in estimates if e.anomalies]
    return {
        "components_assessed": len(rows),
        "by_damage_class": dict(Counter(r.damage_class for r in rows if r.damage_class)),
        "by_recommended_action": dict(Counter(r.recommended_action for r in rows if r.recommended_action)),
        "avg_confidence": round(sum(conf) / len(conf), 3) if conf else None,
        "low_confidence_components": sum(1 for c in conf if c < LOW_CONFIDENCE),
        "reviewer_outcomes": dict(Counter(r.reviewer_outcome for r in rows if r.reviewer_outcome)),
        "estimates_total": len(estimates),
        "estimates_with_anomalies": [
            {"claim_number": numbers.get(e.claim_id, e.claim_id), "anomalies": len(e.anomalies), "claimed_inr": _num(e.total_claimed_inr), "approved_inr": _num(e.total_approved_inr), "is_supplement": e.is_supplement}
            for e in flagged[:15]
        ],
        "note": NOTE + " The vision model is simulated.",
    }


def settlement_workbench(db: Session, tenant_id: str) -> dict[str, Any]:
    numbers = _numbers(db, tenant_id)
    latest: dict[str, Settlement] = {}
    for s in db.query(Settlement).filter(Settlement.tenant_id == tenant_id).order_by(Settlement.version).all():
        latest[s.claim_id] = s
    payments = db.query(Payment).filter(Payment.tenant_id == tenant_id).all()
    approvals = db.query(Approval).filter(Approval.tenant_id == tenant_id).all()
    return {
        "settlements": [
            {
                "claim_number": numbers.get(s.claim_id, s.claim_id), "claim_id": s.claim_id, "pathway": s.pathway,
                "gross_inr": _num(s.gross_assessed_inr),
                "deductions_inr": round(_num(s.depreciation_deduction_inr) + _num(s.compulsory_excess_inr) + _num(s.voluntary_excess_inr) + _num(s.salvage_deduction_inr), 2),
                "net_inr": _num(s.net_payable_inr), "total_loss": bool(s.is_total_loss), "approval_status": s.approval_status,
            }
            for s in list(latest.values())[:20]
        ],
        "approvals_by_decision": dict(Counter(a.decision for a in approvals)),
        "payments_by_status": dict(Counter(p.status for p in payments)),
        "paid_total_inr": round(sum(_num(p.amount_inr) for p in payments if p.status == "paid"), 2),
        "note": NOTE,
    }


def human_review(db: Session, tenant_id: str) -> dict[str, Any]:
    numbers = _numbers(db, tenant_id)
    pending = db.query(Approval).filter(Approval.tenant_id == tenant_id, Approval.decision == "pending").all()
    tasks = db.query(ClaimTask).filter(ClaimTask.tenant_id == tenant_id, ClaimTask.status.in_(["open", "waiting_human"])).all()
    by_role: dict[str, Counter[str]] = defaultdict(Counter)
    for t in tasks:
        by_role[t.assigned_role or "unassigned"][t.priority or "normal"] += 1
    return {
        "pending_approvals": [
            {"claim_number": numbers.get(a.claim_id, a.claim_id), "claim_id": a.claim_id, "action_type": a.action_type, "amount_inr": _num(a.amount_inr), "age_hours": _age_hours(a.created_at)}
            for a in sorted(pending, key=lambda a: a.created_at)[:20]
        ],
        "open_tasks": [
            {"claim_number": numbers.get(t.claim_id, t.claim_id), "claim_id": t.claim_id, "title": t.title, "assigned_role": t.assigned_role, "priority": t.priority, "reason_code": t.reason_code, "created_by_agent": t.created_by_agent, "age_hours": _age_hours(t.created_at)}
            for t in sorted(tasks, key=lambda t: t.created_at)[:30]
        ],
        "workload_by_role": {role: dict(c) for role, c in sorted(by_role.items())},
        "overrides": human_override_report(db, tenant_id),
        "note": NOTE,
    }


def performance(db: Session, tenant_id: str) -> dict[str, Any]:
    traces = db.query(AgentExecutionRecord).filter(AgentExecutionRecord.tenant_id == tenant_id).all()
    per: dict[str, list[AgentExecutionRecord]] = defaultdict(list)
    for t in traces:
        per[t.agent_name].append(t)
    agents = []
    for name, rows in sorted(per.items()):
        confs = [_num(r.confidence) for r in rows if r.confidence is not None]
        agents.append({
            "agent": name, "executions": len(rows),
            "success_rate_pct": round(100.0 * sum(1 for r in rows if r.outcome == "success") / len(rows), 1),
            "escalation_rate_pct": round(100.0 * sum(1 for r in rows if r.outcome == "escalated_to_human") / len(rows), 1),
            "failure_rate_pct": round(100.0 * sum(1 for r in rows if r.outcome in {"failed", "timeout"}) / len(rows), 1),
            "avg_confidence": round(sum(confs) / len(confs), 3) if confs else None,
        })
    return {
        "agents": agents,
        "cost_latency": cost_latency_report(db, tenant_id),
        "overrides": human_override_report(db, tenant_id),
        "kpi_framework": kpi_framework(db, tenant_id),
        "quality_gate": "Accuracy, safety, fairness and hallucination results come from the CI release gate (python -m evals.gate). See docs/responsible-ai.md.",
        "note": NOTE,
    }


def guided_demos(db: Session, tenant_id: str) -> dict[str, Any]:
    spec = product_framework(db)
    by_number = {c.claim_number: c for c in db.query(Claim).filter(Claim.tenant_id == tenant_id).all()}
    demos = []
    for d in spec["demos"]:
        claim = by_number.get(d["claim_number"])
        demos.append({
            **d,
            "available": claim is not None,
            "claim_id": claim.id if claim else None,
            "status": claim.status if claim else None,
            "risk_tier": claim.risk_tier if claim else None,
            "claim_360_path": f"/claims/{claim.id}/claim-360" if claim else None,
        })
    return {"demos": demos, "note": "Demo claims are seeded synthetic data. Demos 2 to 5 are seeded with one agent run that stops at the first human gate. Demo 1 is seeded already approved. Start a new run with POST /api/v1/claims/{id}/orchestrate, or use scripts/od_claim_demo.py. Run the seed reset to restore the claims."}


def capability_model(db: Session) -> dict[str, Any]:
    spec = product_framework(db)
    return {
        "vision": "An autonomous, governed motor insurance claims operating platform.",
        "capability_model": spec["capability_model"],
        "assessment": spec["assessment"],
        "portal_sections": spec["portal_sections"],
        "note": "States are set by the team and checked by tests against the repository. Partial means built with a simulated or sandbox dependency.",
    }
