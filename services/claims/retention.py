"""Evidence retention, legal hold and purge.

Purge removes the stored file bytes and the OCR text. It keeps a tombstone row with the sha256 and the metadata,
so the audit trail still shows that the evidence existed. A legal hold blocks purge. The audit log is never purged here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from services.claims.audit import record_audit_event
from services.claims.models import Claim, Evidence
from services.rules_engine.security import security_controls

PURGED_STATUS = "purged_by_retention"


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def set_legal_hold(db: Session, claim: Claim, *, hold: bool, actor_id: str, actor_role: str, reason: str) -> dict[str, Any]:
    rows = db.query(Evidence).filter(Evidence.claim_id == claim.id, Evidence.tenant_id == claim.tenant_id).all()
    changed = 0
    for ev in rows:
        if ev.legal_hold != hold:
            ev.legal_hold = hold
            changed += 1
    record_audit_event(
        db, tenant_id=claim.tenant_id, claim_id=claim.id, actor_id=actor_id, actor_role=actor_role,
        action="LEGAL_HOLD_PLACED" if hold else "LEGAL_HOLD_RELEASED", object_type="claim", object_id=claim.id,
        details={"reason": reason, "evidence_changed": changed},
    )
    return {"claim_id": claim.id, "legal_hold": hold, "evidence_changed": changed, "evidence_total": len(rows)}


def purge_expired_evidence(db: Session, *, tenant_id: str, actor_id: str, actor_role: str, dry_run: bool = True, now: datetime | None = None) -> dict[str, Any]:
    ctl = security_controls(db)["retention"]
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=365 * int(ctl["evidence_years_after_closure"]))
    claims = db.query(Claim).filter(Claim.tenant_id == tenant_id)
    if ctl["purge_requires_closed_claim"]:
        claims = claims.filter(Claim.status == "CLOSED")
    eligible: list[Evidence] = []
    blocked_by_hold = 0
    for claim in claims.all():
        if _aware(claim.updated_at) > cutoff:
            continue
        for ev in db.query(Evidence).filter(Evidence.claim_id == claim.id, Evidence.doc_status != PURGED_STATUS).all():
            if ev.legal_hold and ctl["purge_blocked_by_legal_hold"]:
                blocked_by_hold += 1
            else:
                eligible.append(ev)
    if not dry_run:
        for ev in eligible:
            path = Path(ev.storage_path)
            if path.is_file():
                path.unlink()
            ev.ocr_text = ""
            ev.doc_status = PURGED_STATUS
            record_audit_event(
                db, tenant_id=tenant_id, claim_id=ev.claim_id, actor_id=actor_id, actor_role=actor_role,
                action="EVIDENCE_PURGED", object_type="evidence", object_id=ev.id, details={"sha256": ev.sha256},
            )
    db.commit()
    return {
        "dry_run": dry_run, "retention_years": ctl["evidence_years_after_closure"], "cutoff": cutoff.isoformat(),
        "eligible": len(eligible), "blocked_by_legal_hold": blocked_by_hold, "purged": 0 if dry_run else len(eligible),
    }
