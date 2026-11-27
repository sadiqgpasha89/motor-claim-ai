"""Financial-calculation safety: differential testing against the independent oracle, invariants, thresholds."""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from typing import Any

from evals.core import EVALS_DIR
from evals.evaluators.settlement import oracle_calculation, run_calculator
from evals.harness import facts_for, run_agent
from evals.oracles.settlement_oracle import doa_required_tier, paise
from evals.safety import SafetyResult
from services.damage_ai.assessor import validate_estimate_lines
from services.workflow.risk_engine import classify_claim_risk_from_facts

CHECK = "financial_calculations"
SEED = 20260101
RANDOM_CASES = 300
_RULES = EVALS_DIR.parent / "rules" / "india"
_CATEGORIES = ["metal", "glass", "fibreglass", "rubber_nylon_plastic_tyres_tubes_batteries_airbags"]
_FIELDS = (
    "gross_assessed_inr",
    "depreciation_deduction_inr",
    "addon_waiver_inr",
    "net_payable_inr",
    "is_total_loss",
    "pathway",
    "ctl_threshold_inr",
)


def _rules(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((_RULES / f"{name}.json").read_text(encoding="utf-8"))
    return data


def _money(rng: random.Random, lo: int, hi: int) -> str:
    return f"{rng.randint(lo, hi)}.{rng.choice([0, 5, 25, 49, 50, 51, 75, 99]):02d}"


def random_calc_input(rng: random.Random) -> dict[str, Any]:
    idv = rng.randint(150_000, 3_000_000)
    first_reg = datetime(2026, 6, 1, tzinfo=timezone.utc) - timedelta(days=rng.randint(10, 365 * 12))
    lines: list[dict[str, str]] = []
    for i in range(rng.randint(1, 7)):
        kind = rng.choices(["part", "labour", "paint", "consumable"], weights=[5, 3, 2, 1])[0]
        category = "consumables_default" if kind == "consumable" else rng.choice(_CATEGORIES)
        lines.append(
            {
                "part_code": f"PRT-{i}",
                "description": f"{kind} {i}",
                "part_category": category,
                "line_type": kind,
                "approved_amount_inr": _money(rng, 100, int(idv * 0.5)),
            }
        )
    return {
        "lines": lines,
        "first_reg": first_reg.isoformat(),
        "incident_at": datetime(2026, 6, 1, tzinfo=timezone.utc).isoformat(),
        "idv_inr": f"{idv}.00",
        "compulsory_deductible_inr": rng.choice(["1000.00", "2000.00", "2500.00"]),
        "voluntary_deductible_inr": rng.choice(["0.00", "0.00", "2500.00", "5000.00"]),
        "addons": {"zero_depreciation": rng.random() < 0.4, "consumables": rng.random() < 0.4},
        "salvage_value_inr": rng.choice(["0.00", "0.00", "35000.00"]),
        "requested_pathway": rng.choice(["cashless", "cashless", "cashless", "total_loss"]),
    }


def _differential(result: SafetyResult) -> None:
    rng = random.Random(SEED)
    mismatches: list[str] = []
    invariants: list[str] = []
    for n in range(RANDOM_CASES):
        inp = random_calc_input(rng)
        got = run_calculator(inp)
        want = oracle_calculation(inp)
        diff = {f: (got[f], want[f]) for f in _FIELDS if got[f] != want[f]}
        if diff:
            mismatches.append(f"case {n}: {diff}")
        gross = Decimal(got["gross_assessed_inr"])
        dep = Decimal(got["depreciation_deduction_inr"])
        net = Decimal(got["net_payable_inr"])
        idv = Decimal(inp["idv_inr"])
        if net < 0:
            invariants.append(f"case {n}: negative net {net}")
        if dep > gross:
            invariants.append(f"case {n}: depreciation {dep} exceeds gross {gross}")
        if not got["is_total_loss"] and net > idv:
            invariants.append(f"case {n}: net {net} exceeds IDV {idv}")
        if net != net.quantize(Decimal("0.01")):
            invariants.append(f"case {n}: net not in paise")
    result.add(
        f"production calculator equals independent oracle on {RANDOM_CASES} seeded random settlements",
        not mismatches,
        detail="; ".join(mismatches[:3]),
    )
    result.add(
        "invariants hold: net >= 0, depreciation <= gross, net <= IDV (non-CTL), whole paise",
        not invariants,
        detail="; ".join(invariants[:3]),
    )


def _rounding(result: SafetyResult) -> None:
    result.add("oracle rounds half away from zero (0.125 -> 0.13)", paise(Fraction(125, 1000)) == Fraction(13, 100))
    result.add("oracle rounds half away from zero (-0.125 -> -0.13)", paise(Fraction(-125, 1000)) == Fraction(-13, 100))
    base = random_calc_input(random.Random(1))
    base["lines"] = [
        {
            "part_code": "P",
            "description": "x",
            "part_category": "metal",
            "line_type": "part",
            "approved_amount_inr": "10000.005",
        }
    ]
    result.add(
        "sub-paise line amounts agree with the oracle (rounding mode)",
        all(run_calculator(base)[f] == oracle_calculation(base)[f] for f in _FIELDS),
    )


def _fast_track_net(net: str) -> str:
    resp = run_agent(
        "settlement_recommendation",
        facts_for(
            "settlement_recommendation",
            calculation={"net": net},
            risk_tier="LOW",
            straight_through_eligible=True,
            allow_fast_track_auto_approve=True,
            active_conditions=[],
        ),
    )
    return str(resp.result["required_doa_tier"])


def _thresholds(result: SafetyResult) -> None:
    controls = _rules("risk_tiering_rules")["controls"]
    matrix = {t["role"]: t["max_settlement_inr"] for t in _rules("approval_authority_matrix")["authority_tiers"]}
    irdai = _rules("irdai_master_circular_2024")["controls"]
    depreciation = _rules("motor_depreciation_rates")

    auto = Decimal(controls["fast_track_auto_approval_limit_inr"])
    handler = Decimal(matrix["claims_handler"])
    survey = Decimal(irdai["mandatory_survey_threshold_inr"])
    low_max = Decimal(controls["low_risk_max_estimate_inr"])

    result.add(
        "rule files agree: low-risk ceiling is one paisa under the mandatory-survey threshold",
        low_max == survey - Decimal("0.01"),
        detail=f"{low_max} vs {survey}",
    )
    result.add(
        "rule files agree: CTL ratio identical in depreciation and risk-tiering rules",
        Decimal(depreciation["constructive_total_loss_idv_ratio_threshold"])
        == Decimal(controls["ctl_idv_ratio_threshold"]),
    )
    result.add(
        "DoA ladder is strictly increasing",
        Decimal(matrix["claims_handler"])
        < Decimal(matrix["claims_manager"])
        < Decimal(matrix["legal_tp"])
        < Decimal(matrix["finance_approver"]),
    )

    one = Decimal("0.01")
    result.add(
        f"fast-track auto-approval applies at the limit ({auto})", _fast_track_net(str(auto)) == "fast_track_auto_limit"
    )
    result.add(
        f"fast-track auto-approval stops one paisa above the limit ({auto + one})",
        _fast_track_net(str(auto + one)) == "claims_handler",
    )
    result.add(f"claims-handler authority holds at {handler}", _doa(handler) == "claims_handler")
    result.add(f"claims-manager authority starts one paisa above {handler}", _doa(handler + one) == "claims_manager")
    result.add(
        "agent DoA routing equals the oracle across the boundary values",
        all(
            _doa(v)
            == doa_required_tier(
                net_inr=str(v),
                risk_tier="MEDIUM",
                conditions=[],
                straight_through_eligible=False,
                allow_fast_track=False,
            )
            for v in (auto, auto + one, handler, handler + one, Decimal("500000.00"))
        ),
    )

    below = classify_claim_risk_from_facts({"estimated_loss_inr": str(low_max), "idv_inr": "780000.00"})["risk_tier"]
    above = classify_claim_risk_from_facts({"estimated_loss_inr": str(low_max + one), "idv_inr": "780000.00"})[
        "risk_tier"
    ]
    result.add(
        "risk engine: loss at the low-risk ceiling is LOW, one paisa above is not",
        below == "LOW" and above != "LOW",
        detail=f"{below}/{above}",
    )

    # With IDV 300,000 the CTL line (225,000) sits below the 250,000 significant-loss threshold, so the
    # HIGH tier at that point can only come from the constructive-total-loss rule.
    ctl = Decimal(controls["ctl_idv_ratio_threshold"])
    idv = Decimal("300000.00")
    edge = idv * ctl
    at = classify_claim_risk_from_facts({"estimated_loss_inr": str(edge), "idv_inr": str(idv)})["risk_tier"]
    under = classify_claim_risk_from_facts({"estimated_loss_inr": str(edge - one), "idv_inr": str(idv)})["risk_tier"]
    result.add(
        "risk engine: CTL escalates to HIGH at exactly the ratio and not one paisa below",
        at == "HIGH" and under != "HIGH",
        detail=f"{at}/{under}",
    )

    base_line = {
        "part_code": "PRT-FRT-BMP-01",
        "line_type": "part",
        "quantity": 1,
        "action": "replace",
        "description": "Line",
    }
    for price, flagged in (("14000.00", False), ("14000.01", True)):
        val = validate_estimate_lines([{**base_line, "unit_price_inr": price}])
        got = any(a["type"] == "rate_variance" for a in val["anomalies"])
        result.add(f"12% rate-card variance boundary: {price} {'flagged' if flagged else 'tolerated'}", got == flagged)


def _doa(net: Decimal) -> str:
    resp = run_agent(
        "settlement_recommendation",
        facts_for("settlement_recommendation", calculation={"net": str(net)}, risk_tier="MEDIUM", active_conditions=[]),
    )
    return str(resp.result["required_doa_tier"])


def run() -> SafetyResult:
    result = SafetyResult(CHECK, "Financial calculations")
    _differential(result)
    _rounding(result)
    _thresholds(result)
    return result
