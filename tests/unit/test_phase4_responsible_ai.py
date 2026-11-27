from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from evals.db_scenarios import scenario_db, seed_claim, seed_customer, seed_policy, seed_tenant, seed_vehicle
from evals.safety import fairness, hallucination, tool_misuse
from services.claims.models import AgentExecutionRecord, Approval
from services.evaluation.cost_latency import cost_latency_report
from services.evaluation.overrides import human_override_report


def _setup(db):
    tenant = seed_tenant(db)
    cust = seed_customer(db, tenant)
    veh = seed_vehicle(db, tenant)
    pol = seed_policy(db, tenant, cust, veh)
    return tenant, seed_claim(db, tenant, cust, veh, pol)


def _approval(db, tenant, claim, decision):
    db.add(Approval(tenant_id=tenant.id, claim_id=claim.id, action_type="settlement_approval", maker_user_id="m", decision=decision, decided_at=datetime.now(timezone.utc)))


def _trace(db, tenant, claim, agent, *, ms=100, model="claude-sonnet-4", cost="1.0000", retry=0, human=None):
    db.add(
        AgentExecutionRecord(
            tenant_id=tenant.id, claim_id=claim.id, workflow_run_id="wf", agent_name=agent, status="completed",
            duration_ms=ms, model_name=model, tokens_input=1000, tokens_output=500, cost_inr=Decimal(cost),
            retry_count=retry, human_intervention=human,
        )
    )


def test_override_rate_counts_non_approved_decisions_and_alerts():
    with scenario_db() as db:
        tenant, claim = _setup(db)
        for d in ["approved", "approved", "approved", "rejected", "rejected", "pending"]:
            _approval(db, tenant, claim, d)
        _trace(db, tenant, claim, "settlement_recommendation", human={"required": True, "resolved": True})
        db.commit()
        rep = human_override_report(db, tenant.id)
    assert rep["approvals_decided"] == 5 and rep["approvals_pending"] == 1
    assert rep["overridden"] == 2 and rep["override_rate_pct"] == 40.0
    assert rep["alerts"], "40% is above the 30% alert threshold with 5 decisions"
    assert rep["agent_interventions"][0]["human_resolved"] == 1


def test_override_alert_needs_enough_decisions():
    with scenario_db() as db:
        tenant, claim = _setup(db)
        _approval(db, tenant, claim, "rejected")
        db.commit()
        assert human_override_report(db, tenant.id)["alerts"] == []


def test_override_report_is_tenant_scoped():
    with scenario_db() as db:
        tenant, claim = _setup(db)
        _approval(db, tenant, claim, "rejected")
        db.commit()
        assert human_override_report(db, "other-tenant")["approvals_decided"] == 0


def test_cost_latency_flags_budget_breaches_and_saving():
    with scenario_db() as db:
        tenant, claim = _setup(db)
        for _ in range(3):
            _trace(db, tenant, claim, "fraud_intelligence", ms=9000, retry=1)
        db.commit()
        rep = cost_latency_report(db, tenant.id)
    row = rep["agents"][0]
    assert row["latency_over_budget"] and row["retry_rate_pct"] == 100.0
    assert Decimal(row["estimated_saving_inr_on_cheapest_model"]) > 0
    assert rep["cost_over_budget"] is False
    text = " ".join(rep["optimisation_hints"])
    assert "latency" in text and "retried" in text


def test_cost_latency_no_hints_below_min_samples():
    with scenario_db() as db:
        tenant, claim = _setup(db)
        _trace(db, tenant, claim, "fraud_intelligence", ms=9000)
        db.commit()
        assert cost_latency_report(db, tenant.id)["optimisation_hints"] == []


def test_hallucination_checker_flags_invented_numbers():
    assert hallucination.ungrounded_claims("Paid INR 5,00,000 under CLM-9", {"x": "CLM-9"}) == ["INR 5,00,000"]


def test_new_suites_pass_on_the_real_system():
    for suite in (tool_misuse, hallucination, fairness):
        res = suite.run()
        assert res.passed, [f"{i.name}: {i.detail}" for i in res.failures]
