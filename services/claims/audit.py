from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session

from packages.observability.logging import get_correlation_id
from services.claims.models import AuditEvent, OutboxEvent


def _hash_payload(data: Any) -> str:
    if data is None:
        return ""
    raw = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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
    event = AuditEvent(
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
    db.add(event)
    return event


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
