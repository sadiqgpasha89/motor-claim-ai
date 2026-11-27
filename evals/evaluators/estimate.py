"""Estimate validation: anomaly-detection precision/recall, false-positive rate and exact money."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from evals.core import AgentEval, CaseResult, Checks, load_dataset
from evals.harness import run_agent
from evals.metrics import precision_recall_f1, r4, safe_div
from services.damage_ai.assessor import validate_estimate_lines

AGENT = "estimate_validation"


def evaluate() -> AgentEval:
    ds = load_dataset("estimate")
    results: list[CaseResult] = []
    tp = fp = fn = 0
    clean_cases = clean_flagged = 0
    money_ok = money_total = 0
    routing_ok = routing_total = 0
    rework_ok = rework_total = 0

    for case in ds.cases:
        inp = case.input
        exp = case.expected
        validation = validate_estimate_lines(
            inp["lines"],
            visible_part_codes=set(inp["visible_part_codes"]) if inp.get("visible_part_codes") else None,
            damage_observations=inp.get("damage_observations"),
        )
        resp = run_agent(AGENT, {"estimate_validation": validation})
        ck = Checks()
        scored = not case.known_gap

        got = Counter(a["type"] for a in validation["anomalies"])
        want = Counter(exp["anomalies"])
        ck.eq("anomalies", sorted(got.elements()), sorted(want.elements()))
        if scored:
            hit = sum((got & want).values())
            tp += hit
            fp += sum(got.values()) - hit
            fn += sum(want.values()) - hit
            if not want:
                clean_cases += 1
                clean_flagged += int(bool(got))
        if "severities" in exp:
            ck.eq("severities", sorted(a["severity"] for a in validation["anomalies"]), sorted(exp["severities"]))
        if "recommended" in exp:
            ok = ck.eq("recommended_total", str(Decimal(validation["total_recommended_inr"])), exp["recommended"])
            if scored:
                money_total += 1
                money_ok += int(ok)
        if "overcharge" in exp:
            ck.eq("overcharge", validation["benchmark_summary"]["potential_overcharge_inr"], exp["overcharge"])

        ok = ck.eq("status", resp.status.value, exp["status"])
        if "routing" in exp:
            ok = ck.eq("routing", resp.decision.routing_outcome if resp.decision else None, exp["routing"]) and ok
        if "next" in exp:
            ok = ck.eq("next_action", resp.suggested_next_action, exp["next"]) and ok
        if scored:
            routing_total += 1
            routing_ok += int(ok)
        if "task" in exp:
            tasks = [a for a in resp.actions_executed if a.action_type == "create_claim_task"]
            ck.expect(
                "task",
                any(exp["task"] in str(a.payload) + a.summary for a in tasks),
                observed=[a.summary for a in tasks],
            )
        if "task_priority" in exp:
            tasks = [a for a in resp.actions_executed if a.action_type == "create_claim_task"]
            ck.expect("task_priority", any(a.payload.get("priority") == exp["task_priority"] for a in tasks))
        if "rework_to" in exp:
            ok = ck.eq(
                "rework_to", resp.rework_requests[0].to_agent if resp.rework_requests else None, exp["rework_to"]
            )
            if scored:
                rework_total += 1
                rework_ok += int(ok)
        results.append(ck.result(case, AGENT))

    prf = precision_recall_f1(tp, fp, fn)
    metrics = {
        "anomaly_precision": r4(prf["precision"]),
        "anomaly_recall": r4(prf["recall"]),
        "false_positive_rate": r4(safe_div(clean_flagged, clean_cases, default=0.0)),
        "recommended_total_accuracy": r4(safe_div(money_ok, money_total)),
        "routing_accuracy": r4(safe_div(routing_ok, routing_total)),
        "rework_accuracy": r4(safe_div(rework_ok, rework_total)),
    }
    return AgentEval(agent=AGENT, metrics=metrics, cases=results)
