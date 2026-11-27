"""Loader for the claims intelligence rules (IN-INTELLIGENCE-2026)."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from services.rules_engine.loader import get_active_rule

INTELLIGENCE_RULE_ID = "IN-INTELLIGENCE-2026"


def intelligence_controls(db: Session | None = None) -> dict[str, Any]:
    return dict(get_active_rule(db, INTELLIGENCE_RULE_ID)["controls"])


def intelligence_rule_version(db: Session | None = None) -> str:
    rule = get_active_rule(db, INTELLIGENCE_RULE_ID)
    return f"{INTELLIGENCE_RULE_ID}:{rule['version']}"


def dec(value: Any) -> Decimal:
    return Decimal(str(value))
