from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


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
    estimated_loss_inr: Decimal = Decimal("0.00")
    preferred_garage_id: Optional[str] = None
    preferred_language: str = "en-IN"
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
    preferred_surveyor_id: Optional[str] = None
    towing_needed: bool = False
