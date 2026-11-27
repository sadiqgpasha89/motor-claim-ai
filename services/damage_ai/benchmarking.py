"""Parts and labour benchmarking for an estimate. Flags are review items, not fraud findings."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from services.rules_engine.intelligence import dec, intelligence_controls, intelligence_rule_version
from services.rules_engine.knowledge import load_rate_card

CITY_TIER = {
    "mumbai": "metro", "delhi": "metro", "bengaluru": "metro", "bangalore": "metro",
    "chennai": "metro", "hyderabad": "metro", "kolkata": "metro", "pune": "metro",
}
CENTS = Decimal("0.01")


def city_tier(city: str | None) -> str:
    key = (city or "").strip().lower()
    if not key:
        return "tier2"
    return CITY_TIER.get(key, "tier2")


def benchmark_lines(lines: list[dict[str, Any]], *, city: str | None = None) -> dict[str, Any]:
    ctl = intelligence_controls()["benchmarking"]
    parts = {p["part_code"]: p for p in load_rate_card()["parts"]}
    tier = city_tier(city)
    labour_mult = dec(ctl["city_tier_labour_multiplier"][tier])
    tol = dec(ctl["tolerance_above_band_pct"])
    rate = dec(ctl["standard_labour_rate_inr_per_hour"])

    zone_of = {code: zone for zone, codes in ctl["adjacent_zone_groups"].items() for code in codes}
    zone_count: dict[str, int] = {}
    for ln in lines:
        if ln.get("line_type") == "labour" and ln["part_code"] in zone_of:
            zone_count[zone_of[ln["part_code"]]] = zone_count.get(zone_of[ln["part_code"]], 0) + 1

    out: list[dict[str, Any]] = []
    totals = {"claimed": Decimal("0"), "benchmark_high": Decimal("0"), "benchmark_low": Decimal("0")}
    for ln in lines:
        code, kind = ln["part_code"], ln.get("line_type", "part")
        qty = int(ln.get("quantity", 1))
        claimed = dec(ln["unit_price_inr"]) * qty
        rc = parts.get(code)
        flags: list[str] = []
        low = high = Decimal("0")
        if rc:
            if kind == "part":
                low = dec(rc["oes_price"]) * qty
                high = dec(rc["oem_price"]) * qty
                if str(ln.get("part_origin", "")).lower() == "aftermarket":
                    low = (low * (1 - dec(ctl["aftermarket_discount_pct"]))).quantize(CENTS)
            elif kind == "labour":
                std = dec(rc["std_labour_inr"]) * labour_mult * qty
                low = high = std
                zone = zone_of.get(code)
                if zone and zone_count.get(zone, 0) > 1:
                    discount = dec(ctl["labour_overlap_discount_pct"])
                    low = high = (std * (1 - discount)).quantize(CENTS)
                    flags.append(f"Adjacent {zone} panels share labour. Overlap discount {discount:.0%} applies.")
                hours = ln.get("labour_hours")
                if hours is not None and rate > 0:
                    std_hours = dec(rc["std_labour_inr"]) / rate
                    if std_hours > 0 and dec(hours) / std_hours > dec(ctl["hours_over_standard_flag_ratio"]):
                        flags.append(f"Labour hours {hours} are above the standard {std_hours:.1f}.")
            elif kind == "paint":
                std = dec(rc["paint_inr"]) * qty
                low = high = std
                zone = zone_of.get(code)
                if zone and zone_count.get(zone, 0) > 1:
                    low = high = (std * (1 - dec(ctl["paint_blend_discount_pct"]))).quantize(CENTS)
                    flags.append("Paint blending across adjacent panels lowers the paint benchmark.")
            if high > 0 and claimed > high * (1 + tol):
                flags.append(f"Claimed amount is above the benchmark band by more than {tol:.0%}.")
        else:
            flags.append("No rate card entry. Manual benchmark needed.")
        totals["claimed"] += claimed
        totals["benchmark_low"] += low
        totals["benchmark_high"] += high
        out.append({
            "part_code": code, "line_type": kind, "claimed_inr": str(claimed.quantize(CENTS)),
            "band_low_inr": str(low.quantize(CENTS)), "band_high_inr": str(high.quantize(CENTS)),
            "within_band": not any("above the benchmark" in f for f in flags), "flags": flags,
        })
    return {
        "city_tier": tier,
        "labour_multiplier": str(labour_mult),
        "lines": out,
        "totals": {k: str(v.quantize(CENTS)) for k, v in totals.items()},
        "flagged_lines": sum(1 for o in out if o["flags"]),
        "rule_version": intelligence_rule_version(),
        "disclaimer": "Benchmarks use a synthetic rate card. Flags are review items, not proof of overcharging.",
    }
