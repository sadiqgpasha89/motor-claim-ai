"""Supplementary estimate review.

A supplement adds repair lines after the first estimate, often for hidden damage.
Variance and gross are checked against the cumulative total of all estimates.
This stops a large loss from being split into small supplements.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from packages.contracts.errors import DomainError, ErrorCode
from packages.security.auth import UserContext
from services.claims.models import Claim, ClaimTask, Estimate, EstimateLine
from services.rules_engine.intelligence import dec, intelligence_controls, intelligence_rule_version
from services.rules_engine.loader import get_active_rule

SETTLEMENT_RULE_ID = "IN-SETTLEMENT-SCENARIOS-2026"
CENTS = Decimal("0.01")


def _variance_threshold(db: Session, ctl: dict[str, Any]) -> Decimal:
    try:
        params = get_active_rule(db, SETTLEMENT_RULE_ID)["parameters"]
        return dec(params["supplementary_reinspection_variance_threshold"])
    except (KeyError, ValueError):
        return dec(ctl["reinspection_variance_default"])


def assert_supplement_allowed(claim: Claim) -> None:
    allowed = intelligence_controls()["supplementary"]["allowed_claim_statuses"]
    if claim.status not in allowed:
        raise DomainError(
            ErrorCode.STATE_CONFLICT,
            f"A supplementary estimate is not allowed while the claim is in {claim.status}.",
            status_code=409,
        )


def review_supplement(db: Session, claim: Claim, supplement: Estimate, user: UserContext) -> dict[str, Any]:
    ctl = intelligence_controls()["supplementary"]
    threshold = _variance_threshold(db, ctl)
    estimates = db.query(Estimate).filter(Estimate.claim_id == claim.id).order_by(Estimate.version.asc()).all()
    base = [e for e in estimates if not e.is_supplement]
    supplements = [e for e in estimates if e.is_supplement]
    base_total = sum((Decimal(str(e.total_approved_inr)) for e in base), Decimal("0"))
    supp_total = sum((Decimal(str(e.total_approved_inr)) for e in supplements), Decimal("0"))
    cumulative = base_total + supp_total
    variance = (supp_total / base_total).quantize(Decimal("0.001")) if base_total > 0 else None

    base_codes = {
        ln.part_code
        for e in base
        for ln in db.query(EstimateLine).filter(EstimateLine.estimate_id == e.id).all()
    }
    zones = intelligence_controls()["benchmarking"]["adjacent_zone_groups"]
    base_zones = {z for z, codes in zones.items() if base_codes & set(codes)}
    keywords = [k.lower() for k in ctl["hidden_damage_keywords"]]

    line_findings: list[dict[str, Any]] = []
    for ln in db.query(EstimateLine).filter(EstimateLine.estimate_id == supplement.id).all():
        text = f"{ln.description} {ln.part_code}".lower()
        hidden = any(k in text for k in keywords)
        in_zone = any(ln.part_code in zones[z] for z in base_zones)
        plausible = hidden or in_zone or ln.part_code in base_codes
        line_findings.append({
            "part_code": ln.part_code,
            "description": ln.description,
            "hidden_damage_wording": hidden,
            "in_original_damage_zone": in_zone,
            "plausible": plausible,
            "note": "Plausible for the original impact." if plausible else "Part is outside the original damage zone. Ask the garage for photos.",
        })

    reasons: list[str] = []
    reinspection = variance is not None and variance > threshold
    if reinspection:
        reasons.append(f"Cumulative supplements are {variance:.0%} of the first estimate. The limit is {threshold:.0%}.")
    if base_total <= 0:
        reinspection = True
        reasons.append("There is no base estimate to compare. Re-inspection is needed.")
    implausible = [f for f in line_findings if not f["plausible"]]
    if implausible and ctl["adjacent_zone_plausibility"]:
        reinspection = True
        reasons.append(f"{len(implausible)} supplementary line(s) are outside the original damage zone.")
    escalate = cumulative >= dec(ctl["escalate_cumulative_gross_inr"])
    if escalate:
        reasons.append(f"Cumulative gross INR {cumulative:.2f} reaches the escalation limit. Senior approval uses the cumulative total.")

    task_id = None
    if reinspection:
        existing = (
            db.query(ClaimTask)
            .filter(ClaimTask.claim_id == claim.id, ClaimTask.task_type == "supplementary_reinspection", ClaimTask.status == "open")
            .first()
        )
        if existing is None:
            existing = ClaimTask(
                tenant_id=claim.tenant_id,
                claim_id=claim.id,
                task_type="supplementary_reinspection",
                title="Re-inspect vehicle for supplementary estimate",
                description=" ".join(reasons),
                assigned_role="claims_handler",
                created_by_agent="supplementary_review",
                priority="high" if escalate else "medium",
                reason_code="SUPPLEMENT_VARIANCE",
                due_at=datetime.now(timezone.utc) + timedelta(days=2),
                metadata_json={"estimate_id": supplement.id, "variance": str(variance), "created_by": user.user_id},
            )
            db.add(existing)
            db.flush()
        task_id = existing.id

    return {
        "estimate_id": supplement.id,
        "base_total_inr": str(base_total.quantize(CENTS)),
        "supplement_total_inr": str(supp_total.quantize(CENTS)),
        "cumulative_gross_inr": str(cumulative.quantize(CENTS)),
        "cumulative_variance": str(variance) if variance is not None else None,
        "variance_threshold": str(threshold),
        "reinspection_required": reinspection,
        "senior_escalation_required": escalate,
        "reinspection_task_id": task_id,
        "line_findings": line_findings,
        "reasons": reasons,
        "rule_version": intelligence_rule_version(),
    }
