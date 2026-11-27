"""AI release gate: run every evaluation and safety suite, then decide whether an AI or prompt change may ship.

Usage::

    python -m evals.gate                    # human-readable verdict, exit 1 when the release is blocked
    python -m evals.gate --json out.json    # also write the machine-readable report
    python -m evals.gate --markdown         # GitHub step-summary markdown on stdout
    python -m evals.gate --update-baseline  # accept the current metrics as the new drift baseline
    python -m evals.gate --site-snapshot    # regenerate site/eval-report.js for the public dashboard

The verdict is computed by the pure function :func:`judge`, so tests can prove the gate really blocks a
release when metrics regress, thresholds are broken, gaps go unregistered or a safety check fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from evals import EVAL_FRAMEWORK_VERSION
from evals.core import EVALS_DIR, AgentEval, load_json, load_known_gaps
from evals.evaluators import evaluate_all
from evals.harness import record_responses
from evals.safety import (
    SafetyResult,
    coverage_grounding,
    fairness,
    financial,
    hallucination,
    human_escalation,
    pii_leakage,
    prompt_injection,
    tool_misuse,
    tool_permissions,
)
from evals.taxonomy import AGENT_LABELS, AGENT_ORDER, GATE_CHECKS, METRIC_DESCRIPTIONS, SCENARIO_CATEGORIES

BASELINE_PATH = EVALS_DIR / "baseline.json"
SITE_SNAPSHOT_PATH = EVALS_DIR.parent / "site" / "eval-report.js"
_EPS = 1e-9


# --------------------------------------------------------------------------------------
# Collection (runs the system under test)
# --------------------------------------------------------------------------------------
def collect() -> tuple[dict[str, AgentEval], dict[str, SafetyResult]]:
    """Run all datasets, recording every agent response, then the nine safety suites."""
    with record_responses() as recorded:
        agent_evals = evaluate_all()
    snapshot = list(recorded)
    suites: dict[str, SafetyResult] = {
        "tool_permissions": tool_permissions.run(snapshot),
        "coverage_grounding": coverage_grounding.run(),
        "financial_calculations": financial.run(),
        "prompt_injection": prompt_injection.run(),
        "pii_leakage": pii_leakage.run(),
        "human_escalation": human_escalation.run(snapshot),
        "tool_misuse": tool_misuse.run(),
        "hallucination": hallucination.run(),
        "fairness": fairness.run(),
    }
    return agent_evals, suites


# --------------------------------------------------------------------------------------
# Judgement (pure)
# --------------------------------------------------------------------------------------
def _metric_ok(value: float, spec: dict[str, Any]) -> bool:
    if "min" in spec:
        return value + _EPS >= float(spec["min"])
    return value - _EPS <= float(spec["max"])


def _at_target(value: float, spec: dict[str, Any]) -> bool:
    target = float(spec["target"])
    return value + _EPS >= target if "min" in spec else value - _EPS <= target


def _worse_by(value: float, base: float, spec: dict[str, Any]) -> float:
    return (base - value) if "min" in spec else (value - base)


def _check(
    key: str,
    failures: list[str],
    gaps: list[str],
    warnings: list[str],
    summary: str,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": GATE_CHECKS[key],
        "passed": not failures,
        "summary": summary,
        "failures": failures,
        "tracked_gaps": gaps,
        "warnings": warnings,
        "detail": detail or {},
    }


def _regression(
    agent_evals: dict[str, AgentEval],
    thresholds: dict[str, Any],
    baseline: dict[str, Any] | None,
    registry: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    failures: list[str] = []
    gaps: list[str] = []
    warnings: list[str] = []
    gate_cfg = thresholds["gate"]
    metric_cfg = thresholds["metrics"]
    rows: dict[str, Any] = {}

    cases = [c for e in agent_evals.values() for c in e.cases]
    ids = Counter(c.case_id for c in cases)
    dupes = sorted(i for i, n in ids.items() if n > 1)
    if dupes:
        failures.append(f"duplicate case ids: {', '.join(dupes[:5])}")
    if set(agent_evals) != set(AGENT_ORDER):
        failures.append("evaluators do not cover exactly the 11 agents")
    by_cat = Counter(c.category for c in cases)
    for cat in SCENARIO_CATEGORIES:
        if by_cat[cat] < gate_cfg["min_cases_per_category"]:
            failures.append(
                f"scenario category '{cat}' has {by_cat[cat]} cases (< {gate_cfg['min_cases_per_category']})"
            )
    unknown_cats = sorted(set(by_cat) - set(SCENARIO_CATEGORIES))
    if unknown_cats:
        failures.append(f"cases use unknown categories: {', '.join(unknown_cats)}")
    if len(cases) < gate_cfg["min_total_cases"]:
        failures.append(f"only {len(cases)} cases (< {gate_cfg['min_total_cases']})")

    for case in cases:
        if case.status == "fail":
            tag = "CRITICAL " if case.critical else ""
            failures.append(f"{tag}{case.case_id} ({case.agent}): {case.detail[:160]}")
        elif case.status == "known_gap":
            if case.known_gap not in registry:
                failures.append(f"{case.case_id} references unregistered gap '{case.known_gap}'")
            else:
                gaps.append(f"{case.case_id} -> {case.known_gap}")
        elif case.status == "gap_fixed":
            warnings.append(f"{case.case_id} now passes: retire {case.known_gap} from known_gaps.json")

    base_metrics = (baseline or {}).get("metrics", {})
    if baseline is None:
        failures.append("baseline.json is missing (run python -m evals.gate --update-baseline and review the diff)")
    for agent, result in agent_evals.items():
        specs = metric_cfg.get(agent, {})
        agent_rows: dict[str, Any] = {}
        for name, value in result.metrics.items():
            spec = specs.get(name)
            if spec is None:
                failures.append(f"{agent}.{name} has no threshold in thresholds.json")
                continue
            status = "pass" if _metric_ok(value, spec) else "fail"
            if status == "fail":
                bound = spec.get("min", spec.get("max"))
                failures.append(f"{agent}.{name} = {value} breaches {'min' if 'min' in spec else 'max'} {bound}")
            base = base_metrics.get(agent, {}).get(name)
            drift = _worse_by(value, float(base), spec) if base is not None else 0.0
            if base is not None and drift > gate_cfg["max_baseline_drift"] + _EPS:
                failures.append(
                    f"{agent}.{name} drifted {drift:.4f} from baseline {base} (max {gate_cfg['max_baseline_drift']})"
                )
            agent_rows[name] = {
                "value": value,
                "baseline": base,
                "min": spec.get("min"),
                "max": spec.get("max"),
                "target": spec["target"],
                "status": status,
                "at_target": _at_target(value, spec),
                "safety": bool(spec.get("safety")),
                "gap": spec.get("gap"),
                "description": METRIC_DESCRIPTIONS.get(agent, {}).get(name, ""),
            }
            if spec.get("gap") and spec["gap"] not in registry:
                failures.append(f"{agent}.{name} references unregistered gap '{spec['gap']}'")
        for name in sorted(set(specs) - set(result.metrics)):
            failures.append(f"{agent}.{name} is thresholded but no longer produced")
        rows[agent] = agent_rows

    scored = [c for c in cases if c.status in {"pass", "fail"} and not c.statistical]
    passed = sum(1 for c in scored if c.passed)
    summary = f"{passed}/{len(scored)} scored cases pass across {len(cases)} cases; {len(gaps)} tracked-gap cases"
    detail = {
        "metrics": rows,
        "cases_total": len(cases),
        "cases_scored": len(scored),
        "cases_passed": passed,
        "cases_by_category": {cat: by_cat[cat] for cat in SCENARIO_CATEGORIES},
        "cases_by_agent": {a: len(agent_evals[a].cases) for a in AGENT_ORDER if a in agent_evals},
    }
    return _check("regression", failures, gaps, warnings, summary, detail), rows


def _safety_check(key: str, result: SafetyResult, registry: dict[str, dict[str, Any]]) -> dict[str, Any]:
    failures = [f"{i.name}: {i.detail}".rstrip(": ") for i in result.failures]
    for item in result.items:
        if item.gap is not None and item.gap not in registry:
            failures.append(f"{item.name}: unregistered gap '{item.gap}'")
    gaps = [f"{i.name} -> {i.gap}" for i in result.tracked_gaps]
    warnings = [f"'{i.name}' now passes: retire {i.gap} from known_gaps.json" for i in result.fixed_gaps]
    summary = f"{len(result.scored) - len(result.failures)}/{len(result.scored)} checks pass; {len(gaps)} tracked gaps"
    return _check(key, failures, gaps, warnings, summary, {"items": [vars(i) for i in result.items]})


def _gap_register(
    registry: dict[str, dict[str, Any]],
    agent_evals: dict[str, AgentEval],
    suites: dict[str, SafetyResult],
    thresholds: dict[str, Any],
) -> list[dict[str, Any]]:
    evidence: dict[str, list[str]] = {gid: [] for gid in registry}
    for e in agent_evals.values():
        for c in e.cases:
            if c.known_gap in evidence:
                evidence[c.known_gap].append(f"{c.case_id}: {'open' if not c.passed else 'FIXED'}")
    for suite in suites.values():
        for item in suite.items:
            if item.gap in evidence:
                evidence[item.gap].append(f"{item.name}: {'open' if not item.passed else 'FIXED'}")
    for agent, specs in thresholds["metrics"].items():
        for name, spec in specs.items():
            if spec.get("gap") in evidence:
                value = agent_evals[agent].metrics.get(name) if agent in agent_evals else None
                evidence[spec["gap"]].append(f"{agent}.{name} = {value} (target {spec['target']})")
    out = []
    for gid, gap in sorted(registry.items()):
        ev = evidence[gid]
        out.append({**gap, "evidence": ev, "open": any("FIXED" not in e for e in ev) if ev else False})
    return out


def judge(
    agent_evals: dict[str, AgentEval],
    suites: dict[str, SafetyResult],
    thresholds: dict[str, Any],
    baseline: dict[str, Any] | None,
    registry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Pure verdict: same inputs always yield the same report. Nothing here touches the system under test."""
    regression, metric_rows = _regression(agent_evals, thresholds, baseline, registry)
    checks = [regression]
    for key in GATE_CHECKS:
        if key == "regression":
            continue
        if key not in suites:
            checks.append(_check(key, [f"suite '{key}' did not run"], [], [], "missing"))
        else:
            checks.append(_safety_check(key, suites[key], registry))
    register = _gap_register(registry, agent_evals, suites, thresholds)
    for entry in register:
        if not entry["evidence"]:
            regression["warnings"].append(
                f"{entry['id']} has no evidence in any dataset or suite (orphaned registry entry)"
            )
    required = thresholds["gate"]["required_checks"]
    missing = sorted(set(required) - {c["key"] for c in checks})
    release = all(c["passed"] for c in checks) and not missing
    return {
        "framework_version": EVAL_FRAMEWORK_VERSION,
        "release_allowed": release,
        "verdict": "RELEASE ALLOWED" if release else "RELEASE BLOCKED",
        "checks": checks,
        "missing_checks": missing,
        "agents": [
            {
                "agent": a,
                "label": AGENT_LABELS[a],
                "metrics": metric_rows.get(a, {}),
                "cases": len(agent_evals[a].cases) if a in agent_evals else 0,
                "failed": sum(1 for c in agent_evals[a].cases if c.status == "fail") if a in agent_evals else 0,
                "tracked_gaps": sum(1 for c in agent_evals[a].cases if c.status == "known_gap")
                if a in agent_evals
                else 0,
            }
            for a in AGENT_ORDER
        ],
        "known_gaps": register,
        "injection": prompt_injection.injection_metrics(),
        "thresholds_version": thresholds.get("version"),
    }


def baseline_from(agent_evals: dict[str, AgentEval]) -> dict[str, Any]:
    return {
        "framework_version": EVAL_FRAMEWORK_VERSION,
        "description": "Accepted metric values. The gate fails when any metric is worse than this by more than max_baseline_drift. Update only via `python -m evals.gate --update-baseline` and review the diff.",
        "metrics": {a: dict(sorted(e.metrics.items())) for a, e in agent_evals.items()},
    }


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def load_baseline() -> dict[str, Any] | None:
    return load_json("baseline.json") if BASELINE_PATH.exists() else None  # type: ignore[no-any-return]


def run_gate() -> dict[str, Any]:
    agent_evals, suites = collect()
    return judge(agent_evals, suites, load_json("thresholds.json"), load_baseline(), load_known_gaps())


def main(argv: Sequence[str] | None = None) -> int:
    from evals.report import site_snapshot_js, to_console, to_markdown

    parser = argparse.ArgumentParser(prog="python -m evals.gate", description="MotorClaim AI release gate")
    parser.add_argument("--json", metavar="PATH", help="write the full machine-readable report")
    parser.add_argument("--markdown", action="store_true", help="print a markdown summary (for $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--update-baseline", action="store_true", help="accept current metrics as the drift baseline")
    parser.add_argument("--site-snapshot", action="store_true", help="regenerate site/eval-report.js")
    args = parser.parse_args(argv)

    agent_evals, suites = collect()
    if args.update_baseline:
        BASELINE_PATH.write_text(json.dumps(baseline_from(agent_evals), indent=2) + "\n", encoding="utf-8")
        print(f"baseline written to {BASELINE_PATH}")
    report = judge(agent_evals, suites, load_json("thresholds.json"), load_baseline(), load_known_gaps())
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
        )
    if args.site_snapshot:
        SITE_SNAPSHOT_PATH.write_text(site_snapshot_js(report), encoding="utf-8")
        print(f"site snapshot written to {SITE_SNAPSHOT_PATH}")
    print(to_markdown(report) if args.markdown else to_console(report))
    return 0 if report["release_allowed"] else 1


if __name__ == "__main__":
    sys.exit(main())
