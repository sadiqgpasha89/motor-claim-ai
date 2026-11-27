"""Platform routes: tool gateway, event bus, recovery, audit integrity, legal hold, retention, MFA, LLM gateway, metrics."""
from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from packages.config import get_settings
from packages.contracts.errors import DomainError, ErrorCode
from packages.security.auth import (
    Role,
    UserContext,
    create_access_token,
    enforce_claim_abac,
    get_current_user,
    require_roles,
)
from packages.security.mfa import demo_secret_for, totp, verify_totp
from services.agent_runtime.llm_gateway import LLMGateway
from services.claims.audit import record_audit_event, verify_audit_chain
from services.claims.db import get_db
from services.claims.models import (
    AgentExecutionRecord,
    Claim,
    DeadLetterRecord,
    EventDelivery,
    OutboxEvent,
    ToolInvocation,
)
from services.claims.retention import purge_expired_evidence, set_legal_hold
from services.evaluation.cost_latency import cost_latency_report
from services.evaluation.overrides import human_override_report
from services.events import consumers  # noqa: F401  (registers the built-in consumers)
from services.events.bus import consumers as registered_consumers
from services.events.bus import dispatch_pending, replay_dead_delivery
from services.integrations.gateway import ToolGateway
from services.integrations.resilience import breaker_snapshots
from services.rules_engine.security import security_controls
from services.workflow.recovery import recover_stalled_workflows

router = APIRouter(prefix="/api/v1", tags=["platform"])

OPS_ROLES = (Role.CLAIMS_MANAGER, Role.ADMIN)
OPS_READ_ROLES = (Role.CLAIMS_MANAGER, Role.AUDITOR, Role.ADMIN)


class ToolCallRequest(BaseModel):
    agent_name: str = "human"
    params: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    approval_id: str | None = None


class LegalHoldRequest(BaseModel):
    hold: bool
    reason: str = Field(min_length=5)


class PurgeRequest(BaseModel):
    dry_run: bool = True


class MfaVerifyRequest(BaseModel):
    code: str


class LlmTestRequest(BaseModel):
    task: str = "claim_summary"
    facts: dict[str, Any]


def _claim(db: Session, claim_id: str, user: UserContext) -> Claim:
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise DomainError(ErrorCode.NOT_FOUND, f"Claim '{claim_id}' not found", status_code=404)
    enforce_claim_abac(user, claim)
    return claim


# --- tool gateway -----------------------------------------------------------------------------------------------

@router.post("/claims/{claim_id}/tools/{tool}")
def invoke_tool(claim_id: str, tool: str, body: ToolCallRequest, user: UserContext = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    claim = _claim(db, claim_id, user)
    return ToolGateway(db, user, claim).invoke(
        tool, agent_name=body.agent_name, params=body.params, idempotency_key=body.idempotency_key, approval_id=body.approval_id,
    )


@router.get("/operations/tool-policy")
def tool_policy(user: UserContext = Depends(require_roles(*OPS_READ_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"tool_policy": security_controls(db)["tool_policy"], "checks": [
        "user authorised", "agent allowed the tool", "claim in scope", "action allowed in current state",
        "approval present when required", "idempotent", "safe (valid input, rate limit, resilient call)",
    ]}


@router.get("/operations/integration-resilience")
def integration_resilience(user: UserContext = Depends(require_roles(*OPS_READ_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = db.query(ToolInvocation).filter(ToolInvocation.tenant_id == user.tenant_id).all()
    return {"circuit_breakers": breaker_snapshots(), "tool_invocations": dict(Counter(r.status for r in rows))}


# --- event bus --------------------------------------------------------------------------------------------------

@router.post("/operations/events/dispatch")
def dispatch_events(user: UserContext = Depends(require_roles(*OPS_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"consumers": [c.name for c in registered_consumers()], **dispatch_pending(db, tenant_id=user.tenant_id)}


@router.get("/operations/events/deliveries")
def list_deliveries(status: str | None = None, user: UserContext = Depends(require_roles(*OPS_READ_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    q = db.query(EventDelivery).filter(EventDelivery.tenant_id == user.tenant_id)
    if status:
        q = q.filter(EventDelivery.status == status)
    rows = q.order_by(EventDelivery.created_at.desc()).limit(200).all()
    by_status = Counter(r.status for r in db.query(EventDelivery).filter(EventDelivery.tenant_id == user.tenant_id).all())
    return {
        "by_status": dict(by_status),
        "deliveries": [
            {"id": r.id, "outbox_event_id": r.outbox_event_id, "consumer": r.consumer, "status": r.status, "attempts": r.attempts, "last_error": r.last_error}
            for r in rows
        ],
    }


@router.post("/operations/events/deliveries/{delivery_id}/replay")
def replay_delivery(delivery_id: str, user: UserContext = Depends(require_roles(*OPS_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.query(EventDelivery).filter(EventDelivery.id == delivery_id, EventDelivery.tenant_id == user.tenant_id).first()
    if row is None:
        raise DomainError(ErrorCode.NOT_FOUND, "Delivery not found", status_code=404)
    if row.status != "dead":
        raise DomainError(ErrorCode.STATE_CONFLICT, "Only a dead delivery can be replayed.", status_code=409)
    replay_dead_delivery(db, row)
    record_audit_event(
        db, tenant_id=user.tenant_id, claim_id=None, actor_id=user.user_id, actor_role=user.role.value,
        action="EVENT_DELIVERY_REPLAYED", object_type="event_delivery", object_id=row.id, details={"consumer": row.consumer},
    )
    db.commit()
    return {"id": row.id, "status": row.status}


# --- durable workflow recovery ----------------------------------------------------------------------------------

@router.post("/operations/workflows/recover")
def recover_workflows(stall_minutes: int = 15, user: UserContext = Depends(require_roles(*OPS_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    return recover_stalled_workflows(db, user, stall_minutes=stall_minutes)


# --- audit integrity, legal hold, retention ---------------------------------------------------------------------

@router.get("/operations/audit/integrity")
def audit_integrity(user: UserContext = Depends(require_roles(*OPS_READ_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    return verify_audit_chain(db, user.tenant_id)


@router.post("/claims/{claim_id}/legal-hold")
def legal_hold(claim_id: str, body: LegalHoldRequest, user: UserContext = Depends(require_roles(Role.CLAIMS_MANAGER, Role.LEGAL_TP, Role.ADMIN)), db: Session = Depends(get_db)) -> dict[str, Any]:
    claim = _claim(db, claim_id, user)
    result = set_legal_hold(db, claim, hold=body.hold, actor_id=user.user_id, actor_role=user.role.value, reason=body.reason)
    db.commit()
    return result


@router.post("/operations/retention/purge")
def retention_purge(body: PurgeRequest, user: UserContext = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)) -> dict[str, Any]:
    return purge_expired_evidence(db, tenant_id=user.tenant_id, actor_id=user.user_id, actor_role=user.role.value, dry_run=body.dry_run)


# --- MFA step-up ------------------------------------------------------------------------------------------------

@router.post("/auth/mfa/verify")
def mfa_verify(body: MfaVerifyRequest, user: UserContext = Depends(get_current_user)) -> dict[str, Any]:
    cfg = security_controls()["mfa"]
    if not verify_totp(demo_secret_for(user.user_id), body.code, period=int(cfg["totp_period_seconds"]), digits=int(cfg["totp_digits"]), window=int(cfg["totp_window_steps"])):
        raise DomainError(ErrorCode.NOT_AUTHORISED, "The MFA code is not valid.", status_code=401)
    stepped = user.model_copy(update={"mfa_verified": True})
    return {"access_token": create_access_token(stepped), "token_type": "bearer", "mfa_verified": True}


@router.get("/auth/mfa/demo-code")
def mfa_demo_code(user: UserContext = Depends(get_current_user)) -> dict[str, Any]:
    """DEMO only. A real identity provider would send this code to the user's device."""
    if get_settings().app_env.lower() == "production":
        raise DomainError(ErrorCode.NOT_FOUND, "Not available", status_code=404)
    cfg = security_controls()["mfa"]
    return {"code": totp(demo_secret_for(user.user_id), period=int(cfg["totp_period_seconds"]), digits=int(cfg["totp_digits"])), "demo_only": True}


# --- LLM gateway and metrics ------------------------------------------------------------------------------------

@router.post("/operations/llm-gateway/complete")
def llm_gateway_complete(body: LlmTestRequest, user: UserContext = Depends(require_roles(Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.ADMIN))) -> dict[str, Any]:
    res = LLMGateway.complete(task=body.task, facts=body.facts, user_id=user.user_id)
    # The caller gets the redacted text. Rehydrated text stays inside the service.
    return {k: v for k, v in res.items() if k != "text_for_internal_use"}


@router.get("/operations/human-overrides")
def human_overrides(user: UserContext = Depends(require_roles(*OPS_READ_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    return human_override_report(db, user.tenant_id)


@router.get("/operations/cost-latency")
def cost_latency(user: UserContext = Depends(require_roles(*OPS_READ_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    return cost_latency_report(db, user.tenant_id)


@router.get("/operations/metrics", response_class=PlainTextResponse)
def metrics(user: UserContext = Depends(require_roles(*OPS_READ_ROLES)), db: Session = Depends(get_db)) -> str:
    t = user.tenant_id
    lines = ["# HELP motorclaim_claims_total Claims by status", "# TYPE motorclaim_claims_total gauge"]
    for status, n in Counter(c.status for c in db.query(Claim).filter(Claim.tenant_id == t)).items():
        lines.append(f'motorclaim_claims_total{{status="{status}"}} {n}')
    lines += ["# HELP motorclaim_agent_executions_total Agent executions by outcome", "# TYPE motorclaim_agent_executions_total counter"]
    for outcome, n in Counter(r.outcome for r in db.query(AgentExecutionRecord).filter(AgentExecutionRecord.tenant_id == t)).items():
        lines.append(f'motorclaim_agent_executions_total{{outcome="{outcome}"}} {n}')
    lines += ["# HELP motorclaim_event_deliveries_total Event deliveries by status", "# TYPE motorclaim_event_deliveries_total gauge"]
    for status, n in Counter(d.status for d in db.query(EventDelivery).filter(EventDelivery.tenant_id == t)).items():
        lines.append(f'motorclaim_event_deliveries_total{{status="{status}"}} {n}')
    lines += [
        "# TYPE motorclaim_outbox_events_total gauge",
        f"motorclaim_outbox_events_total {db.query(OutboxEvent).filter(OutboxEvent.tenant_id == t).count()}",
        "# TYPE motorclaim_dlq_open_total gauge",
        f"motorclaim_dlq_open_total {db.query(DeadLetterRecord).filter(DeadLetterRecord.tenant_id == t, DeadLetterRecord.status == 'open').count()}",
    ]
    for b in breaker_snapshots():
        lines.append(f'motorclaim_circuit_open{{dependency="{b["name"]}"}} {1 if b["state"] == "open" else 0}')
    return "\n".join(lines) + "\n"
