"""Predictive claim complexity. A transparent additive baseline model.

The model is a rules baseline. It is not a trained model. Every score lists its drivers.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from services.claims.models import Claim, Policy, Vehicle
from services.rules_engine.intelligence import intelligence_controls, intelligence_rule_version

BAND_ORDER = ["simple", "standard", "complex", "specialist"]


def _band(score: int, bands: dict[str, int]) -> str:
    name = "simple"
    for b in BAND_ORDER:
        if score >= int(bands[b]):
            name = b
    return name


def predict_complexity(db: Session, claim: Claim) -> dict[str, Any]:
    ctl = intelligence_controls()["complexity"]
    w = {k: int(v) for k, v in ctl["weights"].items()}
    policy = db.get(Policy, claim.policy_id) if claim.policy_id else None
    vehicle = db.get(Vehicle, claim.vehicle_id) if claim.vehicle_id else None
    loss = Decimal(str(claim.estimated_loss_inr or 0))
    drivers: list[dict[str, Any]] = []

    def add(key: str, points: int, why: str) -> None:
        if points:
            drivers.append({"driver": key, "points": points, "why": why})

    if loss > Decimal("250000"):
        add("loss_over_250k", w["loss_over_250k"], "Estimated loss is above INR 250,000.")
    elif loss > Decimal("50000"):
        add("loss_over_50k", w["loss_over_50k"], "Estimated loss is above INR 50,000.")
    if policy and Decimal(str(policy.idv_inr)) > 0 and loss / Decimal(str(policy.idv_inr)) > Decimal("0.5"):
        add("loss_to_idv_ratio_over_50pct", w["loss_to_idv_ratio_over_50pct"], "Loss is above 50% of IDV.")
    if claim.claim_type == "third_party":
        add("third_party_claim", w["third_party_claim"], "Third party claims need liability work.")
    if claim.injury_or_fatality:
        add("injury_or_fatality", w["injury_or_fatality"], "Injury or fatality is reported.")
    if claim.ev_battery_impacted or (vehicle and vehicle.is_ev and claim.severity_band == "severe"):
        add("ev_battery", w["ev_battery"], "EV traction battery may be affected.")
    if claim.multiple_vehicles_involved:
        add("multiple_vehicles", w["multiple_vehicles"], "More than one vehicle is involved.")
    if claim.legal_dispute:
        add("legal_dispute", w["legal_dispute"], "A legal dispute is open.")
    if claim.peril_cause in ("theft", "fire", "flood"):
        add("theft_fire_flood_total_loss", w["theft_fire_flood_total_loss"], f"Peril '{claim.peril_cause}' needs total loss handling.")
    if claim.police_involved:
        add("police_involved", w["police_involved"], "Police involvement adds document steps.")
    if claim.towing_needed:
        add("towing_needed", w["towing_needed"], "Towing adds logistics.")
    if claim.risk_tier in ("HIGH", "CRITICAL"):
        add("high_risk_tier", w["high_risk_tier"], f"Risk tier is {claim.risk_tier}.")
    if Decimal(str(claim.fraud_signal_score or 0)) >= Decimal("0.5"):
        add("fraud_signal_over_threshold", w["fraud_signal_over_threshold"], "Fraud signal score is 0.50 or more.")
    if vehicle and vehicle.first_registration_date:
        months = (claim.incident_at.year - vehicle.first_registration_date.year) * 12 + (claim.incident_at.month - vehicle.first_registration_date.month)
        if months > 60:
            add("vehicle_age_over_60_months", w["vehicle_age_over_60_months"], "Vehicle is older than 60 months. Depreciation work is larger.")
    repeats = (
        db.query(func.count(Claim.id))
        .filter(Claim.tenant_id == claim.tenant_id, Claim.vehicle_reg_input == claim.vehicle_reg_input, Claim.id != claim.id)
        .scalar()
    ) or 0
    if repeats:
        add("repeat_vehicle_claims", w["repeat_vehicle_claims"], f"{repeats} other claim(s) exist for this vehicle.")
    missing = len(claim.missing_documents or [])
    if missing:
        add("missing_documents", min(w["missing_documents"] * missing, w["missing_documents_cap"]), f"{missing} expected document type(s) are still missing.")

    score = min(100, sum(d["points"] for d in drivers))
    band = _band(score, ctl["bands"])
    return {
        "claim_id": claim.id,
        "model_id": ctl["model_id"],
        "score": score,
        "band": band,
        "drivers": sorted(drivers, key=lambda d: -d["points"]),
        "expected_handling_hours": ctl["expected_handling_hours"][band],
        "expected_human_touchpoints": ctl["expected_human_touchpoints"][band],
        "recommended_skill": ctl["recommended_skill"][band],
        "rule_version": intelligence_rule_version(),
        "disclaimer": "Transparent rules baseline. It is not a trained model.",
    }


def complexity_backtest(db: Session, tenant_id: str) -> dict[str, Any]:
    """Compare predicted band with the claim's recorded operational path. Measured, not claimed."""
    claims = db.query(Claim).filter(Claim.tenant_id == tenant_id).all()
    dist = {b: 0 for b in BAND_ORDER}
    agree = 0
    for c in claims:
        band = predict_complexity(db, c)["band"]
        dist[band] += 1
        straight = c.operational_path in ("fast_track",)
        if (band == "simple") == straight:
            agree += 1
    n = len(claims)
    return {
        "claims_scored": n,
        "distribution": dist,
        "simple_vs_fast_track_agreement": round(agree / n, 3) if n else None,
        "note": "Agreement compares the simple band with the fast-track path. It is a sanity check on synthetic data.",
    }
