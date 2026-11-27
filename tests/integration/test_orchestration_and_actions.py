from __future__ import annotations

from tests.conftest import auth_headers


def test_orchestration_dependency_gating_rework_retry_timeout_and_recovery(client):
    ph_hdrs = auth_headers(client, "policyholder@demo.in")
    handler_hdrs = auth_headers(client, "handler@demo.in")
    garage_hdrs = auth_headers(client, "garage@demo.in")

    # 1. Create fresh claim via WhatsApp + Hindi intake with towing
    r_fnol = client.post(
        "/api/v1/claims/intimations",
        json={
            "policy_number": "POL-IN-DEMO-2026-1001",
            "vehicle_reg": "MH02DEMO1042",
            "claim_type": "cashless",
            "peril_cause": "road_accident",
            "intake_channel": "whatsapp",
            "preferred_language": "hi-IN",
            "incident_location": "Bandra Bandstand, Mumbai",
            "incident_description": "Front bumper and fender hit; vehicle immobile.",
            "vehicle_immobile": True,
            "towing_needed": True,
            "preferred_garage_id": "prov-gar-01",
            "estimated_loss_inr": "58000.00",
        },
        headers={**ph_hdrs, "Idempotency-Key": "orch-e2e-001"},
    )
    assert r_fnol.status_code == 201
    claim_id = r_fnol.json()["claim"]["id"]
    assert r_fnol.json()["agent_response"]["result"]["normalised_channel"] == "whatsapp"

    # 2. Dependency gating: downstream settlement_recommendation MUST NOT run before upstream dependencies
    r_blocked = client.post(
        f"/api/v1/claims/{claim_id}/orchestrate/settlement_recommendation",
        json={"enforce_dependencies": True},
        headers=handler_hdrs,
    )
    assert r_blocked.status_code == 409
    assert "Dependency gate blocked" in r_blocked.json()["message"]

    # 3. Upload clean RC evidence -> runs DocumentIntelligence & unlocks downstream
    r_ev = client.post(
        f"/api/v1/claims/{claim_id}/evidence",
        files={"file": ("rc_clean.txt", b"Registration MH02DEMO1042 Policy POL-IN-DEMO-2026-1001", "text/plain")},
        headers=ph_hdrs,
    )
    assert r_ev.status_code == 201

    # 4. Run Coverage Intelligence cleanly
    r_cov = client.post(
        f"/api/v1/claims/{claim_id}/orchestrate/coverage_intelligence",
        json={"enforce_dependencies": True},
        headers=handler_hdrs,
    )
    assert r_cov.status_code == 200
    assert len(r_cov.json()["agent_response"]["result"]["coverage_matrix"]) >= 5

    # 5. Simulate transient timeout once on claim_triage -> auto-retries on attempt 2 and succeeds
    r_tri_retry = client.post(
        f"/api/v1/claims/{claim_id}/orchestrate/claim_triage",
        json={"enforce_dependencies": True, "simulate_transient_timeout_once": True},
        headers=handler_hdrs,
    )
    assert r_tri_retry.status_code == 200
    assert r_tri_retry.json()["agent_response"]["status"] == "completed"
    assert r_tri_retry.json()["agent_response"]["attempt_number"] == 2

    # 6. Simulate persistent timeout on damage_assessment -> escalates after retries
    r_dmg_to = client.post(
        f"/api/v1/claims/{claim_id}/orchestrate/damage_assessment",
        json={"enforce_dependencies": True, "simulate_timeout": True},
        headers=handler_hdrs,
    )
    assert r_dmg_to.status_code == 200
    assert r_dmg_to.json()["agent_response"]["status"] == "timed_out"
    assert r_dmg_to.json()["agent_response"]["attempt_number"] == 3

    # Verify escalation recorded and ClaimTask created
    r_orch_state = client.get(f"/api/v1/claims/{claim_id}/orchestration", headers=handler_hdrs)
    assert r_orch_state.status_code == 200
    orch_data = r_orch_state.json()
    assert len(orch_data["escalations"]) >= 1
    assert any(t["task_type"] == "orchestration_escalation" for t in orch_data["tasks"])

    # 7. Recover orchestration & run remaining ready stages up to garage estimate wait
    r_rec = client.post(
        f"/api/v1/claims/{claim_id}/orchestration/recover",
        json={"resolution_notes": "Vision gateway recovered", "resume_pipeline": True},
        headers=handler_hdrs,
    )
    assert r_rec.status_code == 200
    assert r_rec.json()["cleared_escalations"] >= 1
    assert any(s["agent_name"] == "damage_assessment" and s["status"] == "completed" for s in r_rec.json()["resumed"]["steps_executed"])

    # 8. Submit estimate & request rework back to damage_assessment
    r_est = client.post(
        f"/api/v1/claims/{claim_id}/estimates",
        json={
            "lines": [
                {"part_code": "PRT-FRT-BMP-01", "description": "Front Bumper", "line_type": "part", "action": "replace", "quantity": 1, "unit_price_inr": "12500.00"},
                {"part_code": "PRT-FND-RH-01", "description": "Fender Replace", "line_type": "part", "action": "replace", "quantity": 1, "unit_price_inr": "7800.00"},
            ]
        },
        headers=garage_hdrs,
    )
    assert r_est.status_code == 201
    assert len(r_est.json()["agent_response"]["rework_requests"]) >= 1

    r_rw = client.post(
        f"/api/v1/claims/{claim_id}/rework",
        json={
            "from_agent": "estimate_validation",
            "to_agent": "damage_assessment",
            "reason_code": "RC_VERIFY_FENDER_TEARDOWN",
            "instructions": "Confirm whether fender crease requires replacement.",
            "blocking": True,
        },
        headers=handler_hdrs,
    )
    assert r_rw.status_code == 200
    assert "settlement_recommendation" in r_rw.json()["invalidated_downstream_stages"]

    # Blocking rework prevents fraud_intelligence from running until recovered
    r_blocked_rw = client.post(
        f"/api/v1/claims/{claim_id}/orchestrate/fraud_intelligence",
        json={"enforce_dependencies": True},
        headers=handler_hdrs,
    )
    assert r_blocked_rw.status_code == 409

    # Recover rework and verify Decisions & Tasks endpoints
    r_rec2 = client.post(
        f"/api/v1/claims/{claim_id}/orchestration/recover",
        json={"resolution_notes": "Surveyor verified fender repairability", "resume_pipeline": True},
        headers=handler_hdrs,
    )
    assert r_rec2.status_code == 200

    r_dec = client.get(f"/api/v1/claims/{claim_id}/decisions", headers=handler_hdrs)
    assert r_dec.status_code == 200
    assert len(r_dec.json()["items"]) >= 4
    sample_dec = r_dec.json()["items"][0]
    assert sample_dec["reason_codes"]
    assert sample_dec["policy_rule_refs"]
    assert sample_dec["routing_outcome"]
    assert sample_dec["explanation"]


def test_action_taking_provider_coordination_and_finance_agent_payment(client):
    handler_hdrs = auth_headers(client, "handler@demo.in")
    finance_hdrs = auth_headers(client, "finance@demo.in")

    # EV safety override in provider coordination: request non-EV garage on EV claim -> overridden to VoltCare EV Hub
    r_prov = client.post(
        "/api/v1/claims/clm-demo-0011/provider-coordination",
        json={"preferred_garage_id": "prov-gar-01", "towing_needed": True},
        headers=handler_hdrs,
    )
    assert r_prov.status_code == 200
    prov_res = r_prov.json()["agent_response"]["result"]
    assert prov_res["ev_safety_override_applied"] is True
    assert prov_res["customer_preference_honoured"] is False

    # Finance executes approved settlement payout via controlled agent tool
    r_pay = client.post(
        "/api/v1/claims/clm-demo-0008/payments/agent-release",
        json={
            "settlement_id": "stl-demo-0009",
            "idempotency_key": "agent-pay-test-001",
            "payee_name": "Apex Motors",
        },
        headers=finance_hdrs,
    )
    # clm-demo-0008 has no stl-demo-0009 (stl-demo-0009 belongs to clm-demo-0009), so test on clm-demo-0009!
    assert r_pay.status_code == 409

    r_pay_ok = client.post(
        "/api/v1/claims/clm-demo-0009/payments/agent-release",
        json={
            "settlement_id": "stl-demo-0009",
            "idempotency_key": "agent-pay-0009-unique",
            "payee_name": "Apex Motors Cashless Hub",
        },
        headers=finance_hdrs,
    )
    assert r_pay_ok.status_code == 201
    actions = r_pay_ok.json()["agent_response"]["actions_executed"]
    assert any(a["action_type"] == "initiate_approved_payment" and a["status"] == "executed" for a in actions)
