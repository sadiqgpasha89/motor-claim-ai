from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from packages.contracts.errors import DomainError, ErrorCode
from packages.security.auth import Role, UserContext
from services.rules_engine.loader import get_active_rule


def validate_approval_authority(
    db: Session,
    *,
    user: UserContext,
    claim_type: str,
    amount_inr: Decimal,
    active_conditions: list[str],
    maker_user_id: str | None = None,
) -> str:
    """Enforces Delegation of Authority & Maker-Checker separation of duties."""
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
