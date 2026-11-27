"""Claim Triage: routing accuracy, missed-escalation rate and over-escalation rate."""

from __future__ import annotations

from contextlib import nullcontext

from evals.core import AgentEval, CaseResult, Checks, load_dataset
from evals.harness import action_types, model_outage, run_agent, split_request
from evals.metrics import r4, safe_div

AGENT = "claim_triage"
_TIER_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def evaluate() -> AgentEval:
    ds = load_dataset("triage")
    results: list[CaseResult] = []
    route_ok = route_total = 0
    tier_ok = tier_total = 0
    survey_ok = survey_total = 0
    missed = over = 0
    expected_high = scored_cases = 0

    for case in ds.cases:
        raw = dict(case.input)
        outage = bool(raw.pop("_outage", False))
        facts, req = split_request(raw)
        with model_outage() if outage else nullcontext():
            resp = run_agent(AGENT, facts, **req)
        exp = case.expected
        res = resp.result
        ck = Checks()
        scored = not case.known_gap
        scored_cases += int(scored)

        ck.eq("status", resp.status.value, exp.get("status", "completed"))
        if exp.get("status", "completed") != "completed":
            # Fail-safe path (e.g. gateway outage): no tier is computed; the claim must be preserved for a human.
            ck.eq("routing", resp.suggested_next_action, exp["routing"])
            ck.eq("fallback_mode", res.get("fallback_mode"), exp.get("fallback"))
            ck.expect("no_automated_tier", "risk_tier" not in res)
            results.append(ck.result(case, AGENT))
            continue
        got_tier = res["risk_tier"]
        ok = ck.eq("tier", got_tier, exp["tier"])
        if scored:
            tier_total += 1
            tier_ok += int(ok)
            if _TIER_RANK[got_tier] < _TIER_RANK[exp["tier"]]:
                missed += 1  # under-escalation: the dangerous direction
            elif _TIER_RANK[got_tier] > _TIER_RANK[exp["tier"]]:
                over += 1
            expected_high += int(exp["tier"] == "HIGH")

        routing_checks = []
        for key, field in (
            ("queue", "recommended_queue"),
            ("priority", "routing_priority"),
            ("severity", "severity_band"),
            ("drivable", "vehicle_drivable"),
        ):
            if key in exp:
                routing_checks.append(ck.eq(key, res[field], exp[key]))
        if "next" in exp:
            routing_checks.append(ck.eq("next_action", resp.suggested_next_action, exp["next"]))
        if "straight_through" in exp:
            routing_checks.append(
                ck.eq(
                    "straight_through",
                    res["automation_eligibility"]["straight_through_eligible"],
                    exp["straight_through"],
                )
            )
        if scored:
            route_total += 1
            route_ok += int(ok and all(routing_checks))
        if "survey" in exp:
            sok = ck.eq("survey", res["requires_mandatory_survey"], exp["survey"])
            if scored:
                survey_total += 1
                survey_ok += int(sok)
        for task in exp.get("tasks", []):
            made = [a for a in resp.actions_executed if a.action_type == "create_claim_task"]
            ck.expect(
                f"task[{task}]",
                any(task in (a.summary + str(a.payload)) for a in made),
                observed=[a.summary for a in made],
            )
        for tool in exp.get("tools", []):
            ck.expect(
                f"tool[{tool}]",
                tool in action_types(resp) or tool in resp.tools_invoked,
                observed=sorted(action_types(resp)),
            )
        if exp.get("fraud_never_rejects"):
            ck.eq("fraud_score_can_reject", res["fraud_score_can_reject"], False)
        results.append(ck.result(case, AGENT))

    metrics = {
        "tier_accuracy": r4(safe_div(tier_ok, tier_total)),
        "routing_accuracy": r4(safe_div(route_ok, route_total)),
        "survey_trigger_accuracy": r4(safe_div(survey_ok, survey_total)),
        "missed_escalation_rate": r4(safe_div(missed, max(expected_high, 1))),
        "over_escalation_rate": r4(safe_div(over, max(scored_cases - expected_high, 1))),
    }
    return AgentEval(agent=AGENT, metrics=metrics, cases=results)
