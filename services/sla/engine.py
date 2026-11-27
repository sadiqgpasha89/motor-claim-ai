"""SLA clock engine: turns (rule + claim events) into live SLA instances with pause-aware elapsed time.

Pure functions over ``ClaimSLAContext``; no writes. The legacy ``SLATimer`` table and ``sweep_sla_breaches``
keep owning breach tasks; this engine adds rule-driven, claim-type-aware clocks for all eight SLA metrics.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from services.sla.events import ClaimSLAContext, resolve_event
from services.sla.rules import SLA_METRICS, SLARule, SLARulesService, aware, evaluate_condition

OPEN_STATUSES = {"running", "paused", "breached"}


@dataclass
class SLAInstance:
    claim_id: str
    claim_number: str
    claim_type: str
    queue: str
    sla_id: str
    metric: str
    title: str
    rule_version: str
    trigger_event: str
    stop_event: str
    started_at: str
    stopped_at: str | None
    due_at: str
    deadline_hours: float
    target_label: str
    regulatory_hours: float | None
    regulatory_due_at: str | None
    typical_duration_hours: float
    status: str  # running | paused | breached | met | met_late
    active_elapsed_hours: float
    paused_hours: float
    consumed_pct: float
    remaining_hours: float
    pause_codes_active: list[str] = field(default_factory=list)
    pause_codes_configured: list[str] = field(default_factory=list)
    responsible_team: str = ""
    owner_role: str = ""
    escalation_sequence: list[dict[str, Any]] = field(default_factory=list)
    escalation_due: dict[str, Any] | None = None
    breach_action: dict[str, Any] = field(default_factory=dict)
    penalty_accrued_inr: str = "0.00"
    event_sources: dict[str, str] = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SLAInstance":
        return cls(**data)


def _merge_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for s, e in sorted(intervals):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def pause_intervals(rule: SLARule, ctx: ClaimSLAContext, start: datetime, end: datetime) -> tuple[list[tuple[datetime, datetime]], list[str]]:
    """Derive pause windows from the rule's declarative pause conditions.

    ``task`` sources use ClaimTask lifecycle (created -> completed/now); ``claim_status`` sources can only see the
    *current* status, so they pause from the claim's last update (an approximation that is reported, not hidden).
    """
    raw: list[tuple[datetime, datetime]] = []
    active: list[str] = []
    for pc in rule.pause_conditions:
        code = pc.get("code", "PAUSED")
        if pc.get("source") == "task":
            open_states = set(pc.get("task_statuses", ["open", "in_progress"]))
            for task in ctx.tasks:
                if task.task_type not in pc.get("task_types", []):
                    continue
                t_start = aware(task.created_at)
                if t_start is None:
                    continue
                if task.status in open_states:
                    raw.append((t_start, ctx.now))
                    if code not in active:
                        active.append(code)
                elif task.completed_at:
                    raw.append((t_start, aware(task.completed_at)))  # type: ignore[arg-type]
        elif pc.get("source") == "claim_status":
            statuses = set(pc.get("statuses", []))
            if ctx.claim.status in statuses or ctx.canonical_status in statuses:
                since = aware(ctx.claim.updated_at) or ctx.now
                raw.append((since, ctx.now))
                if code not in active:
                    active.append(code)
    clipped = [(max(s, start), min(e, end)) for s, e in raw if min(e, end) > max(s, start)]
    return _merge_intervals(clipped), active


def build_instance(rule: SLARule, ctx: ClaimSLAContext, start: datetime, start_source: str) -> SLAInstance:
    stop, stop_source = resolve_event(ctx, rule.stop_event)
    if stop is not None and stop < start:
        stop = start
    end = stop or ctx.now
    intervals, active_codes = pause_intervals(rule, ctx, start, end)
    paused_hours = sum((e - s).total_seconds() for s, e in intervals) / 3600.0
    elapsed = max((end - start).total_seconds() / 3600.0 - paused_hours, 0.0)
    deadline = rule.deadline_hours
    due_at = start + timedelta(hours=deadline + paused_hours)
    consumed = elapsed / deadline * 100.0 if deadline else 0.0

    if stop is not None:
        status = "met" if elapsed <= deadline + 1e-9 else "met_late"
    elif active_codes:
        status = "paused" if elapsed <= deadline else "breached"
        if status == "paused":
            consumed = min(consumed, 100.0)
    elif elapsed > deadline:
        status = "breached"
    else:
        status = "running"

    escalation_due: dict[str, Any] | None = None
    if status in {"running", "breached"}:
        due_steps = [s for s in rule.escalation_sequence if s.at_pct <= consumed]
        if due_steps:
            top = due_steps[-1]
            escalation_due = {"step": top.step, "at_pct": top.at_pct, "action": top.action, "to_team": top.to_team}

    penalty = rule.breach_penalty_inr()
    accrued = "0.00"
    if penalty > 0 and stop is None:
        basis = rule.regulatory_hours or deadline
        over = elapsed - basis
        if over > 0:
            accrued = str((penalty * math.ceil(over / 24.0)).quantize(penalty))

    reg_due = start + timedelta(hours=rule.regulatory_hours) if rule.regulatory_hours else None
    c = ctx.claim
    return SLAInstance(
        claim_id=c.id,
        claim_number=c.claim_number,
        claim_type=c.claim_type,
        queue=c.queue_name or rule.queue,
        sla_id=rule.sla_id,
        metric=rule.metric,
        title=rule.title,
        rule_version=rule.rule_version,
        trigger_event=rule.trigger_event,
        stop_event=rule.stop_event,
        started_at=start.isoformat(),
        stopped_at=stop.isoformat() if stop else None,
        due_at=due_at.isoformat(),
        deadline_hours=round(deadline, 4),
        target_label=rule.target_label,
        regulatory_hours=rule.regulatory_hours,
        regulatory_due_at=reg_due.isoformat() if reg_due else None,
        typical_duration_hours=rule.typical_duration_hours,
        status=status,
        active_elapsed_hours=round(elapsed, 4),
        paused_hours=round(paused_hours, 4),
        consumed_pct=round(consumed, 2),
        remaining_hours=round(deadline - elapsed, 4),
        pause_codes_active=active_codes,
        pause_codes_configured=[pc.get("code", "") for pc in rule.pause_conditions],
        responsible_team=rule.responsible_team,
        owner_role=rule.owner_role,
        escalation_sequence=[
            {"step": s.step, "at_pct": s.at_pct, "action": s.action, "to_team": s.to_team} for s in rule.escalation_sequence
        ],
        escalation_due=escalation_due,
        breach_action=rule.breach_action,
        penalty_accrued_inr=accrued,
        event_sources={"start": start_source, "stop": stop_source},
    )


def build_claim_instances(ctx: ClaimSLAContext, rules: SLARulesService) -> list[SLAInstance]:
    """Instantiate every applicable SLA clock whose trigger event has occurred and whose start condition holds."""
    facts = ctx.facts
    instances: list[SLAInstance] = []
    for metric in SLA_METRICS:
        for rule in rules.candidates(metric, ctx.claim.claim_type):
            start, start_source = resolve_event(ctx, rule.trigger_event)
            if start is None:
                continue
            if not rule.effective_at(start):
                continue  # an older/newer rule version governs a claim that started in another window
            if not evaluate_condition(rule.start_condition, facts):
                continue
            instances.append(build_instance(rule, ctx, start, start_source))
            break
    return instances
