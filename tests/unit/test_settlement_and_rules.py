from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from packages.contracts.errors import DomainError
from services.claims.state_machine import ClaimStatus, validate_transition
from services.damage_ai.assessor import validate_estimate_lines
from services.rules_engine.knowledge import HybridPolicyRetriever
from services.settlement.calculator import SettlementCalculator, SettlementLineInput


def test_deterministic_settlement_with_zero_dep_and_consumables():
    now = datetime.now(timezone.utc)
    calc = SettlementCalculator().calculate(
        db=None,
        lines=[
            SettlementLineInput("PRT-FRT-BMP-01", "Front Bumper", "rubber_nylon_plastic_tyres_tubes_batteries_airbags", "part", Decimal("12500.00")),
            SettlementLineInput("PRT-HL-LED-RH", "LED Headlamp", "glass", "part", Decimal("18400.00")),
            SettlementLineInput("PRT-FND-RH-01", "Front Fender", "metal", "part", Decimal("7800.00")),
            SettlementLineInput("PRT-FRT-BMP-01", "Labour", "labour", "labour", Decimal("7600.00")),
            SettlementLineInput("PRT-CONS-KIT-01", "Consumables", "consumables_default", "consumable", Decimal("2400.00")),
        ],
        vehicle_first_reg=now - timedelta(days=540),
        incident_at=now,
        idv_inr=Decimal("780000.00"),
        compulsory_deductible_inr=Decimal("1000.00"),
        voluntary_deductible_inr=Decimal("0.00"),
        addons={"zero_depreciation": True, "consumables": True},
    )
    assert calc.gross_assessed_inr == Decimal("48700.00")
    assert calc.depreciation_deduction_inr == Decimal("0.00")
    assert calc.addon_waiver_inr > Decimal("0.00")
    assert calc.net_payable_inr == Decimal("47700.00")
    assert calc.is_total_loss is False


def test_deterministic_settlement_without_zero_dep_applies_depreciation():
    now = datetime.now(timezone.utc)
    calc = SettlementCalculator().calculate(
        db=None,
        lines=[
            SettlementLineInput("PRT-FRT-BMP-01", "Front Bumper", "rubber_nylon_plastic_tyres_tubes_batteries_airbags", "part", Decimal("10000.00")),
            SettlementLineInput("PRT-CONS-KIT-01", "Consumables", "consumables_default", "consumable", Decimal("2000.00")),
        ],
        vehicle_first_reg=now - timedelta(days=540),
        incident_at=now,
        idv_inr=Decimal("500000.00"),
        compulsory_deductible_inr=Decimal("1000.00"),
        voluntary_deductible_inr=Decimal("500.00"),
        addons={"zero_depreciation": False, "consumables": False},
    )
    assert calc.depreciation_deduction_inr == Decimal("7000.00")
    assert calc.net_payable_inr == Decimal("3500.00")


def test_constructive_total_loss_above_75_pct_idv():
    now = datetime.now(timezone.utc)
    calc = SettlementCalculator().calculate(
        db=None,
        lines=[SettlementLineInput("PRT-BON-01", "Major Shell", "glass", "part", Decimal("400000.00"))],
        vehicle_first_reg=now - timedelta(days=200),
        incident_at=now,
        idv_inr=Decimal("500000.00"),
        compulsory_deductible_inr=Decimal("1000.00"),
        voluntary_deductible_inr=Decimal("0.00"),
        addons={"zero_depreciation": True},
        salvage_value_inr=Decimal("60000.00"),
    )
    assert calc.is_total_loss is True
    assert calc.pathway == "total_loss"
    assert calc.net_payable_inr == Decimal("439000.00")


def test_estimate_validation_detects_duplicate_and_rate_variance():
    res = validate_estimate_lines(
        [
            {"part_code": "PRT-FRT-BMP-01", "description": "Front Bumper", "line_type": "part", "quantity": 1, "unit_price_inr": Decimal("12500.00")},
            {"part_code": "PRT-FRT-BMP-01", "description": "Front Bumper Dup", "line_type": "part", "quantity": 1, "unit_price_inr": Decimal("12500.00")},
            {"part_code": "PRT-FND-RH-01", "description": "Fender", "line_type": "part", "quantity": 1, "unit_price_inr": Decimal("11000.00")},
        ]
    )
    types = {a["type"] for a in res["anomalies"]}
    assert "duplicate_line" in types
    assert "rate_variance" in types
    assert Decimal(res["total_recommended_inr"]) == Decimal("20300.00")


def test_state_machine_rejects_invalid_jump():
    assert validate_transition(ClaimStatus.REGISTERED.value, ClaimStatus.COVERAGE_CHECKED.value) == ClaimStatus.COVERAGE_CHECKED
    with pytest.raises(DomainError):
        validate_transition(ClaimStatus.REGISTERED.value, ClaimStatus.CLOSED.value)


def test_hybrid_policy_retrieval_returns_exact_clause_citations():
    retriever = HybridPolicyRetriever()
    hits = retriever.search("zero depreciation waiver rubber plastic", top_k=2)
    assert len(hits) == 2
    assert any(h["clause_id"] == "ADDON-ZD-01" for h in hits)
