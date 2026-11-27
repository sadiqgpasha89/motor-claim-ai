from __future__ import annotations

import pytest

from packages.contracts.errors import DomainError
from services.agent_runtime.actions import ControlledActionExecutor
from services.claims.state_machine import ClaimStatus, validate_transition
from services.workflow.state_specs import WORKFLOW_STATE_SPECS, compute_exponential_backoff_ms
from tests.conftest import auth_headers


def test_workflow_model_states_and_contracts_endpoint(client):
    hdrs = auth_headers(client, "handler@demo.in")
    resp = client.get("/api/v1/orchestration/workflow-model", headers=hdrs)
    assert resp.status_code == 200
    body = resp.json()
    expected_states = {
        "SUBMITTED",
        "REGISTERED",
        "VALIDATION",
        "TRIAGE",
        "FAST_TRACK",
        "SURVEY_REQUIRED",
        "INVESTIGATION_REQUIRED",
        "HUMAN_REVIEW",
        "ASSESSMENT",
        "ESTIMATE_VALIDATION",
        "SETTLEMENT_PENDING_APPROVAL",
        "APPROVED",
        "PAYMENT_PENDING",
        "PAYMENT_RECONCILIATION",
        "CLOSED",
    }
    returned_states = {s["state"]: s for s in body["states"]}
    assert expected_states <= set(returned_states.keys())
    for state_name in expected_states:
        spec = returned_states[state_name]
        assert spec["entry_conditions"]
        assert spec["required_data"]
        assert spec["allowed_actions"]
        assert spec["exit_conditions"]
        assert spec["responsible_agent_or_service"]
        assert spec["sla"]["stage"]
        assert "max_retries" in spec["retry_strategy"]
        assert spec["human_escalation_criteria"]

    # Verify task DAG scheduling specs match post-FNOL parallel & conditional/approval rules
    dag_map = {t["task_key"]: t for t in body["task_dag"]}
    assert dag_map["policy_validation"]["execution_mode"] == "parallel"
    assert dag_map["document_extraction"]["execution_mode"] == "parallel"
    assert dag_map["duplicate_check"]["execution_mode"] == "parallel"
    assert dag_map["customer_communication"]["execution_mode"] == "parallel"
    assert dag_map["claim_triage"]["execution_mode"] == "sequential"
    assert dag_map["damage_assessment"]["execution_mode"] == "conditional"
    assert dag_map["fraud_analysis"]["execution_mode"] == "parallel"
    assert dag_map["fraud_analysis"]["parallel_group"] == "assessment_and_fraud_parallel"
    assert dag_map["settlement_recommendation"]["execution_mode"] == "sequential"
    assert dag_map["payment_execution"]["execution_mode"] == "approval_gated"

    # Canonical state machine rejects skipping mandatory gates
    assert validate_transition("SUBMITTED", "REGISTERED") == ClaimStatus.REGISTERED
    assert validate_transition("TRIAGE", "FAST_TRACK") == ClaimStatus.FAST_TRACK
    assert validate_transition("TRIAGE", "SURVEY_REQUIRED") == ClaimStatus.SURVEY_REQUIRED
    assert validate_transition("TRIAGE", "INVESTIGATION_REQUIRED") == ClaimStatus.INVESTIGATION_REQUIRED
    assert validate_transition("TRIAGE", "HUMAN_REVIEW") == ClaimStatus.HUMAN_REVIEW
    with pytest.raises(DomainError):
        validate_transition("SUBMITTED", "CLOSED")
    with pytest.raises(DomainError):
        validate_transition("VALIDATION", "APPROVED")


def test_agents_cannot_independently_mutate_claim_status():
    exec_guard = ControlledActionExecutor()
    blocked = exec_guard.update_claim_status(
        agent_name="claim_triage",
        target_status="CLOSED",
        actor="agent",
    )
    assert blocked.status == "blocked_policy"
    assert "ClaimOrchestrator" in blocked.summary


def test_exponential_backoff_calculation():
    strat = WORKFLOW_STATE_SPECS["VALIDATION"].retry_strategy
    d1 = compute_exponential_backoff_ms(1, strat)
    d2 = compute_exponential_backoff_ms(2, strat)
    d3 = compute_exponential_backoff_ms(3, strat)
    assert d1 >= 200
    assert d2 > d1
    assert d3 > d2
    assert d3 <= strat.max_delay_ms


def test_parallel_waves_conditional_damage_duplicate_event_pause_resume_dlq_and_compensation(client):
    ph_hdrs = auth_headers(client, "policyholder@demo.in")
    handler_hdrs = auth_headers(client, "handler@demo.in")
    manager_hdrs = auth_headers(client, "manager@demo.in")

    # 1. Create claim -> orchestrator transitions SUBMITTED -> REGISTERED & schedules DAG tasks
    r_fnol = client.post(
        "/api/v1/claims/intimations",
        json={
            "policy_number": "POL-IN-DEMO-2026-1001",
            "vehicle_reg": "MH02DEMO1042",
            "claim_type": "own_damage",
            "peril_cause": "road_accident",
            "incident_location": "Powai, Mumbai",
            "incident_description": "Windshield crack and front bumper scuff.",
            "estimated_loss_inr": "42000.00",
        },
        headers={**ph_hdrs, "Idempotency-Key": "orch-engine-fast-001"},
    )
    assert r_fnol.status_code == 201
    claim_id = r_fnol.json()["claim"]["id"]
    assert r_fnol.json()["claim"]["status"] == "REGISTERED"

    # 2. Duplicate-event protection: upload RC then test duplicate event handling
    r_ev = client.post(
        f"/api/v1/claims/{claim_id}/evidence",
        files={"file": ("rc_ok.txt", b"Registration MH02DEMO1042 Policy POL-IN-DEMO-2026-1001", "text/plain")},
        headers=ph_hdrs,
    )
    assert r_ev.status_code == 201

    # Dispatch event once -> processed; replay same event_id -> duplicate_ignored
    r_evt1 = client.post(
        f"/api/v1/claims/{claim_id}/orchestration/events",
        json={"event_id": "evt-fast-track-001", "event_type": "ManualAdvance", "auto_advance": True},
        headers=handler_hdrs,
    )
    assert r_evt1.status_code == 200
    assert r_evt1.json()["duplicate_ignored"] is False
    orch_res = r_evt1.json()["orchestration"]
    # Post-FNOL parallel wave ran coverage + customer_communication concurrently
    assert any(s["parallel_group"] == "post_fnol_parallel" for s in orch_res["steps_executed"])
    # Because estimated_loss_inr = 42,000 < 50,000 and no photos uploaded yet, damage_assessment waits conditionally
    r_state1 = client.get(f"/api/v1/claims/{claim_id}/orchestration", headers=handler_hdrs)
    assert r_state1.status_code == 200
    tasks_map = {t["task_key"]: t for t in r_state1.json()["scheduled_tasks"]}
    assert tasks_map["damage_assessment"]["status"] == "waiting_condition"
    assert tasks_map["fraud_analysis"]["status"] in {"completed", "waiting_human"}

    # Replay same event_id -> strictly ignored as duplicate!
    r_evt_dup = client.post(
        f"/api/v1/claims/{claim_id}/orchestration/events",
        json={"event_id": "evt-fast-track-001", "event_type": "ManualAdvance", "auto_advance": True},
        headers=handler_hdrs,
    )
    assert r_evt_dup.status_code == 200
    assert r_evt_dup.json()["duplicate_ignored"] is True
    assert r_evt_dup.json()["duplicate_hits"] == 1

    # 3. Workflow Pause & Resume
    r_pause = client.post(
        f"/api/v1/claims/{claim_id}/orchestration/pause",
        json={"reason": "Waiting on customer daylight photo upload"},
        headers=handler_hdrs,
    )
    assert r_pause.status_code == 200
    assert r_pause.json()["paused"] is True

    r_orch_while_paused = client.post(
        f"/api/v1/claims/{claim_id}/orchestrate",
        json={"stop_on_human_gate": True},
        headers=handler_hdrs,
    )
    assert r_orch_while_paused.status_code == 200
    assert "paused" in r_orch_while_paused.json()["paused_reason"].lower()

    # Upload a daylight photo (minimal valid PNG header) so conditional damage_assessment unlocks on resume
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    r_photo = client.post(
        f"/api/v1/claims/{claim_id}/evidence",
        files={"file": ("front_day.png", png_bytes, "image/png")},
        headers=ph_hdrs,
    )
    assert r_photo.status_code == 201

    r_resume = client.post(
        f"/api/v1/claims/{claim_id}/orchestration/resume",
        json={"resolution_notes": "Daylight photo received", "run_ready_stages": True},
        headers=handler_hdrs,
    )
    assert r_resume.status_code == 200
    assert r_resume.json()["was_paused"] is True
    assert any(
        s["agent_name"] == "damage_assessment" and s["status"] == "completed"
        for s in r_resume.json()["orchestration"]["steps_executed"]
    )

    # 4. Trigger timeout -> DLQ -> Replay DLQ item
    r_to = client.post(
        f"/api/v1/claims/{claim_id}/orchestrate/claim_triage",
        json={"enforce_dependencies": True, "simulate_timeout": True},
        headers=handler_hdrs,
    )
    assert r_to.status_code == 200
    assert r_to.json()["agent_response"]["status"] == "timed_out"

    r_dlq = client.get(f"/api/v1/orchestration/dlq?claim_id={claim_id}", headers=handler_hdrs)
    assert r_dlq.status_code == 200
    assert r_dlq.json()["total"] >= 1
    dlq_item = r_dlq.json()["items"][0]
    assert dlq_item["status"] == "open"
    assert len(dlq_item["retry_history"]) >= 2

    r_replay = client.post(
        f"/api/v1/orchestration/dlq/{dlq_item['id']}/replay",
        json={"resolution_notes": "Triage service healthy again"},
        headers=handler_hdrs,
    )
    assert r_replay.status_code == 200
    assert r_replay.json()["status"] == "requeued"

    # 5. Compensation Saga workflow on a mandatory survey claim (releases surveyor load & voids pending approvals)
    r_surv_fnol = client.post(
        "/api/v1/claims/intimations",
        json={
            "policy_number": "POL-IN-DEMO-2026-1001",
            "vehicle_reg": "MH02DEMO1042",
            "claim_type": "cashless",
            "peril_cause": "road_accident",
            "incident_location": "Dadar, Mumbai",
            "incident_description": "Front impact exceeding 50k threshold.",
            "estimated_loss_inr": "68000.00",
        },
        headers={**ph_hdrs, "Idempotency-Key": "orch-comp-001"},
    )
    comp_claim_id = r_surv_fnol.json()["claim"]["id"]
    client.post(
        f"/api/v1/claims/{comp_claim_id}/surveyor-assignments",
        json={"surveyor_id": "prov-surv-01", "garage_id": "prov-gar-01"},
        headers=handler_hdrs,
    )
    r_comp = client.post(
        f"/api/v1/claims/{comp_claim_id}/orchestration/compensate",
        json={"trigger_reason": "Policyholder withdrew claim prior to inspection", "target_state": "HUMAN_REVIEW"},
        headers=manager_hdrs,
    )
    assert r_comp.status_code == 200
    actions_names = {a["action"] for a in r_comp.json()["actions_executed"]}
    assert "release_surveyor_assignment_and_load" in actions_names
    assert "release_garage_intake_allocation" in actions_names

    # 6. SLA sweep detects breached survey timer on clm-demo-0006
    r_sweep = client.post("/api/v1/orchestration/sla/sweep", headers=handler_hdrs)
    assert r_sweep.status_code == 200
    assert r_sweep.json()["breached_count"] >= 1
