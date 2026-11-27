"""Provider Coordination: assignment success, SLA adherence and override-guardrail compliance."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from evals.core import AgentEval, Case, CaseResult, Checks, load_dataset
from evals.harness import model_outage, run_agent, split_request
from evals.metrics import r4, rate, safe_div
from services.claims.models import Provider
from services.workflow.ecosystem import select_best_garage, select_best_surveyor

AGENT = "provider_coordination"


def build_provider(spec: dict[str, Any]) -> Provider:
    expiry = datetime.now(timezone.utc) + timedelta(days=int(spec["exp_days"])) if "exp_days" in spec else None
    city = spec.get("city", "Mumbai")
    return Provider(
        id=spec["id"],
        tenant_id="tenant-eval",
        provider_type=spec["type"],
        name=spec["id"],
        licence_or_contract_id=f"IIISLA-{spec['id']}",
        licence_status=spec.get("lic", "verified"),
        licence_expiry_at=expiry,
        city=city,
        service_zones=spec.get("zones", [city]),
        skills=spec.get("skills", []),
        ev_capable=spec.get("ev", False),
        is_network=spec.get("net", True),
        active_load=spec.get("load", 2),
        max_capacity=spec.get("cap", 10),
        sla_status=spec.get("sla", "within_sla"),
        quality_score=Decimal(spec.get("q", "4.5")),
        is_available=spec.get("avail", True),
    )


def _selection(case: Case, ck: Checks) -> tuple[bool, bool]:
    """Returns (assignment_correct, guardrail_case_correct)."""
    providers = [build_provider(p) for p in case.input["providers"]]
    params = dict(case.input["params"])
    exp = case.expected
    if case.input["kind"] == "garage":
        res = select_best_garage(providers, **params)
    else:
        res = select_best_surveyor(providers, **params)
    selected = res["selected"].id if res.get("selected") else None
    ok = ck.eq("selected", selected, exp["selected"])
    if "blocked" in exp:
        ok = ck.eq("blocked", bool(res.get("blocked")), exp["blocked"]) and ok
    for key, field in (
        ("honoured", "customer_preference_honoured"),
        ("override_applied", "override_applied"),
        ("ev_safety_override", "ev_safety_override_applied"),
        ("auth_blocked", "authorization_blocked"),
    ):
        if key in exp:
            ok = ck.eq(key, bool(res.get(field)), exp[key]) and ok
    for pid, reason in exp.get("ineligible", {}).items():
        scored = {c["provider_id"]: c for c in res.get("candidates_evaluated", [])}
        got = scored.get(pid, {}).get("ineligible_reasons", [])
        ok = ck.expect(f"ineligible[{pid}]", any(reason in r for r in got), observed=got, expected=reason) and ok
    guard = bool({"auth_blocked", "ineligible", "ev_safety_override"} & set(exp)) or exp.get("blocked") is True
    return ok, guard and ok


def _agent(case: Case, ck: Checks) -> tuple[bool, list[bool]]:
    raw = {k: v for k, v in case.input.items() if k != "mode"}
    outage = bool(raw.pop("_outage", False))
    facts, req = split_request(raw)
    with model_outage() if outage else nullcontext():
        resp = run_agent(AGENT, facts, **req)
    exp = case.expected
    ok = ck.eq("status", resp.status.value, exp["status"])
    if "routing" in exp:
        ok = ck.eq("routing", resp.decision.routing_outcome if resp.decision else None, exp["routing"]) and ok
    if "next" in exp:
        ok = ck.eq("next_action", resp.suggested_next_action, exp["next"]) and ok
    if outage:
        ok = ck.eq("fallback_mode", resp.result.get("fallback_mode"), exp.get("fallback")) and ok
        ck.eq("no_actions", len(resp.actions_executed), 0)
        return ok, []
    types = [a.action_type for a in resp.actions_executed]
    if "override_blocked" in exp:
        ok = ck.eq("override_blocked", resp.result["override_blocked"], exp["override_blocked"]) and ok
    for tool in exp.get("tools", []):
        ok = ck.expect(f"tool[{tool}]", tool in types, observed=types) and ok
    if exp.get("no_inspection"):
        ok = ck.expect("no_inspection_scheduled", "schedule_inspection" not in types, observed=types) and ok
    if exp.get("no_customer_update"):
        ok = ck.expect("no_customer_update", "send_customer_update" not in types, observed=types) and ok
    if "task_role" in exp:
        tasks = [a for a in resp.actions_executed if a.action_type == "create_claim_task"]
        ok = (
            ck.expect(
                "task_role",
                any(exp["task_role"] in a.summary or exp["task_role"] in str(a.payload) for a in tasks),
                observed=[a.summary for a in tasks],
            )
            and ok
        )
    if "sla" in exp:
        ok = ck.eq("sla_deadlines", resp.result["sla_deadlines"], exp["sla"]) and ok
    if "ev_capable_required" in exp:
        ok = ck.eq("ev_capable_required", resp.result["ev_capable_required"], exp["ev_capable_required"]) and ok
    for code in exp.get("reason_codes_include", []):
        ok = ck.expect(f"reason_code[{code}]", code in (resp.decision.reason_codes if resp.decision else [])) and ok
    sla_checks: list[bool] = []
    if "sla" in exp:
        sla_checks.append(ck.items["sla_deadlines"])
    if exp.get("customer_update") == "non_adverse":
        updates = [a for a in resp.actions_executed if a.action_type == "send_customer_update"]
        good = bool(updates) and all(u.payload.get("is_adverse") is False for u in updates)
        sla_checks.append(
            ck.expect("customer_update_non_adverse", good, observed=[u.payload.get("is_adverse") for u in updates])
        )
    return ok, sla_checks


def evaluate() -> AgentEval:
    ds = load_dataset("coordination")
    results: list[CaseResult] = []
    assignments: list[bool] = []
    guardrails: list[bool] = []
    sla_checks: list[bool] = []
    agent_ok: list[bool] = []
    for case in ds.cases:
        ck = Checks()
        scored = not case.known_gap
        if case.input["mode"] == "selection":
            ok, guard_ok = _selection(case, ck)
            if scored:
                assignments.append(ok)
                if guard_ok or case.critical:
                    guardrails.append(ok)
        else:
            ok, extra = _agent(case, ck)
            if scored:
                agent_ok.append(ok)
                if case.critical or "override_blocked" in case.expected:
                    guardrails.append(ok)
                sla_checks.extend(extra)
        results.append(ck.result(case, AGENT))
    metrics = {
        "assignment_success_rate": r4(rate(assignments)),
        "guardrail_compliance": r4(rate(guardrails)),
        "agent_routing_accuracy": r4(rate(agent_ok)),
        "provider_sla_compliance": r4(safe_div(sum(sla_checks), len(sla_checks))),
    }
    return AgentEval(agent=AGENT, metrics=metrics, cases=results)
