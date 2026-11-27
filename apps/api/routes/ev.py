"""Electric-vehicle (EV) claims workflow API (IN-EV-CLAIMS-2026).

EV claims run a safety-first lifecycle next to the Own Damage claim. Every state-changing endpoint needs an
authorised human role; there is no agent or autonomous endpoint here, and no endpoint accepts a photograph as
evidence that the vehicle is safe to operate.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.schemas import (
    EVAdvanceRequest,
    EVBenchmarkRequest,
    EVBenchmarkReviewRequest,
    EVCloseRequest,
    EVDispositionRequest,
    EVEscalationAcknowledgeRequest,
    EVEscalationResolveRequest,
    EVOemDiagnosticsRequest,
    EVRecertificationRequest,
    EVRecoveryRequest,
    EVSafetyEscalationRequest,
    EVSalvageEventRequest,
    EVSpecialistSurveyRequest,
    EVTechnicalSignOffRequest,
    EVThermalWatchClearRequest,
    EVTriageRequest,
)
from packages.contracts.errors import DomainError, ErrorCode
from packages.security.auth import Role, UserContext, enforce_claim_abac, get_current_user, require_roles
from services.claims.db import get_db
from services.claims.models import Claim, EVClaimCase
from services.workflow import ev_claims as ev

router = APIRouter(prefix="/api/v1", tags=["electric-vehicle-claims"])

EV_INTAKE_ROLES = tuple(ev.ROLES_INTAKE)
EV_HANDLING_ROLES = tuple(ev.ROLES_HANDLING)
EV_MANAGER_ROLES = tuple(ev.ROLES_MANAGER)
EV_SURVEY_ROLES = tuple(ev.ROLES_SURVEY)
EV_DIAGNOSTIC_ROLES = tuple(ev.ROLES_DIAGNOSTICS)
EV_RECOVERY_ROLES = tuple(ev.ROLES_RECOVERY)
EV_RECERT_ROLES = tuple(ev.ROLES_RECERT)
EV_SALVAGE_ROLES = tuple(ev.ROLES_SALVAGE)
EV_ESCALATE_ROLES = tuple(ev.ROLES_ESCALATE)
EV_READ_ROLES = tuple(ev.ROLES_VIEW_FULL | {Role.POLICYHOLDER})
EV_DASHBOARD_ROLES = tuple(ev.ROLES_VIEW_FULL - {Role.SURVEYOR, Role.GARAGE})


def _claim(db: Session, claim_id: str, user: UserContext) -> Claim:
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise DomainError(ErrorCode.NOT_FOUND, f"Claim '{claim_id}' not found", status_code=404)
    enforce_claim_abac(user, claim)
    return claim


def _case(db: Session, claim_id: str, user: UserContext) -> tuple[Claim, EVClaimCase]:
    claim = _claim(db, claim_id, user)
    return claim, ev._case_for(db, claim)


def _view(db: Session, claim: Claim, case: EVClaimCase, user: UserContext) -> dict[str, Any]:
    return ev.serialize_ev_case(db, case, claim, user)


@router.get("/ev/lifecycle")
def get_ev_lifecycle(user: UserContext = Depends(get_current_user), db: Session = Depends(get_db)):
    return ev.lifecycle_definition(db)


@router.get("/ev/queues")
def get_ev_queues(user: UserContext = Depends(require_roles(*EV_DASHBOARD_ROLES)), db: Session = Depends(get_db)):
    return ev.build_ev_dashboard(db, user.tenant_id)


@router.get("/ev/cases")
def list_ev_cases(user: UserContext = Depends(require_roles(*EV_DASHBOARD_ROLES)), db: Session = Depends(get_db)):
    cases = db.query(EVClaimCase).filter(EVClaimCase.tenant_id == user.tenant_id).order_by(EVClaimCase.created_at.desc()).all()
    return {"items": [ev.serialize_ev_summary(c) for c in cases]}


@router.post("/claims/{claim_id}/ev/open", status_code=201)
def open_ev_case(claim_id: str, user: UserContext = Depends(require_roles(*EV_INTAKE_ROLES)), db: Session = Depends(get_db)):
    claim = _claim(db, claim_id, user)
    case = ev.open_ev_case(db, claim, user)
    db.commit()
    return _view(db, claim, case, user)


@router.get("/claims/{claim_id}/ev")
def get_ev_case(claim_id: str, user: UserContext = Depends(require_roles(*EV_READ_ROLES)), db: Session = Depends(get_db)):
    claim, case = _case(db, claim_id, user)
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/ev/triage")
def record_ev_triage(
    claim_id: str,
    body: EVTriageRequest,
    user: UserContext = Depends(require_roles(*EV_INTAKE_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    ev.record_triage(db, case, claim, user, **body.model_dump())
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/ev/safety-escalations", status_code=201)
def raise_ev_safety_escalation(
    claim_id: str,
    body: EVSafetyEscalationRequest,
    user: UserContext = Depends(require_roles(*EV_ESCALATE_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    ev.raise_safety_escalation(db, case, claim, user, signals=body.signals, description=body.description, level=body.level)
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/ev/safety-escalations/{escalation_id}/acknowledge")
def acknowledge_ev_safety_escalation(
    claim_id: str,
    escalation_id: str,
    body: EVEscalationAcknowledgeRequest,
    user: UserContext = Depends(require_roles(*EV_MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    ev.acknowledge_safety_escalation(db, case, user, escalation_id=escalation_id, actions_taken=body.actions_taken)
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/ev/safety-escalations/{escalation_id}/resolve")
def resolve_ev_safety_escalation(
    claim_id: str,
    escalation_id: str,
    body: EVEscalationResolveRequest,
    user: UserContext = Depends(require_roles(*EV_MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    ev.resolve_safety_escalation(
        db, case, claim, user, escalation_id=escalation_id, resolution=body.resolution,
        evidence_ref=body.evidence_ref, thermal_stable_confirmed=body.thermal_stable_confirmed,
    )
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/ev/recovery")
def record_ev_recovery(
    claim_id: str,
    body: EVRecoveryRequest,
    user: UserContext = Depends(require_roles(*EV_RECOVERY_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    ev.record_recovery(db, case, claim, user, **body.model_dump())
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/ev/specialist-survey")
def record_ev_specialist_survey(
    claim_id: str,
    body: EVSpecialistSurveyRequest,
    user: UserContext = Depends(require_roles(*EV_SURVEY_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    ev.record_specialist_survey(db, case, claim, user, **body.model_dump())
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/ev/oem-diagnostics")
def record_ev_oem_diagnostics(
    claim_id: str,
    body: EVOemDiagnosticsRequest,
    user: UserContext = Depends(require_roles(*EV_DIAGNOSTIC_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    ev.record_oem_diagnostics(
        db, case, claim, user, provider_id=body.provider_id, tool=body.tool, report_ref=body.report_ref,
        tests=[t.model_dump() for t in body.tests],
    )
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/ev/battery-disposition")
def record_ev_battery_disposition(
    claim_id: str,
    body: EVDispositionRequest,
    user: UserContext = Depends(require_roles(*EV_HANDLING_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    ev.record_disposition(db, case, claim, user, **body.model_dump())
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/ev/cost-benchmark")
def compute_ev_benchmark(
    claim_id: str,
    body: EVBenchmarkRequest,
    user: UserContext = Depends(require_roles(*EV_HANDLING_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    ev.record_benchmark(db, case, claim, user, lines=[ln.model_dump(mode="json") for ln in body.lines])
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/ev/cost-benchmark/review")
def review_ev_benchmark(
    claim_id: str,
    body: EVBenchmarkReviewRequest,
    user: UserContext = Depends(require_roles(*EV_HANDLING_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    ev.review_benchmark(db, case, user, note=body.note)
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/ev/thermal-watch/clear")
def clear_ev_thermal_watch(
    claim_id: str,
    body: EVThermalWatchClearRequest,
    user: UserContext = Depends(require_roles(*EV_MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    ev.clear_thermal_watch(db, case, user, basis=body.basis, oem_reference=body.oem_reference)
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/ev/technical-sign-off")
def ev_technical_sign_off(
    claim_id: str,
    body: EVTechnicalSignOffRequest = EVTechnicalSignOffRequest(),
    user: UserContext = Depends(require_roles(*EV_MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    ev.technical_sign_off(db, case, claim, user, notes=body.notes)
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/ev/recertification")
def record_ev_recertification(
    claim_id: str,
    body: EVRecertificationRequest,
    user: UserContext = Depends(require_roles(*EV_RECERT_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    ev.record_recertification(db, case, claim, user, **body.model_dump())
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/ev/salvage-events", status_code=201)
def record_ev_salvage_event(
    claim_id: str,
    body: EVSalvageEventRequest,
    user: UserContext = Depends(require_roles(*EV_SALVAGE_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    ev.record_salvage_event(db, case, claim, user, **body.model_dump())
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/ev/advance")
def advance_ev_stage(
    claim_id: str,
    body: EVAdvanceRequest = EVAdvanceRequest(),
    user: UserContext = Depends(require_roles(*EV_HANDLING_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    ev.advance_stage(db, case, claim, user, note=body.note)
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/ev/close")
def close_ev_case(
    claim_id: str,
    body: EVCloseRequest,
    user: UserContext = Depends(require_roles(*EV_MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    ev.close_case(db, case, claim, user, closure_notes=body.closure_notes)
    db.commit()
    return _view(db, claim, case, user)
