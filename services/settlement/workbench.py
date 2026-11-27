"""Settlement decision workbench.

Expands the single deterministic settlement simulation into twelve comparable scenarios. Every scenario is
computed with the production ``SettlementCalculator`` (Decimal only) and is returned in the same structure:

1. what was claimed, 2. what was assessed, 3. what was approved, 4. what was deducted,
5. which policy clauses were applied, 6. who approves it (Delegation of Authority), 7. what the customer
receives, 8. why that differs from the requested amount (an itemised reconciliation that always balances).

The static site mirrors this module in ``site/settlement-engine.js``; ``tests/unit/test_settlement_workbench.py``
runs both engines and asserts that they return identical output. Labels, parameters and the clause map live in
``rules/india/settlement_scenario_rules.json`` so that both engines read the same wording.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from services.rules_engine.loader import get_active_rule
from services.settlement.authority import resolve_required_authority
from services.settlement.calculator import SettlementCalculationResult, SettlementCalculator, SettlementLineInput

SCENARIO_RULE_ID = "IN-SETTLEMENT-SCENARIOS-2026"
DEPRECIATION_RULE_ID = "IN-MOTOR-DEPRECIATION-2024"
DOA_RULE_ID = "IN-DOA-MATRIX-2026"

_KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge" / "synthetic_policy_samples"
POLICY_FILE = _KNOWLEDGE_DIR / "policies.json"
DEMO_CLAIM_FILE = _KNOWLEDGE_DIR / "demo_claim_settlement.json"

ZERO = Decimal("0.00")
_TWO_DP = Decimal("0.01")
_FOUR_DP = Decimal("0.0001")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_UP)


def _s(value: Decimal) -> str:
    """Canonical amount string: two decimals, never negative zero."""
    q = _q(value)
    if q == 0:
        q = ZERO
    return f"{q:.2f}"


def _ratio(numerator: Decimal, denominator: Decimal) -> str:
    if denominator == 0:
        return "0.0000"
    return f"{(numerator / denominator).quantize(_FOUR_DP, rounding=ROUND_HALF_UP):.4f}"


def _d(value: Any) -> Decimal:
    return _q(Decimal(str(value)))


@dataclass(frozen=True)
class WorkbenchInputs:
    vehicle_age_months: int
    idv_inr: Decimal
    market_value_inr: Decimal
    compulsory_deductible_inr: Decimal
    voluntary_deductible_inr: Decimal
    salvage_value_inr: Decimal
    zero_depreciation: bool
    consumables: bool

    def echo(self) -> dict[str, Any]:
        return {
            "vehicle_age_months": self.vehicle_age_months,
            "idv_inr": _s(self.idv_inr),
            "market_value_inr": _s(self.market_value_inr),
            "compulsory_deductible_inr": _s(self.compulsory_deductible_inr),
            "voluntary_deductible_inr": _s(self.voluntary_deductible_inr),
            "salvage_value_inr": _s(self.salvage_value_inr),
            "zero_depreciation": self.zero_depreciation,
            "consumables": self.consumables,
        }


@dataclass(frozen=True)
class _Line:
    id: str
    part_code: str
    description: str
    part_category: str
    line_type: str
    amount: Decimal

    def as_input(self) -> SettlementLineInput:
        return SettlementLineInput(self.part_code, self.description, self.part_category, self.line_type, self.amount)


@dataclass(frozen=True)
class _QuoteLine:
    line: _Line
    claimed: Decimal
    assessed: Decimal
    assessment_code: str | None


@dataclass
class _View:
    """One settlement computed with and without add-ons so that the add-on benefit is explicit."""

    gross: Decimal
    tariff_depreciation: Decimal
    applied_depreciation: Decimal
    zd_benefit: Decimal
    cons_benefit: Decimal
    compulsory: Decimal
    voluntary: Decimal
    net: Decimal
    floor_cap: Decimal
    result: SettlementCalculationResult


def load_demo_claim() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(DEMO_CLAIM_FILE.read_text(encoding="utf-8"))
    return loaded


def load_policy_clauses(document_id: str) -> dict[str, dict[str, Any]]:
    for doc in json.loads(POLICY_FILE.read_text(encoding="utf-8")):
        if doc["document_id"] == document_id:
            return {c["clause_id"]: c for c in doc["clauses"]}
    raise KeyError(f"Policy document '{document_id}' not found")


def default_inputs(demo: dict[str, Any] | None = None) -> WorkbenchInputs:
    d = (demo or load_demo_claim())["defaults"]
    return WorkbenchInputs(
        vehicle_age_months=int(d["vehicle_age_months"]),
        idv_inr=_d(d["idv_inr"]),
        market_value_inr=_d(d["market_value_inr"]),
        compulsory_deductible_inr=_d(d["compulsory_deductible_inr"]),
        voluntary_deductible_inr=_d(d["voluntary_deductible_inr"]),
        salvage_value_inr=_d(d["salvage_value_inr"]),
        zero_depreciation=bool(d["zero_depreciation"]),
        consumables=bool(d["consumables"]),
    )


def inputs_from_mapping(overrides: dict[str, Any], demo: dict[str, Any] | None = None) -> WorkbenchInputs:
    base = default_inputs(demo)
    return WorkbenchInputs(
        vehicle_age_months=int(overrides.get("vehicle_age_months", base.vehicle_age_months)),
        idv_inr=_d(overrides.get("idv_inr", base.idv_inr)),
        market_value_inr=_d(overrides.get("market_value_inr", base.market_value_inr)),
        compulsory_deductible_inr=_d(overrides.get("compulsory_deductible_inr", base.compulsory_deductible_inr)),
        voluntary_deductible_inr=_d(overrides.get("voluntary_deductible_inr", base.voluntary_deductible_inr)),
        salvage_value_inr=_d(overrides.get("salvage_value_inr", base.salvage_value_inr)),
        zero_depreciation=bool(overrides.get("zero_depreciation", base.zero_depreciation)),
        consumables=bool(overrides.get("consumables", base.consumables)),
    )


class _Context:
    """Holds rules, inputs and the shared helpers used by every scenario builder."""

    def __init__(self, inp: WorkbenchInputs, demo: dict[str, Any], db: Session | None) -> None:
        self.inp = inp
        self.demo = demo
        self.db = db
        self.rule = get_active_rule(db, SCENARIO_RULE_ID)
        self.dep_rule = get_active_rule(db, DEPRECIATION_RULE_ID)
        self.doa = get_active_rule(db, DOA_RULE_ID)
        self.params: dict[str, Any] = self.rule["parameters"]
        self.labels: dict[str, str] = self.rule["labels"]
        self.clauses = load_policy_clauses(self.rule["policy_document_id"])
        self.calculator = SettlementCalculator()
        self.incident_at = datetime.fromisoformat(demo["incident_at"])
        self.first_reg = self.incident_at - timedelta(days=inp.vehicle_age_months * 30)
        self.addons = {"zero_depreciation": inp.zero_depreciation, "consumables": inp.consumables}
        self.quote = [
            _QuoteLine(
                line=_Line(
                    q["id"], q["part_code"], q["description"], q["part_category"], q["line_type"], _d(q["assessed_inr"])
                ),
                claimed=_d(q["claimed_inr"]),
                assessed=_d(q["assessed_inr"]),
                assessment_code=q.get("assessment_code"),
            )
            for q in demo["quote_lines"]
        ]

    def label(self, key: str) -> str:
        return self.labels[key]

    def calc(
        self,
        lines: list[_Line],
        *,
        addons: dict[str, bool] | None = None,
        pathway: str = "cashless",
        salvage: Decimal = ZERO,
        compulsory: Decimal | None = None,
        voluntary: Decimal | None = None,
    ) -> SettlementCalculationResult:
        return self.calculator.calculate(
            db=self.db,
            lines=[ln.as_input() for ln in lines if ln.amount > ZERO],
            vehicle_first_reg=self.first_reg,
            incident_at=self.incident_at,
            idv_inr=self.inp.idv_inr,
            compulsory_deductible_inr=self.inp.compulsory_deductible_inr if compulsory is None else compulsory,
            voluntary_deductible_inr=self.inp.voluntary_deductible_inr if voluntary is None else voluntary,
            addons=self.addons if addons is None else addons,
            salvage_value_inr=salvage,
            requested_pathway=pathway,
        )

    def view(self, lines: list[_Line], *, addons: dict[str, bool] | None = None) -> _View:
        res = self.calc(lines, addons=addons)
        res_tariff = self.calc(lines, addons={"zero_depreciation": False, "consumables": False})
        benefit = res_tariff.depreciation_deduction_inr - res.depreciation_deduction_inr
        running = res.gross_assessed_inr - res.depreciation_deduction_inr - res.compulsory_excess_inr - res.voluntary_excess_inr
        return _View(
            gross=res.gross_assessed_inr,
            tariff_depreciation=res_tariff.depreciation_deduction_inr,
            applied_depreciation=res.depreciation_deduction_inr,
            zd_benefit=res.addon_waiver_inr,
            cons_benefit=benefit - res.addon_waiver_inr,
            compulsory=res.compulsory_excess_inr,
            voluntary=res.voluntary_excess_inr,
            net=res.net_payable_inr,
            floor_cap=res.net_payable_inr - running,
            result=res,
        )

    def assessed_lines(self) -> list[_Line]:
        return [qline.line for qline in self.quote if qline.assessed > ZERO]

    def claimed_total(self) -> Decimal:
        return sum((q.claimed for q in self.quote), ZERO)

    def assessment_adjustments(self) -> list[tuple[str, Decimal]]:
        return [
            (q.assessment_code, q.assessed - q.claimed)
            for q in self.quote
            if q.assessment_code and q.assessed != q.claimed
        ]

    @staticmethod
    def lines_from(raw: list[dict[str, Any]]) -> list[_Line]:
        return [
            _Line(x["id"], x["part_code"], x["description"], x["part_category"], x["line_type"], _d(x["amount_inr"]))
            for x in raw
        ]

    def clause_records(self, meta: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for ref in meta["clauses"]:
            when = ref.get("when")
            if when == "zd_active" and not self.inp.zero_depreciation:
                continue
            if when == "cons_active" and not self.inp.consumables:
                continue
            clause = self.clauses[ref["id"]]
            out.append(
                {
                    "clause_id": clause["clause_id"],
                    "document_id": self.rule["policy_document_id"],
                    "page": clause["page"],
                    "title": clause["title"],
                    "applied_for": ref["applied_for"],
                }
            )
        return out

    def approval(
        self, *, amount: Decimal, claim_type: str, conditions: list[str], assessor_note: str | None
    ) -> dict[str, Any]:
        auth = resolve_required_authority(
            self.doa, amount_inr=amount, claim_type=claim_type, active_conditions=conditions
        )
        checker = auth["checker_role"]
        release = auth["payment_release_role"]
        return {
            "recommended_by": self.label("role_settlement_agent"),
            "maker": self.label("role_maker"),
            "checker_role": checker,
            "checker_label": self.label(f"role_{checker}"),
            "authority_limit_inr": auth["max_settlement_inr"],
            "authority_amount_inr": _s(amount),
            "payment_release_role": release,
            "payment_release_label": self.label(f"role_{release}"),
            "skipped_tiers": [
                {
                    "role": t["role"],
                    "label": self.label(f"role_{t['role']}"),
                    "reason_code": t["reason_code"],
                    "reason": self.label(f"skip_{t['reason_code']}"),
                }
                for t in auth["skipped_tiers"]
            ],
            "assessor_note": self.label(assessor_note) if assessor_note else None,
            "maker_checker_note": self.label("maker_checker_note"),
            "demo_note": self.label("approval_demo_note"),
            "rule_version": auth["rule_version"],
        }


def _item(ctx: _Context, code: str, amount: Decimal, clause_id: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"code": code, "label": ctx.label(code), "amount": _s(amount)}
    if clause_id is not None:
        out["clause_id"] = clause_id
    return out


def _assemble(
    ctx: _Context,
    meta: dict[str, Any],
    *,
    claimed: Decimal,
    claimed_basis: str,
    adjustments: list[tuple[str, Decimal]],
    withheld: list[tuple[str, Decimal]],
    deductions: list[tuple[str, Decimal, str]],
    benefits: list[tuple[str, Decimal, str]],
    floor_cap: Decimal,
    net: Decimal,
    customer_pays: Decimal,
    payee: str,
    outcome: str,
    auth_amount: Decimal,
    auth_claim_type: str,
    auth_conditions: list[str],
    assessor_note: str | None,
    comparison: dict[str, Any],
    insurer_net_cost: Decimal | None = None,
) -> dict[str, Any]:
    assessed = claimed + sum((a for _, a in adjustments), ZERO)
    approved = assessed + sum((a for _, a in withheld), ZERO)
    deductions = [d for d in deductions if d[1] != ZERO]
    benefits = [b for b in benefits if b[1] != ZERO]

    reconciliation: list[dict[str, Any]] = []
    for code, amt in adjustments + withheld:
        reconciliation.append(_item(ctx, code, amt))
    for code, amt, clause_id in deductions:
        reconciliation.append(_item(ctx, code, -amt, clause_id))
    for code, amt, clause_id in benefits:
        reconciliation.append(_item(ctx, code, amt, clause_id))
    if floor_cap != ZERO:
        reconciliation.append(_item(ctx, "floor_cap", floor_cap, "SEC-1-6"))
    effect = sum((Decimal(r["amount"]) for r in reconciliation), ZERO)

    return {
        "scenario_code": meta["code"],
        "number": meta["number"],
        "label": meta["label"],
        "group": meta["group"],
        "pathway": meta["pathway"],
        "status": meta["status"],
        "summary": meta["summary"],
        "assumptions": list(meta["assumptions"]),
        "claimed": {"amount": _s(claimed), "basis": ctx.label(claimed_basis)},
        "assessed": {"amount": _s(assessed), "adjustments": [_item(ctx, c, a) for c, a in adjustments]},
        "approved": {"amount": _s(approved), "withheld": [_item(ctx, c, a) for c, a in withheld]},
        "deducted": {
            "total": _s(sum((d[1] for d in deductions), ZERO)),
            "items": [_item(ctx, c, a, cl) for c, a, cl in deductions],
        },
        "addon_benefits": {
            "total": _s(sum((b[1] for b in benefits), ZERO)),
            "items": [_item(ctx, c, a, cl) for c, a, cl in benefits],
        },
        "net_payable": _s(net),
        "policy_clauses": ctx.clause_records(meta),
        "approval": ctx.approval(
            amount=auth_amount, claim_type=auth_claim_type, conditions=auth_conditions, assessor_note=assessor_note
        ),
        "customer_receives": {
            "amount": _s(net),
            "payee": ctx.label(payee),
            "outcome": ctx.label(outcome),
            "customer_pays": _s(customer_pays),
        },
        "why_different": {
            "requested": _s(claimed),
            "receives": _s(net),
            "gap": _s(claimed - net),
            "items": reconciliation,
            "balanced": _q(claimed + effect) == _q(net),
        },
        "insurer_net_cost": _s(net if insurer_net_cost is None else insurer_net_cost),
        "comparison": comparison,
    }


def _repair_deductions(view: _View) -> tuple[list[tuple[str, Decimal, str]], list[tuple[str, Decimal, str]]]:
    deductions = [
        ("tariff_depreciation", view.tariff_depreciation, "SEC-1-2"),
        ("compulsory_excess", view.compulsory, "SEC-1-5"),
        ("voluntary_excess", view.voluntary, "SEC-1-5"),
    ]
    benefits = [
        ("addon_zero_dep", view.zd_benefit, "ADDON-ZD-01"),
        ("addon_consumables", view.cons_benefit, "ADDON-CONS-01"),
    ]
    return deductions, benefits


def _option(ctx: _Context, code: str, view: _View) -> dict[str, Any]:
    return {
        "code": code,
        "label": ctx.label(f"option_{code}"),
        "gross_inr": _s(view.gross),
        "applied_depreciation_inr": _s(view.applied_depreciation),
        "net_payable_inr": _s(view.net),
    }


# --------------------------------------------------------------------------- scenario builders


def _cashless(ctx: _Context, meta: dict[str, Any], base: _View) -> dict[str, Any]:
    deductions, benefits = _repair_deductions(base)
    return _assemble(
        ctx, meta,
        claimed=ctx.claimed_total(), claimed_basis="basis_garage_quote",
        adjustments=ctx.assessment_adjustments(), withheld=[],
        deductions=deductions, benefits=benefits, floor_cap=base.floor_cap, net=base.net,
        customer_pays=base.gross - base.net,
        payee="payee_network_garage", outcome="outcome_cashless",
        auth_amount=base.net, auth_claim_type=meta["claim_type"], auth_conditions=[],
        assessor_note="assessor_decision_none", comparison={},
    )


def _reimbursement(ctx: _Context, meta: dict[str, Any], base: _View) -> dict[str, Any]:
    deductions, benefits = _repair_deductions(base)
    claimed = ctx.claimed_total()
    return _assemble(
        ctx, meta,
        claimed=claimed, claimed_basis="basis_garage_quote",
        adjustments=ctx.assessment_adjustments(), withheld=[],
        deductions=deductions, benefits=benefits, floor_cap=base.floor_cap, net=base.net,
        customer_pays=claimed - base.net,
        payee="payee_customer", outcome="outcome_reimbursement",
        auth_amount=base.net, auth_claim_type=meta["claim_type"], auth_conditions=[],
        assessor_note="assessor_decision_none",
        comparison={
            "customer_funds_upfront_inr": _s(claimed),
            "reimbursed_inr": _s(base.net),
            "customer_pays_if_cashless_inr": _s(base.gross - base.net),
            "customer_pays_if_reimbursed_inr": _s(claimed - base.net),
            "documents_required": list(ctx.params["reimbursement_documents"]),
        },
    )


def _repair_vs_replacement(ctx: _Context, meta: dict[str, Any], base: _View) -> dict[str, Any]:
    alt = ctx.demo["repair_alternative"]
    replaced = set(alt["replaces_line_ids"])
    repair_lines = [q.line for q in ctx.quote if q.assessed > ZERO and q.line.id not in replaced]
    repair_lines += ctx.lines_from(alt["lines"])
    repair = ctx.view(repair_lines)
    substitution = repair.gross - base.gross
    deductions, benefits = _repair_deductions(repair)
    return _assemble(
        ctx, meta,
        claimed=ctx.claimed_total(), claimed_basis="basis_garage_quote",
        adjustments=ctx.assessment_adjustments() + [("repair_substitution", substitution)], withheld=[],
        deductions=deductions, benefits=benefits, floor_cap=repair.floor_cap, net=repair.net,
        customer_pays=repair.gross - repair.net,
        payee="payee_network_garage", outcome="outcome_repair",
        auth_amount=repair.net, auth_claim_type=meta["claim_type"], auth_conditions=[],
        assessor_note="assessor_decision_none",
        comparison={
            "options": [_option(ctx, "replace", base), _option(ctx, "repair", repair)],
            "recommended_option": "repair" if repair.net < base.net else "replace",
            "insurer_saving_inr": _s(base.net - repair.net),
        },
    )


def _partial_approval(ctx: _Context, meta: dict[str, Any], base: _View) -> dict[str, Any]:
    cfg = ctx.demo["partial_approval"]
    held_ids = set(cfg["withheld_line_ids"])
    held = [q for q in ctx.quote if q.line.id in held_ids and q.assessed > ZERO]
    kept = [q.line for q in ctx.quote if q.assessed > ZERO and q.line.id not in held_ids]
    partial = ctx.view(kept)
    deductions, benefits = _repair_deductions(partial)
    held_total = sum((q.assessed for q in held), ZERO)
    return _assemble(
        ctx, meta,
        claimed=ctx.claimed_total(), claimed_basis="basis_garage_quote",
        adjustments=ctx.assessment_adjustments(),
        withheld=[(cfg["reason_code"], -held_total)] if held_total != ZERO else [],
        deductions=deductions, benefits=benefits, floor_cap=partial.floor_cap, net=partial.net,
        customer_pays=base.gross - partial.net,
        payee="payee_network_garage", outcome="outcome_partial",
        auth_amount=partial.net, auth_claim_type=meta["claim_type"], auth_conditions=[],
        assessor_note="assessor_decision_holdback",
        comparison={
            "withheld_lines": [
                {
                    "line_id": q.line.id,
                    "part_code": q.line.part_code,
                    "description": q.line.description,
                    "amount_inr": _s(q.assessed),
                }
                for q in held
            ],
            "net_if_released_inr": _s(base.net),
            "additional_payable_on_release_inr": _s(base.net - partial.net),
        },
    )


def _supplementary(ctx: _Context, meta: dict[str, Any], base: _View) -> dict[str, Any]:
    supp = ctx.lines_from(ctx.demo["supplementary_lines"])
    supp_total = sum((ln.amount for ln in supp), ZERO)
    revised = ctx.view(ctx.assessed_lines() + supp)
    threshold = Decimal(str(ctx.params["supplementary_reinspection_variance_threshold"]))
    variance = supp_total / base.gross if base.gross != ZERO else ZERO
    reinspect = variance >= threshold
    deductions, benefits = _repair_deductions(revised)
    return _assemble(
        ctx, meta,
        claimed=ctx.claimed_total() + supp_total, claimed_basis="basis_garage_quote_plus_supplementary",
        adjustments=ctx.assessment_adjustments(), withheld=[],
        deductions=deductions, benefits=benefits, floor_cap=revised.floor_cap, net=revised.net,
        customer_pays=revised.gross - revised.net,
        payee="payee_network_garage", outcome="outcome_supplementary",
        auth_amount=revised.net, auth_claim_type=meta["claim_type"], auth_conditions=[],
        assessor_note="assessor_decision_reinspection" if reinspect else "assessor_decision_no_reinspection",
        comparison={
            "initial_net_inr": _s(base.net),
            "revised_net_inr": _s(revised.net),
            "incremental_payable_inr": _s(revised.net - base.net),
            "supplementary_assessed_inr": _s(supp_total),
            "cumulative_gross_inr": _s(revised.gross),
            "variance_ratio": _ratio(supp_total, base.gross),
            "variance_threshold": f"{threshold:.4f}",
            "reinspection_required": reinspect,
            "lines": [
                {"part_code": ln.part_code, "description": ln.description, "amount_inr": _s(ln.amount)} for ln in supp
            ],
        },
    )


def _total_loss(ctx: _Context, meta: dict[str, Any]) -> dict[str, Any]:
    inp = ctx.inp
    res = ctx.calc([], pathway="total_loss")
    claimed = inp.market_value_inr
    running = inp.idv_inr - res.compulsory_excess_inr - res.voluntary_excess_inr
    return _assemble(
        ctx, meta,
        claimed=claimed, claimed_basis="basis_market_value",
        adjustments=[("idv_basis", inp.idv_inr - claimed)], withheld=[],
        deductions=[
            ("compulsory_excess", res.compulsory_excess_inr, "SEC-1-5"),
            ("voluntary_excess", res.voluntary_excess_inr, "SEC-1-5"),
        ],
        benefits=[], floor_cap=res.net_payable_inr - running, net=res.net_payable_inr,
        customer_pays=res.compulsory_excess_inr + res.voluntary_excess_inr,
        payee="payee_customer", outcome="outcome_total_loss",
        auth_amount=res.net_payable_inr, auth_claim_type=meta["claim_type"], auth_conditions=["total_loss"],
        assessor_note=None,
        comparison={
            "idv_inr": _s(inp.idv_inr),
            "market_value_inr": _s(claimed),
            "shortfall_vs_market_inr": _s(max(claimed - inp.idv_inr, ZERO)),
            "surrender_net_inr": _s(res.net_payable_inr),
        },
    )


def _constructive_total_loss(ctx: _Context, meta: dict[str, Any]) -> dict[str, Any]:
    inp = ctx.inp
    ratio = Decimal(str(ctx.params["ctl_stress_repair_ratio_of_idv"]))
    spec = ctx.demo["stress_ctl_line"]
    stress_amount = _q(inp.idv_inr * ratio)
    stress = _Line("CTL1", spec["part_code"], spec["description"], spec["part_category"], spec["line_type"], stress_amount)
    test = ctx.calc([stress])
    triggered = test.is_total_loss
    surrender_net = max(_q(inp.idv_inr - test.compulsory_excess_inr - test.voluntary_excess_inr), ZERO)
    comparison: dict[str, Any] = {
        "stress_estimate_inr": _s(stress_amount),
        "net_repair_inr": _s(test.gross_assessed_inr - test.depreciation_deduction_inr),
        "ctl_threshold_inr": _s(test.ctl_threshold_inr),
        "ctl_triggered": triggered,
        "surrender_net_inr": _s(surrender_net),
    }
    if not triggered:
        view = ctx.view([stress])
        deductions, benefits = _repair_deductions(view)
        return _assemble(
            ctx, meta,
            claimed=stress_amount, claimed_basis="basis_repair_estimate",
            adjustments=[], withheld=[], deductions=deductions, benefits=benefits,
            floor_cap=view.floor_cap, net=view.net, customer_pays=view.gross - view.net,
            payee="payee_network_garage", outcome="outcome_ctl_not_triggered",
            auth_amount=view.net, auth_claim_type="cashless", auth_conditions=[],
            assessor_note=None, comparison=comparison,
        )
    res = ctx.calc([stress], pathway="total_loss", salvage=inp.salvage_value_inr)
    running = inp.idv_inr - res.compulsory_excess_inr - res.voluntary_excess_inr - res.salvage_deduction_inr
    comparison["retention_net_inr"] = _s(res.net_payable_inr)
    return _assemble(
        ctx, meta,
        claimed=stress_amount, claimed_basis="basis_repair_estimate",
        adjustments=[("idv_basis", inp.idv_inr - stress_amount)], withheld=[],
        deductions=[
            ("compulsory_excess", res.compulsory_excess_inr, "SEC-1-5"),
            ("voluntary_excess", res.voluntary_excess_inr, "SEC-1-5"),
            ("salvage_retained", res.salvage_deduction_inr, "SEC-1-7"),
        ],
        benefits=[], floor_cap=res.net_payable_inr - running, net=res.net_payable_inr,
        customer_pays=res.compulsory_excess_inr + res.voluntary_excess_inr,
        payee="payee_customer", outcome="outcome_ctl_retention",
        auth_amount=res.net_payable_inr, auth_claim_type=meta["claim_type"], auth_conditions=["total_loss"],
        assessor_note=None, comparison=comparison,
    )


def _salvage_recovery(ctx: _Context, meta: dict[str, Any]) -> dict[str, Any]:
    inp = ctx.inp
    surrender = ctx.calc([], pathway="total_loss")
    retention = ctx.calc([], pathway="total_loss", salvage=inp.salvage_value_inr)
    disposal_ratio = Decimal(str(ctx.params["salvage_disposal_cost_ratio"]))
    proceeds = inp.salvage_value_inr
    disposal = _q(proceeds * disposal_ratio)
    net_recovery = proceeds - disposal
    surrender_cost = surrender.net_payable_inr - net_recovery
    claimed = inp.market_value_inr
    running = inp.idv_inr - surrender.compulsory_excess_inr - surrender.voluntary_excess_inr
    sale_auth = ctx.approval(
        amount=net_recovery, claim_type="total_loss", conditions=[], assessor_note=None
    )
    return _assemble(
        ctx, meta,
        claimed=claimed, claimed_basis="basis_market_value",
        adjustments=[("idv_basis", inp.idv_inr - claimed)], withheld=[],
        deductions=[
            ("compulsory_excess", surrender.compulsory_excess_inr, "SEC-1-5"),
            ("voluntary_excess", surrender.voluntary_excess_inr, "SEC-1-5"),
        ],
        benefits=[], floor_cap=surrender.net_payable_inr - running, net=surrender.net_payable_inr,
        customer_pays=surrender.compulsory_excess_inr + surrender.voluntary_excess_inr,
        payee="payee_customer", outcome="outcome_total_loss",
        auth_amount=surrender.net_payable_inr, auth_claim_type=meta["claim_type"], auth_conditions=["total_loss"],
        assessor_note=None,
        insurer_net_cost=surrender_cost,
        comparison={
            "surrender": {
                "customer_payout_inr": _s(surrender.net_payable_inr),
                "salvage_proceeds_inr": _s(proceeds),
                "disposal_cost_inr": _s(disposal),
                "net_recovery_inr": _s(net_recovery),
                "insurer_net_cost_inr": _s(surrender_cost),
            },
            "retention": {
                "customer_payout_inr": _s(retention.net_payable_inr),
                "insurer_net_cost_inr": _s(retention.net_payable_inr),
            },
            "retention_saving_for_insurer_inr": _s(surrender_cost - retention.net_payable_inr),
            "salvage_sale_checker_role": sale_auth["checker_role"],
            "salvage_sale_checker_label": sale_auth["checker_label"],
        },
    )


def _addon_scenario(ctx: _Context, meta: dict[str, Any], *, key: str) -> dict[str, Any]:
    """Shared builder for the two add-on scenarios: recompute with and without one add-on."""
    lines = ctx.assessed_lines()
    other = "consumables" if key == "zero_depreciation" else "zero_depreciation"
    held = {other: bool(ctx.addons[other])}
    with_addon = ctx.view(lines, addons={**held, key: True})
    without_addon = ctx.view(lines, addons={**held, key: False})
    deductions, benefits = _repair_deductions(with_addon)
    return _assemble(
        ctx, meta,
        claimed=ctx.claimed_total(), claimed_basis="basis_garage_quote",
        adjustments=ctx.assessment_adjustments(), withheld=[],
        deductions=deductions, benefits=benefits, floor_cap=with_addon.floor_cap, net=with_addon.net,
        customer_pays=with_addon.gross - with_addon.net,
        payee="payee_network_garage", outcome="outcome_addon",
        auth_amount=with_addon.net, auth_claim_type=meta["claim_type"], auth_conditions=[],
        assessor_note="assessor_decision_none",
        comparison={
            "active_on_policy": bool(ctx.addons[key]),
            "with_addon": {
                "applied_depreciation_inr": _s(with_addon.applied_depreciation),
                "net_payable_inr": _s(with_addon.net),
            },
            "without_addon": {
                "applied_depreciation_inr": _s(without_addon.applied_depreciation),
                "net_payable_inr": _s(without_addon.net),
            },
            "benefit_inr": _s(with_addon.net - without_addon.net),
        },
    )


def _different_deductibles(ctx: _Context, meta: dict[str, Any], base: _View) -> dict[str, Any]:
    lines = ctx.assessed_lines()
    classes = ctx.params["deductible_matrix_vehicle_classes"]
    voluntary = [_d(v) for v in ctx.params["voluntary_deductible_options_inr"]]
    compulsory_map = ctx.dep_rule["compulsory_deductible_by_vehicle_class_inr"]
    matrix = []
    for vehicle_class in classes:
        comp = _d(compulsory_map[vehicle_class])
        cells = [
            {
                "voluntary_inr": _s(vol),
                "net_payable_inr": _s(ctx.calc(lines, compulsory=comp, voluntary=vol).net_payable_inr),
            }
            for vol in voluntary
        ]
        matrix.append({"vehicle_class": vehicle_class, "compulsory_inr": _s(comp), "cells": cells})
    deductions, benefits = _repair_deductions(base)
    return _assemble(
        ctx, meta,
        claimed=ctx.claimed_total(), claimed_basis="basis_garage_quote",
        adjustments=ctx.assessment_adjustments(), withheld=[],
        deductions=deductions, benefits=benefits, floor_cap=base.floor_cap, net=base.net,
        customer_pays=base.gross - base.net,
        payee="payee_network_garage", outcome="outcome_deductible",
        auth_amount=base.net, auth_claim_type=meta["claim_type"], auth_conditions=[],
        assessor_note="assessor_decision_none",
        comparison={
            "current_compulsory_inr": _s(base.compulsory),
            "current_voluntary_inr": _s(base.voluntary),
            "voluntary_options_inr": [_s(v) for v in voluntary],
            "matrix": matrix,
        },
    )


def _underinsurance(ctx: _Context, meta: dict[str, Any], base: _View) -> dict[str, Any]:
    inp = ctx.inp
    loss_after_dep = base.gross - base.applied_depreciation
    if inp.market_value_inr > ZERO and inp.idv_inr < inp.market_value_inr:
        pro_rated = _q(loss_after_dep * inp.idv_inr / inp.market_value_inr)
    else:
        pro_rated = loss_after_dep
    reduction = loss_after_dep - pro_rated
    running = pro_rated - base.compulsory - base.voluntary
    net = min(max(_q(running), ZERO), inp.idv_inr)
    deductions, benefits = _repair_deductions(base)
    deductions.insert(1, ("pro_rata", reduction, "SEC-1-6"))
    return _assemble(
        ctx, meta,
        claimed=ctx.claimed_total(), claimed_basis="basis_garage_quote",
        adjustments=ctx.assessment_adjustments(), withheld=[],
        deductions=deductions, benefits=benefits, floor_cap=net - running, net=net,
        customer_pays=base.gross - net,
        payee="payee_network_garage", outcome="outcome_pro_rata",
        auth_amount=net, auth_claim_type=meta["claim_type"], auth_conditions=[],
        assessor_note="assessor_decision_none",
        comparison={
            "idv_inr": _s(inp.idv_inr),
            "market_value_inr": _s(inp.market_value_inr),
            "idv_ratio": _ratio(inp.idv_inr, inp.market_value_inr),
            "underinsured": bool(inp.market_value_inr > ZERO and inp.idv_inr < inp.market_value_inr),
            "shortfall_on_total_loss_inr": _s(max(inp.market_value_inr - inp.idv_inr, ZERO)),
            "idv_cap_inr": _s(inp.idv_inr),
            "net_without_pro_rata_inr": _s(base.net),
            "net_with_pro_rata_inr": _s(net),
            "pro_rata_reduction_inr": _s(reduction),
        },
    )


# --------------------------------------------------------------------------- public API


def _ledger(ctx: _Context, base: _View) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    running = ZERO

    def add(key: str, sign: str, amount: Decimal, clause_id: str | None = None) -> None:
        nonlocal running
        running = running + amount if sign == "+" else running - amount
        step: dict[str, Any] = {
            "key": key,
            "label": ctx.label(key),
            "sign": sign,
            "amount": _s(amount),
            "running_total": _s(running),
        }
        if clause_id is not None:
            step["clause_id"] = clause_id
        steps.append(step)

    add("approved_amount", "+", base.gross, "SEC-1-1")
    add("tariff_depreciation", "-", base.tariff_depreciation, "SEC-1-2")
    add("addon_zero_dep", "+", base.zd_benefit, "ADDON-ZD-01")
    add("addon_consumables", "+", base.cons_benefit, "ADDON-CONS-01")
    add("compulsory_excess", "-", base.compulsory, "SEC-1-5")
    add("voluntary_excess", "-", base.voluntary, "SEC-1-5")
    add("other_deductions", "-", ZERO)
    if base.floor_cap != ZERO:
        add("floor_cap", "+" if base.floor_cap > ZERO else "-", abs(base.floor_cap), "SEC-1-6")
    return {"steps": steps, "net_payable": _s(base.net)}


def _line_trace(ctx: _Context, base: _View) -> list[dict[str, Any]]:
    trace_rows = iter(base.result.calculation_trace)
    rows: list[dict[str, Any]] = []
    for q in ctx.quote:
        if q.assessed > ZERO:
            t = next(trace_rows)
            rows.append(
                {
                    "line_id": q.line.id,
                    "part_code": q.line.part_code,
                    "description": q.line.description,
                    "line_type": q.line.line_type,
                    "claimed_inr": _s(q.claimed),
                    "assessed_inr": _s(q.assessed),
                    "approved_inr": _s(q.assessed),
                    "raw_depreciation_inr": t["raw_depreciation_inr"],
                    "applied_depreciation_inr": t["applied_depreciation_inr"],
                    "net_line_inr": t["net_line_inr"],
                    "note": t["note"],
                    "assessment_code": q.assessment_code,
                }
            )
        else:
            rows.append(
                {
                    "line_id": q.line.id,
                    "part_code": q.line.part_code,
                    "description": q.line.description,
                    "line_type": q.line.line_type,
                    "claimed_inr": _s(q.claimed),
                    "assessed_inr": _s(q.assessed),
                    "approved_inr": _s(ZERO),
                    "raw_depreciation_inr": _s(ZERO),
                    "applied_depreciation_inr": _s(ZERO),
                    "net_line_inr": _s(ZERO),
                    "note": ctx.label(q.assessment_code or "duplicate_line"),
                    "assessment_code": q.assessment_code,
                }
            )
    return rows


def build_settlement_workbench(
    inputs: WorkbenchInputs | None = None,
    *,
    db: Session | None = None,
    demo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Builds the full settlement decision workbench for the synthetic demo claim."""
    demo_claim = demo or load_demo_claim()
    inp = inputs or default_inputs(demo_claim)
    ctx = _Context(inp, demo_claim, db)
    base = ctx.view(ctx.assessed_lines())

    builders = {
        "cashless_repair": lambda m: _cashless(ctx, m, base),
        "reimbursement": lambda m: _reimbursement(ctx, m, base),
        "repair_vs_replacement": lambda m: _repair_vs_replacement(ctx, m, base),
        "partial_approval": lambda m: _partial_approval(ctx, m, base),
        "supplementary_estimate": lambda m: _supplementary(ctx, m, base),
        "total_loss": lambda m: _total_loss(ctx, m),
        "constructive_total_loss": lambda m: _constructive_total_loss(ctx, m),
        "salvage_recovery": lambda m: _salvage_recovery(ctx, m),
        "zero_dep_addon": lambda m: _addon_scenario(ctx, m, key="zero_depreciation"),
        "consumables_addon": lambda m: _addon_scenario(ctx, m, key="consumables"),
        "different_deductibles": lambda m: _different_deductibles(ctx, m, base),
        "underinsurance_idv": lambda m: _underinsurance(ctx, m, base),
    }
    scenarios = [builders[meta["code"]](meta) for meta in ctx.rule["scenarios"]]

    return {
        "claim_ref": demo_claim["claim_ref"],
        "title": demo_claim["title"],
        "disclaimer": demo_claim["disclaimer"],
        "inputs": inp.echo(),
        "parameters": ctx.params,
        "rule_versions": {
            "depreciation": f"{ctx.dep_rule['rule_id']}:{ctx.dep_rule['version']}",
            "authority": f"{ctx.doa['rule_id']}:{ctx.doa['version']}",
            "scenarios": f"{ctx.rule['rule_id']}:{ctx.rule['version']}",
        },
        "summary": {
            "claimed_inr": _s(ctx.claimed_total()),
            "assessed_inr": _s(base.gross),
            "net_payable_inr": _s(base.net),
            "scenario_count": len(scenarios),
        },
        "ledger": _ledger(ctx, base),
        "line_trace": _line_trace(ctx, base),
        "scenarios": scenarios,
    }
