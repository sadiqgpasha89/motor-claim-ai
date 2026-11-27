from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str


class FNOLCreateRequest(BaseModel):
    idempotency_key: Optional[str] = None
    policy_number: str
    vehicle_reg: str
    claim_type: str = "own_damage"
    peril_cause: str = "road_accident"
    intake_channel: str = "web"
    incident_at: Optional[datetime] = None
    incident_location: str
    geo_coords: Optional[str] = None
    location_landmark: str = ""
    incident_description: str
    channel_transcript: Optional[str] = None
    driver_name: str = ""
    driver_licence_ref: str = ""
    vehicle_immobile: bool = False
    airbags_deployed: bool = False
    injury_or_fatality: bool = False
    police_involved: bool = False
    towing_needed: bool = False
    ev_battery_impacted: bool = False
    multiple_vehicles_involved: bool = False
    involved_vehicles_count: int = 1
    legal_dispute: bool = False
    documents_complete_at_fnol: bool = False
    estimated_loss_inr: Decimal = Decimal("0.00")
    preferred_garage_id: Optional[str] = None
    preferred_language: str = "en-IN"
    preferred_channel: str = "whatsapp"
    whatsapp_consent: bool = True
    auto_send_ack: bool = False


class FactCorrectionRequest(BaseModel):
    verified_value: str
    validation_status: str = "corrected"


class DamageReviewRequest(BaseModel):
    reviewer_outcome: str
    reviewer_notes: str = ""


class EstimateLineInput(BaseModel):
    part_code: str
    description: str
    part_category: str = "metal"
    line_type: str = "part"
    action: str = "replace"
    quantity: int = 1
    unit_price_inr: Decimal


class EstimateSubmitRequest(BaseModel):
    garage_id: Optional[str] = None
    is_supplement: bool = False
    lines: list[EstimateLineInput]


class EstimateLineReviewRequest(BaseModel):
    reviewer_status: str
    approved_amount_inr: Optional[Decimal] = None


class FraudDispositionRequest(BaseModel):
    status: str
    investigator_notes: str = ""
    disposition_reason: Optional[str] = None


class SurveyorAssignRequest(BaseModel):
    surveyor_id: Optional[str] = None
    garage_id: Optional[str] = None


class SurveyReportSubmitRequest(BaseModel):
    inspection_notes: str
    assessed_gross_inr: Decimal
    hidden_damage_found: bool = False
    recommended_pathway: str = "cashless"
    signed: bool = True


class SettlementRecommendRequest(BaseModel):
    requested_pathway: str = "cashless"
    salvage_value_inr: Decimal = Decimal("0.00")


class SettlementWorkbenchRequest(BaseModel):
    """What-if overrides for the synthetic demo claim; omitted fields keep the demo defaults."""

    vehicle_age_months: int | None = Field(default=None, ge=0, le=600)
    idv_inr: Decimal | None = Field(default=None, ge=0)
    market_value_inr: Decimal | None = Field(default=None, ge=0)
    compulsory_deductible_inr: Decimal | None = Field(default=None, ge=0)
    voluntary_deductible_inr: Decimal | None = Field(default=None, ge=0)
    salvage_value_inr: Decimal | None = Field(default=None, ge=0)
    zero_depreciation: bool | None = None
    consumables: bool | None = None


class ApprovalDecisionRequest(BaseModel):
    approval_id: str
    decision: str
    rationale: str


class PaymentInitiateRequest(BaseModel):
    settlement_id: str
    idempotency_key: str
    payee_type: str = "garage"
    payee_name: str
    account_last4: str = "4821"
    ifsc: str = "HDFC0000123"
    simulate_timeout: bool = False


class CommunicationCreateRequest(BaseModel):
    channel: str = "email"
    language: str = "en-IN"
    template_id: str = "CLAIM_UPDATE"
    message_type: str = "status_update"
    subject: str
    body: str
    is_adverse: bool = False


class GrievanceCreateRequest(BaseModel):
    category: str
    description: str


class GrievanceResolveRequest(BaseModel):
    status: str = "resolved"
    resolution_notes: str


class RuleSimulateRequest(BaseModel):
    sample_estimated_loss_inr: Decimal = Decimal("50000.00")
    proposed_threshold_inr: Decimal = Decimal("75000.00")


class ClaimAssignRequest(BaseModel):
    assigned_handler_id: str


class AiOutageToggleRequest(BaseModel):
    enabled: bool


class RepairMilestoneRequest(BaseModel):
    milestone: str
    notes: str = ""
    confirm_completion: bool = False


class OrchestrateRequest(BaseModel):
    stop_on_human_gate: bool = True
    max_steps: int = 15
    simulate_timeout_agent: Optional[str] = None
    simulate_transient_timeout_once_agent: Optional[str] = None


class SingleAgentOrchestrateRequest(BaseModel):
    enforce_dependencies: bool = True
    simulate_timeout: bool = False
    simulate_transient_timeout_once: bool = False


class ReworkSubmitRequest(BaseModel):
    from_agent: str
    to_agent: str
    reason_code: str
    instructions: str
    blocking: bool = True


class OrchestrationRecoverRequest(BaseModel):
    resolution_notes: str = "Resolved upstream holds and recovered orchestration."
    resume_pipeline: bool = True


class OrchestrationEventRequest(BaseModel):
    event_id: str
    event_type: str
    source: str = "api"
    payload: dict = {}
    auto_advance: bool = True


class WorkflowPauseRequest(BaseModel):
    reason: str = "Paused for operational review"


class WorkflowResumeRequest(BaseModel):
    resolution_notes: str = "Resumed workflow from checkpoint"
    run_ready_stages: bool = True


class CompensationRequest(BaseModel):
    trigger_reason: str = "Downstream failure or cancellation rollback"
    target_state: str = "HUMAN_REVIEW"


class DLQActionRequest(BaseModel):
    resolution_notes: str = "Operator resolved DLQ item"


class TaskUpdateRequest(BaseModel):
    status: str = "completed"
    notes: str = ""


class ProviderCoordinateRequest(BaseModel):
    preferred_garage_id: Optional[str] = None
    selected_garage_id: Optional[str] = None
    preferred_surveyor_id: Optional[str] = None
    towing_needed: bool = False
    pickup_required: bool = False
    delivery_required: bool = False
    appointment_at: Optional[datetime] = None
    override_customer_preference: bool = False
    override_contract_rule: bool = False
    override_reason: str = ""
    notify_customer: bool = True


class InspectionRescheduleRequest(BaseModel):
    appointment_at: datetime
    reason: str
    location: str = ""


class SurveyorFollowupRequest(BaseModel):
    notes: str = "IRDAI 15-day surveyor report SLA follow-up"
    escalate_to_manager: bool = False


class PartsAvailabilityRequest(BaseModel):
    parts_status: Optional[str] = None
    parts_items: Optional[list[dict]] = None
    notify_customer: bool = True


class EcosystemLogisticsRequest(BaseModel):
    towing_status: Optional[str] = None
    pickup_delivery_status: Optional[str] = None
    pickup_driver_note: str = ""
    notify_customer: bool = True


class RepairCompletionConfirmRequest(BaseModel):
    milestone: str = "repair_completed"
    notes: str = "Post-repair QC passed and customer handover ready"
    confirm_completion: bool = True


class RiskContextUpdateRequest(BaseModel):
    trigger_event: str = "manual_risk_recalculation"
    estimated_loss_inr: Optional[Decimal] = None
    injury_or_fatality: Optional[bool] = None
    multiple_vehicles_involved: Optional[bool] = None
    involved_vehicles_count: Optional[int] = None
    ev_battery_impacted: Optional[bool] = None
    airbags_deployed: Optional[bool] = None
    vehicle_immobile: Optional[bool] = None
    towing_needed: Optional[bool] = None
    legal_dispute: Optional[bool] = None
    missing_documents: Optional[list[str]] = None
    incident_description_append: Optional[str] = None
    new_evidence_summary: Optional[str] = None
    fraud_signal_score_override_attempt: Optional[Decimal] = None
    decision_requested: Optional[str] = None


# ---- Third-Party (TP) liability workflow (IN-TP-LIABILITY-2026) ----
class TPOpenRequest(BaseModel):
    tp_category: Optional[str] = None


class TPExposureRequest(BaseModel):
    tp_category: str
    description: str = ""


class TPThirdPartyRequest(BaseModel):
    role: str
    name: str
    contact: str = ""
    vehicle_reg: str = ""
    other_insurer: str = ""
    injury_severity: Optional[str] = None
    claimant_demand_inr: Optional[Decimal] = None
    is_minor: bool = False
    notes: str = ""


class TPEvidenceItem(BaseModel):
    kind: str = "other"
    description: str = ""
    source: str = ""


class TPFactsRequest(BaseModel):
    accident_at: Optional[datetime] = None
    location: Optional[str] = None
    narrative: Optional[str] = None
    police_involved: Optional[bool] = None
    vehicles_involved: Optional[int] = None
    evidence: list[TPEvidenceItem] = []


class TPPoliceReportRequest(BaseModel):
    fir_number: str = ""
    police_station: str = ""
    fir_date: Optional[datetime] = None
    sections_invoked: list[str] = []
    dar_status: str = "pending"
    charge_sheet_status: str = "not_filed"
    fir_waived: bool = False
    waiver_reason: str = ""


class TPLiabilityRequest(BaseModel):
    insured_fault_pct: int
    third_party_fault_pct: int
    contributory_negligence: bool = False
    policy_defences: list[str] = []
    rationale: str
    investigator_name: str = ""


class TPLegalDocumentRequest(BaseModel):
    doc_type: str
    status: str = "received"
    reference: str = ""
    notes: str = ""


class TPTribunalRequest(BaseModel):
    claim_petition_filed: Optional[bool] = None
    tribunal_name: str = ""
    petition_number: str = ""
    next_hearing_at: Optional[datetime] = None
    award_amount_inr: Optional[Decimal] = None
    award_reference: str = ""


class TPAdvocateRequest(BaseModel):
    advocate_name: str
    bar_enrolment_ref: str = ""
    role: str = "panel_counsel"
    fee_cap_inr: Optional[Decimal] = None
    conflict_check_cleared: bool = False


class TPMedicalReviewRequest(BaseModel):
    injury_severity: str
    disability_percent: Optional[int] = None
    causation_consistent: bool = True
    opinion: str
    reviewer_name: str
    records_reviewed: list[str] = []


class TPLegalReviewRequest(BaseModel):
    decision: str
    notes: str
    exposure_summary: str = ""


class TPReserveRequest(BaseModel):
    amount_inr: Decimal
    basis: str


class TPSettlementProposalRequest(BaseModel):
    basis: str = "negotiated"
    amount_inr: Decimal
    components: dict[str, Decimal] = {}
    rationale: str
    award_reference: str = ""


class TPSettlementDecisionRequest(BaseModel):
    decision: str
    rationale: str


class TPPaymentAuthoriseRequest(BaseModel):
    idempotency_key: str
    payee_type: str = "claimant"
    payee_name: str
    account_last4: str = ""
    ifsc: str = ""
    simulate_timeout: bool = False


class TPAdvanceRequest(BaseModel):
    note: str = ""


class TPCloseRequest(BaseModel):
    closure_notes: str
    recovery_action_opened: bool = False
class CustomerPreferencesUpdateRequest(BaseModel):
    preferred_language: Optional[str] = None
    preferred_channel: Optional[str] = None
    consent_whatsapp: Optional[bool] = None
    consent_sms: Optional[bool] = None
    consent_email: Optional[bool] = None
    proactive_updates_enabled: Optional[bool] = None


class ProactiveUpdateRequest(BaseModel):
    trigger_event: Optional[str] = None
    language: Optional[str] = None
    channel: Optional[str] = None
    force: bool = True


class CustomerEscalationRequest(BaseModel):
    reason_category: str = "callback_request"
    notes: str = ""
    preferred_language: Optional[str] = None
    preferred_channel: Optional[str] = None


class SLAAgentRunRequest(BaseModel):
    """Run the predictive SLA agent over the portfolio. ``recommend`` never changes data; ``execute`` runs only authorised actions."""

    mode: Literal["recommend", "execute"] = "recommend"
    claim_ids: Optional[list[str]] = None
    min_risk_band: Literal["watch", "at_risk", "critical", "breached"] = "at_risk"
    limit: int = Field(default=10, ge=1, le=50)


class SLARulesValidateRequest(BaseModel):
    catalogue: dict[str, Any]


# ---- Electric-vehicle (EV) claims workflow (IN-EV-CLAIMS-2026) ----
class EVTriageRequest(BaseModel):
    signals: list[str] = []
    notes: str = ""
    customer_declared_drivable: Optional[bool] = None
    charging_in_progress: bool = False
    vehicle_location: str = ""


class EVSafetyEscalationRequest(BaseModel):
    signals: list[str] = []
    description: str
    level: Optional[str] = None


class EVEscalationAcknowledgeRequest(BaseModel):
    actions_taken: str


class EVEscalationResolveRequest(BaseModel):
    resolution: str
    evidence_ref: str = ""
    thermal_stable_confirmed: bool = False


class EVRecoveryRequest(BaseModel):
    provider_id: Optional[str] = None
    tow_method: str
    hv_isolation_method: str = ""
    hv_isolation_verified: bool = False
    quarantine_location: str = ""
    quarantine_clearance_m: Optional[Decimal] = None
    notes: str = ""


class EVSpecialistSurveyRequest(BaseModel):
    surveyor_provider_id: Optional[str] = None
    inspection_mode: str
    hv_isolation_verified: bool = False
    pack_findings: list[str] = []
    hv_system_findings: list[str] = []
    charging_system_findings: list[str] = []
    thermal_indicators_observed: bool = False
    pack_removal_required: bool = False
    report_ref: str = ""
    notes: str = ""


class EVDiagnosticTest(BaseModel):
    test: str
    result: str
    value: Optional[Decimal] = None
    unit: str = ""
    note: str = ""


class EVOemDiagnosticsRequest(BaseModel):
    provider_id: Optional[str] = None
    tool: str = ""
    report_ref: str = ""
    tests: list[EVDiagnosticTest]


class EVDispositionRequest(BaseModel):
    decision: str
    rationale: str
    oem_engineer_name: str = ""
    oem_engineer_ref: str = ""
    oem_engineer_org: str = ""


class EVBenchmarkLine(BaseModel):
    kind: str = "part"
    part_code: str = ""
    description: str = ""
    quantity: Decimal = Decimal("1")
    unit_quoted_inr: Optional[Decimal] = None
    hours: Optional[Decimal] = None
    rate_inr: Optional[Decimal] = None


class EVBenchmarkRequest(BaseModel):
    lines: list[EVBenchmarkLine]


class EVBenchmarkReviewRequest(BaseModel):
    note: str = ""


class EVThermalWatchClearRequest(BaseModel):
    basis: str
    oem_reference: str


class EVTechnicalSignOffRequest(BaseModel):
    notes: str = ""


class EVRecertificationRequest(BaseModel):
    provider_id: Optional[str] = None
    insulation_resistance_ohm_per_volt: Decimal
    dtc_cleared: bool = False
    hv_interlock_ok: bool = False
    charge_test_ok: bool = False
    thermal_scan_ok: bool = False
    physical_road_test_done: bool = False
    oem_certificate_ref: str = ""
    notes: str = ""


class EVSalvageEventRequest(BaseModel):
    event: str
    battery_serial: str
    location: str = ""
    performed_by_provider_id: Optional[str] = None
    recycler_registration_no: str = ""
    transport_dg_compliant: bool = False
    certificate_ref: str = ""
    note: str = ""


class EVAdvanceRequest(BaseModel):
    note: str = ""


class EVCloseRequest(BaseModel):
    closure_notes: str
