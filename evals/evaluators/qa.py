"""QA & Compliance: defect detection, closure checklist accuracy, rework routing and false-closure rate."""

from __future__ import annotations

from contextlib import nullcontext

from evals.core import AgentEval, CaseResult, Checks, load_dataset
from evals.harness import model_outage, run_agent
from evals.metrics import r4, rate, safe_div

AGENT = "qa_compliance"


def evaluate() -> AgentEval:
    ds = load_dataset("qa")
    results: list[CaseResult] = []
    detected = injected = 0
    closure_ok: list[bool] = []
    rework_ok: list[bool] = []
    false_closure = blocked_expected = 0

    for case in ds.cases:
        raw = dict(case.input)
        outage = bool(case.expected.get("outage"))
        # ``checks_only`` supplies the entire checklist; otherwise the case overrides the all-pass baseline.
        checks = dict(raw["checks_only"] if "checks_only" in raw else raw["checks"])
        facts = {"checks": checks}
        with model_outage() if outage else nullcontext():
            resp = run_agent(AGENT, facts)
        exp = case.expected
        ck = Checks()
        scored = not case.known_gap

        if outage:
            ck.eq("status", resp.status.value, exp["status"])
            ck.eq("next_action", resp.suggested_next_action, exp["next"])
            ck.eq("no_closure_flag", resp.result.get("closure_eligible", False), False)
            results.append(ck.result(case, AGENT))
            continue

        eligible = bool(resp.result["closure_eligible"])
        ok = ck.eq("closure_eligible", eligible, exp["closure"])
        if scored:
            closure_ok.append(ok)
            if exp["closure"] is False:
                blocked_expected += 1
                false_closure += int(eligible)
        if "status" in exp:
            ck.eq("status", resp.status.value, exp["status"])
        if "routing" in exp:
            ck.eq("routing", resp.decision.routing_outcome if resp.decision else None, exp["routing"])
        if "next" in exp:
            ck.eq("next_action", resp.suggested_next_action, exp["next"])
        if "readiness" in exp:
            ck.eq("readiness", resp.result["audit_readiness_score"], exp["readiness"])
        if "failed" in exp:
            got = sorted(resp.result["failed_controls"])
            hit = ck.eq("failed_controls", got, sorted(exp["failed"]))
            if scored:
                injected += len(exp["failed"])
                detected += len(set(exp["failed"]) & set(got))
            _ = hit
        if "rework" in exp:
            got_rework = sorted(r.to_agent for r in resp.rework_requests)
            rok = ck.eq("rework_targets", got_rework, sorted(exp["rework"]))
            if scored:
                rework_ok.append(rok)
            ck.expect("rework_is_blocking", all(r.blocking for r in resp.rework_requests))
        if exp.get("task"):
            tasks = [a for a in resp.actions_executed if a.action_type == "create_claim_task"]
            ck.expect("remediation_task", bool(tasks), observed=[a.action_type for a in resp.actions_executed])
        if exp.get("mirrors_input"):
            ck.eq("checks_unaltered", resp.result["checks"], checks)
        results.append(ck.result(case, AGENT))

    metrics = {
        "defect_detection_recall": r4(safe_div(detected, injected)),
        "closure_checklist_accuracy": r4(rate(closure_ok)),
        "rework_routing_accuracy": r4(rate(rework_ok)),
        "false_closure_rate": r4(safe_div(false_closure, blocked_expected, default=0.0)),
    }
    return AgentEval(agent=AGENT, metrics=metrics, cases=results)
