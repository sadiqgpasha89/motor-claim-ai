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
    CompensationRequest,
    CustomerEscalationRequest,
    CustomerPreferencesUpdateRequest,
    DamageReviewRequest,
    EcosystemLogisticsRequest,
    EstimateLineReviewRequest,
    EstimateSubmitRequest,
    FactCorrectionRequest,
    FNOLCreateRequest,
    FraudDispositionRequest,
    GrievanceCreateRequest,
    GrievanceResolveRequest,
    InspectionRescheduleRequest,
    OrchestrateRequest,
    OrchestrationEventRequest,
    OrchestrationRecoverRequest,
    PartsAvailabilityRequest,
    PaymentInitiateRequest,
    ProactiveUpdateRequest,
    ProviderCoordinateRequest,
    RepairCompletionConfirmRequest,
    RepairMilestoneRequest,
    ReworkSubmitRequest,
    RiskContextUpdateRequest,
    SettlementRecommendRequest,
    SingleAgentOrchestrateRequest,
    SurveyorAssignRequest,
    SurveyorFollowupRequest,
    SurveyReportSubmitRequest,
    TaskUpdateRequest,
    WorkflowPauseRequest,
    WorkflowResumeRequest,
)
from packages.config import get_settings
from packages.contracts.agents import AgentInvocationRequest, AgentStatus, ReworkRequest
from packages.contracts.errors import DomainError, ErrorCode
from packages.observability.logging import get_correlation_id
from packages.security.auth import (
    INTERNAL_ROLES,
    SIU_ALLOWED_ROLES,
    TP_LEGAL_ALLOWED_ROLES,
    Role,
    UserContext,
    assert_step_up,
    enforce_claim_abac,
    enforce_siu_access,
    get_current_user,
    require_roles,
)
from packages.security.sanitizer import mask_bank_account, sanitize_untrusted_text, validate_upload_bytes
from services.agent_runtime.actions import ControlledActionExecutor
from services.agent_runtime.contracts import AGENT_CAPABILITY_CONTRACTS, ORCHESTRATION_ORDER
from services.claims.audit import emit_outbox_event, record_audit_event
from services.claims.db import get_db
from services.claims.models import (
    AgentExecutionRecord,
    Approval,
    AuditEvent,
    Claim,
    ClaimParty,
    ClaimTask,
    Communication,
    CompensationLog,
    Customer,
    DamageAssessment,
    DeadLetterRecord,
    DecisionRecord,
    Estimate,
    EstimateLine,
    Evidence,
    ExtractedFact,
    FraudAlert,
    Grievance,
    OrchestrationEventLog,
    OutboxEvent,
    Payment,
    Policy,
    Provider,
    Settlement,
    SLATimer,
    SurveyAssignment,
    Vehicle,
)
from services.claims.state_machine import ClaimStatus, to_canonical_state, validate_transition
from services.claims.supplementary import assert_supplement_allowed, review_supplement
from services.damage_ai.assessor import assess_damage_from_evidence, validate_estimate_lines
from services.document_ai.processor import extract_document_facts
from services.fraud_intelligence.detector import build_entity_relationship_graph, run_fraud_and_anomaly_checks
from services.integrations.adapters import IntegrationAdapterRegistry
from services.observability.traces import resolve_human_intervention
from services.rules_engine.loader import get_active_rule
from services.settlement.authority import validate_approval_authority
from services.settlement.calculator import SettlementCalculator, SettlementLineInput
from services.workflow.customer_experience import (
    build_customer_claim_journey,
    dispatch_proactive_customer_update,
    escalate_to_human_specialist,
    inspect_claim_communication_context,
    update_customer_communication_preferences,
)
from services.workflow.ecosystem import (
    coordinate_claim_ecosystem,
    get_or_create_ecosystem_coordination,
    reschedule_claim_inspection,
    send_surveyor_report_followup,
    serialize_ecosystem_coordination,
    update_claim_logistics,
    update_claim_parts_availability,
    update_repair_milestone_and_confirm,
    verify_surveyor_license,
)
from services.workflow.ev_claims import (
    assert_ev_clearance_for_od_path,
    claim_requires_ev_workflow,
    get_ev_case,
    open_ev_case,
    serialize_ev_summary,
)
from services.workflow.orchestrator import ClaimOrchestrator, record_agent_publication
from services.workflow.risk_engine import (
    assert_fraud_score_never_rejects,
    evaluate_and_persist_risk,
    gather_claim_risk_facts,
    sanitize_risk_payload_for_user,
)
from services.workflow.sla_engine import complete_stage_sla_timer, compute_timer_status, create_stage_sla_timer
from services.workflow.state_specs import WORKFLOW_STATE_SPECS
from services.workflow.tp_liability import (
    assert_not_tp_for_od_path,
    claim_requires_tp_workflow,
    get_tp_case,
    open_tp_case,
    serialize_tp_summary,
)

router = APIRouter(prefix="/api/v1", tags=["claims"])

# Payment statuses that no longer count as money paid or in flight.
UNPAID_PAYMENT_STATUSES = ("failed", "rejected", "reversed", "cancelled")


def _get_claim_for_user(db: Session, claim_id: str, user: UserContext) -> Claim:
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise DomainError(ErrorCode.NOT_FOUND, f"Claim '{claim_id}' not found", status_code=404)
    enforce_claim_abac(user, claim)
    return claim


def _safe_proactive_notify(
    db: Session,
    claim: Claim,
    user: UserContext,
    trigger_event: str,
) -> None:
    """Dispatch state-aware proactive customer update when a lifecycle milestone occurs."""
    customer = db.query(Customer).filter(Customer.id == claim.customer_id).first() if claim.customer_id else None
    if customer is not None and not customer.proactive_updates_enabled:
        return
    dispatch_proactive_customer_update(
        db,
        claim,
        actor=user,
        trigger_event=trigger_event,
        force=False,
    )


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


def _serialize_claim_summary(c: Claim, db: Session, user: UserContext | None = None) -> dict[str, Any]:
    timers = db.query(SLATimer).filter(SLATimer.claim_id == c.id).all()
    sla_flags = [compute_timer_status(t.due_at, t.completed_at, t.paused) for t in timers]
    sla_health = "breached" if "breached" in sla_flags else ("warning" if "warning" in sla_flags else "on_track")
    siu_visible = (user is None) or (user.role in SIU_ALLOWED_ROLES)
    return {
        "id": c.id,
        "claim_number": c.claim_number,
        "claim_type": c.claim_type,
        "peril_cause": c.peril_cause,
        "status": c.status,
        "risk_tier": c.risk_tier or "MEDIUM",
        "operational_path": c.operational_path or "standard",
        "risk_score": int(c.risk_score or 0),
        "fraud_signal_score": str(c.fraud_signal_score or Decimal("0.000")) if siu_visible else None,
        "multiple_vehicles_involved": bool(c.multiple_vehicles_involved),
        "involved_vehicles_count": int(c.involved_vehicles_count or 1),
        "legal_dispute": bool(c.legal_dispute),
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
    risk_tier: Optional[str] = None,
    operational_path: Optional[str] = None,
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
    if risk_tier:
        q = q.filter(Claim.risk_tier == risk_tier.upper())
    if operational_path:
        q = q.filter(Claim.operational_path == operational_path.lower())
    if search:
        like = f"%{search}%"
        q = q.filter(
            (Claim.claim_number.ilike(like))
            | (Claim.vehicle_reg_input.ilike(like))
            | (Claim.policy_number_input.ilike(like))
        )

    claims = q.order_by(Claim.created_at.desc()).all()
    return {"items": [_serialize_claim_summary(c, db, user=user) for c in claims], "total": len(claims)}


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
                "claim": _serialize_claim_summary(existing, db, user=user),
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
    ev_impacted = bool(body.ev_battery_impacted or body.peril_cause == "ev_high_voltage")
    req_survey = (
        body.estimated_loss_inr >= threshold
        or body.peril_cause in {"theft", "fire", "flood", "total_loss", "ev_high_voltage", "tp_bodily_injury"}
        or body.injury_or_fatality
        or ev_impacted
    )

    clean_desc, _, _ = sanitize_untrusted_text(body.incident_description)
    claim_num = f"CLM-DEMO-{datetime.now(timezone.utc).year}-{uuid.uuid4().hex[:6].upper()}"
    missing_docs = [] if body.documents_complete_at_fnol else ["Policy Schedule", "Registration Certificate (RC)", "Driving Licence (DL)", "6-Angle Photos"]
    multi_veh = bool(body.multiple_vehicles_involved or body.involved_vehicles_count > 1)

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
        status=ClaimStatus.SUBMITTED.value,
        severity_band="critical" if body.injury_or_fatality else ("high" if (req_survey or multi_veh) else "medium"),
        queue_name="legal_tp_specialist" if (body.injury_or_fatality or body.claim_type == "third_party" or multi_veh) else "evidence_intake",
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
        ev_battery_impacted=ev_impacted,
        multiple_vehicles_involved=multi_veh,
        involved_vehicles_count=max(1, body.involved_vehicles_count, 2 if multi_veh else 1),
        legal_dispute=body.legal_dispute,
        estimated_loss_inr=body.estimated_loss_inr,
        requires_mandatory_survey=req_survey,
        preferred_language=body.preferred_language,
        preferred_channel=body.preferred_channel,
        whatsapp_consent=body.whatsapp_consent,
        assigned_garage_id=body.preferred_garage_id,
        missing_documents=missing_docs,
        duplicate_candidate_claim_id=dup.id if dup else None,
        next_expected_action=(
            "Baseline documents complete; ready for Risk-Based Triage / Orchestration"
            if not missing_docs
            else "Upload RC, DL, Policy Schedule, and 6 vehicle photos (claim accepted without blocking)"
        ),
        workflow_state={
            "workflow_run_id": f"wf-{uuid.uuid4().hex[:10]}",
            "steps_completed": [],
            "current_state": ClaimStatus.SUBMITTED.value,
            "canonical_state": ClaimStatus.SUBMITTED.value,
            "state_history": [],
            "parallel_waves": [],
        },
    )
    db.add(claim)
    db.flush()

    orch = ClaimOrchestrator(db, user)
    agent_res = orch.initialize_claim_workflow(
        claim,
        fnol_facts={
            "policy_number": claim.policy_number_input,
            "vehicle_reg": claim.vehicle_reg_input,
            "incident_description": clean_desc,
            "incident_location": claim.incident_location,
            "geo_coords": body.geo_coords,
            "location_landmark": body.location_landmark,
            "channel_transcript": body.channel_transcript,
            "intake_channel": claim.intake_channel,
            "preferred_language": claim.preferred_language,
            "peril_cause": claim.peril_cause,
            "vehicle_immobile": claim.vehicle_immobile,
            "airbags_deployed": claim.airbags_deployed,
            "injury_or_fatality": claim.injury_or_fatality,
            "police_involved": claim.police_involved,
            "towing_needed": claim.towing_needed,
            "ev_battery_impacted": claim.ev_battery_impacted,
            "multiple_vehicles_involved": claim.multiple_vehicles_involved,
            "involved_vehicles_count": claim.involved_vehicles_count,
            "legal_dispute": claim.legal_dispute,
            "estimated_loss_inr": str(claim.estimated_loss_inr),
            "missing_documents": missing_docs,
            "auto_send_ack": body.auto_send_ack,
        },
        duplicate_candidate=dup,
    )

    if claim_requires_tp_workflow(claim):
        # Third-Party claims get their own lifecycle, queues and controls (IN-TP-LIABILITY-2026),
        # never the OD estimate -> auto-settlement path.
        open_tp_case(db, claim, user, system_initiated=True)
    elif claim_requires_ev_workflow(claim, vehicle):
        # Electric-vehicle claims get a safety-first lifecycle and an HV hold (IN-EV-CLAIMS-2026);
        # nothing about battery safety is inferred from photographs.
        open_ev_case(db, claim, user, vehicle=vehicle, system_initiated=True)

    ack_comm = Communication(
        tenant_id=user.tenant_id,
        claim_id=claim.id,
        channel="portal",
        language=claim.preferred_language,
        template_id="FNOL_ACKNOWLEDGEMENT",
        subject=f"Claim {claim.claim_number} Registered (DEMO / SYNTHETIC)",
        body=(
            f"Your motor claim {claim.claim_number} for vehicle {claim.vehicle_reg_input} has been registered on {claim.risk_tier} risk ({claim.operational_path}). "
            + (
                "All core documents attached; eligible for straight-through assisted processing."
                if not missing_docs
                else f"Next steps: {', '.join(missing_docs)}."
            )
        ),
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
        "claim": _serialize_claim_summary(claim, db, user=user),
        "risk_assessment": sanitize_risk_payload_for_user(claim.risk_assessment, siu_visible=(user.role in SIU_ALLOWED_ROLES)),
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
    tasks = db.query(ClaimTask).filter(ClaimTask.claim_id == claim.id).order_by(ClaimTask.created_at.desc()).all()
    executions = (
        db.query(AgentExecutionRecord)
        .filter(AgentExecutionRecord.claim_id == claim.id)
        .order_by(AgentExecutionRecord.created_at.desc())
        .all()
    )
    decisions = (
        db.query(DecisionRecord)
        .filter(DecisionRecord.claim_id == claim.id)
        .order_by(DecisionRecord.created_at.desc())
        .all()
    )

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
            "preferred_channel": customer.preferred_channel,
            "consent_whatsapp": customer.consent_whatsapp,
            "consent_sms": customer.consent_sms,
            "consent_email": customer.consent_email,
            "proactive_updates_enabled": customer.proactive_updates_enabled,
        }

    siu_visible = user.role in SIU_ALLOWED_ROLES
    filtered_tasks = [
        {
            "id": t.id,
            "task_type": t.task_type,
            "title": t.title,
            "description": t.description,
            "assigned_role": t.assigned_role,
            "created_by_agent": t.created_by_agent,
            "priority": t.priority,
            "status": t.status,
            "reason_code": t.reason_code,
            "due_at": t.due_at.isoformat() if t.due_at else None,
            "created_at": t.created_at.isoformat(),
        }
        for t in tasks
        if siu_visible or t.task_type != "siu_investigation"
    ]
    filtered_decisions = [
        {
            "id": d.id,
            "agent_name": d.agent_name,
            "stage": d.stage,
            "decision_id": d.decision_id,
            "routing_outcome": d.routing_outcome,
            "reason_codes": d.reason_codes,
            "evidence": d.evidence,
            "policy_rule_refs": d.policy_rule_refs,
            "confidence": str(d.confidence),
            "confidence_band": d.confidence_band,
            "explanation": d.explanation,
            "alternatives_considered": d.alternatives_considered,
            "created_at": d.created_at.isoformat(),
        }
        for d in decisions
        if siu_visible or d.agent_name != "fraud_intelligence"
    ]
    filtered_executions = [
        {
            "id": ex.id,
            "agent_name": ex.agent_name,
            "stage_order": ex.stage_order,
            "attempt_number": ex.attempt_number,
            "status": ex.status,
            "dependencies_satisfied": ex.dependencies_satisfied,
            "depends_on": ex.depends_on,
            "published_result": {} if (ex.agent_name == "fraud_intelligence" and not siu_visible) else ex.published_result,
            "actions_executed": ex.actions_executed,
            "rework_requests": ex.rework_requests,
            "decision": None if (ex.agent_name == "fraud_intelligence" and not siu_visible) else ex.decision,
            "error_message": ex.error_message,
            "duration_ms": ex.duration_ms,
            "created_at": ex.created_at.isoformat(),
        }
        for ex in executions
    ]
    pub_results = dict((claim.workflow_state or {}).get("published_results", {}))
    if not siu_visible and "fraud_intelligence" in pub_results:
        pub_results["fraud_intelligence"] = {"status": pub_results["fraud_intelligence"].get("status", "restricted"), "restricted": True}
    settlement_scenarios = (
        (claim.workflow_state or {})
        .get("published_results", {})
        .get("settlement_recommendation", {})
        .get("data", {})
        .get("scenarios", [])
    )
    orch = ClaimOrchestrator(db, user)
    scheduled_tasks = orch.sync_task_schedule(claim)
    dlq_items = (
        db.query(DeadLetterRecord)
        .filter(DeadLetterRecord.claim_id == claim.id)
        .order_by(DeadLetterRecord.created_at.desc())
        .all()
    )
    compensations = (
        db.query(CompensationLog)
        .filter(CompensationLog.claim_id == claim.id)
        .order_by(CompensationLog.created_at.desc())
        .all()
    )
    orch_events = (
        db.query(OrchestrationEventLog)
        .filter(OrchestrationEventLog.claim_id == claim.id)
        .order_by(OrchestrationEventLog.created_at.desc())
        .all()
    )
    canonical_st = to_canonical_state(claim.status)
    state_contract = WORKFLOW_STATE_SPECS.get(canonical_st)
    safe_risk_assessment = sanitize_risk_payload_for_user(claim.risk_assessment, siu_visible=siu_visible)
    raw_risk_history = list(claim.risk_history or [])
    safe_risk_history = (
        raw_risk_history
        if siu_visible
        else [{**h, "fraud_signal_score": None} for h in raw_risk_history]
    )

    return {
        "claim": {
            **_serialize_claim_summary(claim, db, user=user),
            "canonical_state": canonical_st,
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
            "damage_report": claim.damage_report,
            "risk_assessment": safe_risk_assessment,
            "risk_history": safe_risk_history,
            "workflow_state": claim.workflow_state,
            "duplicate_candidate_claim_id": claim.duplicate_candidate_claim_id,
            "assigned_handler_id": claim.assigned_handler_id,
            "preferred_language": claim.preferred_language,
            "preferred_channel": claim.preferred_channel,
            "whatsapp_consent": bool(claim.whatsapp_consent),
        },
        "risk_assessment": safe_risk_assessment,
        "risk_history": safe_risk_history,
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
                "legal_hold": bool(ev.legal_hold),
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
        "damage_report": claim.damage_report,
        "damage_assessments": [
            {
                "id": d.id,
                "evidence_id": d.evidence_id,
                "component_name": d.component_name,
                "part_code": d.part_code,
                "damage_location": d.damage_location,
                "damage_severity": d.damage_severity,
                "repairability": d.repairability,
                "damage_class": d.damage_class,
                "observation_type": d.observation_type,
                "recommended_action": d.recommended_action,
                "visible_damage": d.visible_damage,
                "possible_hidden_damage": d.possible_hidden_damage,
                "image_quality": d.image_quality,
                "confidence": str(d.confidence),
                "confidence_factors": d.confidence_factors or {},
                "evidence_refs": d.evidence_refs or [],
                "estimated_parts_inr": str(d.estimated_parts_inr),
                "estimated_labour_inr": str(d.estimated_labour_inr),
                "estimated_paint_inr": str(d.estimated_paint_inr),
                "limitations": d.limitations,
                "reviewer_outcome": d.reviewer_outcome,
                "reviewer_notes": d.reviewer_notes,
                "model_version": d.model_version,
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
                "appointment_at": s.appointment_at.isoformat() if s.appointment_at else None,
                "inspection_location": s.inspection_location,
                "reschedule_count": s.reschedule_count,
                "reschedule_reason": s.reschedule_reason,
                "followup_count": s.followup_count,
                "last_followup_at": s.last_followup_at.isoformat() if s.last_followup_at else None,
                "report_due_at": s.report_due_at.isoformat(),
                "report_received_at": s.report_received_at.isoformat() if s.report_received_at else None,
                "delay_reason": s.delay_reason,
                "report_summary": s.report_summary,
                "signed_by_surveyor": s.signed_by_surveyor,
            }
            for s in surveys
        ],
        "ecosystem": serialize_ecosystem_coordination(db, get_or_create_ecosystem_coordination(db, claim)),
        "tp_workflow": (
            serialize_tp_summary(_tp_case)
            if (_tp_case := get_tp_case(db, claim)) and user.role in TP_LEGAL_ALLOWED_ROLES
            else None
        ),
        "tp_workflow_required": claim_requires_tp_workflow(claim),
        "ev_workflow": serialize_ev_summary(_ev_case) if (_ev_case := get_ev_case(db, claim)) else None,
        "ev_workflow_required": claim_requires_ev_workflow(claim, vehicle),
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
                "template_id": cm.template_id,
                "trigger_event": cm.trigger_event,
                "claim_state_snapshot": cm.claim_state_snapshot,
                "subject": cm.subject,
                "body": cm.body,
                "requires_human_review": cm.requires_human_review,
                "delivery_status": cm.delivery_status,
                "consent_verified": bool(cm.consent_verified),
                "whatsapp_message_id": cm.whatsapp_message_id,
                "context_summary": cm.context_summary,
                "created_at": cm.created_at.isoformat(),
            }
            for cm in comms
        ],
        "customer_journey": build_customer_claim_journey(db, claim),
        "customer_experience": inspect_claim_communication_context(db, claim),
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
        "tasks": filtered_tasks,
        "decisions": filtered_decisions,
        "agent_executions": filtered_executions,
        "settlement_scenarios": settlement_scenarios,
        "orchestration_summary": {
            "orchestration_order": ORCHESTRATION_ORDER,
            "current_state": claim.status,
            "canonical_state": canonical_st,
            "triage_track": (claim.workflow_state or {}).get("triage_track"),
            "paused": bool((claim.workflow_state or {}).get("paused", False)),
            "pause_reason": (claim.workflow_state or {}).get("pause_reason"),
            "state_contract": state_contract.model_dump() if state_contract else None,
            "state_history": (claim.workflow_state or {}).get("state_history", []),
            "parallel_waves": (claim.workflow_state or {}).get("parallel_waves", []),
            "stage_statuses": (claim.workflow_state or {}).get("stage_statuses", {}),
            "published_results": pub_results,
            "rework_queue": (claim.workflow_state or {}).get("rework_queue", []),
            "escalations": (claim.workflow_state or {}).get("escalations", []),
            "scheduled_tasks": [
                {
                    "id": ot.id,
                    "task_key": ot.task_key,
                    "title": ot.title,
                    "agent_or_service": ot.agent_or_service,
                    "execution_mode": ot.execution_mode,
                    "parallel_group": ot.parallel_group,
                    "depends_on": ot.depends_on,
                    "condition_expression": ot.condition_expression,
                    "target_state": ot.target_state,
                    "status": ot.status,
                    "attempt_count": ot.attempt_count,
                    "max_retries": ot.max_retries,
                    "backoff_delay_ms": ot.backoff_delay_ms,
                    "retry_history": ot.retry_history,
                    "error_message": ot.error_message,
                }
                for ot in scheduled_tasks
            ],
            "dlq_items": [
                {
                    "id": d.id,
                    "task_key": d.task_key,
                    "agent_or_service": d.agent_or_service,
                    "state_at_failure": d.state_at_failure,
                    "failure_reason": d.failure_reason,
                    "attempt_count": d.attempt_count,
                    "retry_history": d.retry_history,
                    "status": d.status,
                    "created_at": d.created_at.isoformat(),
                }
                for d in dlq_items
            ],
            "compensations": [
                {
                    "id": cp.id,
                    "trigger_reason": cp.trigger_reason,
                    "failed_state": cp.failed_state,
                    "compensating_action": cp.compensating_action,
                    "target_object_type": cp.target_object_type,
                    "target_object_id": cp.target_object_id,
                    "status": cp.status,
                    "created_at": cp.created_at.isoformat(),
                }
                for cp in compensations
            ],
            "events": [
                {
                    "id": ev_row.id,
                    "event_id": ev_row.event_id,
                    "event_type": ev_row.event_type,
                    "processing_status": ev_row.processing_status,
                    "duplicate_hits": ev_row.duplicate_hits,
                    "created_at": ev_row.created_at.isoformat(),
                }
                for ev_row in orch_events
            ],
        },
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
    db.flush()

    doc_label_map = {
        "policy_schedule": "Policy Schedule",
        "registration_certificate": "Registration Certificate (RC)",
        "driving_licence": "Driving Licence (DL)",
        "damage_photo": "6-Angle Photos",
    }
    matched_label = doc_label_map.get(extraction["doc_type"])
    if matched_label and matched_label in (claim.missing_documents or []):
        claim.missing_documents = [d for d in claim.missing_documents if d != matched_label]

    all_evidences = db.query(Evidence).filter(Evidence.claim_id == claim.id).all()
    all_facts = db.query(ExtractedFact).filter(ExtractedFact.claim_id == claim.id).all()
    orch = ClaimOrchestrator(db, user)
    orch.handle_event(
        claim,
        event_id=f"evidence:{ev.id}",
        event_type="EvidenceUploaded",
        source=user.role.value,
        payload={"evidence_id": ev.id, "doc_type": ev.doc_type, "sha256": ev.sha256},
        auto_advance=False,
    )
    agent_res = orch.run_agent(
        claim,
        "document_intelligence",
        enforce_dependencies=False,
        override_facts={
            "policy_number": claim.policy_number_input,
            "vehicle_reg": claim.vehicle_reg_input,
            "evidences": [
                {"id": e.id, "doc_type": e.doc_type, "filename": e.filename, "sha256": e.sha256}
                for e in all_evidences
            ],
            "extracted_facts": [
                {
                    "id": f.id,
                    "evidence_id": f.evidence_id,
                    "field_name": f.field_name,
                    "extracted_value": f.extracted_value,
                    "verified_value": f.verified_value,
                    "confidence": float(f.confidence),
                    "page_number": f.page_number,
                    "bbox": f.bbox,
                    "validation_status": f.validation_status,
                }
                for f in all_facts
            ],
            "prompt_injection_flagged": extraction["prompt_injection_flagged"]
            or any(e.prompt_injection_flagged for e in all_evidences),
        },
        apply_state_progression=True,
    )
    risk_res = evaluate_and_persist_risk(
        db,
        claim,
        trigger_event=f"evidence_uploaded:{ev.doc_type}",
        actor_id=user.user_id,
        actor_role=user.role.value,
        record_decision=True,
        escalate_state=(
            claim.status
            not in {
                ClaimStatus.SUBMITTED.value,
                ClaimStatus.REGISTERED.value,
                ClaimStatus.VALIDATION.value,
                ClaimStatus.EVIDENCE_PENDING.value,
                ClaimStatus.HUMAN_REVIEW.value,
            }
        ),
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
        "legal_hold": bool(ev.legal_hold),
        "malware_scan_status": ev.malware_scan_status,
        "prompt_injection_flagged": ev.prompt_injection_flagged,
        "image_quality": extraction["image_quality"],
        "extracted_facts": created_facts,
        "risk_tier": claim.risk_tier,
        "operational_path": claim.operational_path,
        "risk_assessment": sanitize_risk_payload_for_user(risk_res, siu_visible=(user.role in SIU_ALLOWED_ROLES)),
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

    db.flush()
    evaluate_and_persist_risk(
        db,
        claim,
        trigger_event="fact_verified_or_corrected",
        actor_id=user.user_id,
        actor_role=user.role.value,
        record_decision=True,
        escalate_state=True,
    )

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
    return {
        "id": fact.id,
        "verified_value": fact.verified_value,
        "validation_status": fact.validation_status,
        "risk_tier": claim.risk_tier,
        "operational_path": claim.operational_path,
    }


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

    orch = ClaimOrchestrator(db, user)
    agent_res = orch.run_agent(
        claim,
        "coverage_intelligence",
        enforce_dependencies=False,
        override_facts={
            "peril_cause": claim.peril_cause,
            "claim_type": claim.claim_type,
            "injury_or_fatality": claim.injury_or_fatality,
            "is_ev": vehicle.is_ev if vehicle else claim.ev_battery_impacted,
            "ev_battery_impacted": claim.ev_battery_impacted,
            "period_valid": period_valid,
            "policy_status": policy.status if policy else "not_matched",
            "addons": policy.addons if policy else {},
            "idv_inr": str(policy.idv_inr) if policy else "0.00",
            "compulsory_deductible_inr": str(policy.compulsory_deductible_inr) if policy else "1000.00",
            "voluntary_deductible_inr": str(policy.voluntary_deductible_inr) if policy else "0.00",
            "has_document_mismatch": has_mismatch,
            "missing_documents": claim.missing_documents,
        },
        apply_state_progression=True,
    )
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
    triage_facts = gather_claim_risk_facts(db, claim)
    triage_facts.update({"is_ev": vehicle.is_ev if vehicle else False, "police_involved": claim.police_involved})
    orch = ClaimOrchestrator(db, user)
    agent_res = orch.run_agent(
        claim,
        "claim_triage",
        enforce_dependencies=False,
        override_facts=triage_facts,
        apply_state_progression=True,
    )
    res_data = agent_res.result
    claim.next_expected_action = (
        "Specialist human-led investigation (HIGH RISK)"
        if claim.risk_tier == "HIGH"
        else ("Assign registered surveyor (IRDAI threshold/peril)" if claim.requires_mandatory_survey else "Run AI damage assessment")
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
        details={
            "queue": claim.queue_name,
            "severity": claim.severity_band,
            "mandatory_survey": claim.requires_mandatory_survey,
            "risk_tier": claim.risk_tier,
            "operational_path": claim.operational_path,
        },
    )
    db.commit()
    return {
        "claim_status": claim.status,
        "risk_tier": claim.risk_tier,
        "operational_path": claim.operational_path,
        "risk_assessment": sanitize_risk_payload_for_user(claim.risk_assessment, siu_visible=(user.role in SIU_ALLOWED_ROLES)),
        "triage": claim.triage_summary,
    }


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
        {
            "id": im.id,
            "filename": im.filename,
            "image_angle": im.image_angle,
            "image_quality_status": im.image_quality_status,
            "sha256": im.sha256,
            "ocr_text": im.ocr_text,
        }
        for im in images
    ]
    veh_info = (
        {
            "make": vehicle.make,
            "model": vehicle.model,
            "variant": vehicle.cc_class.replace("_", " ").title(),
            "year": vehicle.year,
            "registration_number": vehicle.registration_number,
            "is_ev": vehicle.is_ev,
            "fuel_type": vehicle.fuel_type,
        }
        if vehicle
        else {"registration_number": claim.vehicle_reg_input, "is_ev": claim.ev_battery_impacted}
    )
    payload = assess_damage_from_evidence(
        claim_description=claim.incident_description,
        is_ev=vehicle.is_ev if vehicle else claim.ev_battery_impacted,
        ev_battery_impacted=claim.ev_battery_impacted,
        image_records=img_records,
        vehicle_info=veh_info,
    )
    orch = ClaimOrchestrator(db, user)
    agent_res = orch.run_agent(
        claim,
        "damage_assessment",
        enforce_dependencies=False,
        override_facts={"assessment_payload": payload},
        apply_state_progression=True,
    )
    saved = list(payload["observations"])

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
        details={
            "observations": len(saved),
            "missing_angles": payload["missing_angles"],
            "route_to_human_assessor": payload["human_assessor_routing"]["route_to_human_assessor"],
        },
    )
    if payload.get("recapture_required_files") or payload.get("poor_quality_files"):
        _safe_proactive_notify(db, claim, user, "photos_insufficient")
    db.commit()
    return {"observations": saved, "damage_report": agent_res.result, "agent_response": agent_res.model_dump()}


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
    db.flush()
    evaluate_and_persist_risk(
        db,
        claim,
        trigger_event="damage_observation_reviewed",
        actor_id=user.user_id,
        actor_role=user.role.value,
        record_decision=True,
        escalate_state=True,
    )
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
    return {"id": da.id, "reviewer_outcome": da.reviewer_outcome, "risk_tier": claim.risk_tier}


@router.post("/claims/{claim_id}/estimates", status_code=201)
def submit_and_validate_estimate(
    claim_id: str,
    body: EstimateSubmitRequest,
    user: UserContext = Depends(require_roles(Role.GARAGE, Role.CLAIMS_HANDLER, Role.SURVEYOR, Role.CLAIMS_MANAGER, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    if body.is_supplement:
        assert_supplement_allowed(claim)
    dmg_rows = db.query(DamageAssessment).filter(DamageAssessment.claim_id == claim.id).all()
    visible_parts = {d.part_code for d in dmg_rows if d.part_code}
    dmg_obs = [
        {"part_code": d.part_code, "recommended_action": d.recommended_action, "repair_vs_replace_rationale": d.limitations}
        for d in dmg_rows
    ]
    raw_lines = [ln.model_dump() for ln in body.lines]
    val = validate_estimate_lines(
        raw_lines,
        visible_part_codes=visible_parts or None,
        damage_observations=dmg_obs or None,
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
    db.flush()

    claim.estimated_loss_inr = est.total_claimed_inr
    orch = ClaimOrchestrator(db, user)
    orch.handle_event(
        claim,
        event_id=f"estimate:{est.id}",
        event_type="EstimateSubmitted",
        source=user.role.value,
        payload={"estimate_id": est.id, "claimed": str(est.total_claimed_inr)},
        auto_advance=False,
    )
    agent_res = orch.run_agent(
        claim,
        "estimate_validation",
        enforce_dependencies=False,
        override_facts={"estimate_validation": val},
        apply_state_progression=True,
    )
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
    supplementary_review = review_supplement(db, claim, est, user) if est.is_supplement else None
    if not val["anomalies"]:
        _safe_proactive_notify(db, claim, user, "estimate_approved")
    db.commit()
    return {
        "estimate_id": est.id,
        "validation": val,
        "supplementary_review": supplementary_review,
        "risk_tier": claim.risk_tier,
        "operational_path": claim.operational_path,
        "risk_assessment": sanitize_risk_payload_for_user(claim.risk_assessment, siu_visible=(user.role in SIU_ALLOWED_ROLES)),
        "agent_response": agent_res.model_dump(),
    }


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

    db.flush()
    evaluate_and_persist_risk(
        db,
        claim,
        trigger_event="estimate_line_reviewed",
        actor_id=user.user_id,
        actor_role=user.role.value,
        record_decision=True,
        escalate_state=True,
    )

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
    return {
        "id": line.id,
        "reviewer_status": line.reviewer_status,
        "approved_amount_inr": str(line.approved_amount_inr),
        "risk_tier": claim.risk_tier,
    }


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
    lic_check = verify_surveyor_license(surveyor)
    if not lic_check["verified"]:
        raise DomainError(
            ErrorCode.VALIDATION_ERROR,
            f"Cannot assign an unverified/expired surveyor ({lic_check['reason']})",
            status_code=400,
        )

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
    orch = ClaimOrchestrator(db, user)
    orch._safe_transition(
        claim,
        ClaimStatus.SURVEY_REQUIRED.value,
        reason=f"Verified surveyor {surveyor.name} assigned",
        trigger_event="SurveyorAssigned",
        next_expected_action=f"Surveyor {surveyor.name} to inspect vehicle & submit report by {due_at.date()}",
    )

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
    prov_res = AGENT_REGISTRY["provider_coordination"].execute(
        _build_agent_req(
            claim,
            user,
            "provider_coordination",
            {
                "requires_mandatory_survey": claim.requires_mandatory_survey,
                "ev_battery_impacted": claim.ev_battery_impacted,
                "recommended_surveyor": {"id": surveyor.id, "name": surveyor.name, "licence": surveyor.licence_or_contract_id},
                "recommended_provider": {"id": surveyor.id, "name": surveyor.name},
                "preferred_garage_id": claim.assigned_garage_id,
            },
        )
    )
    record_agent_publication(db, claim=claim, agent_name="provider_coordination", response=prov_res)
    coord = get_or_create_ecosystem_coordination(db, claim)
    coord.surveyor_id = surveyor.id
    coord.surveyor_license_verified = True
    coord.surveyor_license_checked_at = datetime.now(timezone.utc)
    coord.surveyor_selection_explanation = f"Assigned verified IIISLA surveyor {surveyor.name} (Licence {surveyor.licence_or_contract_id}) in {surveyor.city}."
    if claim.assigned_garage_id:
        coord.garage_id = claim.assigned_garage_id
        coord.customer_preferred_garage_id = coord.customer_preferred_garage_id or claim.assigned_garage_id
    coord.inspection_status = "scheduled"
    coord.inspection_scheduled_at = sa.appointment_at or (datetime.now(timezone.utc) + timedelta(hours=12))
    _safe_proactive_notify(db, claim, user, "survey_scheduled")
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
    orch = ClaimOrchestrator(db, user)
    if claim.status in {ClaimStatus.SURVEY_ASSIGNED.value, ClaimStatus.SURVEY_REQUIRED.value}:
        orch._safe_transition(
            claim,
            ClaimStatus.ESTIMATE_VALIDATION.value,
            reason="Signed surveyor report received",
            trigger_event="SurveyReportReceived",
            next_expected_action="Generate deterministic settlement recommendation",
        )
    else:
        claim.next_expected_action = "Generate deterministic settlement recommendation"

    db.flush()
    evaluate_and_persist_risk(
        db,
        claim,
        trigger_event="survey_report_submitted",
        actor_id=user.user_id,
        actor_role=user.role.value,
        record_decision=True,
        escalate_state=True,
    )

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
    return {"survey_id": sa.id, "status": sa.status, "report_summary": sa.report_summary, "risk_tier": claim.risk_tier}


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

    db.flush()
    entity_graph = build_entity_relationship_graph(db, claim)
    agent_res = AGENT_REGISTRY["fraud_intelligence"].execute(
        _build_agent_req(
            claim,
            user,
            "fraud_intelligence",
            {
                "indicators": [{**i, "confidence": str(i["confidence"])} for i in indicators],
                "entity_graph": entity_graph,
            },
        ),
        action_executor=ControlledActionExecutor(db, claim, user),
    )
    record_agent_publication(db, claim=claim, agent_name="fraud_intelligence", response=agent_res)
    risk_res = evaluate_and_persist_risk(
        db,
        claim,
        trigger_event="fraud_checks_evaluated",
        actor_id=user.user_id,
        actor_role=user.role.value,
        record_decision=True,
        escalate_state=(claim.status != ClaimStatus.CLOSED.value),
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
        details={"new_alerts": created, "fraud_signal_score": risk_res["fraud_signal_score"], "risk_tier": claim.risk_tier},
    )
    db.commit()
    return {
        "new_alerts": created,
        "risk_tier": claim.risk_tier,
        "operational_path": claim.operational_path,
        "fraud_signal_score": risk_res["fraud_signal_score"] if user.role in SIU_ALLOWED_ROLES else None,
        "fraud_score_can_reject": False,
        "agent_response": agent_res.model_dump(),
    }


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

    db.flush()
    evaluate_and_persist_risk(
        db,
        claim,
        trigger_event=f"fraud_alert_dispositioned:{body.status}",
        actor_id=user.user_id,
        actor_role=user.role.value,
        record_decision=True,
        escalate_state=True,
    )

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
    return {
        "id": alert.id,
        "status": alert.status,
        "disposition_reason": alert.disposition_reason,
        "risk_tier": claim.risk_tier,
        "operational_path": claim.operational_path,
    }


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
    assert_not_tp_for_od_path(claim, operation="OD settlement recommendation")
    assert_ev_clearance_for_od_path(db, claim, operation="OD settlement recommendation")
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

    scenarios_res = SettlementCalculator().calculate_scenarios(
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
    calc = scenarios_res["primary"]

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

    open_alerts = (
        db.query(FraudAlert)
        .filter(FraudAlert.claim_id == claim.id, FraudAlert.status.in_(["new", "assigned", "investigating"]))
        .count()
    )
    active_conditions: list[str] = []
    if open_alerts > 0:
        active_conditions.append("fraud_alert_open")
    if claim.injury_or_fatality:
        active_conditions.append("tp_injury")
    if claim.ev_battery_impacted:
        active_conditions.append("ev_battery")
    if calc.is_total_loss:
        active_conditions.append("total_loss")
    if (claim.risk_tier or "MEDIUM") == "HIGH":
        active_conditions.append("high_risk_complex")

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
    db.flush()

    orch = ClaimOrchestrator(db, user)
    agent_res = orch.run_agent(
        claim,
        "settlement_recommendation",
        enforce_dependencies=False,
        override_facts={
            "settlement_id": stl.id,
            "active_conditions": active_conditions,
            "risk_tier": claim.risk_tier or "MEDIUM",
            "allow_fast_track_auto_approve": False,
            "scenarios": scenarios_res["scenarios"],
            "calculation": {
                "gross": str(calc.gross_assessed_inr),
                "depreciation": str(calc.depreciation_deduction_inr),
                "addon_waiver": str(calc.addon_waiver_inr),
                "compulsory_excess": str(calc.compulsory_excess_inr),
                "salvage": str(calc.salvage_deduction_inr),
                "net": str(calc.net_payable_inr),
                "is_total_loss": calc.is_total_loss,
                "ctl_threshold_inr": str(calc.ctl_threshold_inr),
                "idv_inr": str(calc.idv_inr),
            },
        },
        apply_state_progression=True,
    )
    claim.next_expected_action = f"Authorised checker approval required for INR {calc.net_payable_inr}"

    complete_stage_sla_timer(db, claim_id=claim.id, stage="claim_decision")
    _safe_proactive_notify(db, claim, user, "settlement_awaiting_approval")
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
    return {
        "settlement_id": stl.id,
        "approval_id": approval.id,
        "net_payable_inr": str(calc.net_payable_inr),
        "scenarios": scenarios_res["scenarios"],
        "agent_response": agent_res.model_dump(),
    }


@router.post("/claims/{claim_id}/approvals")
def decide_approval(
    claim_id: str,
    body: ApprovalDecisionRequest,
    user: UserContext = Depends(require_roles(Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.LEGAL_TP, Role.FINANCE_APPROVER, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    assert_step_up(user, "approval_decision")
    claim = _get_claim_for_user(db, claim_id, user)
    assert_not_tp_for_od_path(claim, operation="OD settlement approval")
    assert_ev_clearance_for_od_path(db, claim, operation="OD settlement approval")
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
    if (claim.risk_tier or "MEDIUM") == "HIGH":
        conditions.append("high_risk_complex")

    doa_ver = validate_approval_authority(
        db,
        user=user,
        claim_type=claim.claim_type,
        amount_inr=Decimal(str(approval.amount_inr)),
        active_conditions=conditions,
        maker_user_id=approval.maker_user_id,
        decision=body.decision,
        rationale=body.rationale,
        fraud_signal_score=claim.fraud_signal_score,
    )

    approval.checker_user_id = user.user_id
    approval.decision = body.decision
    approval.rationale = body.rationale
    approval.authority_rule_version = doa_ver
    approval.decided_at = datetime.now(timezone.utc)

    stl = db.query(Settlement).filter(Settlement.id == approval.settlement_id).first() if approval.settlement_id else None
    orch = ClaimOrchestrator(db, user)
    gate_task = orch._get_or_create_task(claim, "human_approval_gate")
    if body.decision == "approved":
        if stl:
            stl.approval_status = "approved"
        db.flush()
        orch.transition_state(
            claim,
            ClaimStatus.APPROVED.value,
            reason=f"Independent Checker ({user.email}) approved INR {approval.amount_inr}",
            trigger_event="ApprovalGranted",
            next_expected_action="Finance Approver to verify payee bank & initiate payment",
        )
        gate_task.status = "completed"
        gate_task.completed_at = datetime.now(timezone.utc)
        event_type = "ApprovalGranted"
    else:
        if stl:
            stl.approval_status = "rejected"
        db.flush()
        orch.transition_state(
            claim,
            ClaimStatus.HUMAN_REVIEW.value,
            reason=f"Returned by Checker: {body.rationale}",
            trigger_event="ApprovalRejected",
            next_expected_action=f"Returned by checker: {body.rationale}",
        )
        gate_task.status = "waiting_human"
        event_type = "ApprovalRejected"

    resolve_human_intervention(
        db, claim_id=claim.id, actor_id=user.user_id, actor_role=user.role.value, decision=f"approval_{body.decision}"
    )
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
    assert_step_up(user, "payment_initiation")
    claim = _get_claim_for_user(db, claim_id, user)
    assert_not_tp_for_od_path(claim, operation="OD payment initiation")
    assert_ev_clearance_for_od_path(db, claim, operation="OD payment initiation")
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
    # Lock the claim row so two concurrent payouts cannot both read the same paid total.
    db.query(Claim).filter(Claim.id == claim.id).with_for_update().first()
    already_paid = sum(
        (
            Decimal(str(p.amount_inr))
            for p in db.query(Payment).filter(
                Payment.claim_id == claim.id, Payment.status.notin_(UNPAID_PAYMENT_STATUSES)
            )
        ),
        Decimal("0.00"),
    )
    payable_inr = Decimal(str(stl.net_payable_inr)) - already_paid
    if payable_inr <= Decimal("0.00"):
        raise DomainError(
            ErrorCode.STATE_CONFLICT,
            f"Nothing is payable. INR {already_paid:.2f} was already paid or is in flight against this claim.",
            status_code=409,
        )

    bank_res = IntegrationAdapterRegistry.validate_bank_account(body.account_last4, body.ifsc)
    pg_res = IntegrationAdapterRegistry.execute_payment(
        idempotency_key=body.idempotency_key,
        amount_inr=payable_inr,
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
        amount_inr=payable_inr,
        status=pg_res["status"],
        gateway_reference=pg_res["gateway_reference"],
        approved_by_finance_id=user.user_id,
    )
    db.add(pmt)
    db.flush()
    orch = ClaimOrchestrator(db, user)
    if claim.status == ClaimStatus.APPROVED.value:
        orch.transition_state(
            claim,
            ClaimStatus.PAYMENT_PENDING.value,
            reason="Finance initiated idempotent payout instruction",
            trigger_event="PaymentInitiated",
            next_expected_action=(
                "Reconcile timed-out payment safely before retry"
                if pmt.status == "timeout_reconcile_pending"
                else "Track payment reconciliation and QA closure"
            ),
        )
    else:
        claim.next_expected_action = (
            "Reconcile timed-out payment safely before retry"
            if pmt.status == "timeout_reconcile_pending"
            else "Track repair completion and customer confirmation"
        )
    pmt_task = orch._get_or_create_task(claim, "payment_execution")
    pmt_task.status = "completed" if pmt.status == "confirmed" else "waiting_human"
    if pmt.status == "confirmed":
        pmt_task.completed_at = datetime.now(timezone.utc)
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
    if pmt.status == "confirmed":
        _safe_proactive_notify(db, claim, user, "payment_processed")
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
    db.flush()
    orch = ClaimOrchestrator(db, user)
    orch._safe_transition(
        claim,
        ClaimStatus.PAYMENT_RECONCILIATION.value,
        reason=f"Gateway UTR {pmt.gateway_reference} reconciled safely",
        trigger_event="PaymentReconciled",
        next_expected_action="Run QA compliance check & close claim",
    )
    recon_task = orch._get_or_create_task(claim, "payment_reconciliation")
    recon_task.status = "completed"
    recon_task.completed_at = datetime.now(timezone.utc)
    pmt_task = orch._get_or_create_task(claim, "payment_execution")
    pmt_task.status = "completed"
    pmt_task.completed_at = pmt_task.completed_at or datetime.now(timezone.utc)
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
    _safe_proactive_notify(db, claim, user, "payment_processed")
    db.commit()
    return {"payment_id": pmt.id, "status": pmt.status, "gateway_reference": pmt.gateway_reference}


@router.post("/claims/{claim_id}/repair-status")
def update_repair_milestone(
    claim_id: str,
    body: RepairMilestoneRequest,
    user: UserContext = Depends(require_roles(Role.GARAGE, Role.CLAIMS_HANDLER, Role.SURVEYOR, Role.CLAIMS_MANAGER, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    if claim.status in {ClaimStatus.APPROVED.value, ClaimStatus.PAYMENT_INITIATED.value}:
        claim.status = validate_transition(claim.status, ClaimStatus.REPAIR_IN_PROGRESS.value).value
    claim.workflow_state = {**claim.workflow_state, "repair_milestone": body.milestone, "repair_notes": body.notes}
    is_done = body.confirm_completion or body.milestone in {"repair_completed", "handover_complete", "handover_confirmed"}
    claim.next_expected_action = (
        "Run QA compliance check & close claim" if is_done else f"Repair milestone: {body.milestone}"
    )
    coord = update_repair_milestone_and_confirm(
        db,
        claim,
        user=user,
        milestone=body.milestone,
        notes=body.notes,
        confirm_completion=is_done,
    )
    emit_outbox_event(
        db, tenant_id=claim.tenant_id, aggregate_id=claim.id, event_type="RepairStarted", payload={"milestone": body.milestone, "confirmed": coord.repair_completion_confirmed}
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
        details={"milestone": body.milestone, "notes": body.notes, "completion_confirmed": coord.repair_completion_confirmed},
    )
    _safe_proactive_notify(db, claim, user, "repair_begins")
    db.commit()
    return {
        "claim_status": claim.status,
        "milestone": body.milestone,
        "repair_completion_confirmed": coord.repair_completion_confirmed,
        "ecosystem": serialize_ecosystem_coordination(db, coord),
    }


@router.post("/claims/{claim_id}/close")
def close_claim(
    claim_id: str,
    user: UserContext = Depends(require_roles(Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    assert_not_tp_for_od_path(claim, operation="OD claim closure")
    assert_ev_clearance_for_od_path(db, claim, operation="OD claim closure", require_closed=True)
    confirmed_pmt = db.query(Payment).filter(Payment.claim_id == claim.id, Payment.status == "confirmed").first()
    open_grievance = db.query(Grievance).filter(Grievance.claim_id == claim.id, Grievance.status != "resolved").first()
    unresolved_mismatch = (
        db.query(ExtractedFact)
        .filter(ExtractedFact.claim_id == claim.id, ExtractedFact.validation_status == "mismatch")
        .first()
    )
    signed_survey = (
        db.query(SurveyAssignment)
        .filter(SurveyAssignment.claim_id == claim.id, SurveyAssignment.signed_by_surveyor.is_(True))
        .first()
    )
    approved_app = db.query(Approval).filter(Approval.claim_id == claim.id, Approval.decision == "approved").first()
    checks = {
        "no_unresolved_doc_mismatch": unresolved_mismatch is None,
        "coverage_checked": claim.coverage_factsheet is not None,
        "survey_report_signed": (not claim.requires_mandatory_survey) or (signed_survey is not None),
        "maker_checker_approved": (approved_app is not None) or claim.status == ClaimStatus.DECLINED_PARTIAL.value,
        "confirmed_payment_or_declined": confirmed_pmt is not None or claim.status == ClaimStatus.DECLINED_PARTIAL.value,
        "no_open_grievance": open_grievance is None,
    }
    orch = ClaimOrchestrator(db, user)
    qa_res = orch.run_agent(
        claim,
        "qa_compliance",
        enforce_dependencies=False,
        override_facts={"checks": checks},
        apply_state_progression=False,
    )
    if qa_res.result["failed_controls"]:
        db.commit()
        raise DomainError(
            ErrorCode.STATE_CONFLICT,
            f"Cannot close claim; unmet QA controls: {qa_res.result['failed_controls']}",
            status_code=409,
        )

    orch.transition_state(
        claim,
        ClaimStatus.CLOSED.value,
        reason="All QA compliance controls passed; payment reconciled",
        trigger_event="ClaimClosed",
        next_expected_action="Claim closed; audit & evidence retained",
    )
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
    _safe_proactive_notify(db, claim, user, "claim_closed")
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
        _build_agent_req(
            claim,
            user,
            "customer_communication",
            {
                "claim_number": claim.claim_number,
                "vehicle_reg": claim.vehicle_reg_input,
                "claim_status": claim.status,
                "next_expected_action": claim.next_expected_action,
                "missing_documents": claim.missing_documents,
                "channel": body.channel,
                "language": body.language,
                "message_type": body.message_type,
                "subject": body.subject,
                "draft_message": body.body,
                "is_adverse": body.is_adverse,
            },
        )
    )
    record_agent_publication(db, claim=claim, agent_name="customer_communication", response=agent_res)
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
    evaluate_and_persist_risk(
        db,
        claim,
        trigger_event=f"grievance_opened:{body.category}",
        actor_id=user.user_id,
        actor_role=user.role.value,
        record_decision=True,
        escalate_state=True,
    )
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
    db.flush()
    evaluate_and_persist_risk(
        db,
        claim,
        trigger_event="grievance_resolved",
        actor_id=user.user_id,
        actor_role=user.role.value,
        record_decision=True,
        escalate_state=True,
    )
    db.commit()
    return {"id": g.id, "status": g.status, "resolution_notes": g.resolution_notes, "risk_tier": claim.risk_tier}


@router.get("/claims/{claim_id}/orchestration")
def get_claim_orchestration(
    claim_id: str,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    siu_visible = user.role in SIU_ALLOWED_ROLES
    executions = (
        db.query(AgentExecutionRecord)
        .filter(AgentExecutionRecord.claim_id == claim.id)
        .order_by(AgentExecutionRecord.created_at.asc())
        .all()
    )
    tasks = db.query(ClaimTask).filter(ClaimTask.claim_id == claim.id).order_by(ClaimTask.created_at.desc()).all()
    decisions = (
        db.query(DecisionRecord)
        .filter(DecisionRecord.claim_id == claim.id)
        .order_by(DecisionRecord.created_at.desc())
        .all()
    )
    orch = ClaimOrchestrator(db, user)
    dag = []
    for order_idx, name in enumerate(ORCHESTRATION_ORDER, start=1):
        spec = AGENT_CAPABILITY_CONTRACTS[name]
        deps_ok, missing = orch.check_dependencies(claim, name)
        stage_status = (claim.workflow_state or {}).get("stage_statuses", {}).get(name, "pending")
        dag.append(
            {
                "order": order_idx,
                "agent_name": name,
                "display_name": spec.display_name,
                "stage": spec.stage,
                "depends_on": spec.depends_on,
                "dependencies_satisfied": deps_ok,
                "missing_dependencies": missing,
                "current_status": stage_status,
                "can_request_rework_from": spec.can_request_rework_from,
            }
        )

    pub_results = dict((claim.workflow_state or {}).get("published_results", {}))
    if not siu_visible and "fraud_intelligence" in pub_results:
        pub_results["fraud_intelligence"] = {"status": pub_results["fraud_intelligence"].get("status", "restricted"), "restricted": True}

    scheduled_tasks = orch.sync_task_schedule(claim)
    dlq_items = (
        db.query(DeadLetterRecord)
        .filter(DeadLetterRecord.claim_id == claim.id)
        .order_by(DeadLetterRecord.created_at.desc())
        .all()
    )
    compensations = (
        db.query(CompensationLog)
        .filter(CompensationLog.claim_id == claim.id)
        .order_by(CompensationLog.created_at.desc())
        .all()
    )
    events = (
        db.query(OrchestrationEventLog)
        .filter(OrchestrationEventLog.claim_id == claim.id)
        .order_by(OrchestrationEventLog.created_at.desc())
        .all()
    )
    timers = db.query(SLATimer).filter(SLATimer.claim_id == claim.id).all()
    canonical_st = to_canonical_state(claim.status)
    state_contract = WORKFLOW_STATE_SPECS.get(canonical_st)

    return {
        "claim_id": claim.id,
        "claim_status": claim.status,
        "canonical_state": canonical_st,
        "triage_track": (claim.workflow_state or {}).get("triage_track"),
        "paused": bool((claim.workflow_state or {}).get("paused", False)),
        "pause_reason": (claim.workflow_state or {}).get("pause_reason"),
        "state_contract": state_contract.model_dump() if state_contract else None,
        "state_history": (claim.workflow_state or {}).get("state_history", []),
        "parallel_waves": (claim.workflow_state or {}).get("parallel_waves", []),
        "scheduled_tasks": [
            {
                "id": ot.id,
                "task_key": ot.task_key,
                "title": ot.title,
                "agent_or_service": ot.agent_or_service,
                "execution_mode": ot.execution_mode,
                "parallel_group": ot.parallel_group,
                "depends_on": ot.depends_on,
                "condition_expression": ot.condition_expression,
                "target_state": ot.target_state,
                "status": ot.status,
                "attempt_count": ot.attempt_count,
                "max_retries": ot.max_retries,
                "backoff_delay_ms": ot.backoff_delay_ms,
                "retry_history": ot.retry_history,
                "error_message": ot.error_message,
            }
            for ot in scheduled_tasks
        ],
        "dlq_items": [
            {
                "id": d.id,
                "task_key": d.task_key,
                "agent_or_service": d.agent_or_service,
                "state_at_failure": d.state_at_failure,
                "error_code": d.error_code,
                "failure_reason": d.failure_reason,
                "attempt_count": d.attempt_count,
                "retry_history": d.retry_history,
                "status": d.status,
                "created_at": d.created_at.isoformat(),
            }
            for d in dlq_items
        ],
        "compensations": [
            {
                "id": cp.id,
                "trigger_reason": cp.trigger_reason,
                "failed_state": cp.failed_state,
                "compensating_action": cp.compensating_action,
                "target_object_type": cp.target_object_type,
                "target_object_id": cp.target_object_id,
                "status": cp.status,
                "created_at": cp.created_at.isoformat(),
            }
            for cp in compensations
        ],
        "events": [
            {
                "id": ev_row.id,
                "event_id": ev_row.event_id,
                "event_type": ev_row.event_type,
                "source": ev_row.source,
                "processing_status": ev_row.processing_status,
                "resulting_state": ev_row.resulting_state,
                "duplicate_hits": ev_row.duplicate_hits,
                "created_at": ev_row.created_at.isoformat(),
            }
            for ev_row in events
        ],
        "sla_timers": [
            {
                "id": t.id,
                "stage": t.stage,
                "status": compute_timer_status(t.due_at, t.completed_at, t.paused),
                "paused": t.paused,
                "due_at": t.due_at.isoformat(),
                "owner_role": t.owner_role,
                "daily_penalty_inr": str(t.daily_penalty_inr),
            }
            for t in timers
        ],
        "dag": dag,
        "published_results": pub_results,
        "rework_queue": (claim.workflow_state or {}).get("rework_queue", []),
        "escalations": (claim.workflow_state or {}).get("escalations", []),
        "executions": [
            {
                "id": ex.id,
                "agent_name": ex.agent_name,
                "attempt_number": ex.attempt_number,
                "status": ex.status,
                "dependencies_satisfied": ex.dependencies_satisfied,
                "actions_executed": ex.actions_executed,
                "rework_requests": ex.rework_requests,
                "decision": None if (ex.agent_name == "fraud_intelligence" and not siu_visible) else ex.decision,
                "error_message": ex.error_message,
                "duration_ms": ex.duration_ms,
                "created_at": ex.created_at.isoformat(),
            }
            for ex in executions
        ],
        "tasks": [
            {
                "id": t.id,
                "task_type": t.task_type,
                "title": t.title,
                "assigned_role": t.assigned_role,
                "created_by_agent": t.created_by_agent,
                "priority": t.priority,
                "status": t.status,
                "reason_code": t.reason_code,
            }
            for t in tasks
            if siu_visible or t.task_type != "siu_investigation"
        ],
        "decisions": [
            {
                "id": d.id,
                "agent_name": d.agent_name,
                "decision_id": d.decision_id,
                "routing_outcome": d.routing_outcome,
                "reason_codes": d.reason_codes,
                "evidence": d.evidence,
                "policy_rule_refs": d.policy_rule_refs,
                "confidence": str(d.confidence),
                "confidence_band": d.confidence_band,
                "explanation": d.explanation,
                "created_at": d.created_at.isoformat(),
            }
            for d in decisions
            if siu_visible or d.agent_name != "fraud_intelligence"
        ],
    }


@router.post("/claims/{claim_id}/orchestrate")
def run_claim_orchestration(
    claim_id: str,
    body: OrchestrateRequest = OrchestrateRequest(),
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    orch = ClaimOrchestrator(db, user)
    summary = orch.orchestrate_claim(
        claim,
        stop_on_human_gate=body.stop_on_human_gate,
        max_steps=body.max_steps,
        simulate_timeout_agent=body.simulate_timeout_agent,
        simulate_transient_timeout_once_agent=body.simulate_transient_timeout_once_agent,
    )
    db.commit()
    return summary


@router.post("/claims/{claim_id}/orchestration/events")
def dispatch_orchestration_event(
    claim_id: str,
    body: OrchestrationEventRequest,
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES, Role.POLICYHOLDER, Role.GARAGE, Role.SURVEYOR)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    orch = ClaimOrchestrator(db, user)
    res = orch.handle_event(
        claim,
        event_id=body.event_id,
        event_type=body.event_type,
        source=body.source,
        payload=body.payload,
        auto_advance=body.auto_advance,
    )
    db.commit()
    return res


@router.post("/claims/{claim_id}/orchestration/pause")
def pause_claim_workflow(
    claim_id: str,
    body: WorkflowPauseRequest = WorkflowPauseRequest(),
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    orch = ClaimOrchestrator(db, user)
    res = orch.pause_workflow(claim, reason=body.reason)
    db.commit()
    return res


@router.post("/claims/{claim_id}/orchestration/resume")
def resume_claim_workflow(
    claim_id: str,
    body: WorkflowResumeRequest = WorkflowResumeRequest(),
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    orch = ClaimOrchestrator(db, user)
    res = orch.resume_workflow(
        claim,
        resolution_notes=body.resolution_notes,
        run_ready_stages=body.run_ready_stages,
    )
    db.commit()
    return res


@router.post("/claims/{claim_id}/orchestration/compensate")
def compensate_claim_workflow(
    claim_id: str,
    body: CompensationRequest = CompensationRequest(),
    user: UserContext = Depends(require_roles(Role.CLAIMS_MANAGER, Role.ADMIN, Role.CLAIMS_HANDLER)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    orch = ClaimOrchestrator(db, user)
    res = orch.run_compensation(
        claim,
        trigger_reason=body.trigger_reason,
        target_state=body.target_state,
    )
    db.commit()
    return res


@router.post("/claims/{claim_id}/orchestrate/{agent_name}")
def run_single_orchestrated_agent(
    claim_id: str,
    agent_name: str,
    body: SingleAgentOrchestrateRequest = SingleAgentOrchestrateRequest(),
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    orch = ClaimOrchestrator(db, user)
    resp = orch.run_agent(
        claim,
        agent_name,
        enforce_dependencies=body.enforce_dependencies,
        simulate_timeout=body.simulate_timeout,
        simulate_transient_timeout_once=body.simulate_transient_timeout_once,
    )
    db.commit()
    if resp.status == AgentStatus.BLOCKED_DEPENDENCY:
        raise DomainError(
            ErrorCode.STATE_CONFLICT,
            f"Dependency gate blocked '{agent_name}': {', '.join(resp.missing_information)}",
            status_code=409,
        )
    return {"claim_status": claim.status, "agent_response": resp.model_dump()}


@router.post("/claims/{claim_id}/rework")
def request_stage_rework(
    claim_id: str,
    body: ReworkSubmitRequest,
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES, Role.SURVEYOR)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    orch = ClaimOrchestrator(db, user)
    res = orch.apply_rework_request(
        claim,
        ReworkRequest(
            from_agent=body.from_agent,
            to_agent=body.to_agent,
            reason_code=body.reason_code,
            instructions=body.instructions,
            blocking=body.blocking,
        ),
    )
    db.commit()
    return {"claim_status": claim.status, **res}


@router.post("/claims/{claim_id}/orchestration/recover")
def recover_claim_orchestration(
    claim_id: str,
    body: OrchestrationRecoverRequest = OrchestrationRecoverRequest(),
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    orch = ClaimOrchestrator(db, user)
    res = orch.recover_orchestration(
        claim,
        resolution_notes=body.resolution_notes,
        resume_pipeline=body.resume_pipeline,
    )
    db.commit()
    return {"claim_status": claim.status, **res}


@router.get("/claims/{claim_id}/tasks")
def list_claim_tasks(
    claim_id: str,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    siu_visible = user.role in SIU_ALLOWED_ROLES
    tasks = db.query(ClaimTask).filter(ClaimTask.claim_id == claim.id).order_by(ClaimTask.created_at.desc()).all()
    return {
        "items": [
            {
                "id": t.id,
                "task_type": t.task_type,
                "title": t.title,
                "description": t.description,
                "assigned_role": t.assigned_role,
                "created_by_agent": t.created_by_agent,
                "priority": t.priority,
                "status": t.status,
                "reason_code": t.reason_code,
                "due_at": t.due_at.isoformat() if t.due_at else None,
                "created_at": t.created_at.isoformat(),
            }
            for t in tasks
            if siu_visible or t.task_type != "siu_investigation"
        ]
    }


@router.patch("/claims/{claim_id}/tasks/{task_id}")
def update_claim_task(
    claim_id: str,
    task_id: str,
    body: TaskUpdateRequest,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    task = db.query(ClaimTask).filter(ClaimTask.id == task_id, ClaimTask.claim_id == claim.id).first()
    if not task:
        raise DomainError(ErrorCode.NOT_FOUND, "Claim task not found", status_code=404)
    task.status = body.status
    if body.status == "completed":
        task.completed_at = datetime.now(timezone.utc)
    if body.notes:
        task.metadata_json = {**(task.metadata_json or {}), "completion_notes": body.notes}
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="CLAIM_TASK_UPDATED",
        object_type="claim_task",
        object_id=task.id,
        after_state={"status": task.status},
    )
    db.commit()
    return {"id": task.id, "status": task.status}


@router.get("/claims/{claim_id}/decisions")
def list_claim_decisions(
    claim_id: str,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    siu_visible = user.role in SIU_ALLOWED_ROLES
    decisions = (
        db.query(DecisionRecord)
        .filter(DecisionRecord.claim_id == claim.id)
        .order_by(DecisionRecord.created_at.desc())
        .all()
    )
    return {
        "items": [
            {
                "id": d.id,
                "agent_name": d.agent_name,
                "stage": d.stage,
                "decision_id": d.decision_id,
                "routing_outcome": d.routing_outcome,
                "reason_codes": d.reason_codes,
                "evidence": d.evidence,
                "policy_rule_refs": d.policy_rule_refs,
                "confidence": str(d.confidence),
                "confidence_band": d.confidence_band,
                "explanation": d.explanation,
                "alternatives_considered": d.alternatives_considered,
                "created_at": d.created_at.isoformat(),
            }
            for d in decisions
            if siu_visible or d.agent_name != "fraud_intelligence"
        ]
    }


@router.post("/claims/{claim_id}/provider-coordination")
def coordinate_claim_providers(
    claim_id: str,
    body: ProviderCoordinateRequest = ProviderCoordinateRequest(),
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    coord = coordinate_claim_ecosystem(
        db,
        claim,
        user=user,
        preferred_garage_id=body.preferred_garage_id,
        selected_garage_id=body.selected_garage_id,
        preferred_surveyor_id=body.preferred_surveyor_id,
        towing_needed=body.towing_needed or claim.towing_needed,
        pickup_required=body.pickup_required,
        delivery_required=body.delivery_required,
        appointment_at=body.appointment_at,
        override_customer_preference=body.override_customer_preference,
        override_contract_rule=body.override_contract_rule,
        override_reason=body.override_reason,
        notify_customer=body.notify_customer,
    )
    vehicle = db.query(Vehicle).filter(Vehicle.id == claim.vehicle_id).first() if claim.vehicle_id else None
    facts = {
        "requires_mandatory_survey": claim.requires_mandatory_survey,
        "ev_battery_impacted": claim.ev_battery_impacted,
        "is_ev": vehicle.is_ev if vehicle else False,
        "incident_location": claim.incident_location,
        "towing_needed": coord.towing_required,
        "vehicle_immobile": claim.vehicle_immobile,
        "pickup_required": body.pickup_required,
        "delivery_required": body.delivery_required,
        "preferred_garage_id": coord.customer_preferred_garage_id or body.preferred_garage_id or claim.assigned_garage_id,
        "selected_garage_id": body.selected_garage_id,
        "preferred_surveyor_id": coord.surveyor_id or body.preferred_surveyor_id,
        "surveyor_license_verified": coord.surveyor_license_verified,
        "ev_safety_override_applied": bool(coord.override_applied and coord.override_reason_code == "RC_EV_SAFETY_CONTRACT_RULE"),
        "selection_explanation": coord.coordination_explanation,
        "score_breakdown": {
            "surveyor_score": coord.surveyor_score_breakdown,
            "garage_score": coord.garage_score_breakdown,
        },
        "override_customer_preference": body.override_customer_preference,
        "override_contract_rule": body.override_contract_rule,
        "override_reason": body.override_reason,
        "actor_role": user.role.value,
        "part_items": coord.parts_availability,
        "parts_stock_status": coord.parts_status,
        "notify_customer": False,
    }
    orch = ClaimOrchestrator(db, user)
    agent_res = orch.run_agent(
        claim,
        "provider_coordination",
        enforce_dependencies=False,
        override_facts=facts,
        apply_state_progression=True,
    )
    db.commit()
    return {
        "claim_status": claim.status,
        "ecosystem": serialize_ecosystem_coordination(db, coord),
        "agent_response": agent_res.model_dump(),
    }


@router.get("/claims/{claim_id}/ecosystem")
def get_claim_ecosystem(
    claim_id: str,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    coord = get_or_create_ecosystem_coordination(db, claim)
    db.commit()
    return serialize_ecosystem_coordination(db, coord)


@router.post("/claims/{claim_id}/ecosystem/inspection/reschedule")
def reschedule_ecosystem_inspection(
    claim_id: str,
    body: InspectionRescheduleRequest,
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES, Role.SURVEYOR, Role.GARAGE, Role.POLICYHOLDER)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    coord = reschedule_claim_inspection(
        db,
        claim,
        user=user,
        new_appointment_at=body.appointment_at,
        reason=body.reason,
        location=body.location,
    )
    db.commit()
    return serialize_ecosystem_coordination(db, coord)


@router.post("/claims/{claim_id}/ecosystem/surveyor-followup")
def trigger_surveyor_followup(
    claim_id: str,
    body: SurveyorFollowupRequest = SurveyorFollowupRequest(),
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    coord = send_surveyor_report_followup(
        db,
        claim,
        user=user,
        notes=body.notes,
        escalate_to_manager=body.escalate_to_manager,
    )
    _safe_proactive_notify(db, claim, user, "surveyor_delayed")
    db.commit()
    return serialize_ecosystem_coordination(db, coord)


@router.post("/claims/{claim_id}/ecosystem/parts-check")
def check_or_update_ecosystem_parts(
    claim_id: str,
    body: PartsAvailabilityRequest = PartsAvailabilityRequest(),
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES, Role.GARAGE, Role.SURVEYOR)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    coord = update_claim_parts_availability(
        db,
        claim,
        user=user,
        parts_status=body.parts_status,
        parts_items=body.parts_items,
        notify_customer=body.notify_customer,
    )
    if body.notify_customer and coord.parts_status in {"partial_backorder", "backordered"}:
        _safe_proactive_notify(db, claim, user, "parts_delayed")
    db.commit()
    return serialize_ecosystem_coordination(db, coord)


@router.post("/claims/{claim_id}/ecosystem/logistics")
def update_ecosystem_logistics(
    claim_id: str,
    body: EcosystemLogisticsRequest,
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES, Role.GARAGE, Role.POLICYHOLDER)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    coord = update_claim_logistics(
        db,
        claim,
        user=user,
        towing_status=body.towing_status,
        pickup_delivery_status=body.pickup_delivery_status,
        pickup_driver_note=body.pickup_driver_note,
        notify_customer=body.notify_customer,
    )
    db.commit()
    return serialize_ecosystem_coordination(db, coord)


@router.post("/claims/{claim_id}/ecosystem/repair-completion")
def confirm_ecosystem_repair_completion(
    claim_id: str,
    body: RepairCompletionConfirmRequest = RepairCompletionConfirmRequest(),
    user: UserContext = Depends(require_roles(Role.GARAGE, Role.CLAIMS_HANDLER, Role.SURVEYOR, Role.CLAIMS_MANAGER, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    if claim.status in {ClaimStatus.APPROVED.value, ClaimStatus.PAYMENT_INITIATED.value}:
        claim.status = validate_transition(claim.status, ClaimStatus.REPAIR_IN_PROGRESS.value).value
    claim.workflow_state = {**claim.workflow_state, "repair_milestone": body.milestone, "repair_notes": body.notes}
    claim.next_expected_action = "Run QA compliance check & close claim" if body.confirm_completion else f"Repair milestone: {body.milestone}"
    coord = update_repair_milestone_and_confirm(
        db,
        claim,
        user=user,
        milestone=body.milestone,
        notes=body.notes,
        confirm_completion=body.confirm_completion,
    )
    db.commit()
    return {
        "claim_status": claim.status,
        "repair_completion_confirmed": coord.repair_completion_confirmed,
        "ecosystem": serialize_ecosystem_coordination(db, coord),
    }


@router.post("/claims/{claim_id}/payments/agent-release", status_code=201)
def initiate_approved_payment_via_agent(
    claim_id: str,
    body: PaymentInitiateRequest,
    user: UserContext = Depends(require_roles(Role.FINANCE_APPROVER, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    assert_not_tp_for_od_path(claim, operation="agent payment release")
    assert_ev_clearance_for_od_path(db, claim, operation="agent payment release")
    stl = db.query(Settlement).filter(Settlement.id == body.settlement_id, Settlement.claim_id == claim.id).first()
    if not stl or stl.approval_status != "approved":
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            "Controlled agent payment release requires an approved settlement",
            status_code=409,
        )
    orch = ClaimOrchestrator(db, user)
    agent_res = orch.run_agent(
        claim,
        "settlement_recommendation",
        enforce_dependencies=False,
        override_facts={
            "settlement_id": stl.id,
            "idempotency_key": body.idempotency_key,
            "payee_type": body.payee_type,
            "payee_name": body.payee_name,
            "simulate_timeout": body.simulate_timeout,
            "initiate_approved_payment": True,
            "calculation": {"gross": str(stl.gross_assessed_inr), "net": str(stl.net_payable_inr)},
        },
        apply_state_progression=False,
    )
    if claim.status == ClaimStatus.APPROVED.value:
        orch.transition_state(
            claim,
            ClaimStatus.PAYMENT_PENDING.value,
            reason="Finance approved payout instruction initiated via controlled agent gate",
            trigger_event="PaymentInitiated",
            next_expected_action="Track payment reconciliation & QA closure",
        )
    pmt_task = orch._get_or_create_task(claim, "payment_execution")
    pmt_task.status = "completed"
    pmt_task.completed_at = datetime.now(timezone.utc)
    db.commit()
    return {"claim_status": claim.status, "agent_response": agent_res.model_dump()}


@router.get("/claims/{claim_id}/risk")
def get_claim_risk_profile(
    claim_id: str,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    siu_visible = user.role in SIU_ALLOWED_ROLES
    assessment = claim.risk_assessment
    if not assessment:
        assessment = evaluate_and_persist_risk(
            db,
            claim,
            trigger_event="initial_risk_inspection",
            actor_id=user.user_id,
            actor_role=user.role.value,
            record_decision=False,
            escalate_state=False,
        )
        db.commit()
    safe_assessment = sanitize_risk_payload_for_user(assessment, siu_visible=siu_visible)
    raw_hist = list(claim.risk_history or [])
    safe_hist = raw_hist if siu_visible else [{**h, "fraud_signal_score": None} for h in raw_hist]
    preserved_count = db.query(Evidence).filter(Evidence.claim_id == claim.id, Evidence.legal_hold.is_(True)).count()
    return {
        "claim_id": claim.id,
        "claim_number": claim.claim_number,
        "claim_status": claim.status,
        "risk_tier": claim.risk_tier,
        "operational_path": claim.operational_path,
        "risk_score": int(claim.risk_score or 0),
        "fraud_signal_score": str(claim.fraud_signal_score or Decimal("0.000")) if siu_visible else None,
        "fraud_score_can_reject": False,
        "siu_redacted": not siu_visible,
        "preserved_evidence_count": preserved_count,
        "risk_assessment": safe_assessment,
        "risk_history": safe_hist,
    }


@router.post("/claims/{claim_id}/risk/recalculate")
def recalculate_claim_risk(
    claim_id: str,
    body: RiskContextUpdateRequest,
    user: UserContext = Depends(require_roles(*INTERNAL_ROLES, Role.SURVEYOR)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    candidate_score = (
        body.fraud_signal_score_override_attempt
        if body.fraud_signal_score_override_attempt is not None
        else claim.fraud_signal_score
    )
    if body.decision_requested:
        assert_fraud_score_never_rejects(
            decision=body.decision_requested,
            fraud_signal_score=candidate_score,
            rationale=(
                f"{body.trigger_event} fraud_score={candidate_score}"
                if body.fraud_signal_score_override_attempt is not None
                or "fraud" in body.trigger_event.lower()
                else body.trigger_event
            ),
        )

    if body.estimated_loss_inr is not None:
        claim.estimated_loss_inr = body.estimated_loss_inr
    if body.injury_or_fatality is not None:
        claim.injury_or_fatality = body.injury_or_fatality
    if body.multiple_vehicles_involved is not None:
        claim.multiple_vehicles_involved = body.multiple_vehicles_involved
        if body.multiple_vehicles_involved and int(claim.involved_vehicles_count or 1) < 2:
            claim.involved_vehicles_count = 2
    if body.involved_vehicles_count is not None:
        claim.involved_vehicles_count = max(1, body.involved_vehicles_count)
        if body.involved_vehicles_count > 1:
            claim.multiple_vehicles_involved = True
    if body.ev_battery_impacted is not None:
        claim.ev_battery_impacted = body.ev_battery_impacted
    if body.airbags_deployed is not None:
        claim.airbags_deployed = body.airbags_deployed
    if body.vehicle_immobile is not None:
        claim.vehicle_immobile = body.vehicle_immobile
    if body.towing_needed is not None:
        claim.towing_needed = body.towing_needed
    if body.legal_dispute is not None:
        claim.legal_dispute = body.legal_dispute
    if body.missing_documents is not None:
        claim.missing_documents = list(body.missing_documents)
    if body.incident_description_append:
        clean_add, _, _ = sanitize_untrusted_text(body.incident_description_append)
        claim.incident_description = f"{claim.incident_description}\n[New Evidence Update]: {clean_add}".strip()

    if body.new_evidence_summary:
        clean_note, has_inj, _ = sanitize_untrusted_text(body.new_evidence_summary)
        db.add(
            Evidence(
                tenant_id=claim.tenant_id,
                claim_id=claim.id,
                doc_type="supplement_evidence_note",
                doc_status="extracted_unverified",
                filename=f"evidence_update_{uuid.uuid4().hex[:6]}.txt",
                mime_type="text/plain",
                size_bytes=len(clean_note.encode("utf-8")),
                sha256=uuid.uuid4().hex,
                storage_path=f"./evidence_store/update_{claim.id}.txt",
                uploader_user_id=user.user_id,
                upload_source=user.role.value,
                malware_scan_status="clean_mock",
                prompt_injection_flagged=has_inj,
                ocr_version="note-update-v1",
                ocr_text=clean_note,
            )
        )

    if body.fraud_signal_score_override_attempt is not None:
        score_val = Decimal(str(body.fraud_signal_score_override_attempt))
        if score_val >= Decimal("0.650"):
            existing_alert = (
                db.query(FraudAlert)
                .filter(FraudAlert.claim_id == claim.id, FraudAlert.indicator_code == "FRD-ENTITY-RING-CLUSTER")
                .first()
            )
            if not existing_alert:
                db.add(
                    FraudAlert(
                        tenant_id=claim.tenant_id,
                        claim_id=claim.id,
                        indicator_code="FRD-ENTITY-RING-CLUSTER",
                        title="Elevated fraud signal indicator raised by new evidence",
                        severity_band="high" if score_val >= Decimal("0.800") else "medium",
                        confidence=min(Decimal("0.990"), score_val),
                        evidence_summary=body.new_evidence_summary or "New cross-claim forensic signal reported.",
                        benign_explanation="Advisory signal only; specialist SIU verification required — fraud score NEVER rejects claim.",
                        recommended_action="Assign SIU Investigator for human-led verification and preserve evidence.",
                        status="new",
                    )
                )

    db.flush()
    assessment = evaluate_and_persist_risk(
        db,
        claim,
        trigger_event=body.trigger_event,
        actor_id=user.user_id,
        actor_role=user.role.value,
        record_decision=True,
        escalate_state=True,
    )
    db.commit()
    siu_visible = user.role in SIU_ALLOWED_ROLES
    preserved_count = db.query(Evidence).filter(Evidence.claim_id == claim.id, Evidence.legal_hold.is_(True)).count()
    raw_hist = list(claim.risk_history or [])
    return {
        "claim_id": claim.id,
        "claim_status": claim.status,
        "risk_tier": claim.risk_tier,
        "operational_path": claim.operational_path,
        "risk_score": int(claim.risk_score or 0),
        "fraud_signal_score": str(claim.fraud_signal_score or Decimal("0.000")) if siu_visible else None,
        "fraud_score_can_reject": False,
        "preserved_evidence_count": preserved_count,
        "risk_assessment": sanitize_risk_payload_for_user(assessment, siu_visible=siu_visible),
        "risk_history": raw_hist if siu_visible else [{**h, "fraud_signal_score": None} for h in raw_hist],
    }


@router.get("/claims/{claim_id}/customer-experience")
def get_customer_experience_view(
    claim_id: str,
    language: Optional[str] = None,
    trigger: Optional[str] = None,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    comms = (
        db.query(Communication)
        .filter(Communication.claim_id == claim.id)
        .order_by(Communication.created_at.desc())
        .all()
    )
    return {
        "journey": build_customer_claim_journey(db, claim, language_override=language),
        "intelligence": inspect_claim_communication_context(
            db,
            claim,
            trigger_override=trigger,
            language_override=language,
        ),
        "communications": [
            {
                "id": cm.id,
                "channel": cm.channel,
                "language": cm.language,
                "template_id": cm.template_id,
                "trigger_event": cm.trigger_event,
                "claim_state_snapshot": cm.claim_state_snapshot,
                "subject": cm.subject,
                "body": cm.body,
                "requires_human_review": cm.requires_human_review,
                "delivery_status": cm.delivery_status,
                "consent_verified": bool(cm.consent_verified),
                "whatsapp_message_id": cm.whatsapp_message_id,
                "context_summary": cm.context_summary,
                "created_at": cm.created_at.isoformat(),
            }
            for cm in comms
        ],
    }


@router.patch("/claims/{claim_id}/customer-preferences")
def patch_customer_preferences(
    claim_id: str,
    body: CustomerPreferencesUpdateRequest,
    user: UserContext = Depends(require_roles(Role.POLICYHOLDER, *INTERNAL_ROLES)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    prefs = update_customer_communication_preferences(
        db,
        claim,
        actor=user,
        preferred_language=body.preferred_language,
        preferred_channel=body.preferred_channel,
        consent_whatsapp=body.consent_whatsapp,
        consent_sms=body.consent_sms,
        consent_email=body.consent_email,
        proactive_updates_enabled=body.proactive_updates_enabled,
    )
    db.commit()
    return {
        "claim_id": claim.id,
        "preferences": prefs,
        "journey": build_customer_claim_journey(db, claim),
        "intelligence": inspect_claim_communication_context(db, claim),
    }


@router.post("/claims/{claim_id}/proactive-updates", status_code=201)
def trigger_proactive_customer_update(
    claim_id: str,
    body: ProactiveUpdateRequest = ProactiveUpdateRequest(),
    user: UserContext = Depends(require_roles(Role.POLICYHOLDER, *INTERNAL_ROLES, Role.SURVEYOR, Role.GARAGE)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    res = dispatch_proactive_customer_update(
        db,
        claim,
        actor=user,
        trigger_event=body.trigger_event,
        language=body.language,
        channel=body.channel,
        force=body.force,
    )
    db.commit()
    return res


@router.post("/claims/{claim_id}/customer-escalation", status_code=201)
def request_customer_human_escalation(
    claim_id: str,
    body: CustomerEscalationRequest,
    user: UserContext = Depends(require_roles(Role.POLICYHOLDER, *INTERNAL_ROLES)),
    db: Session = Depends(get_db),
):
    claim = _get_claim_for_user(db, claim_id, user)
    res = escalate_to_human_specialist(
        db,
        claim,
        actor=user,
        reason_category=body.reason_category,
        notes=body.notes,
        preferred_language=body.preferred_language,
        preferred_channel=body.preferred_channel,
    )
    db.commit()
    return res
