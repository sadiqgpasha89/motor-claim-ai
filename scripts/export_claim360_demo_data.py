"""Runs the OD claim demo on a throwaway database and writes `site/claim360-data.js` for the GitHub Pages site.

The static site cannot call the API, so it shows a REAL Claim 360 view and operations dashboard captured from a live
run of the same endpoints. All data is DEMO / SYNTHETIC. Token counts are estimates.

Usage:  python scripts/export_claim360_demo_data.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUTPUT = ROOT / "site" / "claim360-data.js"
HEADER = (
    "/* GENERATED FILE - do not edit by hand.\n"
    " * Source: a live run of scripts/od_claim_demo.py against the API (DEMO / SYNTHETIC data, estimated token counts).\n"
    " * Regenerate with: python scripts/export_claim360_demo_data.py\n"
    " */\n"
)


def build_payload() -> dict[str, object]:
    tmp = Path(tempfile.mkdtemp(prefix="claim360_export_"))
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp / 'export.db'}"
    os.environ["EVIDENCE_STORAGE_DIR"] = str(tmp / "evidence")

    from fastapi.testclient import TestClient

    from apps.api.main import app
    from scripts.od_claim_demo import run_od_claim_demo
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
        token = client.post("/api/v1/auth/login", json={"email": "manager@demo.in"}).json()["access_token"]
        hdrs = {"Authorization": f"Bearer {token}"}
        dashboard = client.get("/api/v1/operations/agent-observability/dashboard", headers=hdrs).json()
        queue = client.get("/api/v1/operations/approval-queue", headers=hdrs).json()
    return {
        "generated_for": "DEMO / SYNTHETIC",
        "journey": result["journey"],
        "claim_360": result["claim_360"],
        "dashboard": dashboard,
        "approval_queue": queue,
    }


def main() -> None:
    payload = build_payload()
    OUTPUT.write_text(HEADER + "window.CLAIM360_DEMO = " + json.dumps(payload, indent=1, default=str) + ";\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
