"""Explainable breach predictor (model ``sla-risk-baseline-v1``).

For each open SLA clock it estimates how much work is still expected (typical duration scaled by observable risk
factors) and compares that to the remaining SLA budget under a normal uncertainty band. Every probability ships with
the drivers that moved it, so operators and agents can act on causes, not scores. The model contract is intentionally
narrow (instance + signals -> prediction) so a trained model can replace it without touching callers.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from services.claims.models import Communication, Provider
from services.sla.engine import SLAInstance
from services.sla.events import UNVERIFIED_DOC_STATES, ClaimSLAContext
from services.sla.rules import SLARulesService, aware

MODEL_ID = "sla-risk-baseline-v1"
SURVEY_METRICS = {"surveyor_assignment", "survey_completion"}
SPECIALIST_METRICS = {"surveyor_assignment", "survey_completion", "repair_completion"}
PARTS_PENDING_STATES = {"awaiting_parts", "ordered", "backordered", "partial", "unavailable"}


@dataclass
class ClaimSignals:
    """Minimised, PII-free operational signals feeding the predictor and the agent."""

    claim_id: str
    claim_number: str
    claim_type: str
    queue: str
    risk_tier: str
    ev_involved: bool
    surveyor: dict[str, Any] | None = None  # id, name, city, load_ratio, avg_turnaround_hours, target_hours
    garage: dict[str, Any] | None = None  # same shape + customer_chosen, parts_lead_time_days
    reschedule_count: int = 0
    followup_count: int = 0
    hours_since_last_followup: float | None = None
    inspection_scheduled: bool | None = None
    inspection_in_hours: float | None = None
    missing_documents: list[str] = field(default_factory=list)
    unverified_documents: list[str] = field(default_factory=list)
    oldest_doc_request_age_hours: float | None = None
    hours_since_last_doc_request: float | None = None
    parts_status: str | None = None
    repair_status: str | None = None
    queue_pressure: float = 0.0
    reassign_candidates: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # kind -> candidates

    def owner_for(self, metric: str) -> tuple[str | None, dict[str, Any] | None]:
        """The external party whose capacity drives this metric (surveyor for survey clocks, garage for repair)."""
        if metric in SURVEY_METRICS:
            return ("surveyor", self.surveyor) if self.surveyor else (None, None)
        if metric == "repair_completion":
            return ("garage", self.garage) if self.garage else (None, None)
        return None, None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClaimSignals":
        return cls(**data)


@dataclass
class SLAPrediction:
    claim_id: str
    claim_number: str
    sla_id: str
    metric: str
    rule_version: str
    model_id: str
    breach_probability: float
    risk_band: str  # on_track | watch | at_risk | critical | breached
    expected_remaining_hours: float
    remaining_budget_hours: float
    projected_overrun_hours: float
    projected_consumed_pct: float
    expected_completion_at: str
    due_at: str
    drivers: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _hours_between(later: datetime, earlier: datetime | None) -> float | None:
    if earlier is None:
        return None
    return round((later - earlier).total_seconds() / 3600.0, 2)


def _provider_view(p: Provider | None) -> dict[str, Any] | None:
    if p is None:
        return None
    return {
        "id": p.id,
        "name": p.name,
        "city": p.city,
        "load_ratio": round(float(p.active_load or 0) / max(int(p.max_capacity or 1), 1), 3),
        "avg_turnaround_hours": float(p.avg_turnaround_hours or 0),
        "target_hours": float(p.sla_target_hours or 0),
        "parts_lead_time_days": int(p.parts_lead_time_days or 0),
        "customer_chosen": False,
    }


def build_signals(ctx: ClaimSLAContext, last_doc_request: dict[str, datetime] | None = None) -> ClaimSignals:
    """Derive operational signals from the claim context (owner load, reschedules, documents, parts)."""
    c = ctx.claim
    co = ctx.coordination
    now = ctx.now
    latest_assignment = ctx.assignments[-1] if ctx.assignments else None

    surveyor_id = latest_assignment.surveyor_id if latest_assignment else (co.surveyor_id if co else None)
    garage_id = co.garage_id if co else None
    sig = ClaimSignals(
        claim_id=c.id,
        claim_number=c.claim_number,
        claim_type=c.claim_type,
        queue=c.queue_name,
        risk_tier=c.risk_tier,
        ev_involved=bool(c.ev_battery_impacted),
        surveyor=_provider_view(ctx.providers.get(surveyor_id)) if surveyor_id else None,
        garage=_provider_view(ctx.providers.get(garage_id)) if garage_id else None,
        missing_documents=list(c.missing_documents or []),
        unverified_documents=sorted({e.doc_type for e in ctx.evidence if e.doc_status in UNVERIFIED_DOC_STATES}),
    )
    if latest_assignment is not None:
        sig.reschedule_count = int(latest_assignment.reschedule_count or 0)
        sig.followup_count = int(latest_assignment.followup_count or 0)
        sig.hours_since_last_followup = _hours_between(now, aware(latest_assignment.last_followup_at))
        appt = aware(latest_assignment.appointment_at)
        sig.inspection_scheduled = appt is not None
        sig.inspection_in_hours = round((appt - now).total_seconds() / 3600.0, 2) if appt else None
    if co is not None:
        sig.reschedule_count = max(sig.reschedule_count, int(co.inspection_reschedule_count or 0))
        sig.followup_count = max(sig.followup_count, int(co.surveyor_followup_count or 0))
        sig.parts_status = co.parts_status
        sig.repair_status = co.repair_status
        if sig.garage is not None:
            sig.garage["customer_chosen"] = bool(
                co.customer_preferred_garage_id and co.customer_preference_honoured and co.customer_preferred_garage_id == co.garage_id
            )

    open_doc_tasks = [t for t in ctx.tasks if t.task_type == "document_request" and t.status in {"open", "in_progress"} and t.created_at]
    if open_doc_tasks:
        oldest = min(aware(t.created_at) for t in open_doc_tasks)  # type: ignore[type-var]
        sig.oldest_doc_request_age_hours = _hours_between(now, oldest)
    if last_doc_request and c.id in last_doc_request:
        sig.hours_since_last_doc_request = _hours_between(now, last_doc_request[c.id])
    return sig


def latest_doc_request_times(db: Any, claim_ids: list[str]) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    if not claim_ids:
        return out
    for comm in db.query(Communication).filter(Communication.claim_id.in_(claim_ids), Communication.template_id == "DOCUMENT_REQUEST").all():
        ts = aware(comm.created_at)
        if ts and (comm.claim_id not in out or ts > out[comm.claim_id]):
            out[comm.claim_id] = ts
    return out


def predict_instance(inst: SLAInstance, sig: ClaimSignals, rules: SLARulesService, now: datetime | None = None) -> SLAPrediction | None:
    """Return a breach prediction for an open SLA clock (None for completed clocks)."""
    if not inst.is_open:
        return None
    rm = rules.risk_model
    now = now or datetime.now(timezone.utc)
    drivers: list[dict[str, Any]] = []
    mult = 1.0
    typical = max(inst.typical_duration_hours, 0.01)

    def add(code: str, label: str, factor: float | None = None, hours: float | None = None, evidence: str = "") -> None:
        drivers.append(
            {
                "code": code,
                "label": label,
                "factor": round(factor, 3) if factor is not None else None,
                "hours": round(hours, 2) if hours is not None else None,
                "evidence": evidence,
            }
        )

    # --- Owner capacity (surveyor / garage): the strongest operational lever ----------------------------------------
    owner_kind, owner = sig.owner_for(inst.metric)
    if owner:
        ratio = owner["load_ratio"]
        for band in sorted(rm.get("load_factors", []), key=lambda f: -f["min_ratio"]):
            if ratio >= band["min_ratio"]:
                mult *= band["multiplier"]
                add("OWNER_OVERLOADED", f"{owner_kind} at {ratio:.0%} of capacity", factor=band["multiplier"], evidence=owner["name"])
                break
        if owner["avg_turnaround_hours"] and owner["target_hours"]:
            slow = owner["avg_turnaround_hours"] / max(owner["target_hours"], 1.0)
            if slow > 1.0:
                m = min(slow, 1.5)
                mult *= m
                add("SLOW_OWNER", f"Average turnaround {owner['avg_turnaround_hours']:.0f}h vs {owner['target_hours']:.0f}h target", factor=m, evidence=owner["name"])

    # --- Rework signals -------------------------------------------------------------------------------------------------
    if sig.reschedule_count:
        m = min(1.0 + rm.get("reschedule_step", 0.12) * sig.reschedule_count, rm.get("reschedule_cap", 1.5))
        mult *= m
        add("RESCHEDULES", f"{sig.reschedule_count} inspection reschedule(s)", factor=m)
    if sig.followup_count and inst.metric in SURVEY_METRICS:
        m = min(1.0 + rm.get("followup_step", 0.08) * sig.followup_count, rm.get("followup_cap", 1.4))
        mult *= m
        add("UNANSWERED_FOLLOWUPS", f"{sig.followup_count} follow-up(s) without a report", factor=m)

    # --- Claim complexity -----------------------------------------------------------------------------------------------
    tier_m = rm.get("risk_tier_multipliers", {}).get(sig.risk_tier, 1.0)
    if tier_m > 1.0:
        mult *= tier_m
        add("CLAIM_COMPLEXITY", f"{sig.risk_tier} risk-tier handling path", factor=tier_m)
    if sig.ev_involved and inst.metric in SPECIALIST_METRICS:
        mult *= rm.get("ev_multiplier", 1.15)
        add("EV_SPECIALIST_SCARCITY", "EV high-voltage work needs scarce certified capacity", factor=rm.get("ev_multiplier", 1.15))

    # --- Queue pressure --------------------------------------------------------------------------------------------------
    if sig.queue_pressure > 0:
        m = 1.0 + rm.get("queue_pressure_weight", 0.4) * sig.queue_pressure
        mult *= m
        if sig.queue_pressure >= 0.3:
            add("QUEUE_PRESSURE", f"Queue '{inst.queue}' pressure {sig.queue_pressure:.0%}", factor=m)

    expected_total = typical * mult
    # Residual work: the unspent part of the expected duration, but never optimistic once a clock has outrun its
    # typical duration. Work that is already late tends to run later still (heavy-tailed durations), so the floor
    # grows with how far past "typical" the clock already is.
    overrun_so_far = max(inst.active_elapsed_hours - expected_total, 0.0)
    expected_remaining = max(expected_total - inst.active_elapsed_hours, 0.35 * expected_total + 0.25 * overrun_so_far, 0.05)

    # --- Additive delays --------------------------------------------------------------------------------------------------
    if inst.metric == "survey_completion":
        if sig.inspection_scheduled is False and inst.consumed_pct >= 25:
            expected_remaining += 24.0
            add("NO_INSPECTION_SLOT", "No inspection appointment booked yet", hours=24.0)
        elif sig.inspection_in_hours is not None and sig.inspection_in_hours > 0:
            floor = sig.inspection_in_hours + 0.3 * typical
            if floor > expected_remaining:
                add("INSPECTION_LATE_SLOT", f"Inspection only in {sig.inspection_in_hours:.0f}h", hours=floor - expected_remaining)
                expected_remaining = floor
    lead_days = int((sig.garage or {}).get("parts_lead_time_days") or 0)
    if inst.metric == "repair_completion" and sig.parts_status in PARTS_PENDING_STATES and lead_days > 0:
        extra = float(lead_days) * 24.0
        expected_remaining += extra
        add("PARTS_DELAY", f"Parts status '{sig.parts_status}', {lead_days}d lead time", hours=extra)
    if sig.missing_documents and inst.metric != "document_verification" and "AWAITING_CUSTOMER_DOCUMENTS" not in inst.pause_codes_configured:
        typical_wait = float(rm.get("typical_customer_response_hours", 36))
        age = sig.oldest_doc_request_age_hours or 0.0
        wait = max(typical_wait - age, 0.25 * typical_wait)
        expected_remaining += wait
        add("DOCUMENTS_OUTSTANDING", f"{len(sig.missing_documents)} document(s) still owed: {', '.join(sig.missing_documents[:3])}", hours=wait)
    if inst.status == "paused" and inst.pause_codes_active:
        typical_wait = float(rm.get("typical_customer_response_hours", 36))
        age = sig.oldest_doc_request_age_hours or 0.0
        add("CLOCK_PAUSED", f"Clock paused ({', '.join(inst.pause_codes_active)}); resumes after the customer responds", hours=max(typical_wait - age, 0.0))

    if inst.status == "breached":
        add("SLA_ALREADY_BREACHED", f"SLA exceeded by {max(-inst.remaining_hours, 0.0):.1f}h", hours=max(-inst.remaining_hours, 0.0))

    sigma = rm.get("uncertainty_pct_of_expected", 0.30) * expected_remaining + rm.get("uncertainty_floor_hours", 0.5)
    budget = inst.remaining_hours
    if inst.status == "breached" or budget <= 0:
        probability = 1.0
        band = "breached"
    else:
        probability = round(max(0.0, min(1.0, 1.0 - _phi((budget - expected_remaining) / sigma))), 4)
        band = rules.band_for_probability(probability)
    overrun = max(expected_remaining - max(budget, 0.0), 0.0)
    projected_pct = (inst.active_elapsed_hours + expected_remaining) / max(inst.deadline_hours, 1e-6) * 100.0
    completion = now + timedelta(hours=expected_remaining)
    drivers.sort(key=lambda d: -(abs((d["factor"] or 1.0) - 1.0) * 100 + (d["hours"] or 0.0) / 4.0))
    return SLAPrediction(
        claim_id=inst.claim_id,
        claim_number=inst.claim_number,
        sla_id=inst.sla_id,
        metric=inst.metric,
        rule_version=inst.rule_version,
        model_id=MODEL_ID,
        breach_probability=probability,
        risk_band=band,
        expected_remaining_hours=round(expected_remaining, 2),
        remaining_budget_hours=round(budget, 2),
        projected_overrun_hours=round(overrun, 2),
        projected_consumed_pct=round(projected_pct, 1),
        expected_completion_at=completion.isoformat(),
        due_at=inst.due_at,
        drivers=drivers,
    )
