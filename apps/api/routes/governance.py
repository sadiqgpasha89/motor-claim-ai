from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.schemas import AiOutageToggleRequest, DLQActionRequest, RuleSimulateRequest
from packages.contracts.errors import DomainError, ErrorCode
from packages.security.auth import INTERNAL_ROLES, Role, UserContext, get_current_user, require_roles
from services.agent_runtime.contracts import AGENT_CAPABILITY_CONTRACTS, OPERATIONS_AGENTS, ORCHESTRATION_ORDER
from services.agent_runtime.gateway import ModelGateway
from services.claims.audit import record_audit_event
from services.claims.db import get_db
from services.claims.models import (
    Claim,
    DeadLetterRecord,
    FraudAlert,
    OutboxEvent,
    Provider,
    RuleVersion,
    Settlement,
    SLATimer,
    User,
)
from services.integrations.adapters import IntegrationAdapterRegistry
from services.rules_engine.knowledge import HybridPolicyRetriever, load_rate_card
from services.rules_engine.loader import sync_rules_to_db
from services.workflow.ecosystem import build_ecosystem_dashboard, serialize_provider_scorecard
from services.workflow.orchestrator import ClaimOrchestrator
from services.workflow.sla_engine import compute_timer_status, sweep_sla_breaches
from services.workflow.state_specs import describe_workflow_model

router = APIRouter(prefix="/api/v1", tags=["governance-and-operations"])


@router.get("/providers")
def list_providers(
    provider_type: str | None = None,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Provider).filter(Provider.tenant_id == user.tenant_id)
    if provider_type:
        q = q.filter(Provider.provider_type == provider_type)
    items = q.order_by(Provider.quality_score.desc()).all()
    return {"items": [serialize_provider_scorecard(p) for p in items]}


@router.get("/ecosystem/dashboard")
def get_ecosystem_dashboard(
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return build_ecosystem_dashboard(db, user.tenant_id)


@router.get("/rules")
def list_rules(
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sync_rules_to_db(db)
    rules = db.query(RuleVersion).order_by(RuleVersion.rule_id.asc()).all()
    return {
        "items": [
            {
                "id": r.id,
                "rule_id": r.rule_id,
                "version": r.version,
                "jurisdiction": r.jurisdiction,
                "title": r.title,
                "source_reference": r.source_reference,
                "owner": r.owner,
                "status": r.status,
                "effective_from": r.effective_from.isoformat(),
                "approved_by": r.approved_by,
                "payload": r.payload,
            }
            for r in rules
        ]
    }


@router.post("/rules/{rule_id}/simulate")
def simulate_rule(
    rule_id: str,
    body: RuleSimulateRequest,
    user: UserContext = Depends(require_roles(Role.CLAIMS_MANAGER, Role.AUDITOR, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    claims = db.query(Claim).filter(Claim.tenant_id == user.tenant_id).all()
    current_survey_count = sum(1 for c in claims if c.requires_mandatory_survey)
    proposed_survey_count = sum(
        1
        for c in claims
        if Decimal(str(c.estimated_loss_inr)) >= body.proposed_threshold_inr
        or c.peril_cause in {"theft", "fire", "flood", "total_loss"}
        or c.injury_or_fatality
        or c.ev_battery_impacted
    )
    return {
        "rule_id": rule_id,
        "evaluated_synthetic_claims": len(claims),
        "current_mandatory_survey_count": current_survey_count,
        "proposed_mandatory_survey_count": proposed_survey_count,
        "delta": proposed_survey_count - current_survey_count,
        "sample_threshold_check": {
            "sample_loss_inr": str(body.sample_estimated_loss_inr),
            "proposed_threshold_inr": str(body.proposed_threshold_inr),
            "would_require_survey": body.sample_estimated_loss_inr >= body.proposed_threshold_inr,
        },
        "note": "Simulation only; production publication requires compliance sign-off.",
    }


@router.post("/rules/{rule_id}/publish")
def publish_rule(
    rule_id: str,
    user: UserContext = Depends(require_roles(Role.AUDITOR, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    rule = db.query(RuleVersion).filter(RuleVersion.rule_id == rule_id).first()
    if not rule:
        raise DomainError(ErrorCode.NOT_FOUND, f"Rule '{rule_id}' not found", status_code=404)
    rule.status = "published"
    rule.approved_by = f"{user.name} ({user.role.value})"
    record_audit_event(
        db,
        tenant_id=user.tenant_id,
        claim_id=None,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="RULE_PUBLISHED",
        object_type="rule_version",
        object_id=rule.id,
        details={"rule_id": rule_id, "version": rule.version},
    )
    db.commit()
    return {"status": "published", "rule_id": rule.rule_id, "version": rule.version, "approved_by": rule.approved_by}


@router.get("/knowledge/search")
def search_policy_knowledge(
    q: str,
    top_k: int = 4,
    user: UserContext = Depends(get_current_user),
):
    retriever = HybridPolicyRetriever()
    return {"query": q, "results": retriever.search(q, top_k=top_k), "rate_card": load_rate_card()}


@router.get("/operations/sla")
def get_sla_dashboard(
    user: UserContext = Depends(require_roles(Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.AUDITOR, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    timers = db.query(SLATimer).filter(SLATimer.tenant_id == user.tenant_id).all()
    rows = []
    breached = 0
    warning = 0
    for t in timers:
        status = compute_timer_status(t.due_at, t.completed_at, t.paused)
        if status == "breached":
            breached += 1
        elif status == "warning":
            warning += 1
        rows.append(
            {
                "id": t.id,
                "claim_id": t.claim_id,
                "stage": t.stage,
                "status": status,
                "started_at": t.started_at.isoformat(),
                "due_at": t.due_at.isoformat(),
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                "owner_role": t.owner_role,
                "daily_penalty_inr": str(t.daily_penalty_inr),
            }
        )
    return {"summary": {"total": len(rows), "breached": breached, "warning": warning}, "timers": rows}


@router.get("/operations/integrations")
def get_integrations_health(
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    adapters = IntegrationAdapterRegistry().health_report()
    outbox = (
        db.query(OutboxEvent)
        .filter(OutboxEvent.tenant_id == user.tenant_id)
        .order_by(OutboxEvent.created_at.desc())
        .limit(25)
        .all()
    )
    return {
        "adapters": adapters,
        "ai_outage_simulated": ModelGateway.is_outage_active(),
        "outbox_events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "aggregate_id": e.aggregate_id,
                "status": e.status,
                "retry_count": e.retry_count,
                "created_at": e.created_at.isoformat(),
            }
            for e in outbox
        ],
    }


@router.post("/operations/ai-outage-toggle")
def toggle_ai_outage(
    body: AiOutageToggleRequest,
    user: UserContext = Depends(require_roles(Role.ADMIN, Role.CLAIMS_MANAGER)),
    db: Session = Depends(get_db),
):
    ModelGateway.set_simulated_outage(body.enabled)
    record_audit_event(
        db,
        tenant_id=user.tenant_id,
        claim_id=None,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="AI_OUTAGE_SIMULATION_TOGGLED",
        object_type="model_gateway",
        object_id="default",
        details={"enabled": body.enabled},
    )
    db.commit()
    return {"ai_outage_simulated": ModelGateway.is_outage_active()}


@router.post("/operations/outbox/{event_id}/retry")
def retry_outbox_event(
    event_id: str,
    user: UserContext = Depends(require_roles(Role.ADMIN, Role.CLAIMS_MANAGER)),
    db: Session = Depends(get_db),
):
    evt = db.query(OutboxEvent).filter(OutboxEvent.id == event_id, OutboxEvent.tenant_id == user.tenant_id).first()
    if not evt:
        raise DomainError(ErrorCode.NOT_FOUND, "Outbox event not found", status_code=404)
    evt.retry_count += 1
    evt.status = "published_mock"
    evt.last_error = None
    db.commit()
    return {"id": evt.id, "status": evt.status, "retry_count": evt.retry_count}


@router.get("/operations/analytics")
def get_analytics(
    user: UserContext = Depends(require_roles(Role.CLAIMS_MANAGER, Role.AUDITOR, Role.ADMIN, Role.CLAIMS_HANDLER)),
    db: Session = Depends(get_db),
):
    claims = db.query(Claim).filter(Claim.tenant_id == user.tenant_id).all()
    alerts = db.query(FraudAlert).filter(FraudAlert.tenant_id == user.tenant_id).all()
    settlements = db.query(Settlement).filter(Settlement.tenant_id == user.tenant_id).all()
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_risk_tier: dict[str, int] = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
    by_operational_path: dict[str, int] = {"fast_track": 0, "standard": 0, "complex_investigation": 0}
    for c in claims:
        by_status[c.status] = by_status.get(c.status, 0) + 1
        by_type[c.claim_type] = by_type.get(c.claim_type, 0) + 1
        rt = (c.risk_tier or "MEDIUM").upper()
        by_risk_tier[rt] = by_risk_tier.get(rt, 0) + 1
        op = c.operational_path or "standard"
        by_operational_path[op] = by_operational_path.get(op, 0) + 1

    total_net_inr = sum((Decimal(str(s.net_payable_inr)) for s in settlements), Decimal("0.00"))
    false_positives = sum(1 for a in alerts if a.status == "not_substantiated")
    substantiated = sum(1 for a in alerts if a.status == "substantiated")
    return {
        "total_claims": len(claims),
        "by_status": by_status,
        "by_claim_type": by_type,
        "by_risk_tier": by_risk_tier,
        "by_operational_path": by_operational_path,
        "total_fraud_alerts": len(alerts),
        "fraud_substantiated": substantiated,
        "fraud_not_substantiated": false_positives,
        "total_recommended_settlement_inr": str(total_net_inr),
        "is_synthetic_demo": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/agents/contracts")
def list_agent_contracts(user: UserContext = Depends(get_current_user)):
    return {
        "total_agents": len(AGENT_CAPABILITY_CONTRACTS),
        "orchestration_order": ORCHESTRATION_ORDER,
        "operations_agents": OPERATIONS_AGENTS,
        "contracts": [AGENT_CAPABILITY_CONTRACTS[name].model_dump() for name in [*ORCHESTRATION_ORDER, *OPERATIONS_AGENTS]],
    }


@router.get("/orchestration/workflow-model")
def get_orchestration_workflow_model(user: UserContext = Depends(get_current_user)):
    return describe_workflow_model()


@router.get("/orchestration/dlq")
def list_dlq_items(
    claim_id: str | None = None,
    status: str | None = None,
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES)),
    db: Session = Depends(get_db),
):
    q = db.query(DeadLetterRecord).filter(DeadLetterRecord.tenant_id == user.tenant_id)
    if claim_id:
        q = q.filter(DeadLetterRecord.claim_id == claim_id)
    if status:
        q = q.filter(DeadLetterRecord.status == status)
    items = q.order_by(DeadLetterRecord.created_at.desc()).all()
    return {
        "total": len(items),
        "items": [
            {
                "id": d.id,
                "claim_id": d.claim_id,
                "task_id": d.task_id,
                "task_key": d.task_key,
                "agent_or_service": d.agent_or_service,
                "state_at_failure": d.state_at_failure,
                "error_code": d.error_code,
                "failure_reason": d.failure_reason,
                "attempt_count": d.attempt_count,
                "retry_history": d.retry_history,
                "status": d.status,
                "resolved_by": d.resolved_by,
                "resolution_notes": d.resolution_notes,
                "created_at": d.created_at.isoformat(),
                "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None,
            }
            for d in items
        ],
    }


@router.post("/orchestration/dlq/{dlq_id}/replay")
def replay_dlq_record(
    dlq_id: str,
    body: DLQActionRequest = DLQActionRequest(),
    user: UserContext = Depends(require_roles(Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    dlq = (
        db.query(DeadLetterRecord)
        .filter(DeadLetterRecord.id == dlq_id, DeadLetterRecord.tenant_id == user.tenant_id)
        .first()
    )
    if not dlq:
        raise DomainError(ErrorCode.NOT_FOUND, "Dead-letter record not found", status_code=404)
    orch = ClaimOrchestrator(db, user)
    res = orch.replay_dlq_item(dlq, resolution_notes=body.resolution_notes)
    db.commit()
    return res


@router.post("/orchestration/dlq/{dlq_id}/compensate")
def compensate_dlq_record(
    dlq_id: str,
    body: DLQActionRequest = DLQActionRequest(),
    user: UserContext = Depends(require_roles(Role.CLAIMS_MANAGER, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    dlq = (
        db.query(DeadLetterRecord)
        .filter(DeadLetterRecord.id == dlq_id, DeadLetterRecord.tenant_id == user.tenant_id)
        .first()
    )
    if not dlq:
        raise DomainError(ErrorCode.NOT_FOUND, "Dead-letter record not found", status_code=404)
    claim = db.query(Claim).filter(Claim.id == dlq.claim_id).first()
    if not claim:
        raise DomainError(ErrorCode.NOT_FOUND, "Claim not found", status_code=404)
    orch = ClaimOrchestrator(db, user)
    res = orch.run_compensation(claim, trigger_reason=f"DLQ {dlq.task_key}: {body.resolution_notes}")
    db.commit()
    return res


@router.post("/orchestration/sla/sweep")
def run_sla_sweep(
    claim_id: str | None = None,
    user: UserContext = Depends(require_roles(Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.AUDITOR, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    res = sweep_sla_breaches(db, tenant_id=user.tenant_id, claim_id=claim_id)
    db.commit()
    return res


@router.get("/auth/users")
def list_demo_users(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.role.asc()).all()
    return {
        "items": [
            {
                "id": u.id,
                "email": u.email,
                "name": u.name,
                "role": u.role,
                "tenant_id": u.tenant_id,
                "partner_id": u.partner_id,
                "branch": u.branch,
            }
            for u in users
        ]
    }
