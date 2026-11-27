from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from agents.specialists import AGENT_REGISTRY
from packages.contracts.agents import AgentInvocationRequest, AgentStatus
from services.claims.models import Provider
from services.workflow.ecosystem import (
    compute_availability_label,
    compute_provider_load_band,
    compute_sla_label,
    select_best_garage,
    select_best_surveyor,
    verify_surveyor_license,
)
from tests.conftest import auth_headers


def _make_provider(
    pid: str,
    ptype: str,
    name: str,
    *,
    city: str = "Mumbai",
    zones: list[str] | None = None,
    skills: list[str] | None = None,
    ev_capable: bool = False,
    is_network: bool = True,
    licence_status: str = "verified",
    licence_expiry_days: int = 180,
    active_load: int = 2,
    max_capacity: int = 10,
    sla_status: str = "within_sla",
    quality_score: str = "4.70",
    is_available: bool = True,
) -> Provider:
    now = datetime.now(timezone.utc)
    return Provider(
        id=pid,
        tenant_id="tenant-in-demo",
        provider_type=ptype,
        name=name,
        licence_or_contract_id=f"LIC-{pid.upper()}",
        licence_status=licence_status,
        licence_expiry_at=now + timedelta(days=licence_expiry_days),
        city=city,
        service_zones=zones or [city],
        skills=skills or [],
        ev_capable=ev_capable,
        is_network=is_network,
        active_load=active_load,
        max_capacity=max_capacity,
        sla_status=sla_status,
        quality_score=Decimal(quality_score),
        is_available=is_available,
    )


def test_surveyor_license_verification_and_multi_factor_scoring():
    expired_surv = _make_provider(
        "surv-exp",
        "surveyor",
        "Expired Surveyor",
        licence_status="expired",
        licence_expiry_days=-10,
        active_load=0,
    )
    busy_delayed_surv = _make_provider(
        "surv-busy",
        "surveyor",
        "Busy Delayed Surveyor",
        city="Pune",
        active_load=9,
        max_capacity=10,
        sla_status="delayed",
        quality_score="4.20",
    )
    best_surv = _make_provider(
        "surv-best",
        "surveyor",
        "Surveyor C",
        city="Mumbai",
        zones=["Mumbai", "Andheri"],
        skills=["ev_hv", "adas_calibration"],
        ev_capable=True,
        active_load=3,
        max_capacity=10,
        sla_status="within_sla",
        quality_score="4.80",
    )

    assert verify_surveyor_license(expired_surv)["verified"] is False
    assert verify_surveyor_license(best_surv)["verified"] is True

    res = select_best_surveyor(
        [expired_surv, busy_delayed_surv, best_surv],
        incident_location="Andheri West, Mumbai",
        required_skills=["ev_hv", "adas_calibration"],
        ev_required=True,
        preferred_surveyor_id="surv-exp",
    )
    assert res["selected"] is not None
    assert res["selected"].id == "surv-best"
    assert "IIISLA licence verification failure" in res["explanation"]

    res_auto = select_best_surveyor(
        [expired_surv, busy_delayed_surv, best_surv],
        incident_location="Andheri West, Mumbai",
        required_skills=["ev_hv"],
        ev_required=True,
    )
    assert res_auto["selected"].id == "surv-best"
    assert "geography" in res_auto["explanation"].lower()
    assert "capacity" in res_auto["explanation"].lower()
    assert "sla" in res_auto["explanation"].lower()


def test_garage_customer_choice_and_contractual_authorization_guardrails():
    gar_a = _make_provider(
        "gar-a",
        "garage",
        "Garage A",
        city="Mumbai",
        zones=["Mumbai", "Andheri"],
        active_load=3,
        max_capacity=20,
        sla_status="within_sla",
        quality_score="4.70",
    )
    gar_b = _make_provider(
        "gar-b",
        "garage",
        "Garage B",
        city="Mumbai",
        active_load=13,
        max_capacity=15,
        sla_status="delayed",
        quality_score="4.20",
    )
    gar_non_net = _make_provider(
        "gar-nonnet",
        "garage",
        "Non-Network Garage",
        is_network=False,
    )

    # 1. Customer preferred Garage A is eligible -> honoured
    honoured = select_best_garage(
        [gar_a, gar_b],
        incident_location="Andheri, Mumbai",
        required_skills=[],
        ev_required=False,
        customer_preferred_garage_id="gar-a",
    )
    assert honoured["selected"].id == "gar-a"
    assert honoured["customer_preference_honoured"] is True
    assert honoured["authorization_blocked"] is False

    # 2. Unauthorized override by claims_handler -> blocked
    blocked = select_best_garage(
        [gar_a, gar_b],
        incident_location="Andheri, Mumbai",
        required_skills=[],
        ev_required=False,
        customer_preferred_garage_id="gar-a",
        requested_override_garage_id="gar-b",
        override_authorized=False,
        actor_role="claims_handler",
        override_reason="Want to use Garage B",
    )
    assert blocked["authorization_blocked"] is True

    # 3. Authorized override by claims_manager with rationale -> allowed
    authorized = select_best_garage(
        [gar_a, gar_b],
        incident_location="Andheri, Mumbai",
        required_skills=[],
        ev_required=False,
        customer_preferred_garage_id="gar-a",
        requested_override_garage_id="gar-b",
        override_authorized=True,
        actor_role="claims_manager",
        override_reason="Customer consented to switch for specialized paint booth",
    )
    assert authorized["authorization_blocked"] is False
    assert authorized["selected"].id == "gar-b"
    assert authorized["override_applied"] is True

    # 4. Contractual cashless rule blocks non-network garage without authorization
    contract_blocked = select_best_garage(
        [gar_a, gar_non_net],
        incident_location="Mumbai",
        required_skills=[],
        ev_required=False,
        cashless_required=True,
        customer_preferred_garage_id="gar-nonnet",
    )
    assert contract_blocked["authorization_blocked"] is True


def test_load_band_availability_and_sla_labels():
    gar_a = _make_provider("a", "garage", "Garage A", active_load=5, max_capacity=20, sla_status="within_sla")
    gar_b = _make_provider("b", "garage", "Garage B", active_load=13, max_capacity=15, sla_status="delayed")
    surv_c = _make_provider("c", "surveyor", "Surveyor C", active_load=6, max_capacity=10, sla_status="within_sla")

    assert (compute_availability_label(gar_a), compute_sla_label(gar_a.sla_status), compute_provider_load_band(gar_a.active_load, gar_a.max_capacity)) == ("Available", "Within SLA", "Low")
    assert (compute_availability_label(gar_b), compute_sla_label(gar_b.sla_status), compute_provider_load_band(gar_b.active_load, gar_b.max_capacity)) == ("Busy", "Delayed", "High")
    assert (compute_availability_label(surv_c), compute_sla_label(surv_c.sla_status), compute_provider_load_band(surv_c.active_load, surv_c.max_capacity)) == ("Available", "Within SLA", "Medium")


def test_provider_coordination_agent_blocks_unauthorized_override_and_unlicensed_surveyor():
    agent = AGENT_REGISTRY["provider_coordination"]

    # Unauthorized override in stateless agent run -> NEEDS_HUMAN + blocked_policy action
    resp = agent.execute(
        AgentInvocationRequest(
            tenant_id="tenant-in-demo",
            claim_id="clm-demo-0001",
            correlation_id="corr-eco-1",
            workflow_run_id="wf-eco-1",
            actor_user_id="usr-handler",
            actor_role="claims_handler",
            minimised_facts={
                "requires_mandatory_survey": True,
                "preferred_garage_id": "prov-gar-01",
                "selected_garage_id": "prov-gar-02",
                "override_customer_preference": True,
                "override_reason": "",
                "actor_role": "claims_handler",
            },
            allowed_tools=sorted(agent.allowed_tools),
        )
    )
    assert resp.status == AgentStatus.NEEDS_HUMAN
    assert resp.result["override_blocked"] is True
    assert any(a.status == "blocked_policy" for a in resp.actions_executed)

    # Expired surveyor licence -> blocked_policy
    resp_lic = agent.execute(
        AgentInvocationRequest(
            tenant_id="tenant-in-demo",
            claim_id="clm-demo-0001",
            correlation_id="corr-eco-2",
            workflow_run_id="wf-eco-2",
            actor_user_id="usr-handler",
            actor_role="claims_handler",
            minimised_facts={
                "requires_mandatory_survey": True,
                "preferred_surveyor_id": "prov-surv-expired",
                "requested_surveyor_licence_status": "expired",
            },
            allowed_tools=sorted(agent.allowed_tools),
        )
    )
    assert resp_lic.status == AgentStatus.NEEDS_HUMAN
    assert resp_lic.result["surveyor_license_verified"] is False


def test_full_ecosystem_workflow_and_dashboard_api_e2e(client):
    handler_hdrs = auth_headers(client, "handler@demo.in")
    manager_hdrs = auth_headers(client, "manager@demo.in")
    garage_hdrs = auth_headers(client, "garage@demo.in")

    # 1. Ecosystem Dashboard exposes Provider, Availability, SLA, Rating, Current load
    r_dash = client.get("/api/v1/ecosystem/dashboard", headers=handler_hdrs)
    assert r_dash.status_code == 200
    dash = r_dash.json()
    assert dash["summary"]["total_providers"] >= 7
    by_name = {p["name"]: p for p in dash["providers"]}
    gar_a = next(p for name, p in by_name.items() if name.startswith("Garage A"))
    gar_b = next(p for name, p in by_name.items() if name.startswith("Garage B"))
    surv_c = next(p for name, p in by_name.items() if name.startswith("Surveyor C"))
    assert gar_a["availability"] == "Available"
    assert gar_a["sla"] == "Within SLA"
    assert gar_a["rating"] == 4.7
    assert gar_a["current_load"] == "Low"
    assert gar_b["availability"] == "Busy"
    assert gar_b["sla"] == "Delayed"
    assert gar_b["rating"] == 4.2
    assert gar_b["current_load"] == "High"
    assert surv_c["availability"] == "Available"
    assert surv_c["sla"] == "Within SLA"
    assert surv_c["rating"] == 4.8
    assert surv_c["current_load"] == "Medium"

    # 2. Unlicensed surveyor assignment rejected with 400
    r_bad_surv = client.post(
        "/api/v1/claims/clm-demo-0001/surveyor-assignments",
        json={"surveyor_id": "prov-surv-expired"},
        headers=handler_hdrs,
    )
    assert r_bad_surv.status_code == 400

    # 3. Coordinate fresh claim with preferred Garage A -> honoured + parts + pickup + inspection + explanation
    r_fnol = client.post(
        "/api/v1/claims/intimations",
        json={
            "policy_number": "POL-IN-DEMO-2026-1001",
            "vehicle_reg": "MH02DEMO1042",
            "claim_type": "cashless",
            "peril_cause": "road_accident",
            "incident_location": "Andheri West, Mumbai",
            "incident_description": "Front bumper & headlamp impact; drivable.",
            "preferred_garage_id": "prov-gar-01",
            "estimated_loss_inr": "58000.00",
        },
        headers={**handler_hdrs, "Idempotency-Key": "eco-e2e-001"},
    )
    assert r_fnol.status_code == 201
    claim_id = r_fnol.json()["claim"]["id"]

    r_coord = client.post(
        f"/api/v1/claims/{claim_id}/provider-coordination",
        json={"preferred_garage_id": "prov-gar-01", "pickup_required": True, "towing_needed": False},
        headers=handler_hdrs,
    )
    assert r_coord.status_code == 200
    eco = r_coord.json()["ecosystem"]
    assert eco["surveyor_license_verified"] is True
    assert eco["customer_preference_honoured"] is True
    assert eco["garage"]["id"] == "prov-gar-01"
    assert eco["parts_status"] == "all_available"
    assert eco["pickup_delivery_status"] == "pickup_scheduled"
    assert eco["inspection_status"] == "scheduled"
    assert len(eco["customer_notifications"]) >= 1
    assert "Andheri" in eco["coordination_explanation"] or "Garage A" in eco["coordination_explanation"]

    # 4. Unauthorized handler override of customer preferred garage -> 403 NOT_AUTHORISED
    r_unauth = client.post(
        f"/api/v1/claims/{claim_id}/provider-coordination",
        json={
            "preferred_garage_id": "prov-gar-01",
            "selected_garage_id": "prov-gar-02",
            "override_customer_preference": True,
            "override_reason": "Trying without manager role",
        },
        headers=handler_hdrs,
    )
    assert r_unauth.status_code == 403

    # 5. Authorized manager override -> 200 with recorded authorization
    r_auth_ov = client.post(
        f"/api/v1/claims/{claim_id}/provider-coordination",
        json={
            "preferred_garage_id": "prov-gar-01",
            "selected_garage_id": "prov-gar-ev-02",
            "override_customer_preference": True,
            "override_reason": "Customer requested ADAS calibration upgrade at VoltCare",
        },
        headers=manager_hdrs,
    )
    assert r_auth_ov.status_code == 200
    assert r_auth_ov.json()["ecosystem"]["override_applied"] is True
    assert r_auth_ov.json()["ecosystem"]["override_authorized"] is True

    # 6. Inspection Reschedule + Surveyor Report Follow-up + Parts Check + Logistics + Repair Completion Confirmation
    r_resched = client.post(
        f"/api/v1/claims/{claim_id}/ecosystem/inspection/reschedule",
        json={"appointment_at": "2026-12-02T15:00:00Z", "reason": "Customer requested afternoon slot"},
        headers=handler_hdrs,
    )
    assert r_resched.status_code == 200
    assert r_resched.json()["inspection_status"] == "rescheduled"
    assert r_resched.json()["inspection_reschedule_count"] == 1

    r_fup = client.post(
        f"/api/v1/claims/{claim_id}/ecosystem/surveyor-followup",
        json={"notes": "Please upload final survey report", "escalate_to_manager": True},
        headers=handler_hdrs,
    )
    assert r_fup.status_code == 200
    assert r_fup.json()["surveyor_followup_count"] == 1
    assert r_fup.json()["surveyor_followup_status"] == "escalated_sla"

    r_parts = client.post(
        f"/api/v1/claims/{claim_id}/ecosystem/parts-check",
        json={"parts_status": "partial_backorder"},
        headers=handler_hdrs,
    )
    assert r_parts.status_code == 200
    assert r_parts.json()["parts_status"] == "partial_backorder"

    r_log = client.post(
        f"/api/v1/claims/{claim_id}/ecosystem/logistics",
        json={"towing_status": "delivered", "pickup_delivery_status": "at_garage"},
        headers=handler_hdrs,
    )
    assert r_log.status_code == 200
    assert r_log.json()["towing_status"] == "delivered"
    assert r_log.json()["pickup_delivery_status"] == "at_garage"

    # Garage can only access its assigned claim (prov-gar-ev-02 is not usr-garage's prov-gar-01; handler confirms completion)
    r_rep_done = client.post(
        f"/api/v1/claims/{claim_id}/ecosystem/repair-completion",
        json={"milestone": "repair_completed", "notes": "Final QC & road test passed", "confirm_completion": True},
        headers=handler_hdrs,
    )
    assert r_rep_done.status_code == 200
    assert r_rep_done.json()["repair_completion_confirmed"] is True
    assert r_rep_done.json()["ecosystem"]["pickup_delivery_status"] == "delivery_scheduled"

    # Also verify garage@demo.in can update repair status on its assigned claim clm-demo-0001
    r_gar_rep = client.post(
        "/api/v1/claims/clm-demo-0001/repair-status",
        json={"milestone": "repair_completed", "notes": "All body panels painted", "confirm_completion": True},
        headers=garage_hdrs,
    )
    assert r_gar_rep.status_code == 200
    assert r_gar_rep.json()["repair_completion_confirmed"] is True
