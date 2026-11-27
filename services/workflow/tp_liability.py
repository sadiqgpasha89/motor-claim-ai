"""Third-Party (TP) liability workflow.

Own Damage (OD) and Third-Party (TP) claims are different products with different risks:

* OD is a first-party repair/replacement claim. Its settlement is deterministic arithmetic over an
  estimate (depreciation, deductibles, salvage), so LOW-risk claims may be auto-approved within a limit.
* TP is a legal-liability claim by someone who is not the insured (bodily injury, fatality, property damage).
  The amount is not arithmetic: it depends on fault, evidence, medical opinion, tribunal practice and legal
  strategy. A wrong autonomous decision is a legal and reputational event, not a repair-cost error.

This module therefore implements a distinct lifecycle (``TPStage``), dedicated task queues, legal and medical
document controls, a reserve discipline, dual-control settlement approval and an explicit prohibition on
autonomous settlement. AI output in this module is advisory only and can never advance a stage, determine
liability, approve a settlement or release a payment (``IN-TP-LIABILITY-2026``).

All data is DEMO / SYNTHETIC. Statutory references and limits in the rule file require legal sign-off
before production use.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import Enum
from typing import Any, Optional

from sqlalchemy.orm import Session

from packages.contracts.errors import DomainError, ErrorCode
from packages.security.auth import Role, UserContext
from packages.security.sanitizer import sanitize_untrusted_text
from services.claims.audit import emit_outbox_event, record_audit_event
from services.claims.models import Claim, ClaimTask, Policy, TPClaimCase
from services.claims.state_machine import ClaimStatus, validate_transition
from services.integrations.adapters import IntegrationAdapterRegistry
from services.rules_engine.loader import get_active_rule
from services.workflow.risk_engine import assert_fraud_score_never_rejects

TP_RULE_ID = "IN-TP-LIABILITY-2026"
TP_PERILS = {"tp_bodily_injury", "tp_fatality", "tp_property_damage"}
TP_CATEGORIES = ("property_damage", "bodily_injury", "fatality")
INJURY_SEVERITIES = ("minor", "moderate", "grievous", "permanent_disability", "fatality")
POLICY_DEFENCES = (
    "no_valid_driving_licence",
    "drunk_driving",
    "unauthorised_use",
    "vehicle_not_roadworthy",
    "passenger_for_hire_breach",
    "policy_lapsed_at_incident",
    "other",
)
EVIDENCE_KINDS = ("photo", "video_cctv", "dashcam", "witness_statement", "spot_panchnama", "site_sketch", "medical", "other")
LEGAL_DOC_STATUSES = ("requested", "received", "verified", "rejected")
TP_PARTY_ROLES = ("injured", "deceased", "legal_heir", "property_owner", "claimant")

ROLES_INTAKE = {Role.FNOL_EXECUTIVE, Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.LEGAL_TP, Role.ADMIN}
ROLES_HANDLING = {Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.LEGAL_TP, Role.ADMIN}
ROLES_LEGAL = {Role.LEGAL_TP, Role.ADMIN}
ROLES_APPROVER = {Role.CLAIMS_MANAGER, Role.LEGAL_TP, Role.ADMIN}
ROLES_FINANCE = {Role.FINANCE_APPROVER, Role.ADMIN}
ROLES_MEDICAL_VIEW = {Role.LEGAL_TP, Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.AUDITOR, Role.ADMIN}


class TPStage(str, Enum):
    INTAKE = "INTAKE"
    EVIDENCE_AND_FACTS = "EVIDENCE_AND_FACTS"
    POLICE_FIR = "POLICE_FIR"
    LIABILITY_INVESTIGATION = "LIABILITY_INVESTIGATION"
    LEGAL_DOCUMENTATION = "LEGAL_DOCUMENTATION"
    ADVOCATE_COORDINATION = "ADVOCATE_COORDINATION"
    MEDICAL_REVIEW = "MEDICAL_REVIEW"
    LEGAL_SPECIALIST_REVIEW = "LEGAL_SPECIALIST_REVIEW"
    SETTLEMENT_CONTROL = "SETTLEMENT_CONTROL"
    SETTLEMENT_APPROVED = "SETTLEMENT_APPROVED"
    PAYMENT_AUTHORISED = "PAYMENT_AUTHORISED"
    CLOSED = "CLOSED"


STAGE_ORDER: list[str] = [s.value for s in TPStage]

# Stages that a human advances with the explicit /advance action once the gate is clear.
# Later stages are advanced only by their own controlled action (approval, payment authorisation, closure).
ADVANCE_ACTION_STAGES = set(STAGE_ORDER[: STAGE_ORDER.index(TPStage.LEGAL_SPECIALIST_REVIEW.value) + 1])

STAGE_TO_CLAIM_STATUS: dict[str, ClaimStatus] = {
    TPStage.INTAKE.value: ClaimStatus.HUMAN_REVIEW,
    TPStage.EVIDENCE_AND_FACTS.value: ClaimStatus.HUMAN_REVIEW,
    TPStage.POLICE_FIR.value: ClaimStatus.HUMAN_REVIEW,
    TPStage.LIABILITY_INVESTIGATION.value: ClaimStatus.HUMAN_REVIEW,
    TPStage.LEGAL_DOCUMENTATION.value: ClaimStatus.HUMAN_REVIEW,
    TPStage.ADVOCATE_COORDINATION.value: ClaimStatus.HUMAN_REVIEW,
    TPStage.MEDICAL_REVIEW.value: ClaimStatus.HUMAN_REVIEW,
    TPStage.LEGAL_SPECIALIST_REVIEW.value: ClaimStatus.HUMAN_REVIEW,
    TPStage.SETTLEMENT_CONTROL.value: ClaimStatus.SETTLEMENT_PENDING_APPROVAL,
    TPStage.SETTLEMENT_APPROVED.value: ClaimStatus.APPROVED,
    TPStage.PAYMENT_AUTHORISED.value: ClaimStatus.PAYMENT_PENDING,
    TPStage.CLOSED.value: ClaimStatus.CLOSED,
}


# ----------------------------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> Optional[str]:
    return dt.isoformat() if dt else None


def _money(value: Any, *, field: str = "amount_inr") -> Decimal:
    try:
        d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise DomainError(ErrorCode.VALIDATION_ERROR, f"'{field}' must be a valid INR amount", status_code=400) from exc
    return d


def _clean(text: str | None, *, max_len: int = 2000) -> str:
    cleaned, _, _ = sanitize_untrusted_text((text or "").strip())
    return cleaned[:max_len]


def _mask_contact(raw: str | None) -> str:
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if len(digits) >= 4:
        return "******" + digits[-4:]
    return "******" if digits else ""


def _actor(user: UserContext) -> dict[str, str]:
    return {"user_id": user.user_id, "name": user.name, "role": user.role.value}


def _require_role(user: UserContext, allowed: set[Role], action: str) -> None:
    if user.role not in allowed:
        raise DomainError(
            ErrorCode.NOT_AUTHORISED,
            f"Role '{user.role.value}' is not permitted to {action} on a Third-Party claim",
            status_code=403,
        )


def tp_rule(db: Session | None) -> dict[str, Any]:
    return get_active_rule(db, TP_RULE_ID)


def claim_requires_tp_workflow(claim: Claim) -> bool:
    """True when a claim must use the TP lifecycle and never the OD settlement/auto-approval path."""
    return claim.claim_type == "third_party" or (claim.peril_cause or "") in TP_PERILS


def assert_not_tp_for_od_path(claim: Claim, *, operation: str) -> None:
    """Guard placed on every OD-only settlement, approval, payment and closure path."""
    if claim_requires_tp_workflow(claim):
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            (
                f"'{operation}' is an Own Damage operation. Third-Party liability claims use the dedicated TP "
                f"workflow (/api/v1/claims/{claim.id}/tp) with legal oversight and dual-control settlement; "
                "autonomous or OD-style settlement is prohibited (IN-TP-LIABILITY-2026)."
            ),
            status_code=409,
            details={"tp_workflow_url": f"/api/v1/claims/{claim.id}/tp", "rule_id": TP_RULE_ID},
        )


def can_view_restricted(user: UserContext) -> bool:
    return user.role in ROLES_MEDICAL_VIEW


def _case_for(db: Session, claim: Claim) -> TPClaimCase:
    case = db.query(TPClaimCase).filter(TPClaimCase.claim_id == claim.id).first()
    if not case:
        raise DomainError(
            ErrorCode.NOT_FOUND,
            f"No Third-Party case is open for claim {claim.claim_number}; open one via POST /claims/{claim.id}/tp/open",
            status_code=404,
        )
    return case


def get_tp_case(db: Session, claim: Claim) -> TPClaimCase | None:
    return db.query(TPClaimCase).filter(TPClaimCase.claim_id == claim.id).first()


def _audit(db: Session, case: TPClaimCase, user: UserContext, action: str, details: dict[str, Any] | None = None) -> None:
    record_audit_event(
        db,
        tenant_id=case.tenant_id,
        claim_id=case.claim_id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action=action,
        object_type="tp_claim_case",
        object_id=case.id,
        after_state={"stage": case.stage, "reserve_inr": str(case.reserve_inr)},
        details=details or {},
    )


# ----------------------------------------------------------------------------------------------
# Stage path, gates and queues
# ----------------------------------------------------------------------------------------------
def stage_path(case: TPClaimCase, rule: dict[str, Any]) -> list[str]:
    cat = rule["categories"][case.tp_category]
    police_required = bool(cat["police_report_required"]) or bool((case.accident_facts or {}).get("police_involved"))
    advocate_required = (
        bool(cat["advocate_required"])
        or bool((case.tribunal or {}).get("claim_petition_filed"))
        or (case.legal_review or {}).get("decision") == "contest_liability"
    )
    path: list[str] = []
    for stage in STAGE_ORDER:
        if stage == TPStage.POLICE_FIR.value and not police_required:
            continue
        if stage == TPStage.ADVOCATE_COORDINATION.value and not advocate_required:
            continue
        if stage == TPStage.MEDICAL_REVIEW.value and not cat["medical_review_required"]:
            continue
        path.append(stage)
    return path


def next_stage_after(case: TPClaimCase, rule: dict[str, Any]) -> Optional[str]:
    path = stage_path(case, rule)
    cur_order = STAGE_ORDER.index(case.stage)
    for stage in path:
        if STAGE_ORDER.index(stage) > cur_order:
            return stage
    return None


def required_documents(case: TPClaimCase, rule: dict[str, Any]) -> list[str]:
    docs = list(rule["categories"][case.tp_category]["required_documents"])
    if not (case.police_report or {}).get("fir_number") and "fir_copy" in docs and (case.police_report or {}).get("fir_waived"):
        docs.remove("fir_copy")
    return docs


def evaluate_gates(db: Session, case: TPClaimCase, rule: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Exit conditions for the current stage. An empty list means a human may advance."""
    rule = rule or tp_rule(db)
    blockers: list[dict[str, str]] = []
    stage = case.stage

    def block(code: str, message: str) -> None:
        blockers.append({"code": code, "message": message})

    if stage == TPStage.INTAKE.value:
        if not case.third_parties:
            block("THIRD_PARTY_REQUIRED", "Record at least one third-party claimant, injured party or property owner.")
        if case.coverage_status not in {"valid", "flagged"}:
            block("COVERAGE_CHECK_REQUIRED", "Run the policy coverage validation for the incident date.")
    elif stage == TPStage.EVIDENCE_AND_FACTS.value:
        facts = case.accident_facts or {}
        if not (facts.get("narrative") and facts.get("location") and facts.get("accident_at")):
            block("ACCIDENT_FACTS_REQUIRED", "Record accident date/time, location and a factual narrative.")
        if not case.evidence_items:
            block("EVIDENCE_REQUIRED", "Attach at least one evidence item (photo, CCTV, witness statement, site sketch).")
    elif stage == TPStage.POLICE_FIR.value:
        pr = case.police_report or {}
        if not (pr.get("fir_number") or pr.get("fir_waived")):
            block("FIR_REQUIRED", "Record the FIR / police report details, or a documented waiver approved by a manager or legal.")
    elif stage == TPStage.LIABILITY_INVESTIGATION.value:
        la = case.liability_assessment or {}
        if la.get("status") != "assessed":
            block("LIABILITY_ASSESSMENT_REQUIRED", "A human claims handler or legal specialist must record the liability assessment.")
    elif stage == TPStage.LEGAL_DOCUMENTATION.value:
        have = {d["doc_type"] for d in case.legal_documents if d.get("status") in {"received", "verified"}}
        missing = [d for d in required_documents(case, rule) if d not in have]
        if missing:
            block("LEGAL_DOCUMENTS_MISSING", f"Required legal documents not yet received: {', '.join(missing)}.")
    elif stage == TPStage.ADVOCATE_COORDINATION.value:
        if not case.advocates:
            block("ADVOCATE_REQUIRED", "Assign at least one panel advocate before legal review.")
    elif stage == TPStage.MEDICAL_REVIEW.value:
        if (case.medical_review or {}).get("status") != "completed":
            block("MEDICAL_REVIEW_REQUIRED", "A medical opinion (severity, disability %, causation) must be recorded.")
    elif stage == TPStage.LEGAL_SPECIALIST_REVIEW.value:
        if not (case.legal_review or {}).get("decision"):
            block("LEGAL_SIGN_OFF_REQUIRED", "Legal/TP specialist sign-off with a legal decision is mandatory.")
        if Decimal(str(case.reserve_inr or 0)) <= Decimal("0.00"):
            block("RESERVE_REQUIRED", "A claim reserve must be set before settlement control.")
    elif stage == TPStage.SETTLEMENT_CONTROL.value:
        if not case.approved_proposal_id:
            block("SETTLEMENT_APPROVAL_REQUIRED", "A settlement proposal must be approved under dual control.")
    elif stage == TPStage.SETTLEMENT_APPROVED.value:
        if (case.payment_authorisation or {}).get("status") != "released":
            block("PAYMENT_AUTHORISATION_REQUIRED", "Finance must authorise payment release.")
    elif stage == TPStage.PAYMENT_AUTHORISED.value:
        block("CLOSURE_REVIEW_REQUIRED", "Closure requires a manager's closure review.")
    return blockers


def _open_stage_task(db: Session, case: TPClaimCase, claim: Claim, rule: dict[str, Any], stage: str) -> ClaimTask:
    for t in (
        db.query(ClaimTask)
        .filter(ClaimTask.claim_id == claim.id, ClaimTask.task_type.like("tp_%"), ClaimTask.status == "open")
        .all()
    ):
        t.status = "completed"
        t.completed_at = _utcnow()
    spec = rule["stage_catalogue"][stage]
    case.queue_name = spec["queue"]
    claim.queue_name = spec["queue"]
    now = _utcnow()
    task = ClaimTask(
        tenant_id=case.tenant_id,
        claim_id=claim.id,
        task_type=f"tp_{stage.lower()}",
        title=f"[TP] {stage.replace('_', ' ').title()} - {case.case_number}",
        description=f"Human-gated Third-Party stage '{stage}'. Autonomous completion is prohibited ({TP_RULE_ID}).",
        assigned_role=spec["owner_role"],
        created_by_agent="tp_workflow_engine",
        priority="urgent" if case.tp_category == "fatality" else "high",
        status="open" if stage != TPStage.CLOSED.value else "completed",
        reason_code="TP_STAGE_HUMAN_GATE",
        due_at=(now + timedelta(hours=int(spec["sla_hours"]))) if spec["sla_hours"] else None,
        metadata_json={"tp_case_id": case.id, "queue": spec["queue"], "stage": stage, "human_gate": spec["human_gate"]},
    )
    db.add(task)
    return task


def _mirror_claim_status(claim: Claim, stage: str) -> None:
    """Best-effort projection of the TP stage onto the shared claim status; the TP stage stays authoritative."""
    target = STAGE_TO_CLAIM_STATUS.get(stage)
    if target is None or claim.status == target.value:
        return
    try:
        claim.status = validate_transition(claim.status, target.value).value
    except DomainError:
        pass


def _enter_stage(
    db: Session,
    case: TPClaimCase,
    claim: Claim,
    rule: dict[str, Any],
    stage: str,
    user: UserContext,
    *,
    note: str = "",
    skipped: list[str] | None = None,
) -> None:
    prev = case.stage
    case.stage = stage
    case.stage_history = [
        *(case.stage_history or []),
        {
            "from": prev,
            "to": stage,
            "at": _iso(_utcnow()),
            "by": _actor(user),
            "note": note,
            "skipped_by_rule": skipped or [],
        },
    ]
    _open_stage_task(db, case, claim, rule, stage)
    _mirror_claim_status(claim, stage)
    claim.workflow_state = {**(claim.workflow_state or {}), "tp_stage": stage, "tp_case_number": case.case_number}
    claim.next_expected_action = _next_action_text(case, rule)


def _next_action_text(case: TPClaimCase, rule: dict[str, Any]) -> str:
    stage = case.stage
    spec = rule["stage_catalogue"].get(stage, {})
    role = spec.get("owner_role", "claims_handler").replace("_", " ")
    return f"TP {stage.replace('_', ' ').title()}: {role} action required (human-gated, queue {spec.get('queue', '')})"


# ----------------------------------------------------------------------------------------------
# Opening a TP case
# ----------------------------------------------------------------------------------------------
def _validate_coverage(db: Session, claim: Claim) -> tuple[str, str]:
    policy = db.query(Policy).filter(Policy.id == claim.policy_id).first() if claim.policy_id else None
    if not policy:
        return "flagged", "No matched policy: legal must confirm statutory liability and recovery rights before any payment."
    inc = claim.incident_at if claim.incident_at.tzinfo else claim.incident_at.replace(tzinfo=timezone.utc)
    start = policy.period_start if policy.period_start.tzinfo else policy.period_start.replace(tzinfo=timezone.utc)
    end = policy.period_end if policy.period_end.tzinfo else policy.period_end.replace(tzinfo=timezone.utc)
    if policy.status != "active" or not (start <= inc <= end):
        return (
            "flagged",
            "Policy not active or incident outside the period of insurance: Legal must decide liability and any "
            "pay-and-recover route. Coverage is never auto-declined for a third-party claim.",
        )
    return "valid", "Policy active and incident within the period of insurance; Section II (Third-Party Liability) applies."


def infer_tp_category(claim: Claim) -> str:
    peril = claim.peril_cause or ""
    if peril == "tp_fatality":
        return "fatality"
    if peril == "tp_property_damage":
        return "property_damage"
    if claim.injury_or_fatality or peril == "tp_bodily_injury":
        return "bodily_injury"
    return "property_damage"


def open_tp_case(
    db: Session,
    claim: Claim,
    user: UserContext,
    *,
    tp_category: str | None = None,
    linked_od_claim_id: str | None = None,
    system_initiated: bool = False,
) -> TPClaimCase:
    # system_initiated: the platform opens the case automatically at FNOL for a third_party claim, whoever submitted it.
    # Opening a case is intake bookkeeping only; every decision after it stays human-gated.
    if not system_initiated:
        _require_role(user, ROLES_INTAKE, "open a TP case")
    existing = get_tp_case(db, claim)
    if existing:
        return existing
    rule = tp_rule(db)
    category = tp_category or infer_tp_category(claim)
    if category not in TP_CATEGORIES:
        raise DomainError(ErrorCode.VALIDATION_ERROR, f"tp_category must be one of {list(TP_CATEGORIES)}", status_code=400)

    if claim.claim_type != "third_party":
        raise DomainError(
            ErrorCode.STATE_CONFLICT,
            "Only a claim of type 'third_party' can carry a TP case. For third-party exposure raised by an Own Damage "
            "claim, use POST /claims/{id}/tp/exposures to create a separate linked TP claim.",
            status_code=409,
        )

    cov_status, cov_notes = _validate_coverage(db, claim)
    case = TPClaimCase(
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        case_number=f"TP-{claim.claim_number.split('CLM-')[-1]}",
        linked_od_claim_id=linked_od_claim_id or (claim.workflow_state or {}).get("linked_od_claim_id"),
        tp_category=category,
        stage=TPStage.INTAKE.value,
        queue_name="tp_intake",
        coverage_status=cov_status,
        coverage_notes=cov_notes,
        accident_facts={
            "accident_at": _iso(claim.incident_at),
            "location": claim.incident_location,
            "narrative": claim.incident_description,
            "police_involved": bool(claim.police_involved),
            "vehicles_involved": int(claim.involved_vehicles_count or 1),
        },
        created_by=user.user_id,
        stage_history=[
            {"from": None, "to": TPStage.INTAKE.value, "at": _iso(_utcnow()), "by": _actor(user), "note": "TP case opened", "skipped_by_rule": []}
        ],
    )
    db.add(case)
    db.flush()

    claim.claim_type = "third_party"
    claim.severity_band = "critical" if category in {"fatality", "bodily_injury"} else "high"
    if category != "property_damage":
        claim.injury_or_fatality = True
    claim.workflow_state = {**(claim.workflow_state or {}), "tp_workflow": True, "tp_case_number": case.case_number}
    _open_stage_task(db, case, claim, rule, TPStage.INTAKE.value)
    _mirror_claim_status(claim, TPStage.INTAKE.value)
    claim.next_expected_action = _next_action_text(case, rule)
    _audit(db, case, user, "TP_CASE_OPENED", {"category": category, "coverage_status": cov_status})
    emit_outbox_event(
        db,
        tenant_id=case.tenant_id,
        aggregate_id=claim.id,
        event_type="TPCaseOpened",
        payload={"tp_case_id": case.id, "category": category, "coverage_status": cov_status},
        idempotency_key=f"TPCaseOpened:{case.id}",
    )
    return case


def raise_tp_exposure_from_od_claim(
    db: Session,
    od_claim: Claim,
    user: UserContext,
    *,
    tp_category: str,
    description: str = "",
) -> tuple[Claim, TPClaimCase]:
    """An OD claim that injures or damages a third party spawns a separate, linked TP claim (never the same record)."""
    _require_role(user, ROLES_INTAKE, "raise a TP exposure")
    if claim_requires_tp_workflow(od_claim):
        raise DomainError(ErrorCode.STATE_CONFLICT, "This claim is already a Third-Party claim", status_code=409)
    if tp_category not in TP_CATEGORIES:
        raise DomainError(ErrorCode.VALIDATION_ERROR, f"tp_category must be one of {list(TP_CATEGORIES)}", status_code=400)
    for c in db.query(Claim).filter(Claim.tenant_id == od_claim.tenant_id, Claim.claim_type == "third_party").all():
        if (c.workflow_state or {}).get("linked_od_claim_id") == od_claim.id:
            tp_case = get_tp_case(db, c)
            if tp_case and tp_case.tp_category == tp_category:
                return c, tp_case

    tp_claim = Claim(
        tenant_id=od_claim.tenant_id,
        claim_number=f"CLM-DEMO-{_utcnow().year}-{uuid.uuid4().hex[:6].upper()}",
        policy_id=od_claim.policy_id,
        customer_id=od_claim.customer_id,
        vehicle_id=od_claim.vehicle_id,
        claim_type="third_party",
        peril_cause={"fatality": "tp_fatality", "bodily_injury": "tp_bodily_injury"}.get(tp_category, "tp_property_damage"),
        intake_channel=od_claim.intake_channel,
        status=ClaimStatus.SUBMITTED.value,
        incident_at=od_claim.incident_at,
        incident_location=od_claim.incident_location,
        incident_description=_clean(description) or f"Third-party exposure arising from OD claim {od_claim.claim_number}: {od_claim.incident_description}",
        policy_number_input=od_claim.policy_number_input,
        vehicle_reg_input=od_claim.vehicle_reg_input,
        driver_name=od_claim.driver_name,
        driver_licence_ref=od_claim.driver_licence_ref,
        injury_or_fatality=tp_category != "property_damage",
        police_involved=od_claim.police_involved or tp_category != "property_damage",
        multiple_vehicles_involved=od_claim.multiple_vehicles_involved,
        involved_vehicles_count=od_claim.involved_vehicles_count,
        queue_name="tp_intake",
        workflow_state={"linked_od_claim_id": od_claim.id, "linked_od_claim_number": od_claim.claim_number},
        is_synthetic_demo=od_claim.is_synthetic_demo,
    )
    db.add(tp_claim)
    db.flush()
    case = open_tp_case(db, tp_claim, user, tp_category=tp_category, linked_od_claim_id=od_claim.id)
    od_claim.workflow_state = {
        **(od_claim.workflow_state or {}),
        "linked_tp_claim_ids": [*((od_claim.workflow_state or {}).get("linked_tp_claim_ids", [])), tp_claim.id],
    }
    return tp_claim, case


# ----------------------------------------------------------------------------------------------
# Intake: third parties, facts, evidence, police
# ----------------------------------------------------------------------------------------------
def _assert_open(case: TPClaimCase) -> None:
    if case.stage == TPStage.CLOSED.value:
        raise DomainError(ErrorCode.STATE_CONFLICT, "TP case is closed; reopen via a legal-approved reopening request", status_code=409)


def add_third_party(
    db: Session,
    case: TPClaimCase,
    user: UserContext,
    *,
    role: str,
    name: str,
    contact: str = "",
    vehicle_reg: str = "",
    other_insurer: str = "",
    injury_severity: str | None = None,
    claimant_demand_inr: Any = None,
    is_minor: bool = False,
    notes: str = "",
) -> dict[str, Any]:
    _require_role(user, ROLES_INTAKE, "record third-party details")
    _assert_open(case)
    if role not in TP_PARTY_ROLES:
        raise DomainError(ErrorCode.VALIDATION_ERROR, f"role must be one of {list(TP_PARTY_ROLES)}", status_code=400)
    if injury_severity and injury_severity not in INJURY_SEVERITIES:
        raise DomainError(ErrorCode.VALIDATION_ERROR, f"injury_severity must be one of {list(INJURY_SEVERITIES)}", status_code=400)
    if not name.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, "Third-party name is required", status_code=400)
    is_medical = role in {"injured", "deceased"} or injury_severity is not None
    party = {
        "party_id": f"tpp-{uuid.uuid4().hex[:8]}",
        "role": role,
        "name": _clean(name, max_len=200),
        "contact_masked": _mask_contact(contact),
        "vehicle_reg": _clean(vehicle_reg, max_len=32).upper(),
        "other_insurer": _clean(other_insurer, max_len=120),
        "injury_severity": injury_severity,
        "claimant_demand_inr": str(_money(claimant_demand_inr, field="claimant_demand_inr")) if claimant_demand_inr not in (None, "") else None,
        "is_minor": bool(is_minor),
        "is_restricted_tp_medical": is_medical,
        "notes": _clean(notes, max_len=500),
        "added_by": _actor(user),
        "added_at": _iso(_utcnow()),
    }
    case.third_parties = [*(case.third_parties or []), party]
    _audit(db, case, user, "TP_THIRD_PARTY_RECORDED", {"party_id": party["party_id"], "role": role})
    return party


def validate_case_coverage(db: Session, case: TPClaimCase, claim: Claim, user: UserContext) -> TPClaimCase:
    _require_role(user, ROLES_INTAKE, "validate coverage")
    status, notes = _validate_coverage(db, claim)
    case.coverage_status, case.coverage_notes = status, notes
    _audit(db, case, user, "TP_COVERAGE_VALIDATED", {"coverage_status": status})
    return case


def record_accident_facts(
    db: Session,
    case: TPClaimCase,
    user: UserContext,
    *,
    accident_at: datetime | None = None,
    location: str | None = None,
    narrative: str | None = None,
    police_involved: bool | None = None,
    vehicles_involved: int | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> TPClaimCase:
    _require_role(user, ROLES_INTAKE, "record accident facts")
    _assert_open(case)
    facts = dict(case.accident_facts or {})
    if accident_at:
        facts["accident_at"] = _iso(accident_at)
    if location:
        facts["location"] = _clean(location, max_len=240)
    if narrative:
        facts["narrative"] = _clean(narrative)
    if police_involved is not None:
        facts["police_involved"] = bool(police_involved)
    if vehicles_involved:
        facts["vehicles_involved"] = int(vehicles_involved)
    facts["last_updated_by"] = _actor(user)
    case.accident_facts = facts
    new_items = []
    for item in evidence or []:
        kind = item.get("kind", "other")
        if kind not in EVIDENCE_KINDS:
            raise DomainError(ErrorCode.VALIDATION_ERROR, f"evidence kind must be one of {list(EVIDENCE_KINDS)}", status_code=400)
        new_items.append(
            {
                "evidence_ref": f"tpe-{uuid.uuid4().hex[:8]}",
                "kind": kind,
                "description": _clean(item.get("description"), max_len=500),
                "source": _clean(item.get("source"), max_len=120),
                "added_by": _actor(user),
                "added_at": _iso(_utcnow()),
                "legal_hold": True,
            }
        )
    if new_items:
        case.evidence_items = [*(case.evidence_items or []), *new_items]
    _audit(db, case, user, "TP_ACCIDENT_FACTS_RECORDED", {"evidence_added": len(new_items)})
    return case


def record_police_report(
    db: Session,
    case: TPClaimCase,
    user: UserContext,
    *,
    fir_number: str = "",
    police_station: str = "",
    fir_date: datetime | None = None,
    sections_invoked: list[str] | None = None,
    dar_status: str = "pending",
    charge_sheet_status: str = "not_filed",
    fir_waived: bool = False,
    waiver_reason: str = "",
) -> TPClaimCase:
    _require_role(user, ROLES_HANDLING, "record police/FIR details")
    _assert_open(case)
    pr = dict(case.police_report or {})
    if fir_waived:
        if user.role not in {Role.CLAIMS_MANAGER, Role.LEGAL_TP, Role.ADMIN}:
            raise DomainError(ErrorCode.NOT_AUTHORISED, "Only a Claims Manager or Legal/TP specialist can waive the FIR requirement", status_code=403)
        if case.tp_category != "property_damage":
            raise DomainError(ErrorCode.VALIDATION_ERROR, "An FIR cannot be waived for bodily injury or fatality claims", status_code=400)
        if len(waiver_reason.strip()) < 15:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "A documented waiver reason (min 15 characters) is required", status_code=400)
        pr.update({"fir_waived": True, "waiver_reason": _clean(waiver_reason, max_len=500), "waived_by": _actor(user)})
    else:
        if not fir_number.strip():
            raise DomainError(ErrorCode.VALIDATION_ERROR, "fir_number is required unless a waiver is recorded", status_code=400)
        pr.update(
            {
                "fir_number": _clean(fir_number, max_len=64),
                "police_station": _clean(police_station, max_len=120),
                "fir_date": _iso(fir_date),
                "sections_invoked": [_clean(s, max_len=40) for s in (sections_invoked or [])],
                "dar_status": dar_status,
                "charge_sheet_status": charge_sheet_status,
                "fir_waived": False,
                "recorded_by": _actor(user),
            }
        )
    case.police_report = pr
    _audit(db, case, user, "TP_POLICE_REPORT_RECORDED", {"fir_waived": fir_waived})
    return case


# ----------------------------------------------------------------------------------------------
# Liability, legal documents, advocates, medical, legal review
# ----------------------------------------------------------------------------------------------
def record_liability_assessment(
    db: Session,
    case: TPClaimCase,
    claim: Claim,
    user: UserContext,
    *,
    insured_fault_pct: int,
    third_party_fault_pct: int,
    contributory_negligence: bool,
    policy_defences: list[str],
    rationale: str,
    investigator_name: str = "",
) -> TPClaimCase:
    """Human-recorded liability assessment. Software may suggest indicators but never determines liability."""
    _require_role(user, ROLES_HANDLING, "record the liability assessment")
    _assert_open(case)
    if case.stage not in {TPStage.LIABILITY_INVESTIGATION.value, TPStage.LEGAL_DOCUMENTATION.value, TPStage.LEGAL_SPECIALIST_REVIEW.value}:
        raise DomainError(
            ErrorCode.STATE_CONFLICT,
            f"Liability is assessed in the LIABILITY_INVESTIGATION stage; case is at {case.stage}",
            status_code=409,
        )
    if not (0 <= insured_fault_pct <= 100 and 0 <= third_party_fault_pct <= 100 and insured_fault_pct + third_party_fault_pct <= 100):
        raise DomainError(ErrorCode.VALIDATION_ERROR, "Fault percentages must be 0-100 and sum to at most 100", status_code=400)
    bad = [d for d in policy_defences if d not in POLICY_DEFENCES]
    if bad:
        raise DomainError(ErrorCode.VALIDATION_ERROR, f"Unknown policy defence(s) {bad}; allowed: {list(POLICY_DEFENCES)}", status_code=400)
    clean_rationale = _clean(rationale)
    if len(clean_rationale) < 30:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "A reasoned liability rationale (min 30 characters) is mandatory", status_code=400)
    case.liability_assessment = {
        "status": "assessed",
        "insured_fault_pct": insured_fault_pct,
        "third_party_fault_pct": third_party_fault_pct,
        "undetermined_pct": 100 - insured_fault_pct - third_party_fault_pct,
        "contributory_negligence": bool(contributory_negligence),
        "policy_defences": list(dict.fromkeys(policy_defences)),
        "recovery_rights_flag": bool(policy_defences),
        "rationale": clean_rationale,
        "investigator": _clean(investigator_name, max_len=120),
        "assessed_by": _actor(user),
        "assessed_at": _iso(_utcnow()),
        "determined_by_ai": False,
    }
    _audit(db, case, user, "TP_LIABILITY_ASSESSED", {"insured_fault_pct": insured_fault_pct, "defences": policy_defences})
    return case


def register_legal_document(
    db: Session,
    case: TPClaimCase,
    user: UserContext,
    *,
    doc_type: str,
    status: str = "received",
    reference: str = "",
    notes: str = "",
) -> dict[str, Any]:
    _require_role(user, ROLES_HANDLING, "register legal documents")
    _assert_open(case)
    if status not in LEGAL_DOC_STATUSES:
        raise DomainError(ErrorCode.VALIDATION_ERROR, f"status must be one of {list(LEGAL_DOC_STATUSES)}", status_code=400)
    if status == "verified" and user.role not in ROLES_LEGAL | {Role.CLAIMS_MANAGER}:
        raise DomainError(ErrorCode.NOT_AUTHORISED, "Only Legal/TP or a Claims Manager can mark a legal document verified", status_code=403)
    doc_type = _clean(doc_type, max_len=64).lower().replace(" ", "_")
    docs = [d for d in (case.legal_documents or []) if d["doc_type"] != doc_type]
    entry = {
        "doc_type": doc_type,
        "status": status,
        "reference": _clean(reference, max_len=120),
        "notes": _clean(notes, max_len=500),
        "recorded_by": _actor(user),
        "recorded_at": _iso(_utcnow()),
    }
    case.legal_documents = [*docs, entry]
    _audit(db, case, user, "TP_LEGAL_DOCUMENT_REGISTERED", {"doc_type": doc_type, "status": status})
    return entry


def record_tribunal_event(
    db: Session,
    case: TPClaimCase,
    user: UserContext,
    *,
    claim_petition_filed: bool | None = None,
    tribunal_name: str = "",
    petition_number: str = "",
    next_hearing_at: datetime | None = None,
    award_amount_inr: Any = None,
    award_reference: str = "",
) -> TPClaimCase:
    _require_role(user, ROLES_LEGAL, "record tribunal (MACT) events")
    _assert_open(case)
    t = dict(case.tribunal or {})
    if claim_petition_filed is not None:
        t["claim_petition_filed"] = bool(claim_petition_filed)
    if tribunal_name:
        t["tribunal_name"] = _clean(tribunal_name, max_len=160)
    if petition_number:
        t["petition_number"] = _clean(petition_number, max_len=64)
    if next_hearing_at:
        t["next_hearing_at"] = _iso(next_hearing_at)
    if award_amount_inr not in (None, ""):
        if not award_reference.strip():
            raise DomainError(ErrorCode.VALIDATION_ERROR, "award_reference is required when recording an award", status_code=400)
        t["award_amount_inr"] = str(_money(award_amount_inr, field="award_amount_inr"))
        t["award_reference"] = _clean(award_reference, max_len=120)
        t["award_recorded_by"] = _actor(user)
    case.tribunal = t
    _audit(db, case, user, "TP_TRIBUNAL_EVENT_RECORDED", {k: v for k, v in t.items() if k != "award_recorded_by"})
    return case


def assign_advocate(
    db: Session,
    case: TPClaimCase,
    user: UserContext,
    *,
    advocate_name: str,
    bar_enrolment_ref: str = "",
    role: str = "panel_counsel",
    fee_cap_inr: Any = None,
    conflict_check_cleared: bool = False,
) -> dict[str, Any]:
    _require_role(user, ROLES_LEGAL, "assign advocates")
    _assert_open(case)
    if not conflict_check_cleared:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "Advocate conflict-of-interest check must be cleared before assignment", status_code=400)
    if role not in {"panel_counsel", "defence_counsel", "settlement_counsel", "watching_brief"}:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "role must be panel_counsel, defence_counsel, settlement_counsel or watching_brief", status_code=400)
    adv = {
        "advocate_id": f"adv-{uuid.uuid4().hex[:8]}",
        "name": _clean(advocate_name, max_len=160),
        "bar_enrolment_ref_masked": ("***" + bar_enrolment_ref[-4:]) if bar_enrolment_ref else "",
        "role": role,
        "fee_cap_inr": str(_money(fee_cap_inr, field="fee_cap_inr")) if fee_cap_inr not in (None, "") else None,
        "conflict_check_cleared": True,
        "assigned_by": _actor(user),
        "assigned_at": _iso(_utcnow()),
    }
    if not adv["name"]:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "advocate_name is required", status_code=400)
    case.advocates = [*(case.advocates or []), adv]
    _audit(db, case, user, "TP_ADVOCATE_ASSIGNED", {"advocate_id": adv["advocate_id"], "role": role})
    return adv


def record_medical_review(
    db: Session,
    case: TPClaimCase,
    user: UserContext,
    *,
    injury_severity: str,
    disability_percent: int | None,
    causation_consistent: bool,
    opinion: str,
    reviewer_name: str,
    records_reviewed: list[str] | None = None,
) -> TPClaimCase:
    _require_role(user, ROLES_LEGAL | {Role.CLAIMS_MANAGER, Role.CLAIMS_HANDLER}, "record the medical review")
    _assert_open(case)
    if injury_severity not in INJURY_SEVERITIES:
        raise DomainError(ErrorCode.VALIDATION_ERROR, f"injury_severity must be one of {list(INJURY_SEVERITIES)}", status_code=400)
    if disability_percent is not None and not (0 <= disability_percent <= 100):
        raise DomainError(ErrorCode.VALIDATION_ERROR, "disability_percent must be 0-100", status_code=400)
    if len(_clean(opinion)) < 20:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "A medical opinion (min 20 characters) is required", status_code=400)
    case.medical_review = {
        "status": "completed",
        "injury_severity": injury_severity,
        "disability_percent": disability_percent,
        "causation_consistent_with_accident": bool(causation_consistent),
        "opinion": _clean(opinion),
        "reviewer_name": _clean(reviewer_name, max_len=160),
        "records_reviewed": [_clean(r, max_len=120) for r in (records_reviewed or [])],
        "recorded_by": _actor(user),
        "recorded_at": _iso(_utcnow()),
        "is_restricted_tp_medical": True,
    }
    _audit(db, case, user, "TP_MEDICAL_REVIEW_RECORDED", {"severity": injury_severity})
    return case


def sign_legal_review(
    db: Session,
    case: TPClaimCase,
    claim: Claim,
    user: UserContext,
    *,
    decision: str,
    notes: str,
    exposure_summary: str = "",
) -> TPClaimCase:
    _require_role(user, ROLES_LEGAL, "sign the legal specialist review")
    _assert_open(case)
    rule = tp_rule(db)
    if case.stage != TPStage.LEGAL_SPECIALIST_REVIEW.value:
        raise DomainError(ErrorCode.STATE_CONFLICT, f"Legal review is signed at LEGAL_SPECIALIST_REVIEW; case is at {case.stage}", status_code=409)
    if decision not in rule["legal_decisions"]:
        raise DomainError(ErrorCode.VALIDATION_ERROR, f"decision must be one of {rule['legal_decisions']}", status_code=400)
    la = case.liability_assessment or {}
    if decision == "pay_and_recover" and not la.get("policy_defences"):
        raise DomainError(ErrorCode.VALIDATION_ERROR, "pay_and_recover requires a recorded policy defence in the liability assessment", status_code=400)
    clean_notes = _clean(notes)
    if len(clean_notes) < 30:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "Legal review notes (min 30 characters) are mandatory", status_code=400)
    assert_fraud_score_never_rejects(decision=decision, fraud_signal_score=claim.fraud_signal_score, rationale=clean_notes)
    case.legal_review = {
        "decision": decision,
        "notes": clean_notes,
        "exposure_summary": _clean(exposure_summary),
        "signed_by": _actor(user),
        "signed_at": _iso(_utcnow()),
    }
    _audit(db, case, user, "TP_LEGAL_REVIEW_SIGNED", {"decision": decision})
    emit_outbox_event(
        db,
        tenant_id=case.tenant_id,
        aggregate_id=claim.id,
        event_type="TPLegalReviewSigned",
        payload={"tp_case_id": case.id, "decision": decision},
    )
    return case


# ----------------------------------------------------------------------------------------------
# Reserve and controlled settlement
# ----------------------------------------------------------------------------------------------
def set_reserve(db: Session, case: TPClaimCase, user: UserContext, *, amount_inr: Any, basis: str) -> TPClaimCase:
    _require_role(user, ROLES_HANDLING, "set the claim reserve")
    _assert_open(case)
    amount = _money(amount_inr, field="reserve amount_inr")
    if amount <= Decimal("0.00"):
        raise DomainError(ErrorCode.VALIDATION_ERROR, "Reserve must be greater than zero", status_code=400)
    clean_basis = _clean(basis)
    if len(clean_basis) < 15:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "A reserve basis (min 15 characters) is mandatory", status_code=400)
    rule = tp_rule(db)
    prev = Decimal(str(case.reserve_inr or 0))
    # A reserve increase above INR 5,00,000 or any change on a fatality needs a manager or legal specialist.
    if (amount > Decimal("500000.00") or case.tp_category == "fatality") and user.role not in {Role.CLAIMS_MANAGER, Role.LEGAL_TP, Role.ADMIN}:
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            "Reserves above INR 5,00,000 or on a fatality require a Claims Manager or Legal/TP specialist",
            status_code=403,
        )
    case.reserve_inr = amount
    case.reserve_history = [
        *(case.reserve_history or []),
        {"from_inr": str(prev), "to_inr": str(amount), "basis": clean_basis, "by": _actor(user), "at": _iso(_utcnow())},
    ]
    _audit(db, case, user, "TP_RESERVE_SET", {"from": str(prev), "to": str(amount), "rule": rule["rule_id"]})
    return case


def _tier_for(rule: dict[str, Any], amount: Decimal, category: str) -> dict[str, Any]:
    for tier in rule["settlement_approval_tiers"]:
        cap = tier["max_amount_inr"]
        if category == "fatality" and not tier["allow_fatality"]:
            continue
        if cap is None or amount <= Decimal(str(cap)):
            return dict(tier)
    return dict(rule["settlement_approval_tiers"][-1])


def propose_settlement(
    db: Session,
    case: TPClaimCase,
    claim: Claim,
    user: UserContext,
    *,
    basis: str,
    amount_inr: Any,
    components: dict[str, Any] | None,
    rationale: str,
    award_reference: str = "",
) -> dict[str, Any]:
    _require_role(user, ROLES_HANDLING, "propose a settlement")
    _assert_open(case)
    rule = tp_rule(db)
    controls = rule["controls"]
    if case.stage != TPStage.SETTLEMENT_CONTROL.value:
        raise DomainError(ErrorCode.STATE_CONFLICT, f"Settlements are proposed at SETTLEMENT_CONTROL; case is at {case.stage}", status_code=409)
    if basis not in rule["settlement_bases"]:
        raise DomainError(ErrorCode.VALIDATION_ERROR, f"basis must be one of {rule['settlement_bases']}", status_code=400)
    legal = case.legal_review or {}
    if not legal.get("decision"):
        raise DomainError(ErrorCode.HUMAN_REVIEW_REQUIRED, "Legal sign-off is required before any settlement proposal", status_code=409)
    if (legal.get("signed_by") or {}).get("user_id") == user.user_id:
        raise DomainError(ErrorCode.NOT_AUTHORISED, "Separation of duties: the legal reviewer cannot also propose the settlement", status_code=403)
    allowed_basis = {
        "negotiate_settlement": {"negotiated"},
        "contest_liability": {"tribunal_award"},
        "pay_and_recover": {"pay_and_recover", "tribunal_award"},
    }[legal["decision"]]
    if basis not in allowed_basis:
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            f"Legal decision '{legal['decision']}' only permits settlement basis {sorted(allowed_basis)}",
            status_code=409,
        )
    amount = _money(amount_inr)
    if amount <= Decimal("0.00"):
        raise DomainError(ErrorCode.VALIDATION_ERROR, "Settlement amount must be greater than zero", status_code=400)
    if Decimal(str(case.reserve_inr or 0)) <= Decimal("0.00"):
        raise DomainError(ErrorCode.HUMAN_REVIEW_REQUIRED, "A reserve must be set before a settlement proposal", status_code=409)
    if amount > Decimal(str(case.reserve_inr)):
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            f"Proposal INR {amount} exceeds reserve INR {case.reserve_inr}; increase the reserve (with basis) first",
            status_code=409,
        )
    if basis == "tribunal_award":
        award = (case.tribunal or {}).get("award_amount_inr")
        if not award or not award_reference.strip():
            raise DomainError(ErrorCode.VALIDATION_ERROR, "A recorded tribunal award and award_reference are required for tribunal_award settlement", status_code=400)
        if amount != Decimal(str(award)):
            raise DomainError(ErrorCode.VALIDATION_ERROR, f"Award compliance amount must equal the recorded award INR {award}", status_code=400)
    elif case.tp_category == "property_damage" and amount > Decimal(str(controls["tppd_limit_inr"])):
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            f"Proposal exceeds the statutory TP property damage limit INR {controls['tppd_limit_inr']}; Legal must record excess liability handling",
            status_code=409,
        )
    clean_rationale = _clean(rationale)
    if len(clean_rationale) < 30:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "Settlement rationale (min 30 characters) is mandatory", status_code=400)

    tier = _tier_for(rule, amount, case.tp_category)
    proposals = []
    for p in case.settlement_proposals or []:
        if p["status"] == "pending_approval":
            p = {**p, "status": "superseded"}
        proposals.append(p)
    proposal = {
        "proposal_id": f"tps-{uuid.uuid4().hex[:8]}",
        "basis": basis,
        "amount_inr": str(amount),
        "components": {k: str(_money(v, field=k)) for k, v in (components or {}).items()},
        "rationale": clean_rationale,
        "award_reference": _clean(award_reference, max_len=120),
        "proposed_by": _actor(user),
        "proposed_at": _iso(_utcnow()),
        "status": "pending_approval",
        "approval_tier": tier["tier"],
        "required_approver_roles": list(tier["required_approver_roles"]),
        "approvals": [],
        "rule_version": f"{rule['rule_id']}:{rule['version']}",
    }
    case.settlement_proposals = [*proposals, proposal]
    claim.next_expected_action = f"TP settlement INR {amount} awaiting {tier['tier']} dual-control approval"
    _audit(db, case, user, "TP_SETTLEMENT_PROPOSED", {"proposal_id": proposal["proposal_id"], "amount": str(amount), "tier": tier["tier"]})
    return proposal


def decide_settlement(
    db: Session,
    case: TPClaimCase,
    claim: Claim,
    user: UserContext,
    *,
    proposal_id: str,
    decision: str,
    rationale: str,
) -> dict[str, Any]:
    _require_role(user, ROLES_APPROVER, "decide a settlement")
    _assert_open(case)
    rule = tp_rule(db)
    if decision not in {"approved", "rejected"}:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "decision must be 'approved' or 'rejected'", status_code=400)
    proposals = list(case.settlement_proposals or [])
    idx = next((i for i, p in enumerate(proposals) if p["proposal_id"] == proposal_id), None)
    if idx is None:
        raise DomainError(ErrorCode.NOT_FOUND, "Settlement proposal not found", status_code=404)
    proposal = dict(proposals[idx])
    if proposal["status"] != "pending_approval":
        raise DomainError(ErrorCode.STATE_CONFLICT, f"Proposal is already {proposal['status']}", status_code=409)
    if proposal["proposed_by"]["user_id"] == user.user_id:
        raise DomainError(ErrorCode.NOT_AUTHORISED, "Maker-checker violation: the proposer cannot approve or reject their own settlement", status_code=403)
    if any(a["user_id"] == user.user_id for a in proposal["approvals"]):
        raise DomainError(ErrorCode.NOT_AUTHORISED, "Each approver must be a distinct user; you have already decided this proposal", status_code=403)
    clean_rationale = _clean(rationale)
    if len(clean_rationale) < 10:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "A decision rationale (min 10 characters) is mandatory", status_code=400)
    assert_fraud_score_never_rejects(decision=decision, fraud_signal_score=claim.fraud_signal_score, rationale=clean_rationale)

    required = list(proposal["required_approver_roles"])
    filled = {a["slot"] for a in proposal["approvals"] if a["decision"] == "approved"}
    open_slots = [r for r in required if r not in filled]
    if user.role.value in open_slots:
        slot = user.role.value
    elif user.role == Role.ADMIN and open_slots:
        slot = open_slots[-1]
    else:
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            f"Tier {proposal['approval_tier']} still needs approval from role(s) {open_slots}; '{user.role.value}' cannot fill an open slot",
            status_code=403,
        )
    proposal["approvals"] = [
        *proposal["approvals"],
        {**_actor(user), "slot": slot, "decision": decision, "rationale": clean_rationale, "decided_at": _iso(_utcnow())},
    ]
    if decision == "rejected":
        proposal["status"] = "rejected"
        claim.next_expected_action = "TP settlement rejected by approver; revise the proposal or revisit the legal decision"
    else:
        filled_after = {a["slot"] for a in proposal["approvals"] if a["decision"] == "approved"}
        if all(r in filled_after for r in required):
            proposal["status"] = "approved"
            case.approved_proposal_id = proposal["proposal_id"]
    proposals[idx] = proposal
    case.settlement_proposals = proposals
    _audit(db, case, user, "TP_SETTLEMENT_DECISION", {"proposal_id": proposal_id, "decision": decision, "slot": slot, "status": proposal["status"]})
    if proposal["status"] == "approved":
        _enter_stage(db, case, claim, rule, TPStage.SETTLEMENT_APPROVED.value, user, note=f"{proposal['approval_tier']} dual-control approval complete")
        emit_outbox_event(
            db,
            tenant_id=case.tenant_id,
            aggregate_id=claim.id,
            event_type="TPSettlementApproved",
            payload={"tp_case_id": case.id, "proposal_id": proposal_id, "amount_inr": proposal["amount_inr"], "tier": proposal["approval_tier"]},
        )
    return proposal


def authorise_payment(
    db: Session,
    case: TPClaimCase,
    claim: Claim,
    user: UserContext,
    *,
    idempotency_key: str,
    payee_type: str,
    payee_name: str,
    account_last4: str = "",
    ifsc: str = "",
    simulate_timeout: bool = False,
) -> dict[str, Any]:
    _require_role(user, ROLES_FINANCE, "authorise TP payments")
    _assert_open(case)
    rule = tp_rule(db)
    existing = case.payment_authorisation or {}
    if existing.get("idempotency_key") == idempotency_key:
        return {**existing, "idempotent_replay": True}
    if existing.get("status") in {"released", "timeout_reconcile_pending"}:
        raise DomainError(ErrorCode.DUPLICATE_REQUEST, "A payment has already been authorised for this TP case; reconcile instead of re-issuing", status_code=409)
    if case.stage != TPStage.SETTLEMENT_APPROVED.value or not case.approved_proposal_id:
        raise DomainError(ErrorCode.HUMAN_REVIEW_REQUIRED, "Payment can only be authorised for a dual-control-approved TP settlement", status_code=409)
    if payee_type not in {"claimant", "tribunal_deposit"}:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "payee_type must be 'claimant' or 'tribunal_deposit'", status_code=400)
    proposal = next(p for p in case.settlement_proposals if p["proposal_id"] == case.approved_proposal_id)
    involved = {proposal["proposed_by"]["user_id"], *(a["user_id"] for a in proposal["approvals"]), (case.legal_review.get("signed_by") or {}).get("user_id")}
    if user.user_id in involved:
        raise DomainError(ErrorCode.NOT_AUTHORISED, "Separation of duties: the payment releaser cannot be the proposer, approver or legal reviewer on this case", status_code=403)
    amount = Decimal(proposal["amount_inr"])
    if user.role != Role.ADMIN and amount > Decimal(str(rule["controls"]["payment_release_max_inr"])):
        raise DomainError(ErrorCode.HUMAN_REVIEW_REQUIRED, "Amount exceeds finance release authority; escalate to the Claims Committee", status_code=403)

    bank = IntegrationAdapterRegistry.validate_bank_account(account_last4 or "0000", ifsc or "MOCK0000000")
    pg = IntegrationAdapterRegistry.execute_payment(idempotency_key=idempotency_key, amount_inr=amount, payee_name=payee_name, simulate_timeout=simulate_timeout)
    record = {
        "idempotency_key": idempotency_key,
        "status": "released" if pg["status"] == "confirmed" else pg["status"],
        "payee_type": payee_type,
        "payee_name": _clean(payee_name, max_len=200),
        "bank_account_masked": bank["account_masked"],
        "amount_inr": str(amount),
        "gateway_reference": pg["gateway_reference"],
        "mode": pg.get("mode", "MOCK"),
        "proposal_id": proposal["proposal_id"],
        "authorised_by": _actor(user),
        "authorised_at": _iso(_utcnow()),
    }
    case.payment_authorisation = record
    _audit(db, case, user, "TP_PAYMENT_AUTHORISED", {"status": record["status"], "amount": str(amount)})
    if record["status"] == "released":
        _enter_stage(db, case, claim, rule, TPStage.PAYMENT_AUTHORISED.value, user, note="Finance released the approved TP payment")
        emit_outbox_event(
            db,
            tenant_id=case.tenant_id,
            aggregate_id=claim.id,
            event_type="TPPaymentAuthorised",
            payload={"tp_case_id": case.id, "amount_inr": str(amount), "gateway_reference": pg["gateway_reference"]},
        )
    return record


def reconcile_payment(db: Session, case: TPClaimCase, claim: Claim, user: UserContext) -> dict[str, Any]:
    """Safe reconciliation of a timed-out TP payment instruction (never issues a second payout)."""
    _require_role(user, ROLES_FINANCE, "reconcile TP payments")
    rule = tp_rule(db)
    pay = dict(case.payment_authorisation or {})
    if pay.get("status") != "timeout_reconcile_pending":
        raise DomainError(ErrorCode.STATE_CONFLICT, "No timed-out TP payment is awaiting reconciliation", status_code=409)
    res = IntegrationAdapterRegistry.reconcile_payment(pay["gateway_reference"])
    pay["status"] = "released" if res["status"] == "confirmed" else pay["status"]
    pay["reconciled_by"] = _actor(user)
    pay["reconciled_at"] = _iso(_utcnow())
    case.payment_authorisation = pay
    _audit(db, case, user, "TP_PAYMENT_RECONCILED", {"status": pay["status"]})
    if pay["status"] == "released":
        _enter_stage(db, case, claim, rule, TPStage.PAYMENT_AUTHORISED.value, user, note="TP payment reconciled and confirmed")
    return {k: v for k, v in pay.items() if k != "idempotency_key"}


def close_case(db: Session, case: TPClaimCase, claim: Claim, user: UserContext, *, closure_notes: str, recovery_action_opened: bool = False) -> TPClaimCase:
    _require_role(user, {Role.CLAIMS_MANAGER, Role.ADMIN}, "close a TP case")
    rule = tp_rule(db)
    if case.stage != TPStage.PAYMENT_AUTHORISED.value:
        raise DomainError(ErrorCode.STATE_CONFLICT, "A TP case can be closed only after payment authorisation (PAYMENT_AUTHORISED)", status_code=409)
    la = case.liability_assessment or {}
    if la.get("recovery_rights_flag") and not recovery_action_opened:
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            "Policy defence(s) recorded: confirm that a recovery action against the insured has been opened before closure",
            status_code=409,
        )
    notes = _clean(closure_notes)
    if len(notes) < 15:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "Closure notes (min 15 characters) are mandatory", status_code=400)
    case.closure = {"notes": notes, "recovery_action_opened": bool(recovery_action_opened), "closed_by": _actor(user), "closed_at": _iso(_utcnow())}
    _enter_stage(db, case, claim, rule, TPStage.CLOSED.value, user, note="Closure review completed by manager")
    claim.next_expected_action = "TP case closed"
    _audit(db, case, user, "TP_CASE_CLOSED", {"recovery_action_opened": recovery_action_opened})
    return case


def advance_stage(db: Session, case: TPClaimCase, claim: Claim, user: UserContext, *, note: str = "") -> TPClaimCase:
    """Human-initiated stage advance. Blocked unless every exit gate of the current stage is satisfied."""
    _require_role(user, ROLES_HANDLING, "advance the TP stage")
    _assert_open(case)
    rule = tp_rule(db)
    if case.stage not in ADVANCE_ACTION_STAGES:
        raise DomainError(
            ErrorCode.STATE_CONFLICT,
            f"Stage {case.stage} is advanced only by its controlled action (settlement approval, payment authorisation or closure)",
            status_code=409,
        )
    stage_owner = rule["stage_catalogue"][case.stage]["owner_role"]
    if stage_owner == "legal_tp" and user.role not in {Role.LEGAL_TP, Role.ADMIN}:
        raise DomainError(ErrorCode.NOT_AUTHORISED, f"Stage {case.stage} is owned by Legal/TP; only Legal/TP can advance it", status_code=403)
    blockers = evaluate_gates(db, case, rule)
    if blockers:
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            f"Stage gate(s) not satisfied for {case.stage}: " + "; ".join(b["message"] for b in blockers),
            status_code=409,
            details={"blockers": blockers, "stage": case.stage},
        )
    nxt = next_stage_after(case, rule)
    if not nxt:
        raise DomainError(ErrorCode.STATE_CONFLICT, "No further stage is available", status_code=409)
    cur_idx = STAGE_ORDER.index(case.stage)
    skipped = [s for s in STAGE_ORDER[cur_idx + 1 : STAGE_ORDER.index(nxt)]]
    # Reserve advisory: when moving into SETTLEMENT_CONTROL the reserve must already be on file (checked by the gate).
    _enter_stage(db, case, claim, rule, nxt, user, note=_clean(note, max_len=300), skipped=skipped)
    _audit(db, case, user, "TP_STAGE_ADVANCED", {"to": nxt, "skipped_by_rule": skipped})
    return case


# ----------------------------------------------------------------------------------------------
# Advisory (non-binding) signals, serialization and dashboards
# ----------------------------------------------------------------------------------------------
def compute_tp_advisory(db: Session, case: TPClaimCase, claim: Claim, rule: dict[str, Any] | None = None) -> dict[str, Any]:
    """Deterministic, explainable, NON-BINDING signals to help the human team. Never advances or decides anything."""
    rule = rule or tp_rule(db)
    thresholds = rule["advisory_thresholds"]
    req = required_documents(case, rule)
    have = {d["doc_type"] for d in case.legal_documents or [] if d.get("status") in {"received", "verified"}}
    completeness = round(100 * len([d for d in req if d in have]) / len(req)) if req else 100

    severities = [p.get("injury_severity") for p in case.third_parties or [] if p.get("injury_severity")]
    med_sev = (case.medical_review or {}).get("injury_severity")
    if med_sev:
        severities.append(med_sev)
    bands = rule["reserve_bands_by_injury_severity"]
    if case.tp_category == "property_damage":
        suggested = Decimal(rule["categories"]["property_damage"]["default_reserve_inr"])
    elif severities:
        suggested = max(Decimal(bands[s]) for s in severities)
    else:
        suggested = Decimal(rule["categories"][case.tp_category]["default_reserve_inr"])

    flags: list[dict[str, str]] = []
    created = claim.created_at if claim.created_at.tzinfo else claim.created_at.replace(tzinfo=timezone.utc)
    inc = claim.incident_at if claim.incident_at.tzinfo else claim.incident_at.replace(tzinfo=timezone.utc)
    if (created - inc).days > int(thresholds["late_intimation_days"]):
        flags.append({"code": "LATE_INTIMATION", "message": f"Intimation was more than {thresholds['late_intimation_days']} days after the incident; legal to consider policy condition impact."})
    fir_date = (case.police_report or {}).get("fir_date")
    if fir_date:
        fd = datetime.fromisoformat(fir_date)
        fd = fd if fd.tzinfo else fd.replace(tzinfo=timezone.utc)
        if (fd - inc).days > int(thresholds["late_fir_days"]):
            flags.append({"code": "LATE_FIR", "message": f"FIR filed more than {thresholds['late_fir_days']} days after the incident."})
    reserve = Decimal(str(case.reserve_inr or 0))
    ratio = Decimal(str(thresholds["claimant_demand_to_reserve_ratio_flag"]))
    for p in case.third_parties or []:
        if p.get("claimant_demand_inr") and reserve > 0 and Decimal(p["claimant_demand_inr"]) > reserve * ratio:
            flags.append({"code": "DEMAND_EXCEEDS_RESERVE", "message": "A claimant demand materially exceeds the current reserve; reserve adequacy review suggested."})
            break
    if (case.liability_assessment or {}).get("policy_defences"):
        flags.append({"code": "RECOVERY_RIGHTS", "message": "A policy defence is recorded; pay-and-recover rights against the insured need legal evaluation."})
    if case.coverage_status == "flagged":
        flags.append({"code": "COVERAGE_FLAGGED", "message": "Coverage flagged at intake; legal must decide statutory liability. Never auto-declined."})
    if (claim.fraud_signal_score or 0) and Decimal(str(claim.fraud_signal_score)) > Decimal("0.500"):
        flags.append({"code": "FRAUD_SIGNAL_ADVISORY", "message": "Advisory fraud signal elevated: route to SIU review. A fraud score alone can never reject a claim."})

    return {
        "binding": False,
        "ai_determines_liability": False,
        "documentation_completeness_pct": completeness,
        "missing_documents": [d for d in req if d not in have],
        "suggested_reserve_inr": str(suggested),
        "suggested_reserve_basis": "Deterministic reserve band from recorded injury severity (IN-TP-LIABILITY-2026); human sets the actual reserve.",
        "flags": flags,
    }


def _mask_party(p: dict[str, Any], can_view: bool) -> dict[str, Any]:
    if can_view or not p.get("is_restricted_tp_medical"):
        return p
    return {**p, "name": "[RESTRICTED TP/MEDICAL RECORD]", "notes": "", "injury_severity": None, "claimant_demand_inr": None}


def serialize_tp_case(db: Session, case: TPClaimCase, claim: Claim, user: UserContext) -> dict[str, Any]:
    rule = tp_rule(db)
    view = can_view_restricted(user)
    path = stage_path(case, rule)
    blockers = evaluate_gates(db, case, rule)
    spec = rule["stage_catalogue"][case.stage]
    open_tasks = (
        db.query(ClaimTask)
        .filter(ClaimTask.claim_id == claim.id, ClaimTask.task_type.like("tp_%"))
        .order_by(ClaimTask.created_at.desc())
        .all()
    )
    return {
        "tp_case_id": case.id,
        "case_number": case.case_number,
        "claim_id": claim.id,
        "claim_number": claim.claim_number,
        "linked_od_claim_id": case.linked_od_claim_id,
        "tp_category": case.tp_category,
        "category_label": rule["categories"][case.tp_category]["label"],
        "stage": case.stage,
        "queue": case.queue_name,
        "owner_role": spec["owner_role"],
        "stage_sla_hours": spec["sla_hours"],
        "stage_path": path,
        "stage_history": case.stage_history,
        "gate_blockers": blockers,
        "can_advance": not blockers and case.stage in ADVANCE_ACTION_STAGES,
        "next_stage": next_stage_after(case, rule),
        "coverage": {"status": case.coverage_status, "notes": case.coverage_notes},
        "third_parties": [_mask_party(p, view) for p in case.third_parties or []],
        "accident_facts": case.accident_facts,
        "evidence_items": case.evidence_items,
        "police_report": case.police_report,
        "liability_assessment": case.liability_assessment,
        "legal_documents": case.legal_documents,
        "required_documents": required_documents(case, rule),
        "tribunal": case.tribunal,
        "advocates": case.advocates,
        "medical_review": case.medical_review if view else {"status": (case.medical_review or {}).get("status"), "restricted": True},
        "legal_review": case.legal_review,
        "reserve_inr": str(case.reserve_inr),
        "reserve_history": case.reserve_history,
        "settlement_proposals": case.settlement_proposals,
        "approved_proposal_id": case.approved_proposal_id,
        "payment_authorisation": {k: v for k, v in (case.payment_authorisation or {}).items() if k != "idempotency_key"},
        "closure": case.closure,
        "advisory": compute_tp_advisory(db, case, claim, rule),
        "tasks": [
            {"id": t.id, "task_type": t.task_type, "status": t.status, "assigned_role": t.assigned_role, "queue": (t.metadata_json or {}).get("queue"), "due_at": _iso(t.due_at)}
            for t in open_tasks
        ],
        "controls": {
            "rule_id": rule["rule_id"],
            "rule_version": rule["version"],
            "autonomous_settlement_allowed": rule["controls"]["autonomous_settlement_allowed"],
            "ai_may_determine_liability": rule["controls"]["ai_may_determine_liability"],
            "shared_with_od_fast_track": rule["controls"]["shared_with_od_fast_track"],
            "separation_of_duties": rule["controls"]["separation_of_duties"],
            "restricted_medical_visible": view,
        },
    }


def serialize_tp_summary(case: TPClaimCase) -> dict[str, Any]:
    """Small, non-medical projection for embedding in Claim 360."""
    return {
        "tp_case_id": case.id,
        "case_number": case.case_number,
        "tp_category": case.tp_category,
        "stage": case.stage,
        "queue": case.queue_name,
        "reserve_inr": str(case.reserve_inr),
        "workflow_url": f"/api/v1/claims/{case.claim_id}/tp",
        "autonomous_settlement_allowed": False,
    }


def build_tp_dashboard(db: Session, tenant_id: str) -> dict[str, Any]:
    rule = tp_rule(db)
    cases = db.query(TPClaimCase).filter(TPClaimCase.tenant_id == tenant_id).all()
    now = _utcnow()
    by_stage = {s: 0 for s in STAGE_ORDER}
    queues: dict[str, dict[str, Any]] = {}
    for stage, spec in rule["stage_catalogue"].items():
        queues.setdefault(spec["queue"], {"queue": spec["queue"], "stage": stage, "owner_role": spec["owner_role"], "open_cases": 0, "overdue": 0})
    reserve_total = Decimal("0.00")
    pending_approvals = 0
    for c in cases:
        by_stage[c.stage] = by_stage.get(c.stage, 0) + 1
        reserve_total += Decimal(str(c.reserve_inr or 0))
        if any(p["status"] == "pending_approval" for p in c.settlement_proposals or []):
            pending_approvals += 1
        if c.stage != TPStage.CLOSED.value:
            queues[c.queue_name]["open_cases"] += 1
    tasks = (
        db.query(ClaimTask)
        .filter(ClaimTask.tenant_id == tenant_id, ClaimTask.task_type.like("tp_%"), ClaimTask.status == "open")
        .all()
    )
    for t in tasks:
        q = (t.metadata_json or {}).get("queue")
        due = t.due_at if (t.due_at is None or t.due_at.tzinfo) else t.due_at.replace(tzinfo=timezone.utc)
        if q in queues and due and due < now:
            queues[q]["overdue"] += 1
    return {
        "rule_id": rule["rule_id"],
        "total_cases": len(cases),
        "open_cases": len([c for c in cases if c.stage != TPStage.CLOSED.value]),
        "by_stage": by_stage,
        "queues": sorted(queues.values(), key=lambda q: STAGE_ORDER.index(q["stage"])),
        "total_reserve_inr": str(reserve_total),
        "cases_pending_dual_control_approval": pending_approvals,
        "autonomous_settlement_allowed": rule["controls"]["autonomous_settlement_allowed"],
    }


def lifecycle_definition(db: Session) -> dict[str, Any]:
    """Public description of the TP lifecycle (for docs/UI), including how it differs from OD."""
    rule = tp_rule(db)
    return {
        "rule_id": rule["rule_id"],
        "rule_version": rule["version"],
        "stages": [{"stage": s, **rule["stage_catalogue"][s]} for s in STAGE_ORDER],
        "categories": rule["categories"],
        "settlement_approval_tiers": rule["settlement_approval_tiers"],
        "controls": rule["controls"],
        "od_vs_tp": {
            "own_damage": ["Coverage validation", "Inspection", "Damage assessment", "Garage coordination", "Estimate validation", "Depreciation & deductible", "Settlement / cashless", "Payment & reconciliation"],
            "third_party": [s.replace("_", " ").title() for s in STAGE_ORDER],
        },
    }
