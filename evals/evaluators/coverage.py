"""Coverage Intelligence: interpretation accuracy, citation correctness and escalation of ambiguity."""

from __future__ import annotations

from evals.core import AgentEval, CaseResult, Checks, load_dataset
from evals.corpus import citation_is_grounded, parse_clause_ref
from evals.harness import run_agent, split_request, took_adverse_decision
from evals.metrics import r4, rate, safe_div

AGENT = "coverage_intelligence"

_ROW_PREFIX = {
    "own_damage": "Section I — Own Damage",
    "third_party": "Section II",
    "zero_dep": "Zero Depreciation",
    "consumables": "Consumables",
    "ev": "EV Traction Battery",
    "ctl": "Constructive Total Loss",
}


def evaluate() -> AgentEval:
    ds = load_dataset("coverage")
    results: list[CaseResult] = []
    assertions_ok = assertions_total = 0
    citations_valid = citations_total = 0
    cite_hits = cite_total = 0
    escalation: list[bool] = []

    def count(ok: bool) -> None:
        nonlocal assertions_ok, assertions_total
        assertions_total += 1
        assertions_ok += int(ok)

    for case in ds.cases:
        facts, req = split_request(case.input)
        resp = run_agent(AGENT, facts, **req)
        exp = case.expected
        ck = Checks()
        scored = not case.known_gap

        def assert_eq(name: str, observed: object, expected: object, ck: Checks = ck, scored: bool = scored) -> None:
            ok = ck.eq(name, observed, expected)
            if scored:
                count(ok)

        assert_eq("status", resp.status.value, exp["status"])
        if "routing" in exp:
            assert_eq("routing", resp.decision.routing_outcome if resp.decision else None, exp["routing"])
        matrix = {row["coverage_item"]: row["status"] for row in resp.result["coverage_matrix"]}
        for key, want in exp.get("matrix", {}).items():
            got = next((v for k, v in matrix.items() if k.startswith(_ROW_PREFIX[key])), None)
            assert_eq(f"matrix.{key}", got, want)
        for key, want in exp.get("deductibles", {}).items():
            assert_eq(f"deductibles.{key}", resp.result["deductibles_summary"].get(key), want)
        for code in exp.get("reason_codes_include", []):
            assert_eq(f"reason_code.{code}", code in (resp.decision.reason_codes if resp.decision else []), True)
        if "rework_to" in exp:
            assert_eq("rework_to", resp.rework_requests[0].to_agent if resp.rework_requests else None, exp["rework_to"])
        if "task_role" in exp:
            roles = [a.payload.get("task_type") for a in resp.actions_executed if a.action_type == "create_claim_task"]
            ck.expect("task_created", bool(roles), observed=roles)
            tasks = [a for a in resp.actions_executed if a.action_type == "create_claim_task"]
            ck.expect(
                "task_role",
                any(f"({exp['task_role']})" in t.summary for t in tasks),
                observed=[t.summary for t in tasks],
                expected=exp["task_role"],
            )
        if "task_priority" in exp:
            tasks = [a for a in resp.actions_executed if a.action_type == "create_claim_task"]
            ck.expect("task_priority", any(t.payload.get("priority") == exp["task_priority"] for t in tasks))
        if "missing_evidence" in exp:
            assert_eq("missing_evidence", resp.result["missing_evidence"], exp["missing_evidence"])
        if "ambiguities_min" in exp:
            ck.expect(
                "ambiguities_min",
                len(resp.result["ambiguities"]) >= exp["ambiguities_min"],
                observed=len(resp.result["ambiguities"]),
            )
        if "exclusions_checklist_min" in exp:
            ck.expect(
                "exclusions_checklist", len(resp.result["exclusions_checklist"]) >= exp["exclusions_checklist_min"]
            )
        if exp.get("no_adverse_decision"):
            ck.expect("no_adverse_decision", not took_adverse_decision(resp))

        # Citations: every cited clause must exist and the excerpt must be quoted from it.
        for cite in resp.evidence_refs:
            ok, why = citation_is_grounded(cite.source_id, cite.reference, cite.excerpt)
            if scored:
                citations_total += 1
                citations_valid += int(ok)
            if not ok:
                ck.expect("citation_grounded", False, observed=why)
        cited = {cid for c in resp.evidence_refs for cid in parse_clause_ref(c.reference).clause_ids}
        for clause_id in exp.get("cites_all", []):
            hit = clause_id in cited
            ck.expect(f"cites[{clause_id}]", hit, observed=sorted(cited))
            if scored:
                cite_total += 1
                cite_hits += int(hit)

        if scored and exp["status"] in {"needs_human", "rework_required"}:
            escalation.append(resp.status.value in {"needs_human", "rework_required"})
        results.append(ck.result(case, AGENT))

    metrics = {
        "interpretation_accuracy": r4(safe_div(assertions_ok, assertions_total)),
        "citation_validity": r4(safe_div(citations_valid, citations_total)),
        "citation_recall": r4(safe_div(cite_hits, cite_total)),
        "escalation_recall": r4(rate(escalation)),
    }
    return AgentEval(agent=AGENT, metrics=metrics, cases=results)
