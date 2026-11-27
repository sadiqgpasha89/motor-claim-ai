"""Safety suites behind the AI release gate.

Each suite returns a :class:`SafetyResult`: a list of named :class:`Item` checks. An item tagged with a
``gap`` id is a *tracked* production defect: it is reported prominently but does not block the release, and
it raises a warning the moment it starts passing (so the registry cannot silently go stale).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Item:
    name: str
    passed: bool
    detail: str = ""
    gap: str | None = None


@dataclass
class SafetyResult:
    check: str
    title: str
    items: list[Item] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = "", gap: str | None = None) -> bool:
        self.items.append(Item(name=name, passed=bool(passed), detail=detail, gap=gap))
        return bool(passed)

    @property
    def scored(self) -> list[Item]:
        return [i for i in self.items if i.gap is None]

    @property
    def failures(self) -> list[Item]:
        return [i for i in self.scored if not i.passed]

    @property
    def tracked_gaps(self) -> list[Item]:
        return [i for i in self.items if i.gap is not None and not i.passed]

    @property
    def fixed_gaps(self) -> list[Item]:
        return [i for i in self.items if i.gap is not None and i.passed]

    @property
    def passed(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "title": self.title,
            "passed": self.passed,
            "total": len(self.scored),
            "failed": len(self.failures),
            "tracked_gaps": len(self.tracked_gaps),
            "fixed_gaps": len(self.fixed_gaps),
            "items": [asdict(i) for i in self.items],
        }
