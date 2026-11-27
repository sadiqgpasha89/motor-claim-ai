"""Independent settlement oracle.

Re-implements the published settlement rules with exact rational arithmetic (``fractions.Fraction``)
and reads the rule JSON files directly. It shares NO code with ``services.settlement.calculator`` so
a regression in the production calculator (rounding mode, depreciation band, CTL threshold, excess
order) cannot also hide in the oracle.

Money convention: each monetary line is rounded to paise (INR 0.01) half away from zero, which is the
documented rounding rule, exactly once per line, exactly where the production rules round.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

_RULES = Path(__file__).resolve().parents[2] / "rules" / "india"


def _frac(value: Any) -> Fraction:
    return Fraction(str(value))


def paise(value: Fraction) -> Fraction:
    """Round half away from zero to 2 decimal places."""
    scaled = value * 100
    rounded = math.floor(abs(scaled) + Fraction(1, 2))
    return Fraction(rounded if scaled >= 0 else -rounded, 100)


def to_str(value: Fraction) -> str:
    cents = int(value * 100)
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def _depreciation_rules() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((_RULES / "motor_depreciation_rates.json").read_text(encoding="utf-8"))
    return data


def age_in_months(first_reg: datetime, incident_at: datetime) -> int:
    if first_reg.tzinfo is None:
        first_reg = first_reg.replace(tzinfo=timezone.utc)
    if incident_at.tzinfo is None:
        incident_at = incident_at.replace(tzinfo=timezone.utc)
    return max((incident_at - first_reg).days, 0) // 30


@dataclass(frozen=True)
class OracleResult:
    gross: Fraction
    depreciation: Fraction
    waiver: Fraction
    net: Fraction
    is_total_loss: bool
    pathway: str
    ctl_threshold: Fraction

    def as_strings(self) -> dict[str, Any]:
        return {
            "gross_assessed_inr": to_str(self.gross),
            "depreciation_deduction_inr": to_str(self.depreciation),
            "addon_waiver_inr": to_str(self.waiver),
            "net_payable_inr": to_str(self.net),
            "is_total_loss": self.is_total_loss,
            "pathway": self.pathway,
            "ctl_threshold_inr": to_str(self.ctl_threshold),
        }


def settle(
    lines: list[dict[str, Any]],
    *,
    first_reg: datetime,
    incident_at: datetime,
    idv: str,
    compulsory: str,
    voluntary: str,
    addons: dict[str, bool],
    salvage: str = "0.00",
    requested_pathway: str = "cashless",
) -> OracleResult:
    rules = _depreciation_rules()
    category_rates = rules["part_category_rates"]
    schedule = rules["metal_wood_age_schedule"]
    age = age_in_months(first_reg, incident_at)

    def metal_rate() -> Fraction:
        for band in schedule:
            if age <= int(band["max_months"]):
                return _frac(band["rate"])
        return Fraction(1, 2)

    zero_dep = bool(addons.get("zero_depreciation")) and rules["zero_depreciation_addon_waives_part_depreciation"]
    consumables = bool(addons.get("consumables")) and rules["consumables_addon_covers_consumables"]

    gross = Fraction(0)
    dep_total = Fraction(0)
    waiver = Fraction(0)
    for line in lines:
        amount = paise(_frac(line["approved_amount_inr"]))
        gross += amount
        kind = line["line_type"]
        if kind == "labour":
            rate = Fraction(0)
        elif kind == "paint":
            rate = Fraction(1, 2) * _frac(category_rates["painting_material_component_ratio"])
        elif kind == "consumable" or line["part_category"] == "consumables_default":
            rate = Fraction(0) if consumables else Fraction(1)
        elif line["part_category"] == "metal":
            rate = metal_rate()
        else:
            rate = _frac(category_rates.get(line["part_category"], "0"))
        raw = paise(amount * rate)
        if zero_dep and kind in {"part", "paint"} and raw > 0:
            waiver += raw
        else:
            dep_total += raw

    idv_f, comp, vol, salv = (paise(_frac(x)) for x in (idv, compulsory, voluntary, salvage))
    ctl_threshold = paise(idv_f * _frac(rules["constructive_total_loss_idv_ratio_threshold"]))
    total_loss = (gross - dep_total) >= ctl_threshold or requested_pathway == "total_loss"
    if total_loss:
        net = paise(idv_f - comp - vol - salv)
        pathway = "total_loss"
    else:
        net = paise(gross - dep_total - comp - vol - salv)
        pathway = requested_pathway
    net = max(net, Fraction(0))
    if not total_loss:
        net = min(net, idv_f)
    return OracleResult(gross, dep_total, waiver, net, total_loss, pathway, ctl_threshold)


def doa_required_tier(
    *,
    net_inr: str,
    risk_tier: str,
    conditions: list[str],
    straight_through_eligible: bool,
    allow_fast_track: bool,
    auto_limit: str = "25000.00",
    handler_limit: str = "75000.00",
) -> str:
    """Independent statement of the delegation-of-authority routing rules."""
    net = _frac(net_inr)
    if (
        risk_tier == "LOW"
        and straight_through_eligible
        and allow_fast_track
        and not conditions
        and 0 < net <= _frac(auto_limit)
    ):
        return "fast_track_auto_limit"
    if "tp_injury" in conditions or "tp_fatality" in conditions:
        return "legal_tp"
    manager_conditions = {"fraud_alert_open", "ev_battery", "total_loss", "high_risk_complex"}
    if manager_conditions & set(conditions) or risk_tier == "HIGH" or net > _frac(handler_limit):
        return "claims_manager"
    return "claims_handler"
