from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from services.claims.models import RuleVersion

RULES_DIR = Path(__file__).resolve().parents[2] / "rules"


def load_rule_files() -> dict[str, dict[str, Any]]:
    rules: dict[str, dict[str, Any]] = {}
    for path in sorted(RULES_DIR.rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        rule_id = data["rule_id"]
        rules[rule_id] = data
    return rules


def sync_rules_to_db(db: Session) -> list[RuleVersion]:
    file_rules = load_rule_files()
    synced: list[RuleVersion] = []
    for rule_id, payload in file_rules.items():
        existing = (
            db.query(RuleVersion)
            .filter(RuleVersion.rule_id == rule_id, RuleVersion.version == payload["version"])
            .first()
        )
        if not existing:
            eff = datetime.fromisoformat(payload["effective_from"].replace("Z", "+00:00"))
            existing = RuleVersion(
                rule_id=rule_id,
                version=payload["version"],
                jurisdiction=payload.get("jurisdiction", "IN"),
                title=payload["title"],
                source_reference=payload["source_reference"],
                owner=payload["owner"],
                status=payload.get("status", "published"),
                payload=payload,
                effective_from=eff,
                approved_by="Synthetic Demo Compliance Seed",
            )
            db.add(existing)
        synced.append(existing)
    db.commit()
    return synced


def get_active_rule(db: Session | None, rule_id: str) -> dict[str, Any]:
    if db is not None:
        now = datetime.now(timezone.utc)
        rec = (
            db.query(RuleVersion)
            .filter(
                RuleVersion.rule_id == rule_id,
                RuleVersion.status == "published",
                RuleVersion.effective_from <= now,
            )
            .order_by(RuleVersion.effective_from.desc())
            .first()
        )
        if rec:
            return rec.payload

    file_rules = load_rule_files()
    if rule_id not in file_rules:
        raise KeyError(f"Rule '{rule_id}' not found")
    return file_rules[rule_id]
