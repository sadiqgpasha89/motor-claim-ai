from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from packages.observability.logging import get_correlation_id
from services.claims.models import AuditEvent, OutboxEvent


def _hash_payload(data: Any) -> str:
    if data is None:
        return ""
    raw = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None)


def compute_event_hash(event: AuditEvent) -> str:
    """Hash of the event fields plus the previous hash. A change to any field or any earlier event changes this value."""
    created = event.created_at.replace(tzinfo=None).isoformat()
    parts = [
        event.prev_event_hash, event.tenant_id, event.claim_id or "", event.actor_id, event.actor_role, event.action,
        event.object_type, event.object_id, event.before_hash, event.after_hash, event.outcome,
        json.dumps(event.details, sort_keys=True, default=str), created,
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def record_audit_event(
    db: Session,
    *,
    tenant_id: str,
    claim_id: Optional[str],
    actor_id: str,
    actor_role: str,
    action: str,
    object_type: str,
    object_id: str,
    before_state: Any = None,
    after_state: Any = None,
    outcome: str = "success",
    details: Optional[dict[str, Any]] = None,
) -> AuditEvent:
    # Sessions here do not autoflush. So the chain head is the newest of: the database head and events still pending in this session.
    # shortcut: this assumes one writer per tenant chain. For many API instances, take a per-tenant lock or a sequence.
    last = (
        db.query(AuditEvent)
        .filter(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .first()
    )
    pending = [o for o in db.new if isinstance(o, AuditEvent) and o.tenant_id == tenant_id]
    if pending:
        newest = max(pending, key=lambda e: e.created_at)
        if last is None or _naive(newest.created_at) >= _naive(last.created_at):
            last = newest
    now = datetime.now(timezone.utc)
    if last is not None:
        last_at = last.created_at if last.created_at.tzinfo else last.created_at.replace(tzinfo=timezone.utc)
        now = max(now, last_at + timedelta(microseconds=1))
    event = AuditEvent(
        prev_event_hash=last.event_hash if last is not None else "",
        created_at=now,
        tenant_id=tenant_id,
        claim_id=claim_id,
        actor_id=actor_id,
        actor_role=actor_role,
        action=action,
        object_type=object_type,
        object_id=object_id,
        before_hash=_hash_payload(before_state),
        after_hash=_hash_payload(after_state),
        correlation_id=get_correlation_id(),
        outcome=outcome,
        details=details or {},
    )
    event.event_hash = compute_event_hash(event)
    db.add(event)
    return event


def verify_audit_chain(db: Session, tenant_id: str) -> dict[str, Any]:
    """Recompute the hash chain. Events from before the chain existed have no hash and are counted, not checked."""
    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        .all()
    )
    legacy = 0
    checked = 0
    prev = ""
    for ev in events:
        if not ev.event_hash:
            legacy += 1
            continue
        if ev.prev_event_hash != prev:
            return {"ok": False, "checked": checked, "legacy_unchained": legacy, "broken_at": ev.id, "reason": "Link to the previous event does not match."}
        if compute_event_hash(ev) != ev.event_hash:
            return {"ok": False, "checked": checked, "legacy_unchained": legacy, "broken_at": ev.id, "reason": "Event content does not match its hash."}
        prev = ev.event_hash
        checked += 1
    return {"ok": True, "checked": checked, "legacy_unchained": legacy, "head_hash": prev}


def emit_outbox_event(
    db: Session,
    *,
    tenant_id: str,
    aggregate_id: str,
    event_type: str,
    payload: dict[str, Any],
    idempotency_key: Optional[str] = None,
) -> OutboxEvent:
    key = idempotency_key or f"{event_type}:{aggregate_id}:{uuid.uuid4()}"
    existing = db.query(OutboxEvent).filter(OutboxEvent.idempotency_key == key).first()
    if existing:
        return existing

    evt = OutboxEvent(
        tenant_id=tenant_id,
        aggregate_id=aggregate_id,
        event_type=event_type,
        correlation_id=get_correlation_id(),
        idempotency_key=key,
        payload=payload,
        status="published_mock",
    )
    db.add(evt)
    return evt
