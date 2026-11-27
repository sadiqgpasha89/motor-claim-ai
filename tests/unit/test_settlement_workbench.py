from __future__ import annotations

import itertools
import json
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from scripts.export_settlement_workbench_data import OUTPUT, render
from services.settlement.authority import resolve_required_authority
from services.settlement.workbench import build_settlement_workbench, inputs_from_mapping
from tests.conftest import auth_headers

ROOT = Path(__file__).resolve().parents[2]


def _scenarios(overrides: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    wb = build_settlement_workbench(inputs_from_mapping(overrides or {}))
    return {s["scenario_code"]: s for s in wb["scenarios"]}


def test_workbench_has_twelve_scenarios_with_all_eight_decision_fields():
    wb = build_settlement_workbench()
    assert wb["summary"]["scenario_count"] == 12
    assert [s["number"] for s in wb["scenarios"]] == list(range(1, 13))
    for sc in wb["scenarios"]:
        assert sc["claimed"]["amount"] and sc["assessed"]["amount"] and sc["approved"]["amount"]
        assert "total" in sc["deducted"]
        assert sc["policy_clauses"], sc["scenario_code"]
        assert sc["approval"]["checker_role"] and sc["approval"]["payment_release_role"]
        assert sc["customer_receives"]["amount"] == sc["net_payable"]
        assert sc["why_different"]["items"] is not None


def test_ledger_matches_the_existing_calculator_headline_numbers():
    wb = build_settlement_workbench()
    steps = {s["key"]: s for s in wb["ledger"]["steps"]}
    assert steps["approved_amount"]["amount"] == "48700.00"
    assert steps["tariff_depreciation"]["amount"] == "9430.00"
    assert steps["addon_zero_dep"]["amount"] == "7030.00"
    assert steps["addon_consumables"]["amount"] == "2400.00"
    assert steps["compulsory_excess"]["amount"] == "1000.00"
    assert wb["ledger"]["net_payable"] == "47700.00"
    assert wb["summary"]["claimed_inr"] == "64400.00"


def test_claimed_assessed_approved_chain_for_the_primary_scenario():
    sc = _scenarios()["cashless_repair"]
    assert (sc["claimed"]["amount"], sc["assessed"]["amount"], sc["approved"]["amount"]) == ("64400.00", "48700.00", "48700.00")
    assert {a["code"]: a["amount"] for a in sc["assessed"]["adjustments"]} == {
        "duplicate_line": "-12500.00",
        "rate_variance": "-3200.00",
    }
    assert sc["customer_receives"]["customer_pays"] == "1000.00"


def test_reimbursement_has_same_net_but_customer_funds_more():
    s = _scenarios()
    assert s["reimbursement"]["net_payable"] == s["cashless_repair"]["net_payable"]
    assert Decimal(s["reimbursement"]["customer_receives"]["customer_pays"]) > Decimal(
        s["cashless_repair"]["customer_receives"]["customer_pays"]
    )
    assert s["reimbursement"]["comparison"]["documents_required"]


def test_repair_is_cheaper_than_replacement_and_paint_is_depreciated_without_zero_dep():
    s = _scenarios()["repair_vs_replacement"]
    assert s["net_payable"] == "30800.00"
    assert s["comparison"]["recommended_option"] == "repair"
    assert s["comparison"]["insurer_saving_inr"] == "16900.00"
    off = _scenarios({"zero_depreciation": False})["repair_vs_replacement"]
    # paint material carries 25% depreciation: (2400 + 2200) * 25% = 1150
    assert off["comparison"]["options"][1]["applied_depreciation_inr"] == "1150.00"


def test_partial_approval_withholds_line_and_reports_release_amount():
    s = _scenarios()["partial_approval"]
    assert s["approved"]["amount"] == "30300.00"
    assert s["approved"]["withheld"][0]["amount"] == "-18400.00"
    assert s["net_payable"] == "29300.00"
    assert s["comparison"]["additional_payable_on_release_inr"] == "18400.00"


def test_supplementary_estimate_applies_excess_once_and_flags_reinspection():
    s = _scenarios()["supplementary_estimate"]
    c = s["comparison"]
    assert c["initial_net_inr"] == "47700.00" and c["revised_net_inr"] == "65500.00"
    assert c["incremental_payable_inr"] == "17800.00"  # full supplementary amount: excess not charged twice
    assert c["reinspection_required"] is True
    assert c["variance_ratio"] == "0.3655" and c["variance_threshold"] == "0.2000"


def test_total_loss_ctl_and_salvage_recovery():
    s = _scenarios()
    assert s["total_loss"]["net_payable"] == "779000.00"
    assert s["total_loss"]["comparison"]["shortfall_vs_market_inr"] == "130000.00"
    assert s["constructive_total_loss"]["comparison"]["ctl_triggered"] is True
    assert s["constructive_total_loss"]["net_payable"] == "694000.00"
    sal = s["salvage_recovery"]
    assert sal["comparison"]["surrender"]["net_recovery_inr"] == "80750.00"
    assert sal["insurer_net_cost"] == "698250.00"
    assert sal["comparison"]["retention_saving_for_insurer_inr"] == "4250.00"


def test_ctl_not_triggered_for_old_vehicle_without_zero_dep():
    s = _scenarios({"vehicle_age_months": 90, "zero_depreciation": False})["constructive_total_loss"]
    assert s["comparison"]["ctl_triggered"] is False
    assert s["customer_receives"]["outcome"].startswith("Repair threshold not reached")


def test_addon_scenarios_report_their_value():
    s = _scenarios()
    assert s["zero_dep_addon"]["comparison"]["benefit_inr"] == "7030.00"
    assert s["consumables_addon"]["comparison"]["benefit_inr"] == "2400.00"
    off = _scenarios({"zero_depreciation": False, "consumables": False})
    assert off["zero_dep_addon"]["comparison"]["active_on_policy"] is False
    assert off["cashless_repair"]["net_payable"] == "38270.00"


def test_deductible_matrix_and_underinsurance():
    s = _scenarios()
    matrix = s["different_deductibles"]["comparison"]["matrix"]
    assert [row["compulsory_inr"] for row in matrix] == ["1000.00", "1500.00", "2000.00"]
    assert matrix[0]["cells"][0]["net_payable_inr"] == "47700.00"
    assert matrix[0]["cells"][4]["net_payable_inr"] == "32700.00"  # 1,000 + 15,000 excess
    u = s["underinsurance_idv"]["comparison"]
    assert u["idv_ratio"] == "0.8571" and u["underinsured"] is True
    assert u["net_with_pro_rata_inr"] == "40742.86"
    fully = _scenarios({"market_value_inr": "780000"})["underinsurance_idv"]
    assert fully["comparison"]["underinsured"] is False
    assert fully["net_payable"] == "47700.00"


def test_approval_authority_follows_the_doa_matrix():
    s = _scenarios()
    assert s["cashless_repair"]["approval"]["checker_role"] == "claims_handler"
    assert s["total_loss"]["approval"]["checker_role"] == "finance_approver"
    reasons = {t["role"]: t["reason_code"] for t in s["total_loss"]["approval"]["skipped_tiers"]}
    assert reasons["claims_handler"] == "amount_exceeds_limit"
    assert reasons["claims_manager"] == "amount_exceeds_limit"
    assert reasons["legal_tp"] == "claim_type_not_allowed"
    # a larger repair moves from handler to manager
    big = _scenarios({"idv_inr": "5000000", "market_value_inr": "5000000"})
    assert big["constructive_total_loss"]["approval"]["checker_role"] == "finance_approver"


def test_resolve_required_authority_blocks_conditions():
    from services.rules_engine.loader import load_rule_files

    doa = load_rule_files()["IN-DOA-MATRIX-2026"]
    res = resolve_required_authority(doa, amount_inr=Decimal("50000"), claim_type="cashless", active_conditions=["fraud_alert_open"])
    assert res["checker_role"] == "claims_manager"
    assert res["skipped_tiers"][0] == {"role": "claims_handler", "reason_code": "condition_blocked"}


@pytest.mark.parametrize(
    "age,zd,cons,comp,vol,salvage,idv,mv",
    list(
        itertools.product(
            [3, 30, 90], [True, False], [True, False], [1000, 60000], [0, 15000], [0, 900000], [780000, 60000], [910000, 0]
        )
    ),
)
def test_why_different_always_reconciles_to_the_rupee(age, zd, cons, comp, vol, salvage, idv, mv):
    scenarios = _scenarios(
        {
            "vehicle_age_months": age,
            "zero_depreciation": zd,
            "consumables": cons,
            "compulsory_deductible_inr": comp,
            "voluntary_deductible_inr": vol,
            "salvage_value_inr": salvage,
            "idv_inr": idv,
            "market_value_inr": mv,
        }
    )
    for code, sc in scenarios.items():
        w = sc["why_different"]
        assert w["balanced"], code
        total = sum(Decimal(i["amount"]) for i in w["items"])
        assert Decimal(w["requested"]) + total == Decimal(w["receives"]), code
        assert Decimal(sc["net_payable"]) >= 0


# ----------------------------------------------------------------------------- site parity


def test_site_data_file_is_up_to_date():
    assert OUTPUT.read_text(encoding="utf-8") == render(), (
        "site/settlement-workbench-data.js is stale; run python scripts/export_settlement_workbench_data.py"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for the JS parity check")
def test_browser_engine_matches_python_engine_exactly():
    cases: list[dict[str, Any]] = [
        {},
        {"zero_depreciation": False, "consumables": False},
        {"vehicle_age_months": 90, "zero_depreciation": False},
        {"vehicle_age_months": 130, "consumables": False},
        {"salvage_value_inr": 900000, "compulsory_deductible_inr": 60000, "voluntary_deductible_inr": 15000},
        {"idv_inr": 60000, "market_value_inr": 0},
        {"idv_inr": "5000000", "market_value_inr": "5500000.55", "vehicle_age_months": 30},
        {"compulsory_deductible_inr": "1234.565", "voluntary_deductible_inr": 2500},
    ]
    proc = subprocess.run(
        ["node", str(ROOT / "tests" / "unit" / "js" / "run_workbench.js")],
        input=json.dumps(cases),
        capture_output=True,
        text=True,
        check=True,
    )
    js_results = json.loads(proc.stdout)
    for overrides, js in zip(cases, js_results, strict=True):
        py = json.loads(json.dumps(build_settlement_workbench(inputs_from_mapping(overrides)), default=str))
        assert py == js, overrides


# ----------------------------------------------------------------------------- API


def test_workbench_endpoint_is_role_gated_and_returns_all_scenarios(client):
    assert client.post("/api/v1/settlement/workbench", json={}).status_code in (401, 403)
    headers = auth_headers(client, "manager@demo.in")
    resp = client.post("/api/v1/settlement/workbench", json={"zero_depreciation": False}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["scenarios"]) == 12
    assert body["inputs"]["zero_depreciation"] is False
    # no Zero-Dep: plastic (6,250) + metal (780) depreciation applies, consumables stay covered
    assert body["ledger"]["net_payable"] == "40670.00"
    assert client.post("/api/v1/settlement/workbench", json={"idv_inr": -5}, headers=headers).status_code == 422
