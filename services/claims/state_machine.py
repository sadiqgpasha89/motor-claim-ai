from __future__ import annotations

from enum import Enum

from packages.contracts.errors import DomainError, ErrorCode


class ClaimStatus(str, Enum):
    INTIMATED = "INTIMATED"
    REGISTERED = "REGISTERED"
    EVIDENCE_PENDING = "EVIDENCE_PENDING"
    COVERAGE_CHECKED = "COVERAGE_CHECKED"
    TRIAGED = "TRIAGED"
    SURVEY_ASSIGNED = "SURVEY_ASSIGNED"
    AI_ASSESSMENT = "AI_ASSESSMENT"
    ESTIMATE_REVIEW = "ESTIMATE_REVIEW"
    SETTLEMENT_RECOMMENDED = "SETTLEMENT_RECOMMENDED"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    APPROVED = "APPROVED"
    PAYMENT_INITIATED = "PAYMENT_INITIATED"
    REPAIR_IN_PROGRESS = "REPAIR_IN_PROGRESS"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
    DECLINED_PARTIAL = "DECLINED_PARTIAL"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


ALLOWED_TRANSITIONS: dict[ClaimStatus, set[ClaimStatus]] = {
    ClaimStatus.INTIMATED: {ClaimStatus.REGISTERED, ClaimStatus.EVIDENCE_PENDING},
    ClaimStatus.REGISTERED: {
        ClaimStatus.EVIDENCE_PENDING,
        ClaimStatus.COVERAGE_CHECKED,
        ClaimStatus.TRIAGED,
        ClaimStatus.CLARIFICATION_REQUESTED,
    },
    ClaimStatus.EVIDENCE_PENDING: {
        ClaimStatus.COVERAGE_CHECKED,
        ClaimStatus.TRIAGED,
        ClaimStatus.CLARIFICATION_REQUESTED,
    },
    ClaimStatus.COVERAGE_CHECKED: {
        ClaimStatus.TRIAGED,
        ClaimStatus.CLARIFICATION_REQUESTED,
        ClaimStatus.DECLINED_PARTIAL,
    },
    ClaimStatus.TRIAGED: {
        ClaimStatus.SURVEY_ASSIGNED,
        ClaimStatus.AI_ASSESSMENT,
        ClaimStatus.ESTIMATE_REVIEW,
        ClaimStatus.CLARIFICATION_REQUESTED,
    },
    ClaimStatus.SURVEY_ASSIGNED: {
        ClaimStatus.ESTIMATE_REVIEW,
        ClaimStatus.SETTLEMENT_RECOMMENDED,
        ClaimStatus.CLARIFICATION_REQUESTED,
    },
    ClaimStatus.AI_ASSESSMENT: {
        ClaimStatus.ESTIMATE_REVIEW,
        ClaimStatus.SURVEY_ASSIGNED,
        ClaimStatus.SETTLEMENT_RECOMMENDED,
    },
    ClaimStatus.ESTIMATE_REVIEW: {
        ClaimStatus.SETTLEMENT_RECOMMENDED,
        ClaimStatus.SURVEY_ASSIGNED,
        ClaimStatus.CLARIFICATION_REQUESTED,
    },
    ClaimStatus.SETTLEMENT_RECOMMENDED: {
        ClaimStatus.APPROVAL_PENDING,
        ClaimStatus.CLARIFICATION_REQUESTED,
        ClaimStatus.DECLINED_PARTIAL,
    },
    ClaimStatus.APPROVAL_PENDING: {
        ClaimStatus.APPROVED,
        ClaimStatus.CLARIFICATION_REQUESTED,
        ClaimStatus.DECLINED_PARTIAL,
    },
    ClaimStatus.APPROVED: {
        ClaimStatus.PAYMENT_INITIATED,
        ClaimStatus.REPAIR_IN_PROGRESS,
    },
    ClaimStatus.PAYMENT_INITIATED: {
        ClaimStatus.REPAIR_IN_PROGRESS,
        ClaimStatus.CLOSED,
    },
    ClaimStatus.REPAIR_IN_PROGRESS: {
        ClaimStatus.CLOSED,
        ClaimStatus.ESTIMATE_REVIEW,
    },
    ClaimStatus.CLARIFICATION_REQUESTED: {
        ClaimStatus.EVIDENCE_PENDING,
        ClaimStatus.COVERAGE_CHECKED,
        ClaimStatus.TRIAGED,
        ClaimStatus.ESTIMATE_REVIEW,
    },
    ClaimStatus.DECLINED_PARTIAL: {
        ClaimStatus.CLOSED,
        ClaimStatus.REOPENED,
    },
    ClaimStatus.CLOSED: {ClaimStatus.REOPENED},
    ClaimStatus.REOPENED: {
        ClaimStatus.TRIAGED,
        ClaimStatus.ESTIMATE_REVIEW,
        ClaimStatus.SETTLEMENT_RECOMMENDED,
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
