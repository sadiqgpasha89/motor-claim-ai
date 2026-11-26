from __future__ import annotations

from decimal import Decimal
from typing import Any

from services.rules_engine.knowledge import load_rate_card

REQUIRED_ANGLES = ["front", "rear", "left", "right", "odometer", "closeup"]


def assess_damage_from_evidence(
    *,
    claim_description: str,
    is_ev: bool,
    ev_battery_impacted: bool,
    image_records: list[dict[str, Any]],
) -> dict[str, Any]:
    uploaded_angles = {r.get("image_angle") for r in image_records if r.get("image_angle")}
    missing_angles = [a for a in REQUIRED_ANGLES if a not in uploaded_angles]
    poor_quality = [r["filename"] for r in image_records if r.get("image_quality_status") == "recapture_needed"]

    observations: list[dict[str, Any]] = []
    desc_lower = claim_description.lower()

    if any(k in desc_lower for k in ["bumper", "front", "collision", "hit"]) or "front" in uploaded_angles:
        observations.append(
            {
                "component_name": "Front Bumper Assembly (Primed)",
                "part_code": "PRT-FRT-BMP-01",
                "damage_class": "deformation",
                "observation_type": "visible_observed",
                "recommended_action": "replace",
                "confidence": 0.88,
                "limitations": "Visible outer skin deformation; behind-bumper absorber requires physical inspection.",
            }
        )
        observations.append(
            {
                "component_name": "Headlamp Assembly LED RH",
                "part_code": "PRT-HL-LED-RH",
                "damage_class": "crack",
                "observation_type": "visible_observed",
                "recommended_action": "replace",
                "confidence": 0.84,
                "limitations": "Lens housing crack visible; mounting bracket check needed.",
            }
        )

    if any(k in desc_lower for k in ["fender", "side", "scrape", "right"]) or "right" in uploaded_angles:
        observations.append(
            {
                "component_name": "Front Fender Panel RH (Steel)",
                "part_code": "PRT-FND-RH-01",
                "damage_class": "dent",
                "observation_type": "visible_observed",
                "recommended_action": "repair",
                "confidence": 0.79,
                "limitations": "Surface dent visible; inner apron alignment cannot be confirmed from photos alone.",
            }
        )

    if any(k in desc_lower for k in ["bonnet", "hood", "radiator"]):
        observations.append(
            {
                "component_name": "Radiator Core Support",
                "part_code": "PRT-RAD-SUP-01",
                "damage_class": "deformation",
                "observation_type": "inferred_possible",
                "recommended_action": "inspect",
                "confidence": 0.62,
                "limitations": "Inferred possible internal impact; DO NOT treat as confirmed without physical survey.",
            }
        )

    ev_safety_alerts: list[str] = []
    if is_ev or ev_battery_impacted or any(k in desc_lower for k in ["battery", "ev", "high voltage", "underbody"]):
        ev_safety_alerts.append(
            "EV HIGH-VOLTAGE SAFETY: Mandatory HV isolation and OEM traction battery diagnostic scan at EV-certified garage before repair."
        )
        observations.append(
            {
                "component_name": "EV Traction Battery Underbody Shield & Tray",
                "part_code": "PRT-EV-BAT-TRAY",
                "damage_class": "ev_hv_alert",
                "observation_type": "inferred_possible",
                "recommended_action": "inspect",
                "confidence": 0.71,
                "limitations": "EV battery state-of-health cannot be inferred from exterior photos; physical BMS scan mandatory.",
            }
        )

    return {
        "model_version": "cv-adapter-stub-v1",
        "observations": observations,
        "missing_angles": missing_angles,
        "recapture_required_files": poor_quality,
        "ev_safety_alerts": ev_safety_alerts,
        "disclaimer": "AI damage output is assistive only. Hidden structural damage cannot be confirmed from photographs alone.",
    }


def validate_estimate_lines(
    lines: list[dict[str, Any]],
    *,
    visible_part_codes: set[str] | None = None,
) -> dict[str, Any]:
    rate_card = load_rate_card()
    parts_by_code = {p["part_code"]: p for p in rate_card["parts"]}
    max_var_pct = Decimal(str(rate_card.get("max_allowed_variance_pct", "12.00")))

    seen_keys: dict[tuple[str, str], int] = {}
    anomalies: list[dict[str, Any]] = []
    evaluated_lines: list[dict[str, Any]] = []
    total_claimed = Decimal("0.00")
    total_recommended = Decimal("0.00")

    for idx, line in enumerate(lines):
        part_code = line["part_code"]
        line_type = line.get("line_type", "part")
        qty = int(line.get("quantity", 1))
        unit_price = Decimal(str(line["unit_price_inr"]))
        line_total = unit_price * qty
        total_claimed += line_total

        flags: list[str] = []
        dup_key = (part_code, line_type)
        if dup_key in seen_keys:
            flags.append(f"DUPLICATE_LINE: repeats line #{seen_keys[dup_key] + 1} for {part_code} ({line_type})")
            anomalies.append(
                {
                    "type": "duplicate_line",
                    "severity": "medium",
                    "part_code": part_code,
                    "message": f"Duplicate estimate line for {line['description']} ({line_type}). Explainable billing error or review item—not proof of fraud.",
                }
            )
        seen_keys[dup_key] = idx

        rc_part = parts_by_code.get(part_code)
        rc_price: Decimal | None = None
        recommended_amt = line_total

        if rc_part:
            if line_type == "part":
                rc_price = Decimal(str(rc_part["oem_price"]))
            elif line_type == "labour":
                rc_price = Decimal(str(rc_part["std_labour_inr"]))
            elif line_type == "paint":
                rc_price = Decimal(str(rc_part["paint_inr"]))
            elif line_type == "consumable":
                rc_price = Decimal(str(rc_part["oem_price"]))

            if rc_price and rc_price > Decimal("0.00"):
                variance_pct = ((unit_price - rc_price) / rc_price) * Decimal("100")
                if variance_pct > max_var_pct:
                    flags.append(f"RATE_VARIANCE: +{variance_pct:.1f}% vs OEM rate card ({rc_price})")
                    anomalies.append(
                        {
                            "type": "rate_variance",
                            "severity": "medium",
                            "part_code": part_code,
                            "message": f"Claimed INR {unit_price} exceeds OEM rate card INR {rc_price} by {variance_pct:.1f}%",
                        }
                    )
                    recommended_amt = rc_price * qty

        if qty > 2 and line_type == "part":
            flags.append(f"QUANTITY_ANOMALY: qty={qty} unusual for single panel/part")
            anomalies.append(
                {
                    "type": "quantity_anomaly",
                    "severity": "low",
                    "part_code": part_code,
                    "message": f"Quantity {qty} for {part_code} requires adjuster/surveyor verification",
                }
            )

        if visible_part_codes and line_type == "part" and part_code not in visible_part_codes and part_code != "PRT-CONS-KIT-01":
            flags.append("NOT_IN_VISIBLE_DAMAGE: requires surveyor physical check")

        if any(f.startswith("DUPLICATE_LINE") for f in flags):
            recommended_amt = Decimal("0.00")

        total_recommended += recommended_amt
        evaluated_lines.append(
            {
                **line,
                "part_category": rc_part["category"] if rc_part else line.get("part_category", "metal"),
                "rate_card_price_inr": str(rc_price) if rc_price is not None else None,
                "approved_amount_inr": str(recommended_amt),
                "variance_flag": "; ".join(flags) if flags else None,
            }
        )

    return {
        "rate_card_id": rate_card["rate_card_id"],
        "total_claimed_inr": str(total_claimed),
        "total_recommended_inr": str(total_recommended),
        "anomalies": anomalies,
        "lines": evaluated_lines,
    }
