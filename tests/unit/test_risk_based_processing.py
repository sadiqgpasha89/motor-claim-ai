from __future__ import annotations

from decimal import Decimal

import pytest

from packages.contracts.errors import DomainError
from services.workflow.risk_engine import (
    assert_fraud_score_never_rejects,
    classify_claim_risk_from_facts,
)
from tests.conftest import auth_headers


def _base_low_risk_facts() -> dict:
    return {
        "effective_loss_inr": "18500.00",
        "estimated_loss_inr": "18500.00",
        "idv_inr": "780000.00",
        "claim_type": "cashless",
        "peril_cause": "road_accident",
        "claim_status": "REGISTERED",
        "injury_or_fatality": False,
        "multiple_vehicles_involved": False,
        "involved_vehicles_count": 1,
        "ev_battery_impacted": False,
        "airbags_deployed": False,
        "vehicle_immobile": False,
        "towing_needed": False,
        "legal_dispute": False,
        "policy_matched": True,
        "policy_active": True,
        "period_valid": True,
        "missing_documents": [],
        "has_doc_mismatch": False,
        "prompt_injection_flagged": False,
        "doc_conflict_count": 0,
        "duplicate_candidate_claim_id": None,
        "has_recapture_needed": False,
        "hidden_damage_found": False,
        "has_severe_structural_damage": False,
        "has_inspection_required_damage": False,
        "estimate_anomalies": [],
        "estimate_overcharge_inr": "0.00",
        "has_supplement_estimate": False,
        "coverage_clarifications": [],
        "open_dispute_grievance_count": 0,
        "has_assigned_garage": True,
        "fraud_alerts": [],
    }


def test_deterministic_risk_tier_classification_across_all_three_paths():
    # 1. LOW RISK -> fast_track & straight-through <= 25,000 limit
    low = classify_claim_risk_from_facts(_base_low_risk_facts(), trigger_event="unit_low")
    assert low["risk_tier"] == "LOW"
    assert low["operational_path"] == "fast_track"
    assert all(low["low_risk_criteria_check"].values()) is True
    assert low["automation_eligibility"]["straight_through_eligible"] is True
    assert low["automation_eligibility"]["within_auto_approval_limit"] is True
    assert low["automation_eligibility"]["requires_mandatory_survey"] is False
    assert low["fraud_score_can_reject"] is False

    # LOW RISK between 25,000.01 and 49,999.99: straight-through fast_track, but above automated limit
    mid_low = {**_base_low_risk_facts(), "effective_loss_inr": "38000.00", "estimated_loss_inr": "38000.00"}
    low_over_limit = classify_claim_risk_from_facts(mid_low, trigger_event="unit_low_assisted")
    assert low_over_limit["risk_tier"] == "LOW"
    assert low_over_limit["operational_path"] == "fast_track"
    assert low_over_limit["automation_eligibility"]["straight_through_eligible"] is True
    assert low_over_limit["automation_eligibility"]["within_auto_approval_limit"] is False

    # 2. MEDIUM RISK -> every standard claims driver
    for mut, expected_code in [
        ({"effective_loss_inr": "65000.00"}, "MEDIUM_DAMAGE_REQUIRES_INSPECTION"),
        ({"estimate_anomalies": [{"type": "rate_variance"}]}, "MEDIUM_ESTIMATE_DISCREPANCIES"),
        ({"missing_documents": ["Driving Licence (DL)"]}, "MEDIUM_MISSING_DOCUMENTS"),
        ({"coverage_clarifications": ["Verify consumables clause"]}, "MEDIUM_COVERAGE_CLARIFICATION"),
        ({"towing_needed": True}, "MEDIUM_REPAIR_COORDINATION"),
    ]:
        med = classify_claim_risk_from_facts({**_base_low_risk_facts(), **mut})
        assert med["risk_tier"] == "MEDIUM"
        assert med["operational_path"] == "standard"
        assert expected_code in {d["code"] for d in med["drivers"]}

    # 3. HIGH RISK -> every complex/investigation driver
    high_cases = [
        ({"injury_or_fatality": True}, "HIGH_INJURY_OR_TP_LIABILITY"),
        ({"multiple_vehicles_involved": True, "involved_vehicles_count": 3}, "HIGH_INJURY_OR_TP_LIABILITY"),
        (
            {
                "fraud_alerts": [
                    {"indicator_code": "FRD-ENTITY-RING-CLUSTER", "severity_band": "high", "confidence": "0.89", "status": "new"}
                ]
            },
            "HIGH_SUSPECTED_FRAUD",
        ),
        ({"effective_loss_inr": "280000.00"}, "HIGH_SIGNIFICANT_LOSS"),
        ({"has_doc_mismatch": True}, "HIGH_CONFLICTING_EVIDENCE"),
        ({"ev_battery_impacted": True}, "HIGH_EV_BATTERY_DAMAGE"),
        ({"legal_dispute": True}, "HIGH_LEGAL_OR_COVERAGE_DISPUTE"),
        ({"policy_active": False}, "HIGH_LEGAL_OR_COVERAGE_DISPUTE"),
    ]
    for mut, expected_code in high_cases:
        high = classify_claim_risk_from_facts({**_base_low_risk_facts(), **mut})
        assert high["risk_tier"] == "HIGH"
        assert high["operational_path"] == "complex_investigation"
        assert high["automation_eligibility"]["evidence_preservation_active"] is True
        assert high["fraud_score_can_reject"] is False
        assert expected_code in {d["code"] for d in high["drivers"]}


def test_fraud_score_guardrail_never_auto_rejects():
    with pytest.raises(DomainError) as exc_info:
        assert_fraud_score_never_rejects(
            decision="rejected",
            fraud_signal_score=Decimal("0.920"),
            rationale="auto_reject_fraud due to fraud_score",
        )
    assert exc_info.value.status_code == 409

    # Valid non-rejecting risk classification with extreme fraud alerts never sets reject
    res = classify_claim_risk_from_facts(
        {
            **_base_low_risk_facts(),
            "fraud_alerts": [
                {"indicator_code": "FRD-IMG-HASH-REUSE", "severity_band": "high", "confidence": "0.95", "status": "new"}
            ],
        }
    )
    assert Decimal(res["fraud_signal_score"]) >= Decimal("0.900")
    assert res["fraud_score_can_reject"] is False
    assert res["risk_tier"] == "HIGH"


def test_low_risk_fast_track_straight_through_and_auto_approval_e2e(client):
    handler_hdrs = auth_headers(client, "handler@demo.in")
    finance_hdrs = auth_headers(client, "finance@demo.in")
    fnol_resp = client.post(
        "/api/v1/claims/intimations",
        json={
            "policy_number": "POL-IN-DEMO-2026-FT01",
            "vehicle_reg": "MH12FT2026",
            "claim_type": "cashless",
            "peril_cause": "road_accident",
            "incident_location": "Juhu, Mumbai",
            "incident_description": "Minor scratch on front bumper and LH mirror cap.",
            "estimated_loss_inr": "14000.00",
            "documents_complete_at_fnol": True,
        },
        headers=handler_hdrs,
    )
    assert fnol_resp.status_code == 201
    claim_id = fnol_resp.json()["claim"]["id"]
    assert fnol_resp.json()["claim"]["risk_tier"] == "LOW"
    assert fnol_resp.json()["claim"]["operational_path"] == "fast_track"

    # Upload complete RC doc + clean damage photo for document reconciliation & visual assessment
    r_rc = client.post(
        f"/api/v1/claims/{claim_id}/evidence",
        files={
            "file": (
                "rc_ft.txt",
                b"Registration Certificate Vehicle MH12FT2026 Policy POL-IN-DEMO-2026-FT01 Verified",
                "text/plain",
            )
        },
        headers=handler_hdrs,
    )
    assert r_rc.status_code == 201
    for fname, content in [
        ("front_daylight.jpg", b"clean daylight photo front"),
        ("left_daylight.jpg", b"clean daylight photo left"),
        ("closeup_daylight.jpg", b"clean daylight photo closeup"),
    ]:
        r_photo = client.post(
            f"/api/v1/claims/{claim_id}/evidence",
            files={"file": (fname, content, "image/jpeg")},
            headers=handler_hdrs,
        )
        assert r_photo.status_code == 201
        assert r_photo.json()["legal_hold"] is False

    # First orchestration pass: runs Wave 1, Triage -> FAST_TRACK, skips provider_coordination, stops for estimate
    orch1 = client.post(
        f"/api/v1/claims/{claim_id}/orchestrate",
        json={"stop_on_human_gate": True},
        headers=handler_hdrs,
    )
    assert orch1.status_code == 200
    assert orch1.json()["workflow_state"]["stage_statuses"].get("provider_coordination") == "skipped_fast_track"

    # Submit clean estimate <= 25,000
    est_resp = client.post(
        f"/api/v1/claims/{claim_id}/estimates",
        json={
            "lines": [
                {
                    "part_code": "PRT-FRT-BMP-01",
                    "description": "Front Bumper Minor Refinish",
                    "part_category": "plastic_rubber",
                    "line_type": "part",
                    "quantity": 1,
                    "unit_price_inr": "12000.00",
                }
            ]
        },
        headers=handler_hdrs,
    )
    assert est_resp.status_code == 201

    # Resume orchestration -> straight-through auto-approved within INR 25,000 limit!
    orch2 = client.post(
        f"/api/v1/claims/{claim_id}/orchestrate",
        json={"stop_on_human_gate": True},
        headers=handler_hdrs,
    )
    assert orch2.status_code == 200
    assert orch2.json()["claim_status"] == "APPROVED"

    detail = client.get(f"/api/v1/claims/{claim_id}", headers=handler_hdrs).json()
    assert detail["claim"]["risk_tier"] == "LOW"
    assert any(a["action_type"] == "fast_track_auto_approval" and a["decision"] == "approved" for a in detail["approvals"])

    # Finance executes payout & closes straight-through claim cleanly (without requiring physical surveyor)
    stl_id = detail["settlements"][0]["id"]
    r_pay = client.post(
        f"/api/v1/claims/{claim_id}/payments",
        json={
            "settlement_id": stl_id,
            "idempotency_key": "fast-track-pay-001",
            "payee_type": "customer",
            "payee_name": "Aarav Deshmukh",
        },
        headers=finance_hdrs,
    )
    assert r_pay.status_code == 201
    r_close = client.post(f"/api/v1/claims/{claim_id}/close", headers=handler_hdrs)
    assert r_close.status_code == 200
    assert r_close.json()["claim_status"] == "CLOSED"


def test_dynamic_risk_recalculation_low_to_high_and_non_rejection_api(client):
    handler_hdrs = auth_headers(client, "handler@demo.in")
    manager_hdrs = auth_headers(client, "manager@demo.in")
    garage_hdrs = auth_headers(client, "garage@demo.in")

    # 1. Start as clean LOW RISK fast-track claim
    r_fnol = client.post(
        "/api/v1/claims/intimations",
        json={
            "policy_number": "POL-IN-DEMO-2026-FT01",
            "vehicle_reg": "MH12FT2026",
            "claim_type": "cashless",
            "peril_cause": "road_accident",
            "incident_location": "Bandra, Mumbai",
            "incident_description": "Minor bumper scrape reported on hotline.",
            "estimated_loss_inr": "19500.00",
            "documents_complete_at_fnol": True,
        },
        headers=handler_hdrs,
    )
    assert r_fnol.status_code == 201
    claim_id = r_fnol.json()["claim"]["id"]
    assert r_fnol.json()["claim"]["risk_tier"] == "LOW"

    r_up = client.post(
        f"/api/v1/claims/{claim_id}/evidence",
        files={"file": ("spot_front.jpg", b"clean front view", "image/jpeg")},
        headers=handler_hdrs,
    )
    assert r_up.status_code == 201
    assert r_up.json()["legal_hold"] is False

    # 2. Attempting to reject purely from fraud score is BLOCKED (409)
    r_bad_reject = client.post(
        f"/api/v1/claims/{claim_id}/risk/recalculate",
        json={
            "trigger_event": "auto_reject_fraud_score",
            "fraud_signal_score_override_attempt": "0.880",
            "decision_requested": "rejected",
        },
        headers=handler_hdrs,
    )
    assert r_bad_reject.status_code == 409
    assert r_bad_reject.json()["error_code"] == "HUMAN_REVIEW_REQUIRED"

    # 3. Late arriving evidence (multi-vehicle + EV battery + high fraud lead) dynamically escalates LOW -> HIGH
    r_esc = client.post(
        f"/api/v1/claims/{claim_id}/risk/recalculate",
        json={
            "trigger_event": "late_bms_and_multi_vehicle_evidence",
            "multiple_vehicles_involved": True,
            "involved_vehicles_count": 3,
            "ev_battery_impacted": True,
            "fraud_signal_score_override_attempt": "0.860",
            "new_evidence_summary": "Spot panchanama confirms 3 vehicles; underbody BMS shows HV pack impact.",
        },
        headers=handler_hdrs,
    )
    assert r_esc.status_code == 200
    body = r_esc.json()
    assert body["risk_tier"] == "HIGH"
    assert body["operational_path"] == "complex_investigation"
    assert body["fraud_score_can_reject"] is False
    assert body["preserved_evidence_count"] >= 1
    assert len(body["risk_history"]) >= 2
    assert body["risk_history"][0]["new_tier"] == "LOW"
    assert body["risk_history"][-1]["new_tier"] == "HIGH"

    # 4. Check rules, analytics & ABAC redaction on seeded clm-demo-0001
    rules_resp = client.get("/api/v1/rules", headers=manager_hdrs)
    assert rules_resp.status_code == 200
    assert any(r["rule_id"] == "IN-RISK-PROCESSING-2026" for r in rules_resp.json()["items"])

    analytics = client.get("/api/v1/operations/analytics", headers=manager_hdrs)
    assert analytics.status_code == 200
    assert analytics.json()["by_risk_tier"]["LOW"] >= 1
    assert analytics.json()["by_risk_tier"]["HIGH"] >= 1

    r_garage_risk = client.get("/api/v1/claims/clm-demo-0001/risk", headers=garage_hdrs)
    assert r_garage_risk.status_code == 200
    assert r_garage_risk.json()["siu_redacted"] is True
    assert r_garage_risk.json()["fraud_signal_score"] is None

    # 5. Late evidence arriving even AFTER LOW-risk auto-approval supersedes approval and escalates to HIGH
    r_auto_esc = client.post(
        "/api/v1/claims/clm-demo-0012/risk/recalculate",
        json={
            "trigger_event": "post_approval_conflicting_evidence",
            "legal_dispute": True,
            "new_evidence_summary": "Policyholder notice of legal dispute received before payout.",
        },
        headers=manager_hdrs,
    )
    assert r_auto_esc.status_code == 200
    assert r_auto_esc.json()["risk_tier"] == "HIGH"
    assert r_auto_esc.json()["claim_status"] == "INVESTIGATION_REQUIRED"

    # L1 handler blocked on HIGH risk settlement approval (high_risk_complex in IN-DOA-MATRIX-2026)
    checker_hdrs = auth_headers(client, "handler2@demo.in")
    r_stl_12 = client.post(
        "/api/v1/claims/clm-demo-0012/settlement-recommendations",
        json={"requested_pathway": "cashless"},
        headers=handler_hdrs,
    )
    if r_stl_12.status_code == 201:
        app_id_12 = r_stl_12.json()["approval_id"]
        r_l1_blocked = client.post(
            "/api/v1/claims/clm-demo-0012/approvals",
            json={"approval_id": app_id_12, "decision": "approved", "rationale": "L1 attempt on HIGH risk"},
            headers=checker_hdrs,
        )
        assert r_l1_blocked.status_code == 403
        assert r_l1_blocked.json()["error_code"] == "HUMAN_REVIEW_REQUIRED"

