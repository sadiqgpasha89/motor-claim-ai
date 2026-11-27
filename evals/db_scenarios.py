"""Isolated in-memory database used by evaluators that need persisted claim context.

It never touches the application's engine or the demo database: every scenario gets a fresh
SQLite ``:memory:`` engine (single shared connection) with the real production schema.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from services.claims import models as m
from services.claims.db import Base

_counter = itertools.count(1)
NOW = datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)


@contextmanager
def scenario_db() -> Iterator[Session]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def seed_tenant(db: Session) -> m.Tenant:
    tenant = m.Tenant(code="EVAL", name="Evaluation Tenant", is_synthetic_demo=True)
    db.add(tenant)
    db.commit()
    return tenant


def seed_customer(db: Session, tenant: m.Tenant, name: str = "Eval Customer") -> m.Customer:
    cust = m.Customer(
        tenant_id=tenant.id,
        name=name,
        phone_token=f"tok-{next(_counter)}",
        phone_masked="XXXXXX0001",
        email_masked="e***@example.test",
    )
    db.add(cust)
    db.commit()
    return cust


def seed_vehicle(db: Session, tenant: m.Tenant, reg: str = "MH02AB1234", *, ev: bool = False) -> m.Vehicle:
    veh = m.Vehicle(
        tenant_id=tenant.id,
        registration_number=reg,
        vin_chassis=f"VIN{next(_counter):012d}",
        engine_number=f"ENG{next(_counter):08d}",
        make="Maruti Suzuki",
        model="Baleno",
        year=2024,
        fuel_type="electric" if ev else "petrol",
        is_ev=ev,
        first_registration_date=NOW - timedelta(days=700),
    )
    db.add(veh)
    db.commit()
    return veh


def seed_policy(
    db: Session,
    tenant: m.Tenant,
    cust: m.Customer,
    veh: m.Vehicle,
    *,
    started_days_ago: int = 200,
    idv: str = "780000.00",
) -> m.Policy:
    start = NOW - timedelta(days=started_days_ago)
    pol = m.Policy(
        tenant_id=tenant.id,
        customer_id=cust.id,
        vehicle_id=veh.id,
        policy_number=f"POL-EVAL-{next(_counter):05d}",
        product_code="PC-COMP",
        uin="IRDAN000EVAL",
        period_start=start,
        period_end=start + timedelta(days=365),
        idv_inr=Decimal(idv),
    )
    db.add(pol)
    db.commit()
    return pol


def seed_claim(
    db: Session,
    tenant: m.Tenant,
    cust: m.Customer,
    veh: m.Vehicle,
    pol: m.Policy | None,
    **overrides: Any,
) -> m.Claim:
    n = next(_counter)
    fields: dict[str, Any] = {
        "tenant_id": tenant.id,
        "claim_number": f"CLM-EVAL-{n:05d}",
        "policy_id": pol.id if pol else None,
        "customer_id": cust.id,
        "vehicle_id": veh.id,
        "incident_at": NOW - timedelta(days=2),
        "incident_location": "Mumbai",
        "incident_description": "Front bumper collision",
        "policy_number_input": pol.policy_number if pol else "POL-UNKNOWN",
        "vehicle_reg_input": veh.registration_number,
        "estimated_loss_inr": Decimal("30000.00"),
    }
    fields.update(overrides)
    claim = m.Claim(**fields)
    db.add(claim)
    db.commit()
    return claim


def seed_evidence(
    db: Session, tenant: m.Tenant, claim: m.Claim, *, sha: str, filename: str = "front.jpg"
) -> m.Evidence:
    ev = m.Evidence(
        tenant_id=tenant.id,
        claim_id=claim.id,
        filename=filename,
        mime_type="image/jpeg",
        size_bytes=1024,
        sha256=sha,
        storage_path=f"/dev/null/{filename}",
        uploader_user_id="eval",
    )
    db.add(ev)
    db.commit()
    return ev


def seed_estimate(
    db: Session,
    tenant: m.Tenant,
    claim: m.Claim,
    *,
    garage_id: str | None = None,
    status: str = "submitted",
    anomalies: list[dict[str, Any]] | None = None,
) -> m.Estimate:
    est = m.Estimate(
        tenant_id=tenant.id,
        claim_id=claim.id,
        garage_id=garage_id,
        status=status,
        total_claimed_inr=Decimal("25000.00"),
        total_approved_inr=Decimal("12500.00") if anomalies else Decimal("25000.00"),
        anomalies=anomalies or [],
    )
    db.add(est)
    db.commit()
    return est
