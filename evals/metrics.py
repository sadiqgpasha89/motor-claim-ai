"""Small, dependency-free metric helpers used by every evaluator."""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Sequence
from typing import TypeVar

T = TypeVar("T", bound=Hashable)


def safe_div(numerator: float, denominator: float, default: float = 1.0) -> float:
    """Division that returns ``default`` when the denominator is zero (vacuous truth)."""
    return default if denominator == 0 else numerator / denominator


def precision_recall_f1(tp: int, fp: int, fn: int) -> dict[str, float]:
    """Precision / recall / F1 with the vacuous-truth convention (no positives -> 1.0)."""
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    f1 = 1.0 if (tp + fp + fn) == 0 else safe_div(2 * precision * recall, precision + recall, default=0.0)
    return {"precision": precision, "recall": recall, "f1": f1}


def set_confusion(predicted: Iterable[T], expected: Iterable[T]) -> tuple[int, int, int]:
    """Return (tp, fp, fn) comparing two collections as sets."""
    p, e = set(predicted), set(expected)
    return len(p & e), len(p - e), len(e - p)


def levenshtein(a: str, b: str) -> int:
    """Classic edit distance (iterative, O(len(a)*len(b)))."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def char_accuracy(predicted: str, truth: str) -> float:
    """1 - normalised edit distance; an empty prediction scores 0."""
    if not truth:
        return 1.0 if not predicted else 0.0
    if not predicted:
        return 0.0
    return max(0.0, 1.0 - levenshtein(predicted, truth) / max(len(predicted), len(truth)))


def expected_calibration_error(confidences: Sequence[float], correct: Sequence[bool], bins: int = 5) -> float:
    """Expected calibration error with equal-width bins over [0, 1]."""
    n = len(confidences)
    if n == 0:
        return 0.0
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, c in enumerate(confidences) if (lo <= c < hi) or (b == bins - 1 and c == 1.0)]
        if not idx:
            continue
        avg_conf = sum(confidences[i] for i in idx) / len(idx)
        accuracy = sum(1 for i in idx if correct[i]) / len(idx)
        total += (len(idx) / n) * abs(avg_conf - accuracy)
    return total


def brier_score(confidences: Sequence[float], correct: Sequence[bool]) -> float:
    """Mean squared error between confidence and outcome (lower is better)."""
    if not confidences:
        return 0.0
    return sum((c - (1.0 if ok else 0.0)) ** 2 for c, ok in zip(confidences, correct, strict=True)) / len(confidences)


def rate(flags: Sequence[bool]) -> float:
    """Share of True values; empty -> 1.0 (vacuous)."""
    return safe_div(sum(1 for f in flags if f), len(flags))


def r4(value: float) -> float:
    """Round for stable, diff-friendly reports."""
    return round(float(value), 4)
