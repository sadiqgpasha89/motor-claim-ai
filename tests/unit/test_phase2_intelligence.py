from __future__ import annotations

from decimal import Decimal

from services.damage_ai.benchmarking import benchmark_lines, city_tier
from services.damage_ai.multimodal import fuse_modalities
from services.damage_ai.repair_replace import decide_repair_replace


def test_safety_critical_and_ev_battery_are_never_decided_from_photos():
    rad = decide_repair_replace(part_code="PRT-RAD-SUP-01", severity="minor", confidence=0.95)
    assert rad["decision"] == "replace_and_inspect" and rad["human_review_required"]
    bat = decide_repair_replace(part_code="PRT-EV-BAT-TRAY", severity="minor", confidence=0.99)
    assert bat["decision"] == "specialist_inspection" and bat["human_review_required"]


def test_plastic_minor_is_repaired_and_severe_is_replaced():
    assert decide_repair_replace(part_code="PRT-FRT-BMP-01", severity="minor", confidence=0.9)["decision"] == "repair"
    assert decide_repair_replace(part_code="PRT-FRT-BMP-01", severity="severe", confidence=0.9)["decision"] == "replace"


def test_low_confidence_needs_a_human_and_ctl_flags_near_idv():
    low = decide_repair_replace(part_code="PRT-FND-RH-01", severity="minor", confidence=0.5)
    assert low["human_review_required"]
    ctl = decide_repair_replace(
        part_code="PRT-FND-RH-01", severity="minor", confidence=0.9,
        idv_inr=Decimal("100000"), claim_repair_total_inr=Decimal("80000"),
    )
    assert ctl["constructive_total_loss"]["total_loss_review_required"] is True


def test_benchmark_applies_city_tier_and_overlap_discount():
    assert city_tier("Mumbai") == "metro" and city_tier("Nashik") == "tier2" and city_tier(None) == "tier2"
    lines = [
        {"part_code": "PRT-FND-RH-01", "line_type": "labour", "quantity": 1, "unit_price_inr": "2800"},
        {"part_code": "PRT-DOOR-RH-01", "line_type": "labour", "quantity": 1, "unit_price_inr": "2800"},
    ]
    res = benchmark_lines(lines, city="Mumbai")
    assert res["city_tier"] == "metro"
    assert any("Overlap discount" in f for ln in res["lines"] for f in ln["flags"])


def test_benchmark_flags_price_above_band_and_unknown_parts():
    lines = [
        {"part_code": "PRT-BON-01", "line_type": "part", "quantity": 1, "unit_price_inr": "30000"},
        {"part_code": "PRT-UNKNOWN", "line_type": "part", "quantity": 1, "unit_price_inr": "100"},
    ]
    res = benchmark_lines(lines)
    assert res["lines"][0]["within_band"] is False
    assert "No rate card entry" in res["lines"][1]["flags"][0]


def test_fusion_agrees_when_sources_match_and_flags_contradiction():
    ok = fuse_modalities(
        photo_part_codes=["PRT-FRT-BMP-01"], fnol_text="Front bumper scuff",
        estimate_part_codes=["PRT-FRT-BMP-01"],
    )
    assert ok["agreed_zones"] == ["front"] and not ok["contradictions"] and not ok["human_review_required"]
    bad = fuse_modalities(
        photo_part_codes=["PRT-FRT-BMP-01"], fnol_text="Front bumper scuff",
        estimate_part_codes=["PRT-RR-BMP-01"],
    )
    assert bad["contradictions"] and bad["human_review_required"]
    assert bad["fused_confidence"] < ok["fused_confidence"]


def test_fusion_with_one_modality_is_capped_and_needs_review():
    one = fuse_modalities(photo_part_codes=["PRT-FRT-BMP-01"], fnol_text="", estimate_part_codes=[])
    assert one["fused_confidence"] <= 0.5 and one["human_review_required"]
