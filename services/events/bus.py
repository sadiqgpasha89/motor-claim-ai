"""Durable event bus on top of the transactional outbox.

The outbox row is written in the same transaction as the business change. A relay (dispatch_pending) then
delivers each event to each registered consumer. One `event_deliveries` row per (event, consumer) makes
delivery idempotent. A failed delivery retries with backoff. After max attempts it becomes `dead`: this is the
consumer-side dead letter queue, and an operator can replay it.

shortcut: the relay is a function that scans the newest events for a tenant. It is not a long-running broker.
Upgrade to a broker (Kafka, SQS) and a relay worker when event volume needs it. The consumer interface stays the same.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from services.claims.models import EventDelivery, OutboxEvent

Handler = Callable[[Session, OutboxEvent], None]


@dataclass(frozen=True)
class Consumer:
    name: str
    event_types: frozenset[str]  # a single "*" means every event
    handler: Handler


_CONSUMERS: dict[str, Consumer] = {}


def register_consumer(name: str, event_types: set[str] | frozenset[str], handler: Handler) -> None:
    _CONSUMERS[name] = Consumer(name=name, event_types=frozenset(event_types), handler=handler)


def consumers() -> list[Consumer]:
    return list(_CONSUMERS.values())


def _wants(consumer: Consumer, event_type: str) -> bool:
    return "*" in consumer.event_types or event_type in consumer.event_types


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def dispatch_pending(
    db: Session, *, tenant_id: str, now: datetime | None = None, max_attempts: int = 3, limit: int = 200,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    events = (
        db.query(OutboxEvent)
        .filter(OutboxEvent.tenant_id == tenant_id)
        .order_by(OutboxEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    summary = {"delivered": 0, "failed": 0, "dead": 0, "skipped": 0}
    for evt in reversed(events):  # oldest first keeps per-claim order
        for consumer in consumers():
            if not _wants(consumer, evt.event_type):
                continue
            delivery = (
                db.query(EventDelivery)
                .filter(EventDelivery.outbox_event_id == evt.id, EventDelivery.consumer == consumer.name)
                .first()
            )
            if delivery is None:
                delivery = EventDelivery(tenant_id=tenant_id, outbox_event_id=evt.id, consumer=consumer.name)
                db.add(delivery)
                db.flush()
            retry_at = _aware(delivery.next_attempt_at)
            if delivery.status in ("delivered", "dead") or (retry_at is not None and retry_at > now):
                summary["skipped"] += 1
                continue
            try:
                with db.begin_nested():  # a failing handler must not leave half-written rows
                    consumer.handler(db, evt)
            except Exception as exc:  # noqa: BLE001 - any handler failure is a delivery failure
                delivery.attempts += 1
                delivery.last_error = f"{type(exc).__name__}: {exc}"[:500]
                if delivery.attempts >= max_attempts:
                    delivery.status = "dead"
                    summary["dead"] += 1
                else:
                    delivery.status = "failed"
                    delivery.next_attempt_at = now + timedelta(seconds=2 ** delivery.attempts)
                    summary["failed"] += 1
                continue
            delivery.attempts += 1
            delivery.status = "delivered"
            delivery.delivered_at = now
            delivery.last_error = None
            summary["delivered"] += 1
    db.commit()
    return summary


def replay_dead_delivery(db: Session, delivery: EventDelivery) -> EventDelivery:
    """Put a dead delivery back in the queue. The next dispatch retries it from attempt zero."""
    delivery.status = "pending"
    delivery.attempts = 0
    delivery.next_attempt_at = None
    delivery.last_error = None
    return delivery
