"""Electric-vehicle (EV) claims workflow (IN-EV-CLAIMS-2026): dedicated safety-first lifecycle, no photo-only clearance."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from agents.specialists import AGENT_REGISTRY
from packages.contracts.agents import AgentInvocationRequest, AgentStatus
from packages.contracts.errors import DomainError
from services.claims.db import SessionLocal
from services.claims.models import Claim, Settlement
from services.damage_ai.assessor import assess_damage_from_evidence
from services.rules_engine.loader import get_active_rule
from services.workflow.ev_claims import STAGE_ORDER, EVStage, classify_signals, compute_benchmark, evaluate_diagnostics
from services.workflow.risk_engine import classify_claim_risk_from_facts
from tests.conftest import auth_headers

EV_POLICY = "POL-IN-DEMO-2026-EV02"
EV_VEHICLE = "MH01EVDEMO99"
ICE_POLICY = "POL-IN-DEMO-2026-1001"
ICE_VEHICLE = "MH02DEMO1042"
EV_GARAGE = "prov-gar-ev-02"

ALL_PASS = [
    {"test": "dtc_scan", "result": "pass"},
    {"test": "bms_cell_voltage_delta", "result": "pass", "value": "22", "unit": "mV"},
    {"test": "insulation_resistance", "result": "pass", "value": "1200", "unit": "ohm/V"},
    {"test": "hv_interlock_loop", "result": "pass"},
    {"test": "coolant_circuit_pressure", "result": "pass"},
    {"test": "pack_leak_ip_test", "result": "pass"},
    {"test": "state_of_health", "result": "pass", "value": "93", "unit": "%"},
]
INSULATION_FAIL = [
    {**t, "result": "fail", "value": "180"} if t["test"] == "insulation_resistance" else t for t in ALL_PASS
]


def _rule():
    db = SessionLocal()
    try:
        return get_active_rule(db, "IN-EV-CLAIMS-2026")
    finally:
        db.close()


def _post(client, hdrs, path, body=None, expect=200):
    r = client.post(path, json=body or {}, headers=hdrs)
    assert r.status_code == expect, f"{path} -> {r.status_code} {r.text}"
    return r.json()


def _get(client, hdrs, cid):
    r = client.get(f"/api/v1/claims/{cid}/ev", headers=hdrs)
    assert r.status_code == 200, r.text
    return r.json()


def _ev_claim(client, *, peril: str = "road_accident", immobile: bool = False, battery: bool = False, airbags: bool = False, assign: bool = True) -> str:
    ph = auth_headers(client, "policyholder@demo.in")
    r = client.post(
        "/api/v1/claims/intimations",
        json={
            "policy_number": EV_POLICY,
            "vehicle_reg": EV_VEHICLE,
            "claim_type": "cashless",
            "peril_cause": peril,
            "incident_location": "Powai, Mumbai",
            "incident_description": "Electric hatchback hit a speed-breaker hard; the underbody scraped.",
            "vehicle_immobile": immobile,
            "ev_battery_impacted": battery,
            "airbags_deployed": airbags,
            "estimated_loss_inr": "120000.00",
        },
        headers={**ph, "Idempotency-Key": f"ev-{uuid.uuid4().hex}"},
    )
    assert r.status_code == 201, r.text
    cid = r.json()["claim"]["id"]
    if assign:
        db = SessionLocal()
        try:
            claim = db.query(Claim).filter(Claim.id == cid).first()
            claim.assigned_surveyor_id = "prov-surv-01"
            claim.assigned_garage_id = EV_GARAGE
            db.commit()
        finally:
            db.close()
    return cid


def _settle_ack(client, cid: str) -> None:
    """Acknowledge every open safety escalation as the claims manager."""
    manager = auth_headers(client, "manager@demo.in")
    for e in _get(client, manager, cid)["safety_escalations"]:
        if e["status"] == "open":
            _post(client, manager, f"/api/v1/claims/{cid}/ev/safety-escalations/{e['id']}/acknowledge", {"actions_taken": "Customer called; EV recovery arranged."})


def _settle_resolve(client, cid: str, *, thermal: bool = False) -> None:
    manager = auth_headers(client, "manager@demo.in")
    for e in _get(client, manager, cid)["safety_escalations"]:
        if e["status"] != "resolved":
            _post(
                client, manager, f"/api/v1/claims/{cid}/ev/safety-escalations/{e['id']}/resolve",
                {"resolution": "Hazard contained and verified.", "evidence_ref": "EVSO-LOG-001", "thermal_stable_confirmed": thermal},
            )


def _to_survey_stage(client, cid: str, signals=None) -> None:
    handler = auth_headers(client, "handler@demo.in")
    _post(client, handler, f"/api/v1/claims/{cid}/ev/triage", {"signals": signals or ["underbody_impact"], "vehicle_location": "Powai, Mumbai"})
    _settle_ack(client, cid)
    _post(client, handler, f"/api/v1/claims/{cid}/ev/advance", {})
    _post(
        client, handler, f"/api/v1/claims/{cid}/ev/recovery",
        {"provider_id": "prov-tow-01", "tow_method": "flatbed", "hv_isolation_method": "service disconnect pulled", "hv_isolation_verified": True, "quarantine_location": "Bay B3", "quarantine_clearance_m": "8"},
    )
    _settle_resolve(client, cid)
    _post(client, handler, f"/api/v1/claims/{cid}/ev/advance", {})


def _survey(client, cid: str, **over) -> dict:
    surveyor = auth_headers(client, "surveyor@demo.in")
    body = {
        "inspection_mode": "physical_on_lift",
        "hv_isolation_verified": True,
        "pack_findings": ["Underbody shield cracked over the pack tray"],
        "pack_removal_required": True,
        "report_ref": f"SURV-{uuid.uuid4().hex[:6]}",
        **over,
    }
    return _post(client, surveyor, f"/api/v1/claims/{cid}/ev/specialist-survey", body)


def _to_diagnostics_stage(client, cid: str, signals=None) -> None:
    _to_survey_stage(client, cid, signals)
    _survey(client, cid)
    _post(client, auth_headers(client, "handler@demo.in"), f"/api/v1/claims/{cid}/ev/advance", {})


def _diagnostics(client, cid: str, tests=None, expect=200) -> dict:
    garage = auth_headers(client, "garage.ev@demo.in")
    return _post(client, garage, f"/api/v1/claims/{cid}/ev/oem-diagnostics", {"tool": "OEM-DiagTool v9", "report_ref": "OEMSCAN-7781", "tests": tests or ALL_PASS}, expect)


GOOD_LINES = [
    {"kind": "part", "part_code": "PRT-EV-BAT-TRAY", "unit_quoted_inr": "26000", "quantity": "1"},
    {"kind": "part", "part_code": "PRT-EV-PACK-FULL", "unit_quoted_inr": "1300000", "quantity": "1"},
    {"kind": "labour", "hours": "6", "rate_inr": "1800"},
]


def _full_to_sign_off(client, cid: str, *, tests=None, decision="replace_pack", signals=None) -> None:
    handler = auth_headers(client, "handler@demo.in")
    _to_diagnostics_stage(client, cid, signals)
    _diagnostics(client, cid, tests)
    _post(client, handler, f"/api/v1/claims/{cid}/ev/advance", {})
    _post(
        client, handler, f"/api/v1/claims/{cid}/ev/battery-disposition",
        {"decision": decision, "rationale": "OEM tests and survey support this decision.", "oem_engineer_name": "S. Kulkarni", "oem_engineer_ref": "OEM-ENG-5521", "oem_engineer_org": "VoltCare OEM"},
    )
    _post(client, auth_headers(client, "manager@demo.in"), f"/api/v1/claims/{cid}/ev/advance", {})
    _post(client, handler, f"/api/v1/claims/{cid}/ev/cost-benchmark", {"lines": GOOD_LINES})
    # A full-pack quote is high value, so a claims manager reviews it.
    _post(client, auth_headers(client, "manager@demo.in"), f"/api/v1/claims/{cid}/ev/cost-benchmark/review", {"note": "Reviewed; within bands."})
    _post(client, handler, f"/api/v1/claims/{cid}/ev/advance", {})


# ----------------------------------------------------------------------------------------------
def test_ev_claim_opens_dedicated_case_with_hv_hold_at_fnol(client):
    cid = _ev_claim(client, immobile=True)
    handler = auth_headers(client, "handler@demo.in")
    v = _get(client, handler, cid)
    assert v["stage"] == "INTAKE_TRIAGE"
    assert v["queue"] == "ev_triage_intake"
    assert v["operation_status"] == "hold_do_not_operate_pending_inspection"
    assert v["safe_to_operate"] == "not_determinable_from_photographs"
    assert v["controls"]["photo_only_clearance_allowed"] is False
    assert v["controls"]["ai_may_declare_vehicle_safe_to_operate"] is False
    assert v["risk_class"] in {"hv_suspected", "battery_critical"}
    assert v["case_number"].startswith("EV-")
    assert v["od_hold"]["held"] is True
    c360 = client.get(f"/api/v1/claims/{cid}", headers=handler).json()
    assert c360["ev_workflow_required"] is True
    assert c360["ev_workflow"]["operation_status"] == "hold_do_not_operate_pending_inspection"
    # An immobile EV is an HV signal, so an urgent escalation exists from the first minute.
    assert any(e["level"] == "urgent" for e in v["safety_escalations"])


def test_non_ev_claim_has_no_ev_case_and_cannot_open_one(client):
    ph = auth_headers(client, "policyholder@demo.in")
    r = client.post(
        "/api/v1/claims/intimations",
        json={"policy_number": ICE_POLICY, "vehicle_reg": ICE_VEHICLE, "claim_type": "cashless", "incident_location": "Bandra", "incident_description": "Bumper scrape."},
        headers={**ph, "Idempotency-Key": f"ice-{uuid.uuid4().hex}"},
    )
    cid = r.json()["claim"]["id"]
    handler = auth_headers(client, "handler@demo.in")
    assert client.get(f"/api/v1/claims/{cid}/ev", headers=handler).status_code == 404
    assert client.post(f"/api/v1/claims/{cid}/ev/open", headers=handler).status_code == 409
    assert client.get(f"/api/v1/claims/{cid}", headers=handler).json()["ev_workflow_required"] is False


def test_policyholder_sees_only_the_customer_safety_view(client):
    cid = _ev_claim(client)
    ph = auth_headers(client, "policyholder@demo.in")
    v = _get(client, ph, cid)
    assert set(v) == {"customer_view"}
    cv = v["customer_view"]
    assert cv["do_not_drive_or_charge"] is True
    assert cv["photo_only_clearance_allowed"] is False
    assert "Do not" in cv["safety_instruction"] or "do not" in cv["safety_instruction"]
    assert "diagnostics" not in v and "benchmark" not in v
    # A policyholder cannot drive the workflow.
    assert client.post(f"/api/v1/claims/{cid}/ev/triage", json={"signals": []}, headers=ph).status_code == 403
    assert client.post(f"/api/v1/claims/{cid}/ev/advance", json={}, headers=ph).status_code == 403


def test_battery_pack_impact_detection_has_no_safe_outcome():
    rule = _rule()
    db = SessionLocal()
    try:
        claim = db.query(Claim).filter(Claim.id == "clm-demo-0001").first()
        assert claim is not None
        none_declared = classify_signals(rule, [], claim)
        assert none_declared["impact_band"] == "not_excluded"
        assert none_declared["safe_to_operate"] == "not_determinable_from_photographs"
        assert "safe" not in none_declared["impact_band"].replace("not_excluded", "")
        severe = classify_signals(rule, ["underbody_impact", "pack_zone_deformation", "airbags_deployed"], claim)
        assert severe["impact_band"] in {"probable", "severe"}
        assert severe["risk_class"] == "battery_critical"
        thermal = classify_signals(rule, ["smoke_or_fire"], claim)
        assert thermal["thermal_level"] == "emergency"
        assert thermal["escalation_level"] == "emergency"
        charging = classify_signals(rule, ["charge_port_damage"], claim)
        assert charging["escalation_level"] == "urgent"
        with pytest.raises(DomainError):
            classify_signals(rule, ["looks_fine_in_photos"], claim)
    finally:
        db.close()


def test_triage_signals_are_append_only_and_risk_class_never_downgrades(client):
    cid = _ev_claim(client)
    handler = auth_headers(client, "handler@demo.in")
    v = _post(client, handler, f"/api/v1/claims/{cid}/ev/triage", {"signals": ["underbody_impact", "pack_zone_deformation"]})
    assert v["risk_class"] == "battery_critical"
    assert v["thermal_watch"]["required"] is True
    again = _post(client, handler, f"/api/v1/claims/{cid}/ev/triage", {"signals": []})
    assert again["risk_class"] == "battery_critical"
    assert {"underbody_impact", "pack_zone_deformation"} <= set(again["triage"]["signals"])
    bad = client.post(f"/api/v1/claims/{cid}/ev/triage", json={"signals": ["looks_fine_in_photos"]}, headers=handler)
    assert bad.status_code == 400


def test_customer_declared_drivable_is_recorded_but_never_accepted(client):
    cid = _ev_claim(client)
    handler = auth_headers(client, "handler@demo.in")
    v = _post(client, handler, f"/api/v1/claims/{cid}/ev/triage", {"signals": ["collision_impact_any"], "customer_declared_drivable": True, "charging_in_progress": True})
    assert v["triage"]["customer_declared_drivable"] is True
    assert "NOT accepted" in v["triage"]["drivability_note"]
    assert v["operation_status"] == "hold_do_not_operate_pending_inspection"
    assert v["triage"]["safe_to_operate"] == "not_determinable_from_photographs"


def test_policyholder_reported_thermal_signal_raises_an_emergency_that_blocks_everything(client):
    cid = _ev_claim(client)
    ph = auth_headers(client, "policyholder@demo.in")
    handler = auth_headers(client, "handler@demo.in")
    manager = auth_headers(client, "manager@demo.in")
    _post(client, handler, f"/api/v1/claims/{cid}/ev/triage", {"signals": ["underbody_impact"]})
    _settle_ack(client, cid)
    out = _post(client, ph, f"/api/v1/claims/{cid}/ev/safety-escalations", {"signals": ["smoke_or_fire"], "description": "Smoke from under the car."}, 201)
    assert out["customer_view"]["open_safety_escalation"] is True
    assert "112" in out["customer_view"]["safety_instruction"]

    v = _get(client, handler, cid)
    assert v["risk_class"] == "battery_critical"
    esc = [e for e in v["safety_escalations"] if e["level"] == "emergency"][0]
    assert esc["status"] == "open"
    assert any(t["task_type"] == "ev_case_escalation" and t["status"] == "open" for t in v["tasks"])
    # The open escalation blocks the stage and the OD settlement path.
    r = client.post(f"/api/v1/claims/{cid}/ev/advance", json={}, headers=handler)
    assert r.status_code == 409
    r = client.post(f"/api/v1/claims/{cid}/settlement-recommendations", json={}, headers=handler)
    assert r.status_code == 409 and r.json()["details"]["rule_id"] == "IN-EV-CLAIMS-2026"

    path = f"/api/v1/claims/{cid}/ev/safety-escalations/{esc['id']}"
    assert client.post(f"{path}/resolve", json={"resolution": "x", "evidence_ref": "E1", "thermal_stable_confirmed": True}, headers=manager).status_code == 409  # not acknowledged
    _post(client, manager, f"{path}/acknowledge", {"actions_taken": "Fire service informed; area cleared."})
    assert client.post(f"{path}/resolve", json={"resolution": "ok", "evidence_ref": "E1", "thermal_stable_confirmed": False}, headers=manager).status_code == 409
    assert client.post(f"{path}/resolve", json={"resolution": "ok", "evidence_ref": "", "thermal_stable_confirmed": True}, headers=manager).status_code == 400
    resolved = _post(client, manager, f"{path}/resolve", {"resolution": "Pack thermally stable per OEM scan.", "evidence_ref": "OEM-THERMAL-77", "thermal_stable_confirmed": True})
    assert all(e["status"] == "resolved" for e in resolved["safety_escalations"] if e["id"] == esc["id"])


def test_escalation_resolver_must_differ_from_the_user_who_raised_it(client):
    cid = _ev_claim(client)
    manager = auth_headers(client, "manager@demo.in")
    out = _post(client, manager, f"/api/v1/claims/{cid}/ev/safety-escalations", {"signals": ["hv_warning_light"], "description": "HV warning seen at inspection."}, 201)
    esc = [e for e in out["safety_escalations"] if e["raised_by"]["role"] == "claims_manager"][0]
    path = f"/api/v1/claims/{cid}/ev/safety-escalations/{esc['id']}"
    _post(client, manager, f"{path}/acknowledge", {"actions_taken": "Recovery arranged."})
    r = client.post(f"{path}/resolve", json={"resolution": "ok", "evidence_ref": "E-1"}, headers=manager)
    assert r.status_code == 403
    assert "Separation of duties" in r.json()["message"]


def test_recovery_must_be_flatbed_by_an_ev_qualified_provider_with_quarantine_clearance(client):
    cid = _ev_claim(client)
    handler = auth_headers(client, "handler@demo.in")
    _post(client, handler, f"/api/v1/claims/{cid}/ev/triage", {"signals": ["underbody_impact"]})
    base = {"hv_isolation_method": "service disconnect", "hv_isolation_verified": True, "quarantine_location": "Bay B3", "quarantine_clearance_m": "8"}
    # Not at the recovery stage yet.
    assert client.post(f"/api/v1/claims/{cid}/ev/recovery", json={"provider_id": "prov-tow-01", "tow_method": "flatbed", **base}, headers=handler).status_code == 409
    _settle_ack(client, cid)
    _post(client, handler, f"/api/v1/claims/{cid}/ev/advance", {})
    for bad in ("wheel_lift_tow", "dolly_tow", "driven_under_own_power"):
        r = client.post(f"/api/v1/claims/{cid}/ev/recovery", json={"provider_id": "prov-tow-01", "tow_method": bad, **base}, headers=handler)
        assert r.status_code == 409, bad
    r = client.post(f"/api/v1/claims/{cid}/ev/recovery", json={"provider_id": "prov-gar-01", "tow_method": "flatbed", **base}, headers=handler)
    assert r.status_code == 403 and "EV-HV qualified" in r.json()["message"]
    r = client.post(f"/api/v1/claims/{cid}/ev/recovery", json={"provider_id": "prov-tow-01", "tow_method": "flatbed", **{**base, "quarantine_clearance_m": "2"}}, headers=handler)
    assert r.status_code == 409
    ok = _post(client, handler, f"/api/v1/claims/{cid}/ev/recovery", {"provider_id": "prov-tow-01", "tow_method": "flatbed", **base})
    assert ok["recovery"]["hv_isolation_verified"] is True
    assert ok["operation_status"] == "hold_do_not_operate_pending_inspection"


def test_specialist_survey_must_be_physical_and_by_an_ev_hv_certified_surveyor(client):
    cid = _ev_claim(client)
    handler = auth_headers(client, "handler@demo.in")
    surveyor = auth_headers(client, "surveyor@demo.in")
    _to_survey_stage(client, cid)
    for mode in ("photo_remote", "video_remote", "customer_self_declared"):
        r = client.post(f"/api/v1/claims/{cid}/ev/specialist-survey", json={"inspection_mode": mode, "hv_isolation_verified": True, "report_ref": "R1"}, headers=surveyor)
        assert r.status_code == 409, mode
        assert "photograph" in r.json()["message"]
    # A general (non-EV) surveyor recorded by the handler is rejected.
    r = client.post(f"/api/v1/claims/{cid}/ev/specialist-survey", json={"surveyor_provider_id": "prov-surv-03", "inspection_mode": "physical_on_lift", "hv_isolation_verified": True, "report_ref": "R2"}, headers=handler)
    assert r.status_code == 403 and "EV-HV qualified" in r.json()["message"]
    r = client.post(f"/api/v1/claims/{cid}/ev/specialist-survey", json={"surveyor_provider_id": "prov-surv-expired", "inspection_mode": "physical_on_lift", "hv_isolation_verified": True, "report_ref": "R3"}, headers=handler)
    assert r.status_code == 403
    # A partner user cannot record work for another organisation.
    r = client.post(f"/api/v1/claims/{cid}/ev/specialist-survey", json={"surveyor_provider_id": "prov-surv-02", "inspection_mode": "physical_on_lift", "hv_isolation_verified": True, "report_ref": "R4"}, headers=surveyor)
    assert r.status_code == 403
    # Isolation not confirmed: recorded but the gate holds.
    out = _survey(client, cid, hv_isolation_verified=False)
    assert any(b["code"] == "SURVEY_ISOLATION_UNVERIFIED" for b in out["gate_blockers"])
    assert client.post(f"/api/v1/claims/{cid}/ev/advance", json={}, headers=handler).status_code == 409
    ok = _survey(client, cid)
    assert ok["survey"]["qualification"]["qualified"] is True
    assert ok["can_advance"] is True


def test_surveyor_observing_thermal_indicators_raises_an_emergency(client):
    cid = _ev_claim(client)
    _to_survey_stage(client, cid)
    out = _survey(client, cid, thermal_indicators_observed=True)
    assert out["risk_class"] == "battery_critical"
    assert any(e["level"] == "emergency" and e["source"] == "specialist_survey" and e["status"] == "open" for e in out["safety_escalations"])
    assert client.post(f"/api/v1/claims/{cid}/ev/advance", json={}, headers=auth_headers(client, "handler@demo.in")).status_code == 409


def test_oem_diagnostics_need_an_oem_authorised_ev_workshop_and_a_complete_test_set(client):
    cid = _ev_claim(client)
    _to_diagnostics_stage(client, cid)
    handler = auth_headers(client, "handler@demo.in")
    # The non-EV workshop cannot record diagnostics (even if assigned).
    db = SessionLocal()
    try:
        db.query(Claim).filter(Claim.id == cid).first().assigned_garage_id = "prov-gar-01"
        db.commit()
    finally:
        db.close()
    r = client.post(
        f"/api/v1/claims/{cid}/ev/oem-diagnostics",
        json={"tool": "generic", "report_ref": "X1", "tests": ALL_PASS},
        headers=auth_headers(client, "garage@demo.in"),
    )
    assert r.status_code == 403 and "EV-HV qualified" in r.json()["message"]
    db = SessionLocal()
    try:
        db.query(Claim).filter(Claim.id == cid).first().assigned_garage_id = EV_GARAGE
        db.commit()
    finally:
        db.close()

    # Measured value contradicts the reported pass.
    contradict = [{**t, "value": "120"} if t["test"] == "insulation_resistance" else t for t in ALL_PASS]
    assert _diagnostics(client, cid, contradict, expect=400)["error_code"] == "VALIDATION_ERROR"
    # Missing report reference.
    r = client.post(f"/api/v1/claims/{cid}/ev/oem-diagnostics", json={"tool": "t", "report_ref": "", "tests": ALL_PASS}, headers=auth_headers(client, "garage.ev@demo.in"))
    assert r.status_code == 400
    partial = _diagnostics(client, cid, ALL_PASS[:3])
    assert partial["diagnostics"]["complete"] is False
    assert "pack_leak_ip_test" in partial["diagnostics"]["missing_tests"]
    assert client.post(f"/api/v1/claims/{cid}/ev/advance", json={}, headers=handler).status_code == 409
    full = _diagnostics(client, cid)
    assert full["diagnostics"]["complete"] is True and full["diagnostics"]["outcome"] == "pass"
    assert full["can_advance"] is True


def test_battery_disposition_advisory_is_not_binding_and_a_critical_failure_bars_repair(client):
    cid = _ev_claim(client)
    handler = auth_headers(client, "handler@demo.in")
    manager = auth_headers(client, "manager@demo.in")
    _to_diagnostics_stage(client, cid)
    out = _diagnostics(client, cid, INSULATION_FAIL)
    assert out["diagnostics"]["critical_fail"] is True
    adv = out["advisory"]["battery_disposition"]
    assert adv["recommended"] in {"replace_pack", "total_loss_review"}
    assert adv["binding"] is False
    _post(client, handler, f"/api/v1/claims/{cid}/ev/advance", {})
    path = f"/api/v1/claims/{cid}/ev/battery-disposition"
    ok_body = {"rationale": "Insulation failure on the pack.", "oem_engineer_name": "S. Kulkarni", "oem_engineer_ref": "OEM-ENG-1"}
    for barred in ("repair_in_place", "no_battery_work"):
        assert client.post(path, json={"decision": barred, **ok_body}, headers=handler).status_code == 409, barred
    assert client.post(path, json={"decision": "replace_pack", "rationale": "x", "oem_engineer_name": "", "oem_engineer_ref": ""}, headers=handler).status_code == 400
    # The inspecting surveyor cannot also be the OEM engineer who signs the decision.
    r = client.post(path, json={"decision": "replace_pack", **{**ok_body, "oem_engineer_name": "R. K. Sharma (Surveyor)"}}, headers=handler)
    assert r.status_code == 403
    done = _post(client, handler, path, {"decision": "replace_pack", **ok_body})
    assert done["disposition"]["followed_advisory"] in {True, False}
    assert done["disposition"]["oem_engineer"]["ref"] == "OEM-ENG-1"
    assert done["disposition"]["requires_pack_removal"] is True
    # Only a manager advances the manager-owned disposition stage.
    assert client.post(f"/api/v1/claims/{cid}/ev/advance", json={}, headers=handler).status_code == 403
    assert _post(client, manager, f"/api/v1/claims/{cid}/ev/advance", {})["stage"] == "COST_BENCHMARKING"


def test_ev_parts_cost_benchmark_flags_variance_and_needs_a_manager_when_flagged(client):
    rule = _rule()
    bm = compute_benchmark(
        rule,
        [
            {"kind": "part", "part_code": "PRT-EV-HV-JB", "unit_quoted_inr": "75000"},
            {"kind": "part", "part_code": "PRT-EV-OBC", "unit_quoted_inr": "400000"},
            {"kind": "part", "part_code": "PRT-EV-DCDC", "unit_quoted_inr": "3000"},
            {"kind": "part", "part_code": "PRT-UNKNOWN-9", "unit_quoted_inr": "1000"},
            {"kind": "labour", "hours": "5", "rate_inr": "9000"},
        ],
    )
    status = {ln["part_code"]: ln["status"] for ln in bm["lines"]}
    assert status["PRT-EV-HV-JB"] == "within_benchmark"
    assert status["PRT-EV-OBC"] == "above_benchmark"
    assert status["PRT-EV-DCDC"] == "suspiciously_low"
    assert status["PRT-UNKNOWN-9"] == "no_benchmark"
    assert status["LABOUR-HV"] == "above_benchmark"
    assert bm["flagged_lines"] == 4 and bm["requires_manager_review"] is True and bm["binding"] is False

    cid = _ev_claim(client)
    handler = auth_headers(client, "handler@demo.in")
    manager = auth_headers(client, "manager@demo.in")
    _to_diagnostics_stage(client, cid)
    _diagnostics(client, cid)
    _post(client, handler, f"/api/v1/claims/{cid}/ev/advance", {})
    _post(client, handler, f"/api/v1/claims/{cid}/ev/battery-disposition", {"decision": "repair_in_place", "rationale": "Enclosure repair only.", "oem_engineer_name": "S. Kulkarni", "oem_engineer_ref": "OEM-ENG-9"})
    _post(client, manager, f"/api/v1/claims/{cid}/ev/advance", {})
    assert client.post(f"/api/v1/claims/{cid}/ev/cost-benchmark", json={"lines": []}, headers=handler).status_code == 400
    out = _post(client, handler, f"/api/v1/claims/{cid}/ev/cost-benchmark", {"lines": [{"kind": "part", "part_code": "PRT-EV-OBC", "unit_quoted_inr": "400000"}]})
    assert out["benchmark"]["requires_manager_review"] is True
    assert client.post(f"/api/v1/claims/{cid}/ev/advance", json={}, headers=handler).status_code == 409
    assert client.post(f"/api/v1/claims/{cid}/ev/cost-benchmark/review", json={"note": "ok"}, headers=handler).status_code == 403
    assert client.post(f"/api/v1/claims/{cid}/ev/cost-benchmark/review", json={"note": ""}, headers=manager).status_code == 400
    _post(client, manager, f"/api/v1/claims/{cid}/ev/cost-benchmark/review", {"note": "OBC quote challenged with the workshop; accepted at benchmark ceiling."})
    assert _get(client, handler, cid)["can_advance"] is True


def test_technical_sign_off_has_separation_of_duties_and_is_the_only_thing_that_lifts_the_od_hold(client):
    cid = _ev_claim(client)
    handler = auth_headers(client, "handler@demo.in")
    manager = auth_headers(client, "manager@demo.in")
    admin = auth_headers(client, "admin@demo.in")
    _to_diagnostics_stage(client, cid)
    _diagnostics(client, cid)
    _post(client, handler, f"/api/v1/claims/{cid}/ev/advance", {})
    # The manager records the disposition this time, so the same manager cannot sign it off.
    _post(client, manager, f"/api/v1/claims/{cid}/ev/battery-disposition", {"decision": "repair_in_place", "rationale": "Enclosure repair only.", "oem_engineer_name": "S. Kulkarni", "oem_engineer_ref": "OEM-ENG-3"})
    _post(client, manager, f"/api/v1/claims/{cid}/ev/advance", {})
    _post(client, handler, f"/api/v1/claims/{cid}/ev/cost-benchmark", {"lines": GOOD_LINES[:1]})
    _post(client, handler, f"/api/v1/claims/{cid}/ev/cost-benchmark/review", {"note": "ok"})
    _post(client, handler, f"/api/v1/claims/{cid}/ev/advance", {})
    v = _get(client, handler, cid)
    assert v["stage"] == "TECHNICAL_SIGN_OFF"
    assert v["od_hold"]["held"] is True
    assert client.post(f"/api/v1/claims/{cid}/ev/advance", json={}, headers=handler).status_code == 409  # not advanceable generically
    assert client.post(f"/api/v1/claims/{cid}/ev/technical-sign-off", json={}, headers=handler).status_code == 403
    r = client.post(f"/api/v1/claims/{cid}/ev/technical-sign-off", json={}, headers=manager)
    assert r.status_code == 403 and "Separation of duties" in r.json()["message"]
    done = _post(client, admin, f"/api/v1/claims/{cid}/ev/technical-sign-off", {"notes": "Checked by the EV technical lead."})
    assert done["stage"] == "SETTLEMENT_CLEARED"
    assert done["settlement_clearance"]["status"] == "granted"
    assert done["od_hold"]["held"] is False
    # The OD guard is now open: any other refusal is not the EV hold.
    r = client.post(f"/api/v1/claims/{cid}/settlement-recommendations", json={}, headers=handler)
    assert (r.json().get("details") or {}).get("rule_id") != "IN-EV-CLAIMS-2026"


def test_full_ev_lifecycle_recertification_thermal_watch_salvage_and_closure(client):
    cid = _ev_claim(client)
    handler = auth_headers(client, "handler@demo.in")
    manager = auth_headers(client, "manager@demo.in")
    admin = auth_headers(client, "admin@demo.in")
    garage = auth_headers(client, "garage.ev@demo.in")
    _full_to_sign_off(client, cid, decision="replace_pack", tests=ALL_PASS, signals=["underbody_impact", "pack_zone_deformation"])
    # Disposition was recorded by the handler, so the manager may sign off.
    _post(client, manager, f"/api/v1/claims/{cid}/ev/technical-sign-off", {})
    assert _get(client, manager, cid)["stage"] == "SETTLEMENT_CLEARED"
    # Repair cannot start before the OD engine has approved a settlement.
    assert client.post(f"/api/v1/claims/{cid}/ev/advance", json={}, headers=handler).status_code == 409
    db = SessionLocal()
    try:
        db.add(
            Settlement(
                tenant_id="tenant-in-demo", claim_id=cid, gross_assessed_inr=Decimal("100000"), depreciation_deduction_inr=Decimal("0"),
                compulsory_excess_inr=Decimal("1000"), net_payable_inr=Decimal("99000"), approval_status="approved", created_by="usr-handler",
            )
        )
        db.commit()
    finally:
        db.close()
    assert _post(client, handler, f"/api/v1/claims/{cid}/ev/advance", {})["stage"] == "REPAIR_RECERTIFICATION"
    serial = "PACK-SN-884412"
    removal = {"event": "pack_removed", "battery_serial": serial, "location": "VoltCare bay B3", "performed_by_provider_id": EV_GARAGE}
    for bad_event in ("sold_for_reuse", "retained_by_insured", "sold_as_used_part"):
        r = client.post(f"/api/v1/claims/{cid}/ev/salvage-events", json={**removal, "event": bad_event}, headers=garage)
        assert r.status_code == 409, bad_event
    assert client.post(f"/api/v1/claims/{cid}/ev/salvage-events", json={**removal, "event": "handed_over"}, headers=garage).status_code == 409  # must start at removal
    _post(client, garage, f"/api/v1/claims/{cid}/ev/salvage-events", removal, 201)
    assert client.post(f"/api/v1/claims/{cid}/ev/salvage-events", json={"event": "quarantined", "battery_serial": "OTHER-SERIAL"}, headers=garage).status_code == 409
    _post(client, garage, f"/api/v1/claims/{cid}/ev/salvage-events", {"event": "quarantined", "battery_serial": serial, "location": "Quarantine cage Q1"}, 201)

    rc = {"provider_id": EV_GARAGE, "insulation_resistance_ohm_per_volt": "1500", "dtc_cleared": True, "hv_interlock_ok": True, "charge_test_ok": True, "thermal_scan_ok": True, "physical_road_test_done": True, "oem_certificate_ref": "OEM-RECERT-22"}
    failed = _post(client, garage, f"/api/v1/claims/{cid}/ev/recertification", {**rc, "insulation_resistance_ohm_per_volt": "150"})
    assert failed["recertification"]["passed"] is False
    assert failed["operation_status"] == "hold_do_not_operate_pending_inspection"
    # All checks pass, but the battery-critical thermal watch is not cleared: still held.
    held = _post(client, garage, f"/api/v1/claims/{cid}/ev/recertification", rc)
    assert held["recertification"]["passed"] is False
    assert held["operation_status"] == "hold_do_not_operate_pending_inspection"
    assert any(b["code"] == "THERMAL_WATCH_NOT_CLEARED" for b in held["gate_blockers"])
    assert client.post(f"/api/v1/claims/{cid}/ev/thermal-watch/clear", json={"basis": "x", "oem_reference": "y"}, headers=handler).status_code == 403
    _post(client, manager, f"/api/v1/claims/{cid}/ev/thermal-watch/clear", {"basis": "Monitoring window complete, OEM scan stable.", "oem_reference": "OEM-THERMAL-9"})
    released = _post(client, garage, f"/api/v1/claims/{cid}/ev/recertification", rc)
    assert released["recertification"]["passed"] is True
    assert released["operation_status"] == "released_after_recertification"
    assert client.post(f"/api/v1/claims/{cid}/ev/close", json={"closure_notes": "x"}, headers=manager).status_code == 409  # salvage not done

    assert _post(client, handler, f"/api/v1/claims/{cid}/ev/advance", {})["stage"] == "SALVAGE_DISPOSAL"
    assert client.post(f"/api/v1/claims/{cid}/ev/advance", json={}, headers=handler).status_code == 409
    r = client.post(f"/api/v1/claims/{cid}/ev/salvage-events", json={"event": "handed_over", "battery_serial": serial, "recycler_registration_no": "BWM-REC-4410"}, headers=handler)
    assert r.status_code == 409  # dangerous-goods compliant transport required
    r = client.post(f"/api/v1/claims/{cid}/ev/salvage-events", json={"event": "handed_over", "battery_serial": serial, "transport_dg_compliant": True}, headers=handler)
    assert r.status_code == 400  # recycler registration required
    _post(client, handler, f"/api/v1/claims/{cid}/ev/salvage-events", {"event": "handed_over", "battery_serial": serial, "recycler_registration_no": "BWM-REC-4410", "transport_dg_compliant": True, "location": "Recycler dock"}, 201)
    assert client.post(f"/api/v1/claims/{cid}/ev/salvage-events", json={"event": "disposal_certified", "battery_serial": serial}, headers=handler).status_code == 400
    # The OD claim cannot close before the EV case does.
    assert client.post(f"/api/v1/claims/{cid}/close", headers=manager).status_code == 409
    _post(client, handler, f"/api/v1/claims/{cid}/ev/salvage-events", {"event": "disposal_certified", "battery_serial": serial, "certificate_ref": "RECYCLE-CERT-0042"}, 201)
    closed = _post(client, admin, f"/api/v1/claims/{cid}/ev/close", {"closure_notes": "Recertified, pack recycled with certificate."})
    assert closed["stage"] == "CLOSED"
    assert closed["closure"]["salvage_certificate_ref"] == "RECYCLE-CERT-0042"
    assert closed["salvage"]["complete"] is True
    r = client.post(f"/api/v1/claims/{cid}/close", headers=manager)
    assert (r.json().get("details") or {}).get("rule_id") != "IN-EV-CLAIMS-2026"  # EV part of the guard is satisfied


def test_screening_only_ev_claim_skips_specialist_stages_but_still_needs_oem_screening(client):
    cid = _ev_claim(client, peril="glass_damage")
    handler = auth_headers(client, "handler@demo.in")
    v = _get(client, handler, cid)
    assert v["risk_class"] == "screening_only"
    assert v["stage_path"] == [s for s in STAGE_ORDER if s not in {"SAFE_RECOVERY_ISOLATION", "SPECIALIST_SURVEY", "BATTERY_DISPOSITION", "SALVAGE_DISPOSAL"}]
    assert v["operation_status"] == "hold_do_not_operate_pending_inspection"  # nothing is cleared from a photo
    assert v["od_hold"]["held"] is True
    _post(client, handler, f"/api/v1/claims/{cid}/ev/triage", {"signals": []})
    nxt = _post(client, handler, f"/api/v1/claims/{cid}/ev/advance", {})
    assert nxt["stage"] == "OEM_DIAGNOSTICS"
    assert nxt["stage_history"][-1]["skipped_by_rule"] == ["SAFE_RECOVERY_ISOLATION", "SPECIALIST_SURVEY"]
    screening = [t for t in ALL_PASS if t["test"] in {"dtc_scan", "insulation_resistance", "hv_interlock_loop", "state_of_health"}]
    out = _diagnostics(client, cid, screening)
    assert out["diagnostics"]["complete"] is True
    assert _post(client, handler, f"/api/v1/claims/{cid}/ev/advance", {})["stage"] == "COST_BENCHMARKING"
    # New evidence of a hazard escalates the class, rewinds the case and cannot be undone.
    esc = _post(client, handler, f"/api/v1/claims/{cid}/ev/safety-escalations", {"signals": ["underbody_impact", "pack_zone_deformation"], "description": "Workshop found pack tray deformation."}, 201)
    assert esc["risk_class"] == "battery_critical"
    assert esc["stage"] == "SAFE_RECOVERY_ISOLATION"
    assert "BATTERY_DISPOSITION" in esc["stage_path"]


def test_class_escalation_after_sign_off_revokes_the_settlement_clearance(client):
    cid = _ev_claim(client, peril="glass_damage")
    handler = auth_headers(client, "handler@demo.in")
    manager = auth_headers(client, "manager@demo.in")
    _post(client, handler, f"/api/v1/claims/{cid}/ev/triage", {"signals": []})
    _post(client, handler, f"/api/v1/claims/{cid}/ev/advance", {})
    screening = [t for t in ALL_PASS if t["test"] in {"dtc_scan", "insulation_resistance", "hv_interlock_loop", "state_of_health"}]
    _diagnostics(client, cid, screening)
    _post(client, handler, f"/api/v1/claims/{cid}/ev/advance", {})
    _post(client, handler, f"/api/v1/claims/{cid}/ev/cost-benchmark", {"lines": GOOD_LINES[:1]})
    _post(client, handler, f"/api/v1/claims/{cid}/ev/cost-benchmark/review", {"note": "ok"})
    _post(client, handler, f"/api/v1/claims/{cid}/ev/advance", {})
    cleared = _post(client, manager, f"/api/v1/claims/{cid}/ev/technical-sign-off", {})
    assert cleared["settlement_clearance"]["status"] == "granted"
    esc = _post(client, handler, f"/api/v1/claims/{cid}/ev/safety-escalations", {"signals": ["underbody_impact", "pack_zone_deformation"], "description": "Customer reports a burning smell and floor damage."}, 201)
    assert esc["settlement_clearance"]["status"] == "revoked"
    assert esc["od_hold"]["held"] is True
    assert esc["stage"] == "SAFE_RECOVERY_ISOLATION"


def test_od_settlement_approval_payment_and_close_paths_refuse_ev_claims_until_cleared(client):
    cid = _ev_claim(client)
    handler = auth_headers(client, "handler@demo.in")
    manager = auth_headers(client, "manager@demo.in")
    finance = auth_headers(client, "finance@demo.in")
    probes = [
        (client.post(f"/api/v1/claims/{cid}/settlement-recommendations", json={}, headers=handler)),
        (client.post(f"/api/v1/claims/{cid}/approvals", json={"approval_id": "x", "decision": "approved", "rationale": "ok ok ok ok"}, headers=manager)),
        (client.post(f"/api/v1/claims/{cid}/payments", json={"settlement_id": "x", "idempotency_key": "k1", "payee_name": "X", "payee_type": "claimant", "account_last4": "1234", "ifsc": "HDFC0000001"}, headers=finance)),
        (client.post(f"/api/v1/claims/{cid}/payments/agent-release", json={"settlement_id": "x", "idempotency_key": "k2", "payee_name": "X", "payee_type": "claimant", "account_last4": "1234", "ifsc": "HDFC0000001"}, headers=finance)),
        (client.post(f"/api/v1/claims/{cid}/close", headers=manager)),
    ]
    for r in probes:
        assert r.status_code == 409, r.text
        assert r.json()["error_code"] == "HUMAN_REVIEW_REQUIRED"
        assert r.json()["details"]["rule_id"] == "IN-EV-CLAIMS-2026"
        assert "photograph" in r.json()["message"]
        assert r.json()["details"]["ev_workflow_url"].endswith("/ev")


def test_settlement_agent_holds_ev_claims_until_technical_sign_off():
    agent = AGENT_REGISTRY["settlement_recommendation"]

    def run(facts):
        return agent.execute(
            AgentInvocationRequest(
                tenant_id="tenant-in-demo", claim_id="clm-demo-0011", correlation_id="corr-ev-1", workflow_run_id="wf-ev-1",
                actor_user_id="usr-handler", actor_role="claims_handler", claim_type="cashless",
                minimised_facts={"risk_tier": "LOW", "straight_through_eligible": True, "allow_fast_track_auto_approve": True, "active_conditions": [], "calculation": {"net": "10000.00"}, **facts},
                allowed_tools=sorted(agent.allowed_tools),
            )
        )

    held = run({"ev_workflow_required": True, "ev_settlement_cleared": False})
    assert held.status == AgentStatus.NEEDS_HUMAN
    assert held.result["auto_approved"] is False
    assert held.result["ev_workflow_required"] is True
    assert held.actions_executed == []
    assert held.suggested_next_action == "route_to_ev_workflow"
    assert "RC_NO_PHOTO_ONLY_EV_CLEARANCE" in held.decision.reason_codes


def test_risk_engine_never_marks_an_electric_vehicle_straight_through_or_low():
    facts = {
        "effective_loss_inr": "5000.00", "estimated_loss_inr": "5000.00", "idv_inr": "780000.00", "claim_type": "cashless",
        "peril_cause": "road_accident", "claim_status": "REGISTERED", "policy_matched": True, "missing_documents": [],
    }
    ice = classify_claim_risk_from_facts(facts, trigger_event="ice_control")
    assert ice["automation_eligibility"]["straight_through_eligible"] is True  # control
    ev = classify_claim_risk_from_facts({**facts, "is_ev_vehicle": True}, trigger_event="ev_unit")
    assert ev["automation_eligibility"]["straight_through_eligible"] is False
    assert ev["risk_tier"] in {"MEDIUM", "HIGH"}
    assert any(d["code"] == "MEDIUM_EV_HV_SCREENING" for d in ev["drivers"])


def test_damage_ai_never_declares_an_ev_safe_to_operate_from_photographs():
    imgs = [
        {"id": "a", "filename": "front.jpg", "image_angle": "front", "image_quality_status": "acceptable", "sha256": "h1"},
        {"id": "b", "filename": "under.jpg", "image_angle": "underbody", "image_quality_status": "acceptable", "sha256": "h2"},
        {"id": "c", "filename": "close.jpg", "image_angle": "closeup", "image_quality_status": "acceptable", "sha256": "h3"},
    ]
    ev = assess_damage_from_evidence(claim_description="Minor scrape on the front bumper only.", is_ev=True, ev_battery_impacted=False, image_records=imgs)
    det = ev["ev_safety_determination"]
    assert det["safe_to_operate"] == "not_determinable_from_photographs"
    assert det["photo_only_clearance_allowed"] is False
    assert ev["human_assessor_routing"]["route_to_human_assessor"] is True
    assert ev["ev_safety_alerts"]
    ice = assess_damage_from_evidence(claim_description="Minor scrape on the front bumper only.", is_ev=False, ev_battery_impacted=False, image_records=imgs)
    assert ice["ev_safety_determination"] is None


def test_diagnostic_and_disposition_rules_are_enforced_by_the_engine():
    rule = _rule()
    with pytest.raises(DomainError):
        evaluate_diagnostics(rule, "hv_suspected", [{"test": "magic_scan", "result": "pass"}])
    with pytest.raises(DomainError):
        evaluate_diagnostics(rule, "hv_suspected", [{"test": "dtc_scan", "result": "maybe"}])
    inconclusive = evaluate_diagnostics(rule, "hv_suspected", [{"test": "dtc_scan", "result": "inconclusive"}])
    assert inconclusive["outcome"] == "inconclusive" and inconclusive["complete"] is False


def test_ev_dashboard_lifecycle_and_seeded_demo_case(client):
    manager = auth_headers(client, "manager@demo.in")
    life = client.get("/api/v1/ev/lifecycle", headers=manager).json()
    assert [s["stage"] for s in life["stages"]] == [s.value for s in EVStage]
    assert life["controls"]["photo_only_clearance_allowed"] is False
    assert life["controls"]["ai_may_declare_vehicle_safe_to_operate"] is False
    assert set(life["risk_classes"]) == {"battery_critical", "hv_suspected", "screening_only"}
    assert life["oem_diagnostics"]["required_tests"]
    dash = client.get("/api/v1/ev/queues", headers=manager).json()
    assert dash["photo_only_clearance_allowed"] is False
    assert dash["vehicles_on_hv_hold"] >= 1
    assert any(q["queue"] == "ev_safety_escalation" for q in dash["queues"])
    seeded = client.get("/api/v1/claims/clm-demo-0011/ev", headers=manager).json()
    assert seeded["stage"] == "OEM_DIAGNOSTICS"
    assert seeded["risk_class"] == "battery_critical"
    assert seeded["survey"]["qualification"]["qualified"] is True
    assert seeded["recovery"]["tow_method"] == "flatbed"
    assert seeded["triage"]["customer_declared_drivable"] is True
    assert seeded["operation_status"] == "hold_do_not_operate_pending_inspection"
    cases = client.get("/api/v1/ev/cases", headers=manager).json()["items"]
    assert any(c["case_number"] == seeded["case_number"] for c in cases)
    # Workflow-restricted roles: finance cannot drive EV stages; an unassigned surveyor/garage is isolated.
    finance = auth_headers(client, "finance@demo.in")
    assert client.post("/api/v1/claims/clm-demo-0011/ev/advance", json={}, headers=finance).status_code == 403
    garage = auth_headers(client, "garage@demo.in")
    assert client.get("/api/v1/claims/clm-demo-0011/ev", headers=garage).status_code == 403
