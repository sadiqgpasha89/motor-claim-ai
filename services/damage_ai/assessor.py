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

    per_image_quality: list[dict[str, Any]] = []
    quality_scores: list[float] = []
    for rec in image_records:
        q_status = rec.get("image_quality_status") or "acceptable"
        q_score = float(rec.get("quality_score") or (0.35 if q_status == "recapture_needed" else 0.90))
        quality_scores.append(q_score)
        per_image_quality.append(
            {
                "filename": rec.get("filename", "photo.jpg"),
                "angle": rec.get("image_angle", "unknown"),
                "quality_status": q_status,
                "quality_confidence": round(q_score, 3),
            }
        )

    completeness_ratio = (len(REQUIRED_ANGLES) - len(missing_angles)) / len(REQUIRED_ANGLES)
    avg_img_conf = sum(quality_scores) / len(quality_scores) if quality_scores else 0.72
    image_quality_confidence = round(max(0.25, min(0.98, (avg_img_conf * 0.7) + (completeness_ratio * 0.3))), 3)

    observations: list[dict[str, Any]] = []
    desc_lower = claim_description.lower()

    if any(k in desc_lower for k in ["bumper", "front", "collision", "hit"]) or "front" in uploaded_angles:
        observations.append(
            {
                "component_name": "Front Bumper Assembly (Primed)",
                "part_code": "PRT-FRT-BMP-01",
                "part_category": "rubber_nylon_plastic_tyres_tubes_batteries_airbags",
                "zone": "front_fascia",
                "severity": "moderate",
                "repairability": "replace_recommended",
                "damage_class": "deformation",
                "observation_type": "visible_observed",
                "recommended_action": "replace",
                "confidence": 0.88,
                "repair_vs_replace_rationale": "Cracked plastic mounting tabs and outer fascia tear require OEM bumper replacement.",
                "limitations": "Visible outer skin deformation; behind-bumper absorber requires physical inspection.",
            }
        )
        observations.append(
            {
                "component_name": "Headlamp Assembly LED RH",
                "part_code": "PRT-HL-LED-RH",
                "part_category": "glass",
                "zone": "front_right_lighting",
                "severity": "moderate",
                "repairability": "replace_recommended",
                "damage_class": "crack",
                "observation_type": "visible_observed",
                "recommended_action": "replace",
                "confidence": 0.84,
                "repair_vs_replace_rationale": "Sealed LED headlamp lens & housing crack cannot be safely repaired; full unit replacement required.",
                "limitations": "Lens housing crack visible; mounting bracket check needed.",
            }
        )

    if any(k in desc_lower for k in ["fender", "side", "scrape", "right"]) or "right" in uploaded_angles:
        observations.append(
            {
                "component_name": "Front Fender Panel RH (Steel)",
                "part_code": "PRT-FND-RH-01",
                "part_category": "metal",
                "zone": "front_right_quarter",
                "severity": "minor_cosmetic",
                "repairability": "repairable",
                "damage_class": "dent",
                "observation_type": "visible_observed",
                "recommended_action": "repair",
                "confidence": 0.79,
                "repair_vs_replace_rationale": "Minor crease dent on steel fender without A-pillar/apron tear is repairable via denting + repainting.",
                "limitations": "Surface dent visible; inner apron alignment cannot be confirmed from photos alone.",
            }
        )

    if any(k in desc_lower for k in ["windshield", "glass", "wiper", "cowl"]):
        observations.append(
            {
                "component_name": "Front Windshield Laminated Glass",
                "part_code": "PRT-WS-LAM-01",
                "part_category": "glass",
                "zone": "windshield_cowl",
                "severity": "moderate",
                "repairability": "replace_recommended",
                "damage_class": "crack",
                "observation_type": "visible_observed",
                "recommended_action": "replace",
                "confidence": 0.90,
                "repair_vs_replace_rationale": "Laminated structural windshield crack in driver field of vision requires replacement.",
                "limitations": "Rain-sensor calibration check recommended post-fitment.",
            }
        )

    if any(k in desc_lower for k in ["bonnet", "hood", "radiator"]):
        observations.append(
            {
                "component_name": "Radiator Core Support",
                "part_code": "PRT-RAD-SUP-01",
                "part_category": "metal",
                "zone": "engine_bay_core",
                "severity": "severe_structural",
                "repairability": "teardown_inspection_required",
                "damage_class": "deformation",
                "observation_type": "inferred_possible",
                "recommended_action": "inspect",
                "confidence": 0.62,
                "repair_vs_replace_rationale": "Requires teardown inspection to determine straightening vs replacement.",
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
                "part_category": "metal",
                "zone": "underbody_hv_pack",
                "severity": "safety_critical",
                "repairability": "teardown_inspection_required",
                "damage_class": "ev_hv_alert",
                "observation_type": "inferred_possible",
                "recommended_action": "inspect",
                "confidence": 0.71,
                "repair_vs_replace_rationale": "Mandatory HV isolation & OEM BMS cell balance test before repair/replacement decision.",
                "limitations": "EV battery state-of-health cannot be inferred from exterior photos; physical BMS scan mandatory.",
            }
        )

    damage_zones = sorted({o["zone"] for o in observations})
    severities = [o["severity"] for o in observations]
    if "safety_critical" in severities:
        overall_severity = "safety_critical"
    elif "severe_structural" in severities:
        overall_severity = "severe_structural"
    elif "moderate" in severities:
        overall_severity = "moderate"
    elif observations:
        overall_severity = "minor_cosmetic"
    else:
        overall_severity = "unassessed"

    return {
        "model_version": "cv-adapter-stub-v2",
        "observations": observations,
        "damage_zones": damage_zones,
        "overall_severity": overall_severity,
        "missing_angles": missing_angles,
        "recapture_required_files": poor_quality,
        "per_image_quality": per_image_quality,
        "image_quality_confidence": image_quality_confidence,
        "ev_safety_alerts": ev_safety_alerts,
        "disclaimer": "AI damage output is assistive only. Hidden structural damage cannot be confirmed from photographs alone.",
    }


def validate_estimate_lines(
    lines: list[dict[str, Any]],
    *,
    visible_part_codes: set[str] | None = None,
    damage_observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rate_card = load_rate_card()
    parts_by_code = {p["part_code"]: p for p in rate_card["parts"]}
    max_var_pct = Decimal(str(rate_card.get("max_allowed_variance_pct", "12.00")))

    obs_by_part = {
        o.get("part_code"): o
        for o in (damage_observations or [])
        if o.get("part_code")
    }

    seen_keys: dict[tuple[str, str], int] = {}
    anomalies: list[dict[str, Any]] = []
    evaluated_lines: list[dict[str, Any]] = []
    total_claimed = Decimal("0.00")
    total_recommended = Decimal("0.00")
    oem_benchmark_total = Decimal("0.00")
    oes_benchmark_total = Decimal("0.00")
    labour_benchmark_total = Decimal("0.00")
    paint_benchmark_total = Decimal("0.00")
    repair_vs_replace_flags: list[dict[str, Any]] = []

    for idx, line in enumerate(lines):
        part_code = line["part_code"]
        line_type = line.get("line_type", "part")
        action = line.get("action", "replace")
        qty = int(line.get("quantity", 1))
        unit_price = Decimal(str(line["unit_price_inr"]))
        line_total = unit_price * qty
        total_claimed += line_total

        flags: list[str] = []
        dup_key = (part_code, line_type)
        is_duplicate = dup_key in seen_keys
        if is_duplicate:
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
        oes_price: Decimal | None = None
        recommended_amt = line_total
        justification_status = "justified"

        if rc_part:
            if line_type == "part":
                rc_price = Decimal(str(rc_part["oem_price"]))
                oes_price = Decimal(str(rc_part["oes_price"]))
                if not is_duplicate:
                    oem_benchmark_total += rc_price * qty
                    oes_benchmark_total += oes_price * qty
            elif line_type == "labour":
                rc_price = Decimal(str(rc_part["std_labour_inr"]))
                if not is_duplicate:
                    labour_benchmark_total += rc_price * qty
            elif line_type == "paint":
                rc_price = Decimal(str(rc_part["paint_inr"]))
                if not is_duplicate:
                    paint_benchmark_total += rc_price * qty
            elif line_type == "consumable":
                rc_price = Decimal(str(rc_part["oem_price"]))

            if rc_price is not None and rc_price > Decimal("0.00"):
                variance_pct = ((unit_price - rc_price) / rc_price) * Decimal("100")
                if variance_pct > max_var_pct:
                    flags.append(f"RATE_VARIANCE: +{variance_pct:.1f}% vs OEM/standard benchmark ({rc_price})")
                    anomalies.append(
                        {
                            "type": "rate_variance",
                            "severity": "high" if variance_pct >= Decimal("25.0") else "medium",
                            "part_code": part_code,
                            "message": f"Claimed INR {unit_price} exceeds benchmark INR {rc_price} by {variance_pct:.1f}%",
                        }
                    )
                    recommended_amt = rc_price * qty

        obs = obs_by_part.get(part_code)
        if obs and line_type == "part" and action == "replace" and obs.get("recommended_action") == "repair":
            justification_status = "repair_recommended_over_replace"
            msg = (
                f"Garage quoted full replacement for {part_code}, whereas visual assessment recommends repair "
                f"({obs.get('repair_vs_replace_rationale', 'minor surface damage')})."
            )
            flags.append("REPAIR_VS_REPLACE_CONFLICT: visual assessment recommends repair")
            anomalies.append(
                {
                    "type": "repair_vs_replace_conflict",
                    "severity": "medium",
                    "part_code": part_code,
                    "message": msg,
                }
            )
            repair_vs_replace_flags.append(
                {
                    "part_code": part_code,
                    "garage_action": action,
                    "assessed_action": obs.get("recommended_action"),
                    "rationale": obs.get("repair_vs_replace_rationale", ""),
                }
            )

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

        if is_duplicate:
            recommended_amt = Decimal("0.00")

        total_recommended += recommended_amt
        evaluated_lines.append(
            {
                **line,
                "unit_price_inr": str(unit_price),
                "part_category": rc_part["category"] if rc_part else line.get("part_category", "metal"),
                "rate_card_price_inr": str(rc_price) if rc_price is not None else None,
                "oes_benchmark_price_inr": str(oes_price) if oes_price is not None else None,
                "approved_amount_inr": str(recommended_amt),
                "justification_status": justification_status,
                "variance_flag": "; ".join(flags) if flags else None,
            }
        )

    potential_overcharge = max(total_claimed - total_recommended, Decimal("0.00"))
    return {
        "rate_card_id": rate_card["rate_card_id"],
        "total_claimed_inr": str(total_claimed),
        "total_recommended_inr": str(total_recommended),
        "benchmark_summary": {
            "oem_benchmark_total_inr": str(oem_benchmark_total),
            "oes_benchmark_total_inr": str(oes_benchmark_total),
            "labour_benchmark_total_inr": str(labour_benchmark_total),
            "paint_benchmark_total_inr": str(paint_benchmark_total),
            "potential_overcharge_inr": str(potential_overcharge),
            "max_allowed_variance_pct": str(max_var_pct),
            "repair_vs_replace_flags": repair_vs_replace_flags,
        },
        "anomalies": anomalies,
        "lines": evaluated_lines,
    }
