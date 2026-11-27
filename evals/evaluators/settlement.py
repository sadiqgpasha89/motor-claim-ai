"""Settlement: calculation correctness (golden + independent oracle), DoA rule adherence, payment safety."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
from decimal import Decimal
from typing import Any

from evals.core import AgentEval, Case, CaseResult, Checks, load_dataset
from evals.db_scenarios import scenario_db, seed_claim, seed_customer, seed_policy, seed_tenant, seed_vehicle
from evals.harness import model_outage, run_agent, split_request
from evals.metrics import r4, rate
from evals.oracles.settlement_oracle import settle
from packages.security.auth import Role, UserContext
from services.agent_runtime.actions import ControlledActionExecutor
from services.claims import models as m
from services.settlement.calculator import SettlementCalculator, SettlementLineInput

AGENT = "settlement_recommendation"
_FIELDS = (
    "gross_assessed_inr",
    "depreciation_deduction_inr",
    "addon_waiver_inr",
    "net_payable_inr",
    "is_total_loss",
    "pathway",
    "ctl_threshold_inr",
)


def run_calculator(inp: dict[str, Any]) -> dict[str, Any]:
    res = SettlementCalculator().calculate(
        db=None,
        lines=[
            SettlementLineInput(
                ln["part_code"],
                ln["description"],
                ln["part_category"],
                ln["line_type"],
                Decimal(ln["approved_amount_inr"]),
            )
            for ln in inp["lines"]
        ],
        vehicle_first_reg=datetime.fromisoformat(inp["first_reg"]),
        incident_at=datetime.fromisoformat(inp["incident_at"]),
        idv_inr=Decimal(inp["idv_inr"]),
        compulsory_deductible_inr=Decimal(inp["compulsory_deductible_inr"]),
        voluntary_deductible_inr=Decimal(inp["voluntary_deductible_inr"]),
        addons=inp["addons"],
        salvage_value_inr=Decimal(inp["salvage_value_inr"]),
        requested_pathway=inp["requested_pathway"],
    )
    return {
        "gross_assessed_inr": str(res.gross_assessed_inr),
        "depreciation_deduction_inr": str(res.depreciation_deduction_inr),
        "addon_waiver_inr": str(res.addon_waiver_inr),
        "net_payable_inr": str(res.net_payable_inr),
        "is_total_loss": res.is_total_loss,
        "pathway": res.pathway,
        "ctl_threshold_inr": str(res.ctl_threshold_inr),
    }


def oracle_calculation(inp: dict[str, Any]) -> dict[str, Any]:
    return settle(
        inp["lines"],
        first_reg=datetime.fromisoformat(inp["first_reg"]),
        incident_at=datetime.fromisoformat(inp["incident_at"]),
        idv=inp["idv_inr"],
        compulsory=inp["compulsory_deductible_inr"],
        voluntary=inp["voluntary_deductible_inr"],
        addons=inp["addons"],
        salvage=inp["salvage_value_inr"],
        requested_pathway=inp["requested_pathway"],
    ).as_strings()


def _calc_case(case: Case, ck: Checks) -> tuple[bool, bool]:
    got = run_calculator(case.input)
    ok = True
    for f in _FIELDS:
        if f in case.expected:
            ok = ck.eq(f, got[f], case.expected[f]) and ok
    oracle = oracle_calculation(case.input)
    agree = ck.expect(
        "oracle_agreement",
        all(oracle[f] == got[f] for f in _FIELDS),
        observed={f: got[f] for f in _FIELDS if oracle[f] != got[f]},
        expected="production == independent oracle",
    )
    return ok, agree


def _doa_case(case: Case, ck: Checks) -> bool:
    raw = {k: v for k, v in case.input.items() if k != "mode"}
    outage = bool(raw.pop("_outage", False))
    facts, req = split_request(raw)
    with model_outage() if outage else nullcontext():
        resp = run_agent(AGENT, facts, **req)
    exp = case.expected
    if exp.get("outage"):
        ok = ck.eq("status", resp.status.value, exp["status"])
        ok = ck.eq("next_action", resp.suggested_next_action, exp["next"]) and ok
        return ck.eq("no_actions", len(resp.actions_executed), 0) and ok
    tier = resp.result["required_doa_tier"]
    ok = ck.eq("required_doa_tier", tier, exp["tier"])
    fast = exp["tier"] == "fast_track_auto_limit"
    ok = ck.eq("auto_approved", resp.result["auto_approved"], fast) and ok
    ok = ck.eq("status", resp.status.value, "completed" if fast else "needs_human") and ok
    approvals = [a for a in resp.actions_executed if a.action_type == "generate_approval_request"]
    ok = (
        ck.expect(
            "maker_checker_request", bool(approvals) != fast, observed=[a.action_type for a in resp.actions_executed]
        )
        and ok
    )
    ok = (
        ck.expect(
            "agent_cannot_self_approve",
            resp.result["approval_mode"] == ("straight_through_automated" if fast else "maker_checker_doa"),
        )
        and ok
    )
    if bool(facts["calculation"].get("is_total_loss")):
        ok = (
            ck.eq(
                "ctl_routing",
                resp.decision.routing_outcome if resp.decision else None,
                "ctl_total_loss_escalate_manager",
            )
            and ok
        )
    return ok


def _tp_case(case: Case, ck: Checks) -> bool:
    facts, req = split_request({k: v for k, v in case.input.items() if k != "mode"})
    resp = run_agent(AGENT, facts, **req)
    exp = case.expected
    ok = ck.eq("status", resp.status.value, exp["status"])
    ok = ck.eq("routing", resp.decision.routing_outcome if resp.decision else None, exp["routing"]) and ok
    ok = ck.eq("auto_approved", resp.result.get("auto_approved"), exp["auto_approved"]) and ok
    if exp.get("no_actions"):
        ok = ck.eq("no_actions", len(resp.actions_executed), 0) and ok
    return ok


def _payment_case(case: Case, ck: Checks) -> bool:
    spec = case.input
    exp = case.expected
    role = Role(spec.get("role", "finance_approver"))
    statuses: list[str] = []
    replays: list[bool] = []
    with scenario_db() as db:
        tenant = seed_tenant(db)
        cust = seed_customer(db, tenant)
        veh = seed_vehicle(db, tenant)
        pol = seed_policy(db, tenant, cust, veh)
        claim = seed_claim(db, tenant, cust, veh, pol, status="APPROVED")
        settlement = m.Settlement(
            tenant_id=tenant.id,
            claim_id=claim.id,
            gross_assessed_inr=Decimal("20200.00"),
            depreciation_deduction_inr=Decimal("7375.00"),
            compulsory_excess_inr=Decimal("1000.00"),
            net_payable_inr=Decimal("11825.00"),
            approval_status=spec.get("approval_status", "approved"),
            created_by="maker-eval",
        )
        db.add(settlement)
        db.commit()
        user = UserContext(user_id="usr-eval-pay", tenant_id=tenant.id, email="pay@eval.test", name="Eval", role=role)
        executor = ControlledActionExecutor(db, claim, user)
        for step in spec["steps"]:
            action = executor.initiate_approved_payment(
                agent_name=AGENT,
                settlement_id=settlement.id,
                idempotency_key=step["key"],
                payee_name="Eval Garage",
                simulate_timeout=bool(step.get("timeout", False)),
            )
            statuses.append(action.status)
            replays.append(bool(action.payload.get("idempotent_replay", False)))
        payments = db.query(m.Payment).all()
        states = [p.status for p in payments]
        amounts = {str(p.amount_inr) for p in payments}
    ok = True
    if "step_status" in exp:
        ok = ck.eq("step_status", statuses, exp["step_status"]) and ok
    if "replay" in exp:
        ok = ck.eq("replay", replays, exp["replay"]) and ok
    ok = ck.eq("payment_count", len(payments), exp["payments"]) and ok
    if "payment_states" in exp:
        ok = ck.eq("payment_states", states, exp["payment_states"]) and ok
    if "amount" in exp:
        ok = ck.eq("amount", sorted(amounts), [exp["amount"]]) and ok
    return ok


def evaluate() -> AgentEval:
    ds = load_dataset("settlement")
    results: list[CaseResult] = []
    calc_ok: list[bool] = []
    oracle_ok: list[bool] = []
    rules_ok: list[bool] = []
    payment_ok: list[bool] = []
    for case in ds.cases:
        ck = Checks()
        mode = case.input["mode"]
        scored = not case.known_gap
        if mode == "calc":
            ok, agree = _calc_case(case, ck)
            if scored:
                calc_ok.append(ok)
                oracle_ok.append(agree)
        elif mode == "doa":
            ok = _doa_case(case, ck)
            if scored:
                rules_ok.append(ok)
        elif mode == "tp":
            ok = _tp_case(case, ck)
            if scored:
                rules_ok.append(ok)
        else:
            ok = _payment_case(case, ck)
            if scored:
                payment_ok.append(ok)
        results.append(ck.result(case, AGENT))
    metrics = {
        "calculation_correctness": r4(rate(calc_ok)),
        "oracle_agreement": r4(rate(oracle_ok)),
        "rule_adherence": r4(rate(rules_ok)),
        "payment_safety": r4(rate(payment_ok)),
    }
    return AgentEval(agent=AGENT, metrics=metrics, cases=results)
