from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from packages.config import get_settings


class IntegrationAdapterRegistry:
    """Replaceable enterprise integration adapters (clearly labelled DEMO / MOCK in local mode)."""

    def health_report(self) -> list[dict[str, Any]]:
        settings = get_settings()
        mode = settings.integration_mode.upper()
        now = datetime.now(timezone.utc).isoformat()
        return [
            {
                "name": "Core Policy Admin & Wording Repo",
                "code": "core_policy",
                "mode": f"{mode} (DEMO)",
                "status": "healthy",
                "latency_ms": 18,
                "last_checked": now,
            },
            {
                "name": "Core Claims Ledger",
                "code": "core_claims",
                "mode": f"{mode} (DEMO)",
                "status": "healthy",
                "latency_ms": 22,
                "last_checked": now,
            },
            {
                "name": "Payment Gateway & Bank Penny-Drop",
                "code": "payment_gateway",
                "mode": f"{mode} (DEMO)",
                "status": "healthy",
                "latency_ms": 34,
                "last_checked": now,
            },
            {
                "name": "Surveyor IIISLA Roster & Scheduling",
                "code": "surveyor_roster",
                "mode": f"{mode} (DEMO)",
                "status": "healthy",
                "latency_ms": 15,
                "last_checked": now,
            },
            {
                "name": "Garage OEM/OES Parts Rate Card",
                "code": "parts_catalogue",
                "mode": f"{mode} (DEMO)",
                "status": "healthy",
                "latency_ms": 19,
                "last_checked": now,
            },
            {
                "name": "WhatsApp / Email / SMS Notification Bus",
                "code": "messaging_bus",
                "mode": f"{mode} (DEMO)",
                "status": "healthy",
                "latency_ms": 12,
                "last_checked": now,
            },
            {
                "name": "Model Gateway (LLM / Vision / OCR)",
                "code": "model_gateway",
                "mode": f"{settings.ai_provider_mode.upper()} (OUTAGE_SIM={settings.ai_simulate_outage})",
                "status": "degraded_manual_fallback" if settings.ai_simulate_outage else "healthy",
                "latency_ms": 0 if settings.ai_simulate_outage else 42,
                "last_checked": now,
            },
        ]

    @staticmethod
    def validate_bank_account(account_last4: str, ifsc: str) -> dict[str, Any]:
        return {
            "verified": True,
            "mode": "MOCK_PENNY_DROP",
            "account_masked": f"XXXXXX{account_last4}",
            "ifsc": ifsc.upper(),
            "verification_ref": f"VER-{uuid.uuid4().hex[:10].upper()}",
        }

    @staticmethod
    def execute_payment(
        *,
        idempotency_key: str,
        amount_inr: Decimal,
        payee_name: str,
        simulate_timeout: bool = False,
    ) -> dict[str, Any]:
        if simulate_timeout:
            return {
                "status": "timeout_reconcile_pending",
                "gateway_reference": f"PG-PEND-{idempotency_key[:10].upper()}",
                "message": "Upstream bank gateway timed out; safe reconciliation required before retry.",
            }
        return {
            "status": "confirmed",
            "gateway_reference": f"PG-UTR-{uuid.uuid4().hex[:12].upper()}",
            "amount_inr": str(amount_inr),
            "payee": payee_name,
            "mode": "MOCK_NEFT_IMPS",
        }

    @staticmethod
    def reconcile_payment(gateway_reference: str) -> dict[str, Any]:
        return {
            "status": "confirmed",
            "gateway_reference": gateway_reference,
            "utr": f"UTR-RECON-{gateway_reference[-8:]}",
            "reconciled_at": datetime.now(timezone.utc).isoformat(),
        }
