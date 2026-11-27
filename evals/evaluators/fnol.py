"""FNOL Concierge: completeness, extraction accuracy and intake success."""

from __future__ import annotations

from evals.core import AgentEval, CaseResult, Checks, load_dataset
from evals.harness import action_types, run_agent, split_request, took_adverse_decision
from evals.metrics import r4, rate, safe_div

AGENT = "fnol_concierge"


def evaluate() -> AgentEval:
    ds = load_dataset("fnol")
    results: list[CaseResult] = []
    completeness: list[bool] = []
    intake_ok: list[bool] = []
    actions_ok: list[bool] = []
    field_hits = field_total = 0

    for case in ds.cases:
        facts, req = split_request(case.input)
        resp = run_agent(AGENT, facts, **req)
        exp = case.expected
        ck = Checks()

        ck.eq("status", resp.status.value, exp["status"])
        registered = resp.result.get("registration_allowed") is True and resp.status.value in {
            "completed",
            "insufficient_evidence",
        }
        ck.expect("registration_allowed", registered, observed=resp.result.get("registration_allowed"), expected=True)
        if not case.known_gap:
            intake_ok.append(registered)

        if "missing" in exp:
            ok = set(resp.missing_information) == set(exp["missing"])
            ck.expect("missing_information", ok, observed=resp.missing_information, expected=exp["missing"])
            if not case.known_gap:
                completeness.append(ok)

        structured = resp.result.get("structured_incident", {})
        for key, value in exp.get("structured", {}).items():
            hit = structured.get(key) == value
            ck.expect(f"structured.{key}", hit, observed=structured.get(key), expected=value)
            if not case.known_gap:
                field_hits += int(hit)
                field_total += 1

        if "actions" in exp:
            got = action_types(resp)
            ok = got == set(exp["actions"])
            ck.expect("actions", ok, observed=sorted(got), expected=sorted(exp["actions"]))
            if not case.known_gap:
                actions_ok.append(ok)
        if "checklist" in exp:
            ck.expect(
                "checklist",
                set(exp["checklist"]) <= set(resp.result.get("recommended_checklist", [])),
                observed=resp.result.get("recommended_checklist"),
                expected=exp["checklist"],
            )
        if exp.get("ev_flatbed"):
            tow = [a for a in resp.actions_executed if a.action_type == "dispatch_towing"]
            ck.expect("ev_flatbed", bool(tow) and tow[0].payload.get("ev_flatbed") is True)
        if exp.get("no_coverage_decision"):
            ck.expect(
                "no_coverage_decision",
                not took_adverse_decision(resp),
                observed=resp.decision.routing_outcome if resp.decision else None,
            )

        results.append(ck.result(case, AGENT))

    metrics = {
        "completeness_accuracy": r4(rate(completeness)),
        "field_extraction_accuracy": r4(safe_div(field_hits, field_total)),
        "intake_success_rate": r4(rate(intake_ok)),
        "action_accuracy": r4(rate(actions_ok)),
    }
    return AgentEval(agent=AGENT, metrics=metrics, cases=results)
