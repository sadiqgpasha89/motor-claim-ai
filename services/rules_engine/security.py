"""Loader for the security controls rule (IN-SECURITY-CONTROLS-2026)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from services.rules_engine.loader import get_active_rule

SECURITY_RULE_ID = "IN-SECURITY-CONTROLS-2026"


def security_controls(db: Session | None = None) -> dict[str, Any]:
    return dict(get_active_rule(db, SECURITY_RULE_ID)["controls"])
