"""Fully working own-damage (OD) claim demo: FNOL to closure through the live API.

Works with any client that has `.post` and `.get` and returns `.status_code` and `.json()`.
That means a FastAPI TestClient (default) or an httpx.Client pointed at a running server.

    python -m scripts.od_claim_demo                 # in-process, fresh seeded database
    python -m scripts.od_claim_demo --base-url http://localhost:8000
"""
from __future__ import annotations

import argparse
import json
import uuid
from typing import Any, Protocol

OD_POLICY = "POL-IN-DEMO-2026-OD01"  # dedicated clean demo policy: no claim history, so the claim stays LOW risk
OD_VEHICLE = "MH04OD2026"
PHOTO_NAMES = ["front_daylight.jpg", "left_daylight.jpg", "closeup_daylight.jpg"]


class _Client(Protocol):
    def post(self, url: str, **kwargs: Any) -> Any: ...
    def get(self, url: str, **kwargs: Any) -> Any: ...


def _login(client: _Client, email: str) -> dict[str, str]:
    r = client.post("/api/v1/auth/login", json={"email": email})
    if r.status_code != 200:
        raise RuntimeError(f"Login failed for {email}: HTTP {r.status_code}")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _ok(resp: Any, step: str, expected: int = 200) -> Any:
    if resp.status_code != expected:
        raise RuntimeError(f"OD demo step '{step}' failed: HTTP {resp.status_code} {resp.text}")
    return resp.json()


def run_od_claim_demo(client: _Client, *, reset_demo_data: bool = False) -> dict[str, Any]:
    """Run the zero-touch OD journey and return the journey log plus the final Claim 360 view.

    The demo policy has no claim history. A second run on the same data would see a repeat claim and
    leave the fast track, so pass `reset_demo_data=True` to reseed first (manager persona, DEMO data only).
    """
    run_id = uuid.uuid4().hex[:8]
    handler = _login(client, "handler@demo.in")
    finance = _login(client, "finance@demo.in")
    manager = _login(client, "manager@demo.in")
    if reset_demo_data:
        _ok(client.post("/api/v1/operations/seed-reset", headers=manager), "reset demo data")
    journey: list[dict[str, Any]] = []

    def log(step: str, status: str, note: str) -> None:
        journey.append({"step": step, "claim_status": status, "note": note})

    fnol = _ok(
        client.post(
            "/api/v1/claims/intimations",
            json={
                "policy_number": OD_POLICY,
                "vehicle_reg": OD_VEHICLE,
                "claim_type": "cashless",
                "peril_cause": "road_accident",
                "incident_location": "Powai, Mumbai",
                "incident_description": "Light scuff on the front bumper from a low-speed parking bump.",
                "estimated_loss_inr": "14000.00",
                "documents_complete_at_fnol": True,
            },
            headers={**handler, "Idempotency-Key": f"od-demo-{run_id}"},
        ),
        "fnol",
        201,
    )
    claim_id = fnol["claim"]["id"]
    log("FNOL intake", fnol["claim"]["status"], f"risk tier {fnol['claim']['risk_tier']}, path {fnol['claim']['operational_path']}")

    rc = f"Registration Certificate Vehicle {OD_VEHICLE} Policy {OD_POLICY} Verified od-demo {run_id}".encode()
    _ok(client.post(f"/api/v1/claims/{claim_id}/evidence", files={"file": ("rc_od.txt", rc, "text/plain")}, headers=handler), "rc upload", 201)
    for name in PHOTO_NAMES:
        # Unique bytes per run: identical files on two claims would correctly trigger the reused-evidence fraud signal.
        body = f"clean daylight photo {name} od-demo {run_id}".encode()
        _ok(client.post(f"/api/v1/claims/{claim_id}/evidence", files={"file": (name, body, "image/jpeg")}, headers=handler), f"photo {name}", 201)
    log("Evidence upload", "REGISTERED", "RC and 3 daylight photos stored with sha256")

    first = _ok(client.post(f"/api/v1/claims/{claim_id}/orchestrate", json={"stop_on_human_gate": True}, headers=handler), "orchestrate 1")
    log("Agent wave 1", first["claim_status"], "agents: " + ", ".join(s["agent_name"] for s in first["steps_executed"]))

    _ok(
        client.post(
            f"/api/v1/claims/{claim_id}/estimates",
            json={"lines": [{"part_code": "PRT-FRT-BMP-01", "description": "Front Bumper Minor Refinish", "part_category": "plastic_rubber",
                             "line_type": "part", "quantity": 1, "unit_price_inr": "12000.00"}]},
            headers=handler,
        ),
        "estimate",
        201,
    )
    second = _ok(client.post(f"/api/v1/claims/{claim_id}/orchestrate", json={"stop_on_human_gate": True}, headers=handler), "orchestrate 2")
    log("Agent wave 2", second["claim_status"], "estimate validated, settlement calculated, auto-approved inside authority limit")

    detail = _ok(client.get(f"/api/v1/claims/{claim_id}", headers=handler), "claim detail")
    settlement_id = detail["settlements"][0]["id"]
    payment = _ok(
        client.post(
            f"/api/v1/claims/{claim_id}/payments",
            json={"settlement_id": settlement_id, "idempotency_key": f"od-demo-pay-{run_id}", "payee_type": "customer", "payee_name": "Rohan Kulkarni"},
            headers=finance,
        ),
        "payment",
        201,
    )
    log("Payment", payment.get("status", "initiated"), "finance approver released idempotent payment")
    closed = _ok(client.post(f"/api/v1/claims/{claim_id}/close", headers=handler), "close")
    log("Closure", closed["claim_status"], "claim closed")

    view = _ok(client.get(f"/api/v1/claims/{claim_id}/claim-360", headers=handler), "claim-360")
    dashboard = _ok(client.get("/api/v1/operations/agent-observability/dashboard", headers=manager), "dashboard")
    return {"claim_id": claim_id, "final_status": closed["claim_status"], "journey": journey, "claim_360": view, "ops_kpis": dashboard["kpis"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="Run against a live API instead of an in-process fresh database")
    parser.add_argument("--out", help="Write the full JSON result to this file")
    args = parser.parse_args()

    if args.base_url:
        import httpx

        with httpx.Client(base_url=args.base_url, timeout=60) as client:
            result = run_od_claim_demo(client)
    else:
        from fastapi.testclient import TestClient

        from apps.api.main import app
        from scripts.seed_demo import reset_and_seed
        from services.claims.db import Base, SessionLocal, engine

        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            reset_and_seed(db)
        finally:
            db.close()
        with TestClient(app) as client:
            result = run_od_claim_demo(client)

    for step in result["journey"]:
        print(f"{step['step']:<16} {step['claim_status']:<28} {step['note']}")
    print(f"FINAL: {result['final_status']}  agent executions: {result['claim_360']['agent_summary']['executions']}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, default=str)


if __name__ == "__main__":
    main()
