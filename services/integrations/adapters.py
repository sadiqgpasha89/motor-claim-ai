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

    @staticmethod
    def verify_surveyor_licence(
        *,
        licence_id: str,
        licence_status: str,
        licence_expiry_at: datetime | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        exp = licence_expiry_at
        if exp is not None and exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        not_expired = exp is None or exp > now
        verified = licence_status == "verified" and not_expired
        reason = (
            "IIISLA licence active and verified"
            if verified
            else ("IIISLA licence expired" if not not_expired else f"IIISLA licence status='{licence_status}' (not verified)")
        )
        return {
            "verified": verified,
            "licence_id": licence_id,
            "licence_status": licence_status,
            "not_expired": not_expired,
            "reason": reason,
            "mode": "MOCK_IIISLA_REGISTRY",
            "checked_at": now.isoformat(),
        }

    @staticmethod
    def check_parts_availability(
        *,
        garage_name: str,
        parts_stock_status: str,
        parts_lead_time_days: int,
        part_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        results: list[dict[str, Any]] = []
        any_backorder = False
        any_partial = parts_stock_status == "partial_backorder"
        for idx, item in enumerate(part_items):
            code = str(item.get("part_code") or f"PRT-OEM-{idx + 1}")
            desc = str(item.get("description") or item.get("component_name") or "Body/Trim Assembly")
            is_ev_or_hl = any(tok in desc.lower() or tok in code.lower() for tok in ("battery", "hv", "adas", "radar", "matrix"))
            if parts_stock_status == "backordered" or (parts_stock_status == "partial_backorder" and is_ev_or_hl):
                status = "backordered"
                eta_days = max(parts_lead_time_days, 5)
                any_backorder = True
            elif is_ev_or_hl and parts_lead_time_days > 2:
                status = "ordered_oem"
                eta_days = parts_lead_time_days
                any_partial = True
            else:
                status = "in_stock"
                eta_days = min(parts_lead_time_days, 1) if parts_stock_status == "in_stock" else parts_lead_time_days
            results.append(
                {
                    "part_code": code,
                    "description": desc,
                    "availability": status,
                    "eta_days": eta_days,
                    "source": "OEM Warehouse" if status != "in_stock" else f"{garage_name} Stock",
                }
            )

        overall = (
            "backordered"
            if any_backorder and all(r["availability"] == "backordered" for r in results)
            else ("partial_backorder" if (any_backorder or any_partial) else "all_available")
        )
        return {
            "parts_status": overall,
            "items": results,
            "checked_at": now.isoformat(),
            "mode": "MOCK_OEM_PARTS_CATALOGUE",
        }

    @staticmethod
    def dispatch_pickup_delivery(
        *,
        mode: str,
        location: str,
        garage_name: str,
        ev_flatbed: bool = False,
    ) -> dict[str, Any]:
        return {
            "dispatch_ref": f"LOG-{uuid.uuid4().hex[:8].upper()}",
            "mode": mode,
            "location": location,
            "garage_name": garage_name,
            "ev_flatbed": ev_flatbed,
            "status": "scheduled",
            "adapter": "MOCK_ROADSIDE_LOGISTICS",
        }
