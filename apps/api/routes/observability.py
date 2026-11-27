"""Agent observability, operations console and Claim 360 endpoints (feedback items 16 and 19)."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from packages.contracts.errors import DomainError, ErrorCode
from packages.security.auth import (
    INTERNAL_ROLES,
    SIU_ALLOWED_ROLES,
    Role,
    UserContext,
    enforce_claim_abac,
    require_roles,
)
from services.claims.claim360 import build_claim_360
from services.claims.db import get_db
from services.claims.models import AgentExecutionRecord, Approval, Claim, ClaimTask
from services.observability.operations import build_operations_dashboard, list_traces, serialize_trace

router = APIRouter(prefix="/api/v1", tags=["agent-observability"])

OPS_ROLES = (Role.CLAIMS_MANAGER, Role.AUDITOR, Role.ADMIN)
CLAIM_VIEW_ROLES = (*INTERNAL_ROLES, Role.AUDITOR, Role.ADMIN)
APPROVER_ROLES = {Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.LEGAL_TP, Role.FINANCE_APPROVER, Role.ADMIN}


def _claim_for_user(db: Session, claim_id: str, user: UserContext) -> Claim:
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise DomainError(ErrorCode.NOT_FOUND, f"Claim '{claim_id}' not found", status_code=404)
    enforce_claim_abac(user, claim)
    return claim


@router.get("/operations/agent-observability/dashboard")
def agent_observability_dashboard(
    user: UserContext = Depends(require_roles(*OPS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return build_operations_dashboard(db, tenant_id=user.tenant_id)


@router.get("/operations/agent-observability/traces")
def agent_traces(
    claim_id: str | None = None,
    agent_name: str | None = None,
    outcome: str | None = None,
    limit: int = 100,
    user: UserContext = Depends(require_roles(*OPS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = list_traces(db, tenant_id=user.tenant_id, claim_id=claim_id, agent_name=agent_name, outcome=outcome, limit=limit)
    return {"count": len(rows), "traces": rows}


@router.get("/operations/approval-queue")
def approval_queue(
    user: UserContext = Depends(require_roles(*APPROVER_ROLES, Role.AUDITOR)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Human approval backlog. Segregation of duties: a maker never sees `can_decide` for their own approval."""
    claims = {c.id: c for c in db.query(Claim).filter(Claim.tenant_id == user.tenant_id).all()}
    approvals = db.query(Approval).filter(Approval.tenant_id == user.tenant_id, Approval.decision == "pending").order_by(Approval.created_at.asc()).all()
    tasks = (
        db.query(ClaimTask)
        .filter(ClaimTask.tenant_id == user.tenant_id, ClaimTask.status.in_(["open", "waiting_human"]))
        .order_by(ClaimTask.created_at.asc())
        .all()
    )
    interventions = (
        db.query(AgentExecutionRecord)
        .filter(AgentExecutionRecord.tenant_id == user.tenant_id, AgentExecutionRecord.outcome == "escalated_to_human")
        .order_by(AgentExecutionRecord.created_at.desc())
        .limit(50)
        .all()
    )
    open_interventions = [serialize_trace(r) for r in interventions if r.human_intervention and not r.human_intervention.get("resolved")]
    return {
        "pending_approvals": [
            {
                "approval_id": a.id,
                "claim_id": a.claim_id,
                "claim_number": claims[a.claim_id].claim_number if a.claim_id in claims else a.claim_id,
                "action_type": a.action_type,
                "amount_inr": str(Decimal(str(a.amount_inr)).quantize(Decimal("0.01"))),
                "maker_user_id": a.maker_user_id,
                "authority_rule_version": a.authority_rule_version,
                "created_at": a.created_at.isoformat(),
                "can_decide": user.role in APPROVER_ROLES and a.maker_user_id != user.user_id,
            }
            for a in approvals
        ],
        "open_human_tasks": [
            {"task_id": t.id, "claim_id": t.claim_id, "claim_number": claims[t.claim_id].claim_number if t.claim_id in claims else t.claim_id,
             "task_type": t.task_type, "title": t.title, "assigned_role": t.assigned_role, "priority": t.priority,
             "created_by_agent": t.created_by_agent, "status": t.status}
            for t in tasks
        ],
        "agent_escalations_awaiting_human": open_interventions,
        "claims_in_human_review": [
            {"claim_id": c.id, "claim_number": c.claim_number, "next_expected_action": c.next_expected_action}
            for c in claims.values()
            if c.status == "HUMAN_REVIEW"
        ],
    }


@router.get("/claims/{claim_id}/claim-360")
def claim_360(
    claim_id: str,
    user: UserContext = Depends(require_roles(*CLAIM_VIEW_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    claim = _claim_for_user(db, claim_id, user)
    return build_claim_360(db, claim, user, include_fraud=user.role in SIU_ALLOWED_ROLES)


@router.get("/claims/{claim_id}/agent-timeline")
def claim_agent_timeline(
    claim_id: str,
    user: UserContext = Depends(require_roles(*CLAIM_VIEW_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    claim = _claim_for_user(db, claim_id, user)
    view = build_claim_360(db, claim, user, include_fraud=False)
    return {
        "claim_id": claim.id,
        "claim_number": claim.claim_number,
        "workflow": view["workflow"],
        "timeline": view["execution_timeline"],
        "executions": view["agent_executions"],
        "summary": view["agent_summary"],
    }
