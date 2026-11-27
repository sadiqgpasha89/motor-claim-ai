"""Predictive SLA management API.

Read endpoints are open to internal roles. The agent runs in ``recommend`` mode for operational roles, but ``execute``
mode (the only mode that creates tasks or contacts partners) is restricted to the roles named in the SLA catalogue's
``agent_guardrails.execution_roles``; the agent additionally gates every action through ``authorise_action``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from agents.specialists import AGENT_REGISTRY
from apps.api.schemas import SLAAgentRunRequest, SLARulesValidateRequest
from packages.contracts.agents import AgentInvocationRequest
from packages.contracts.errors import DomainError, ErrorCode
from packages.observability.logging import get_correlation_id
from packages.security.auth import INTERNAL_ROLES, UserContext, enforce_claim_abac, require_roles
from services.agent_runtime.actions import ControlledActionExecutor
from services.claims.audit import record_audit_event
from services.claims.db import get_db
from services.claims.models import Claim
from services.sla.portfolio import (
    BAND_ORDER,
    build_dashboard,
    build_insights,
    claim_risk_ranking,
    document_delay_report,
)
from services.sla.rules import SLARulesService, validate_catalogue
from services.sla.service import agent_inputs, build_snapshot, claim_sla_view

router = APIRouter(prefix="/api/v1", tags=["predictive-sla"])

SLA_READ_ROLES = tuple(INTERNAL_ROLES)


def _claim(db: Session, claim_id: str, user: UserContext) -> Claim:
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise DomainError(ErrorCode.NOT_FOUND, f"Claim '{claim_id}' not found", status_code=404)
    enforce_claim_abac(user, claim)
    return claim


def _with_rebalance_flag(inputs: dict[str, Any], raised: set[str]) -> dict[str, Any]:
    """One queue-rebalance approval per queue per run: later claims in the same queue see it as already raised."""
    ctx = inputs.get("queue_context")
    if ctx and ctx.get("queue") in raised:
        inputs = {**inputs, "queue_context": {**ctx, "rebalance_raised": True}}
    return inputs


@router.get("/sla/rules")
def get_sla_rules(user: UserContext = Depends(require_roles(*SLA_READ_ROLES)), db: Session = Depends(get_db)):
    """The versioned SLA rule catalogue: the single source of every SLA value shown or enforced anywhere."""
    return SLARulesService.load(db).public_catalogue()


@router.post("/sla/rules/validate")
def validate_sla_rules(
    body: SLARulesValidateRequest,
    user: UserContext = Depends(require_roles(*SLA_READ_ROLES)),
):
    """Dry-run validation of a draft catalogue (unknown events/actions, bad escalation order, overlapping versions). Never publishes."""
    errors = validate_catalogue(body.catalogue)
    return {"valid": not errors, "errors": errors}


@router.get("/sla/dashboard")
def get_sla_dashboard(user: UserContext = Depends(require_roles(*SLA_READ_ROLES)), db: Session = Depends(get_db)):
    return build_dashboard(build_snapshot(db, user.tenant_id))


@router.get("/sla/predictions")
def get_sla_predictions(
    min_risk_band: str = "watch",
    limit: int = 25,
    user: UserContext = Depends(require_roles(*SLA_READ_ROLES)),
    db: Session = Depends(get_db),
):
    snap = build_snapshot(db, user.tenant_id)
    threshold = BAND_ORDER.get(min_risk_band, BAND_ORDER["watch"])
    items = [r for r in claim_risk_ranking(snap, limit=max(1, min(limit, 100))) if BAND_ORDER.get(r["risk_band"], 9) <= threshold]
    return {"generated_at": snap.now.isoformat(), "model_id": snap.rules.risk_model.get("model_id"), "total": len(items), "items": items}


@router.get("/sla/insights")
def get_sla_insights(user: UserContext = Depends(require_roles(*SLA_READ_ROLES)), db: Session = Depends(get_db)):
    """Breach-prone claims, overloaded surveyors, delaying garages, document delays and queue bottlenecks."""
    return build_insights(build_snapshot(db, user.tenant_id))


@router.get("/claims/{claim_id}/sla")
def get_claim_sla(claim_id: str, user: UserContext = Depends(require_roles(*SLA_READ_ROLES)), db: Session = Depends(get_db)):
    claim = _claim(db, claim_id, user)
    snap = build_snapshot(db, user.tenant_id)  # whole tenant so queue pressure and provider load are real
    return claim_sla_view(snap, claim.id)


@router.post("/sla/agent/run")
def run_sla_agent(
    body: SLAAgentRunRequest,
    user: UserContext = Depends(require_roles(*SLA_READ_ROLES)),
    db: Session = Depends(get_db),
):
    """Run the predictive SLA agent. ``recommend`` is read-only; ``execute`` performs only authorised actions."""
    rules = SLARulesService.load(db)
    guard = rules.guardrails
    allowed_roles = set(guard.get("execution_roles" if body.mode == "execute" else "recommendation_roles", []))
    if user.role.value not in allowed_roles and user.role.value != "admin":
        raise DomainError(
            ErrorCode.NOT_AUTHORISED,
            f"SLA agent '{body.mode}' requires one of: {', '.join(sorted(allowed_roles))}",
            status_code=403,
        )

    snap = build_snapshot(db, user.tenant_id, rules=rules)
    if body.claim_ids:
        target_ids = [cid for cid in body.claim_ids if cid in snap.contexts]
        if len(target_ids) != len(set(body.claim_ids)):
            raise DomainError(ErrorCode.NOT_FOUND, "One or more claims were not found in your tenant", status_code=404)
    else:
        threshold = BAND_ORDER[body.min_risk_band]
        ranked = claim_risk_ranking(snap, limit=body.limit * 4)
        target_ids = [r["claim_id"] for r in ranked if BAND_ORDER.get(r["risk_band"], 9) <= threshold]
        # Claims whose clock is paused on a stale customer document request are low-probability but still need a nudge.
        stale_docs = [r["claim_id"] for r in document_delay_report(snap)["claims"] if r["paused_clocks"] and r["delay_risk"] in {"high", "medium"}]
        target_ids = list(dict.fromkeys([*target_ids, *stale_docs]))[: body.limit]

    agent = AGENT_REGISTRY["sla_intelligence"]
    run_id = f"sla-run-{uuid.uuid4().hex[:10]}"
    results: list[dict[str, Any]] = []
    totals = {"claims": 0, "recommended": 0, "executed": 0, "already_open": 0, "gated_for_approval": 0, "blocked": 0}
    rebalanced_queues: set[str] = set()
    for cid in target_ids:
        claim = snap.contexts[cid].claim
        enforce_claim_abac(user, claim)
        executor = ControlledActionExecutor(db=db, claim=claim, user=user)
        request = AgentInvocationRequest(
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            correlation_id=get_correlation_id(),
            workflow_run_id=run_id,
            actor_user_id=user.user_id,
            actor_role=user.role.value,
            claim_type=claim.claim_type,
            minimised_facts={**_with_rebalance_flag(agent_inputs(snap, cid), rebalanced_queues), "mode": body.mode},
            allowed_tools=sorted(agent.allowed_tools),
        )
        response = agent.execute(request, action_executor=executor)
        res = response.result
        recs = res.get("recommended_actions", [])
        blocked = sum(1 for a in response.actions_executed if a.status == "blocked_policy")
        totals["claims"] += 1
        totals["recommended"] += len(recs)
        rebalanced_queues.update(r["params"]["queue"] for r in recs if r["action"] == "rebalance_queue" and r.get("params", {}).get("queue"))
        totals["executed"] += res.get("executed_count", 0)
        totals["already_open"] += res.get("already_open_count", 0)
        totals["gated_for_approval"] += res.get("gated_count", 0)
        totals["blocked"] += blocked
        if body.mode == "execute" and (res.get("executed_count") or res.get("gated_count")):
            record_audit_event(
                db,
                tenant_id=claim.tenant_id,
                claim_id=claim.id,
                actor_id=f"agent:sla_intelligence/on-behalf-of:{user.user_id}",
                actor_role=user.role.value,
                action="SLA_AGENT_ACTIONS_EXECUTED",
                object_type="sla_agent_run",
                object_id=run_id,
                details={
                    "executed": res.get("executed_count", 0),
                    "gated": res.get("gated_count", 0),
                    "catalogue_version": res.get("catalogue_version"),
                    "actions": [a.action_type for a in response.actions_executed if a.status in {"executed", "gated_human_review"}],
                },
            )
        results.append(
            {
                "claim_id": claim.id,
                "claim_number": claim.claim_number,
                "status": response.status.value,
                "routing_outcome": response.decision.routing_outcome if response.decision else None,
                "explanation": response.decision.explanation if response.decision else None,
                "worst_breach_probability": res.get("worst_breach_probability", 0.0),
                "predictions": res.get("predictions", []),
                "recommended_actions": recs,
                "suppressed": res.get("suppressed", []),
                "actions": [a.model_dump() for a in response.actions_executed],
            }
        )
    if body.mode == "execute":
        db.commit()
    else:
        db.rollback()
    return {
        "run_id": run_id,
        "mode": body.mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "catalogue_version": rules.catalogue_version,
        "model_id": rules.risk_model.get("model_id"),
        "executed_by_role": user.role.value,
        "totals": totals,
        "results": results,
    }
