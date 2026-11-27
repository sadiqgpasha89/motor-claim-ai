from __future__ import annotations

from agents.specialists import AGENT_REGISTRY
from packages.contracts.agents import AgentInvocationRequest, AgentStatus
from tests.conftest import auth_headers


def test_motor_claim_tracker_and_all_10_proactive_triggers_multilingual():
    triggers = [
        ("documents_missing", "Driving Licence"),
        ("photos_insufficient", "blurry_front.jpg"),
        ("survey_scheduled", "R. K. Sharma"),
        ("surveyor_delayed", "SLA"),
        ("estimate_approved", "48,700"),
        ("repair_begins", "body_paint"),
        ("parts_delayed", "Radiator Support"),
        ("settlement_awaiting_approval", "47,700"),
        ("payment_processed", "PG-UTR-9911"),
        ("claim_closed", "closed"),
    ]
    agent = AGENT_REGISTRY["customer_communication"]

    for idx, (trig, expected_token) in enumerate(triggers):
        lang = ["en-IN", "hi-IN", "mr-IN", "ta-IN", "kn-IN"][idx % 5]
        resp = agent.execute(
            AgentInvocationRequest(
                tenant_id="tenant-in-demo",
                claim_id="clm-cx-unit",
                correlation_id=f"corr-cx-{idx}",
                workflow_run_id="wf-cx-unit",
                actor_user_id="usr-handler",
                actor_role="claims_handler",
                locale=lang,
                minimised_facts={
                    "claim_number": "CLM-CX-UNIT-01",
                    "vehicle_reg": "MH02DEMO1042",
                    "claim_status": "SURVEY_REQUIRED",
                    "trigger_event": trig,
                    "language": lang,
                    "channel": "whatsapp",
                    "consent_whatsapp": True,
                    "missing_documents": ["Driving Licence"],
                    "photo_issue_details": ["blurry_front.jpg"],
                    "surveyor_name": "R. K. Sharma",
                    "inspection_slot_label": "28 Nov 2026, 11:00 UTC",
                    "delay_reason": "SLA deadline exceeded",
                    "garage_name": "Garage A — Apex Motors",
                    "approved_estimate_label": "₹48,700.00",
                    "repair_stage_label": "body_paint",
                    "delayed_parts_label": "Radiator Support",
                    "parts_eta_days": 5,
                    "settlement_net_label": "₹47,700.00",
                    "approval_gate_label": "Claims Checker",
                    "payment_amount_label": "₹47,700.00",
                    "payment_utr": "PG-UTR-9911",
                },
                allowed_tools=sorted(agent.allowed_tools),
            )
        )
        assert resp.status == AgentStatus.COMPLETED
        assert resp.result["trigger_event"] == trig
        assert resp.result["language"] == lang
        assert resp.result["effective_channel"] == "whatsapp"
        assert resp.result["whatsapp_blocked_no_consent"] is False
        assert resp.result["human_escalation_available"] is True
        assert resp.result["draft_message"]
        if lang == "en-IN":
            assert expected_token.lower() in resp.result["draft_message"].lower()


def test_whatsapp_consent_guardrail_blocks_unconsented_whatsapp():
    agent = AGENT_REGISTRY["customer_communication"]
    resp = agent.execute(
        AgentInvocationRequest(
            tenant_id="tenant-in-demo",
            claim_id="clm-cx-consent",
            correlation_id="corr-consent",
            workflow_run_id="wf-cx-consent",
            actor_user_id="usr-handler",
            actor_role="claims_handler",
            minimised_facts={
                "claim_number": "CLM-CX-CONSENT-01",
                "vehicle_reg": "MH02DEMO1042",
                "trigger_event": "survey_scheduled",
                "language": "en-IN",
                "channel": "whatsapp",
                "consent_whatsapp": False,
                "consent_email": True,
                "surveyor_name": "R. K. Sharma",
            },
            allowed_tools=sorted(agent.allowed_tools),
        )
    )
    assert resp.status == AgentStatus.COMPLETED
    assert resp.result["whatsapp_blocked_no_consent"] is True
    assert resp.result["effective_channel"] == "email"
    assert "RC_WHATSAPP_CONSENT_REQUIRED" in resp.decision.reason_codes


def test_customer_experience_api_journey_preferences_consent_and_escalation(client):
    ph_hdrs = auth_headers(client, "policyholder@demo.in")
    handler_hdrs = auth_headers(client, "handler@demo.in")
    other_hdrs = auth_headers(client, "other@other.in")

    # 1. Create a fresh claim as policyholder with missing docs
    r_fnol = client.post(
        "/api/v1/claims/intimations",
        json={
            "policy_number": "POL-IN-DEMO-2026-1001",
            "vehicle_reg": "MH02DEMO1042",
            "claim_type": "cashless",
            "peril_cause": "road_accident",
            "incident_location": "Andheri West, Mumbai",
            "incident_description": "Front bumper scratch and headlamp cracked.",
            "estimated_loss_inr": "56000.00",
            "preferred_language": "en-IN",
            "preferred_channel": "whatsapp",
            "whatsapp_consent": True,
        },
        headers={**ph_hdrs, "Idempotency-Key": "cx-e2e-001"},
    )
    assert r_fnol.status_code == 201, r_fnol.text
    claim_id = r_fnol.json()["claim"]["id"]

    # 2. Inspect 5-stage Motor Claim Tracker & proactive intelligence
    r_cx = client.get(f"/api/v1/claims/{claim_id}/customer-experience", headers=ph_hdrs)
    assert r_cx.status_code == 200, r_cx.text
    cx_data = r_cx.json()
    stages = cx_data["journey"]["stages"]
    assert [s["key"] for s in stages] == [
        "claim_registered",
        "documents_verified",
        "vehicle_inspection",
        "repair_approval",
        "repair_and_settlement",
    ]
    assert stages[0]["title"] == "Claim registered"
    assert "accident claim submitted" in stages[0]["detail"].lower()
    assert stages[1]["status"] == "action_required"
    assert cx_data["intelligence"]["primary_trigger"] == "documents_missing"
    assert len(cx_data["intelligence"]["trigger_matrix"]) == 10

    # 3. Update preferences: switch language to Hindi and revoke WhatsApp consent
    r_pref = client.patch(
        f"/api/v1/claims/{claim_id}/customer-preferences",
        json={
            "preferred_language": "hi-IN",
            "preferred_channel": "whatsapp",
            "consent_whatsapp": False,
        },
        headers=ph_hdrs,
    )
    assert r_pref.status_code == 200, r_pref.text
    assert r_pref.json()["preferences"]["preferred_language"] == "hi-IN"
    assert r_pref.json()["preferences"]["consent_whatsapp"] is False
    assert r_pref.json()["journey"]["stages"][0]["title"] == "दावा पंजीकृत"

    # 4. Attempt proactive WhatsApp update while opted out -> blocked & fell back safely
    r_pro_blocked = client.post(
        f"/api/v1/claims/{claim_id}/proactive-updates",
        json={"trigger_event": "documents_missing", "channel": "whatsapp", "language": "hi-IN", "force": True},
        headers=handler_hdrs,
    )
    assert r_pro_blocked.status_code == 201, r_pro_blocked.text
    assert r_pro_blocked.json()["whatsapp_blocked_no_consent"] is True
    assert r_pro_blocked.json()["channel"] != "whatsapp"

    # 5. Re-enable WhatsApp consent -> WhatsApp delivery succeeds with wamid
    r_pref_on = client.patch(
        f"/api/v1/claims/{claim_id}/customer-preferences",
        json={"consent_whatsapp": True, "preferred_language": "ta-IN"},
        headers=ph_hdrs,
    )
    assert r_pref_on.status_code == 200
    r_pro_ok = client.post(
        f"/api/v1/claims/{claim_id}/proactive-updates",
        json={"trigger_event": "survey_scheduled", "channel": "whatsapp", "language": "ta-IN", "force": True},
        headers=handler_hdrs,
    )
    assert r_pro_ok.status_code == 201, r_pro_ok.text
    assert r_pro_ok.json()["whatsapp_blocked_no_consent"] is False
    assert r_pro_ok.json()["channel"] == "whatsapp"
    assert r_pro_ok.json()["whatsapp_message_id"].startswith("wamid.DEMO-")
    assert r_pro_ok.json()["language"] == "ta-IN"

    # 6. Escalate to Human Specialist as policyholder
    r_esc = client.post(
        f"/api/v1/claims/{claim_id}/customer-escalation",
        json={
            "reason_category": "surveyor_delay",
            "notes": "Please call me in Tamil regarding surveyor arrival time.",
            "preferred_language": "ta-IN",
            "preferred_channel": "whatsapp",
        },
        headers=ph_hdrs,
    )
    assert r_esc.status_code == 201, r_esc.text
    esc_data = r_esc.json()
    assert esc_data["escalation_ref"].startswith("ESC-")
    assert esc_data["callback_language"] == "ta-IN"
    assert esc_data["callback_channel"] == "whatsapp"

    # Verify Claim 360 exposes customer_journey & human_escalations
    r_360 = client.get(f"/api/v1/claims/{claim_id}", headers=ph_hdrs)
    assert r_360.status_code == 200
    assert len(r_360.json()["customer_journey"]["stages"]) == 5
    assert len(r_360.json()["customer_experience"]["human_escalations"]) >= 1

    # 7. Cross-tenant isolation: other tenant cannot access customer-experience or escalate
    r_other = client.get(f"/api/v1/claims/{claim_id}/customer-experience", headers=other_hdrs)
    assert r_other.status_code == 403
