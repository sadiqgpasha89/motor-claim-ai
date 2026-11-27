from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from scripts.od_claim_demo import run_od_claim_demo
from services.claims.db import SessionLocal
from services.claims.models import AgentExecutionRecord, Approval, Claim
from services.observability.traces import estimate_cost_inr, estimate_tokens
from tests.conftest import auth_headers

TRACE_KEYS = {
    "claim_id", "workflow_id", "agent_name", "agent_version", "model_name", "prompt_version", "task_input_ref",
    "tool_calls", "tool_outputs", "started_at", "ended_at", "token_usage", "latency_ms", "retry_count",
    "outcome", "confidence", "error_details", "human_intervention", "final_action",
}
DASHBOARD_SECTIONS = {
    "kpis", "failed_agent_executions", "stuck_workflows", "claims_breaching_sla", "human_approval_backlog",
    "fraud_investigation_queue", "payment_reconciliation_failures", "model_api_outages", "cost",
}


@pytest.fixture(scope="module")
def od_run():
    """The OD demo policy has no history, so run it once per seeded database."""
    with TestClient(app) as c:
        return run_od_claim_demo(c)


def test_od_demo_runs_intake_to_closure_with_full_traces(od_run):
    result = od_run
    assert result["final_status"] == "CLOSED"
    assert [s["step"] for s in result["journey"]][0] == "FNOL intake"
    execs = result["claim_360"]["agent_executions"]
    assert len(execs) >= 5
    for e in execs:
        assert TRACE_KEYS <= set(e), TRACE_KEYS - set(e)
        assert e["model_name"] and e["prompt_version"] and e["agent_version"]
        assert e["task_input_ref"].startswith(f"claim:{result['claim_id']}/agent:")
        assert e["token_usage"]["total"] > 0 and e["token_usage"]["source"] == "estimated"
        assert e["started_at"] <= e["ended_at"]
    done = {e["agent_name"] for e in execs if e["outcome"] == "success"}
    assert {"claim_triage", "damage_assessment"} <= done
    assert result["claim_360"]["overview"]["canonical_state"] == "CLOSED"


def test_claim_360_answers_the_eight_officer_questions(client):
    hdrs = auth_headers(client, "handler@demo.in")
    db = SessionLocal()
    try:
        claim_id = db.query(Claim).filter(Claim.claim_number == "CLM-DEMO-2026-0001").one().id
    finally:
        db.close()
    r = client.post(f"/api/v1/claims/{claim_id}/orchestrate", json={"stop_on_human_gate": True}, headers=hdrs)
    assert r.status_code == 200
    body = client.get(f"/api/v1/claims/{claim_id}/claim-360", headers=hdrs).json()
    answers = body["answers"]
    for key in ("what_has_happened", "what_is_happening_now", "what_is_blocked", "why_blocked", "what_did_ai_do",
                "what_did_ai_find", "next_action", "do_i_need_to_act"):
        assert key in answers, key
    assert len(answers["what_is_blocked"]) == len(answers["why_blocked"])
    assert {"overview", "execution_timeline", "evidence", "settlement_and_approvals", "workflow"} <= set(body)
    kinds = {i["kind"] for i in body["execution_timeline"]}
    assert "agent_execution" in kinds and "state_transition" in kinds
    assert [n["agent_name"] for n in body["workflow"]][0] == "fnol_concierge"
    at = [i["at"] for i in body["execution_timeline"]]
    assert at == sorted(at)


def test_claim_360_hides_fraud_from_non_siu_and_blocks_external_roles(client):
    db = SessionLocal()
    try:
        claim_id = db.query(Claim).filter(Claim.claim_number == "CLM-DEMO-2026-0001").one().id
    finally:
        db.close()
    handler = client.get(f"/api/v1/claims/{claim_id}/claim-360", headers=auth_headers(client, "handler@demo.in")).json()
    manager = client.get(f"/api/v1/claims/{claim_id}/claim-360", headers=auth_headers(client, "manager@demo.in")).json()
    assert handler["fraud"] == {"visible": False}
    assert manager["fraud"]["visible"] is True
    for email in ("policyholder@demo.in", "garage@demo.in", "surveyor@demo.in"):
        assert client.get(f"/api/v1/claims/{claim_id}/claim-360", headers=auth_headers(client, email)).status_code == 403
    assert client.get(f"/api/v1/claims/{claim_id}/claim-360").status_code in {401, 403}


def test_claim_360_enforces_tenant_isolation(client):
    db = SessionLocal()
    try:
        other = db.query(Claim).filter(Claim.claim_number == "CLM-OTH-2026-0001").one().id
    finally:
        db.close()
    r = client.get(f"/api/v1/claims/{other}/claim-360", headers=auth_headers(client, "manager@demo.in"))
    assert r.status_code == 403


def test_ops_dashboard_exposes_every_required_section_and_is_role_gated(client, od_run):
    manager = auth_headers(client, "manager@demo.in")
    body = client.get("/api/v1/operations/agent-observability/dashboard", headers=manager).json()
    assert DASHBOARD_SECTIONS <= set(body)
    kpis = body["kpis"]
    assert 0 <= kpis["workflow_success_rate_pct"] <= 100
    assert kpis["basis"] == "measured_from_trace_store"
    cost = body["cost"]
    assert {"by_claim", "by_agent", "by_claim_complexity"} <= set(cost)
    assert cost["by_claim"] and cost["by_agent"]
    assert {r["complexity"] for r in cost["by_claim_complexity"]} <= {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}
    assert "model_gateway_outage_active" in body["model_api_outages"]
    for email in ("handler@demo.in", "policyholder@demo.in", "finance@demo.in"):
        assert client.get("/api/v1/operations/agent-observability/dashboard", headers=auth_headers(client, email)).status_code == 403
    assert client.get("/api/v1/operations/agent-observability/dashboard", headers=auth_headers(client, "auditor@demo.in")).status_code == 200


def test_failed_execution_records_retries_and_error_details(client, od_run):
    handler = auth_headers(client, "handler@demo.in")
    manager = auth_headers(client, "manager@demo.in")
    claim_id = od_run["claim_id"]
    r = client.post(f"/api/v1/claims/{claim_id}/orchestrate/claim_triage", json={"enforce_dependencies": False, "simulate_timeout": True}, headers=handler)
    assert r.status_code == 200 and r.json()["agent_response"]["status"] == "timed_out"
    failed = client.get(f"/api/v1/operations/agent-observability/traces?claim_id={claim_id}&outcome=timeout", headers=manager).json()
    assert failed["count"] >= 1
    t = failed["traces"][0]
    assert t["retry_count"] >= 2 and t["error_details"]["retryable"] is True
    dash = client.get("/api/v1/operations/agent-observability/dashboard", headers=manager).json()
    assert any(f["claim_id"] == claim_id for f in dash["failed_agent_executions"])


def test_human_intervention_is_recorded_then_resolved_by_approval(client):
    handler = auth_headers(client, "handler@demo.in")
    manager = auth_headers(client, "manager@demo.in")
    db = SessionLocal()
    try:
        claim_id = db.query(Claim).filter(Claim.claim_number == "CLM-DEMO-2026-0001").one().id
    finally:
        db.close()
    client.post(f"/api/v1/claims/{claim_id}/orchestrate", json={"stop_on_human_gate": True}, headers=handler)
    traces = client.get(f"/api/v1/operations/agent-observability/traces?claim_id={claim_id}", headers=manager).json()["traces"]
    marked = [t for t in traces if t["human_intervention"]]
    assert marked and all(t["human_intervention"]["required"] for t in marked)
    queue = client.get("/api/v1/operations/approval-queue", headers=manager).json()
    assert {"pending_approvals", "open_human_tasks", "agent_escalations_awaiting_human", "claims_in_human_review"} <= set(queue)


def test_approval_queue_applies_segregation_of_duties(client):
    handler = auth_headers(client, "handler@demo.in")
    manager = auth_headers(client, "manager@demo.in")
    db = SessionLocal()
    try:
        claim = db.query(Claim).filter(Claim.claim_number == "CLM-DEMO-2026-0002").one()
        row = Approval(tenant_id=claim.tenant_id, claim_id=claim.id, action_type="settlement", amount_inr=Decimal("42000.00"), maker_user_id="usr-handler")
        db.add(row)
        db.commit()
        approval_id, claim_id = row.id, claim.id
    finally:
        db.close()
    try:
        own = {a["approval_id"]: a for a in client.get("/api/v1/operations/approval-queue", headers=handler).json()["pending_approvals"]}
        other = {a["approval_id"]: a for a in client.get("/api/v1/operations/approval-queue", headers=manager).json()["pending_approvals"]}
        assert own[approval_id]["can_decide"] is False  # the maker can never be the checker
        assert other[approval_id]["can_decide"] is True
        assert other[approval_id]["claim_id"] == claim_id
        assert client.get("/api/v1/operations/approval-queue", headers=auth_headers(client, "policyholder@demo.in")).status_code == 403
        dash = client.get("/api/v1/operations/agent-observability/dashboard", headers=manager).json()
        assert any(a["approval_id"] == approval_id for a in dash["human_approval_backlog"]["pending_approvals"])
    finally:
        db = SessionLocal()
        try:
            db.query(Approval).filter(Approval.id == approval_id).delete()
            db.commit()
        finally:
            db.close()


def test_trace_builder_is_deterministic_and_cost_uses_rate_card():
    assert estimate_tokens("abcd" * 10) == 10
    assert estimate_tokens({"a": 1}) == estimate_tokens({"a": 1})
    assert estimate_cost_inr("motorclaim-deterministic-stub", 1000, 1000) == Decimal("0.8000")
    assert estimate_cost_inr("unknown-model", 1000, 0) == Decimal("0.5000")


def test_every_trace_row_has_a_non_empty_model_and_outcome():
    db = SessionLocal()
    try:
        rows = db.query(AgentExecutionRecord).all()
        assert rows
        assert all(r.outcome and r.model_name for r in rows if r.created_at)
    finally:
        db.close()
