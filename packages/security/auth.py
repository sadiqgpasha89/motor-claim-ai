from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

import jwt
from fastapi import Depends, Header
from pydantic import BaseModel

from packages.config import get_settings
from packages.contracts.errors import DomainError, ErrorCode


class Role(str, Enum):
    POLICYHOLDER = "policyholder"
    FNOL_EXECUTIVE = "fnol_executive"
    CLAIMS_HANDLER = "claims_handler"
    SURVEYOR = "surveyor"
    GARAGE = "garage"
    SIU_INVESTIGATOR = "siu_investigator"
    CLAIMS_MANAGER = "claims_manager"
    LEGAL_TP = "legal_tp"
    FINANCE_APPROVER = "finance_approver"
    AUDITOR = "auditor"
    ADMIN = "admin"


INTERNAL_ROLES = {
    Role.FNOL_EXECUTIVE,
    Role.CLAIMS_HANDLER,
    Role.SIU_INVESTIGATOR,
    Role.CLAIMS_MANAGER,
    Role.LEGAL_TP,
    Role.FINANCE_APPROVER,
    Role.AUDITOR,
    Role.ADMIN,
}

SIU_ALLOWED_ROLES = {Role.SIU_INVESTIGATOR, Role.CLAIMS_MANAGER, Role.AUDITOR, Role.ADMIN}
TP_LEGAL_ALLOWED_ROLES = {Role.LEGAL_TP, Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.AUDITOR, Role.ADMIN}


class UserContext(BaseModel):
    user_id: str
    tenant_id: str
    email: str
    name: str
    role: Role
    partner_id: Optional[str] = None
    branch: str = "MUM-WEST"


def create_access_token(user: UserContext) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user.user_id,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "name": user.name,
        "role": user.role.value,
        "partner_id": user.partner_id,
        "branch": user.branch,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> UserContext:
    settings = get_settings()
    try:
        data = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return UserContext(
            user_id=data["sub"],
            tenant_id=data["tenant_id"],
            email=data["email"],
            name=data["name"],
            role=Role(data["role"]),
            partner_id=data.get("partner_id"),
            branch=data.get("branch", "MUM-WEST"),
        )
    except Exception as exc:
        raise DomainError(
            ErrorCode.NOT_AUTHORISED,
            "Invalid or expired authentication token",
            status_code=401,
        ) from exc


async def get_current_user(authorization: Optional[str] = Header(default=None)) -> UserContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise DomainError(
            ErrorCode.NOT_AUTHORISED,
            "Authentication required (Bearer token missing)",
            status_code=401,
        )
    token = authorization.split(" ", 1)[1].strip()
    return decode_access_token(token)


def require_roles(*allowed: Role):
    async def _checker(user: UserContext = Depends(get_current_user)) -> UserContext:
        if user.role not in allowed and user.role != Role.ADMIN:
            raise DomainError(
                ErrorCode.NOT_AUTHORISED,
                f"Role '{user.role.value}' is not permitted for this operation",
                status_code=403,
            )
        return user

    return _checker


def enforce_claim_abac(user: UserContext, claim: Any) -> None:
    """Server-side tenant + ABAC isolation check. Never rely on UI hiding."""
    if claim.tenant_id != user.tenant_id:
        raise DomainError(
            ErrorCode.NOT_AUTHORISED,
            "Cross-tenant claim access denied",
            status_code=403,
        )

    if user.role == Role.POLICYHOLDER:
        if claim.customer_id != user.partner_id:
            raise DomainError(
                ErrorCode.NOT_AUTHORISED,
                "Policyholder can only access their own claims",
                status_code=403,
            )
    elif user.role == Role.GARAGE:
        if claim.assigned_garage_id != user.partner_id:
            raise DomainError(
                ErrorCode.NOT_AUTHORISED,
                "Garage can only access claims assigned to their workshop",
                status_code=403,
            )
    elif user.role == Role.SURVEYOR:
        if claim.assigned_surveyor_id != user.partner_id:
            raise DomainError(
                ErrorCode.NOT_AUTHORISED,
                "Surveyor can only access claims assigned to them",
                status_code=403,
            )


def enforce_siu_access(user: UserContext) -> None:
    if user.role not in SIU_ALLOWED_ROLES:
        raise DomainError(
            ErrorCode.NOT_AUTHORISED,
            "SIU fraud investigation records require SIU Investigator, Manager, or Auditor role",
            status_code=403,
        )


def enforce_tp_medical_access(user: UserContext) -> None:
    if user.role not in TP_LEGAL_ALLOWED_ROLES:
        raise DomainError(
            ErrorCode.NOT_AUTHORISED,
            "Third-party medical/legal records require authorised TP/Legal/Claims access",
            status_code=403,
        )
