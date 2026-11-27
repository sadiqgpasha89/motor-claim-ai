"""The evaluation framework's own tests: metrics maths, dataset integrity, and proof the gate has teeth."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from functools import lru_cache
from typing import Any

import pytest

from evals.core import AgentEval, load_json, load_known_gaps
from evals.gate import SITE_SNAPSHOT_PATH, collect, judge, load_baseline
from evals.metrics import expected_calibration_error, precision_recall_f1, safe_div
from evals.report import site_snapshot_js
from evals.safety import Item, SafetyResult
from evals.taxonomy import AGENT_ORDER, GATE_CHECKS, SCENARIO_CATEGORIES


@lru_cache(maxsize=1)
def _collected() -> tuple[dict[str, AgentEval], dict[str, SafetyResult]]:
    return collect()


def _judge(
    evals: dict[str, AgentEval] | None = None,
    suites: dict[str, SafetyResult] | None = None,
    thresholds: dict[str, Any] | None = None,
    baseline: dict[str, Any] | None = ...,  # type: ignore[assignment]
    registry: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    base_evals, base_suites = _collected()
    return judge(
        evals or base_evals,
        suites or base_suites,
        thresholds or copy.deepcopy(load_json("thresholds.json")),
        load_baseline() if baseline is ... else baseline,
        registry or load_known_gaps(),
    )


def _check(report: dict[str, Any], key: str) -> dict[str, Any]:
    return next(c for c in report["checks"] if c["key"] == key)


# ---- metrics maths ------------------------------------------------------------------
def test_precision_recall_f1_known_values() -> None:
    out = precision_recall_f1(tp=8, fp=2, fn=2)
    assert out["precision"] == pytest.approx(0.8)
    assert out["recall"] == pytest.approx(0.8)
    assert out["f1"] == pytest.approx(0.8)


def test_calibration_error_perfect_and_overconfident() -> None:
    assert expected_calibration_error([1.0, 1.0], [True, True]) == pytest.approx(0.0)
    assert expected_calibration_error([0.9, 0.9, 0.9, 0.9], [True, False, False, False]) == pytest.approx(0.65)
    assert safe_div(1, 0, default=0.0) == 0.0


# ---- dataset integrity --------------------------------------------------------------
def test_every_agent_and_category_is_covered() -> None:
    evals, _ = _collected()
    assert set(evals) == set(AGENT_ORDER)
    cats = {c.category for e in evals.values() for c in e.cases}
    assert cats == set(SCENARIO_CATEGORIES)
    thresholds = load_json("thresholds.json")
    for category in SCENARIO_CATEGORIES:
        assert (
            sum(1 for e in evals.values() for c in e.cases if c.category == category)
            >= thresholds["gate"]["min_cases_per_category"]
        )


def test_case_ids_unique_and_gaps_registered() -> None:
    evals, suites = _collected()
    ids = [c.case_id for e in evals.values() for c in e.cases]
    assert len(ids) == len(set(ids))
    registry = load_known_gaps()
    used = {c.known_gap for e in evals.values() for c in e.cases if c.known_gap}
    used |= {i.gap for s in suites.values() for i in s.items if i.gap}
    assert used <= set(registry)
    for gap in registry.values():
        assert {"id", "title", "agent", "severity", "description", "recommended_fix"} <= set(gap)


def test_every_metric_has_a_threshold() -> None:
    evals, _ = _collected()
    specs = load_json("thresholds.json")["metrics"]
    for agent, result in evals.items():
        assert set(result.metrics) == set(specs[agent])


# ---- the gate on the real system ----------------------------------------------------
def test_gate_passes_on_main() -> None:
    report = _judge()
    assert report["release_allowed"], [c["failures"] for c in report["checks"] if c["failures"]]
    assert [c["key"] for c in report["checks"]] == list(GATE_CHECKS)
    assert not report["missing_checks"]


def test_known_gaps_are_reported_not_hidden() -> None:
    report = _judge()
    open_ids = {g["id"] for g in report["known_gaps"] if g["open"]}
    assert {"GAP-SET-001", "GAP-QA-001", "GAP-COMM-001", "GAP-TOOL-001", "GAP-PII-001", "GAP-INJ-001"} <= open_ids
    assert not [w for c in report["checks"] for w in c["warnings"]], "stale gap entries should be retired"


# ---- the gate has teeth -------------------------------------------------------------
def test_blocks_on_a_regressed_metric() -> None:
    evals, _ = _collected()
    bad = dict(evals)
    metrics = dict(evals["settlement_recommendation"].metrics)
    metrics["calculation_correctness"] = 0.90
    bad["settlement_recommendation"] = replace(evals["settlement_recommendation"], metrics=metrics)
    report = _judge(evals=bad)
    assert not report["release_allowed"]
    assert any("calculation_correctness" in f for f in _check(report, "regression")["failures"])


def test_blocks_on_baseline_drift_even_above_the_floor() -> None:
    evals, _ = _collected()
    bad = dict(evals)
    metrics = dict(evals["fnol_concierge"].metrics)
    metrics["action_accuracy"] = 0.96  # above the 0.95 floor but 4 points below baseline
    bad["fnol_concierge"] = replace(evals["fnol_concierge"], metrics=metrics)
    failures = _check(_judge(evals=bad), "regression")["failures"]
    assert any("drifted" in f for f in failures)


def test_blocks_on_a_failing_critical_case() -> None:
    evals, _ = _collected()
    target = evals["claim_triage"]
    cases = list(target.cases)
    cases[0] = replace(cases[0], passed=False, known_gap=None, critical=True, detail="forced failure")
    report = _judge(evals={**evals, "claim_triage": replace(target, cases=cases)})
    assert any(f.startswith("CRITICAL") for f in _check(report, "regression")["failures"])
    assert not report["release_allowed"]


def test_blocks_without_a_baseline() -> None:
    assert not _judge(baseline=None)["release_allowed"]


def test_blocks_on_unregistered_gap() -> None:
    registry = load_known_gaps()
    registry.pop("GAP-SET-001")
    assert not _judge(registry=registry)["release_allowed"]


@pytest.mark.parametrize("key", [k for k in GATE_CHECKS if k != "regression"])
def test_blocks_when_any_safety_suite_fails(key: str) -> None:
    _, suites = _collected()
    sabotaged = copy.deepcopy(suites)
    sabotaged[key].items.append(Item(name="sabotage", passed=False, detail="injected failure"))
    report = _judge(suites=sabotaged)
    assert not report["release_allowed"]
    assert not _check(report, key)["passed"]


def test_blocks_when_a_suite_is_missing() -> None:
    _, suites = _collected()
    partial = {k: v for k, v in suites.items() if k != "pii_leakage"}
    assert not _judge(suites=partial)["release_allowed"]


def test_fixed_gap_raises_a_warning_but_does_not_block() -> None:
    _, suites = _collected()
    fixed = copy.deepcopy(suites)
    for item in fixed["pii_leakage"].items:
        if item.gap == "GAP-PII-003":
            item.passed = True
    report = _judge(suites=fixed)
    assert report["release_allowed"]
    assert any("GAP-PII-003" in w for w in _check(report, "pii_leakage")["warnings"])


def test_threshold_breach_blocks() -> None:
    thresholds = copy.deepcopy(load_json("thresholds.json"))
    thresholds["metrics"]["damage_assessment"]["classification_precision"]["min"] = 0.9
    assert not _judge(thresholds=thresholds)["release_allowed"]


# ---- public site snapshot -----------------------------------------------------------
def test_site_snapshot_is_in_sync() -> None:
    expected = site_snapshot_js(_judge())
    assert SITE_SNAPSHOT_PATH.read_text(encoding="utf-8") == expected, "run: python -m evals.gate --site-snapshot"
    payload = expected.split("window.AI_EVAL_REPORT = ", 1)[1].rstrip().rstrip(";")
    assert json.loads(payload)["release_allowed"] is True
