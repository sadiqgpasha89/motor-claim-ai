"""Built-in event consumers. Import this module once at startup to register them."""
from __future__ import annotations

from sqlalchemy.orm import Session

from services.claims.models import Claim, OutboxEvent
from services.events.bus import register_consumer
from services.integrations.resilience import breaker_for, call_with_resilience
from services.integrations.sandbox import PORTS

NOTIFY_EVENTS = {"PaymentConfirmed", "ClaimClosed", "EstimateValidated"}
TEMPLATE_BY_EVENT = {
    "PaymentConfirmed": "payment_confirmed",
    "ClaimClosed": "claim_closed",
    "EstimateValidated": "estimate_validated",
}


def _claim_for(db: Session, evt: OutboxEvent) -> Claim | None:
    return db.query(Claim).filter(Claim.id == evt.aggregate_id, Claim.tenant_id == evt.tenant_id).first()


def claims_ledger_consumer(db: Session, evt: OutboxEvent) -> None:
    claim = _claim_for(db, evt)
    if claim is None:
        return
    call_with_resilience(
        lambda: PORTS["claims_system"].post_event(claim_number=claim.claim_number, event_type=evt.event_type, payload={"event_id": evt.id}),
        breaker=breaker_for("claims_system"),
        sleep=lambda _s: None,
    )


def notification_consumer(db: Session, evt: OutboxEvent) -> None:
    claim = _claim_for(db, evt)
    if claim is None:
        return
    call_with_resilience(
        lambda: PORTS["messaging"].send(channel="whatsapp", recipient_token=f"cust:{claim.customer_id}", template=TEMPLATE_BY_EVENT[evt.event_type]),
        breaker=breaker_for("messaging"),
        sleep=lambda _s: None,
    )


register_consumer("claims_ledger", {"*"}, claims_ledger_consumer)
register_consumer("customer_notifications", NOTIFY_EVENTS, notification_consumer)
