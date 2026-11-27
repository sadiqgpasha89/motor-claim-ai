from __future__ import annotations

from sqlalchemy import func, select

from services.claims.db import SessionLocal
from services.claims.models import ClaimTask, SurveyAssignment
from services.rules_engine.loader import load_rule_files
from services.sla.rules import SLA_CATALOGUE_ID, SLA_METRICS
from tests.conftest import auth_headers

AUTONOMOUS_TASK_PREFIX = "sla_"
APPROVAL_TASK_PREFIX = "sla_approval_"


def _assignment_snapshot() -> list[tuple[str, str, str]]:
    db = SessionLocal()
    try:
        return sorted((a.id, a.claim_id, a.surveyor_id) for a in db.scalars(select(SurveyAssignment)))
    finally:
        db.close()


def _sla_task_count() -> int:
    db = SessionLocal()
    try:
        return db.scalar(select(func.count()).select_from(ClaimTask).where(ClaimTask.task_type.like("sla\\_%", escape="\\"))) or 0
    finally:
        db.close()


# ---------------------------------------------------------------------------------------------------------------------
# Rules service
# ---------------------------------------------------------------------------------------------------------------------
def test_rules_endpoint_serves_the_versioned_catalogue(client):
    body = client.get("/api/v1/sla/rules", headers=auth_headers(client, "handler@demo.in")).json()
    assert body["validation_errors"] == []
    assert list(body["metrics"]) == list(SLA_METRICS)
    rule = body["rules"][0]
    for key in ("rule_version", "applicable_claim_types", "trigger_event", "start_condition", "pause_conditions", "deadline_hours", "escalation_sequence", "responsible_team", "breach_action"):
        assert key in rule, key
    versions = {r["rule_version"] for r in body["rules"] if r["metric"] == "document_verification"}
    assert {"1.0.0", "1.1.0"} <= versions


def test_rules_validation_endpoint_reports_errors_without_publishing(client):
    hdrs = auth_headers(client, "manager@demo.in")
    catalogue = load_rule_files()[SLA_CATALOGUE_ID]  # validation takes the raw catalogue, not the public read view
    ok = client.post("/api/v1/sla/rules/validate", json={"catalogue": catalogue}, headers=hdrs).json()
    assert ok["valid"] is True and ok["errors"] == []
    broken = {**catalogue, "rules": [{**catalogue["rules"][0], "stop_event": "ClaimTeleported"}, *catalogue["rules"][1:]]}
    bad = client.post("/api/v1/sla/rules/validate", json={"catalogue": broken}, headers=hdrs).json()
    assert bad["valid"] is False and any("ClaimTeleported" in e for e in bad["errors"])
    after = client.get("/api/v1/sla/rules", headers=hdrs).json()
    assert after["validation_errors"] == []  # the draft was never applied


# ---------------------------------------------------------------------------------------------------------------------
# Dashboard and predictive views
# ---------------------------------------------------------------------------------------------------------------------
def test_dashboard_has_one_row_per_metric_driven_by_the_catalogue(client):
    body = client.get("/api/v1/sla/dashboard", headers=auth_headers(client, "handler@demo.in")).json()
    rows = {m["metric"]: m for m in body["metrics"]}
    assert set(rows) == set(SLA_METRICS)
    assert rows["survey_completion"]["regulatory_hours"] == 360
    assert rows["claim_registration"]["deadline_hours"] < 1  # near real-time, from the catalogue
    assert rows["payment_processing"]["regulatory_hours"] is None
    assert body["totals"]["open_clocks"] >= 1 and body["model_id"] == "sla-risk-baseline-v1"
    assert sum(body["risk_band_counts"].values()) >= 1


def test_seeded_scenarios_are_detected_in_the_insights(client):
    body = client.get("/api/v1/sla/insights", headers=auth_headers(client, "handler@demo.in")).json()
    assert body["claims_likely_to_breach"], "seeded survey/garage scenarios should predict breaches"
    assert any(s["load_ratio"] >= 0.8 for s in body["surveyors"]), "seeded overloaded surveyor is reported"
    assert any(g["name"] for g in body["garages"]) and body["queues"] and "claims" in body["documents"]


def test_predictions_are_ranked_and_explainable(client):
    items = client.get("/api/v1/sla/predictions?min_risk_band=at_risk", headers=auth_headers(client, "handler@demo.in")).json()["items"]
    assert items
    probs = [i["breach_probability"] for i in items]
    assert probs == sorted(probs, reverse=True)
    assert all(i["drivers"] for i in items if i["risk_band"] != "on_track")
    assert all(i["risk_band"] in {"at_risk", "critical", "breached"} for i in items)


def test_per_claim_sla_view_and_unknown_claim(client):
    hdrs = auth_headers(client, "handler@demo.in")
    claim_id = client.get("/api/v1/sla/predictions", headers=hdrs).json()["items"][0]["claim_id"]
    view = client.get(f"/api/v1/claims/{claim_id}/sla", headers=hdrs)
    assert view.status_code == 200 and view.json()["claim_id"] == claim_id
    assert client.get("/api/v1/claims/does-not-exist/sla", headers=hdrs).status_code == 404


def test_sla_data_is_tenant_isolated_and_role_restricted(client):
    handler = auth_headers(client, "handler@demo.in")
    other = auth_headers(client, "other@other.in")
    own_claim = client.get("/api/v1/sla/predictions", headers=handler).json()["items"][0]["claim_id"]
    assert client.get(f"/api/v1/claims/{own_claim}/sla", headers=other).status_code in {403, 404}
    other_ids = {i["claim_id"] for i in client.get("/api/v1/sla/predictions?min_risk_band=on_track&limit=100", headers=other).json()["items"]}
    assert own_claim not in other_ids
    for email in ("policyholder@demo.in", "garage@demo.in", "surveyor@demo.in"):
        assert client.get("/api/v1/sla/dashboard", headers=auth_headers(client, email)).status_code == 403, email


# ---------------------------------------------------------------------------------------------------------------------
# Predictive SLA agent: recommends broadly, executes narrowly
# ---------------------------------------------------------------------------------------------------------------------
def test_recommend_mode_creates_and_changes_nothing(client):
    before_tasks, before_assign = _sla_task_count(), _assignment_snapshot()
    resp = client.post("/api/v1/sla/agent/run", json={"mode": "recommend", "min_risk_band": "at_risk"}, headers=auth_headers(client, "handler@demo.in"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "recommend" and body["totals"]["recommended"] >= 1
    assert body["totals"]["executed"] == 0 and body["totals"]["gated_for_approval"] == 0
    assert _sla_task_count() == before_tasks and _assignment_snapshot() == before_assign
    assert all(a["status"] != "executed" for r in body["results"] for a in r["actions"])


def test_execute_requires_an_execution_role(client):
    for email in ("handler@demo.in", "fnol@demo.in", "siu@demo.in"):
        resp = client.post("/api/v1/sla/agent/run", json={"mode": "execute"}, headers=auth_headers(client, email))
        assert resp.status_code == 403, email


def test_unknown_claim_ids_are_rejected(client):
    resp = client.post("/api/v1/sla/agent/run", json={"mode": "recommend", "claim_ids": ["nope"]}, headers=auth_headers(client, "manager@demo.in"))
    assert resp.status_code == 404


def test_execute_runs_only_authorised_actions_and_gates_reassignment(client):
    hdrs = auth_headers(client, "manager@demo.in")
    before_assign = _assignment_snapshot()
    resp = client.post("/api/v1/sla/agent/run", json={"mode": "execute", "min_risk_band": "at_risk"}, headers=hdrs)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["totals"]["executed"] + body["totals"]["gated_for_approval"] + body["totals"]["already_open"] >= 1

    actions = [a for r in body["results"] for a in r["actions"]]
    assert actions
    allowed_tools = {"create_claim_task", "send_surveyor_followup", "request_documents"}
    assert {a["action_type"] for a in actions} <= allowed_tools | {a["action_type"] for a in actions if a["status"] != "executed"}
    for r in body["results"]:
        for rec in r["recommended_actions"]:
            if rec["action"] in {"reassign_surveyor", "reassign_garage", "rebalance_queue"}:
                assert rec["autonomy"] == "human_approval"

    # Reassignment never happens directly: it becomes a manager approval task, and surveyor assignments are untouched.
    assert _assignment_snapshot() == before_assign
    db = SessionLocal()
    try:
        approval_tasks = list(db.scalars(select(ClaimTask).where(ClaimTask.task_type.like("sla\\_approval\\_%", escape="\\"))))
        assert approval_tasks, "seeded overload scenarios must raise approval tasks"
        assert {t.assigned_role for t in approval_tasks} == {"claims_manager"}
        autonomous = list(db.scalars(select(ClaimTask).where(ClaimTask.task_type.like("sla\\_%", escape="\\"), ~ClaimTask.task_type.like("sla\\_approval\\_%", escape="\\"))))
        assert all(t.assigned_role in {"claims_manager", "claims_handler", "finance_ops", "fnol_executive", "claims_team_lead"} for t in autonomous)
    finally:
        db.close()


def test_execute_is_idempotent(client):
    hdrs = auth_headers(client, "manager@demo.in")
    payload = {"mode": "execute", "min_risk_band": "at_risk"}
    client.post("/api/v1/sla/agent/run", json=payload, headers=hdrs)
    settled = _sla_task_count()
    second = client.post("/api/v1/sla/agent/run", json=payload, headers=hdrs).json()
    assert _sla_task_count() == settled, "re-running must reuse open tasks, not duplicate them"
    assert second["totals"]["executed"] == 0 or second["totals"]["already_open"] >= 1


def test_execute_writes_an_audit_trail_attributed_to_the_agent_and_the_human(client):
    from services.claims.models import AuditEvent  # local import: only needed here

    hdrs = auth_headers(client, "manager@demo.in")
    run = client.post("/api/v1/sla/agent/run", json={"mode": "execute", "min_risk_band": "at_risk"}, headers=hdrs).json()
    db = SessionLocal()
    try:
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "SLA_AGENT_ACTIONS_EXECUTED")))
    finally:
        db.close()
    if run["totals"]["executed"] or run["totals"]["gated_for_approval"]:
        assert events and all(e.actor_id.startswith("agent:sla_intelligence/on-behalf-of:") for e in events)


def test_sla_agent_is_in_the_governed_contract_registry(client):
    body = client.get("/api/v1/agents/contracts", headers=auth_headers(client, "manager@demo.in"))
    data = body.json()
    assert data["operations_agents"] == ["sla_intelligence"]
    contracts = {c["agent_name"]: c for c in data["contracts"]} if isinstance(data.get("contracts"), list) else data["contracts"]
    sla = contracts["sla_intelligence"]
    prohibited = " ".join(sla["prohibited_actions"])
    assert "approve_settlement" in prohibited and "initiate_payment" in prohibited and "edit_sla_rules" in prohibited
