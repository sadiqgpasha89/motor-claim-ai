"""Portal routes: the nine product sections, the KPI framework, guided demos and the capability model."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from packages.security.auth import INTERNAL_ROLES, Role, UserContext, require_roles
from services.analytics import portal as p
from services.analytics.kpis import kpi_framework
from services.claims.db import get_db

router = APIRouter(prefix="/api/v1/portal", tags=["portal"])
VIEW_ROLES = tuple(INTERNAL_ROLES)
OPS_ROLES = (Role.CLAIMS_MANAGER, Role.AUDITOR, Role.ADMIN)


@router.get("/executive-dashboard")
def executive_dashboard(user: UserContext = Depends(require_roles(*OPS_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    return p.executive_dashboard(db, user.tenant_id)


@router.get("/kpi-framework")
def kpis(user: UserContext = Depends(require_roles(*OPS_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    return kpi_framework(db, user.tenant_id)


@router.get("/evidence-intelligence")
def evidence(user: UserContext = Depends(require_roles(*VIEW_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    return p.evidence_intelligence(db, user.tenant_id)


@router.get("/damage-assessment")
def damage(user: UserContext = Depends(require_roles(*VIEW_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    return p.damage_assessment(db, user.tenant_id)


@router.get("/settlement-workbench")
def settlement(user: UserContext = Depends(require_roles(*VIEW_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    return p.settlement_workbench(db, user.tenant_id)


@router.get("/human-review")
def human_review(user: UserContext = Depends(require_roles(*VIEW_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    return p.human_review(db, user.tenant_id)


@router.get("/performance")
def performance(user: UserContext = Depends(require_roles(*OPS_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    return p.performance(db, user.tenant_id)


@router.get("/demos")
def demos(user: UserContext = Depends(require_roles(*VIEW_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    return p.guided_demos(db, user.tenant_id)


@router.get("/capability-model")
def capability(user: UserContext = Depends(require_roles(*VIEW_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    return p.capability_model(db)
