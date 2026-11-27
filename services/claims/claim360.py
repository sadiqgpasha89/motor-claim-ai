"""Claim 360: one screen answering what happened, what is happening, what is blocked and what to do next (item 19)."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from packages.security.auth import Role, UserContext
from services.agent_runtime.contracts import AGENT_CAPABILITY_CONTRACTS, ORCHESTRATION_ORDER
from services.claims.models import (
    AgentExecutionRecord,
    Approval,
    AuditEvent,
    Claim,
    ClaimTask,
    Customer,
    DeadLetterRecord,
    Evidence,
    ExtractedFact,
    FraudAlert,
    Payment,
    Policy,
    Settlement,
    SLATimer,
    Vehicle,
)
from services.claims.state_machine import to_canonical_state
from services.observability.operations import serialize_trace
from services.sla.service import build_snapshot, claim_sla_view
from services.workflow.complexity import predict_complexity
from services.workflow.sla_engine import compute_timer_status

OPEN_TASK_STATUSES = {"open", "waiting_human"}
OPEN_FRAUD = {"new", "assigned", "investigating"}
LOW_CONFIDENCE = Decimal("0.700")


def _money(v: Any) -> str:
    return str(Decimal(str(v or 0)).quantize(Decimal("0.01")))


def _timeline(traces: list[AgentExecutionRecord], claim: Claim, audits: list[AuditEvent]) -> list[dict[str, Any]]:
    """Merge agent executions, state transitions and human/audit events into one chronological feed."""
    items: list[dict[str, Any]] = []
    for t in traces:
        when = t.started_at or t.created_at
        items.append({"at": when.isoformat(), "kind": "agent_execution", "title": f"{t.agent_name} → {t.outcome}",
                      "detail": t.final_action, "agent_name": t.agent_name, "outcome": t.outcome,
                      "latency_ms": t.duration_ms, "trace_id": t.id})
    for h in (claim.workflow_state or {}).get("state_history", []):
        items.append({"at": h.get("timestamp", ""), "kind": "state_transition", "title": f"{h.get('from_state')} → {h.get('to_state')}",
                      "detail": h.get("reason", ""), "trigger_event": h.get("trigger_event")})
    for a in audits:
        if a.action in {"APPROVAL_DECIDED", "WORKFLOW_RESUMED", "WORKFLOW_PAUSED"} or a.actor_role not in {"orchestrator", "system"}:
            items.append({"at": a.created_at.isoformat(), "kind": "human_or_audit", "title": a.action,
                          "detail": f"{a.actor_role} {a.outcome}", "actor_role": a.actor_role})
    return sorted(items, key=lambda i: i["at"])


def _sla_risk(db: Session, claim: Claim) -> dict[str, Any]:
    """Predicted SLA risk per clock. Taken from the SLA engine, not recomputed here."""
    view = claim_sla_view(build_snapshot(db, claim.tenant_id, claim_ids=[claim.id]), claim.id)
    preds = view["predictions"]
    return {"catalogue_version": view["catalogue_version"], "predictions": preds, "signals": view["signals"]}


def build_claim_360(db: Session, claim: Claim, user: UserContext, *, include_fraud: bool) -> dict[str, Any]:
    tid, cid = claim.tenant_id, claim.id
    wf = claim.workflow_state or {}
    customer = db.query(Customer).filter(Customer.id == claim.customer_id).first() if claim.customer_id else None
    policy = db.query(Policy).filter(Policy.id == claim.policy_id).first() if claim.policy_id else None
    vehicle = db.query(Vehicle).filter(Vehicle.id == claim.vehicle_id).first() if claim.vehicle_id else None
    traces = db.query(AgentExecutionRecord).filter(AgentExecutionRecord.claim_id == cid, AgentExecutionRecord.tenant_id == tid).order_by(AgentExecutionRecord.created_at.asc()).all()
    audits = db.query(AuditEvent).filter(AuditEvent.claim_id == cid, AuditEvent.tenant_id == tid).order_by(AuditEvent.created_at.asc()).all()
    evidence = db.query(Evidence).filter(Evidence.claim_id == cid, Evidence.tenant_id == tid).all()
    facts = db.query(ExtractedFact).filter(ExtractedFact.claim_id == cid, ExtractedFact.tenant_id == tid).all()
    settlements = db.query(Settlement).filter(Settlement.claim_id == cid, Settlement.tenant_id == tid).order_by(Settlement.created_at.asc()).all()
    approvals = db.query(Approval).filter(Approval.claim_id == cid, Approval.tenant_id == tid).order_by(Approval.created_at.asc()).all()
    payments = db.query(Payment).filter(Payment.claim_id == cid, Payment.tenant_id == tid).all()
    timers = db.query(SLATimer).filter(SLATimer.claim_id == cid, SLATimer.tenant_id == tid).all()
    tasks = db.query(ClaimTask).filter(ClaimTask.claim_id == cid, ClaimTask.tenant_id == tid, ClaimTask.status.in_(OPEN_TASK_STATUSES)).all()
    dlq = db.query(DeadLetterRecord).filter(DeadLetterRecord.claim_id == cid, DeadLetterRecord.tenant_id == tid, DeadLetterRecord.status == "open").all()
    alerts = db.query(FraudAlert).filter(FraudAlert.claim_id == cid, FraudAlert.tenant_id == tid).all() if include_fraud else []

    latest: dict[str, AgentExecutionRecord] = {}
    for t in traces:
        latest[t.agent_name] = t
    statuses = wf.get("stage_statuses", {})
    nodes = []
    for order, name in enumerate(ORCHESTRATION_ORDER, start=1):
        spec = AGENT_CAPABILITY_CONTRACTS[name]
        last = latest.get(name)
        nodes.append({"order": order, "agent_name": name, "display_name": spec.display_name, "stage": spec.stage,
                      "depends_on": spec.depends_on, "status": statuses.get(name, "pending"),
                      "last_outcome": last.outcome if last else None, "last_latency_ms": last.duration_ms if last else None,
                      "last_confidence": float(last.confidence) if last and last.confidence is not None else None})

    pending_approvals = [a for a in approvals if a.decision == "pending"]
    open_alerts = [a for a in alerts if a.status in OPEN_FRAUD]
    paused = bool(wf.get("paused"))
    blockers: list[dict[str, str]] = []
    if paused:
        blockers.append({"code": "WORKFLOW_PAUSED", "why": wf.get("pause_reason", "Workflow paused for manual review"), "owner": "claims_handler"})
    if dlq:
        blockers.append({"code": "DEAD_LETTER_OPEN", "why": "; ".join(d.failure_reason for d in dlq)[:240], "owner": "claims_manager"})
    if pending_approvals:
        blockers.append({"code": "APPROVAL_PENDING", "why": f"{len(pending_approvals)} approval(s) await an independent checker", "owner": "claims_manager"})
    if claim.missing_documents:
        blockers.append({"code": "DOCUMENTS_MISSING", "why": "Missing: " + ", ".join(map(str, claim.missing_documents)), "owner": "policyholder"})
    if open_alerts:
        blockers.append({"code": "FRAUD_REVIEW_OPEN", "why": f"{len(open_alerts)} fraud signal(s) need SIU review", "owner": "siu_investigator"})
    for task in tasks:
        blockers.append({"code": f"TASK_{task.task_type}".upper(), "why": task.title, "owner": task.assigned_role})

    approver_roles = {Role.CLAIMS_MANAGER, Role.FINANCE_APPROVER, Role.LEGAL_TP, Role.ADMIN}
    action_needed = any(task.assigned_role == user.role.value for task in tasks) or (bool(pending_approvals) and user.role in approver_roles)

    done = [t.agent_name for t in traces if t.outcome == "success"]
    found: list[str] = []
    for t in traces:
        for code in ((t.decision or {}).get("reason_codes") or [])[:2]:
            found.append(f"{t.agent_name}: {code}")
    low_conf = [f"{f.field_name} ({f.confidence})" for f in facts if Decimal(str(f.confidence)) < LOW_CONFIDENCE]

    canonical = to_canonical_state(claim.status)
    answers = {
        "what_has_happened": [h.get("reason", "") for h in wf.get("state_history", [])][-5:] or ["Claim registered"],
        "what_is_happening_now": f"State {canonical}" + (" (workflow paused)" if paused else "") + f"; queue {claim.queue_name}",
        "what_is_blocked": [b["code"] for b in blockers],
        "why_blocked": [b["why"] for b in blockers],
        "what_did_ai_do": [f"{t.agent_name}: {t.final_action} ({t.outcome})" for t in traces if t.outcome != "blocked"][-8:],
        "what_did_ai_find": (found[:8] + ([f"Low-confidence extraction: {', '.join(low_conf)}"] if low_conf else [])),
        "next_action": claim.next_expected_action,
        "do_i_need_to_act": {"required": action_needed, "role": user.role.value,
                             "reason": "Approval or task assigned to your role" if action_needed else "No action assigned to your role"},
    }

    return {
        "claim_id": cid,
        "overview": {
            "claim_number": claim.claim_number, "status": claim.status, "canonical_state": canonical,
            "claim_type": claim.claim_type, "peril_cause": claim.peril_cause, "risk_tier": claim.risk_tier,
            "operational_path": claim.operational_path, "severity_band": claim.severity_band,
            "estimated_loss_inr": _money(claim.estimated_loss_inr), "queue_name": claim.queue_name,
            "policy": {"policy_number": policy.policy_number, "idv_inr": _money(policy.idv_inr), "status": policy.status} if policy else None,
            "vehicle": {"registration": vehicle.registration_number, "make": vehicle.make, "model": vehicle.model, "year": vehicle.year, "is_ev": vehicle.is_ev} if vehicle else None,
            "customer": {"name": customer.name, "phone": customer.phone_masked, "email": customer.email_masked, "language": customer.preferred_language} if customer else None,
            "paused": paused,
            "sla": [{"stage": t.stage, "status": compute_timer_status(t.due_at, t.completed_at, t.paused), "due_at": t.due_at.isoformat()} for t in timers],
        },
        "answers": answers,
        "blockers": blockers,
        "intelligence": {
            "complexity": predict_complexity(db, claim),
            "sla_risk": _sla_risk(db, claim),
        },
        "workflow": nodes,
        "execution_timeline": _timeline(traces, claim, audits),
        "agent_executions": [serialize_trace(t) for t in traces],
        "agent_summary": {
            "executions": len(traces),
            "total_cost_inr": _money(sum((Decimal(str(t.cost_inr or 0)) for t in traces), Decimal("0"))),
            "total_tokens": sum(t.tokens_input + t.tokens_output for t in traces),
            "human_interventions": sum(1 for t in traces if t.human_intervention),
            "completed_agents": done,
        },
        "evidence": {
            "documents": [{"id": e.id, "doc_type": e.doc_type, "status": e.doc_status, "filename": e.filename, "sha256": e.sha256,
                           "malware_scan": e.malware_scan_status, "prompt_injection_flagged": e.prompt_injection_flagged,
                           "legal_hold": e.legal_hold, "image_quality": e.image_quality_status} for e in evidence],
            "extracted_facts": [{"evidence_id": f.evidence_id, "field": f.field_name, "value": f.verified_value or f.extracted_value,
                                 "confidence": float(f.confidence), "validation_status": f.validation_status} for f in facts],
            "integrity": "sha256 recorded per document",
        },
        "settlement_and_approvals": {
            "settlements": [{"id": s.id, "version": s.version, "gross_assessed_inr": _money(s.gross_assessed_inr),
                             "depreciation_inr": _money(s.depreciation_deduction_inr), "compulsory_excess_inr": _money(s.compulsory_excess_inr),
                             "voluntary_excess_inr": _money(s.voluntary_excess_inr), "salvage_inr": _money(s.salvage_deduction_inr),
                             "net_payable_inr": _money(s.net_payable_inr), "approval_status": s.approval_status,
                             "rule_versions": s.rule_versions} for s in settlements],
            "approvals": [{"id": a.id, "action_type": a.action_type, "amount_inr": _money(a.amount_inr), "decision": a.decision,
                           "maker_user_id": a.maker_user_id, "checker_user_id": a.checker_user_id,
                           "authority_rule_version": a.authority_rule_version} for a in approvals],
            "payments": [{"id": p.id, "status": p.status, "amount_inr": _money(p.amount_inr), "payee_type": p.payee_type,
                          "bank_account": p.bank_account_masked, "gateway_reference": p.gateway_reference} for p in payments],
        },
        "fraud": ({"visible": True, "alerts": [{"indicator_code": a.indicator_code, "severity_band": a.severity_band, "status": a.status,
                                                 "title": a.title} for a in alerts]} if include_fraud else {"visible": False}),
        "is_synthetic_demo": True,
    }
