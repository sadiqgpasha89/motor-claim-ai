"""Third-Party (TP) liability workflow API (IN-TP-LIABILITY-2026).

TP claims are legal-liability claims. They never share the OD estimate -> settlement -> auto-approval path.
Every state-changing endpoint requires an authorised human role; there is no agent/autonomous endpoint here.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.schemas import (
    TPAdvanceRequest,
    TPAdvocateRequest,
    TPCloseRequest,
    TPExposureRequest,
    TPFactsRequest,
    TPLegalDocumentRequest,
    TPLegalReviewRequest,
    TPLiabilityRequest,
    TPMedicalReviewRequest,
    TPOpenRequest,
    TPPaymentAuthoriseRequest,
    TPPoliceReportRequest,
    TPReserveRequest,
    TPSettlementDecisionRequest,
    TPSettlementProposalRequest,
    TPThirdPartyRequest,
    TPTribunalRequest,
)
from packages.contracts.errors import DomainError, ErrorCode
from packages.security.auth import (
    TP_LEGAL_ALLOWED_ROLES,
    Role,
    UserContext,
    enforce_claim_abac,
    get_current_user,
    require_roles,
)
from services.claims.db import get_db
from services.claims.models import Claim, TPClaimCase
from services.workflow import tp_liability as tp

router = APIRouter(prefix="/api/v1", tags=["third-party-liability"])

TP_INTAKE_ROLES = (Role.FNOL_EXECUTIVE, Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.LEGAL_TP)
TP_HANDLING_ROLES = (Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.LEGAL_TP)
TP_READ_ROLES = tuple(TP_LEGAL_ALLOWED_ROLES | {Role.FNOL_EXECUTIVE, Role.FINANCE_APPROVER})


def _claim(db: Session, claim_id: str, user: UserContext) -> Claim:
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise DomainError(ErrorCode.NOT_FOUND, f"Claim '{claim_id}' not found", status_code=404)
    enforce_claim_abac(user, claim)
    return claim


def _case(db: Session, claim_id: str, user: UserContext) -> tuple[Claim, TPClaimCase]:
    claim = _claim(db, claim_id, user)
    return claim, tp._case_for(db, claim)


def _view(db: Session, claim: Claim, case: TPClaimCase, user: UserContext) -> dict[str, Any]:
    return tp.serialize_tp_case(db, case, claim, user)


@router.get("/tp/lifecycle")
def get_tp_lifecycle(user: UserContext = Depends(get_current_user), db: Session = Depends(get_db)):
    return tp.lifecycle_definition(db)


@router.get("/tp/queues")
def get_tp_queues(user: UserContext = Depends(require_roles(*TP_READ_ROLES)), db: Session = Depends(get_db)):
    return tp.build_tp_dashboard(db, user.tenant_id)


@router.get("/tp/cases")
def list_tp_cases(user: UserContext = Depends(require_roles(*TP_READ_ROLES)), db: Session = Depends(get_db)):
    cases = db.query(TPClaimCase).filter(TPClaimCase.tenant_id == user.tenant_id).order_by(TPClaimCase.created_at.desc()).all()
    return {"items": [tp.serialize_tp_summary(c) for c in cases]}


@router.post("/claims/{claim_id}/tp/open", status_code=201)
def open_tp_case(
    claim_id: str,
    body: TPOpenRequest = TPOpenRequest(),
    user: UserContext = Depends(require_roles(*TP_INTAKE_ROLES)),
    db: Session = Depends(get_db),
):
    claim = _claim(db, claim_id, user)
    case = tp.open_tp_case(db, claim, user, tp_category=body.tp_category)
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/tp/exposures", status_code=201)
def raise_tp_exposure(
    claim_id: str,
    body: TPExposureRequest,
    user: UserContext = Depends(require_roles(*TP_INTAKE_ROLES)),
    db: Session = Depends(get_db),
):
    od_claim = _claim(db, claim_id, user)
    tp_claim, case = tp.raise_tp_exposure_from_od_claim(db, od_claim, user, tp_category=body.tp_category, description=body.description)
    db.commit()
    return {"od_claim_id": od_claim.id, "tp_claim_id": tp_claim.id, "tp_case": _view(db, tp_claim, case, user)}


@router.get("/claims/{claim_id}/tp")
def get_tp_case(claim_id: str, user: UserContext = Depends(require_roles(*TP_READ_ROLES)), db: Session = Depends(get_db)):
    claim, case = _case(db, claim_id, user)
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/tp/coverage-check")
def tp_coverage_check(claim_id: str, user: UserContext = Depends(require_roles(*TP_INTAKE_ROLES)), db: Session = Depends(get_db)):
    claim, case = _case(db, claim_id, user)
    tp.validate_case_coverage(db, case, claim, user)
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/tp/third-parties", status_code=201)
def add_tp_third_party(
    claim_id: str,
    body: TPThirdPartyRequest,
    user: UserContext = Depends(require_roles(*TP_INTAKE_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    tp.add_third_party(db, case, user, **body.model_dump())
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/tp/facts")
def record_tp_facts(
    claim_id: str,
    body: TPFactsRequest,
    user: UserContext = Depends(require_roles(*TP_INTAKE_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    data = body.model_dump()
    tp.record_accident_facts(db, case, user, **data)
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/tp/police-report")
def record_tp_police_report(
    claim_id: str,
    body: TPPoliceReportRequest,
    user: UserContext = Depends(require_roles(*TP_HANDLING_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    tp.record_police_report(db, case, user, **body.model_dump())
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/tp/liability-assessment")
def record_tp_liability(
    claim_id: str,
    body: TPLiabilityRequest,
    user: UserContext = Depends(require_roles(*TP_HANDLING_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    tp.record_liability_assessment(db, case, claim, user, **body.model_dump())
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/tp/legal-documents", status_code=201)
def register_tp_legal_document(
    claim_id: str,
    body: TPLegalDocumentRequest,
    user: UserContext = Depends(require_roles(*TP_HANDLING_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    tp.register_legal_document(db, case, user, **body.model_dump())
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/tp/tribunal")
def record_tp_tribunal(
    claim_id: str,
    body: TPTribunalRequest,
    user: UserContext = Depends(require_roles(Role.LEGAL_TP)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    tp.record_tribunal_event(db, case, user, **body.model_dump())
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/tp/advocates", status_code=201)
def assign_tp_advocate(
    claim_id: str,
    body: TPAdvocateRequest,
    user: UserContext = Depends(require_roles(Role.LEGAL_TP)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    tp.assign_advocate(db, case, user, **body.model_dump())
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/tp/medical-review")
def record_tp_medical_review(
    claim_id: str,
    body: TPMedicalReviewRequest,
    user: UserContext = Depends(require_roles(Role.LEGAL_TP, Role.CLAIMS_MANAGER, Role.CLAIMS_HANDLER)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    tp.record_medical_review(db, case, user, **body.model_dump())
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/tp/legal-review")
def sign_tp_legal_review(
    claim_id: str,
    body: TPLegalReviewRequest,
    user: UserContext = Depends(require_roles(Role.LEGAL_TP)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    tp.sign_legal_review(db, case, claim, user, **body.model_dump())
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/tp/reserve")
def set_tp_reserve(
    claim_id: str,
    body: TPReserveRequest,
    user: UserContext = Depends(require_roles(*TP_HANDLING_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    tp.set_reserve(db, case, user, amount_inr=body.amount_inr, basis=body.basis)
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/tp/advance")
def advance_tp_stage(
    claim_id: str,
    body: TPAdvanceRequest = TPAdvanceRequest(),
    user: UserContext = Depends(require_roles(*TP_HANDLING_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    tp.advance_stage(db, case, claim, user, note=body.note)
    db.commit()
    return _view(db, claim, case, user)


@router.post("/claims/{claim_id}/tp/settlement-proposals", status_code=201)
def propose_tp_settlement(
    claim_id: str,
    body: TPSettlementProposalRequest,
    user: UserContext = Depends(require_roles(*TP_HANDLING_ROLES)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    proposal = tp.propose_settlement(db, case, claim, user, **body.model_dump())
    db.commit()
    return {"proposal": proposal, "tp_case": _view(db, claim, case, user)}


@router.post("/claims/{claim_id}/tp/settlement-proposals/{proposal_id}/decision")
def decide_tp_settlement(
    claim_id: str,
    proposal_id: str,
    body: TPSettlementDecisionRequest,
    user: UserContext = Depends(require_roles(Role.CLAIMS_MANAGER, Role.LEGAL_TP)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    proposal = tp.decide_settlement(db, case, claim, user, proposal_id=proposal_id, decision=body.decision, rationale=body.rationale)
    db.commit()
    return {"proposal": proposal, "tp_case": _view(db, claim, case, user)}


@router.post("/claims/{claim_id}/tp/payment-authorisation", status_code=201)
def authorise_tp_payment(
    claim_id: str,
    body: TPPaymentAuthoriseRequest,
    user: UserContext = Depends(require_roles(Role.FINANCE_APPROVER)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    payment = tp.authorise_payment(db, case, claim, user, **body.model_dump())
    db.commit()
    return {"payment": {k: v for k, v in payment.items() if k != "idempotency_key"}, "tp_case": _view(db, claim, case, user)}


@router.post("/claims/{claim_id}/tp/payment-authorisation/reconcile")
def reconcile_tp_payment(claim_id: str, user: UserContext = Depends(require_roles(Role.FINANCE_APPROVER)), db: Session = Depends(get_db)):
    claim, case = _case(db, claim_id, user)
    payment = tp.reconcile_payment(db, case, claim, user)
    db.commit()
    return {"payment": payment, "tp_case": _view(db, claim, case, user)}


@router.post("/claims/{claim_id}/tp/close")
def close_tp_case(
    claim_id: str,
    body: TPCloseRequest,
    user: UserContext = Depends(require_roles(Role.CLAIMS_MANAGER)),
    db: Session = Depends(get_db),
):
    claim, case = _case(db, claim_id, user)
    tp.close_case(db, case, claim, user, closure_notes=body.closure_notes, recovery_action_opened=body.recovery_action_opened)
    db.commit()
    return _view(db, claim, case, user)
