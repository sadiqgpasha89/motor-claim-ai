"""SLA rules service: versioned, effective-dated, claim-type aware SLA definitions.

Each rule carries: rule version, applicable claim types, trigger event, start condition, pause conditions,
deadline, escalation sequence, responsible team and breach action. Nothing here hardcodes an SLA value;
all targets come from the ``COMMON-SLA-RULES-V2`` catalogue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from services.rules_engine.loader import get_active_rule

SLA_CATALOGUE_ID = "COMMON-SLA-RULES-V2"

SLA_METRICS: list[str] = [
    "claim_registration",
    "document_verification",
    "surveyor_assignment",
    "survey_completion",
    "estimate_approval",
    "repair_completion",
    "payment_processing",
    "claim_closure",
]

KNOWN_EVENTS: set[str] = {
    "ClaimIntimated",
    "ClaimRegistered",
    "DocumentsVerified",
    "ClaimTriaged",
    "SurveyorAssigned",
    "SurveyReportReceived",
    "EstimateSubmitted",
    "EstimateApproved",
    "RepairCompleted",
    "SettlementApproved",
    "PaymentCompleted",
    "ClaimClosed",
}

KNOWN_FACTS: set[str] = {
    "claim_type",
    "claim_status",
    "risk_tier",
    "operational_path",
    "evidence_count",
    "missing_document_count",
    "survey_required",
    "garage_assigned",
    "ev_involved",
}

KNOWN_PAUSE_SOURCES: set[str] = {"task", "claim_status"}
_UNIT_HOURS = {"minutes": 1 / 60, "hours": 1.0, "days": 24.0}


def aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def parse_version(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in str(version).split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return aware(datetime.fromisoformat(value.replace("Z", "+00:00")))


@dataclass(frozen=True)
class EscalationStep:
    step: int
    at_pct: float
    action: str
    to_team: str


@dataclass(frozen=True)
class SLARule:
    sla_id: str
    metric: str
    title: str
    rule_version: str
    effective_from: datetime
    effective_to: datetime | None
    applicable_claim_types: tuple[str, ...]
    trigger_event: str
    start_condition: dict[str, Any]
    stop_event: str
    pause_conditions: tuple[dict[str, Any], ...]
    deadline_hours: float
    target_label: str
    regulatory_hours: float | None
    regulatory_reference: str | None
    typical_duration_hours: float
    escalation_sequence: tuple[EscalationStep, ...]
    responsible_team: str
    owner_role: str
    queue: str
    breach_action: dict[str, Any]
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SLARule":
        dl = data["deadline"]
        unit = dl.get("unit", "hours")
        if unit not in _UNIT_HOURS:
            raise ValueError(f"{data.get('sla_id')}: unknown deadline unit '{unit}'")
        return cls(
            sla_id=data["sla_id"],
            metric=data["metric"],
            title=data.get("title", data["metric"]),
            rule_version=str(data["rule_version"]),
            effective_from=_parse_dt(data["effective_from"]) or datetime.min.replace(tzinfo=timezone.utc),
            effective_to=_parse_dt(data.get("effective_to")),
            applicable_claim_types=tuple(data.get("applicable_claim_types", ["own_damage"])),
            trigger_event=data["trigger_event"],
            start_condition=dict(data.get("start_condition") or {}),
            stop_event=data["stop_event"],
            pause_conditions=tuple(data.get("pause_conditions", [])),
            deadline_hours=float(dl["value"]) * _UNIT_HOURS[unit],
            target_label=str(dl.get("target_label", "Configurable")),
            regulatory_hours=float(dl["regulatory_hours"]) if dl.get("regulatory_hours") is not None else None,
            regulatory_reference=dl.get("regulatory_reference"),
            typical_duration_hours=float(data.get("typical_duration_hours", dl["value"])),
            escalation_sequence=tuple(
                EscalationStep(
                    step=int(s["step"]),
                    at_pct=float(s["at_pct"]),
                    action=str(s["action"]),
                    to_team=str(s.get("to_team", data.get("responsible_team", ""))),
                )
                for s in data.get("escalation_sequence", [])
            ),
            responsible_team=data.get("responsible_team", ""),
            owner_role=data.get("owner_role", "claims_handler"),
            queue=data.get("queue", ""),
            breach_action=dict(data.get("breach_action", {})),
            raw=data,
        )

    def effective_at(self, when: datetime) -> bool:
        when = aware(when) or datetime.now(timezone.utc)
        if when < self.effective_from:
            return False
        return self.effective_to is None or when <= self.effective_to

    def applies_to(self, claim_type: str) -> bool:
        return claim_type in self.applicable_claim_types or "*" in self.applicable_claim_types

    def breach_penalty_inr(self) -> Decimal:
        return Decimal(str(self.breach_action.get("daily_penalty_inr", "0.00")))

    def to_public(self) -> dict[str, Any]:
        """Serializable rule definition for APIs, UIs and agents (single source of SLA truth)."""
        return {
            "sla_id": self.sla_id,
            "metric": self.metric,
            "title": self.title,
            "rule_version": self.rule_version,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "applicable_claim_types": list(self.applicable_claim_types),
            "trigger_event": self.trigger_event,
            "start_condition": self.start_condition,
            "stop_event": self.stop_event,
            "pause_conditions": list(self.pause_conditions),
            "deadline_hours": round(self.deadline_hours, 4),
            "target_label": self.target_label,
            "regulatory_hours": self.regulatory_hours,
            "regulatory_reference": self.regulatory_reference,
            "escalation_sequence": [
                {"step": s.step, "at_pct": s.at_pct, "action": s.action, "to_team": s.to_team}
                for s in self.escalation_sequence
            ],
            "responsible_team": self.responsible_team,
            "owner_role": self.owner_role,
            "queue": self.queue,
            "breach_action": self.breach_action,
        }


class SLARulesService:
    """Reads the active SLA catalogue and resolves which rule version governs a claim at a point in time."""

    def __init__(self, catalogue: dict[str, Any]) -> None:
        self.catalogue = catalogue
        self.rules: list[SLARule] = [SLARule.from_dict(r) for r in catalogue.get("rules", [])]
        self.risk_model: dict[str, Any] = dict(catalogue.get("risk_model", {}))
        self.guardrails: dict[str, Any] = dict(catalogue.get("agent_guardrails", {}))
        self.action_catalogue: dict[str, dict[str, Any]] = dict(catalogue.get("action_catalogue", {}))
        self.families: dict[str, list[str]] = dict(catalogue.get("claim_type_families", {}))

    def family(self, claim_type: str) -> str:
        """Map a stored claim_type (own_damage, cashless, reimbursement, third_party...) to its SLA family."""
        for fam, members in self.families.items():
            if claim_type in members or claim_type == fam:
                return fam
        return "own_damage"

    @classmethod
    def load(cls, db: Session | None = None) -> "SLARulesService":
        return cls(get_active_rule(db, SLA_CATALOGUE_ID))

    @property
    def catalogue_version(self) -> str:
        return f"{self.catalogue.get('rule_id', SLA_CATALOGUE_ID)}:{self.catalogue.get('version', '')}"

    def candidates(self, metric: str, claim_type: str) -> list[SLARule]:
        """All rule versions for a metric/claim type, newest rule_version first."""
        fam = self.family(claim_type)
        found = [r for r in self.rules if r.metric == metric and r.applies_to(fam)]
        return sorted(found, key=lambda r: parse_version(r.rule_version), reverse=True)

    def resolve(self, metric: str, claim_type: str, at: datetime) -> SLARule | None:
        """Pick the highest rule_version in force at ``at`` (the moment the SLA clock would start)."""
        for rule in self.candidates(metric, claim_type):
            if rule.effective_at(at):
                return rule
        return None

    def rules_for_claim_type(self, claim_type: str) -> list[SLARule]:
        fam = self.family(claim_type)
        return [r for r in self.rules if r.applies_to(fam)]

    def action_policy(self, action: str) -> dict[str, Any]:
        return self.action_catalogue.get(action, {})

    def band_for_probability(self, probability: float) -> str:
        t = self.risk_model.get("band_thresholds", {"watch": 0.35, "at_risk": 0.60, "critical": 0.85})
        if probability >= t["critical"]:
            return "critical"
        if probability >= t["at_risk"]:
            return "at_risk"
        if probability >= t["watch"]:
            return "watch"
        return "on_track"

    def validate(self) -> list[str]:
        return validate_catalogue(self.catalogue)

    def public_catalogue(self, *, at: datetime | None = None) -> dict[str, Any]:
        now = at or datetime.now(timezone.utc)
        return {
            "catalogue_id": self.catalogue.get("rule_id", SLA_CATALOGUE_ID),
            "catalogue_version": self.catalogue.get("version"),
            "owner": self.catalogue.get("owner"),
            "metrics": SLA_METRICS,
            "claim_type_families": self.families,
            "rules": [
                {**r.to_public(), "in_force": r.effective_at(now)}
                for r in sorted(self.rules, key=lambda x: (SLA_METRICS.index(x.metric), x.sla_id, parse_version(x.rule_version)))
            ],
            "action_catalogue": self.action_catalogue,
            "agent_guardrails": self.guardrails,
            "risk_model": self.risk_model,
            "validation_errors": self.validate(),
        }


def evaluate_condition(cond: dict[str, Any] | None, facts: dict[str, Any]) -> bool:
    """Tiny declarative predicate DSL: {"all":[...]}, {"any":[...]}, {"fact":..,"op":..,"value":..}."""
    if not cond:
        return True
    if "all" in cond:
        return all(evaluate_condition(c, facts) for c in cond["all"])
    if "any" in cond:
        items = cond["any"]
        return any(evaluate_condition(c, facts) for c in items) if items else True
    fact = cond["fact"]
    op = cond.get("op", "==")
    expected = cond.get("value")
    actual = facts.get(fact)
    if op == "==":
        return actual == expected
    if op == "!=":
        return actual != expected
    if op == "in":
        return actual in (expected or [])
    if op == "not_in":
        return actual not in (expected or [])
    if actual is None:
        return False
    if op == ">":
        return bool(actual > expected)
    if op == ">=":
        return bool(actual >= expected)
    if op == "<":
        return bool(actual < expected)
    if op == "<=":
        return bool(actual <= expected)
    raise ValueError(f"Unsupported SLA condition operator '{op}'")


def _walk_facts(cond: dict[str, Any] | None) -> list[str]:
    if not cond:
        return []
    if "all" in cond:
        return [f for c in cond["all"] for f in _walk_facts(c)]
    if "any" in cond:
        return [f for c in cond["any"] for f in _walk_facts(c)]
    return [cond["fact"]] if "fact" in cond else []


def validate_catalogue(catalogue: dict[str, Any]) -> list[str]:
    """Static checks so a mis-configured rule can be rejected before it governs live claims."""
    errors: list[str] = []
    actions = set(catalogue.get("action_catalogue", {}))
    seen_versions: dict[tuple[str, str, str], str] = {}
    covered: set[str] = set()
    for raw in catalogue.get("rules", []):
        sid = raw.get("sla_id", "?")
        try:
            rule = SLARule.from_dict(raw)
        except Exception as exc:  # noqa: BLE001 - surface any malformed rule as a validation error
            errors.append(f"{sid}: malformed rule ({exc})")
            continue
        covered.add(rule.metric)
        if rule.metric not in SLA_METRICS:
            errors.append(f"{sid}: unknown metric '{rule.metric}'")
        for ev_name in (rule.trigger_event, rule.stop_event):
            if ev_name not in KNOWN_EVENTS:
                errors.append(f"{sid}@{rule.rule_version}: unknown event '{ev_name}'")
        if rule.deadline_hours <= 0:
            errors.append(f"{sid}@{rule.rule_version}: deadline must be positive")
        for fact in _walk_facts(rule.start_condition):
            if fact not in KNOWN_FACTS:
                errors.append(f"{sid}@{rule.rule_version}: unknown start-condition fact '{fact}'")
        for pc in rule.pause_conditions:
            if pc.get("source") not in KNOWN_PAUSE_SOURCES:
                errors.append(f"{sid}@{rule.rule_version}: unknown pause source '{pc.get('source')}'")
        last_pct = -1.0
        for step in rule.escalation_sequence:
            if step.action not in actions:
                errors.append(f"{sid}@{rule.rule_version}: escalation action '{step.action}' not in action_catalogue")
            if step.at_pct <= last_pct:
                errors.append(f"{sid}@{rule.rule_version}: escalation steps must have ascending at_pct")
            last_pct = step.at_pct
        if rule.effective_to and rule.effective_to < rule.effective_from:
            errors.append(f"{sid}@{rule.rule_version}: effective_to precedes effective_from")
        for ct in rule.applicable_claim_types:
            key = (rule.metric, ct, rule.rule_version)
            if key in seen_versions and seen_versions[key] != sid:
                errors.append(f"{sid}: duplicate rule_version {rule.rule_version} for {rule.metric}/{ct} (also {seen_versions[key]})")
            seen_versions[key] = sid
    for metric in SLA_METRICS:
        if metric not in covered:
            errors.append(f"metric '{metric}' has no rule")
    return errors


def add_hours(start: datetime, hours: float) -> datetime:
    return start + timedelta(hours=hours)
