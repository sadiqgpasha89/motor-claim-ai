"""Runs the Phase 3 platform controls on a throwaway database and writes `site/platform-data.js`.

The static site cannot call the API, so it shows real responses captured from a live run.
All data is DEMO / SYNTHETIC.

Usage:  python scripts/export_platform_demo_data.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUTPUT = ROOT / "site" / "platform-data.js"
HEADER = (
    "/* GENERATED FILE - do not edit by hand.\n"
    " * Source: live calls to the Phase 3 platform controls (DEMO / SYNTHETIC data).\n"
    " * Regenerate with: python scripts/export_platform_demo_data.py\n"
    " */\n"
)


def build_payload() -> dict[str, object]:
    tmp = Path(tempfile.mkdtemp(prefix="platform_export_"))
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp / 'export.db'}"
    os.environ["EVIDENCE_STORAGE_DIR"] = str(tmp / "evidence")

    from datetime import datetime, timedelta, timezone

    from fastapi.testclient import TestClient

    from apps.api.main import app
    from scripts.seed_demo import reset_and_seed
    from services.claims.db import Base, SessionLocal, engine
    from services.claims.models import Claim
    from services.events.bus import dispatch_pending
    from services.integrations.resilience import reset_breakers
    from services.integrations.sandbox import FAULTS, reset_faults

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        reset_and_seed(db)
    finally:
        db.close()
    reset_breakers()
    reset_faults()

    with TestClient(app) as c:
        def hdr(email: str) -> dict[str, str]:
            token = c.post("/api/v1/auth/login", json={"email": email}).json()["access_token"]
            return {"Authorization": f"Bearer {token}"}

        handler, mgr = hdr("handler@demo.in"), hdr("manager@demo.in")
        claim_id = c.post(
            "/api/v1/claims/intimations",
            json={
                "policy_number": "POL-IN-DEMO-2026-2002", "vehicle_reg": "KA03DEMO5521", "claim_type": "own_damage",
                "peril_cause": "road_accident", "incident_location": "Whitefield, Bengaluru",
                "incident_description": "Rear bumper scuff.", "estimated_loss_inr": "9000.00",
            },
            headers={**handler, "Idempotency-Key": "platform-export-1"},
        ).json()["claim"]["id"]

        def tool(name: str, headers: dict[str, str], **body: object) -> dict[str, object]:
            r = c.post(f"/api/v1/claims/{claim_id}/tools/{name}", json=body, headers=headers)
            return {"http_status": r.status_code, "body": r.json()}

        garage = {"garage_id": "prov-gar-01", "slot": "10:00"}
        FAULTS["garage"].transient_failures = 2
        retry = tool("garage_book", handler, agent_name="provider_coordination", params=garage, idempotency_key="exp-retry")
        replay = tool("garage_book", handler, agent_name="provider_coordination", params=garage, idempotency_key="exp-retry")
        denied_agent = tool("garage_book", handler, agent_name="claim_triage", params=garage, idempotency_key="exp-denied")
        denied_route = tool("payment_execute", hdr("finance@demo.in"), agent_name="human", params={}, idempotency_key="exp-pay")
        FAULTS["surveyor"].transient_failures = 100
        outage = [
            tool("surveyor_assign", handler, agent_name="provider_coordination", params={"surveyor_id": "prov-surv-01"}, idempotency_key=f"exp-out-{i}")
            for i in range(2)
        ]
        reset_faults()

        FAULTS["claims_system"].permanent = True
        db = SessionLocal()
        try:
            tenant = db.get(Claim, claim_id).tenant_id
            t0 = datetime.now(timezone.utc)
            passes = [dispatch_pending(db, tenant_id=tenant, now=t0 + timedelta(hours=h)) for h in (0, 1, 2)]
        finally:
            db.close()
        dead = c.get("/api/v1/operations/events/deliveries?status=dead", headers=mgr).json()
        reset_faults()
        replayed = c.post(f"/api/v1/operations/events/deliveries/{dead['deliveries'][0]['id']}/replay", headers=mgr).json()
        recovered = c.post("/api/v1/operations/events/dispatch", headers=mgr).json()

        llm = c.post(
            "/api/v1/operations/llm-gateway/complete",
            json={"task": "summary", "facts": {"note": "Customer rohan@example.com phone 9876543210"}},
            headers=handler,
        ).json()
        return {
            "generated_for": "DEMO / SYNTHETIC",
            "tool_policy": c.get("/api/v1/operations/tool-policy", headers=mgr).json(),
            "tool_calls": {"retry_then_success": retry, "idempotent_replay": replay, "denied_agent": denied_agent, "denied_payment_tool": denied_route, "outage_then_fast_fail": outage},
            "circuit_breakers": c.get("/api/v1/operations/integration-resilience", headers=mgr).json(),
            "event_bus": {"failing_consumer_passes": passes, "dead_deliveries": dead["by_status"], "replayed": replayed, "after_recovery": recovered},
            "audit_integrity": c.get("/api/v1/operations/audit/integrity", headers=mgr).json(),
            "llm_gateway": llm,
        }


def main() -> None:
    payload = build_payload()
    OUTPUT.write_text(HEADER + "window.PLATFORM_DEMO = " + json.dumps(payload, indent=1, default=str) + ";\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
