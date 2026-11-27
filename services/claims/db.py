from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from packages.config import get_settings


class Base(DeclarativeBase):
    pass


def _build_engine():
    settings = get_settings()
    connect_args = {}
    if settings.database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(settings.database_url, connect_args=connect_args, future=True)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _ensure_sqlite_claim_columns() -> None:
    """Safely adds additive columns to pre-existing local SQLite demo DBs."""
    if not str(engine.url).startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "claims" not in inspector.get_table_names():
        return
    existing_cols = {c["name"] for c in inspector.get_columns("claims")}
    additive = {
        "risk_tier": "VARCHAR(16) NOT NULL DEFAULT 'MEDIUM'",
        "operational_path": "VARCHAR(32) NOT NULL DEFAULT 'standard'",
        "risk_score": "INTEGER NOT NULL DEFAULT 35",
        "fraud_signal_score": "NUMERIC(4, 3) NOT NULL DEFAULT 0.000",
        "multiple_vehicles_involved": "BOOLEAN NOT NULL DEFAULT 0",
        "involved_vehicles_count": "INTEGER NOT NULL DEFAULT 1",
        "legal_dispute": "BOOLEAN NOT NULL DEFAULT 0",
        "risk_assessment": "JSON",
        "risk_history": "JSON NOT NULL DEFAULT '[]'",
    }
    with engine.begin() as conn:
        for col, col_def in additive.items():
            if col not in existing_cols:
                conn.execute(text(f"ALTER TABLE claims ADD COLUMN {col} {col_def}"))


def init_db() -> None:
    import services.claims.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_claim_columns()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
