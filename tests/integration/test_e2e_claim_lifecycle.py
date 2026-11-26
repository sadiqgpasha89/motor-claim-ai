from __future__ import annotations

from tests.conftest import auth_headers


def test_full_vertical_slice_e2e_lifecycle(client):
    ph_hdrs = auth_headers(client, "policyholder@demo.in")
    handler_hdrs = auth_headers(client, "handler@demo.in")
    checker_hdrs = auth_headers(client, "handler2@demo.in")
    surveyor_hdrs = auth_headers(client, "surveyor@demo.in")
    garage_hdrs = auth_headers(client, "garage@demo.in")
    finance_hdrs = auth_headers(client, "finance@demo.in")

    fnol_payload = {
        "policy_number": "POL-IN-DEMO-2026-1001",
        "vehicle_reg": "MH02DEMO1042",
        "claim_type": "cashless",
        "peril_cause": "road_accident",
        "incident_location": "Bandra West, Mumbai",
        "incident_description": "Front bumper and RH headlamp damaged in intersection collision.",
        "estimated_loss_inr": "56000.00",
    }
    r1 = client.post("/api/v1/claims/intimations", json=fnol_payload, headers={**ph_hdrs, "Idempotency-Key": "e2e-fnol-001"})
    assert r1.status_code == 201, r1.text
    claim_id = r1.json()["claim"]["id"]
    assert r1.json()["claim"]["requires_mandatory_survey"] is True

    r1_dup = client.post("/api/v1/claims/intimations", json=fnol_payload, headers={**ph_hdrs, "Idempotency-Key": "e2e-fnol-001"})
    assert r1_dup.status_code == 201
    assert r1_dup.json()["idempotent_replay"] is True
    assert r1_dup.json()["claim"]["id"] == claim_id

    r_ev = client.post(
        f"/api/v1/claims/{claim_id}/evidence",
        files={"file": ("rc_scan.txt", b"Registration MH02DEMO1042 Policy POL-IN-DEMO-2026-1001", "text/plain")},
        headers=ph_hdrs,
    )
    assert r_ev.status_code == 201, r_ev.text
    assert r_ev.json()["doc_type"] == "registration_certificate"

    r_cov = client.post(f"/api/v1/claims/{claim_id}/coverage-checks", headers=handler_hdrs)
    assert r_cov.status_code == 200
    assert len(r_cov.json()["coverage_factsheet"]["evidence_refs"]) >= 1

    r_tri = client.post(f"/api/v1/claims/{claim_id}/triage", headers=handler_hdrs)
    assert r_tri.status_code == 200
    assert r_tri.json()["triage"]["result"]["requires_mandatory_survey"] is True

    r_surv = client.post(
        f"/api/v1/claims/{claim_id}/surveyor-assignments",
        json={"surveyor_id": "prov-surv-01", "garage_id": "prov-gar-01"},
        headers=handler_hdrs,
    )
    assert r_surv.status_code == 200

    r_dmg = client.post(f"/api/v1/claims/{claim_id}/damage-assessments", headers=surveyor_hdrs)
    assert r_dmg.status_code == 200
    assert len(r_dmg.json()["observations"]) >= 1

    r_est = client.post(
        f"/api/v1/claims/{claim_id}/estimates",
        json={
            "lines": [
                {"part_code": "PRT-FRT-BMP-01", "description": "Front Bumper", "line_type": "part", "quantity": 1, "unit_price_inr": "12500.00"},
                {"part_code": "PRT-HL-LED-RH", "description": "LED Headlamp", "line_type": "part", "quantity": 1, "unit_price_inr": "18400.00"},
                {"part_code": "PRT-FRT-BMP-01", "description": "Bumper Labour", "line_type": "labour", "quantity": 1, "unit_price_inr": "3200.00"},
            ]
        },
        headers=garage_hdrs,
    )
    assert r_est.status_code == 201

    r_rep = client.post(
        f"/api/v1/claims/{claim_id}/survey-reports",
        json={"inspection_notes": "Confirmed front bumper & headlamp damage.", "assessed_gross_inr": "34100.00", "signed": True},
        headers=surveyor_hdrs,
    )
    assert r_rep.status_code == 200

    r_frd = client.post(f"/api/v1/claims/{claim_id}/fraud-checks", headers=handler_hdrs)
    assert r_frd.status_code == 200

    r_stl = client.post(
        f"/api/v1/claims/{claim_id}/settlement-recommendations",
        json={"requested_pathway": "cashless"},
        headers=handler_hdrs,
    )
    assert r_stl.status_code == 201
    stl_id = r_stl.json()["settlement_id"]
    app_id = r_stl.json()["approval_id"]

    manager_hdrs = auth_headers(client, "manager@demo.in")
    # Open fraud indicator (repeat vehicle) blocks L1 handler approval and requires manager escalation
    r_app_blocked = client.post(
        f"/api/v1/claims/{claim_id}/approvals",
        json={"approval_id": app_id, "decision": "approved", "rationale": "Handler attempt with open alert"},
        headers=checker_hdrs,
    )
    assert r_app_blocked.status_code == 403
    assert r_app_blocked.json()["error_code"] == "HUMAN_REVIEW_REQUIRED"

    r_app = client.post(
        f"/api/v1/claims/{claim_id}/approvals",
        json={"approval_id": app_id, "decision": "approved", "rationale": "Manager verified against surveyor report & zero-dep policy"},
        headers=manager_hdrs,
    )
    assert r_app.status_code == 200
    assert r_app.json()["claim_status"] == "APPROVED"

    r_pmt = client.post(
        f"/api/v1/claims/{claim_id}/payments",
        json={
            "settlement_id": stl_id,
            "idempotency_key": "e2e-pay-001",
            "payee_type": "garage",
            "payee_name": "Apex Motors",
            "simulate_timeout": True,
        },
        headers=finance_hdrs,
    )
    assert r_pmt.status_code == 201
    pmt_id = r_pmt.json()["payment_id"]
    assert r_pmt.json()["status"] == "timeout_reconcile_pending"

    r_pmt_retry = client.post(
        f"/api/v1/claims/{claim_id}/payments",
        json={
            "settlement_id": stl_id,
            "idempotency_key": "e2e-pay-001",
            "payee_type": "garage",
            "payee_name": "Apex Motors",
        },
        headers=finance_hdrs,
    )
    assert r_pmt_retry.json()["idempotent_replay"] is True
    assert r_pmt_retry.json()["payment_id"] == pmt_id

    r_rec = client.post(f"/api/v1/claims/{claim_id}/payments/{pmt_id}/reconcile", headers=finance_hdrs)
    assert r_rec.status_code == 200
    assert r_rec.json()["status"] == "confirmed"

    r_rep_ms = client.post(
        f"/api/v1/claims/{claim_id}/repair-status",
        json={"milestone": "handover_complete", "notes": "Vehicle handed over to insured"},
        headers=garage_hdrs,
    )
    assert r_rep_ms.status_code == 200

    r_close = client.post(f"/api/v1/claims/{claim_id}/close", headers=handler_hdrs)
    assert r_close.status_code == 200
    assert r_close.json()["claim_status"] == "CLOSED"

    r_tl = client.get(f"/api/v1/claims/{claim_id}/timeline", headers=handler_hdrs)
    assert r_tl.status_code == 200
    assert len(r_tl.json()["audit_events"]) >= 8
