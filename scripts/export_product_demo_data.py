"""Captures the Phase 5 portal responses on a throwaway database and writes `site/product-data.js`.

The static site cannot call the API, so it shows real responses from a live run. All data is DEMO / SYNTHETIC.

Usage:  python scripts/export_product_demo_data.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUTPUT = ROOT / "site" / "product-data.js"
HEADER = (
    "/* GENERATED FILE - do not edit by hand.\n"
    " * Source: live calls to the Phase 5 portal API (DEMO / SYNTHETIC data).\n"
    " * Regenerate with: python scripts/export_product_demo_data.py\n"
    " */\n"
)


def build_payload() -> dict[str, object]:
    tmp = Path(tempfile.mkdtemp(prefix="product_export_"))
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp / 'export.db'}"
    os.environ["EVIDENCE_STORAGE_DIR"] = str(tmp / "evidence")

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

    with TestClient(app) as c:
        token = c.post("/api/v1/auth/login", json={"email": "manager@demo.in"}).json()["access_token"]
        hdr = {"Authorization": f"Bearer {token}"}

        def get(path: str) -> dict[str, object]:
            r = c.get(f"/api/v1/{path}", headers=hdr)
            r.raise_for_status()
            return r.json()  # type: ignore[no-any-return]

        demos = get("portal/demos")
        claim_360 = {}
        for d in demos["demos"]:  # type: ignore[attr-defined]
            if d["claim_id"]:
                claim_360[d["id"]] = get(f"claims/{d['claim_id']}/claim-360")["answers"]  # type: ignore[index]
        return {
            "generated_for": "DEMO / SYNTHETIC",
            "executive_dashboard": get("portal/executive-dashboard"),
            "kpi_framework": get("portal/kpi-framework"),
            "demos": demos,
            "demo_claim_360_answers": claim_360,
            "capability_model": get("portal/capability-model"),
        }


def main() -> None:
    payload = build_payload()
    OUTPUT.write_text(HEADER + "window.PRODUCT_DEMO = " + json.dumps(payload, indent=1, default=str) + ";\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
