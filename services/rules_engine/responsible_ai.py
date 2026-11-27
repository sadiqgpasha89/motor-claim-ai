"""Loader for the responsible AI controls rule (IN-RESPONSIBLE-AI-2026)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from services.rules_engine.loader import get_active_rule

RESPONSIBLE_AI_RULE_ID = "IN-RESPONSIBLE-AI-2026"


def responsible_ai_controls(db: Session | None = None) -> dict[str, Any]:
    return dict(get_active_rule(db, RESPONSIBLE_AI_RULE_ID)["controls"])
