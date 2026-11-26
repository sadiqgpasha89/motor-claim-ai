from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from sqlalchemy.orm import Session

from agents.specialists import AGENT_REGISTRY
from apps.api.schemas import (
    ApprovalDecisionRequest,
    ClaimAssignRequest,
    CommunicationCreateRequest,
    DamageReviewRequest,
    EstimateLineReviewRequest,
    EstimateSubmitRequest,
    FactCorrectionRequest,
    FNOLCreateRequest,
    FraudDispositionRequest,
    GrievanceCreateRequest,
    GrievanceResolveRequest,
    PaymentInitiateRequest,
    RepairMilestoneRequest,
    SettlementRecommendRequest,
    SurveyorAssignRequest,
    SurveyReportSubmitRequest,
)
from packages.config import get_settings
from packages.contracts.agents import AgentInvocationRequest
from packages.contracts.errors import DomainError, ErrorCode
from packages.observability.logging import get_correlation_id
from packages.security.auth import (
    INTERNAL_ROLES,
    SIU_ALLOWED_ROLES,
    TP_LEGAL_ALLOWED_ROLES,
    Role,
    UserContext,
    enforce_claim_abac,
    enforce_siu_access,
    get_current_user,
    require_roles,
)
from packages.security.sanitizer import mask_bank_account, sanitize_untrusted_text, validate_upload_bytes
from services.claims.audit import emit_outbox_event, record_audit_event
from services.claims.db import get_db
from services.claims.models import (
    Approval,
    AuditEvent,
    Claim,
    ClaimParty,
    Communication,
    Customer,
    DamageAssessment,
    Estimate,
    EstimateLine,
    Evidence,
    ExtractedFact,
    FraudAlert,
    Grievance,
    OutboxEvent,
    Payment,
    Policy,
    Provider,
    Settlement,
    SLATimer,
    SurveyAssignment,
    Vehicle,
)
from services.claims.state_machine import ClaimStatus, validate_transition
from services.damage_ai.assessor import assess_damage_from_evidence, validate_estimate_lines
from services.document_ai.processor import extract_document_facts
from services.fraud_intelligence.detector import build_entity_relationship_graph, run_fraud_and_anomaly_checks
from services.integrations.adapters import IntegrationAdapterRegistry
from services.rules_engine.loader import get_active_rule
from services.settlement.authority import validate_approval_authority
from services.settlement.calculator import SettlementCalculator, SettlementLineInput
from services.workflow.sla_engine import complete_stage_sla_timer, compute_timer_status, create_stage_sla_timer

router = APIRouter(prefix="/api/v1", tags=["claims"])


def _get_claim_for_user(db: Session, claim_id: str, user: UserContext) -> Claim:
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise DomainError(ErrorCode.NOT_FOUND, f"Claim '{claim_id}' not found", status_code=404)
    enforce_claim_abac(user, claim)
    return claim


def _build_agent_req(
    claim: Claim, user: UserContext, agent_name: str, facts: dict[str, Any]
) -> AgentInvocationRequest:
    agent = AGENT_REGISTRY[agent_name]
    return AgentInvocationRequest(
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        correlation_id=get_correlation_id(),
        workflow_run_id=claim.workflow_state.get("workflow_run_id", claim.id),
        actor_user_id=user.user_id,
        actor_role=user.role.value,
        product_code="PRIVATE_CAR_PACKAGE",
        claim_type=claim.claim_type,
        locale=claim.preferred_language,
        rule_versions={"irdai": "IN-IRDAI-MC-2024:1.0.0", "dep": "IN-MOTOR-DEPRECIATION-2024:1.0.0"},
        minimised_facts=facts,
        allowed_tools=sorted(agent.allowed_tools),
    )


def _serialize_claim_summary(c: Claim, db: Session) -> dict[str, Any]:
    timers = db.query(SLATimer).filter(SLATimer.claim_id == c.id).all()
    sla_flags = [compute_timer_status(t.due_at, t.completed_at, t.paused) for t in timers]
    sla_health = "breached" if "breached" in sla_flags else ("warning" if "warning" in sla_flags else "on_track")
    return {
        "id": c.id,
        "claim_number": c.claim_number,
        "claim_type": c.claim_type,
        "peril_cause": c.peril_cause,
        "status": c.status,
        "severity_band": c.severity_band,
        "queue_name": c.queue_name,
        "policy_number_input": c.policy_number_input,
        "vehicle_reg_input": c.vehicle_reg_input,
        "estimated_loss_inr": str(c.estimated_loss_inr),
        "requires_mandatory_survey": c.requires_mandatory_survey,
        "next_expected_action": c.next_expected_action,
        "assigned_surveyor_id": c.assigned_surveyor_id,
        "assigned_garage_id": c.assigned_garage_id,
        "sla_health": sla_health,
        "injury_or_fatality": c.injury_or_fatality,
        "ev_battery_impacted": c.ev_battery_impacted,
        "is_synthetic_demo": c.is_synthetic_demo,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }


@router.get("/claims")
def list_claims(
    status: Optional[str] = None,
    queue_name: Optional[str] = None,
    claim_type: Optional[str] = None,
    search: Optional[str] = None,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Claim).filter(Claim.tenant_id == user.tenant_id)
    if user.role == Role.POLICYHOLDER:
        q = q.filter(Claim.customer_id == user.partner_id)
    elif user.role == Role.GARAGE:
        q = q.filter(Claim.assigned_garage_id == user.partner_id)
    elif user.role == Role.SURVEYOR:
        q = q.filter(Claim.assigned_surveyor_id == user.partner_id)

    if status:
        q = q.filter(Claim.status == status)
    if queue_name:
        q = q.filter(Claim.queue_name == queue_name)
    if claim_type:
        q = q.filter(Claim.claim_type == claim_type)
    if search:
        like = f"%{search}%"
        q = q.filter(
            (Claim.claim_number.ilike(like))
            | (Claim.vehicle_reg_input.ilike(like))
            | (Claim.policy_number_input.ilike(like))
        )

    claims = q.order_by(Claim.created_at.desc()).all()
    return {"items": [_serialize_claim_summary(c, db) for c in claims], "total": len(claims)}


@router.post("/claims/intimations", status_code=201)
def create_fnol_intimation(
    body: FNOLCreateRequest,
    idempotency_key_hdr: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    idem_key = idempotency_key_hdr or body.idempotency_key
    if idem_key:
        existing = (
            db.query(Claim)
            .filter(Claim.tenant_id == user.tenant_id, Claim.idempotency_key == idem_key)
            .first()
        )
        if existing:
            return {
                "idempotent_replay": True,
                "claim": _serialize_claim_summary(existing, db),
                "acknowledgement": f"Claim {existing.claim_number} already registered.",
            }

    inc_at = body.incident_at or datetime.now(timezone.utc)
    if inc_at.tzinfo is None:
        inc_at = inc_at.replace(tzinfo=timezone.utc)

    policy = (
        db.query(Policy)
        .filter(Policy.tenant_id == user.tenant_id, Policy.policy_number == body.policy_number.upper())
        .first()
    )
    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.tenant_id == user.tenant_id, Vehicle.registration_number == body.vehicle_reg.upper())
        .first()
    )

    if user.role == Role.POLICYHOLDER and policy and policy.customer_id != user.partner_id:
        raise DomainError(ErrorCode.NOT_AUTHORISED, "Policy belongs to another customer", status_code=403)

    dup = (
        db.query(Claim)
        .filter(
            Claim.tenant_id == user.tenant_id,
            Claim.vehicle_reg_input == body.vehicle_reg.upper(),
            Claim.status != ClaimStatus.CLOSED.value,
        )
        .first()
    )

    irdai = get_active_rule(db, "IN-IRDAI-MC-2024")["controls"]
    threshold = Decimal(str(irdai["mandatory_survey_threshold_inr"]))
    req_survey = (
        body.estimated_loss_inr >= threshold
        or body.peril_cause in {"theft", "fire", "flood", "total_loss"}
        or body.injury_or_fatality
        or body.ev_battery_impacted
    )

    clean_desc, _, _ = sanitize_untrusted_text(body.incident_description)
    claim_num = f"CLM-DEMO-{datetime.now(timezone.utc).year}-{uuid.uuid4().hex[:6].upper()}"
    missing_docs = ["Policy Schedule", "Registration Certificate (RC)", "Driving Licence (DL)", "6-Angle Photos"]

    claim = Claim(
        tenant_id=user.tenant_id,
        claim_number=claim_num,
        idempotency_key=idem_key,
        policy_id=policy.id if policy else None,
        customer_id=policy.customer_id if policy else (user.partner_id if user.role == Role.POLICYHOLDER else None),
        vehicle_id=vehicle.id if vehicle else None,
        claim_type=body.claim_type,
        peril_cause=body.peril_cause,
        intake_channel=body.intake_channel,
        status=ClaimStatus.REGISTERED.value,
        severity_band="critical" if body.injury_or_fatality else ("high" if req_survey else "medium"),
        queue_name="legal_tp_specialist" if (body.injury_or_fatality or body.claim_type == "third_party") else "evidence_intake",
        incident_at=inc_at,
        incident_location=body.incident_location,
        incident_description=clean_desc,
        policy_number_input=body.policy_number.upper(),
        vehicle_reg_input=body.vehicle_reg.upper(),
        driver_name=body.driver_name,
        driver_licence_ref=body.driver_licence_ref,
        vehicle_immobile=body.vehicle_immobile,
        airbags_deployed=body.airbags_deployed,
        injury_or_fatality=body.injury_or_fatality,
        police_involved=body.police_involved,
        towing_needed=body.towing_needed,
        ev_battery_impacted=body.ev_battery_impacted or (vehicle.is_ev if vehicle else False),
        estimated_loss_inr=body.estimated_loss_inr,
        requires_mandatory_survey=req_survey,
        preferred_language=body.preferred_language,
        assigned_garage_id=body.preferred_garage_id,
        missing_documents=missing_docs,
        duplicate_candidate_claim_id=dup.id if dup else None,
        next_expected_action="Upload RC, DL, Policy Schedule, and 6 vehicle photos (claim accepted without blocking)",
        workflow_state={"workflow_run_id": f"wf-{uuid.uuid4().hex[:10]}", "steps_completed": ["FNOL_REGISTERED"]},
    )
    db.add(claim)
    db.flush()

    agent_req = _build_agent_req(
        claim,
        user,
        "fnol_concierge",
        {
            "policy_number": claim.policy_number_input,
            "vehicle_reg": claim.vehicle_reg_input,
            "incident_description": clean_desc,
            "incident_location": claim.incident_location,
            "intake_channel": claim.intake_channel,
        },
    )
    agent_res = AGENT_REGISTRY["fnol_concierge"].execute(agent_req)

    ack_comm = Communication(
        tenant_id=user.tenant_id,
        claim_id=claim.id,
        channel="portal",
        language=claim.preferred_language,
        template_id="FNOL_ACKNOWLEDGEMENT",
        subject=f"Claim {claim.claim_number} Registered (DEMO / SYNTHETIC)",
        body=f"Your motor claim {claim.claim_number} for vehicle {claim.vehicle_reg_input} has been registered. Next steps: {', '.join(missing_docs)}.",
        requires_human_review=False,
        delivery_status="sent_mock",
    )
    db.add(ack_comm)

    create_stage_sla_timer(db, tenant_id=user.tenant_id, claim_id=claim.id, stage="surveyor_allocation")
    emit_outbox_event(
        db,
        tenant_id=user.tenant_id,
        aggregate_id=claim.id,
        event_type="ClaimCreated",
        payload={"claim_number": claim.claim_number, "policy_number": claim.policy_number_input},
    )
    record_audit_event(
        db,
        tenant_id=user.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="CLAIM_INTIMATED_REGISTERED",
        object_type="claim",
        object_id=claim.id,
        after_state={"claim_number": claim.claim_number, "status": claim.status},
        details={"duplicate_candidate_id": dup.id if dup else None, "agent_status": agent_res.status.value},
    )
    db.commit()

    return {
        "idempotent_replay": False,
        "claim": _serialize_claim_summary(claim, db),
        "acknowledgement": ack_comm.body,
        "duplicate_review_alert": f"Potential related open claim: {dup.claim_number}" if dup else None,
        "agent_response": agent_res.model_dump(),
    }


@router.get("/claims/{claim_id}")
def get_claim_360(
    claim_id: str,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    policy = db.query(Policy).filter(Policy.id == claim.policy_id).first() if claim.policy_id else None
    vehicle = db.query(Vehicle).filter(Vehicle.id == claim.vehicle_id).first() if claim.vehicle_id else None
    customer = db.query(Customer).filter(Customer.id == claim.customer_id).first() if claim.customer_id else None

    parties = db.query(ClaimParty).filter(ClaimParty.claim_id == claim.id).all()
    filtered_parties = []
    for p in parties:
        if p.is_restricted_tp_medical and user.role not in TP_LEGAL_ALLOWED_ROLES:
            filtered_parties.append(
                {
                    "id": p.id,
                    "party_role": p.party_role,
                    "name": "[RESTRICTED TP/MEDICAL RECORD]",
                    "contact_masked": "****",
                    "is_restricted_tp_medical": True,
                    "notes": "Requires Legal/TP or authorised Claims Handler access.",
                }
            )
        else:
            filtered_parties.append(
                {
                    "id": p.id,
                    "party_role": p.party_role,
                    "name": p.name,
                    "contact_masked": p.contact_masked,
                    "is_restricted_tp_medical": p.is_restricted_tp_medical,
                    "notes": p.notes,
                }
            )

    evidences = db.query(Evidence).filter(Evidence.claim_id == claim.id).order_by(Evidence.created_at.desc()).all()
    facts = db.query(ExtractedFact).filter(ExtractedFact.claim_id == claim.id).all()
    damages = db.query(DamageAssessment).filter(DamageAssessment.claim_id == claim.id).all()
    estimates = db.query(Estimate).filter(Estimate.claim_id == claim.id).order_by(Estimate.version.asc()).all()
    est_payload = []
    for e in estimates:
        lines = db.query(EstimateLine).filter(EstimateLine.estimate_id == e.id).all()
        est_payload.append(
            {
                "id": e.id,
                "version": e.version,
                "is_supplement": e.is_supplement,
                "status": e.status,
                "total_claimed_inr": str(e.total_claimed_inr),
                "total_approved_inr": str(e.total_approved_inr),
                "anomalies": e.anomalies,
                "lines": [
                    {
                        "id": ln.id,
                        "part_code": ln.part_code,
                        "description": ln.description,
                        "part_category": ln.part_category,
                        "line_type": ln.line_type,
                        "action": ln.action,
                        "quantity": ln.quantity,
                        "unit_price_inr": str(ln.unit_price_inr),
                        "rate_card_price_inr": str(ln.rate_card_price_inr) if ln.rate_card_price_inr else None,
                        "approved_amount_inr": str(ln.approved_amount_inr) if ln.approved_amount_inr else None,
                        "variance_flag": ln.variance_flag,
                        "reviewer_status": ln.reviewer_status,
                    }
                    for ln in lines
                ],
            }
        )

    surveys = db.query(SurveyAssignment).filter(SurveyAssignment.claim_id == claim.id).all()
    settlements = db.query(Settlement).filter(Settlement.claim_id == claim.id).order_by(Settlement.version.desc()).all()
    approvals = db.query(Approval).filter(Approval.claim_id == claim.id).order_by(Approval.created_at.desc()).all()
    payments = db.query(Payment).filter(Payment.claim_id == claim.id).order_by(Payment.created_at.desc()).all()
    timers = db.query(SLATimer).filter(SLATimer.claim_id == claim.id).all()
    comms = db.query(Communication).filter(Communication.claim_id == claim.id).order_by(Communication.created_at.desc()).all()
    grievances = db.query(Grievance).filter(Grievance.claim_id == claim.id).all()
    audits = db.query(AuditEvent).filter(AuditEvent.claim_id == claim.id).order_by(AuditEvent.created_at.desc()).all()

    fraud_alerts_payload: list[dict[str, Any]] | None = None
    if user.role in SIU_ALLOWED_ROLES:
        alerts = db.query(FraudAlert).filter(FraudAlert.claim_id == claim.id).all()
        fraud_alerts_payload = [
            {
                "id": a.id,
                "indicator_code": a.indicator_code,
                "title": a.title,
                "severity_band": a.severity_band,
                "confidence": str(a.confidence),
                "evidence_summary": a.evidence_summary,
                "benign_explanation": a.benign_explanation,
                "recommended_action": a.recommended_action,
                "entity_links": a.entity_links,
                "status": a.status,
                "investigator_notes": a.investigator_notes,
                "disposition_reason": a.disposition_reason,
            }
            for a in alerts
        ]

    customer_payload = None
    if customer and user.role != Role.GARAGE:
        customer_payload = {
            "id": customer.id,
            "name": customer.name,
            "phone_masked": customer.phone_masked,
            "email_masked": customer.email_masked,
            "preferred_language": customer.preferred_language,
        }

    return {
        "claim": {
            **_serialize_claim_summary(claim, db),
            "incident_at": claim.incident_at.isoformat(),
            "incident_location": claim.incident_location,
            "incident_description": claim.incident_description,
            "driver_name": claim.driver_name,
            "driver_licence_ref": claim.driver_licence_ref,
            "vehicle_immobile": claim.vehicle_immobile,
            "airbags_deployed": claim.airbags_deployed,
            "police_involved": claim.police_involved,
            "towing_needed": claim.towing_needed,
            "missing_documents": claim.missing_documents,
            "coverage_factsheet": claim.coverage_factsheet,
            "triage_summary": claim.triage_summary,
            "workflow_state": claim.workflow_state,
            "duplicate_candidate_claim_id": claim.duplicate_candidate_claim_id,
            "assigned_handler_id": claim.assigned_handler_id,
        },
        "policy": {
            "id": policy.id,
            "policy_number": policy.policy_number,
            "product_code": policy.product_code,
            "uin": policy.uin,
            "status": policy.status,
            "period_start": policy.period_start.isoformat(),
            "period_end": policy.period_end.isoformat(),
            "idv_inr": str(policy.idv_inr),
            "compulsory_deductible_inr": str(policy.compulsory_deductible_inr),
            "voluntary_deductible_inr": str(policy.voluntary_deductible_inr),
            "addons": policy.addons,
            "endorsements": policy.endorsements,
        }
        if policy
        else None,
        "vehicle": {
            "id": vehicle.id,
            "registration_number": vehicle.registration_number,
            "vin_chassis": vehicle.vin_chassis,
            "make": vehicle.make,
            "model": vehicle.model,
            "year": vehicle.year,
            "fuel_type": vehicle.fuel_type,
            "is_ev": vehicle.is_ev,
            "first_registration_date": vehicle.first_registration_date.isoformat(),
        }
        if vehicle
        else None,
        "customer": customer_payload,
        "parties": filtered_parties,
        "evidence": [
            {
                "id": ev.id,
                "doc_type": ev.doc_type,
                "doc_status": ev.doc_status,
                "filename": ev.filename,
                "mime_type": ev.mime_type,
                "size_bytes": ev.size_bytes,
                "sha256": ev.sha256,
                "malware_scan_status": ev.malware_scan_status,
                "prompt_injection_flagged": ev.prompt_injection_flagged,
                "ocr_text": ev.ocr_text,
                "image_angle": ev.image_angle,
                "image_quality_status": ev.image_quality_status,
                "created_at": ev.created_at.isoformat(),
            }
            for ev in evidences
        ],
        "extracted_facts": [
            {
                "id": f.id,
                "evidence_id": f.evidence_id,
                "field_name": f.field_name,
                "extracted_value": f.extracted_value,
                "verified_value": f.verified_value,
                "confidence": str(f.confidence),
                "page_number": f.page_number,
                "bbox": f.bbox,
                "validation_status": f.validation_status,
            }
            for f in facts
        ],
        "damage_assessments": [
            {
                "id": d.id,
                "component_name": d.component_name,
                "part_code": d.part_code,
                "damage_class": d.damage_class,
                "observation_type": d.observation_type,
                "recommended_action": d.recommended_action,
                "confidence": str(d.confidence),
                "limitations": d.limitations,
                "reviewer_outcome": d.reviewer_outcome,
                "reviewer_notes": d.reviewer_notes,
            }
            for d in damages
        ],
        "estimates": est_payload,
        "surveys": [
            {
                "id": s.id,
                "surveyor_id": s.surveyor_id,
                "status": s.status,
                "assigned_at": s.assigned_at.isoformat(),
                "report_due_at": s.report_due_at.isoformat(),
                "report_received_at": s.report_received_at.isoformat() if s.report_received_at else None,
                "delay_reason": s.delay_reason,
                "report_summary": s.report_summary,
                "signed_by_surveyor": s.signed_by_surveyor,
            }
            for s in surveys
        ],
        "fraud_alerts_restricted": fraud_alerts_payload is None,
        "fraud_alerts": fraud_alerts_payload or [],
        "settlements": [
            {
                "id": s.id,
                "version": s.version,
                "pathway": s.pathway,
                "gross_assessed_inr": str(s.gross_assessed_inr),
                "depreciation_deduction_inr": str(s.depreciation_deduction_inr),
                "addon_waiver_inr": str(s.addon_waiver_inr),
                "compulsory_excess_inr": str(s.compulsory_excess_inr),
                "voluntary_excess_inr": str(s.voluntary_excess_inr),
                "salvage_deduction_inr": str(s.salvage_deduction_inr),
                "net_payable_inr": str(s.net_payable_inr),
                "is_total_loss": s.is_total_loss,
                "calculation_trace": s.calculation_trace,
                "rule_versions": s.rule_versions,
                "policy_citations": s.policy_citations,
                "approval_status": s.approval_status,
            }
            for s in settlements
        ],
        "approvals": [
            {
                "id": a.id,
                "settlement_id": a.settlement_id,
                "action_type": a.action_type,
                "amount_inr": str(a.amount_inr),
                "maker_user_id": a.maker_user_id,
                "checker_user_id": a.checker_user_id,
                "decision": a.decision,
                "rationale": a.rationale,
                "authority_rule_version": a.authority_rule_version,
                "created_at": a.created_at.isoformat(),
                "decided_at": a.decided_at.isoformat() if a.decided_at else None,
            }
            for a in approvals
        ],
        "payments": [
            {
                "id": p.id,
                "settlement_id": p.settlement_id,
                "idempotency_key": p.idempotency_key,
                "payee_type": p.payee_type,
                "payee_name": p.payee_name,
                "bank_account_masked": p.bank_account_masked,
                "bank_verified": p.bank_verified,
                "amount_inr": str(p.amount_inr),
                "status": p.status,
                "gateway_reference": p.gateway_reference,
                "created_at": p.created_at.isoformat(),
            }
            for p in payments
        ],
        "sla_timers": [
            {
                "id": t.id,
                "stage": t.stage,
                "status": compute_timer_status(t.due_at, t.completed_at, t.paused),
                "due_at": t.due_at.isoformat(),
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                "owner_role": t.owner_role,
                "daily_penalty_inr": str(t.daily_penalty_inr),
            }
            for t in timers
        ],
        "communications": [
            {
                "id": cm.id,
                "channel": cm.channel,
                "language": cm.language,
                "subject": cm.subject,
                "body": cm.body,
                "requires_human_review": cm.requires_human_review,
                "delivery_status": cm.delivery_status,
                "created_at": cm.created_at.isoformat(),
            }
            for cm in comms
        ],
        "grievances": [
            {
                "id": g.id,
                "category": g.category,
                "description": g.description,
                "status": g.status,
                "due_at": g.due_at.isoformat(),
                "resolution_notes": g.resolution_notes,
            }
            for g in grievances
        ],
        "audit_events": [
            {
                "id": au.id,
                "actor_id": au.actor_id,
                "actor_role": au.actor_role,
                "action": au.action,
                "object_type": au.object_type,
                "before_hash": au.before_hash[:12],
                "after_hash": au.after_hash[:12],
                "correlation_id": au.correlation_id,
                "outcome": au.outcome,
                "details": au.details,
                "created_at": au.created_at.isoformat(),
            }
            for au in audits
        ],
    }


@router.get("/claims/{claim_id}/timeline")
def get_claim_timeline(
    claim_id: str,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    audits = db.query(AuditEvent).filter(AuditEvent.claim_id == claim.id).order_by(AuditEvent.created_at.asc()).all()
    outbox = db.query(OutboxEvent).filter(OutboxEvent.aggregate_id == claim.id).order_by(OutboxEvent.created_at.asc()).all()
    return {
        "claim_id": claim.id,
        "claim_number": claim.claim_number,
        "audit_events": [
            {
                "id": a.id,
                "action": a.action,
                "actor_role": a.actor_role,
                "correlation_id": a.correlation_id,
                "details": a.details,
                "created_at": a.created_at.isoformat(),
            }
            for a in audits
        ],
        "domain_events": [
            {"id": e.id, "event_type": e.event_type, "status": e.status, "created_at": e.created_at.isoformat()}
            for e in outbox
        ],
    }


@router.post("/claims/{claim_id}/assign")
def assign_handler(
    claim_id: str,
    body: ClaimAssignRequest,
    user: UserContext = Depends(require_roles(Role.CLAIMS_MANAGER, Role.CLAIMS_HANDLER, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    claim.assigned_handler_id = body.assigned_handler_id
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="CLAIM_HANDLER_ASSIGNED",
        object_type="claim",
        object_id=claim.id,
        details={"assigned_handler_id": body.assigned_handler_id},
    )
    db.commit()
    return {"claim_id": claim.id, "assigned_handler_id": claim.assigned_handler_id}


@router.post("/claims/{claim_id}/evidence", status_code=201)
async def upload_evidence(
    claim_id: str,
    file: UploadFile = File(...),
    text_override: Optional[str] = Form(default=None),
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    settings = get_settings()
    raw_bytes = await file.read()
    try:
        meta = validate_upload_bytes(
            file.filename or "upload.bin",
            file.content_type or "application/octet-stream",
            raw_bytes,
            max_mb=settings.max_upload_size_mb,
        )
    except ValueError as exc:
        raise DomainError(ErrorCode.VALIDATION_ERROR, str(exc), status_code=400) from exc

    store_dir = Path(settings.evidence_storage_dir) / claim.tenant_id / claim.id
    store_dir.mkdir(parents=True, exist_ok=True)
    target_path = store_dir / f"{meta['sha256'][:12]}_{Path(meta['filename']).name}"
    target_path.write_bytes(raw_bytes)

    extraction = extract_document_facts(
        filename=meta["filename"],
        mime_type=meta["mime_type"],
        raw_bytes=raw_bytes,
        policy_number_expected=claim.policy_number_input,
        vehicle_reg_expected=claim.vehicle_reg_input,
        text_override=text_override,
    )

    ev = Evidence(
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        doc_type=extraction["doc_type"],
        doc_status="inconsistent"
        if any(f["validation_status"] == "mismatch" for f in extraction["facts"])
        else "extracted_unverified",
        filename=meta["filename"],
        mime_type=meta["mime_type"],
        size_bytes=meta["size_bytes"],
        sha256=meta["sha256"],
        storage_path=str(target_path),
        uploader_user_id=user.user_id,
        upload_source=user.role.value,
        malware_scan_status=meta["malware_scan"],
        prompt_injection_flagged=extraction["prompt_injection_flagged"],
        ocr_version=extraction["ocr_version"],
        ocr_text=extraction["sanitized_text"],
        image_angle=extraction["image_quality"]["angle"] if extraction["image_quality"] else None,
        image_quality_status=extraction["image_quality"]["quality_status"] if extraction["image_quality"] else None,
    )
    db.add(ev)
    db.flush()

    created_facts = []
    for f in extraction["facts"]:
        ef = ExtractedFact(
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            evidence_id=ev.id,
            field_name=f["field_name"],
            extracted_value=f["extracted_value"],
            confidence=Decimal(str(f["confidence"])),
            page_number=f["page_number"],
            bbox=f["bbox"],
            validation_status=f["validation_status"],
        )
        db.add(ef)
        created_facts.append(f)

    doc_label_map = {
        "policy_schedule": "Policy Schedule",
        "registration_certificate": "Registration Certificate (RC)",
        "driving_licence": "Driving Licence (DL)",
        "damage_photo": "6-Angle Photos",
    }
    matched_label = doc_label_map.get(extraction["doc_type"])
    if matched_label and matched_label in (claim.missing_documents or []):
        claim.missing_documents = [d for d in claim.missing_documents if d != matched_label]

    agent_res = AGENT_REGISTRY["document_intelligence"].execute(
        _build_agent_req(
            claim,
            user,
            "document_intelligence",
            {
                "extracted_facts": created_facts,
                "prompt_injection_flagged": extraction["prompt_injection_flagged"],
            },
        )
    )

    emit_outbox_event(
        db,
        tenant_id=claim.tenant_id,
        aggregate_id=claim.id,
        event_type="EvidenceUploaded",
        payload={"evidence_id": ev.id, "doc_type": ev.doc_type, "sha256": ev.sha256},
    )
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="EVIDENCE_UPLOADED_AND_EXTRACTED",
        object_type="evidence",
        object_id=ev.id,
        after_state={"sha256": ev.sha256, "doc_type": ev.doc_type, "injection": ev.prompt_injection_flagged},
    )
    db.commit()

    return {
        "evidence_id": ev.id,
        "doc_type": ev.doc_type,
        "doc_status": ev.doc_status,
        "sha256": ev.sha256,
        "malware_scan_status": ev.malware_scan_status,
        "prompt_injection_flagged": ev.prompt_injection_flagged,
        "image_quality": extraction["image_quality"],
        "extracted_facts": created_facts,
        "agent_response": agent_res.model_dump(),
    }


@router.get("/claims/{claim_id}/evidence")
def list_evidence(
    claim_id: str,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    items = db.query(Evidence).filter(Evidence.claim_id == claim.id).all()
    return {
        "items": [
            {
                "id": ev.id,
                "doc_type": ev.doc_type,
                "doc_status": ev.doc_status,
                "filename": ev.filename,
                "sha256": ev.sha256,
                "prompt_injection_flagged": ev.prompt_injection_flagged,
                "image_quality_status": ev.image_quality_status,
            }
            for ev in items
        ]
    }


@router.patch("/claims/{claim_id}/evidence/{evidence_id}/facts/{fact_id}")
def correct_extracted_fact(
    claim_id: str,
    evidence_id: str,
    fact_id: str,
    body: FactCorrectionRequest,
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    fact = (
        db.query(ExtractedFact)
        .filter(
            ExtractedFact.id == fact_id,
            ExtractedFact.evidence_id == evidence_id,
            ExtractedFact.claim_id == claim.id,
        )
        .first()
    )
    if not fact:
        raise DomainError(ErrorCode.NOT_FOUND, "Extracted fact not found", status_code=404)

    before = {"extracted_value": fact.extracted_value, "validation_status": fact.validation_status}
    fact.verified_value = body.verified_value
    fact.validation_status = body.validation_status
    fact.verified_by = user.user_id

    ev = db.query(Evidence).filter(Evidence.id == evidence_id).first()
    if ev:
        ev.doc_status = "verified"

    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="EXTRACTED_FACT_VERIFIED",
        object_type="extracted_fact",
        object_id=fact.id,
        before_state=before,
        after_state={"verified_value": fact.verified_value, "validation_status": fact.validation_status},
    )
    db.commit()
    return {"id": fact.id, "verified_value": fact.verified_value, "validation_status": fact.validation_status}


@router.post("/claims/{claim_id}/coverage-checks")
def run_coverage_check(
    claim_id: str,
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    policy = db.query(Policy).filter(Policy.id == claim.policy_id).first() if claim.policy_id else None
    vehicle = db.query(Vehicle).filter(Vehicle.id == claim.vehicle_id).first() if claim.vehicle_id else None
    facts_rows = db.query(ExtractedFact).filter(ExtractedFact.claim_id == claim.id).all()
    has_mismatch = any(f.validation_status == "mismatch" for f in facts_rows)

    period_valid = False
    if policy:
        ps = policy.period_start.replace(tzinfo=timezone.utc) if policy.period_start.tzinfo is None else policy.period_start
        pe = policy.period_end.replace(tzinfo=timezone.utc) if policy.period_end.tzinfo is None else policy.period_end
        inc = claim.incident_at.replace(tzinfo=timezone.utc) if claim.incident_at.tzinfo is None else claim.incident_at
        period_valid = ps <= inc <= pe

    agent_res = AGENT_REGISTRY["coverage_intelligence"].execute(
        _build_agent_req(
            claim,
            user,
            "coverage_intelligence",
            {
                "peril_cause": claim.peril_cause,
                "claim_type": claim.claim_type,
                "injury_or_fatality": claim.injury_or_fatality,
                "is_ev": vehicle.is_ev if vehicle else claim.ev_battery_impacted,
                "period_valid": period_valid,
                "policy_status": policy.status if policy else "not_matched",
                "addons": policy.addons if policy else {},
                "has_document_mismatch": has_mismatch,
                "missing_documents": claim.missing_documents,
            },
        )
    )

    claim.coverage_factsheet = agent_res.model_dump()
    if claim.status in {ClaimStatus.REGISTERED.value, ClaimStatus.EVIDENCE_PENDING.value}:
        claim.status = validate_transition(claim.status, ClaimStatus.COVERAGE_CHECKED.value).value
    claim.next_expected_action = (
        "Resolve policy/document mismatch before proceeding" if has_mismatch else "Run claim triage & severity assessment"
    )
    emit_outbox_event(
        db, tenant_id=claim.tenant_id, aggregate_id=claim.id, event_type="CoverageCheckCompleted", payload={"status": agent_res.status.value}
    )
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="COVERAGE_CHECK_COMPLETED",
        object_type="claim",
        object_id=claim.id,
        details={"confidence": agent_res.confidence, "period_valid": period_valid},
    )
    db.commit()
    return {"claim_status": claim.status, "coverage_factsheet": claim.coverage_factsheet}


@router.post("/claims/{claim_id}/triage")
def run_claim_triage(
    claim_id: str,
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    vehicle = db.query(Vehicle).filter(Vehicle.id == claim.vehicle_id).first() if claim.vehicle_id else None
    agent_res = AGENT_REGISTRY["claim_triage"].execute(
        _build_agent_req(
            claim,
            user,
            "claim_triage",
            {
                "estimated_loss_inr": str(claim.estimated_loss_inr),
                "injury_or_fatality": claim.injury_or_fatality,
                "ev_battery_impacted": claim.ev_battery_impacted,
                "is_ev": vehicle.is_ev if vehicle else False,
                "claim_type": claim.claim_type,
                "peril_cause": claim.peril_cause,
            },
        )
    )
    res_data = agent_res.result
    if "severity_band" in res_data:
        claim.severity_band = res_data["severity_band"]
        claim.queue_name = res_data["recommended_queue"]
        claim.requires_mandatory_survey = bool(res_data["requires_mandatory_survey"])
    claim.triage_summary = agent_res.model_dump()
    if claim.status in {ClaimStatus.REGISTERED.value, ClaimStatus.EVIDENCE_PENDING.value, ClaimStatus.COVERAGE_CHECKED.value}:
        claim.status = validate_transition(claim.status, ClaimStatus.TRIAGED.value).value
    claim.next_expected_action = (
        "Assign registered surveyor (IRDAI threshold/peril)" if claim.requires_mandatory_survey else "Run AI damage assessment"
    )
    emit_outbox_event(db, tenant_id=claim.tenant_id, aggregate_id=claim.id, event_type="TriageCompleted", payload=res_data)
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="CLAIM_TRIAGED",
        object_type="claim",
        object_id=claim.id,
        details={"queue": claim.queue_name, "severity": claim.severity_band, "mandatory_survey": claim.requires_mandatory_survey},
    )
    db.commit()
    return {"claim_status": claim.status, "triage": claim.triage_summary}


@router.post("/claims/{claim_id}/damage-assessments")
def run_damage_assessment(
    claim_id: str,
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES, Role.SURVEYOR)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    vehicle = db.query(Vehicle).filter(Vehicle.id == claim.vehicle_id).first() if claim.vehicle_id else None
    images = (
        db.query(Evidence)
        .filter(Evidence.claim_id == claim.id, Evidence.mime_type.like("image/%"))
        .all()
    )
    img_records = [
        {"filename": im.filename, "image_angle": im.image_angle, "image_quality_status": im.image_quality_status}
        for im in images
    ]
    payload = assess_damage_from_evidence(
        claim_description=claim.incident_description,
        is_ev=vehicle.is_ev if vehicle else claim.ev_battery_impacted,
        ev_battery_impacted=claim.ev_battery_impacted,
        image_records=img_records,
    )
    agent_res = AGENT_REGISTRY["damage_assessment"].execute(
        _build_agent_req(claim, user, "damage_assessment", {"assessment_payload": payload})
    )

    db.query(DamageAssessment).filter(
        DamageAssessment.claim_id == claim.id, DamageAssessment.reviewer_outcome == "pending"
    ).delete()

    saved = []
    for obs in payload["observations"]:
        da = DamageAssessment(
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            component_name=obs["component_name"],
            part_code=obs["part_code"],
            damage_class=obs["damage_class"],
            observation_type=obs["observation_type"],
            recommended_action=obs["recommended_action"],
            confidence=Decimal(str(obs["confidence"])),
            limitations=obs["limitations"],
            model_version=payload["model_version"],
        )
        db.add(da)
        saved.append(obs)

    emit_outbox_event(
        db, tenant_id=claim.tenant_id, aggregate_id=claim.id, event_type="DamageAssessmentCompleted", payload={"count": len(saved)}
    )
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="DAMAGE_ASSESSMENT_EXECUTED",
        object_type="claim",
        object_id=claim.id,
        details={"observations": len(saved), "missing_angles": payload["missing_angles"]},
    )
    db.commit()
    return {"observations": saved, "agent_response": agent_res.model_dump()}


@router.patch("/claims/{claim_id}/damage-assessments/{assessment_id}")
def review_damage_observation(
    claim_id: str,
    assessment_id: str,
    body: DamageReviewRequest,
    user: UserContext = Depends(require_roles(Role.SURVEYOR, Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    da = db.query(DamageAssessment).filter(DamageAssessment.id == assessment_id, DamageAssessment.claim_id == claim.id).first()
    if not da:
        raise DomainError(ErrorCode.NOT_FOUND, "Damage assessment row not found", status_code=404)
    da.reviewer_outcome = body.reviewer_outcome
    da.reviewer_notes = body.reviewer_notes
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="DAMAGE_OBSERVATION_REVIEWED",
        object_type="damage_assessment",
        object_id=da.id,
        details={"outcome": body.reviewer_outcome},
    )
    db.commit()
    return {"id": da.id, "reviewer_outcome": da.reviewer_outcome}


@router.post("/claims/{claim_id}/estimates", status_code=201)
def submit_and_validate_estimate(
    claim_id: str,
    body: EstimateSubmitRequest,
    user: UserContext = Depends(require_roles(Role.GARAGE, Role.CLAIMS_HANDLER, Role.SURVEYOR, Role.CLAIMS_MANAGER, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    visible_parts = {
        d.part_code
        for d in db.query(DamageAssessment).filter(DamageAssessment.claim_id == claim.id).all()
        if d.part_code
    }
    raw_lines = [ln.model_dump() for ln in body.lines]
    val = validate_estimate_lines(raw_lines, visible_part_codes=visible_parts or None)
    agent_res = AGENT_REGISTRY["estimate_validation"].execute(
        _build_agent_req(claim, user, "estimate_validation", {"estimate_validation": val})
    )

    prev_count = db.query(Estimate).filter(Estimate.claim_id == claim.id).count()
    est = Estimate(
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        garage_id=body.garage_id or claim.assigned_garage_id,
        version=prev_count + 1,
        is_supplement=body.is_supplement,
        status="validated" if not val["anomalies"] else "disputed",
        total_claimed_inr=Decimal(val["total_claimed_inr"]),
        total_approved_inr=Decimal(val["total_recommended_inr"]),
        anomalies=val["anomalies"],
    )
    db.add(est)
    db.flush()

    for ln in val["lines"]:
        db.add(
            EstimateLine(
                estimate_id=est.id,
                part_code=ln["part_code"],
                description=ln["description"],
                part_category=ln["part_category"],
                line_type=ln["line_type"],
                action=ln["action"],
                quantity=ln["quantity"],
                unit_price_inr=Decimal(str(ln["unit_price_inr"])),
                rate_card_price_inr=Decimal(ln["rate_card_price_inr"]) if ln["rate_card_price_inr"] else None,
                approved_amount_inr=Decimal(ln["approved_amount_inr"]),
                variance_flag=ln["variance_flag"],
                reviewer_status="pending" if ln["variance_flag"] else "accepted",
            )
        )

    if claim.status in {
        ClaimStatus.TRIAGED.value,
        ClaimStatus.SURVEY_ASSIGNED.value,
        ClaimStatus.AI_ASSESSMENT.value,
        ClaimStatus.REPAIR_IN_PROGRESS.value,
    }:
        claim.status = validate_transition(claim.status, ClaimStatus.ESTIMATE_REVIEW.value).value
    claim.estimated_loss_inr = est.total_claimed_inr
    emit_outbox_event(
        db, tenant_id=claim.tenant_id, aggregate_id=claim.id, event_type="EstimateValidated", payload={"estimate_id": est.id}
    )
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="ESTIMATE_SUBMITTED_AND_VALIDATED",
        object_type="estimate",
        object_id=est.id,
        details={"claimed": str(est.total_claimed_inr), "recommended": str(est.total_approved_inr), "anomalies": len(val["anomalies"])},
    )
    db.commit()
    return {"estimate_id": est.id, "validation": val, "agent_response": agent_res.model_dump()}


@router.patch("/claims/{claim_id}/estimates/{estimate_id}/lines/{line_id}")
def review_estimate_line(
    claim_id: str,
    estimate_id: str,
    line_id: str,
    body: EstimateLineReviewRequest,
    user: UserContext = Depends(require_roles(Role.SURVEYOR, Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    line = db.query(EstimateLine).filter(EstimateLine.id == line_id, EstimateLine.estimate_id == estimate_id).first()
    if not line:
        raise DomainError(ErrorCode.NOT_FOUND, "Estimate line not found", status_code=404)

    line.reviewer_status = body.reviewer_status
    if body.reviewer_status == "rejected":
        line.approved_amount_inr = Decimal("0.00")
    elif body.approved_amount_inr is not None:
        line.approved_amount_inr = body.approved_amount_inr

    est = db.query(Estimate).filter(Estimate.id == estimate_id).first()
    if est:
        all_lines = db.query(EstimateLine).filter(EstimateLine.estimate_id == est.id).all()
        est.total_approved_inr = sum((Decimal(str(ln.approved_amount_inr or 0)) for ln in all_lines), Decimal("0.00"))
        est.status = "approved"

    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="ESTIMATE_LINE_REVIEWED",
        object_type="estimate_line",
        object_id=line.id,
        details={"status": body.reviewer_status, "approved_amount": str(line.approved_amount_inr)},
    )
    db.commit()
    return {"id": line.id, "reviewer_status": line.reviewer_status, "approved_amount_inr": str(line.approved_amount_inr)}


@router.post("/claims/{claim_id}/surveyor-assignments")
def assign_surveyor_and_garage(
    claim_id: str,
    body: SurveyorAssignRequest,
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    if body.garage_id:
        garage = db.query(Provider).filter(Provider.id == body.garage_id, Provider.provider_type == "garage").first()
        if not garage:
            raise DomainError(ErrorCode.NOT_FOUND, "Selected garage not found", status_code=404)
        claim.assigned_garage_id = garage.id

    surveyor: Provider | None = None
    if body.surveyor_id:
        surveyor = db.query(Provider).filter(Provider.id == body.surveyor_id, Provider.provider_type == "surveyor").first()
    else:
        surveyor = (
            db.query(Provider)
            .filter(
                Provider.tenant_id == claim.tenant_id,
                Provider.provider_type == "surveyor",
                Provider.licence_status == "verified",
                Provider.is_available.is_(True),
            )
            .order_by(Provider.active_load.asc())
            .first()
        )

    if not surveyor:
        raise DomainError(ErrorCode.DEPENDENCY_UNAVAILABLE, "No available licensed surveyor in roster", status_code=503)
    if surveyor.licence_status != "verified":
        raise DomainError(ErrorCode.VALIDATION_ERROR, "Cannot assign an unverified/unlicensed surveyor", status_code=400)

    irdai = get_active_rule(db, "IN-IRDAI-MC-2024")["controls"]
    due_at = datetime.now(timezone.utc) + timedelta(days=int(irdai["survey_report_due_days"]))
    sa = SurveyAssignment(
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        surveyor_id=surveyor.id,
        status="assigned",
        report_due_at=due_at,
    )
    db.add(sa)
    surveyor.active_load += 1
    claim.assigned_surveyor_id = surveyor.id
    if claim.status in {ClaimStatus.REGISTERED.value, ClaimStatus.COVERAGE_CHECKED.value, ClaimStatus.TRIAGED.value, ClaimStatus.ESTIMATE_REVIEW.value}:
        claim.status = validate_transition(claim.status, ClaimStatus.SURVEY_ASSIGNED.value).value
    claim.next_expected_action = f"Surveyor {surveyor.name} to inspect vehicle & submit report by {due_at.date()}"

    complete_stage_sla_timer(db, claim_id=claim.id, stage="surveyor_allocation")
    create_stage_sla_timer(db, tenant_id=claim.tenant_id, claim_id=claim.id, stage="survey_report_submission")

    db.add(
        Communication(
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            channel="sms",
            language=claim.preferred_language,
            template_id="SURVEYOR_APPOINTED",
            subject=f"Surveyor Appointed for {claim.claim_number}",
            body=f"Registered Surveyor {surveyor.name} (Licence {surveyor.licence_or_contract_id}) appointed. Report due within 15 days per IRDAI norms.",
            delivery_status="sent_mock",
        )
    )
    emit_outbox_event(
        db, tenant_id=claim.tenant_id, aggregate_id=claim.id, event_type="SurveyorAssigned", payload={"surveyor_id": surveyor.id}
    )
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="SURVEYOR_ASSIGNED",
        object_type="survey_assignment",
        object_id=surveyor.id,
        details={"surveyor_name": surveyor.name, "licence": surveyor.licence_or_contract_id},
    )
    db.commit()
    return {"assignment_id": sa.id, "surveyor_name": surveyor.name, "report_due_at": due_at.isoformat()}


@router.post("/claims/{claim_id}/survey-reports")
def submit_survey_report(
    claim_id: str,
    body: SurveyReportSubmitRequest,
    user: UserContext = Depends(require_roles(Role.SURVEYOR, Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    sa = db.query(SurveyAssignment).filter(SurveyAssignment.claim_id == claim.id).order_by(SurveyAssignment.assigned_at.desc()).first()
    if not sa:
        raise DomainError(ErrorCode.NOT_FOUND, "No surveyor assignment found for this claim", status_code=404)

    sa.status = "report_submitted"
    sa.report_received_at = datetime.now(timezone.utc)
    sa.signed_by_surveyor = body.signed
    sa.report_summary = {
        "inspection_notes": body.inspection_notes,
        "assessed_gross_inr": str(body.assessed_gross_inr),
        "hidden_damage_found": body.hidden_damage_found,
        "recommended_pathway": body.recommended_pathway,
    }
    complete_stage_sla_timer(db, claim_id=claim.id, stage="survey_report_submission")
    create_stage_sla_timer(db, tenant_id=claim.tenant_id, claim_id=claim.id, stage="claim_decision")
    if claim.status == ClaimStatus.SURVEY_ASSIGNED.value:
        claim.status = validate_transition(claim.status, ClaimStatus.ESTIMATE_REVIEW.value).value
    claim.next_expected_action = "Generate deterministic settlement recommendation"

    emit_outbox_event(
        db, tenant_id=claim.tenant_id, aggregate_id=claim.id, event_type="SurveyReportReceived", payload={"survey_id": sa.id}
    )
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="SURVEY_REPORT_SUBMITTED",
        object_type="survey_assignment",
        object_id=sa.id,
        details=sa.report_summary,
    )
    db.commit()
    return {"survey_id": sa.id, "status": sa.status, "report_summary": sa.report_summary}


@router.post("/claims/{claim_id}/fraud-checks")
def run_fraud_checks(
    claim_id: str,
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    indicators = run_fraud_and_anomaly_checks(db, claim)
    created = []
    for ind in indicators:
        exists = (
            db.query(FraudAlert)
            .filter(FraudAlert.claim_id == claim.id, FraudAlert.indicator_code == ind["indicator_code"])
            .first()
        )
        if not exists:
            fa = FraudAlert(
                tenant_id=claim.tenant_id,
                claim_id=claim.id,
                indicator_code=ind["indicator_code"],
                title=ind["title"],
                severity_band=ind["severity_band"],
                confidence=ind["confidence"],
                evidence_summary=ind["evidence_summary"],
                benign_explanation=ind["benign_explanation"],
                recommended_action=ind["recommended_action"],
                entity_links=ind["entity_links"],
                status="new",
            )
            db.add(fa)
            created.append(ind["indicator_code"])

    agent_res = AGENT_REGISTRY["fraud_intelligence"].execute(
        _build_agent_req(
            claim,
            user,
            "fraud_intelligence",
            {"indicators": [{**i, "confidence": str(i["confidence"])} for i in indicators]},
        )
    )
    if created:
        emit_outbox_event(
            db, tenant_id=claim.tenant_id, aggregate_id=claim.id, event_type="FraudAlertRaised", payload={"codes": created}
        )
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="FRAUD_INDICATORS_EVALUATED",
        object_type="claim",
        object_id=claim.id,
        details={"new_alerts": created},
    )
    db.commit()
    return {"new_alerts": created, "agent_response": agent_res.model_dump()}


@router.get("/siu/alerts")
def list_siu_alerts(
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enforce_siu_access(user)
    alerts = db.query(FraudAlert).filter(FraudAlert.tenant_id == user.tenant_id).order_by(FraudAlert.created_at.desc()).all()
    return {
        "items": [
            {
                "id": a.id,
                "claim_id": a.claim_id,
                "indicator_code": a.indicator_code,
                "title": a.title,
                "severity_band": a.severity_band,
                "confidence": str(a.confidence),
                "evidence_summary": a.evidence_summary,
                "benign_explanation": a.benign_explanation,
                "recommended_action": a.recommended_action,
                "entity_links": a.entity_links,
                "status": a.status,
                "investigator_notes": a.investigator_notes,
                "disposition_reason": a.disposition_reason,
            }
            for a in alerts
        ]
    }


@router.post("/claims/{claim_id}/fraud-alerts/{alert_id}/disposition")
def disposition_fraud_alert(
    claim_id: str,
    alert_id: str,
    body: FraudDispositionRequest,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enforce_siu_access(user)
    claim = _get_claim_for_user(db, claim_id, user)
    alert = db.query(FraudAlert).filter(FraudAlert.id == alert_id, FraudAlert.claim_id == claim.id).first()
    if not alert:
        raise DomainError(ErrorCode.NOT_FOUND, "Fraud alert not found", status_code=404)

    before = {"status": alert.status}
    alert.status = body.status
    alert.assigned_investigator_id = user.user_id
    if body.investigator_notes:
        alert.investigator_notes = body.investigator_notes
    if body.disposition_reason:
        alert.disposition_reason = body.disposition_reason

    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="SIU_ALERT_DISPOSITIONED",
        object_type="fraud_alert",
        object_id=alert.id,
        before_state=before,
        after_state={"status": alert.status, "reason": alert.disposition_reason},
    )
    db.commit()
    return {"id": alert.id, "status": alert.status, "disposition_reason": alert.disposition_reason}


@router.get("/claims/{claim_id}/entity-graph")
def get_entity_graph(
    claim_id: str,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enforce_siu_access(user)
    claim = _get_claim_for_user(db, claim_id, user)
    return build_entity_relationship_graph(db, claim)


@router.post("/claims/{claim_id}/settlement-recommendations", status_code=201)
def recommend_settlement(
    claim_id: str,
    body: SettlementRecommendRequest,
    user: UserContext = Depends(require_roles(Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.LEGAL_TP, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    policy = db.query(Policy).filter(Policy.id == claim.policy_id).first() if claim.policy_id else None
    vehicle = db.query(Vehicle).filter(Vehicle.id == claim.vehicle_id).first() if claim.vehicle_id else None
    if not policy or not vehicle:
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            "Matched Policy and Vehicle are required for deterministic settlement calculation",
            status_code=400,
        )

    estimates = db.query(Estimate).filter(Estimate.claim_id == claim.id).order_by(Estimate.version.desc()).all()
    if not estimates:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "Submit at least one repair estimate before calculating settlement", status_code=400)

    lines_input: list[SettlementLineInput] = []
    for est in estimates:
        est_lines = db.query(EstimateLine).filter(EstimateLine.estimate_id == est.id).all()
        for ln in est_lines:
            if ln.reviewer_status == "rejected":
                continue
            amt = Decimal(str(ln.approved_amount_inr if ln.approved_amount_inr is not None else ln.unit_price_inr * ln.quantity))
            if amt <= Decimal("0.00"):
                continue
            lines_input.append(
                SettlementLineInput(
                    part_code=ln.part_code,
                    description=ln.description,
                    part_category=ln.part_category,
                    line_type=ln.line_type,
                    approved_amount_inr=amt,
                )
            )

    calc = SettlementCalculator().calculate(
        db=db,
        lines=lines_input,
        vehicle_first_reg=vehicle.first_registration_date,
        incident_at=claim.incident_at,
        idv_inr=Decimal(str(policy.idv_inr)),
        compulsory_deductible_inr=Decimal(str(policy.compulsory_deductible_inr)),
        voluntary_deductible_inr=Decimal(str(policy.voluntary_deductible_inr)),
        addons=policy.addons or {},
        salvage_value_inr=body.salvage_value_inr,
        requested_pathway=body.requested_pathway,
    )

    prev_count = db.query(Settlement).filter(Settlement.claim_id == claim.id).count()
    stl = Settlement(
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        version=prev_count + 1,
        pathway=calc.pathway,
        gross_assessed_inr=calc.gross_assessed_inr,
        depreciation_deduction_inr=calc.depreciation_deduction_inr,
        compulsory_excess_inr=calc.compulsory_excess_inr,
        voluntary_excess_inr=calc.voluntary_excess_inr,
        salvage_deduction_inr=calc.salvage_deduction_inr,
        addon_waiver_inr=calc.addon_waiver_inr,
        net_payable_inr=calc.net_payable_inr,
        is_total_loss=calc.is_total_loss,
        calculation_trace=calc.calculation_trace,
        rule_versions=calc.rule_versions,
        policy_citations=calc.policy_citations,
        approval_status="pending_checker",
        created_by=user.user_id,
    )
    db.add(stl)
    db.flush()

    approval = Approval(
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        settlement_id=stl.id,
        action_type="settlement_checker",
        amount_inr=calc.net_payable_inr,
        maker_user_id=user.user_id,
        decision="pending",
        rationale="Pending independent checker approval under DoA matrix",
    )
    db.add(approval)

    agent_res = AGENT_REGISTRY["settlement_recommendation"].execute(
        _build_agent_req(
            claim,
            user,
            "settlement_recommendation",
            {"calculation": {"gross": str(calc.gross_assessed_inr), "net": str(calc.net_payable_inr)}},
        )
    )

    if claim.status in {
        ClaimStatus.TRIAGED.value,
        ClaimStatus.SURVEY_ASSIGNED.value,
        ClaimStatus.AI_ASSESSMENT.value,
        ClaimStatus.ESTIMATE_REVIEW.value,
    }:
        claim.status = validate_transition(claim.status, ClaimStatus.SETTLEMENT_RECOMMENDED.value).value
    claim.status = validate_transition(claim.status, ClaimStatus.APPROVAL_PENDING.value).value
    claim.next_expected_action = f"Authorised checker approval required for INR {calc.net_payable_inr}"

    complete_stage_sla_timer(db, claim_id=claim.id, stage="claim_decision")
    emit_outbox_event(
        db,
        tenant_id=claim.tenant_id,
        aggregate_id=claim.id,
        event_type="SettlementRecommended",
        payload={"settlement_id": stl.id, "net_payable_inr": str(calc.net_payable_inr)},
    )
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="SETTLEMENT_RECOMMENDED",
        object_type="settlement",
        object_id=stl.id,
        after_state={"net_payable_inr": str(calc.net_payable_inr), "pathway": calc.pathway},
    )
    db.commit()
    return {"settlement_id": stl.id, "approval_id": approval.id, "net_payable_inr": str(calc.net_payable_inr), "agent_response": agent_res.model_dump()}


@router.post("/claims/{claim_id}/approvals")
def decide_approval(
    claim_id: str,
    body: ApprovalDecisionRequest,
    user: UserContext = Depends(require_roles(Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.LEGAL_TP, Role.FINANCE_APPROVER, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    approval = db.query(Approval).filter(Approval.id == body.approval_id, Approval.claim_id == claim.id).first()
    if not approval:
        raise DomainError(ErrorCode.NOT_FOUND, "Approval task not found", status_code=404)

    open_alerts = (
        db.query(FraudAlert)
        .filter(FraudAlert.claim_id == claim.id, FraudAlert.status.in_(["new", "assigned", "investigating"]))
        .count()
    )
    conditions: list[str] = []
    if open_alerts > 0:
        conditions.append("fraud_alert_open")
    if claim.injury_or_fatality:
        conditions.append("tp_injury")
    if claim.ev_battery_impacted:
        conditions.append("ev_battery")

    doa_ver = validate_approval_authority(
        db,
        user=user,
        claim_type=claim.claim_type,
        amount_inr=Decimal(str(approval.amount_inr)),
        active_conditions=conditions,
        maker_user_id=approval.maker_user_id,
    )

    approval.checker_user_id = user.user_id
    approval.decision = body.decision
    approval.rationale = body.rationale
    approval.authority_rule_version = doa_ver
    approval.decided_at = datetime.now(timezone.utc)

    stl = db.query(Settlement).filter(Settlement.id == approval.settlement_id).first() if approval.settlement_id else None
    if body.decision == "approved":
        if stl:
            stl.approval_status = "approved"
        claim.status = validate_transition(claim.status, ClaimStatus.APPROVED.value).value
        claim.next_expected_action = "Finance Approver to verify payee bank & initiate payment"
        event_type = "ApprovalGranted"
    else:
        if stl:
            stl.approval_status = "rejected"
        claim.status = validate_transition(claim.status, ClaimStatus.CLARIFICATION_REQUESTED.value).value
        claim.next_expected_action = f"Returned by checker: {body.rationale}"
        event_type = "ApprovalRejected"

    emit_outbox_event(
        db, tenant_id=claim.tenant_id, aggregate_id=claim.id, event_type=event_type, payload={"approval_id": approval.id}
    )
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="APPROVAL_DECIDED",
        object_type="approval",
        object_id=approval.id,
        after_state={"decision": body.decision, "rationale": body.rationale},
    )
    db.commit()
    return {"approval_id": approval.id, "decision": approval.decision, "claim_status": claim.status}


@router.post("/claims/{claim_id}/approvals/bulk")
def reject_bulk_approval(user: UserContext = Depends(get_current_user)):
    raise DomainError(
        ErrorCode.NOT_AUTHORISED,
        "Bulk approval/repudiation/payout is prohibited by governance controls",
        status_code=403,
    )


@router.post("/claims/{claim_id}/payments", status_code=201)
def initiate_payment(
    claim_id: str,
    body: PaymentInitiateRequest,
    user: UserContext = Depends(require_roles(Role.FINANCE_APPROVER, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    existing = (
        db.query(Payment)
        .filter(Payment.tenant_id == claim.tenant_id, Payment.idempotency_key == body.idempotency_key)
        .first()
    )
    if existing:
        return {
            "idempotent_replay": True,
            "payment_id": existing.id,
            "status": existing.status,
            "gateway_reference": existing.gateway_reference,
        }

    stl = db.query(Settlement).filter(Settlement.id == body.settlement_id, Settlement.claim_id == claim.id).first()
    if not stl or stl.approval_status != "approved":
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            "Payment cannot be initiated without an approved settlement",
            status_code=409,
        )

    bank_res = IntegrationAdapterRegistry.validate_bank_account(body.account_last4, body.ifsc)
    pg_res = IntegrationAdapterRegistry.execute_payment(
        idempotency_key=body.idempotency_key,
        amount_inr=Decimal(str(stl.net_payable_inr)),
        payee_name=body.payee_name,
        simulate_timeout=body.simulate_timeout,
    )

    pmt = Payment(
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        settlement_id=stl.id,
        idempotency_key=body.idempotency_key,
        payee_type=body.payee_type,
        payee_name=body.payee_name,
        bank_account_masked=mask_bank_account(body.account_last4),
        bank_verified=bank_res["verified"],
        amount_inr=Decimal(str(stl.net_payable_inr)),
        status=pg_res["status"],
        gateway_reference=pg_res["gateway_reference"],
        approved_by_finance_id=user.user_id,
    )
    db.add(pmt)
    db.flush()
    if claim.status == ClaimStatus.APPROVED.value:
        claim.status = validate_transition(claim.status, ClaimStatus.PAYMENT_INITIATED.value).value
    claim.next_expected_action = (
        "Reconcile timed-out payment safely before retry"
        if pmt.status == "timeout_reconcile_pending"
        else "Track repair completion and customer confirmation"
    )
    emit_outbox_event(
        db,
        tenant_id=claim.tenant_id,
        aggregate_id=claim.id,
        event_type="PaymentConfirmed" if pmt.status == "confirmed" else "PaymentRequested",
        payload={"payment_id": pmt.id, "status": pmt.status},
    )
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="PAYMENT_INITIATED",
        object_type="payment",
        object_id=pmt.id,
        after_state={"status": pmt.status, "amount_inr": str(pmt.amount_inr), "ref": pmt.gateway_reference},
    )
    db.commit()
    return {"idempotent_replay": False, "payment_id": pmt.id, "status": pmt.status, "gateway_reference": pmt.gateway_reference}


@router.post("/claims/{claim_id}/payments/{payment_id}/reconcile")
def reconcile_payment(
    claim_id: str,
    payment_id: str,
    user: UserContext = Depends(require_roles(Role.FINANCE_APPROVER, Role.CLAIMS_MANAGER, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    pmt = db.query(Payment).filter(Payment.id == payment_id, Payment.claim_id == claim.id).first()
    if not pmt:
        raise DomainError(ErrorCode.NOT_FOUND, "Payment not found", status_code=404)
    recon = IntegrationAdapterRegistry.reconcile_payment(pmt.gateway_reference or pmt.id)
    pmt.status = recon["status"]
    pmt.gateway_reference = recon["utr"]
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="PAYMENT_RECONCILED_SAFELY",
        object_type="payment",
        object_id=pmt.id,
        after_state={"status": pmt.status, "utr": pmt.gateway_reference},
    )
    db.commit()
    return {"payment_id": pmt.id, "status": pmt.status, "gateway_reference": pmt.gateway_reference}


@router.post("/claims/{claim_id}/repair-status")
def update_repair_milestone(
    claim_id: str,
    body: RepairMilestoneRequest,
    user: UserContext = Depends(require_roles(Role.GARAGE, Role.CLAIMS_HANDLER, Role.SURVEYOR, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    if claim.status in {ClaimStatus.APPROVED.value, ClaimStatus.PAYMENT_INITIATED.value}:
        claim.status = validate_transition(claim.status, ClaimStatus.REPAIR_IN_PROGRESS.value).value
    claim.workflow_state = {**claim.workflow_state, "repair_milestone": body.milestone, "repair_notes": body.notes}
    claim.next_expected_action = "Run QA compliance check & close claim" if body.milestone == "handover_complete" else f"Repair milestone: {body.milestone}"
    emit_outbox_event(
        db, tenant_id=claim.tenant_id, aggregate_id=claim.id, event_type="RepairStarted", payload={"milestone": body.milestone}
    )
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="REPAIR_MILESTONE_UPDATED",
        object_type="claim",
        object_id=claim.id,
        details={"milestone": body.milestone, "notes": body.notes},
    )
    db.commit()
    return {"claim_status": claim.status, "milestone": body.milestone}


@router.post("/claims/{claim_id}/close")
def close_claim(
    claim_id: str,
    user: UserContext = Depends(require_roles(Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    confirmed_pmt = db.query(Payment).filter(Payment.claim_id == claim.id, Payment.status == "confirmed").first()
    open_grievance = db.query(Grievance).filter(Grievance.claim_id == claim.id, Grievance.status != "resolved").first()
    checks = {
        "confirmed_payment_or_declined": confirmed_pmt is not None or claim.status == ClaimStatus.DECLINED_PARTIAL.value,
        "no_open_grievance": open_grievance is None,
    }
    qa_res = AGENT_REGISTRY["qa_compliance"].execute(
        _build_agent_req(claim, user, "qa_compliance", {"checks": checks})
    )
    if qa_res.result["failed_controls"]:
        raise DomainError(
            ErrorCode.STATE_CONFLICT,
            f"Cannot close claim; unmet QA controls: {qa_res.result['failed_controls']}",
            status_code=409,
        )

    claim.status = validate_transition(claim.status, ClaimStatus.CLOSED.value).value
    claim.next_expected_action = "Claim closed; audit & evidence retained"
    emit_outbox_event(db, tenant_id=claim.tenant_id, aggregate_id=claim.id, event_type="ClaimClosed", payload={})
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="CLAIM_CLOSED",
        object_type="claim",
        object_id=claim.id,
    )
    db.commit()
    return {"claim_status": claim.status, "qa_compliance": qa_res.model_dump()}


@router.post("/claims/{claim_id}/reopen")
def reopen_claim(
    claim_id: str,
    user: UserContext = Depends(require_roles(Role.CLAIMS_MANAGER, Role.CLAIMS_HANDLER, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    claim.status = validate_transition(claim.status, ClaimStatus.REOPENED.value).value
    claim.next_expected_action = "Review reopened claim reason and assign owner"
    emit_outbox_event(db, tenant_id=claim.tenant_id, aggregate_id=claim.id, event_type="ClaimReopened", payload={})
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="CLAIM_REOPENED",
        object_type="claim",
        object_id=claim.id,
    )
    db.commit()
    return {"claim_status": claim.status}


@router.post("/claims/{claim_id}/communications", status_code=201)
def send_communication(
    claim_id: str,
    body: CommunicationCreateRequest,
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    agent_res = AGENT_REGISTRY["customer_communication"].execute(
        _build_agent_req(claim, user, "customer_communication", {"draft_message": body.body, "is_adverse": body.is_adverse})
    )
    comm = Communication(
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        channel=body.channel,
        language=body.language,
        template_id=body.template_id,
        subject=body.subject,
        body=body.body,
        requires_human_review=body.is_adverse,
        approved_by=user.user_id if not body.is_adverse else None,
        delivery_status="pending_human_review" if body.is_adverse else "sent_mock",
    )
    db.add(comm)
    emit_outbox_event(
        db, tenant_id=claim.tenant_id, aggregate_id=claim.id, event_type="CustomerNotified", payload={"channel": body.channel}
    )
    db.commit()
    return {"communication_id": comm.id, "delivery_status": comm.delivery_status, "agent_response": agent_res.model_dump()}


@router.post("/claims/{claim_id}/grievances", status_code=201)
def open_grievance(
    claim_id: str,
    body: GrievanceCreateRequest,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    irdai = get_active_rule(db, "IN-IRDAI-MC-2024")["controls"]
    due = datetime.now(timezone.utc) + timedelta(days=int(irdai["grievance_resolution_days"]))
    g = Grievance(
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        category=body.category,
        description=body.description,
        status="acknowledged",
        due_at=due,
    )
    db.add(g)
    db.flush()
    create_stage_sla_timer(db, tenant_id=claim.tenant_id, claim_id=claim.id, stage="grievance_resolution")
    emit_outbox_event(db, tenant_id=claim.tenant_id, aggregate_id=claim.id, event_type="GrievanceOpened", payload={"category": body.category})
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="GRIEVANCE_OPENED",
        object_type="grievance",
        object_id=g.id,
        details={"category": body.category, "due_at": due.isoformat()},
    )
    db.commit()
    return {"grievance_id": g.id, "status": g.status, "due_at": due.isoformat()}


@router.patch("/claims/{claim_id}/grievances/{grievance_id}")
def resolve_grievance(
    claim_id: str,
    grievance_id: str,
    body: GrievanceResolveRequest,
    user: UserContext = Depends(require_roles(Role.CLAIMS_MANAGER, Role.AUDITOR, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    g = db.query(Grievance).filter(Grievance.id == grievance_id, Grievance.claim_id == claim.id).first()
    if not g:
        raise DomainError(ErrorCode.NOT_FOUND, "Grievance not found", status_code=404)
    g.status = body.status
    g.resolution_notes = body.resolution_notes
    g.owner_user_id = user.user_id
    g.resolved_at = datetime.now(timezone.utc)
    complete_stage_sla_timer(db, claim_id=claim.id, stage="grievance_resolution")
    db.commit()
    return {"id": g.id, "status": g.status, "resolution_notes": g.resolution_notes}
