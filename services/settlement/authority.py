from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from packages.contracts.errors import DomainError, ErrorCode
from packages.security.auth import Role, UserContext
from services.rules_engine.loader import get_active_rule
from services.workflow.risk_engine import assert_fraud_score_never_rejects


def validate_approval_authority(
    db: Session,
    *,
    user: UserContext,
    claim_type: str,
    amount_inr: Decimal,
    active_conditions: list[str],
    maker_user_id: str | None = None,
    decision: str = "approved",
    rationale: str = "",
    fraud_signal_score: Decimal | float | str | None = None,
) -> str:
    """Enforces Delegation of Authority, Maker-Checker separation, and fraud non-rejection."""
    assert_fraud_score_never_rejects(
        decision=decision,
        fraud_signal_score=fraud_signal_score,
        rationale=rationale,
    )
    doa = get_active_rule(db, "IN-DOA-MATRIX-2026")

    if maker_user_id and doa.get("forbid_same_user_maker_checker", True):
        if user.user_id == maker_user_id:
            raise DomainError(
                ErrorCode.NOT_AUTHORISED,
                "Maker-checker violation: the same user cannot both recommend and approve a settlement",
                status_code=403,
            )

    if user.role == Role.ADMIN:
        return f"{doa['rule_id']}:{doa['version']}"

    tiers = {t["role"]: t for t in doa["authority_tiers"]}
    tier = tiers.get(user.role.value)
    if not tier:
        raise DomainError(
            ErrorCode.NOT_AUTHORISED,
            f"Role '{user.role.value}' has no settlement/payment approval authority",
            status_code=403,
        )

    max_amt = Decimal(str(tier["max_settlement_inr"]))
    if amount_inr > max_amt:
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            f"Amount INR {amount_inr} exceeds {user.role.value} limit of INR {max_amt}; escalate to higher authority",
            status_code=403,
        )

    if claim_type not in tier["allowed_claim_types"]:
        raise DomainError(
            ErrorCode.NOT_AUTHORISED,
            f"Role '{user.role.value}' cannot approve claim type '{claim_type}'",
            status_code=403,
        )

    disallowed = set(tier.get("disallowed_conditions", [])) & set(active_conditions)
    if disallowed:
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            f"Specialist/manager approval required due to active conditions: {sorted(disallowed)}",
            status_code=403,
        )

    return f"{doa['rule_id']}:{doa['version']}"


def resolve_required_authority(
    doa: dict[str, Any],
    *,
    amount_inr: Decimal,
    claim_type: str,
    active_conditions: list[str],
) -> dict[str, Any]:
    """Resolves which Delegation-of-Authority tier must approve a settlement (read-only, no user needed).

    Mirrors the checks in ``validate_approval_authority``: amount limit, allowed claim types and
    disallowed conditions. Tiers are tried from the lowest limit upwards; every tier that is skipped is
    reported with a reason code so the approval decision can be explained.
    """
    tiers = sorted(doa["authority_tiers"], key=lambda t: Decimal(str(t["max_settlement_inr"])))
    skipped: list[dict[str, str]] = []
    resolved: dict[str, Any] | None = None
    for tier in tiers:
        max_amt = Decimal(str(tier["max_settlement_inr"]))
        blocked = sorted(set(tier.get("disallowed_conditions", [])) & set(active_conditions))
        if amount_inr > max_amt:
            skipped.append({"role": tier["role"], "reason_code": "amount_exceeds_limit"})
        elif claim_type not in tier["allowed_claim_types"]:
            skipped.append({"role": tier["role"], "reason_code": "claim_type_not_allowed"})
        elif blocked:
            skipped.append({"role": tier["role"], "reason_code": "condition_blocked"})
        else:
            resolved = tier
            break
    if resolved is None:
        resolved = tiers[-1]
    release = next(
        (t["role"] for t in doa["authority_tiers"] if t.get("required_for_payment_release")),
        resolved["role"],
    )
    return {
        "checker_role": resolved["role"],
        "max_settlement_inr": str(Decimal(str(resolved["max_settlement_inr"])).quantize(Decimal("0.01"))),
        "payment_release_role": release,
        "skipped_tiers": skipped,
        "rule_version": f"{doa['rule_id']}:{doa['version']}",
    }
