"""Phase 2 intelligence routes: repair vs replace, benchmarking, fusion, complexity, fraud network."""
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
    enforce_siu_access,
    require_roles,
)
from services.claims.audit import emit_outbox_event, record_audit_event
from services.claims.db import get_db
from services.claims.models import Claim, DamageAssessment, Estimate, EstimateLine, FraudAlert, Policy, Provider
from services.damage_ai.benchmarking import benchmark_lines
from services.damage_ai.multimodal import fuse_modalities
from services.damage_ai.repair_replace import decide_repair_replace
from services.fraud_intelligence.graph import build_weighted_graph
from services.workflow.complexity import complexity_backtest, predict_complexity

router = APIRouter(prefix="/api/v1", tags=["claim-intelligence"])

VIEW_ROLES = (*INTERNAL_ROLES, Role.AUDITOR, Role.ADMIN)
OPS_ROLES = (Role.CLAIMS_MANAGER, Role.AUDITOR, Role.ADMIN)
NETWORK_LEAD_CODE = "NETWORK_RING_LEAD"


def _claim(db: Session, claim_id: str, user: UserContext) -> Claim:
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise DomainError(ErrorCode.NOT_FOUND, f"Claim '{claim_id}' not found", status_code=404)
    enforce_claim_abac(user, claim)
    return claim


def _estimate_lines(db: Session, claim: Claim) -> list[dict[str, Any]]:
    rows = (
        db.query(EstimateLine)
        .join(Estimate, Estimate.id == EstimateLine.estimate_id)
        .filter(Estimate.claim_id == claim.id)
        .all()
    )
    return [
        {"part_code": r.part_code, "line_type": r.line_type, "quantity": r.quantity, "unit_price_inr": str(r.unit_price_inr)}
        for r in rows
    ]


@router.get("/claims/{claim_id}/repair-replace-analysis")
def repair_replace_analysis(
    claim_id: str,
    user: UserContext = Depends(require_roles(*VIEW_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    claim = _claim(db, claim_id, user)
    policy = db.get(Policy, claim.policy_id) if claim.policy_id else None
    rows = db.query(DamageAssessment).filter(DamageAssessment.claim_id == claim.id, DamageAssessment.part_code.isnot(None)).all()
    first = [
        decide_repair_replace(part_code=r.part_code or "", severity=r.damage_severity, confidence=float(r.confidence))
        for r in rows
    ]
    total = sum(
        (Decimal(d["replace_cost_inr"] if d["decision"] != "repair" else d["repair_cost_inr"]) for d in first),
        Decimal("0.00"),
    )
    idv = Decimal(str(policy.idv_inr)) if policy else None
    components = [
        decide_repair_replace(
            part_code=r.part_code or "", severity=r.damage_severity, confidence=float(r.confidence),
            idv_inr=idv, claim_repair_total_inr=total,
        )
        for r in rows
    ]
    return {"claim_id": claim.id, "components": components, "claim_repair_total_inr": str(total), "advisory_only": True}


@router.get("/claims/{claim_id}/estimate-benchmark")
def estimate_benchmark(
    claim_id: str,
    user: UserContext = Depends(require_roles(*VIEW_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    claim = _claim(db, claim_id, user)
    garage = db.get(Provider, claim.assigned_garage_id) if claim.assigned_garage_id else None
    result = benchmark_lines(_estimate_lines(db, claim), city=garage.city if garage else None)
    return {"claim_id": claim.id, "garage_city": garage.city if garage else None, **result}


@router.get("/claims/{claim_id}/multimodal-fusion")
def multimodal_fusion(
    claim_id: str,
    user: UserContext = Depends(require_roles(*VIEW_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    claim = _claim(db, claim_id, user)
    photo_codes = [r.part_code for r in db.query(DamageAssessment).filter(DamageAssessment.claim_id == claim.id).all() if r.part_code]
    est_codes = [ln["part_code"] for ln in _estimate_lines(db, claim) if ln["line_type"] == "part"]
    return {
        "claim_id": claim.id,
        **fuse_modalities(
            photo_part_codes=photo_codes,
            fnol_text=claim.incident_description,
            estimate_part_codes=est_codes,
            vehicle_signals={"airbags_deployed": claim.airbags_deployed},
        ),
    }


@router.get("/claims/{claim_id}/complexity")
def claim_complexity(
    claim_id: str,
    user: UserContext = Depends(require_roles(*VIEW_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return predict_complexity(db, _claim(db, claim_id, user))


@router.get("/operations/complexity-backtest")
def complexity_backtest_route(
    user: UserContext = Depends(require_roles(*OPS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return complexity_backtest(db, user.tenant_id)


@router.get("/claims/{claim_id}/fraud-network")
def fraud_network(
    claim_id: str,
    user: UserContext = Depends(require_roles(*SIU_ALLOWED_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    enforce_siu_access(user)
    return build_weighted_graph(db, _claim(db, claim_id, user))


@router.post("/claims/{claim_id}/fraud-network/siu-lead", status_code=201)
def open_network_siu_lead(
    claim_id: str,
    user: UserContext = Depends(require_roles(Role.SIU_INVESTIGATOR, Role.CLAIMS_MANAGER, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    enforce_siu_access(user)
    claim = _claim(db, claim_id, user)
    graph = build_weighted_graph(db, claim)
    if not graph["siu_case_recommended"]:
        raise DomainError(
            ErrorCode.STATE_CONFLICT,
            f"Network score {graph['network_score']} is below the SIU lead threshold.",
            status_code=409,
        )
    existing = (
        db.query(FraudAlert)
        .filter(FraudAlert.claim_id == claim.id, FraudAlert.indicator_code == NETWORK_LEAD_CODE, FraudAlert.status.in_(["new", "assigned", "investigating"]))
        .first()
    )
    if existing:
        return {"alert_id": existing.id, "created": False, "graph": graph}
    alert = FraudAlert(
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        indicator_code=NETWORK_LEAD_CODE,
        title="Linked claims network needs SIU review",
        severity_band="high" if graph["ring_suspected"] else "medium",
        confidence=Decimal(str(min(0.99, graph["network_score"]))),
        evidence_summary="; ".join(graph["explanation"]),
        benign_explanation="Shared garages, surveyors and locations are common in one city. Links do not prove fraud.",
        recommended_action="SIU reviews the linked claims. Do not reject the claim from this lead alone.",
        entity_links=[{"claim": e["from"], "other": e["to"], "weight": e["weight"]} for e in graph["edges"]][:20],
    )
    db.add(alert)
    db.flush()
    record_audit_event(
        db, tenant_id=claim.tenant_id, claim_id=claim.id, actor_id=user.user_id, actor_role=user.role.value,
        action="SIU_NETWORK_LEAD_OPENED", object_type="fraud_alert", object_id=alert.id,
        details={"network_score": graph["network_score"], "ring_suspected": graph["ring_suspected"]},
    )
    emit_outbox_event(db, tenant_id=claim.tenant_id, aggregate_id=claim.id, event_type="SIULeadOpened", payload={"alert_id": alert.id})
    db.commit()
    return {"alert_id": alert.id, "created": True, "graph": graph}
