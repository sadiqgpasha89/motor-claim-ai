from __future__ import annotations

import io
from decimal import Decimal

from PIL import Image, ImageDraw

from agents.specialists import AGENT_REGISTRY
from packages.contracts.agents import AgentInvocationRequest, AgentStatus
from services.damage_ai.assessor import assess_damage_from_evidence
from services.document_ai.processor import check_image_quality
from tests.conftest import auth_headers


def _make_png_bytes(width: int, height: int, *, dark: bool = False, varied: bool = True) -> bytes:
    bg = (15, 15, 15) if dark else (140, 165, 195)
    img = Image.new("RGB", (width, height), color=bg)
    if varied and not dark:
        draw = ImageDraw.Draw(img)
        draw.rectangle([width // 5, height // 4, (width * 4) // 5, (height * 3) // 4], fill=(45, 70, 110), outline=(240, 240, 240))
        draw.line([(0, 0), (width, height)], fill=(250, 200, 60), width=4)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_structured_damage_assessment_and_10_step_workflow():
    report = assess_damage_from_evidence(
        claim_description="Front right bumper cracked, RH LED headlight fractured, and right fender dented.",
        is_ev=False,
        ev_battery_impacted=False,
        image_records=[
            {"id": "ev-1", "filename": "front_day.jpg", "image_angle": "front", "image_quality_status": "acceptable", "sha256": "aaa111"},
            {"id": "ev-2", "filename": "right_day.jpg", "image_angle": "right", "image_quality_status": "acceptable", "sha256": "bbb222"},
            {"id": "ev-3", "filename": "closeup_day.jpg", "image_angle": "closeup", "image_quality_status": "acceptable", "sha256": "ccc333"},
        ],
        vehicle_info={
            "make": "Maruti Suzuki",
            "model": "Baleno",
            "variant": "Alpha AGS",
            "year": 2024,
            "registration_number": "MH02DEMO1042",
            "is_ev": False,
        },
    )

    # Vehicle structured fields
    assert report["vehicle"]["make"] == "Maruti Suzuki"
    assert report["vehicle"]["model"] == "Baleno"
    assert report["vehicle"]["variant"] == "Alpha AGS"
    assert report["vehicle"]["detection_status"] == "matched"

    # 10-step visual workflow
    steps = report["visual_workflow_steps"]
    assert len(steps) == 10
    assert [s["step_number"] for s in steps] == list(range(1, 11))

    # 10-field structured table
    table_fields = {r["field"] for r in report["structured_assessment_table"]}
    assert {
        "Vehicle",
        "Damage location",
        "Damaged component",
        "Damage severity",
        "Repairability",
        "Visible damage",
        "Possible hidden damage",
        "Image quality",
        "Confidence",
        "Evidence",
    } <= table_fields

    # Every component carries location, severity, repairability, visible/hidden, quality, per-component confidence, bbox evidence
    assert len(report["observations"]) >= 3
    for obs in report["observations"]:
        assert obs["damage_location"]
        assert obs["damaged_component"] in {"Bumper", "Headlight", "Fender"}
        assert obs["damage_severity"] in {"minor", "moderate", "severe"}
        assert obs["repairability"] in {"repair", "replace", "uncertain"}
        assert obs["visible_damage"]
        assert obs["possible_hidden_damage"]
        assert obs["image_quality"] in {"good", "poor", "recapture"}
        assert 0.0 < obs["component_confidence"] <= 1.0
        assert len(obs["evidence"]) >= 1
        assert "bbox" in obs["evidence"][0]
        assert "norm_x" in obs["evidence"][0]["bbox"]

    # Parts & labour estimate computed from RC-IN-2026-DEMO-V1
    est = report["parts_labour_estimate"]
    assert est["rate_card_id"] == "RC-IN-2026-DEMO-V1"
    assert Decimal(est["total_recommended_inr"]) > Decimal("0.00")


def test_component_level_confidence_guardrail_prevents_overclaiming_on_high_image_quality():
    # High-quality crisp daylight images (overall quality >= 0.85), yet bumper mounting tabs are shadowed/uncertain!
    report = assess_damage_from_evidence(
        claim_description="Front right LED headlight shattered; front bumper corner partially shadowed and mounting alignment uncertain.",
        is_ev=False,
        ev_battery_impacted=False,
        image_records=[
            {"id": "img-1", "filename": "front_daylight.jpg", "image_angle": "front", "image_quality_status": "acceptable", "sha256": "h1"},
            {"id": "img-2", "filename": "right_daylight.jpg", "image_angle": "right", "image_quality_status": "acceptable", "sha256": "h2"},
            {"id": "img-3", "filename": "closeup_headlight.jpg", "image_angle": "closeup", "image_quality_status": "acceptable", "sha256": "h3"},
        ],
    )
    assert report["overall_image_quality"] == "good"
    assert report["image_quality_confidence"] >= 0.78

    by_comp = {o["damaged_component"]: o for o in report["observations"]}
    assert by_comp["Headlight"]["repairability"] == "replace"
    assert by_comp["Headlight"]["component_confidence"] >= 0.85

    # Crucial requirement: Bumper must NOT be claimed beyond repair just because overall image confidence is high!
    assert by_comp["Bumper"]["repairability"] == "uncertain"
    assert by_comp["Bumper"]["component_confidence"] < 0.72
    assert report["human_assessor_routing"]["route_to_human_assessor"] is True
    assert report["human_assessor_routing"]["confidence_guardrail_triggered"] is True
    assert any("Bumper" in u for u in report["human_assessor_routing"]["uncertain_components"])

    # Agent returns NEEDS_HUMAN and creates human assessor ClaimTask + photo request
    agent = AGENT_REGISTRY["damage_assessment"]
    resp = agent.execute(
        AgentInvocationRequest(
            tenant_id="t1",
            claim_id="c1",
            correlation_id="corr-dmg-1",
            workflow_run_id="wf-dmg-1",
            actor_user_id="u1",
            actor_role="surveyor",
            minimised_facts={"assessment_payload": report},
            allowed_tools=sorted(agent.allowed_tools),
        )
    )
    assert resp.status == AgentStatus.NEEDS_HUMAN
    assert resp.decision is not None
    assert "RC_COMPONENT_UNCERTAINTY_GUARDRAIL" in resp.decision.reason_codes
    assert any(a.action_type == "create_claim_task" for a in resp.actions_executed)


def test_cross_photo_inconsistencies_and_pil_image_quality_validation():
    # Real PIL image checks: good vs low-res recapture vs dark recapture
    good_q = check_image_quality("front_daylight.png", _make_png_bytes(640, 480))
    assert good_q["normalized_quality"] == "good"

    small_q = check_image_quality("front_tiny.png", _make_png_bytes(160, 120))
    assert small_q["normalized_quality"] == "recapture"
    assert small_q["quality_status"] == "recapture_needed"

    dark_q = check_image_quality("front_night.png", _make_png_bytes(640, 480, dark=True))
    assert dark_q["normalized_quality"] == "recapture"

    poor_q = check_image_quality("front_shadow_glare.jpg", b"synthetic")
    assert poor_q["normalized_quality"] == "poor"

    # FNOL describes rear bumper collision while uploaded photos only show front angle + duplicate hash + wrong vehicle make
    inc_report = assess_damage_from_evidence(
        claim_description="Rear bumper and tail lamp damaged in rear-end collision.",
        is_ev=False,
        ev_battery_impacted=False,
        image_records=[
            {"id": "i1", "filename": "front_hyundai_creta.jpg", "image_angle": "front", "image_quality_status": "acceptable", "sha256": "samehash999"},
            {"id": "i2", "filename": "closeup_dup.jpg", "image_angle": "closeup", "image_quality_status": "acceptable", "sha256": "samehash999"},
        ],
        vehicle_info={"make": "Maruti Suzuki", "model": "Baleno", "registration_number": "MH02DEMO1042"},
    )
    inc_types = {i["type"] for i in inc_report["inconsistencies"]}
    assert "fnol_vs_photo_location_mismatch" in inc_types
    assert "duplicate_photo_hash" in inc_types
    assert "vehicle_identity_mismatch" in inc_types
    assert inc_report["human_assessor_routing"]["route_to_human_assessor"] is True


def test_damage_ai_api_upload_assess_and_route_uncertain_e2e(client):
    handler_hdrs = auth_headers(client, "handler@demo.in")
    surveyor_hdrs = auth_headers(client, "surveyor@demo.in")

    # 1. Create claim with shadowed/uncertain bumper alongside clear headlight crack
    r_fnol = client.post(
        "/api/v1/claims/intimations",
        json={
            "policy_number": "POL-IN-DEMO-2026-1001",
            "vehicle_reg": "MH02DEMO1042",
            "claim_type": "cashless",
            "peril_cause": "road_accident",
            "incident_location": "Worli Sea Face, Mumbai",
            "incident_description": "RH LED headlight cracked; front bumper lower mounting alignment uncertain in shadow.",
            "estimated_loss_inr": "52000.00",
        },
        headers=handler_hdrs,
    )
    assert r_fnol.status_code == 201
    claim_id = r_fnol.json()["claim"]["id"]

    # 2. Upload crisp daylight PNGs (front + closeup)
    good_png = _make_png_bytes(640, 480)
    for fname in ["front_daylight.png", "closeup_headlight.png"]:
        r_up = client.post(
            f"/api/v1/claims/{claim_id}/evidence",
            files={"file": (fname, good_png, "image/png")},
            headers=handler_hdrs,
        )
        assert r_up.status_code == 201
        assert r_up.json()["image_quality"]["normalized_quality"] == "good"

    # 3. Assign surveyor and run Damage Assessment AI -> persists structured report + routes uncertain bumper to human assessor
    r_surv = client.post(
        f"/api/v1/claims/{claim_id}/surveyor-assignments",
        json={"surveyor_id": "prov-surv-01", "garage_id": "prov-gar-01"},
        headers=handler_hdrs,
    )
    assert r_surv.status_code == 200
    r_dmg = client.post(f"/api/v1/claims/{claim_id}/damage-assessments", headers=surveyor_hdrs)
    assert r_dmg.status_code == 200
    body = r_dmg.json()
    assert body["agent_response"]["status"] == "needs_human"
    report = body["damage_report"]
    assert len(report["visual_workflow_steps"]) == 10
    assert report["human_assessor_routing"]["route_to_human_assessor"] is True

    # 4. Verify Claim 360 exposes structured damage_report & enriched damage_assessments
    r_c360 = client.get(f"/api/v1/claims/{claim_id}", headers=handler_hdrs)
    assert r_c360.status_code == 200
    c360 = r_c360.json()
    assert c360["damage_report"]["vehicle"]["make"] == "Maruti Suzuki"
    assert len(c360["damage_assessments"]) >= 2
    bumper_row = next(d for d in c360["damage_assessments"] if "Bumper" in d["component_name"])
    assert bumper_row["repairability"] == "uncertain"
    assert Decimal(bumper_row["confidence"]) < Decimal("0.72")
    assert len(bumper_row["evidence_refs"]) >= 1
    assert any(t["task_type"] == "human_damage_assessment" for t in c360["tasks"])
