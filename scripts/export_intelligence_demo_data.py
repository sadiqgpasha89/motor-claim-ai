"""Runs the Phase 2 intelligence endpoints on a throwaway database and writes `site/intelligence-data.js`.

The static site cannot call the API, so it shows real responses captured from a live run.
All data is DEMO / SYNTHETIC. Thresholds are illustrative.

Usage:  python scripts/export_intelligence_demo_data.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUTPUT = ROOT / "site" / "intelligence-data.js"
HEADER = (
    "/* GENERATED FILE - do not edit by hand.\n"
    " * Source: live calls to the Phase 2 intelligence endpoints (DEMO / SYNTHETIC data, illustrative thresholds).\n"
    " * Regenerate with: python scripts/export_intelligence_demo_data.py\n"
    " */\n"
)


def build_payload() -> dict[str, object]:
    tmp = Path(tempfile.mkdtemp(prefix="intelligence_export_"))
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp / 'export.db'}"
    os.environ["EVIDENCE_STORAGE_DIR"] = str(tmp / "evidence")

    from fastapi.testclient import TestClient

    from apps.api.main import app
    from scripts.seed_demo import reset_and_seed
    from services.claims.db import Base, SessionLocal, engine
    from services.claims.models import Claim

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        reset_and_seed(db)
    finally:
        db.close()

    def part(code: str, desc: str, price: str) -> dict[str, object]:
        return {"part_code": code, "description": desc, "part_category": "metal", "line_type": "part", "quantity": 1, "unit_price_inr": price}

    with TestClient(app) as c:
        def hdr(email: str) -> dict[str, str]:
            token = c.post("/api/v1/auth/login", json={"email": email}).json()["access_token"]
            return {"Authorization": f"Bearer {token}"}

        handler, siu = hdr("handler@demo.in"), hdr("siu@demo.in")
        ids = []
        for i in range(3):
            r = c.post(
                "/api/v1/claims/intimations",
                json={
                    "policy_number": "POL-IN-DEMO-2026-2002", "vehicle_reg": "KA03DEMO5521", "claim_type": "own_damage",
                    "peril_cause": "road_accident", "incident_location": "Indiranagar, Bengaluru",
                    "incident_description": "Front bumper and bonnet damage.", "estimated_loss_inr": "30000.00",
                },
                headers={**handler, "Idempotency-Key": f"intel-export-{i}"},
            )
            ids.append(r.json()["claim"]["id"])
        focus = ids[1]
        for name in ("front_left.jpg", "front_center.jpg", "closeup_bumper.jpg"):
            c.post(f"/api/v1/claims/{focus}/evidence", files={"file": (name, f"daylight photo {name} intel-export".encode(), "image/jpeg")}, headers=handler)
        c.post(f"/api/v1/claims/{focus}/damage-assessments", headers=handler)
        labour = {"line_type": "labour", "part_category": "metal", "quantity": 1}
        c.post(
            f"/api/v1/claims/{focus}/estimates",
            json={"lines": [
                part("PRT-FRT-BMP-01", "Front bumper", "12500"),
                {**labour, "part_code": "PRT-FND-RH-01", "description": "Fender labour", "unit_price_inr": "2800"},
                {**labour, "part_code": "PRT-DOOR-RH-01", "description": "Door labour", "unit_price_inr": "5200"},
            ]},
            headers=handler,
        )
        db = SessionLocal()
        try:
            db.query(Claim).filter(Claim.id == focus).update({"status": "ESTIMATE_VALIDATION"})
            db.commit()
        finally:
            db.close()
        supp = c.post(
            f"/api/v1/claims/{focus}/estimates",
            json={"is_supplement": True, "lines": [part("PRT-BON-01", "Bonnet hidden damage", "16200")]},
            headers=handler,
        ).json()["supplementary_review"]
        get = lambda path: c.get(f"/api/v1/claims/{focus}/{path}", headers=handler).json()  # noqa: E731
        return {
            "generated_for": "DEMO / SYNTHETIC",
            "repair_replace": get("repair-replace-analysis"),
            "benchmark": get("estimate-benchmark"),
            "fusion": get("multimodal-fusion"),
            "complexity": get("complexity"),
            "supplementary": supp,
            "fraud_network": c.get(f"/api/v1/claims/{ids[0]}/fraud-network", headers=siu).json(),
            "complexity_backtest": c.get("/api/v1/operations/complexity-backtest", headers=hdr("manager@demo.in")).json(),
        }


def main() -> None:
    payload = build_payload()
    OUTPUT.write_text(HEADER + "window.INTELLIGENCE_DEMO = " + json.dumps(payload, indent=1, default=str) + ";\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
