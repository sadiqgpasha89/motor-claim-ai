from __future__ import annotations

from enum import Enum

from packages.contracts.errors import DomainError, ErrorCode


class ClaimStatus(str, Enum):
    # Recommended Enterprise Orchestrator Workflow States
    SUBMITTED = "SUBMITTED"
    REGISTERED = "REGISTERED"
    VALIDATION = "VALIDATION"
    TRIAGE = "TRIAGE"
    FAST_TRACK = "FAST_TRACK"
    SURVEY_REQUIRED = "SURVEY_REQUIRED"
    INVESTIGATION_REQUIRED = "INVESTIGATION_REQUIRED"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    ASSESSMENT = "ASSESSMENT"
    ESTIMATE_VALIDATION = "ESTIMATE_VALIDATION"
    SETTLEMENT_PENDING_APPROVAL = "SETTLEMENT_PENDING_APPROVAL"
    APPROVED = "APPROVED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_RECONCILIATION = "PAYMENT_RECONCILIATION"
    CLOSED = "CLOSED"

    # Granular / Legacy Compatibility & Exception States
    INTIMATED = "INTIMATED"
    EVIDENCE_PENDING = "EVIDENCE_PENDING"
    COVERAGE_CHECKED = "COVERAGE_CHECKED"
    TRIAGED = "TRIAGED"
    SURVEY_ASSIGNED = "SURVEY_ASSIGNED"
    AI_ASSESSMENT = "AI_ASSESSMENT"
    ESTIMATE_REVIEW = "ESTIMATE_REVIEW"
    SETTLEMENT_RECOMMENDED = "SETTLEMENT_RECOMMENDED"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    PAYMENT_INITIATED = "PAYMENT_INITIATED"
    REPAIR_IN_PROGRESS = "REPAIR_IN_PROGRESS"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
    DECLINED_PARTIAL = "DECLINED_PARTIAL"
    REOPENED = "REOPENED"


class TriageTrack(str, Enum):
    FAST_TRACK = "FAST_TRACK"
    SURVEY_REQUIRED = "SURVEY_REQUIRED"
    INVESTIGATION_REQUIRED = "INVESTIGATION_REQUIRED"
    HUMAN_REVIEW = "HUMAN_REVIEW"


CANONICAL_WORKFLOW_STATES: list[str] = [
    ClaimStatus.SUBMITTED.value,
    ClaimStatus.REGISTERED.value,
    ClaimStatus.VALIDATION.value,
    ClaimStatus.TRIAGE.value,
    ClaimStatus.FAST_TRACK.value,
    ClaimStatus.SURVEY_REQUIRED.value,
    ClaimStatus.INVESTIGATION_REQUIRED.value,
    ClaimStatus.HUMAN_REVIEW.value,
    ClaimStatus.ASSESSMENT.value,
    ClaimStatus.ESTIMATE_VALIDATION.value,
    ClaimStatus.SETTLEMENT_PENDING_APPROVAL.value,
    ClaimStatus.APPROVED.value,
    ClaimStatus.PAYMENT_PENDING.value,
    ClaimStatus.PAYMENT_RECONCILIATION.value,
    ClaimStatus.CLOSED.value,
]

LEGACY_TO_CANONICAL_STATE: dict[str, str] = {
    ClaimStatus.SUBMITTED.value: ClaimStatus.SUBMITTED.value,
    ClaimStatus.INTIMATED.value: ClaimStatus.SUBMITTED.value,
    ClaimStatus.REGISTERED.value: ClaimStatus.REGISTERED.value,
    ClaimStatus.VALIDATION.value: ClaimStatus.VALIDATION.value,
    ClaimStatus.EVIDENCE_PENDING.value: ClaimStatus.VALIDATION.value,
    ClaimStatus.COVERAGE_CHECKED.value: ClaimStatus.VALIDATION.value,
    ClaimStatus.TRIAGE.value: ClaimStatus.TRIAGE.value,
    ClaimStatus.TRIAGED.value: ClaimStatus.TRIAGE.value,
    ClaimStatus.FAST_TRACK.value: ClaimStatus.FAST_TRACK.value,
    ClaimStatus.SURVEY_REQUIRED.value: ClaimStatus.SURVEY_REQUIRED.value,
    ClaimStatus.SURVEY_ASSIGNED.value: ClaimStatus.SURVEY_REQUIRED.value,
    ClaimStatus.INVESTIGATION_REQUIRED.value: ClaimStatus.INVESTIGATION_REQUIRED.value,
    ClaimStatus.HUMAN_REVIEW.value: ClaimStatus.HUMAN_REVIEW.value,
    ClaimStatus.CLARIFICATION_REQUESTED.value: ClaimStatus.HUMAN_REVIEW.value,
    ClaimStatus.ASSESSMENT.value: ClaimStatus.ASSESSMENT.value,
    ClaimStatus.AI_ASSESSMENT.value: ClaimStatus.ASSESSMENT.value,
    ClaimStatus.ESTIMATE_VALIDATION.value: ClaimStatus.ESTIMATE_VALIDATION.value,
    ClaimStatus.ESTIMATE_REVIEW.value: ClaimStatus.ESTIMATE_VALIDATION.value,
    ClaimStatus.SETTLEMENT_PENDING_APPROVAL.value: ClaimStatus.SETTLEMENT_PENDING_APPROVAL.value,
    ClaimStatus.SETTLEMENT_RECOMMENDED.value: ClaimStatus.SETTLEMENT_PENDING_APPROVAL.value,
    ClaimStatus.APPROVAL_PENDING.value: ClaimStatus.SETTLEMENT_PENDING_APPROVAL.value,
    ClaimStatus.APPROVED.value: ClaimStatus.APPROVED.value,
    ClaimStatus.PAYMENT_PENDING.value: ClaimStatus.PAYMENT_PENDING.value,
    ClaimStatus.PAYMENT_INITIATED.value: ClaimStatus.PAYMENT_PENDING.value,
    ClaimStatus.PAYMENT_RECONCILIATION.value: ClaimStatus.PAYMENT_RECONCILIATION.value,
    ClaimStatus.REPAIR_IN_PROGRESS.value: ClaimStatus.PAYMENT_RECONCILIATION.value,
    ClaimStatus.CLOSED.value: ClaimStatus.CLOSED.value,
    ClaimStatus.DECLINED_PARTIAL.value: ClaimStatus.DECLINED_PARTIAL.value,
    ClaimStatus.REOPENED.value: ClaimStatus.REOPENED.value,
}


def to_canonical_state(status: str) -> str:
    return LEGACY_TO_CANONICAL_STATE.get(status, status)


ALLOWED_TRANSITIONS: dict[ClaimStatus, set[ClaimStatus]] = {
    # Canonical Recommended Workflow Model
    ClaimStatus.SUBMITTED: {
        ClaimStatus.REGISTERED,
        ClaimStatus.EVIDENCE_PENDING,
        ClaimStatus.HUMAN_REVIEW,
    },
    ClaimStatus.REGISTERED: {
        ClaimStatus.VALIDATION,
        ClaimStatus.EVIDENCE_PENDING,
        ClaimStatus.COVERAGE_CHECKED,
        ClaimStatus.TRIAGE,
        ClaimStatus.TRIAGED,
        ClaimStatus.HUMAN_REVIEW,
        ClaimStatus.CLARIFICATION_REQUESTED,
    },
    ClaimStatus.VALIDATION: {
        ClaimStatus.TRIAGE,
        ClaimStatus.TRIAGED,
        ClaimStatus.COVERAGE_CHECKED,
        ClaimStatus.INVESTIGATION_REQUIRED,
        ClaimStatus.HUMAN_REVIEW,
        ClaimStatus.CLARIFICATION_REQUESTED,
        ClaimStatus.DECLINED_PARTIAL,
    },
    ClaimStatus.TRIAGE: {
        ClaimStatus.FAST_TRACK,
        ClaimStatus.SURVEY_REQUIRED,
        ClaimStatus.INVESTIGATION_REQUIRED,
        ClaimStatus.HUMAN_REVIEW,
        ClaimStatus.ASSESSMENT,
        ClaimStatus.SURVEY_ASSIGNED,
        ClaimStatus.AI_ASSESSMENT,
        ClaimStatus.ESTIMATE_VALIDATION,
    },
    ClaimStatus.FAST_TRACK: {
        ClaimStatus.ASSESSMENT,
        ClaimStatus.ESTIMATE_VALIDATION,
        ClaimStatus.SURVEY_REQUIRED,
        ClaimStatus.INVESTIGATION_REQUIRED,
        ClaimStatus.HUMAN_REVIEW,
    },
    ClaimStatus.SURVEY_REQUIRED: {
        ClaimStatus.ASSESSMENT,
        ClaimStatus.SURVEY_ASSIGNED,
        ClaimStatus.ESTIMATE_VALIDATION,
        ClaimStatus.INVESTIGATION_REQUIRED,
        ClaimStatus.HUMAN_REVIEW,
    },
    ClaimStatus.INVESTIGATION_REQUIRED: {
        ClaimStatus.ASSESSMENT,
        ClaimStatus.ESTIMATE_VALIDATION,
        ClaimStatus.HUMAN_REVIEW,
        ClaimStatus.SETTLEMENT_PENDING_APPROVAL,
        ClaimStatus.DECLINED_PARTIAL,
    },
    ClaimStatus.HUMAN_REVIEW: {
        ClaimStatus.VALIDATION,
        ClaimStatus.TRIAGE,
        ClaimStatus.FAST_TRACK,
        ClaimStatus.SURVEY_REQUIRED,
        ClaimStatus.INVESTIGATION_REQUIRED,
        ClaimStatus.ASSESSMENT,
        ClaimStatus.ESTIMATE_VALIDATION,
        ClaimStatus.SETTLEMENT_PENDING_APPROVAL,
        ClaimStatus.APPROVED,
        ClaimStatus.PAYMENT_PENDING,
        ClaimStatus.DECLINED_PARTIAL,
    },
    ClaimStatus.ASSESSMENT: {
        ClaimStatus.ESTIMATE_VALIDATION,
        ClaimStatus.ESTIMATE_REVIEW,
        ClaimStatus.SURVEY_REQUIRED,
        ClaimStatus.INVESTIGATION_REQUIRED,
        ClaimStatus.HUMAN_REVIEW,
        ClaimStatus.SETTLEMENT_PENDING_APPROVAL,
    },
    ClaimStatus.ESTIMATE_VALIDATION: {
        ClaimStatus.SETTLEMENT_PENDING_APPROVAL,
        ClaimStatus.SETTLEMENT_RECOMMENDED,
        ClaimStatus.APPROVAL_PENDING,
        ClaimStatus.ASSESSMENT,
        ClaimStatus.SURVEY_REQUIRED,
        ClaimStatus.INVESTIGATION_REQUIRED,
        ClaimStatus.HUMAN_REVIEW,
        ClaimStatus.CLARIFICATION_REQUESTED,
    },
    ClaimStatus.SETTLEMENT_PENDING_APPROVAL: {
        ClaimStatus.APPROVED,
        ClaimStatus.INVESTIGATION_REQUIRED,
        ClaimStatus.HUMAN_REVIEW,
        ClaimStatus.ESTIMATE_VALIDATION,
        ClaimStatus.CLARIFICATION_REQUESTED,
        ClaimStatus.DECLINED_PARTIAL,
    },
    ClaimStatus.APPROVED: {
        ClaimStatus.PAYMENT_PENDING,
        ClaimStatus.PAYMENT_INITIATED,
        ClaimStatus.REPAIR_IN_PROGRESS,
        ClaimStatus.INVESTIGATION_REQUIRED,
        ClaimStatus.HUMAN_REVIEW,
    },
    ClaimStatus.PAYMENT_PENDING: {
        ClaimStatus.PAYMENT_RECONCILIATION,
        ClaimStatus.PAYMENT_INITIATED,
        ClaimStatus.REPAIR_IN_PROGRESS,
        ClaimStatus.HUMAN_REVIEW,
        ClaimStatus.CLOSED,
    },
    ClaimStatus.PAYMENT_RECONCILIATION: {
        ClaimStatus.CLOSED,
        ClaimStatus.PAYMENT_PENDING,
        ClaimStatus.HUMAN_REVIEW,
        ClaimStatus.ESTIMATE_VALIDATION,
    },
    ClaimStatus.CLOSED: {ClaimStatus.REOPENED},

    # Compatibility Transitions for Granular / Legacy Statuses
    ClaimStatus.INTIMATED: {
        ClaimStatus.SUBMITTED,
        ClaimStatus.REGISTERED,
        ClaimStatus.EVIDENCE_PENDING,
        ClaimStatus.VALIDATION,
    },
    ClaimStatus.EVIDENCE_PENDING: {
        ClaimStatus.VALIDATION,
        ClaimStatus.COVERAGE_CHECKED,
        ClaimStatus.TRIAGE,
        ClaimStatus.TRIAGED,
        ClaimStatus.HUMAN_REVIEW,
        ClaimStatus.CLARIFICATION_REQUESTED,
    },
    ClaimStatus.COVERAGE_CHECKED: {
        ClaimStatus.VALIDATION,
        ClaimStatus.TRIAGE,
        ClaimStatus.TRIAGED,
        ClaimStatus.HUMAN_REVIEW,
        ClaimStatus.CLARIFICATION_REQUESTED,
        ClaimStatus.DECLINED_PARTIAL,
    },
    ClaimStatus.TRIAGED: {
        ClaimStatus.TRIAGE,
        ClaimStatus.FAST_TRACK,
        ClaimStatus.SURVEY_REQUIRED,
        ClaimStatus.INVESTIGATION_REQUIRED,
        ClaimStatus.HUMAN_REVIEW,
        ClaimStatus.SURVEY_ASSIGNED,
        ClaimStatus.AI_ASSESSMENT,
        ClaimStatus.ASSESSMENT,
        ClaimStatus.ESTIMATE_REVIEW,
        ClaimStatus.ESTIMATE_VALIDATION,
        ClaimStatus.CLARIFICATION_REQUESTED,
    },
    ClaimStatus.SURVEY_ASSIGNED: {
        ClaimStatus.SURVEY_REQUIRED,
        ClaimStatus.ASSESSMENT,
        ClaimStatus.ESTIMATE_REVIEW,
        ClaimStatus.ESTIMATE_VALIDATION,
        ClaimStatus.SETTLEMENT_RECOMMENDED,
        ClaimStatus.SETTLEMENT_PENDING_APPROVAL,
        ClaimStatus.CLARIFICATION_REQUESTED,
        ClaimStatus.HUMAN_REVIEW,
    },
    ClaimStatus.AI_ASSESSMENT: {
        ClaimStatus.ASSESSMENT,
        ClaimStatus.ESTIMATE_REVIEW,
        ClaimStatus.ESTIMATE_VALIDATION,
        ClaimStatus.SURVEY_ASSIGNED,
        ClaimStatus.SURVEY_REQUIRED,
        ClaimStatus.SETTLEMENT_RECOMMENDED,
        ClaimStatus.SETTLEMENT_PENDING_APPROVAL,
    },
    ClaimStatus.ESTIMATE_REVIEW: {
        ClaimStatus.ESTIMATE_VALIDATION,
        ClaimStatus.SETTLEMENT_RECOMMENDED,
        ClaimStatus.SETTLEMENT_PENDING_APPROVAL,
        ClaimStatus.SURVEY_ASSIGNED,
        ClaimStatus.SURVEY_REQUIRED,
        ClaimStatus.AI_ASSESSMENT,
        ClaimStatus.ASSESSMENT,
        ClaimStatus.CLARIFICATION_REQUESTED,
        ClaimStatus.HUMAN_REVIEW,
    },
    ClaimStatus.SETTLEMENT_RECOMMENDED: {
        ClaimStatus.SETTLEMENT_PENDING_APPROVAL,
        ClaimStatus.APPROVAL_PENDING,
        ClaimStatus.ESTIMATE_REVIEW,
        ClaimStatus.ESTIMATE_VALIDATION,
        ClaimStatus.CLARIFICATION_REQUESTED,
        ClaimStatus.HUMAN_REVIEW,
        ClaimStatus.DECLINED_PARTIAL,
    },
    ClaimStatus.APPROVAL_PENDING: {
        ClaimStatus.APPROVED,
        ClaimStatus.CLARIFICATION_REQUESTED,
        ClaimStatus.HUMAN_REVIEW,
        ClaimStatus.DECLINED_PARTIAL,
    },
    ClaimStatus.PAYMENT_INITIATED: {
        ClaimStatus.PAYMENT_RECONCILIATION,
        ClaimStatus.REPAIR_IN_PROGRESS,
        ClaimStatus.CLOSED,
        ClaimStatus.HUMAN_REVIEW,
    },
    ClaimStatus.REPAIR_IN_PROGRESS: {
        ClaimStatus.PAYMENT_RECONCILIATION,
        ClaimStatus.CLOSED,
        ClaimStatus.ESTIMATE_REVIEW,
        ClaimStatus.ESTIMATE_VALIDATION,
    },
    ClaimStatus.CLARIFICATION_REQUESTED: {
        ClaimStatus.VALIDATION,
        ClaimStatus.EVIDENCE_PENDING,
        ClaimStatus.COVERAGE_CHECKED,
        ClaimStatus.TRIAGE,
        ClaimStatus.TRIAGED,
        ClaimStatus.ASSESSMENT,
        ClaimStatus.ESTIMATE_REVIEW,
        ClaimStatus.ESTIMATE_VALIDATION,
        ClaimStatus.HUMAN_REVIEW,
    },
    ClaimStatus.DECLINED_PARTIAL: {
        ClaimStatus.CLOSED,
        ClaimStatus.REOPENED,
    },
    ClaimStatus.REOPENED: {
        ClaimStatus.VALIDATION,
        ClaimStatus.TRIAGE,
        ClaimStatus.TRIAGED,
        ClaimStatus.ESTIMATE_REVIEW,
        ClaimStatus.ESTIMATE_VALIDATION,
        ClaimStatus.SETTLEMENT_RECOMMENDED,
        ClaimStatus.SETTLEMENT_PENDING_APPROVAL,
        ClaimStatus.HUMAN_REVIEW,
    },
}


def validate_transition(current: str, target: str) -> ClaimStatus:
    try:
        cur = ClaimStatus(current)
        tgt = ClaimStatus(target)
    except ValueError as exc:
        raise DomainError(
            ErrorCode.VALIDATION_ERROR,
            f"Unknown claim status '{current}' -> '{target}'",
            status_code=400,
        ) from exc

    if cur == tgt:
        return tgt

    allowed = ALLOWED_TRANSITIONS.get(cur, set())
    if tgt not in allowed:
        raise DomainError(
            ErrorCode.STATE_CONFLICT,
            f"Invalid claim state transition from {cur.value} to {tgt.value}",
            status_code=409,
        )
    return tgt
