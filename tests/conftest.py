from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_TMP_DB = Path(tempfile.gettempdir()) / "motor_claim_ai_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["EVIDENCE_STORAGE_DIR"] = str(Path(tempfile.gettempdir()) / "motor_claim_ai_test_ev")

from apps.api.main import app  # noqa: E402
from scripts.seed_demo import reset_and_seed  # noqa: E402
from services.claims.db import Base, SessionLocal, engine  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    if _TMP_DB.exists():
        _TMP_DB.unlink()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        reset_and_seed(db)
    finally:
        db.close()
    yield
    if _TMP_DB.exists():
        _TMP_DB.unlink()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def auth_headers(client: TestClient, email: str) -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json={"email": email})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
