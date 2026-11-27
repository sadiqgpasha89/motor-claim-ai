from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services.rules_engine.loader import load_rule_files
from services.sla.actions import RecommendedAction, authorise_action, plan_claim_actions, task_spec
from services.sla.engine import build_claim_instances, build_instance
from services.sla.events import ClaimSLAContext
from services.sla.predictor import MODEL_ID, ClaimSignals, predict_instance
from services.sla.rules import SLA_CATALOGUE_ID, SLARulesService

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)
AGENT_TOOLS = {"create_claim_task", "send_surveyor_followup", "request_documents"}


@pytest.fixture()
def rules() -> SLARulesService:
    return SLARulesService(load_rule_files()[SLA_CATALOGUE_ID])


def _claim(**kw):
    base = dict(
        id="c1", claim_number="CLM-T-1", claim_type="own_damage", queue_name="nagpur", status="SURVEY_ASSIGNED", risk_tier="MEDIUM",
        operational_path="standard", missing_documents=[], ev_battery_impacted=False, triage_summary=None,
        created_at=NOW - timedelta(hours=100), updated_at=NOW - timedelta(hours=1),
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _survey_instance(rules, elapsed_hours: float, report_after: float | None = None, **claim_kw):
    assigned = NOW - timedelta(hours=elapsed_hours)
    a = SimpleNamespace(assigned_at=assigned, surveyor_id="s1", report_received_at=assigned + timedelta(hours=report_after) if report_after else None)
    ctx = ClaimSLAContext(claim=_claim(**claim_kw), now=NOW, assignments=[a])  # type: ignore[arg-type]
    return next(i for i in build_claim_instances(ctx, rules) if i.metric == "survey_completion")


def _repair_instance(rules, elapsed_hours: float):
    rule = rules.resolve("repair_completion", "own_damage", NOW)
    ctx = ClaimSLAContext(claim=_claim(status="REPAIR_IN_PROGRESS"), now=NOW)  # type: ignore[arg-type]
    return build_instance(rule, ctx, NOW - timedelta(hours=elapsed_hours), "inferred")


def _surveyor(load: float, turnaround: float = 60.0, name: str = "Surveyor A") -> dict:
    return {"id": "s1", "name": name, "city": "Nagpur", "load_ratio": load, "avg_turnaround_hours": turnaround, "target_hours": 72.0}


def _signals(**kw) -> ClaimSignals:
    base = dict(claim_id="c1", claim_number="CLM-T-1", claim_type="own_damage", queue="nagpur", risk_tier="MEDIUM", ev_involved=False, surveyor=_surveyor(0.3))
    base.update(kw)
    return ClaimSignals(**base)


# ---------------------------------------------------------------------------------------------------------------------
# Predictor
# ---------------------------------------------------------------------------------------------------------------------
def test_probability_rises_monotonically_with_elapsed_time(rules):
    probs = [predict_instance(_survey_instance(rules, h), _signals(), rules, NOW).breach_probability for h in (10, 60, 110, 150, 165)]
    assert probs == sorted(probs)
    assert probs[-1] > 0.6 > 0.2 > probs[0]


def test_overloaded_surveyor_raises_risk_and_is_named_as_a_driver(rules):
    inst = _survey_instance(rules, 120)
    calm = predict_instance(inst, _signals(surveyor=_surveyor(0.3)), rules, NOW)
    loaded = predict_instance(inst, _signals(surveyor=_surveyor(0.95)), rules, NOW)
    assert loaded.breach_probability > calm.breach_probability
    assert "OWNER_OVERLOADED" in {d["code"] for d in loaded.drivers}
    assert "OWNER_OVERLOADED" not in {d["code"] for d in calm.drivers}
    assert loaded.model_id == MODEL_ID == "sla-risk-baseline-v1"


def test_each_documented_driver_fires_only_with_its_signal(rules):
    inst = _survey_instance(rules, 60)
    p = predict_instance(inst, _signals(reschedule_count=2, followup_count=2, inspection_scheduled=False, risk_tier="HIGH", ev_involved=True,
                                        missing_documents=["RC"], oldest_doc_request_age_hours=10.0, queue_pressure=0.8), rules, NOW)
    codes = {d["code"] for d in p.drivers}
    assert {"RESCHEDULES", "UNANSWERED_FOLLOWUPS", "NO_INSPECTION_SLOT", "CLAIM_COMPLEXITY", "EV_SPECIALIST_SCARCITY", "DOCUMENTS_OUTSTANDING", "QUEUE_PRESSURE"} <= codes
    clean = predict_instance(inst, _signals(), rules, NOW)
    signal_codes = codes - {"CLAIM_COMPLEXITY"}  # MEDIUM tier carries a small baseline complexity factor
    assert not {d["code"] for d in clean.drivers} & signal_codes


def test_breached_clock_is_certain_and_completed_clock_has_no_prediction(rules):
    breached = predict_instance(_survey_instance(rules, 200), _signals(), rules, NOW)
    assert breached.breach_probability == 1.0 and breached.risk_band == "breached"
    assert "SLA_ALREADY_BREACHED" in {d["code"] for d in breached.drivers}
    assert predict_instance(_survey_instance(rules, 100, report_after=50), _signals(), rules, NOW) is None


def test_a_clock_that_has_outrun_its_typical_duration_is_not_predicted_optimistically(rules):
    # Regression: past the typical duration the residual-work estimate collapsed to ~0 and the claim looked safe.
    inst = _survey_instance(rules, 150)
    assert inst.active_elapsed_hours > inst.typical_duration_hours
    pred = predict_instance(inst, _signals(), rules, NOW)
    assert pred.expected_remaining_hours > 5.0
    assert pred.breach_probability > 0.2


def test_parts_delay_applies_only_to_repair_completion(rules):
    garage = {"id": "g1", "name": "Slow Garage", "city": "Nagpur", "load_ratio": 0.5, "avg_turnaround_hours": 120.0, "target_hours": 120.0,
              "customer_chosen": False, "parts_lead_time_days": 5}
    pred = predict_instance(_repair_instance(rules, 100), _signals(surveyor=None, garage=garage, parts_status="awaiting_parts"), rules, NOW)
    assert "PARTS_DELAY" in {d["code"] for d in pred.drivers}
    no_parts = predict_instance(_repair_instance(rules, 100), _signals(surveyor=None, garage=garage, parts_status="received"), rules, NOW)
    assert "PARTS_DELAY" not in {d["code"] for d in no_parts.drivers}
    assert pred.breach_probability > no_parts.breach_probability
    survey_pred = predict_instance(_survey_instance(rules, 60), _signals(garage=garage, parts_status="awaiting_parts"), rules, NOW)
    assert "PARTS_DELAY" not in {d["code"] for d in survey_pred.drivers}


def test_signals_roundtrip_through_dict():
    sig = _signals(missing_documents=["RC"], reassign_candidates={"surveyor": [{"id": "s2", "name": "B", "load_ratio": 0.2}]})
    assert ClaimSignals.from_dict(sig.to_dict()) == sig


# ---------------------------------------------------------------------------------------------------------------------
# Action planning
# ---------------------------------------------------------------------------------------------------------------------
def _plan(rules, inst, sig, queue_context=None):
    pred = predict_instance(inst, sig, rules, NOW)
    return plan_claim_actions([inst], [pred], sig, rules, queue_context)


def test_overloaded_surveyor_yields_a_reassignment_recommendation_with_candidates(rules):
    cand = [{"id": "s2", "name": "Surveyor B", "city": "Nagpur", "load_ratio": 0.2}]
    recs, _ = _plan(rules, _survey_instance(rules, 140), _signals(surveyor=_surveyor(0.95), reassign_candidates={"surveyor": cand}))
    by_action = {r.action: r for r in recs}
    assert "reassign_surveyor" in by_action
    assert by_action["reassign_surveyor"].autonomy == "human_approval"
    assert by_action["reassign_surveyor"].params["candidates"] == cand
    assert all(r.rationale for r in recs)


def test_low_risk_claim_gets_no_actions(rules):
    recs, suppressed = _plan(rules, _survey_instance(rules, 5), _signals())
    assert recs == [] and suppressed == []


def test_cooldown_suppresses_a_repeat_surveyor_followup(rules):
    inst = _survey_instance(rules, 140)
    fresh, _ = _plan(rules, inst, _signals(surveyor=_surveyor(0.9), hours_since_last_followup=2.0))
    assert "remind_surveyor" not in {r.action for r in fresh}
    _, suppressed = _plan(rules, inst, _signals(surveyor=_surveyor(0.9), hours_since_last_followup=2.0))
    assert any(s["action"] == "remind_surveyor" and "cooldown" in s["reason"] for s in suppressed)
    old, _ = _plan(rules, inst, _signals(surveyor=_surveyor(0.9), hours_since_last_followup=40.0))
    assert "remind_surveyor" in {r.action for r in old}


def test_customer_chosen_garage_is_never_reassigned(rules):
    garage = {"id": "g1", "name": "Chosen Garage", "city": "Nagpur", "load_ratio": 0.95, "avg_turnaround_hours": 200.0, "target_hours": 120.0,
              "customer_chosen": True, "parts_lead_time_days": 0}
    other = {"id": "g2", "name": "Other", "city": "Nagpur", "load_ratio": 0.1}
    recs, suppressed = _plan(rules, _repair_instance(rules, 150), _signals(surveyor=None, garage=garage, reassign_candidates={"garage": [other]}))
    assert "reassign_garage" not in {r.action for r in recs}
    assert any(s["action"] == "reassign_garage" and "customer-chosen" in s["reason"] for s in suppressed)
    assert "escalate_manager" in {r.action for r in recs}
    # the same overloaded garage, when the system (not the customer) chose it, may be reassigned via a gated approval
    system_chosen = {**garage, "customer_chosen": False}
    recs, _ = _plan(rules, _repair_instance(rules, 150), _signals(surveyor=None, garage=system_chosen, reassign_candidates={"garage": [other]}))
    assert "reassign_garage" in {r.action for r in recs}


def test_queue_rebalance_is_raised_once_per_run(rules):
    ctx = {"queue": "nagpur", "pressure": 0.8, "late_clocks": 4, "open_clocks": 5, "rebalance_raised": True}
    sig = _signals(queue_pressure=0.8)
    recs, suppressed = _plan(rules, _survey_instance(rules, 160), sig, ctx)
    assert "rebalance_queue" not in {r.action for r in recs}
    assert any(s["action"] == "rebalance_queue" for s in suppressed)
    ctx["rebalance_raised"] = False
    recs, _ = _plan(rules, _survey_instance(rules, 160), sig, ctx)
    assert "rebalance_queue" in {r.action for r in recs}


# ---------------------------------------------------------------------------------------------------------------------
# Authorisation: the single choke point for what the agent may execute
# ---------------------------------------------------------------------------------------------------------------------
def _rec(action: str, rules: SLARulesService, **kw) -> RecommendedAction:
    policy = rules.action_policy(action)
    base = dict(action=action, label=policy.get("label", action), claim_id="c1", claim_number="CLM-T-1", sla_id="SLA-SURVEY-COMPLETION",
                metric="survey_completion", urgency="today", rationale="r", autonomy=policy["autonomy"], tool=policy["tool"], probability=0.9,
                approver_role=policy.get("approver_role"))
    base.update(kw)
    return RecommendedAction(**base)


def _auth(rec, rules, **kw):
    args = dict(mode="execute", claim_type="own_damage", agent_tools=AGENT_TOOLS, request_tools=AGENT_TOOLS, rules=rules, executed_so_far=0)
    args.update(kw)
    return authorise_action(rec, **args)


def test_recommend_mode_never_executes(rules):
    assert _auth(_rec("escalate_manager", rules), rules, mode="recommend").decision == "recommend_only"


def test_autonomous_actions_execute_in_execute_mode(rules):
    for action in ("remind_owner", "escalate_team_lead", "escalate_manager", "prioritize_claim"):
        assert _auth(_rec(action, rules), rules).decision == "execute", action


def test_reassignments_and_rebalance_are_gated_to_a_human(rules):
    for action in ("reassign_surveyor", "reassign_garage", "rebalance_queue"):
        decision = _auth(_rec(action, rules), rules)
        assert decision.decision == "gate_human" and "approval" in decision.reason, action


def test_tools_outside_the_allowlist_are_blocked(rules):
    rec = _rec("remind_owner", rules, tool="initiate_payment")
    assert _auth(rec, rules).decision == "block_policy"
    # a tool the agent has but the caller's request did not grant is also blocked
    assert _auth(_rec("remind_owner", rules), rules, request_tools=set()).decision == "block_policy"


def test_never_autonomous_actions_are_blocked_even_if_a_tool_is_allowed(rules):
    banned = rules.guardrails["never_autonomous"][0]
    rec = replace(_rec("remind_owner", rules), action=banned)
    assert _auth(rec, rules).decision == "block_policy"


def test_third_party_claims_allow_tasks_only(rules):
    reminder = _rec("chase_documents", rules)
    assert reminder.tool != "create_claim_task"
    assert _auth(reminder, rules, claim_type="third_party").decision == "block_policy"
    assert _auth(_rec("escalate_manager", rules), rules, claim_type="third_party").decision == "execute"
    assert _auth(reminder, rules, claim_type="own_damage").decision == "execute"


def test_per_claim_action_budget_is_enforced(rules):
    budget = rules.guardrails["max_autonomous_actions_per_claim_per_run"]
    assert _auth(_rec("remind_owner", rules), rules, executed_so_far=budget - 1).decision == "execute"
    assert _auth(_rec("remind_owner", rules), rules, executed_so_far=budget).decision == "recommend_only"


def test_task_specs_route_approvals_to_managers_and_never_to_external_parties(rules):
    spec = task_spec(_rec("reassign_surveyor", rules), None, approval=True)
    assert spec["task_type"].startswith("sla_approval_") and spec["assigned_role"] == "claims_manager"
    inst = _survey_instance(rules, 100)
    inst.owner_role = "surveyor"
    reminder = task_spec(_rec("remind_owner", rules), inst, approval=False)
    assert reminder["assigned_role"] == "claims_handler"  # the internal owner, never the external surveyor


# ---------------------------------------------------------------------------------------------------------------------
# Agent behaviour on degenerate input
# ---------------------------------------------------------------------------------------------------------------------
def test_agent_with_no_sla_inputs_completes_without_acting():
    from agents.specialists import AGENT_REGISTRY
    from packages.contracts.agents import AgentInvocationRequest

    agent = AGENT_REGISTRY["sla_intelligence"]
    request = AgentInvocationRequest(
        tenant_id="t", claim_id="c", correlation_id="x", workflow_run_id="w", actor_user_id="u", actor_role="claims_manager",
        claim_type="own_damage", minimised_facts={"mode": "execute"}, allowed_tools=sorted(agent.allowed_tools),
    )
    response = agent.execute(request, action_executor=None)
    assert response.status.value == "completed"
    assert response.actions_executed == []
    assert response.result.get("executed_count", 0) == 0
