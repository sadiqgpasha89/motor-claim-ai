from __future__ import annotations

from decimal import Decimal
from typing import Any

from services.rules_engine.knowledge import load_rate_card

REQUIRED_ANGLES = ["front", "rear", "left", "right", "odometer", "closeup"]

# Location & region bounding boxes (normalized 0..1 and 1280x720 pixel coordinates)
_REGION_BBOXES: dict[str, dict[str, Any]] = {
    "front_center": {"x": 280, "y": 430, "w": 720, "h": 190, "norm_x": 0.22, "norm_y": 0.60, "norm_w": 0.56, "norm_h": 0.26, "region_label": "Front Bumper & Lower Fascia"},
    "front_right": {"x": 810, "y": 300, "w": 260, "h": 180, "norm_x": 0.63, "norm_y": 0.42, "norm_w": 0.20, "norm_h": 0.25, "region_label": "Front Right Corner / Lighting & Fender"},
    "front_left": {"x": 210, "y": 300, "w": 260, "h": 180, "norm_x": 0.16, "norm_y": 0.42, "norm_w": 0.20, "norm_h": 0.25, "region_label": "Front Left Corner / Lighting & Fender"},
    "windshield_cowl": {"x": 340, "y": 140, "w": 600, "h": 170, "norm_x": 0.27, "norm_y": 0.19, "norm_w": 0.47, "norm_h": 0.24, "region_label": "Front Windshield & Cowl"},
    "bonnet_hood": {"x": 310, "y": 260, "w": 660, "h": 175, "norm_x": 0.24, "norm_y": 0.36, "norm_w": 0.52, "norm_h": 0.24, "region_label": "Bonnet / Hood Assembly"},
    "side_left": {"x": 390, "y": 270, "w": 460, "h": 240, "norm_x": 0.30, "norm_y": 0.38, "norm_w": 0.36, "norm_h": 0.33, "region_label": "Left Side Door & Sill"},
    "side_right": {"x": 420, "y": 270, "w": 460, "h": 240, "norm_x": 0.33, "norm_y": 0.38, "norm_w": 0.36, "norm_h": 0.33, "region_label": "Right Side Door & Quarter"},
    "rear": {"x": 270, "y": 390, "w": 740, "h": 210, "norm_x": 0.21, "norm_y": 0.54, "norm_w": 0.58, "norm_h": 0.29, "region_label": "Rear Bumper & Tailgate"},
    "underbody": {"x": 300, "y": 510, "w": 680, "h": 150, "norm_x": 0.23, "norm_y": 0.71, "norm_w": 0.53, "norm_h": 0.21, "region_label": "Underbody / EV Battery & Subframe"},
}

_ANGLE_COMPATIBILITY: dict[str, set[str]] = {
    "front_center": {"front", "closeup", "front_left", "front_right"},
    "front_right": {"front", "right", "closeup", "front_right"},
    "front_left": {"front", "left", "closeup", "front_left"},
    "side_left": {"left", "closeup", "front_left"},
    "side_right": {"right", "closeup", "front_right"},
    "rear": {"rear", "closeup", "rear_left", "rear_right"},
    "underbody": {"underbody", "closeup", "front", "rear"},
}

_KNOWN_MAKES = ("maruti", "suzuki", "baleno", "swift", "tata", "nexon", "hyundai", "creta", "honda", "city", "mahindra", "kia", "toyota")


def _normalize_image_quality(rec: dict[str, Any]) -> tuple[str, float, list[str]]:
    raw_status = str(rec.get("image_quality_status") or "").lower()
    norm = str(rec.get("normalized_quality") or "").lower()
    fname = str(rec.get("filename") or "").lower()
    issues: list[str] = list(rec.get("issues") or [])

    if raw_status == "recapture_needed" or norm == "recapture" or any(
        tok in fname for tok in ["blurry", "dark", "low_quality", "corrupt", "recapture"]
    ):
        q_score = float(rec.get("quality_score") or 0.34)
        if not issues:
            issues.append("Blur, underexposure, or low resolution requires daylight recapture")
        return "recapture", round(min(q_score, 0.49), 3), issues

    if raw_status == "poor" or norm == "poor" or any(
        tok in fname for tok in ["shadow", "glare", "occluded", "cropped", "night", "dim", "rain", "poor"]
    ):
        q_score = float(rec.get("quality_score") or 0.62)
        if not issues:
            issues.append("Shadow, glare, or partial framing limits component certainty")
        return "poor", round(max(0.50, min(q_score, 0.72)), 3), issues

    q_score = float(rec.get("quality_score") or 0.91)
    return "good", round(max(0.75, min(q_score, 0.98)), 3), issues


def _detect_vehicle(
    *,
    vehicle_info: dict[str, Any] | None,
    claim_description: str,
    image_records: list[dict[str, Any]],
    is_ev: bool,
) -> dict[str, Any]:
    v = dict(vehicle_info or {})
    make = str(v.get("make") or ("Tata" if is_ev else "Maruti Suzuki"))
    model = str(v.get("model") or ("Nexon EV" if is_ev else "Baleno"))
    variant = str(v.get("variant") or ("Empowered+ LR" if is_ev else "Alpha AGS"))
    year = int(v.get("year") or 2024)
    reg = str(v.get("registration_number") or "UNSPECIFIED")
    fuel_type = str(v.get("fuel_type") or ("electric" if is_ev else "petrol"))

    detected_make_tokens: set[str] = set()
    for rec in image_records:
        blob = f"{rec.get('filename', '')} {rec.get('ocr_text', '')}".lower()
        for mk in _KNOWN_MAKES:
            if mk in blob:
                detected_make_tokens.add(mk)

    expected_blob = f"{make} {model}".lower()
    conflicting_tokens = [tok for tok in detected_make_tokens if tok not in expected_blob]
    if conflicting_tokens:
        detection_status = "mismatch"
        detection_conf = 0.54
    elif image_records:
        detection_status = "matched"
        detection_conf = 0.94
    else:
        detection_status = "metadata_only_awaiting_photos"
        detection_conf = 0.78

    return {
        "make": make,
        "model": model,
        "variant": variant,
        "year": year,
        "registration_number": reg,
        "fuel_type": fuel_type,
        "is_ev": bool(v.get("is_ev", is_ev)),
        "detection_status": detection_status,
        "detection_confidence": detection_conf,
        "conflicting_vehicle_signals": conflicting_tokens,
        "photos_analysed": len(image_records),
        "display_label": f"{year} {make} {model} {variant}".strip(),
    }


def _matching_evidence_for_location(
    damage_location: str,
    bbox_key: str,
    normalized_images: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    compat_angles = _ANGLE_COMPATIBILITY.get(damage_location, {"front", "closeup"})
    bbox = _REGION_BBOXES.get(bbox_key, _REGION_BBOXES["front_center"])
    matched: list[dict[str, Any]] = []
    for im in normalized_images:
        ang = im["angle"]
        loc_hint = im.get("location_hint", ang)
        if ang in compat_angles or loc_hint == damage_location or ang == "closeup":
            matched.append(
                {
                    "evidence_id": im.get("evidence_id"),
                    "filename": im["filename"],
                    "angle": ang,
                    "location_hint": loc_hint,
                    "image_quality": im["normalized_quality"],
                    "sha256_prefix": str(im.get("sha256") or "")[:12],
                    "region_label": bbox["region_label"],
                    "bbox": {
                        "x": bbox["x"],
                        "y": bbox["y"],
                        "w": bbox["w"],
                        "h": bbox["h"],
                        "norm_x": bbox["norm_x"],
                        "norm_y": bbox["norm_y"],
                        "norm_w": bbox["norm_w"],
                        "norm_h": bbox["norm_h"],
                    },
                }
            )
    return matched


def _calibrate_component_confidence(
    *,
    overall_img_conf: float,
    matching_evidence: list[dict[str, Any]],
    is_inferred: bool,
    is_uncertain_cue: bool,
    has_inconsistency: bool,
    repairability: str,
) -> tuple[float, str, dict[str, Any]]:
    """Computes component-level confidence independently of overall image confidence.

    Critically: high overall image quality (e.g. 0.92) MUST NOT inflate confidence for an
    occluded, shadowed, single-angle severe, or internally inferred component.
    """
    if matching_evidence:
        qualities = [ev["image_quality"] for ev in matching_evidence]
        if all(q == "recapture" for q in qualities):
            comp_quality = "recapture"
            base = 0.40
        elif "recapture" in qualities or "poor" in qualities:
            comp_quality = "poor" if "poor" in qualities else "recapture"
            base = 0.63 if "poor" in qualities else 0.45
        else:
            comp_quality = "good"
            base = 0.87
    else:
        comp_quality = "poor" if overall_img_conf < 0.72 else "good"
        base = 0.77 if not is_inferred else 0.59

    unique_angles = {ev["angle"] for ev in matching_evidence}
    corroboration_bonus = 0.05 if len(unique_angles) >= 2 else (0.0 if len(unique_angles) == 1 else -0.04)
    if repairability == "replace" and len(unique_angles) == 1 and "closeup" not in unique_angles and not is_inferred:
        # Single wide photo without closeup cannot give >0.85 certainty on replacement
        corroboration_bonus -= 0.08

    occlusion_penalty = 0.24 if is_uncertain_cue else (0.21 if is_inferred else 0.0)
    inconsistency_penalty = 0.16 if has_inconsistency else 0.0

    score = round(max(0.28, min(0.96, base + corroboration_bonus - occlusion_penalty - inconsistency_penalty)), 3)
    band = "high" if score >= 0.80 else ("medium" if score >= 0.65 else "low")

    if is_uncertain_cue:
        rationale = (
            f"Overall image quality is {overall_img_conf:.2f}, but component-level visibility is degraded by "
            "shadow/occlusion/mounting ambiguity; human assessor verification required before replacement."
        )
    elif is_inferred:
        rationale = "Internal/underbody component inferred from impact zone; physical teardown required."
    elif has_inconsistency:
        rationale = "Confidence reduced due to cross-photo or FNOL-vs-photo inconsistency."
    elif len(unique_angles) >= 2 and comp_quality == "good":
        rationale = f"Corroborated across {len(unique_angles)} good-quality angles ({', '.join(sorted(unique_angles))})."
    else:
        rationale = f"Calibrated from {comp_quality} component view ({len(unique_angles)} angle(s))."

    return score, band, {
        "overall_image_quality": overall_img_conf,
        "component_image_quality": comp_quality,
        "angles_supporting_count": len(unique_angles),
        "corroboration_delta": round(corroboration_bonus, 3),
        "occlusion_or_hidden_penalty": round(occlusion_penalty, 3),
        "inconsistency_penalty": round(inconsistency_penalty, 3),
        "rationale": rationale,
    }


def _cost_breakdown_for_component(
    part_code: str,
    repairability: str,
    parts_by_code: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rc = parts_by_code.get(part_code)
    if not rc:
        return {
            "parts_oem_inr": "0.00",
            "parts_oes_inr": "0.00",
            "labour_inr": "2500.00",
            "paint_inr": "2500.00",
            "subtotal_oem_inr": "5000.00",
            "subtotal_oes_inr": "5000.00",
            "estimate_range_inr": "5000.00 - 5000.00",
            "action_basis": repairability,
        }
    oem = Decimal(str(rc["oem_price"]))
    oes = Decimal(str(rc["oes_price"]))
    labour = Decimal(str(rc["std_labour_inr"]))
    paint = Decimal(str(rc["paint_inr"]))

    if repairability == "repair":
        parts_oem = Decimal("0.00")
        parts_oes = Decimal("0.00")
        sub_oem = labour + paint
        sub_oes = labour + paint
        rng = f"{sub_oem:.2f}"
    elif repairability == "replace":
        parts_oem = oem
        parts_oes = oes
        sub_oem = oem + labour + paint
        sub_oes = oes + labour + paint
        rng = f"{sub_oes:.2f} - {sub_oem:.2f}"
    else:
        # Uncertain: show repair floor up to OEM replacement ceiling
        parts_oem = oem
        parts_oes = oes
        repair_floor = labour + paint
        replace_ceil = oem + labour + paint
        sub_oem = replace_ceil
        sub_oes = repair_floor
        rng = f"{repair_floor:.2f} (repair) - {replace_ceil:.2f} (replace)"

    return {
        "parts_oem_inr": f"{parts_oem:.2f}",
        "parts_oes_inr": f"{parts_oes:.2f}",
        "labour_inr": f"{labour:.2f}",
        "paint_inr": f"{paint:.2f}",
        "subtotal_oem_inr": f"{sub_oem:.2f}",
        "subtotal_oes_inr": f"{sub_oes:.2f}",
        "estimate_range_inr": rng,
        "action_basis": repairability,
    }


def assess_damage_from_evidence(
    *,
    claim_description: str,
    is_ev: bool,
    ev_battery_impacted: bool,
    image_records: list[dict[str, Any]],
    vehicle_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rate_card = load_rate_card()
    parts_by_code = {p["part_code"]: p for p in rate_card["parts"]}

    # Step 1 & 2: Normalize uploaded photos & validate image quality
    normalized_images: list[dict[str, Any]] = []
    seen_hashes: dict[str, str] = {}
    duplicate_hashes: list[dict[str, str]] = []
    per_image_quality: list[dict[str, Any]] = []
    quality_scores: list[float] = []

    for idx, rec in enumerate(image_records):
        norm_q, q_score, issues = _normalize_image_quality(rec)
        raw_angle = str(rec.get("image_angle") or "closeup").lower()
        loc_hint = str(rec.get("location_hint") or raw_angle).lower()
        fname = str(rec.get("filename") or f"photo_{idx + 1}.jpg")
        sha = str(rec.get("sha256") or "")
        if sha and sha in seen_hashes:
            duplicate_hashes.append({"sha256_prefix": sha[:12], "first_file": seen_hashes[sha], "duplicate_file": fname})
        elif sha:
            seen_hashes[sha] = fname

        entry = {
            "evidence_id": rec.get("id") or rec.get("evidence_id") or f"img-{idx + 1}",
            "filename": fname,
            "angle": raw_angle,
            "location_hint": loc_hint,
            "quality_status": rec.get("image_quality_status") or ("recapture_needed" if norm_q == "recapture" else ("poor" if norm_q == "poor" else "acceptable")),
            "normalized_quality": norm_q,
            "quality_confidence": q_score,
            "issues": issues,
            "sha256": sha,
            "ocr_text": str(rec.get("ocr_text") or ""),
        }
        normalized_images.append(entry)
        quality_scores.append(q_score)
        per_image_quality.append(
            {
                "evidence_id": entry["evidence_id"],
                "filename": fname,
                "angle": raw_angle,
                "location_hint": loc_hint,
                "quality_status": entry["quality_status"],
                "normalized_quality": norm_q,
                "quality_confidence": q_score,
                "issues": issues,
            }
        )

    uploaded_angles = {im["angle"] for im in normalized_images}
    # Front_left/front_right photos also satisfy front/left/right angle presence
    for im in normalized_images:
        if im["location_hint"] == "front_left":
            uploaded_angles.update({"front", "left"})
        elif im["location_hint"] == "front_right":
            uploaded_angles.update({"front", "right"})

    missing_angles = [a for a in REQUIRED_ANGLES if a not in uploaded_angles]
    recapture_files = [im["filename"] for im in normalized_images if im["normalized_quality"] == "recapture"]
    poor_files = [im["filename"] for im in normalized_images if im["normalized_quality"] == "poor"]

    completeness_ratio = (len(REQUIRED_ANGLES) - len(missing_angles)) / len(REQUIRED_ANGLES)
    avg_img_conf = sum(quality_scores) / len(quality_scores) if quality_scores else 0.72
    image_quality_confidence = round(max(0.25, min(0.98, (avg_img_conf * 0.7) + (completeness_ratio * 0.3))), 3)

    overall_image_quality = (
        "recapture"
        if recapture_files and len(recapture_files) == len(normalized_images)
        else ("poor" if (recapture_files or poor_files) else "good")
    )

    # Step 3: Detect vehicle and identify visible damaged regions
    vehicle = _detect_vehicle(
        vehicle_info=vehicle_info,
        claim_description=claim_description,
        image_records=normalized_images,
        is_ev=is_ev,
    )

    desc_lower = claim_description.lower()
    image_blob = " ".join(f"{im['filename']} {im['ocr_text']}" for im in normalized_images).lower()
    combined_blob = f"{desc_lower} {image_blob}"

    # Signals for uncertainty & location side
    front_left_hint = any(k in combined_blob for k in ["front left", "front_left", "lh", "left headlight", "left headlamp", "left fender"])
    front_right_hint = any(k in combined_blob for k in ["front right", "front_right", "rh", "right headlight", "right headlamp", "right fender"])
    uncertain_bumper_cue = any(
        k in combined_blob
        for k in ["uncertain", "shadow", "occluded", "mounting", "alignment", "borderline", "partial", "hidden", "glare", "cropped"]
    )
    minor_bumper_cue = any(k in desc_lower for k in ["scuff", "scratch", "minor", "light rub", "paint transfer"])
    severe_bumper_cue = any(k in desc_lower for k in ["torn", "shattered", "crushed", "split", "severely deformed"])

    # Step 4: Classify damaged components with per-component confidence & repairability
    candidates: list[dict[str, Any]] = []

    if any(k in desc_lower for k in ["bumper", "front", "collision", "hit", "impact"]) and "rear bumper" not in desc_lower or "front" in uploaded_angles:
        if not any(k in desc_lower for k in ["rear bumper", "rear-end", "rear end", "tailgate"]) or "front" in uploaded_angles or "front" in desc_lower:
            bumper_loc = "front_left" if front_left_hint and not front_right_hint else ("front_right" if front_right_hint and not front_left_hint else "front_center")
            if uncertain_bumper_cue:
                b_sev, b_rep, b_act, b_class = "moderate", "uncertain", "inspect", "deformation"
                b_vis = "Outer bumper fascia abrasion and edge distortion visible; lower mounting tabs partially shadowed."
                b_hid = "Bumper reinforcement bar, energy absorber foam, and PDC sensor harness require physical teardown."
                b_rat = "Component visibility is partially occluded/ambiguous; cannot confirm beyond repair from photos alone — route to human assessor."
            elif minor_bumper_cue and not severe_bumper_cue:
                b_sev, b_rep, b_act, b_class = "minor", "repair", "repair", "scratch"
                b_vis = "Superficial clear-coat scuff and minor corner abrasion on front bumper skin."
                b_hid = "No structural deformation apparent; confirm parking sensor calibration on routine check."
                b_rat = "Surface cosmetic scuff without mounting tab tear is repairable via spot refinishing & repaint."
            else:
                b_sev, b_rep, b_act, b_class = "moderate", "replace", "replace", "deformation"
                b_vis = "Cracked outer bumper fascia, displaced grille seam, and stressed upper clip mounts visible."
                b_hid = "Behind-bumper impact absorber foam, fog-lamp bracket, and radar/PDC wiring require physical check."
                b_rat = "Cracked plastic mounting tabs and outer fascia tear require OEM bumper replacement."

            candidates.append(
                {
                    "damaged_component": "Bumper",
                    "component_name": "Front Bumper Assembly (Primed)",
                    "part_code": "PRT-FRT-BMP-01",
                    "part_category": "rubber_nylon_plastic_tyres_tubes_batteries_airbags",
                    "damage_location": bumper_loc,
                    "bbox_key": bumper_loc,
                    "zone": "front_fascia",
                    "damage_severity": b_sev,
                    "severity": "minor_cosmetic" if b_sev == "minor" else b_sev,
                    "repairability": b_rep,
                    "recommended_action": b_act,
                    "damage_class": b_class,
                    "observation_type": "visible_observed",
                    "visible_damage": b_vis,
                    "possible_hidden_damage": b_hid,
                    "repair_vs_replace_rationale": b_rat,
                    "limitations": b_hid,
                    "is_uncertain_cue": uncertain_bumper_cue,
                }
            )

    if any(k in desc_lower for k in ["headlamp", "headlight", "lamp", "light", "front", "collision", "hit"]) and not minor_bumper_cue and "rear" not in desc_lower:
        if any(k in desc_lower for k in ["headlamp", "headlight", "lamp", "light", "collision", "hit"]) or "front" in uploaded_angles:
            is_lh = front_left_hint and not front_right_hint
            hl_code = "PRT-HL-LED-LH" if is_lh else "PRT-HL-LED-RH"
            hl_loc = "front_left" if is_lh else "front_right"
            hl_name = "Headlamp Assembly LED LH" if is_lh else "Headlamp Assembly LED RH"
            hl_uncertain = any(k in combined_blob for k in ["headlight uncertain", "headlamp occluded", "foggy lens"])
            candidates.append(
                {
                    "damaged_component": "Headlight",
                    "component_name": hl_name,
                    "part_code": hl_code,
                    "part_category": "glass",
                    "damage_location": hl_loc,
                    "bbox_key": hl_loc,
                    "zone": "front_left_lighting" if is_lh else "front_right_lighting",
                    "damage_severity": "moderate",
                    "severity": "moderate",
                    "repairability": "uncertain" if hl_uncertain else "replace",
                    "recommended_action": "inspect" if hl_uncertain else "replace",
                    "damage_class": "crack",
                    "observation_type": "visible_observed",
                    "visible_damage": "Polycarbonate lens fracture and moisture ingress seal breach visible on LED housing.",
                    "possible_hidden_damage": "Headlamp levelling motor, ballast module, and upper core bracket alignment require check.",
                    "repair_vs_replace_rationale": (
                        "Glare/occlusion on headlamp housing requires human verification."
                        if hl_uncertain
                        else "Sealed LED headlamp lens & housing crack cannot be safely repaired; full unit replacement required."
                    ),
                    "limitations": "Lens housing crack visible; mounting bracket and beam alignment check needed.",
                    "is_uncertain_cue": hl_uncertain,
                }
            )

    if any(k in desc_lower for k in ["fender", "scrape", "quarter"]) or "right" in uploaded_angles or ("front" in uploaded_angles and front_right_hint):
        is_lh_f = front_left_hint and not front_right_hint
        f_code = "PRT-FND-LH-01" if is_lh_f else "PRT-FND-RH-01"
        f_loc = "front_left" if is_lh_f else "front_right"
        f_name = "Front Fender Panel LH (Steel)" if is_lh_f else "Front Fender Panel RH (Steel)"
        f_severe = any(k in desc_lower for k in ["fender crushed", "fender torn", "deep crease"])
        candidates.append(
            {
                "damaged_component": "Fender",
                "component_name": f_name,
                "part_code": f_code,
                "part_category": "metal",
                "damage_location": f_loc,
                "bbox_key": f_loc,
                "zone": "front_left_quarter" if is_lh_f else "front_right_quarter",
                "damage_severity": "moderate" if f_severe else "minor",
                "severity": "moderate" if f_severe else "minor_cosmetic",
                "repairability": "uncertain" if f_severe else "repair",
                "recommended_action": "inspect" if f_severe else "repair",
                "damage_class": "dent",
                "observation_type": "visible_observed",
                "visible_damage": "Wheel-arch panel crease and paint abrasion visible along front fender edge.",
                "possible_hidden_damage": "Inner wheel-well liner, A-pillar lower hinge, and apron flange alignment cannot be confirmed from photos.",
                "repair_vs_replace_rationale": (
                    "Deep fender crease near A-pillar requires human assessor gauge check for denting vs replacement."
                    if f_severe
                    else "Minor crease dent on steel fender without A-pillar/apron tear is repairable via denting + repainting."
                ),
                "limitations": "Surface dent visible; inner apron alignment cannot be confirmed from photos alone.",
                "is_uncertain_cue": f_severe,
            }
        )

    if any(k in desc_lower for k in ["door", "side impact", "t-bone", "sill", "side scrape"]):
        is_lh_d = "left" in combined_blob and "right" not in combined_blob
        d_code = "PRT-DOOR-LH-01" if is_lh_d else "PRT-DOOR-RH-01"
        d_loc = "side_left" if is_lh_d else "side_right"
        d_name = "Front Door Shell LH (Steel)" if is_lh_d else "Front Door Shell RH (Steel)"
        d_severe = any(k in desc_lower for k in ["door crushed", "intrusion", "side impact", "t-bone", "jammed"])
        candidates.append(
            {
                "damaged_component": "Door",
                "component_name": d_name,
                "part_code": d_code,
                "part_category": "metal",
                "damage_location": d_loc,
                "bbox_key": d_loc,
                "zone": "side_body_panel",
                "damage_severity": "severe" if d_severe else "moderate",
                "severity": "severe_structural" if d_severe else "moderate",
                "repairability": "replace" if d_severe else "repair",
                "recommended_action": "replace" if d_severe else "repair",
                "damage_class": "dent",
                "observation_type": "visible_observed",
                "visible_damage": "Door skin buckling and beltline scuffing visible across outer panel.",
                "possible_hidden_damage": "Side-impact intrusion beam, window regulator track, and B-pillar latch alignment require inspection.",
                "repair_vs_replace_rationale": (
                    "Deep intrusion across door reinforcement beam requires full shell replacement."
                    if d_severe
                    else "Outer skin dent without sill/B-pillar distortion is repairable via panel beating & refinishing."
                ),
                "limitations": "Internal intrusion beam integrity requires trim-panel removal.",
                "is_uncertain_cue": False,
            }
        )

    if any(k in desc_lower for k in ["mirror", "orvm"]):
        candidates.append(
            {
                "damaged_component": "Mirror",
                "component_name": "ORVM Wing Mirror Assembly LH (Power Fold)",
                "part_code": "PRT-ORVM-LH-01",
                "part_category": "rubber_nylon_plastic_tyres_tubes_batteries_airbags",
                "damage_location": "front_left",
                "bbox_key": "side_left",
                "zone": "side_mirror_trim",
                "damage_severity": "minor",
                "severity": "minor_cosmetic",
                "repairability": "repair",
                "recommended_action": "repair",
                "damage_class": "scratch",
                "observation_type": "visible_observed",
                "visible_damage": "Painted outer mirror cap scuff; glass and turn-indicator lens intact.",
                "possible_hidden_damage": "Power-fold actuator gear play to be verified functionally.",
                "repair_vs_replace_rationale": "Intact mirror housing & motor; repaint/cap refinish recommended.",
                "limitations": "Electrical fold motor test recommended at workshop.",
                "is_uncertain_cue": False,
            }
        )

    if any(k in desc_lower for k in ["windshield", "glass", "wiper", "cowl"]):
        candidates.append(
            {
                "damaged_component": "Windshield",
                "component_name": "Front Windshield Laminated Glass",
                "part_code": "PRT-WS-LAM-01",
                "part_category": "glass",
                "damage_location": "front_center",
                "bbox_key": "windshield_cowl",
                "zone": "windshield_cowl",
                "damage_severity": "moderate",
                "severity": "moderate",
                "repairability": "replace",
                "recommended_action": "replace",
                "damage_class": "crack",
                "observation_type": "visible_observed",
                "visible_damage": "Laminated spider-web fracture radiating across driver primary viewing zone.",
                "possible_hidden_damage": "A-pillar pinch-weld corrosion, rain/ADAS camera bracket calibration needed post-fitment.",
                "repair_vs_replace_rationale": "Laminated structural windshield crack in driver field of vision requires replacement.",
                "limitations": "Rain-sensor & ADAS camera calibration check recommended post-fitment.",
                "is_uncertain_cue": False,
            }
        )

    if any(k in desc_lower for k in ["rear", "tail", "tailgate", "back"]) or "rear" in uploaded_angles:
        if any(k in desc_lower for k in ["rear", "tail", "tailgate", "back"]) or "rear" in uploaded_angles:
            r_minor = any(k in desc_lower for k in ["scuff", "scratch", "minor"])
            candidates.append(
                {
                    "damaged_component": "Rear Bumper",
                    "component_name": "Rear Bumper Assembly (Primed)",
                    "part_code": "PRT-RR-BMP-01",
                    "part_category": "rubber_nylon_plastic_tyres_tubes_batteries_airbags",
                    "damage_location": "rear",
                    "bbox_key": "rear",
                    "zone": "rear_fascia",
                    "damage_severity": "minor" if r_minor else "moderate",
                    "severity": "minor_cosmetic" if r_minor else "moderate",
                    "repairability": "repair" if r_minor else "replace",
                    "recommended_action": "repair" if r_minor else "replace",
                    "damage_class": "scratch" if r_minor else "deformation",
                    "observation_type": "visible_observed",
                    "visible_damage": "Rear bumper scuffing/indentation along lower tailgate loading lip.",
                    "possible_hidden_damage": "Rear crash beam, boot floor pan, and spare-wheel well alignment require boot-liner lift check.",
                    "repair_vs_replace_rationale": (
                        "Minor rear bumper scuffing without structural tear is repairable."
                        if r_minor
                        else "Rear impact indentation near sensor mounts warrants OEM bumper replacement."
                    ),
                    "limitations": "Boot floor pan and rear crash bar require physical inspection.",
                    "is_uncertain_cue": False,
                }
            )
            if any(k in desc_lower for k in ["tail", "lamp", "rear-end", "rear end"]):
                candidates.append(
                    {
                        "damaged_component": "Tail Lamp",
                        "component_name": "Tail Lamp Assembly LED",
                        "part_code": "PRT-TL-LED-01",
                        "part_category": "glass",
                        "damage_location": "rear",
                        "bbox_key": "rear",
                        "zone": "rear_lighting",
                        "damage_severity": "moderate",
                        "severity": "moderate",
                        "repairability": "replace",
                        "recommended_action": "replace",
                        "damage_class": "crack",
                        "observation_type": "visible_observed",
                        "visible_damage": "Rear LED tail lamp outer lens cracked with reflector exposure.",
                        "possible_hidden_damage": "Quarter-panel lamp pocket and wiring grommet seal check needed.",
                        "repair_vs_replace_rationale": "Cracked sealed tail lamp assembly cannot be repaired safely.",
                        "limitations": "Confirm wiring harness connector integrity.",
                        "is_uncertain_cue": False,
                    }
                )

    if any(k in desc_lower for k in ["bonnet", "hood", "radiator", "teardown", "core support"]):
        candidates.append(
            {
                "damaged_component": "Bonnet",
                "component_name": "Bonnet / Hood Panel (Steel)",
                "part_code": "PRT-BON-01",
                "part_category": "metal",
                "damage_location": "front_center",
                "bbox_key": "bonnet_hood",
                "zone": "front_hood",
                "damage_severity": "severe",
                "severity": "severe_structural",
                "repairability": "replace",
                "recommended_action": "replace",
                "damage_class": "deformation",
                "observation_type": "visible_observed",
                "visible_damage": "Leading-edge bonnet crumple crease and latch misalignment visible.",
                "possible_hidden_damage": "Bonnet hinges, cowl panel, and radiator upper tie-bar require inspection.",
                "repair_vs_replace_rationale": "Crumple zone deformation on leading hood edge compromises pedestrian safety; replace recommended.",
                "limitations": "Latch and hinge geometry require physical verification.",
                "is_uncertain_cue": False,
            }
        )
        candidates.append(
            {
                "damaged_component": "Radiator Core Support",
                "component_name": "Radiator Core Support",
                "part_code": "PRT-RAD-SUP-01",
                "part_category": "metal",
                "damage_location": "front_center",
                "bbox_key": "front_center",
                "zone": "engine_bay_core",
                "damage_severity": "severe",
                "severity": "severe_structural",
                "repairability": "uncertain",
                "recommended_action": "inspect",
                "damage_class": "deformation",
                "observation_type": "inferred_possible",
                "visible_damage": "Not directly observable in exterior closed-bonnet photos; inferred from front-center crumple.",
                "possible_hidden_damage": "Radiator core support, AC condenser fins, intercooler, and cooling fan shroud require teardown inspection.",
                "repair_vs_replace_rationale": "Requires teardown inspection to determine straightening vs replacement; cannot conclude from photos.",
                "limitations": "Inferred possible internal impact; DO NOT treat as confirmed without physical survey.",
                "is_uncertain_cue": True,
            }
        )

    ev_safety_alerts: list[str] = []
    if is_ev or ev_battery_impacted or any(k in desc_lower for k in ["battery", "high voltage", "underbody", "undercarriage"]):
        ev_safety_alerts.append(
            "EV HIGH-VOLTAGE SAFETY: Mandatory HV isolation and OEM traction battery diagnostic scan at EV-certified garage before repair."
        )
        candidates.append(
            {
                "damaged_component": "EV Battery Tray",
                "component_name": "EV Traction Battery Underbody Shield & Tray",
                "part_code": "PRT-EV-BAT-TRAY",
                "part_category": "metal",
                "damage_location": "underbody",
                "bbox_key": "underbody",
                "zone": "underbody_hv_pack",
                "damage_severity": "severe",
                "severity": "safety_critical",
                "repairability": "uncertain",
                "recommended_action": "inspect",
                "damage_class": "ev_hv_alert",
                "observation_type": "inferred_possible",
                "visible_damage": "Underbody impact zone near traction pack tray; exterior images cannot inspect HV cell integrity.",
                "possible_hidden_damage": "HV battery tray deformation, coolant plate leak, pyrotechnic fuse & BMS cell imbalance require lift & OEM BMS scan.",
                "repair_vs_replace_rationale": "Mandatory HV isolation & OEM BMS cell balance test before repair/replacement decision.",
                "limitations": "EV battery state-of-health cannot be inferred from exterior photos; physical BMS scan mandatory.",
                "is_uncertain_cue": True,
            }
        )

    # Deduplicate candidates by part_code
    seen_part_codes: set[str] = set()
    unique_candidates: list[dict[str, Any]] = []
    for c in candidates:
        if c["part_code"] not in seen_part_codes:
            seen_part_codes.add(c["part_code"])
            unique_candidates.append(c)
    candidates = unique_candidates

    # Step 5 & 6: Compare damage across photos & identify inconsistencies
    inconsistencies: list[dict[str, Any]] = []
    if duplicate_hashes:
        for dup in duplicate_hashes:
            inconsistencies.append(
                {
                    "inconsistency_id": f"inc-dup-{dup['sha256_prefix']}",
                    "type": "duplicate_photo_hash",
                    "severity": "high",
                    "summary": f"Identical SHA-256 ({dup['sha256_prefix']}) submitted for '{dup['first_file']}' and '{dup['duplicate_file']}'.",
                    "affected_components": [c["component_name"] for c in candidates],
                    "evidence_refs": [dup["first_file"], dup["duplicate_file"]],
                    "resolution_required": "Upload distinct original angle photographs for cross-angle corroboration.",
                }
            )

    if vehicle["detection_status"] == "mismatch":
        inconsistencies.append(
            {
                "inconsistency_id": "inc-veh-mismatch",
                "type": "vehicle_identity_mismatch",
                "severity": "high",
                "summary": (
                    f"Photo/OCR signals ({', '.join(vehicle['conflicting_vehicle_signals'])}) conflict with "
                    f"insured vehicle {vehicle['display_label']}."
                ),
                "affected_components": [c["component_name"] for c in candidates],
                "evidence_refs": [im["filename"] for im in normalized_images],
                "resolution_required": "Human assessor must verify VIN/chassis plate and live odometer photo.",
            }
        )

    if normalized_images:
        fnol_mentions_rear = any(k in desc_lower for k in ["rear bumper", "rear-end", "rear end", "tail lamp", "tailgate"])
        fnol_mentions_front = any(k in desc_lower for k in ["front bumper", "headlamp", "headlight", "bonnet", "windshield"])
        if fnol_mentions_rear and not fnol_mentions_front and "rear" not in uploaded_angles and "front" in uploaded_angles:
            inconsistencies.append(
                {
                    "inconsistency_id": "inc-fnol-photo-loc",
                    "type": "fnol_vs_photo_location_mismatch",
                    "severity": "high",
                    "summary": "FNOL describes rear-end damage, but uploaded photos only capture front angle (no rear photo).",
                    "affected_components": ["Rear Bumper Assembly (Primed)", "Tail Lamp Assembly LED"],
                    "evidence_refs": [im["filename"] for im in normalized_images],
                    "resolution_required": "Request rear & rear-closeup photos and route to human assessor for reconciliation.",
                }
            )
        if fnol_mentions_front and not fnol_mentions_rear and "front" not in uploaded_angles and "rear" in uploaded_angles:
            inconsistencies.append(
                {
                    "inconsistency_id": "inc-fnol-photo-loc-front",
                    "type": "fnol_vs_photo_location_mismatch",
                    "severity": "high",
                    "summary": "FNOL describes front-end damage, but uploaded photos only show rear angle (no front photo).",
                    "affected_components": ["Front Bumper Assembly (Primed)"],
                    "evidence_refs": [im["filename"] for im in normalized_images],
                    "resolution_required": "Request front & closeup photos and route to human assessor for reconciliation.",
                }
            )
        if severe_bumper_cue and minor_bumper_cue:
            inconsistencies.append(
                {
                    "inconsistency_id": "inc-sev-conflict",
                    "type": "severity_overclaim_conflict",
                    "severity": "medium",
                    "summary": "Claim narrative mixes minor scuff terminology with severe replacement cues; requires visual verification.",
                    "affected_components": ["Front Bumper Assembly (Primed)"],
                    "evidence_refs": [im["filename"] for im in normalized_images],
                    "resolution_required": "Human assessor to confirm repair vs replacement on bumper skin.",
                }
            )

    inconsistent_component_names = {
        comp for inc in inconsistencies for comp in inc.get("affected_components", [])
    }

    # Build final structured observations with per-component confidence & cost estimates
    observations: list[dict[str, Any]] = []
    cross_photo_comparison: list[dict[str, Any]] = []
    seen_regions: set[str] = set()
    parts_oem_total = Decimal("0.00")
    parts_oes_total = Decimal("0.00")
    labour_total = Decimal("0.00")
    paint_total = Decimal("0.00")
    total_estimated = Decimal("0.00")
    uncertain_min_total = Decimal("0.00")
    uncertain_max_total = Decimal("0.00")
    estimate_lines: list[dict[str, Any]] = []

    for c in candidates:
        matched_ev = _matching_evidence_for_location(c["damage_location"], c["bbox_key"], normalized_images)
        has_inc = c["component_name"] in inconsistent_component_names
        is_inferred = c["observation_type"] == "inferred_possible"

        comp_conf, conf_band, conf_factors = _calibrate_component_confidence(
            overall_img_conf=image_quality_confidence,
            matching_evidence=matched_ev,
            is_inferred=is_inferred,
            is_uncertain_cue=bool(c.get("is_uncertain_cue")),
            has_inconsistency=has_inc,
            repairability=c["repairability"],
        )

        # Guardrail: if component confidence drops below 0.72 and it was leaning replace, downgrade to uncertain!
        repairability = c["repairability"]
        rec_action = c["recommended_action"]
        rationale = c["repair_vs_replace_rationale"]
        if comp_conf < 0.72 and repairability == "replace":
            repairability = "uncertain"
            rec_action = "inspect"
            rationale = (
                f"Component-level confidence ({comp_conf:.2f}) is below autonomous replacement threshold (0.72) "
                f"despite overall image confidence ({image_quality_confidence:.2f}); routed to human assessor."
            )

        cost = _cost_breakdown_for_component(c["part_code"], repairability, parts_by_code)
        parts_oem_total += Decimal(cost["parts_oem_inr"]) if repairability != "uncertain" else Decimal("0.00")
        parts_oes_total += Decimal(cost["parts_oes_inr"]) if repairability != "uncertain" else Decimal("0.00")
        labour_total += Decimal(cost["labour_inr"])
        paint_total += Decimal(cost["paint_inr"])
        if repairability == "uncertain":
            uncertain_min_total += Decimal(cost["subtotal_oes_inr"])
            uncertain_max_total += Decimal(cost["subtotal_oem_inr"])
            total_estimated += Decimal(cost["subtotal_oes_inr"])
        else:
            total_estimated += Decimal(cost["subtotal_oem_inr"])

        estimate_lines.append(
            {
                "part_code": c["part_code"],
                "damaged_component": c["damaged_component"],
                "component_name": c["component_name"],
                "repairability": repairability,
                "component_confidence": comp_conf,
                **cost,
            }
        )

        comp_quality = conf_factors["component_image_quality"]
        obs_entry = {
            "damaged_component": c["damaged_component"],
            "component_name": c["component_name"],
            "part_code": c["part_code"],
            "part_category": c["part_category"],
            "damage_location": c["damage_location"],
            "zone": c["zone"],
            "damage_severity": c["damage_severity"],
            "severity": c["severity"],
            "repairability": repairability,
            "recommended_action": rec_action,
            "damage_class": c["damage_class"],
            "observation_type": c["observation_type"],
            "visible_damage": c["visible_damage"],
            "possible_hidden_damage": c["possible_hidden_damage"],
            "image_quality": comp_quality,
            "confidence": comp_conf,
            "component_confidence": comp_conf,
            "confidence_band": conf_band,
            "confidence_factors": conf_factors,
            "evidence": matched_ev,
            "estimated_cost": cost,
            "repair_vs_replace_rationale": rationale,
            "limitations": c["limitations"],
        }
        observations.append(obs_entry)

        if c["damage_location"] not in seen_regions:
            seen_regions.add(c["damage_location"])
            angles_cov = sorted({ev["angle"] for ev in matched_ev})
            if has_inc:
                agree = "conflicting"
            elif len(angles_cov) >= 2:
                agree = "corroborated"
            elif len(angles_cov) == 1:
                agree = "single_angle_only"
            else:
                agree = "no_photo_coverage"
            cross_photo_comparison.append(
                {
                    "damage_location": c["damage_location"],
                    "zone": c["zone"],
                    "photos_covering": [ev["filename"] for ev in matched_ev],
                    "angles_covered": angles_cov,
                    "agreement_status": agree,
                    "notes": (
                        "Corroborated across multiple angles"
                        if agree == "corroborated"
                        else (
                            "Conflict detected across evidence or FNOL narrative"
                            if agree == "conflicting"
                            else (
                                "Observed in single angle only; closeup recommended if severe"
                                if agree == "single_angle_only"
                                else "No photo covering this region uploaded yet"
                            )
                        )
                    ),
                }
            )

    # Step 9: Additional photo requests
    additional_photo_requests: list[dict[str, Any]] = []
    for fname in recapture_files:
        matching_im = next((im for im in normalized_images if im["filename"] == fname), None)
        ang = matching_im["angle"] if matching_im else "front"
        additional_photo_requests.append(
            {
                "angle": ang,
                "reason_code": "RC_PHOTO_RECAPTURE_QUALITY",
                "priority": "high",
                "reason": f"Photo '{fname}' failed quality validation (recapture needed).",
                "guidance": "Retake photo in clear daylight with full panel and surrounding reference visible.",
            }
        )
    for fname in poor_files:
        matching_im = next((im for im in normalized_images if im["filename"] == fname), None)
        ang = matching_im["angle"] if matching_im else "closeup"
        additional_photo_requests.append(
            {
                "angle": ang,
                "reason_code": "RC_POOR_VISIBILITY_CLOSEUP",
                "priority": "medium",
                "reason": f"Photo '{fname}' has shadow/glare/occlusion reducing component confidence.",
                "guidance": "Upload unobstructed perpendicular close-up in daylight.",
            }
        )
    uncertain_obs = [o for o in observations if o["repairability"] == "uncertain" or o["component_confidence"] < 0.72]
    if uncertain_obs and "closeup" not in uploaded_angles:
        additional_photo_requests.append(
            {
                "angle": "closeup",
                "reason_code": "RC_UNCERTAIN_COMPONENT_CLOSEUP",
                "priority": "high",
                "reason": f"Close-up needed for uncertain component(s): {', '.join(o['damaged_component'] for o in uncertain_obs)}.",
                "guidance": "Capture 45-degree close-up showing bumper clips/brackets or panel crease depth.",
            }
        )
    if (is_ev or ev_battery_impacted) and "underbody" not in uploaded_angles:
        additional_photo_requests.append(
            {
                "angle": "underbody",
                "reason_code": "RC_EV_UNDERBODY_REQUIRED",
                "priority": "high",
                "reason": "EV traction battery impact reported; underbody & BMS diagnostic photos required.",
                "guidance": "Upload ramp/lift photo of underbody HV battery tray shield after HV isolation.",
            }
        )
    for ang in missing_angles:
        if not any(r["angle"] == ang for r in additional_photo_requests):
            additional_photo_requests.append(
                {
                    "angle": ang,
                    "reason_code": "RC_MISSING_STANDARD_ANGLE",
                    "priority": "low" if len(missing_angles) <= 3 else "medium",
                    "reason": f"Missing standard 6-angle evidence photo ({ang}).",
                    "guidance": f"Upload clear daylight '{ang}' view of the vehicle.",
                }
            )

    # Step 10: Route uncertain cases to a human assessor
    human_reasons: list[str] = []
    if recapture_files:
        human_reasons.append(f"Image quality recapture required for: {', '.join(recapture_files)}")
    if poor_files:
        human_reasons.append(f"Poor image visibility in: {', '.join(poor_files)}")
    if uncertain_obs:
        human_reasons.append(
            "Uncertain repairability / low component-level confidence on: "
            + ", ".join(f"{o['damaged_component']} ({o['component_confidence']:.2f})" for o in uncertain_obs)
        )
    if inconsistencies:
        human_reasons.append(f"{len(inconsistencies)} cross-photo / FNOL inconsistency(s) detected")
    if ev_safety_alerts:
        human_reasons.append("Mandatory EV HV isolation & physical BMS inspection required")

    route_to_human = bool(human_reasons)
    recommended_role = "ev_specialist" if ev_safety_alerts else "surveyor"

    damage_zones = sorted({o["zone"] for o in observations})
    damage_locations = sorted({o["damage_location"] for o in observations})
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

    parts_labour_estimate = {
        "rate_card_id": rate_card["rate_card_id"],
        "currency": "INR",
        "parts_oem_total_inr": f"{parts_oem_total:.2f}",
        "parts_oes_total_inr": f"{parts_oes_total:.2f}",
        "labour_total_inr": f"{labour_total:.2f}",
        "paint_total_inr": f"{paint_total:.2f}",
        "total_recommended_inr": f"{total_estimated:.2f}",
        "uncertain_exposure_min_inr": f"{uncertain_min_total:.2f}",
        "uncertain_exposure_max_inr": f"{uncertain_max_total:.2f}",
        "lines": estimate_lines,
    }

    structured_assessment_table = [
        {
            "field": "Vehicle",
            "value": vehicle["display_label"],
            "detail": f"Reg: {vehicle['registration_number']} · Detection: {vehicle['detection_status']} ({vehicle['detection_confidence']:.2f})",
        },
        {
            "field": "Damage location",
            "value": ", ".join(damage_locations) if damage_locations else "unassessed",
            "detail": f"Zones: {', '.join(damage_zones)}" if damage_zones else "No zones localized",
        },
        {
            "field": "Damaged component",
            "value": ", ".join(o["damaged_component"] for o in observations) if observations else "none",
            "detail": ", ".join(o["part_code"] for o in observations),
        },
        {
            "field": "Damage severity",
            "value": ", ".join(sorted({o["damage_severity"] for o in observations})) if observations else "unassessed",
            "detail": f"Overall severity band: {overall_severity}",
        },
        {
            "field": "Repairability",
            "value": ", ".join(f"{o['damaged_component']}: {o['repairability']}" for o in observations) if observations else "unassessed",
            "detail": f"{sum(1 for o in observations if o['repairability'] == 'uncertain')} uncertain component(s)",
        },
        {
            "field": "Visible damage",
            "value": " | ".join(o["visible_damage"] for o in observations if o["observation_type"] == "visible_observed") or "Awaiting exterior photos",
            "detail": f"{sum(1 for o in observations if o['observation_type'] == 'visible_observed')} visible_observed item(s)",
        },
        {
            "field": "Possible hidden damage",
            "value": " | ".join(dict.fromkeys(o["possible_hidden_damage"] for o in observations if o["possible_hidden_damage"])) or "None flagged",
            "detail": "Never confirmed from photos alone; requires physical inspection",
        },
        {
            "field": "Image quality",
            "value": overall_image_quality,
            "detail": f"Overall image score: {image_quality_confidence:.2f} · {len(normalized_images)} photo(s) · {len(recapture_files)} recapture",
        },
        {
            "field": "Confidence",
            "value": " | ".join(f"{o['damaged_component']}: {o['component_confidence']:.2f} ({o['confidence_band']})" for o in observations) or f"{image_quality_confidence:.2f}",
            "detail": "Per-component confidence calibrated independently of overall photo score",
        },
        {
            "field": "Evidence",
            "value": f"{sum(len(o['evidence']) for o in observations)} bounding-box ref(s) across {len(normalized_images)} image(s)",
            "detail": ", ".join(im["filename"] for im in normalized_images) or "No images uploaded yet",
        },
    ]

    visual_workflow_steps = [
        {
            "step_number": 1,
            "step_key": "upload_accident_photos",
            "title": "Upload accident photos",
            "status": "completed" if normalized_images else "pending",
            "summary": f"{len(normalized_images)} accident photo(s) ingested ({', '.join(sorted(uploaded_angles)) or 'none yet'}).",
        },
        {
            "step_number": 2,
            "step_key": "validate_image_quality",
            "title": "Validate image quality",
            "status": "warning" if (recapture_files or poor_files) else ("completed" if normalized_images else "pending"),
            "summary": f"Overall quality={overall_image_quality} ({image_quality_confidence:.2f}); recapture={len(recapture_files)}, poor={len(poor_files)}.",
        },
        {
            "step_number": 3,
            "step_key": "detect_vehicle_and_regions",
            "title": "Detect vehicle & damaged regions",
            "status": "warning" if vehicle["detection_status"] == "mismatch" else "completed",
            "summary": f"{vehicle['display_label']} ({vehicle['detection_status']}); regions={damage_locations or ['none']}.",
        },
        {
            "step_number": 4,
            "step_key": "classify_damaged_components",
            "title": "Classify damaged components",
            "status": "completed" if observations else "pending",
            "summary": f"Classified {len(observations)} component(s) with per-component confidence scores.",
        },
        {
            "step_number": 5,
            "step_key": "compare_damage_across_photos",
            "title": "Compare damage across photos",
            "status": "completed" if cross_photo_comparison else "pending",
            "summary": (
                f"{sum(1 for c in cross_photo_comparison if c['agreement_status'] == 'corroborated')} corroborated, "
                f"{sum(1 for c in cross_photo_comparison if c['agreement_status'] == 'single_angle_only')} single-angle, "
                f"{sum(1 for c in cross_photo_comparison if c['agreement_status'] == 'conflicting')} conflicting."
            ),
        },
        {
            "step_number": 6,
            "step_key": "identify_inconsistencies",
            "title": "Identify inconsistencies",
            "status": "warning" if inconsistencies else "completed",
            "summary": f"{len(inconsistencies)} inconsistency(s) detected across photos, vehicle metadata & FNOL." if inconsistencies else "Zero cross-photo or FNOL inconsistencies.",
        },
        {
            "step_number": 7,
            "step_key": "generate_repair_vs_replace",
            "title": "Repair vs replacement recommendation",
            "status": "warning" if uncertain_obs else "completed",
            "summary": (
                f"repair={sum(1 for o in observations if o['repairability'] == 'repair')}, "
                f"replace={sum(1 for o in observations if o['repairability'] == 'replace')}, "
                f"uncertain={len(uncertain_obs)}."
            ),
        },
        {
            "step_number": 8,
            "step_key": "estimate_parts_and_labour",
            "title": "Estimate parts and labour",
            "status": "completed",
            "summary": f"OEM+Labour+Paint baseline INR {total_estimated:.2f} (Rate card {rate_card['rate_card_id']}).",
        },
        {
            "step_number": 9,
            "step_key": "request_additional_photos",
            "title": "Request additional photos where necessary",
            "status": "warning" if (recapture_files or poor_files or len(missing_angles) > 3) else "completed",
            "summary": f"{len(additional_photo_requests)} photo request(s) generated ({len(missing_angles)} missing standard angles).",
        },
        {
            "step_number": 10,
            "step_key": "route_uncertain_to_human",
            "title": "Route uncertain cases to human assessor",
            "status": "needs_human" if route_to_human else "completed",
            "summary": (
                f"Routed to {recommended_role}: {'; '.join(human_reasons)}"
                if route_to_human
                else "All classified components exceed autonomous confidence threshold; ready for estimate validation."
            ),
        },
    ]

    return {
        "model_version": "cv-damage-vision-v3",
        "vehicle": vehicle,
        "observations": observations,
        "damage_zones": damage_zones,
        "damage_locations": damage_locations,
        "overall_severity": overall_severity,
        "overall_image_quality": overall_image_quality,
        "missing_angles": missing_angles,
        "recapture_required_files": recapture_files,
        "poor_quality_files": poor_files,
        "per_image_quality": per_image_quality,
        "image_quality_confidence": image_quality_confidence,
        "cross_photo_comparison": cross_photo_comparison,
        "inconsistencies": inconsistencies,
        "parts_labour_estimate": parts_labour_estimate,
        "additional_photo_requests": additional_photo_requests,
        "human_assessor_routing": {
            "route_to_human_assessor": route_to_human,
            "recommended_role": recommended_role,
            "trigger_reasons": human_reasons,
            "uncertain_components": [o["component_name"] for o in uncertain_obs],
            "confidence_guardrail_triggered": any(
                o["component_confidence"] < 0.72 and (overall_image_quality == "good" or image_quality_confidence >= 0.72)
                for o in observations
            ),
        },
        "structured_assessment_table": structured_assessment_table,
        "visual_workflow_steps": visual_workflow_steps,
        "ev_safety_alerts": ev_safety_alerts,
        "ev_safety_determination": (
            {
                "safe_to_operate": "not_determinable_from_photographs",
                "photo_only_clearance_allowed": False,
                "required_before_any_operation": (
                    "Physical inspection by an EV-HV certified surveyor, HV isolation and an OEM diagnostic scan; "
                    "release only after post-repair HV recertification (IN-EV-CLAIMS-2026)."
                ),
                "workflow": "EV claims workflow",
            }
            if (is_ev or ev_battery_impacted or ev_safety_alerts)
            else None
        ),
        "disclaimer": (
            "AI damage output is assistive only. Component-level confidence governs repairability; "
            "hidden structural damage cannot be confirmed from photographs alone."
        ),
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
        raw_action = line.get("action", "replace")
        desc_text = str(line.get("description", "")).lower()
        if raw_action == "replace" and any(w in desc_text for w in ("refinish", "repair", "denting", "buffing", "polish")) and "replace" not in desc_text:
            action = "repair"
        else:
            action = raw_action
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
