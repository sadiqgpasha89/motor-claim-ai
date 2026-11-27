"""Sandbox adapters for the six enterprise systems. DEMO / SYNTHETIC. They behave like remote systems.

Each adapter can be told to fail, so resilience and fallback are testable. A live adapter would implement the
same methods and call the real system.
"""
from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any

from services.integrations.adapters import IntegrationAdapterRegistry
from services.integrations.resilience import PermanentIntegrationError, TransientIntegrationError


class FaultInjector:
    """Fail the next N calls with a transient error. Or fail every call with a permanent error."""

    def __init__(self) -> None:
        self.transient_failures = 0
        self.permanent = False

    def maybe_fail(self, system: str) -> None:
        if self.permanent:
            raise PermanentIntegrationError(f"{system} rejected the request")
        if self.transient_failures > 0:
            self.transient_failures -= 1
            raise TransientIntegrationError(f"{system} is temporarily unavailable")

    def reset(self) -> None:
        self.transient_failures = 0
        self.permanent = False


FAULTS: dict[str, FaultInjector] = {n: FaultInjector() for n in ("policy_admin", "claims_system", "garage", "surveyor", "payment_gateway", "whatsapp", "sms", "email")}


def reset_faults() -> None:
    for f in FAULTS.values():
        f.reset()


def _ref(prefix: str, *parts: Any) -> str:
    return f"{prefix}-" + hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:10].upper()


class PolicyAdminSandbox:
    def lookup(self, *, policy_number: str) -> dict[str, Any]:
        FAULTS["policy_admin"].maybe_fail("policy admin")
        return {"policy_number": policy_number, "status": "active", "source": "policy-admin-sandbox"}


class ClaimsSystemSandbox:
    def post_event(self, *, claim_number: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        FAULTS["claims_system"].maybe_fail("claims system")
        return {"ledger_ref": _ref("LEDGER", claim_number, event_type, sorted(payload.items())), "accepted": True}


class GarageSandbox:
    def book_slot(self, *, garage_id: str, claim_number: str, slot: str) -> dict[str, Any]:
        FAULTS["garage"].maybe_fail("garage system")
        return {"booking_ref": _ref("GBK", garage_id, claim_number, slot), "slot": slot}


class SurveyorSandbox:
    def assign(self, *, surveyor_id: str, claim_number: str) -> dict[str, Any]:
        FAULTS["surveyor"].maybe_fail("surveyor roster")
        return {"assignment_ref": _ref("SVY", surveyor_id, claim_number), "report_due_days": 15}


class PaymentGatewaySandbox:
    def pay(self, *, idempotency_key: str, amount_inr: str, payee_name: str) -> dict[str, Any]:
        FAULTS["payment_gateway"].maybe_fail("payment gateway")
        res = IntegrationAdapterRegistry.execute_payment(
            idempotency_key=idempotency_key, amount_inr=Decimal(amount_inr), payee_name=payee_name, simulate_timeout=False
        )
        return {"status": res["status"], "gateway_reference": res["gateway_reference"]}


class MessagingSandbox:
    CHANNELS = ("whatsapp", "sms", "email")

    def send(self, *, channel: str, recipient_token: str, template: str) -> dict[str, Any]:
        if channel not in self.CHANNELS:
            raise PermanentIntegrationError(f"Unknown channel '{channel}'")
        FAULTS[channel].maybe_fail(channel)
        return {"channel": channel, "message_ref": _ref("MSG", channel, recipient_token, template), "template": template}


PORTS: dict[str, Any] = {
    "policy_admin": PolicyAdminSandbox(),
    "claims_system": ClaimsSystemSandbox(),
    "garage": GarageSandbox(),
    "surveyor": SurveyorSandbox(),
    "payment_gateway": PaymentGatewaySandbox(),
    "messaging": MessagingSandbox(),
}
