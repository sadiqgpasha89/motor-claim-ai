from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from services.rules_engine.loader import get_active_rule

TWO_DP = Decimal("0.01")


def _q(val: Decimal) -> Decimal:
    return val.quantize(TWO_DP, rounding=ROUND_HALF_UP)


@dataclass
class SettlementLineInput:
    part_code: str
    description: str
    part_category: str
    line_type: str
    approved_amount_inr: Decimal


@dataclass
class SettlementCalculationResult:
    pathway: str
    gross_assessed_inr: Decimal
    depreciation_deduction_inr: Decimal
    addon_waiver_inr: Decimal
    compulsory_excess_inr: Decimal
    voluntary_excess_inr: Decimal
    salvage_deduction_inr: Decimal
    net_payable_inr: Decimal
    is_total_loss: bool
    idv_inr: Decimal
    ctl_threshold_inr: Decimal
    calculation_trace: list[dict[str, Any]]
    rule_versions: dict[str, str]
    policy_citations: list[str]


def _vehicle_age_months(first_reg: datetime, incident_at: datetime) -> int:
    if first_reg.tzinfo is None:
        first_reg = first_reg.replace(tzinfo=timezone.utc)
    if incident_at.tzinfo is None:
        incident_at = incident_at.replace(tzinfo=timezone.utc)
    days = max((incident_at - first_reg).days, 0)
    return int(days // 30)


def _metal_depreciation_rate(age_months: int, schedule: list[dict[str, Any]]) -> Decimal:
    for band in schedule:
        if age_months <= int(band["max_months"]):
            return Decimal(str(band["rate"]))
    return Decimal("0.50")


class SettlementCalculator:
    """Deterministic financial settlement calculator using Decimal arithmetic only."""

    def calculate(
        self,
        *,
        db: Session | None,
        lines: list[SettlementLineInput],
        vehicle_first_reg: datetime,
        incident_at: datetime,
        idv_inr: Decimal,
        compulsory_deductible_inr: Decimal,
        voluntary_deductible_inr: Decimal,
        addons: dict[str, Any],
        salvage_value_inr: Decimal = Decimal("0.00"),
        requested_pathway: str = "cashless",
    ) -> SettlementCalculationResult:
        dep_rule = get_active_rule(db, "IN-MOTOR-DEPRECIATION-2024")
        irdai_rule = get_active_rule(db, "IN-IRDAI-MC-2024")

        part_rates = dep_rule["part_category_rates"]
        metal_schedule = dep_rule["metal_wood_age_schedule"]
        age_months = _vehicle_age_months(vehicle_first_reg, incident_at)

        zero_dep_active = bool(addons.get("zero_depreciation", False)) and bool(
            dep_rule.get("zero_depreciation_addon_waives_part_depreciation", True)
        )
        consumables_active = bool(addons.get("consumables", False)) and bool(
            dep_rule.get("consumables_addon_covers_consumables", True)
        )

        gross_total = Decimal("0.00")
        dep_total = Decimal("0.00")
        waiver_total = Decimal("0.00")
        trace: list[dict[str, Any]] = []

        for line in lines:
            amt = _q(line.approved_amount_inr)
            gross_total += amt

            if line.line_type == "labour":
                dep_rate = Decimal("0.00")
                rule_note = "Labour carries 0% depreciation"
            elif line.line_type == "paint":
                mat_ratio = Decimal(str(part_rates["painting_material_component_ratio"]))
                dep_rate = Decimal("0.50") * mat_ratio
                rule_note = "Painting material component (50% of paint cost @ 50% dep = 25%)"
            elif line.line_type == "consumable" or line.part_category == "consumables_default":
                if consumables_active:
                    dep_rate = Decimal("0.00")
                    rule_note = "Covered under Consumables Add-on (ADDON-CONS-01)"
                else:
                    dep_rate = Decimal("1.00")
                    rule_note = "Consumables excluded without Consumables Add-on (100% deducted)"
            elif line.part_category == "metal":
                dep_rate = _metal_depreciation_rate(age_months, metal_schedule)
                rule_note = f"Metal age-graded depreciation ({age_months} months age)"
            else:
                dep_rate = Decimal(str(part_rates.get(line.part_category, "0.00")))
                rule_note = f"Category '{line.part_category}' standard rate"

            raw_dep = _q(amt * dep_rate)
            if zero_dep_active and line.line_type in {"part", "paint"} and raw_dep > Decimal("0.00"):
                waiver_total += raw_dep
                applied_dep = Decimal("0.00")
                rule_note += " -> Waived by Zero Depreciation Add-on (ADDON-ZD-01)"
            else:
                applied_dep = raw_dep

            dep_total += applied_dep
            trace.append(
                {
                    "part_code": line.part_code,
                    "description": line.description,
                    "line_type": line.line_type,
                    "approved_amount_inr": str(amt),
                    "raw_depreciation_inr": str(raw_dep),
                    "applied_depreciation_inr": str(applied_dep),
                    "net_line_inr": str(_q(amt - applied_dep)),
                    "note": rule_note,
                }
            )

        gross_total = _q(gross_total)
        dep_total = _q(dep_total)
        waiver_total = _q(waiver_total)
        comp_excess = _q(compulsory_deductible_inr)
        vol_excess = _q(voluntary_deductible_inr)
        salvage = _q(salvage_value_inr)

        ctl_ratio = Decimal(str(dep_rule.get("constructive_total_loss_idv_ratio_threshold", "0.75")))
        ctl_threshold = _q(idv_inr * ctl_ratio)
        is_total_loss = (gross_total - dep_total) >= ctl_threshold or requested_pathway == "total_loss"

        if is_total_loss:
            pathway = "total_loss"
            net_before_cap = _q(idv_inr - comp_excess - vol_excess - salvage)
            trace.append(
                {
                    "step": "CTL Evaluation",
                    "note": f"Net repair ({gross_total - dep_total}) >= {ctl_ratio*100:.0f}% of IDV ({ctl_threshold}). Constructive Total Loss applies (SEC-1-4).",
                    "idv_inr": str(_q(idv_inr)),
                    "salvage_deduction_inr": str(salvage),
                }
            )
        else:
            pathway = requested_pathway
            net_before_cap = _q(gross_total - dep_total - comp_excess - vol_excess - salvage)

        net_payable = max(_q(net_before_cap), Decimal("0.00"))
        if not is_total_loss:
            net_payable = min(net_payable, _q(idv_inr))

        citations = [
            "POL-WORDING-PC-2024 SEC-1-1 p.3 (Insured Perils)",
            "POL-WORDING-PC-2024 SEC-1-2 p.4 (Standard Parts Depreciation)",
        ]
        if zero_dep_active:
            citations.append("POL-WORDING-PC-2024 ADDON-ZD-01 p.11 (Zero Depreciation Cover)")
        if consumables_active:
            citations.append("POL-WORDING-PC-2024 ADDON-CONS-01 p.12 (Consumables Cover)")
        if is_total_loss:
            citations.append("POL-WORDING-PC-2024 SEC-1-4 p.6 (Constructive Total Loss >75% IDV)")

        return SettlementCalculationResult(
            pathway=pathway,
            gross_assessed_inr=gross_total,
            depreciation_deduction_inr=dep_total,
            addon_waiver_inr=waiver_total,
            compulsory_excess_inr=comp_excess,
            voluntary_excess_inr=vol_excess,
            salvage_deduction_inr=salvage,
            net_payable_inr=net_payable,
            is_total_loss=is_total_loss,
            idv_inr=_q(idv_inr),
            ctl_threshold_inr=ctl_threshold,
            calculation_trace=trace,
            rule_versions={
                "depreciation": f"{dep_rule['rule_id']}:{dep_rule['version']}",
                "irdai_controls": f"{irdai_rule['rule_id']}:{irdai_rule['version']}",
            },
            policy_citations=citations,
        )

    def calculate_scenarios(
        self,
        *,
        db: Session | None,
        lines: list[SettlementLineInput],
        vehicle_first_reg: datetime,
        incident_at: datetime,
        idv_inr: Decimal,
        compulsory_deductible_inr: Decimal,
        voluntary_deductible_inr: Decimal,
        addons: dict[str, Any],
        salvage_value_inr: Decimal = Decimal("0.00"),
        requested_pathway: str = "cashless",
    ) -> dict[str, Any]:
        """Evaluates primary + comparative settlement scenarios (cashless, reimbursement, without add-ons, CTL/salvage)."""
        primary = self.calculate(
            db=db,
            lines=lines,
            vehicle_first_reg=vehicle_first_reg,
            incident_at=incident_at,
            idv_inr=idv_inr,
            compulsory_deductible_inr=compulsory_deductible_inr,
            voluntary_deductible_inr=voluntary_deductible_inr,
            addons=addons,
            salvage_value_inr=salvage_value_inr,
            requested_pathway=requested_pathway,
        )
        reimb = self.calculate(
            db=db,
            lines=lines,
            vehicle_first_reg=vehicle_first_reg,
            incident_at=incident_at,
            idv_inr=idv_inr,
            compulsory_deductible_inr=compulsory_deductible_inr,
            voluntary_deductible_inr=voluntary_deductible_inr,
            addons=addons,
            salvage_value_inr=salvage_value_inr,
            requested_pathway="reimbursement",
        )
        no_addons = self.calculate(
            db=db,
            lines=lines,
            vehicle_first_reg=vehicle_first_reg,
            incident_at=incident_at,
            idv_inr=idv_inr,
            compulsory_deductible_inr=compulsory_deductible_inr,
            voluntary_deductible_inr=voluntary_deductible_inr,
            addons={"zero_depreciation": False, "consumables": False},
            salvage_value_inr=salvage_value_inr,
            requested_pathway=requested_pathway,
        )
        est_salvage = salvage_value_inr if salvage_value_inr > Decimal("0.00") else _q(idv_inr * Decimal("0.12"))
        ctl = self.calculate(
            db=db,
            lines=lines,
            vehicle_first_reg=vehicle_first_reg,
            incident_at=incident_at,
            idv_inr=idv_inr,
            compulsory_deductible_inr=compulsory_deductible_inr,
            voluntary_deductible_inr=voluntary_deductible_inr,
            addons=addons,
            salvage_value_inr=est_salvage,
            requested_pathway="total_loss",
        )

        def _row(code: str, label: str, res: SettlementCalculationResult, recommended: bool, note: str) -> dict[str, Any]:
            return {
                "scenario_code": code,
                "label": label,
                "pathway": res.pathway,
                "recommended": recommended,
                "gross_assessed_inr": str(res.gross_assessed_inr),
                "depreciation_deduction_inr": str(res.depreciation_deduction_inr),
                "addon_waiver_inr": str(res.addon_waiver_inr),
                "deductibles_total_inr": str(_q(res.compulsory_excess_inr + res.voluntary_excess_inr)),
                "salvage_deduction_inr": str(res.salvage_deduction_inr),
                "policy_idv_limit_inr": str(res.idv_inr),
                "idv_cap_applied": res.gross_assessed_inr > res.idv_inr or res.is_total_loss,
                "net_payable_inr": str(res.net_payable_inr),
                "is_total_loss": res.is_total_loss,
                "rationale": note,
            }

        scenarios = [
            _row(
                "primary_recommended",
                f"Primary ({primary.pathway.replace('_', ' ').title()})",
                primary,
                True,
                "Active policy terms, add-ons, depreciation, deductibles, and IDV cap applied.",
            ),
            _row(
                "reimbursement_option",
                "Customer Reimbursement Alternative",
                reimb,
                False,
                "Direct customer reimbursement option if repaired at non-network workshop.",
            ),
            _row(
                "without_addons_baseline",
                "Standard Tariff Baseline (No Add-ons)",
                no_addons,
                False,
                f"Shows exact customer benefit of active add-ons (waiver savings: INR {primary.addon_waiver_inr}).",
            ),
            _row(
                "ctl_salvage_retention",
                "Constructive Total Loss (IDV - Salvage)",
                ctl,
                primary.is_total_loss,
                f"CTL threshold 75% IDV = INR {primary.ctl_threshold_inr}; IDV limit = INR {primary.idv_inr}.",
            ),
        ]

        return {
            "primary": primary,
            "scenarios": scenarios,
            "addon_benefit_inr": str(_q(primary.net_payable_inr - no_addons.net_payable_inr)),
            "ctl_threshold_inr": str(primary.ctl_threshold_inr),
            "policy_idv_limit_inr": str(primary.idv_inr),
        }
