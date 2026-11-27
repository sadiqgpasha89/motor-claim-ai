"""Loader for the product framework rule (IN-PRODUCT-FRAMEWORK-2026)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from services.rules_engine.loader import get_active_rule

PRODUCT_RULE_ID = "IN-PRODUCT-FRAMEWORK-2026"


def product_framework(db: Session | None = None) -> dict[str, Any]:
    return dict(get_active_rule(db, PRODUCT_RULE_ID)["controls"])
