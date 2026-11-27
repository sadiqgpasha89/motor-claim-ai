"""Claim SLA context: bulk-loads everything the SLA clocks need and resolves rule events to timestamps.

Every resolved event carries its provenance: ``table`` (a real timestamp column), ``audit`` (immutable audit event)
or ``inferred`` (derived from claim status when no timestamp was recorded). Dashboards show that provenance so
operators can see how much of a clock rests on inferred data.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from services.claims.models import (
    Approval,
    AuditEvent,
    Claim,
    ClaimTask,
    EcosystemCoordination,
    Estimate,
    Evidence,
    Payment,
    Provider,
    Settlement,
    SurveyAssignment,
)
from services.claims.state_machine import LEGACY_TO_CANONICAL_STATE
from services.sla.rules import aware

UNVERIFIED_DOC_STATES = {"awaiting_verification", "extracted_unverified", "inconsistent", "quarantined"}
PAYMENT_DONE_STATES = {"confirmed", "reconciled", "settled", "completed", "paid"}
SURVEY_STATES = {"SURVEY_REQUIRED", "INVESTIGATION_REQUIRED"}
POST_ESTIMATE_STATES = {"SETTLEMENT_PENDING_APPROVAL", "APPROVED", "PAYMENT_PENDING", "PAYMENT_RECONCILIATION", "CLOSED"}
POST_REGISTRATION_EXCLUDED = {"SUBMITTED"}
AUDIT_ACTIONS = (
    "CLAIM_INTIMATED_REGISTERED",
    "CLAIM_TRIAGED",
    "COVERAGE_CHECK_COMPLETED",
    "EXTRACTED_FACT_VERIFIED",
    "APPROVAL_DECIDED",
    "PAYMENT_RECONCILED_SAFELY",
    "PAYMENT_INITIATED",
    "CLAIM_CLOSED",
)


@dataclass
class ClaimSLAContext:
    claim: Claim
    now: datetime
    assignments: list[SurveyAssignment] = field(default_factory=list)
    estimates: list[Estimate] = field(default_factory=list)
    settlements: list[Settlement] = field(default_factory=list)
    approvals: list[Approval] = field(default_factory=list)
    payments: list[Payment] = field(default_factory=list)
    coordination: EcosystemCoordination | None = None
    evidence: list[Evidence] = field(default_factory=list)
    tasks: list[ClaimTask] = field(default_factory=list)
    audit_first: dict[str, datetime] = field(default_factory=dict)
    audit_last: dict[str, datetime] = field(default_factory=dict)
    providers: dict[str, Provider] = field(default_factory=dict)

    @property
    def canonical_status(self) -> str:
        return LEGACY_TO_CANONICAL_STATE.get(self.claim.status, self.claim.status)

    @property
    def facts(self) -> dict[str, Any]:
        c = self.claim
        status = self.canonical_status
        survey_required = bool(self.assignments) or status in SURVEY_STATES or c.operational_path == "complex_investigation"
        return {
            "claim_type": c.claim_type,
            "claim_status": status,
            "risk_tier": c.risk_tier,
            "operational_path": c.operational_path,
            "evidence_count": len(self.evidence),
            "missing_document_count": len(c.missing_documents or []),
            "survey_required": survey_required,
            "garage_assigned": bool(self.coordination and self.coordination.garage_id),
            "ev_involved": bool(c.ev_battery_impacted),
        }


def load_contexts(db: Session, claims: list[Claim], now: datetime | None = None) -> dict[str, ClaimSLAContext]:
    """Bulk-load SLA contexts for many claims with one query per related table (no N+1)."""
    now = now or datetime.now(timezone.utc)
    if not claims:
        return {}
    ids = [c.id for c in claims]
    tenant_ids = {c.tenant_id for c in claims}

    def by_claim(model: Any) -> dict[str, list[Any]]:
        grouped: dict[str, list[Any]] = defaultdict(list)
        for row in db.query(model).filter(model.claim_id.in_(ids)).all():
            grouped[row.claim_id].append(row)
        return grouped

    assignments = by_claim(SurveyAssignment)
    estimates = by_claim(Estimate)
    settlements = by_claim(Settlement)
    approvals = by_claim(Approval)
    payments = by_claim(Payment)
    evidence = by_claim(Evidence)
    tasks = by_claim(ClaimTask)
    coordinations = {row.claim_id: row for row in db.query(EcosystemCoordination).filter(EcosystemCoordination.claim_id.in_(ids)).all()}
    providers = {p.id: p for p in db.query(Provider).filter(Provider.tenant_id.in_(tenant_ids)).all()}

    audit_first: dict[str, dict[str, datetime]] = defaultdict(dict)
    audit_last: dict[str, dict[str, datetime]] = defaultdict(dict)
    for ev in db.query(AuditEvent).filter(AuditEvent.claim_id.in_(ids), AuditEvent.action.in_(AUDIT_ACTIONS)).all():
        ts = aware(ev.created_at)
        if ts is None or ev.claim_id is None:
            continue
        first = audit_first[ev.claim_id].get(ev.action)
        last = audit_last[ev.claim_id].get(ev.action)
        if first is None or ts < first:
            audit_first[ev.claim_id][ev.action] = ts
        if last is None or ts > last:
            audit_last[ev.claim_id][ev.action] = ts

    return {
        c.id: ClaimSLAContext(
            claim=c,
            now=now,
            assignments=sorted(assignments.get(c.id, []), key=lambda a: aware(a.assigned_at) or now),
            estimates=sorted(estimates.get(c.id, []), key=lambda e: aware(e.created_at) or now),
            settlements=sorted(settlements.get(c.id, []), key=lambda s: aware(s.created_at) or now),
            approvals=approvals.get(c.id, []),
            payments=sorted(payments.get(c.id, []), key=lambda p: aware(p.created_at) or now),
            coordination=coordinations.get(c.id),
            evidence=evidence.get(c.id, []),
            tasks=tasks.get(c.id, []),
            audit_first=audit_first.get(c.id, {}),
            audit_last=audit_last.get(c.id, {}),
            providers=providers,
        )
        for c in claims
    }


def load_context(db: Session, claim: Claim, now: datetime | None = None) -> ClaimSLAContext:
    return load_contexts(db, [claim], now)[claim.id]


# ---------------------------------------------------------------------------------------------------------------------
# Event resolvers: (context) -> (timestamp | None, provenance)
# ---------------------------------------------------------------------------------------------------------------------
EventResult = tuple[datetime | None, str]


def _ev_claim_intimated(ctx: ClaimSLAContext) -> EventResult:
    return aware(ctx.claim.created_at), "table"


def _ev_claim_registered(ctx: ClaimSLAContext) -> EventResult:
    ts = ctx.audit_first.get("CLAIM_INTIMATED_REGISTERED")
    if ts:
        return ts, "audit"
    if ctx.canonical_status not in POST_REGISTRATION_EXCLUDED:
        return aware(ctx.claim.created_at), "inferred"
    return None, "pending"


def _ev_documents_verified(ctx: ClaimSLAContext) -> EventResult:
    if ctx.claim.missing_documents:
        return None, "pending"
    if any(e.doc_status in UNVERIFIED_DOC_STATES for e in ctx.evidence):
        return None, "pending"
    if not ctx.evidence:
        return None, "pending"
    for action in ("EXTRACTED_FACT_VERIFIED", "COVERAGE_CHECK_COMPLETED"):
        ts = ctx.audit_last.get(action)
        if ts:
            return ts, "audit"
    latest = max((ts for e in ctx.evidence if e.created_at and (ts := aware(e.created_at)) is not None), default=None)
    return latest, "inferred"


def _ev_claim_triaged(ctx: ClaimSLAContext) -> EventResult:
    ts = ctx.audit_first.get("CLAIM_TRIAGED")
    if ts:
        return ts, "audit"
    if ctx.claim.triage_summary:
        return aware(ctx.claim.created_at), "inferred"
    return None, "pending"


def _ev_surveyor_assigned(ctx: ClaimSLAContext) -> EventResult:
    if ctx.assignments:
        return aware(ctx.assignments[0].assigned_at), "table"
    return None, "pending"


def _ev_survey_report_received(ctx: ClaimSLAContext) -> EventResult:
    received = [aware(a.report_received_at) for a in ctx.assignments if a.report_received_at]
    if received:
        return min(received), "table"  # type: ignore[type-var]
    return None, "pending"


def _ev_estimate_submitted(ctx: ClaimSLAContext) -> EventResult:
    base = [e for e in ctx.estimates if not e.is_supplement] or ctx.estimates
    if base:
        return aware(base[0].created_at), "table"
    return None, "pending"


def _ev_estimate_approved(ctx: ClaimSLAContext) -> EventResult:
    if ctx.settlements:
        return aware(ctx.settlements[0].created_at), "inferred"
    if ctx.canonical_status in POST_ESTIMATE_STATES:
        return aware(ctx.claim.updated_at), "inferred"
    return None, "pending"


def _ev_repair_completed(ctx: ClaimSLAContext) -> EventResult:
    co = ctx.coordination
    if co and co.repair_completion_confirmed and co.repair_confirmed_at:
        return aware(co.repair_confirmed_at), "table"
    return None, "pending"


def _ev_settlement_approved(ctx: ClaimSLAContext) -> EventResult:
    decided = [aware(a.decided_at) for a in ctx.approvals if a.decision == "approved" and a.decided_at]
    if decided:
        return max(decided), "table"  # type: ignore[type-var]
    ts = ctx.audit_last.get("APPROVAL_DECIDED")
    if ts and any(s.approval_status == "approved" for s in ctx.settlements):
        return ts, "audit"
    return None, "pending"


def _ev_payment_completed(ctx: ClaimSLAContext) -> EventResult:
    done = [p for p in ctx.payments if p.status in PAYMENT_DONE_STATES]
    if not done:
        return None, "pending"
    ts = ctx.audit_last.get("PAYMENT_RECONCILED_SAFELY")
    if ts:
        return ts, "audit"
    return aware(done[-1].created_at), "inferred"


def _ev_claim_closed(ctx: ClaimSLAContext) -> EventResult:
    ts = ctx.audit_last.get("CLAIM_CLOSED")
    if ts and ctx.canonical_status == "CLOSED":
        return ts, "audit"
    if ctx.canonical_status == "CLOSED":
        return aware(ctx.claim.updated_at), "inferred"
    return None, "pending"


EVENT_RESOLVERS: dict[str, Callable[[ClaimSLAContext], EventResult]] = {
    "ClaimIntimated": _ev_claim_intimated,
    "ClaimRegistered": _ev_claim_registered,
    "DocumentsVerified": _ev_documents_verified,
    "ClaimTriaged": _ev_claim_triaged,
    "SurveyorAssigned": _ev_surveyor_assigned,
    "SurveyReportReceived": _ev_survey_report_received,
    "EstimateSubmitted": _ev_estimate_submitted,
    "EstimateApproved": _ev_estimate_approved,
    "RepairCompleted": _ev_repair_completed,
    "SettlementApproved": _ev_settlement_approved,
    "PaymentCompleted": _ev_payment_completed,
    "ClaimClosed": _ev_claim_closed,
}


def resolve_event(ctx: ClaimSLAContext, event: str) -> EventResult:
    resolver = EVENT_RESOLVERS.get(event)
    if resolver is None:
        raise KeyError(f"No resolver registered for SLA event '{event}'")
    return resolver(ctx)
