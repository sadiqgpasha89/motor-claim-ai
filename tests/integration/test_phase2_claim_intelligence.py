from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from scripts.od_claim_demo import run_od_claim_demo
from services.claims.db import SessionLocal
from services.claims.models import Claim, ClaimTask, Payment
from tests.conftest import auth_headers

POLICY = "POL-IN-DEMO-2026-2002"
VEHICLE = "KA03DEMO5521"


def _fnol(client, hdrs, key: str, loss: str = "30000.00") -> str:
    r = client.post(
        "/api/v1/claims/intimations",
        json={
            "policy_number": POLICY, "vehicle_reg": VEHICLE, "claim_type": "own_damage", "peril_cause": "road_accident",
            "incident_location": "Indiranagar, Bengaluru", "incident_description": "Front bumper and bonnet damage.",
            "estimated_loss_inr": loss,
        },
        headers={**hdrs, "Idempotency-Key": key},
    )
    assert r.status_code == 201, r.text
    return r.json()["claim"]["id"]


def _estimate(client, hdrs, claim_id, lines, supplement=False):
    return client.post(f"/api/v1/claims/{claim_id}/estimates", json={"is_supplement": supplement, "lines": lines}, headers=hdrs)


def _part(code, desc, price):
    return {"part_code": code, "description": desc, "part_category": "metal", "line_type": "part", "quantity": 1, "unit_price_inr": price}


@pytest.fixture(scope="module")
def claim_ids():
    with TestClient(app) as c:
        hdrs = auth_headers(c, "handler@demo.in")
        return [_fnol(c, hdrs, f"p2-{i}") for i in range(3)]


def test_supplement_not_allowed_in_a_state_that_has_no_estimate_yet(client, claim_ids):
    hdrs = auth_headers(client, "handler@demo.in")
    r = _estimate(client, hdrs, claim_ids[0], [_part("PRT-BON-01", "Bonnet", "16000")], supplement=True)
    assert r.status_code == 409


def test_large_supplement_opens_one_reinspection_task_and_uses_cumulative_totals(client, claim_ids):
    hdrs = auth_headers(client, "handler@demo.in")
    cid = claim_ids[1]
    assert _estimate(client, hdrs, cid, [_part("PRT-FRT-BMP-01", "Front bumper", "12500")]).status_code == 201
    db = SessionLocal()
    try:
        db.query(Claim).filter(Claim.id == cid).update({"status": "ESTIMATE_VALIDATION"})
        db.commit()
    finally:
        db.close()
    r1 = _estimate(client, hdrs, cid, [_part("PRT-BON-01", "Bonnet hidden damage", "16200")], supplement=True)
    assert r1.status_code == 201, r1.text
    review = r1.json()["supplementary_review"]
    assert review["reinspection_required"] is True and review["reinspection_task_id"]
    assert Decimal(review["cumulative_gross_inr"]) > Decimal(review["base_total_inr"])
    db = SessionLocal()
    try:
        db.query(Claim).filter(Claim.id == cid).update({"status": "ESTIMATE_VALIDATION"})
        db.commit()
    finally:
        db.close()
    r2 = _estimate(client, hdrs, cid, [_part("PRT-FND-RH-01", "Fender", "7800")], supplement=True)
    assert r2.json()["supplementary_review"]["reinspection_task_id"] == review["reinspection_task_id"]
    db = SessionLocal()
    try:
        open_tasks = db.query(ClaimTask).filter(ClaimTask.claim_id == cid, ClaimTask.task_type == "supplementary_reinspection", ClaimTask.status == "open").count()
    finally:
        db.close()
    assert open_tasks == 1


def test_complexity_is_explained_and_backtest_is_measured(client, claim_ids):
    hdrs = auth_headers(client, "handler@demo.in")
    body = client.get(f"/api/v1/claims/{claim_ids[2]}/complexity", headers=hdrs).json()
    assert body["band"] in {"simple", "standard", "complex", "specialist"}
    assert body["model_id"] == "complexity-baseline-v1" and "baseline" in body["disclaimer"]
    assert all({"driver", "points", "why"} <= set(d) for d in body["drivers"])
    mgr = auth_headers(client, "manager@demo.in")
    bt = client.get("/api/v1/operations/complexity-backtest", headers=mgr).json()
    assert bt["claims_scored"] > 0 and sum(bt["distribution"].values()) == bt["claims_scored"]
    assert client.get("/api/v1/operations/complexity-backtest", headers=hdrs).status_code == 403


def test_claim_360_includes_complexity_and_sla_risk(client, claim_ids):
    hdrs = auth_headers(client, "handler@demo.in")
    body = client.get(f"/api/v1/claims/{claim_ids[2]}/claim-360", headers=hdrs).json()
    assert body["intelligence"]["complexity"]["band"]
    assert "predictions" in body["intelligence"]["sla_risk"]


def test_analysis_endpoints_return_advisory_results(client, claim_ids):
    hdrs = auth_headers(client, "handler@demo.in")
    cid = claim_ids[1]
    rr = client.get(f"/api/v1/claims/{cid}/repair-replace-analysis", headers=hdrs)
    assert rr.status_code == 200 and rr.json()["advisory_only"] is True
    bm = client.get(f"/api/v1/claims/{cid}/estimate-benchmark", headers=hdrs).json()
    assert bm["lines"] and "synthetic" in bm["disclaimer"].lower()
    mm = client.get(f"/api/v1/claims/{cid}/multimodal-fusion", headers=hdrs).json()
    assert "fused_confidence" in mm


def test_fraud_network_links_claims_and_opens_one_siu_lead(client, claim_ids):
    siu = auth_headers(client, "siu@demo.in")
    graph = client.get(f"/api/v1/claims/{claim_ids[0]}/fraud-network", headers=siu).json()
    assert graph["component_size"] >= 3 and graph["never_auto_reject"] is True
    assert graph["edges"] and all(e["reasons"] for e in graph["edges"])
    assert graph["siu_case_recommended"] is True
    first = client.post(f"/api/v1/claims/{claim_ids[0]}/fraud-network/siu-lead", headers=siu)
    assert first.status_code == 201 and first.json()["created"] is True
    again = client.post(f"/api/v1/claims/{claim_ids[0]}/fraud-network/siu-lead", headers=siu)
    assert again.json()["created"] is False and again.json()["alert_id"] == first.json()["alert_id"]


def test_fraud_network_is_closed_to_non_siu_roles(client, claim_ids):
    hdrs = auth_headers(client, "handler@demo.in")
    assert client.get(f"/api/v1/claims/{claim_ids[0]}/fraud-network", headers=hdrs).status_code == 403
    auditor = auth_headers(client, "auditor@demo.in")
    assert client.post(f"/api/v1/claims/{claim_ids[0]}/fraud-network/siu-lead", headers=auditor).status_code == 403


def test_second_payment_on_a_paid_settlement_is_refused():
    with TestClient(app) as c:
        run = run_od_claim_demo(c, reset_demo_data=True)
        finance = auth_headers(c, "finance@demo.in")
        detail = c.get(f"/api/v1/claims/{run['claim_id']}", headers=auth_headers(c, "handler@demo.in")).json()
        stl = detail["settlements"][0]["id"]
        r = c.post(
            f"/api/v1/claims/{run['claim_id']}/payments",
            json={"settlement_id": stl, "idempotency_key": "p2-second-payout", "payee_type": "customer", "payee_name": "Rohan Kulkarni"},
            headers=finance,
        )
        assert r.status_code == 409 and "already paid" in r.text
        db = SessionLocal()
        try:
            assert db.query(Payment).filter(Payment.claim_id == run["claim_id"]).count() == 1
        finally:
            db.close()
        # The OD demo policy must stay free of history for other tests.
        c.post("/api/v1/operations/seed-reset", headers=auth_headers(c, "manager@demo.in"))
