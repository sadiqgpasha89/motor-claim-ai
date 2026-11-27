"""Repair vs replace decision for one damaged component.

Deterministic. Thresholds come from IN-INTELLIGENCE-2026. The output is advisory.
Safety critical parts and EV traction battery parts are never decided from photos.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from services.rules_engine.intelligence import dec, intelligence_controls, intelligence_rule_version
from services.rules_engine.knowledge import load_rate_card

SEVERITY_ORDER = {"none": 0, "minor": 1, "moderate": 2, "severe": 3}
RATE_CARD_CATEGORY = {"glass": "glass", "metal": "metal"}


def _policy_category(part: dict[str, Any], part_code: str, controls: dict[str, Any]) -> str:
    if part_code in controls["ev_battery_part_codes"]:
        return "ev_battery"
    if part_code in controls["safety_critical_part_codes"]:
        return "safety_critical"
    category = str(part.get("category", "metal"))
    if "plastic" in category or "rubber" in category:
        return "plastic"
    return RATE_CARD_CATEGORY.get(category, "metal")


def decide_repair_replace(
    *,
    part_code: str,
    severity: str,
    confidence: float,
    from_photos_only: bool = True,
    idv_inr: Decimal | None = None,
    claim_repair_total_inr: Decimal | None = None,
) -> dict[str, Any]:
    controls = intelligence_controls()["repair_replace"]
    parts = {p["part_code"]: p for p in load_rate_card()["parts"]}
    part = parts.get(part_code, {})
    category = _policy_category(part, part_code, controls)
    policy = controls["category_policy"][category]

    oem = dec(part.get("oem_price", "0"))
    labour = dec(part.get("std_labour_inr", "0"))
    paint = dec(part.get("paint_inr", "0"))
    multiplier = dec(controls["severe_straightening_multiplier"]) if severity == "severe" else Decimal("1")
    repair_cost = ((labour * multiplier) + paint).quantize(Decimal("0.01"))
    replace_cost = (oem + labour + paint).quantize(Decimal("0.01"))
    ratio = (repair_cost / replace_cost).quantize(Decimal("0.001")) if replace_cost > 0 else Decimal("0")

    reasons: list[str] = []
    needs_human = False
    if category in ("ev_battery", "safety_critical"):
        decision = "replace_and_inspect" if category == "safety_critical" else "specialist_inspection"
        needs_human = True
        reasons.append(policy["note"])
    else:
        sev_ok = SEVERITY_ORDER.get(severity, 2) <= SEVERITY_ORDER[policy["max_repair_severity"]]
        cost_ok = ratio <= dec(policy["repair_cost_max_ratio"])
        decision = "repair" if sev_ok and cost_ok else "replace"
        if not sev_ok:
            reasons.append(f"Severity '{severity}' is above the repair limit '{policy['max_repair_severity']}' for {category} parts.")
        if not cost_ok:
            reasons.append(f"Repair costs {ratio:.0%} of replacement. The limit for {category} parts is {dec(policy['repair_cost_max_ratio']):.0%}.")
        if decision == "repair":
            reasons.append(f"Repair is within the {category} policy. {policy['note']}")
        if confidence < float(controls["confidence_floor"]):
            needs_human = True
            reasons.append(f"Confidence {confidence:.2f} is below the floor {controls['confidence_floor']}. A human assessor must confirm.")
    if from_photos_only and category in ("ev_battery", "safety_critical"):
        reasons.append("Decision is not allowed from photographs alone.")

    ctl: dict[str, Any] | None = None
    if idv_inr and claim_repair_total_inr is not None and idv_inr > 0:
        ctl_ratio = (claim_repair_total_inr / idv_inr).quantize(Decimal("0.001"))
        limit = dec(controls["ctl_idv_ratio_threshold"])
        ctl = {
            "repair_to_idv_ratio": str(ctl_ratio),
            "threshold": str(limit),
            "total_loss_review_required": ctl_ratio >= limit,
        }
        if ctl["total_loss_review_required"]:
            needs_human = True
            reasons.append("Claim repair cost is near IDV. Constructive total loss review is required.")

    return {
        "part_code": part_code,
        "category": category,
        "decision": decision,
        "repair_cost_inr": str(repair_cost),
        "replace_cost_inr": str(replace_cost),
        "repair_to_replace_ratio": str(ratio),
        "confidence": confidence,
        "human_review_required": needs_human,
        "constructive_total_loss": ctl,
        "reasons": reasons,
        "rule_version": intelligence_rule_version(),
    }
