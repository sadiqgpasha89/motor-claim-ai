"""Multimodal damage fusion. Compares the damage zones that each source reports.

Sources: photos, FNOL narrative, estimate lines, surveyor notes and vehicle signals.
A zone that only one source reports is a contradiction to review. It is not a fraud finding.
"""
from __future__ import annotations

from typing import Any

from services.rules_engine.intelligence import intelligence_controls, intelligence_rule_version


def zones_from_text(text: str | None, zone_keywords: dict[str, list[str]]) -> set[str]:
    low = f" {(text or '').lower()} "
    return {zone for zone, words in zone_keywords.items() if any(f" {w}" in low or f"{w} " in low for w in words)}


def fuse_modalities(
    *,
    photo_part_codes: list[str],
    fnol_text: str,
    estimate_part_codes: list[str],
    surveyor_text: str = "",
    vehicle_signals: dict[str, bool] | None = None,
) -> dict[str, Any]:
    ctl = intelligence_controls()["multimodal"]
    zone_of = ctl["part_zone"]
    side_zones = {"front", "rear", "underbody"}
    keywords = ctl["zone_keywords"]

    zones: dict[str, set[str]] = {
        "photos": {zone_of[c] for c in photo_part_codes if c in zone_of},
        "fnol_narrative": zones_from_text(fnol_text, keywords),
        "estimate": {zone_of[c] for c in estimate_part_codes if c in zone_of},
        "surveyor_notes": zones_from_text(surveyor_text, keywords),
    }
    signals = vehicle_signals or {}
    zones["vehicle_signals"] = {"front"} if signals.get("airbags_deployed") else set()
    present = {m: z for m, z in zones.items() if z}

    # A zone is "agreed" when at least two sources report it. Left/right are compared with the primary zones.
    votes: dict[str, list[str]] = {}
    for modality, zset in present.items():
        for z in zset:
            votes.setdefault(z, []).append(modality)
    agreed = {z for z, mods in votes.items() if len(mods) >= 2}

    contradictions: list[dict[str, Any]] = []
    if len(present) >= int(ctl["min_modalities"]):
        for modality, zset in present.items():
            # Side zones are compared as primary zones. A left or right mention alone is a weak cue.
            strong = {z for z in zset if z in side_zones} or zset
            if agreed and not (strong & agreed):
                contradictions.append({
                    "modality": modality,
                    "reported_zones": sorted(zset),
                    "agreed_zones": sorted(agreed),
                    "message": f"{modality} reports {sorted(zset)}, which no other source supports.",
                })

    total_w = sum(float(ctl["modality_weights"][m]) for m in present) or 1.0
    support = sum(float(ctl["modality_weights"][m]) for m in present if not any(c["modality"] == m for c in contradictions))
    confidence = support / total_w
    confidence -= float(ctl["contradiction_penalty"]) * len(contradictions)
    if len(present) < int(ctl["min_modalities"]):
        confidence = min(confidence, 0.5)
    confidence = round(max(0.0, min(1.0, confidence)), 3)

    return {
        "modalities_present": sorted(present),
        "modalities_missing": sorted(m for m in zones if m not in present),
        "zones_by_modality": {m: sorted(z) for m, z in zones.items()},
        "agreed_zones": sorted(agreed),
        "contradictions": contradictions,
        "fused_confidence": confidence,
        "human_review_required": bool(contradictions) or len(present) < int(ctl["min_modalities"]),
        "rule_version": intelligence_rule_version(),
    }
