"""Dataset loading, case/result containers and the small assertion helper shared by all evaluators."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

EVALS_DIR = Path(__file__).resolve().parent
DATASET_DIR = EVALS_DIR / "datasets"


# --------------------------------------------------------------------------------------
# Datasets
# --------------------------------------------------------------------------------------
@dataclass
class Case:
    """One evaluation case: an input, the ground-truth expectation, and bookkeeping tags."""

    id: str
    category: str
    description: str
    input: dict[str, Any]
    expected: dict[str, Any]
    known_gap: str | None = None
    critical: bool = False  # safety-critical: a failure here always blocks the release
    statistical: bool = False  # contributes to metrics only (no per-case pass/fail)
    tags: list[str] = field(default_factory=list)


@dataclass
class Dataset:
    name: str
    agent: str
    version: str
    cases: list[Case]


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursive dict merge; scalars and lists in ``override`` replace those in ``base``."""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def case_from_dict(raw: dict[str, Any], base_input: dict[str, Any]) -> Case:
    return Case(
        id=raw["id"],
        category=raw["category"],
        description=raw.get("description", ""),
        input=deep_merge(base_input, raw.get("input", {})),
        expected=raw.get("expected", {}),
        known_gap=raw.get("known_gap"),
        critical=bool(raw.get("critical", False)),
        statistical=bool(raw.get("statistical", False)),
        tags=list(raw.get("tags", [])),
    )


def load_dataset(name: str) -> Dataset:
    """Load ``evals/datasets/<name>.json`` and merge each case input over the file-level ``base``."""
    path = DATASET_DIR / f"{name}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    base_input = raw.get("base", {}).get("input", {})
    cases = [case_from_dict(c, base_input) for c in raw["cases"]]
    return Dataset(name=name, agent=raw["agent"], version=raw.get("version", "1.0.0"), cases=cases)


def load_json(name: str) -> Any:
    return json.loads((EVALS_DIR / name).read_text(encoding="utf-8"))


def load_known_gaps() -> dict[str, dict[str, Any]]:
    """Registry of defects the evaluation itself uncovered and that are tracked, not hidden."""
    gaps = load_json("known_gaps.json")["gaps"]
    return {g["id"]: g for g in gaps}


# --------------------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------------------
@dataclass
class CaseResult:
    case_id: str
    agent: str
    category: str
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    detail: str = ""
    known_gap: str | None = None
    critical: bool = False
    statistical: bool = False

    @property
    def status(self) -> str:
        if self.known_gap:
            return "gap_fixed" if self.passed else "known_gap"
        return "pass" if self.passed else "fail"


@dataclass
class AgentEval:
    agent: str
    metrics: dict[str, float]
    cases: list[CaseResult]
    extra: dict[str, Any] = field(default_factory=dict)

    def scored_cases(self) -> list[CaseResult]:
        """Cases that count toward the pass-rate (not known gaps, not purely statistical)."""
        return [c for c in self.cases if not c.known_gap and not c.statistical]

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "metrics": self.metrics,
            "cases": [asdict(c) | {"status": c.status} for c in self.cases],
            "extra": self.extra,
        }


class Checks:
    """Accumulates named boolean checks for one case and renders a compact failure detail."""

    def __init__(self) -> None:
        self.items: dict[str, bool] = {}
        self._failures: list[str] = []

    def expect(self, name: str, ok: bool, *, observed: Any = None, expected: Any = None) -> bool:
        self.items[name] = bool(ok)
        if not ok:
            self._failures.append(f"{name}: expected={_short(expected)} observed={_short(observed)}")
        return bool(ok)

    def eq(self, name: str, observed: Any, expected: Any) -> bool:
        return self.expect(name, observed == expected, observed=observed, expected=expected)

    @property
    def passed(self) -> bool:
        return all(self.items.values())

    @property
    def detail(self) -> str:
        return "; ".join(self._failures)

    def result(self, case: Case, agent: str) -> CaseResult:
        return CaseResult(
            case_id=case.id,
            agent=agent,
            category=case.category,
            passed=self.passed,
            checks=dict(self.items),
            detail=self.detail,
            known_gap=case.known_gap,
            critical=case.critical,
            statistical=case.statistical,
        )


def _short(value: Any, limit: int = 140) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def active(cases: list[Case]) -> list[Case]:
    """Cases that feed aggregate metrics (known-gap cases are reported separately)."""
    return [c for c in cases if not c.known_gap]
