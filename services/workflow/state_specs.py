from __future__ import annotations

import random
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from services.claims.models import (
    Approval,
    Claim,
    DamageAssessment,
    Estimate,
    Evidence,
    ExtractedFact,
    FraudAlert,
    Grievance,
    Payment,
    Settlement,
    SurveyAssignment,
)
from services.claims.state_machine import ClaimStatus


class SLASpec(BaseModel):
    stage: str
    target_hours: int
    internal_target_hours: float
    warning_pct: int = 75
    escalation_role: str = "claims_manager"
    daily_penalty_inr: str = "0.00"


class RetryStrategySpec(BaseModel):
    max_retries: int = 2
    base_delay_ms: int = 200
    backoff_multiplier: float = 2.0
    max_delay_ms: int = 5000
    jitter_pct: float = 0.1
    retryable_errors: list[str] = Field(
        default_factory=lambda: ["AgentTimeoutError", "TransientGatewayError", "OutboxDeliveryError"]
    )
    dlq_on_exhaustion: bool = True


class StateContractSpec(BaseModel):
    state: str
    display_name: str
    phase: str
    description: str
    entry_conditions: list[str]
    required_data: list[str]
    allowed_actions: list[str]
    exit_conditions: list[str]
    responsible_agent_or_service: str
    sla: SLASpec
    retry_strategy: RetryStrategySpec
    human_escalation_criteria: list[str]
    next_states: list[str]
    triage_substates: list[str] = Field(default_factory=list)


class TaskDAGSpec(BaseModel):
    task_key: str
    title: str
    dependency_label: str
    depends_on: list[str]
    execution_mode: str  # parallel | sequential | conditional | approval_gated
    parallel_group: str | None = None
    condition_description: str | None = None
    agent_or_service: str
    target_state: str
    timeout_seconds: int = 15
    max_retries: int = 2


TASK_DAG_SPECS: list[TaskDAGSpec] = [
    TaskDAGSpec(
        task_key="fnol_intake",
        title="FNOL Intimation & Claim Registration",
        dependency_label="External FNOL Event + Idempotency-Key",
        depends_on=[],
        execution_mode="sequential",
        agent_or_service="fnol_concierge",
        target_state=ClaimStatus.REGISTERED.value,
        timeout_seconds=12,
        max_retries=2,
    ),
    TaskDAGSpec(
        task_key="policy_validation",
        title="Policy Validation & Coverage Matrix",
        dependency_label="FNOL",
        depends_on=["fnol_intake"],
        execution_mode="parallel",
        parallel_group="post_fnol_parallel",
        agent_or_service="coverage_intelligence",
        target_state=ClaimStatus.VALIDATION.value,
        timeout_seconds=15,
        max_retries=2,
    ),
    TaskDAGSpec(
        task_key="document_extraction",
        title="Document Extraction & Cross-Doc Reconciliation",
        dependency_label="FNOL",
        depends_on=["fnol_intake"],
        execution_mode="parallel",
        parallel_group="post_fnol_parallel",
        agent_or_service="document_intelligence",
        target_state=ClaimStatus.VALIDATION.value,
        timeout_seconds=15,
        max_retries=2,
    ),
    TaskDAGSpec(
        task_key="duplicate_check",
        title="Duplicate Claim & Entity Collision Check",
        dependency_label="FNOL",
        depends_on=["fnol_intake"],
        execution_mode="parallel",
        parallel_group="post_fnol_parallel",
        agent_or_service="duplicate_detector_service",
        target_state=ClaimStatus.VALIDATION.value,
        timeout_seconds=8,
        max_retries=2,
    ),
    TaskDAGSpec(
        task_key="customer_communication",
        title="Multilingual Customer Registration Acknowledgement",
        dependency_label="Claim registration",
        depends_on=["fnol_intake"],
        execution_mode="parallel",
        parallel_group="post_fnol_parallel",
        agent_or_service="customer_communication",
        target_state=ClaimStatus.REGISTERED.value,
        timeout_seconds=10,
        max_retries=2,
    ),
    TaskDAGSpec(
        task_key="claim_triage",
        title="Claim Triage & Pathway Branching",
        dependency_label="Policy + extracted data",
        depends_on=["policy_validation", "document_extraction", "duplicate_check"],
        execution_mode="sequential",
        agent_or_service="claim_triage",
        target_state=ClaimStatus.TRIAGE.value,
        timeout_seconds=10,
        max_retries=2,
    ),
    TaskDAGSpec(
        task_key="provider_coordination",
        title="Surveyor, Garage & Towing Dispatch",
        dependency_label="Claim triage + mandatory survey / EV / towing trigger",
        depends_on=["claim_triage"],
        execution_mode="conditional",
        condition_description="Executed when requires_mandatory_survey, towing_needed, or ev_battery_impacted is true",
        agent_or_service="provider_coordination",
        target_state=ClaimStatus.SURVEY_REQUIRED.value,
        timeout_seconds=12,
        max_retries=2,
    ),
    TaskDAGSpec(
        task_key="damage_assessment",
        title="Visual Damage Assessment",
        dependency_label="Photos + vehicle details",
        depends_on=["claim_triage"],
        execution_mode="conditional",
        parallel_group="assessment_and_fraud_parallel",
        condition_description="Conditional on uploaded vehicle photos & vehicle details",
        agent_or_service="damage_assessment",
        target_state=ClaimStatus.ASSESSMENT.value,
        timeout_seconds=20,
        max_retries=2,
    ),
    TaskDAGSpec(
        task_key="fraud_analysis",
        title="Fraud & Anomaly Network Analysis",
        dependency_label="Claim + evidence",
        depends_on=["claim_triage", "document_extraction"],
        execution_mode="parallel",
        parallel_group="assessment_and_fraud_parallel",
        condition_description="Parallel with damage assessment",
        agent_or_service="fraud_intelligence",
        target_state=ClaimStatus.ASSESSMENT.value,
        timeout_seconds=15,
        max_retries=2,
    ),
    TaskDAGSpec(
        task_key="estimate_validation",
        title="Repair Estimate & OEM Rate-Card Validation",
        dependency_label="Damage assessment + garage estimate",
        depends_on=["damage_assessment"],
        execution_mode="sequential",
        condition_description="Requires submitted garage estimate lines",
        agent_or_service="estimate_validation",
        target_state=ClaimStatus.ESTIMATE_VALIDATION.value,
        timeout_seconds=15,
        max_retries=2,
    ),
    TaskDAGSpec(
        task_key="settlement_recommendation",
        title="Deterministic Settlement Calculation",
        dependency_label="Assessment + coverage + estimate",
        depends_on=["damage_assessment", "policy_validation", "estimate_validation", "fraud_analysis"],
        execution_mode="sequential",
        agent_or_service="settlement_recommendation",
        target_state=ClaimStatus.SETTLEMENT_PENDING_APPROVAL.value,
        timeout_seconds=15,
        max_retries=2,
    ),
    TaskDAGSpec(
        task_key="human_approval_gate",
        title="Independent Maker-Checker DoA Approval Gate",
        dependency_label="Settlement recommendation",
        depends_on=["settlement_recommendation"],
        execution_mode="approval_gated",
        agent_or_service="doa_authority_service",
        target_state=ClaimStatus.APPROVED.value,
        timeout_seconds=30,
        max_retries=0,
    ),
    TaskDAGSpec(
        task_key="payment_execution",
        title="Idempotent Finance Payout Instruction",
        dependency_label="Approved settlement",
        depends_on=["human_approval_gate"],
        execution_mode="approval_gated",
        agent_or_service="payment_gateway_adapter",
        target_state=ClaimStatus.PAYMENT_PENDING.value,
        timeout_seconds=15,
        max_retries=2,
    ),
    TaskDAGSpec(
        task_key="payment_reconciliation",
        title="Gateway UTR & Ledger Reconciliation",
        dependency_label="Payment execution",
        depends_on=["payment_execution"],
        execution_mode="sequential",
        agent_or_service="reconciliation_service",
        target_state=ClaimStatus.PAYMENT_RECONCILIATION.value,
        timeout_seconds=15,
        max_retries=3,
    ),
    TaskDAGSpec(
        task_key="qa_closure",
        title="Pre-Closure QA & Compliance Audit",
        dependency_label="Payment reconciliation",
        depends_on=["payment_reconciliation"],
        execution_mode="sequential",
        agent_or_service="qa_compliance",
        target_state=ClaimStatus.CLOSED.value,
        timeout_seconds=12,
        max_retries=2,
    ),
]


WORKFLOW_STATE_SPECS: dict[str, StateContractSpec] = {
    ClaimStatus.SUBMITTED.value: StateContractSpec(
        state=ClaimStatus.SUBMITTED.value,
        display_name="Submitted",
        phase="1. Intake",
        description="Initial FNOL payload received from Web, Mobile, WhatsApp, or Voice channel with duplicate-event and Idempotency-Key protection.",
        entry_conditions=[
            "Valid authenticated session or partner webhook token",
            "Idempotency-Key verified (no prior conflicting claim for same key)",
        ],
        required_data=["policy_number_input", "vehicle_reg_input", "incident_description", "incident_location"],
        allowed_actions=["sanitize_untrusted_text", "assign_idempotency_key", "emit_fnol_submitted_event"],
        exit_conditions=["Claim row persisted cleanly", "Claim number assigned", "FNOL concierge intake completed"],
        responsible_agent_or_service="ClaimOrchestrator + FNOLConciergeAgent",
        sla=SLASpec(stage="fnol_acknowledgement", target_hours=24, internal_target_hours=0.05, warning_pct=50, escalation_role="claims_manager"),
        retry_strategy=RetryStrategySpec(max_retries=2, base_delay_ms=100, backoff_multiplier=2.0, max_delay_ms=1000),
        human_escalation_criteria=["Unparseable channel payload after sanitization", "Customer requests immediate human callback"],
        next_states=[ClaimStatus.REGISTERED.value, ClaimStatus.HUMAN_REVIEW.value],
    ),
    ClaimStatus.REGISTERED.value: StateContractSpec(
        state=ClaimStatus.REGISTERED.value,
        display_name="Registered",
        phase="1. Intake",
        description="Claim formally registered without blocking for missing documents (IRDAI 2024). Orchestrator fans out parallel validation & communication tasks.",
        entry_conditions=["Claim exists in SUBMITTED state", "Idempotency check passed"],
        required_data=["claim_number", "tenant_id", "workflow_run_id", "incident_at"],
        allowed_actions=[
            "schedule_post_fnol_parallel_wave",
            "dispatch_towing",
            "send_localized_acknowledgement",
            "issue_document_checklist",
        ],
        exit_conditions=["Post-FNOL parallel tasks scheduled (policy_validation, document_extraction, duplicate_check, customer_communication)"],
        responsible_agent_or_service="ClaimOrchestrator + FNOLConciergeAgent + CustomerCommunicationAgent",
        sla=SLASpec(stage="surveyor_allocation", target_hours=24, internal_target_hours=6, warning_pct=75, escalation_role="claims_manager"),
        retry_strategy=RetryStrategySpec(max_retries=2, base_delay_ms=200, backoff_multiplier=2.0, max_delay_ms=2000),
        human_escalation_criteria=["Duplicate open claim detected on same registration & incident date", "Model gateway outage during intake"],
        next_states=[ClaimStatus.VALIDATION.value, ClaimStatus.HUMAN_REVIEW.value],
    ),
    ClaimStatus.VALIDATION.value: StateContractSpec(
        state=ClaimStatus.VALIDATION.value,
        display_name="Validation",
        phase="2. Validation",
        description="Parallel execution of Policy Validation (Hybrid RAG), Document Extraction & Cross-Doc Reconciliation, and Duplicate Claim Checks.",
        entry_conditions=["Claim is REGISTERED", "Post-FNOL parallel wave initiated"],
        required_data=["policy_id (or policy_number_input)", "vehicle_id (or vehicle_reg_input)", "uploaded_evidence (if available)"],
        allowed_actions=[
            "run_policy_validation_parallel",
            "run_document_extraction_parallel",
            "run_duplicate_check_parallel",
            "request_missing_documents",
            "quarantine_prompt_injection",
        ],
        exit_conditions=[
            "policy_validation published without blocking ambiguity",
            "document_extraction published without unresolved RC/policy mismatch or prompt injection",
            "duplicate_check completed",
        ],
        responsible_agent_or_service="CoverageIntelligenceAgent + DocumentIntelligenceAgent + DuplicateDetectorService (Parallel Wave)",
        sla=SLASpec(stage="validation_completion", target_hours=12, internal_target_hours=2, warning_pct=75, escalation_role="claims_handler"),
        retry_strategy=RetryStrategySpec(max_retries=2, base_delay_ms=250, backoff_multiplier=2.0, max_delay_ms=4000),
        human_escalation_criteria=[
            "Prompt injection directive quarantined inside uploaded evidence",
            "RC/Policy/DL cross-document mismatch detected",
            "Policy inactive, lapsed, or incident outside policy period",
            "Duplicate open claim collision confirmed",
        ],
        next_states=[ClaimStatus.TRIAGE.value, ClaimStatus.HUMAN_REVIEW.value, ClaimStatus.DECLINED_PARTIAL.value],
    ),
    ClaimStatus.TRIAGE.value: StateContractSpec(
        state=ClaimStatus.TRIAGE.value,
        display_name="Triage",
        phase="3. Triage",
        description="Sequential decision point combining validated policy coverage and extracted evidence to route the claim deterministically into FAST_TRACK, SURVEY_REQUIRED, INVESTIGATION_REQUIRED, or HUMAN_REVIEW.",
        entry_conditions=["Policy validation, document extraction, and duplicate checks completed cleanly"],
        required_data=["coverage_factsheet", "estimated_loss_inr", "peril_cause", "injury_or_fatality", "ev_battery_impacted"],
        allowed_actions=["classify_severity_and_queue", "evaluate_irdai_50k_threshold", "branch_triage_pathway"],
        exit_conditions=["ClaimTriageAgent published routing outcome", "Orchestrator transitions to selected triage branch"],
        responsible_agent_or_service="ClaimTriageAgent + ClaimOrchestrator",
        sla=SLASpec(stage="triage_routing", target_hours=4, internal_target_hours=0.5, warning_pct=75, escalation_role="claims_manager"),
        retry_strategy=RetryStrategySpec(max_retries=2, base_delay_ms=200, backoff_multiplier=2.0, max_delay_ms=2000),
        human_escalation_criteria=[
            "Third-party bodily injury or fatality (mandatory Legal/TP track)",
            "EV high-voltage traction battery impact",
            "Unmatched policy or ambiguous coverage",
        ],
        next_states=[
            ClaimStatus.FAST_TRACK.value,
            ClaimStatus.SURVEY_REQUIRED.value,
            ClaimStatus.INVESTIGATION_REQUIRED.value,
            ClaimStatus.HUMAN_REVIEW.value,
        ],
        triage_substates=[
            ClaimStatus.FAST_TRACK.value,
            ClaimStatus.SURVEY_REQUIRED.value,
            ClaimStatus.INVESTIGATION_REQUIRED.value,
            ClaimStatus.HUMAN_REVIEW.value,
        ],
    ),
    ClaimStatus.FAST_TRACK.value: StateContractSpec(
        state=ClaimStatus.FAST_TRACK.value,
        display_name="Triage -> Fast Track",
        phase="3. Triage Branch",
        description="Low-risk Own Damage (< INR 50,000, non-EV, no TP injury, zero fraud alerts) eligible for automated straight-through visual assessment without physical surveyor delay.",
        entry_conditions=["estimated_loss_inr < 50000", "injury_or_fatality == false", "ev_battery_impacted == false"],
        required_data=["triage_summary", "coverage_factsheet"],
        allowed_actions=["notify_network_garage", "schedule_conditional_damage_assessment", "schedule_parallel_fraud_analysis"],
        exit_conditions=["Assessment wave scheduled or escalated if supplement pushes loss >= INR 50,000"],
        responsible_agent_or_service="ClaimOrchestrator + DamageAssessmentAgent",
        sla=SLASpec(stage="fast_track_assessment", target_hours=12, internal_target_hours=2, warning_pct=75, escalation_role="claims_handler"),
        retry_strategy=RetryStrategySpec(max_retries=2, base_delay_ms=200, backoff_multiplier=2.0, max_delay_ms=2000),
        human_escalation_criteria=["Supplement quote crosses INR 50,000 IRDAI mandatory survey threshold", "Fraud signal detected"],
        next_states=[ClaimStatus.ASSESSMENT.value, ClaimStatus.SURVEY_REQUIRED.value, ClaimStatus.INVESTIGATION_REQUIRED.value, ClaimStatus.HUMAN_REVIEW.value],
    ),
    ClaimStatus.SURVEY_REQUIRED.value: StateContractSpec(
        state=ClaimStatus.SURVEY_REQUIRED.value,
        display_name="Triage -> Survey Required",
        phase="3. Triage Branch",
        description="IRDAI 2024 mandatory surveyor branch (>= INR 50,000, EV HV, fire/flood/theft, or total loss). Dispatches licensed IIISLA surveyor and EV-capable garage.",
        entry_conditions=["requires_mandatory_survey == true"],
        required_data=["triage_summary", "verified_provider_roster", "incident_location"],
        allowed_actions=["schedule_licensed_surveyor", "notify_garage_with_ev_safety", "dispatch_towing", "start_15d_survey_sla"],
        exit_conditions=["Verified licensed IIISLA surveyor assigned", "Assessment & Fraud parallel wave ready"],
        responsible_agent_or_service="ProviderCoordinationAgent + ClaimOrchestrator",
        sla=SLASpec(stage="survey_report_submission", target_hours=360, internal_target_hours=168, warning_pct=80, escalation_role="claims_manager", daily_penalty_inr="500.00"),
        retry_strategy=RetryStrategySpec(max_retries=2, base_delay_ms=250, backoff_multiplier=2.0, max_delay_ms=3000),
        human_escalation_criteria=["Zero available licensed IIISLA surveyors in city", "Surveyor report overdue past 15-day IRDAI SLA", "No EV-certified garage available"],
        next_states=[ClaimStatus.ASSESSMENT.value, ClaimStatus.INVESTIGATION_REQUIRED.value, ClaimStatus.HUMAN_REVIEW.value],
    ),
    ClaimStatus.INVESTIGATION_REQUIRED.value: StateContractSpec(
        state=ClaimStatus.INVESTIGATION_REQUIRED.value,
        display_name="Triage -> Investigation Required",
        phase="3. Triage Branch",
        description="SIU or Legal/TP specialist branch triggered by entity-network fraud leads, duplicate evidence SHA-256 reuse, early inception anomalies, or TP bodily injury.",
        entry_conditions=["Open SIU fraud alert OR TP bodily injury/fatality OR confirmed duplicate claim collision"],
        required_data=["fraud_alerts (with benign explanations)", "entity_graph", "police_fir / medical_records (if TP)"],
        allowed_actions=["assign_siu_investigator", "assign_legal_tp_specialist", "restrict_l1_approval", "disposition_fraud_alert"],
        exit_conditions=["All open fraud alerts dispositioned OR Legal/TP review recorded"],
        responsible_agent_or_service="FraudIntelligenceAgent + SIU Investigator / Legal TP Specialist",
        sla=SLASpec(stage="siu_or_legal_investigation", target_hours=120, internal_target_hours=48, warning_pct=75, escalation_role="claims_manager"),
        retry_strategy=RetryStrategySpec(max_retries=1, base_delay_ms=300, backoff_multiplier=2.0, max_delay_ms=3000),
        human_escalation_criteria=["Any fraud indicator requires human SIU disposition", "Substantiated fraud triggers compensation/repudiation review"],
        next_states=[ClaimStatus.ASSESSMENT.value, ClaimStatus.HUMAN_REVIEW.value, ClaimStatus.DECLINED_PARTIAL.value],
    ),
    ClaimStatus.HUMAN_REVIEW.value: StateContractSpec(
        state=ClaimStatus.HUMAN_REVIEW.value,
        display_name="Human Review (Hold / Escalation Gate)",
        phase="Exception / Governance Gate",
        description="Paused human authority gate for document mismatches, prompt injections, blurry photo recapture, DLQ escalations, or coverage ambiguities. Workflow resumes cleanly from checkpoint once resolved.",
        entry_conditions=["Any blocking rework, prompt injection, mismatch, DLQ exhaustion, or explicit workflow pause"],
        required_data=["open_claim_tasks", "rework_queue or dlq_records"],
        allowed_actions=["verify_extracted_fact", "upload_recaptured_photos", "resolve_rework", "replay_dlq_task", "resume_orchestration", "run_compensation"],
        exit_conditions=["All blocking rework requests resolved", "Open escalation/clarification tasks completed"],
        responsible_agent_or_service="Human Claims Handler / Claims Manager / Legal TP + ClaimOrchestrator",
        sla=SLASpec(stage="human_clarification_sla", target_hours=48, internal_target_hours=12, warning_pct=75, escalation_role="claims_manager"),
        retry_strategy=RetryStrategySpec(max_retries=0, base_delay_ms=0, backoff_multiplier=1.0, max_delay_ms=0, dlq_on_exhaustion=False),
        human_escalation_criteria=["SLA breach on customer clarification or DLQ escalation requires Claims Manager override"],
        next_states=[
            ClaimStatus.VALIDATION.value,
            ClaimStatus.TRIAGE.value,
            ClaimStatus.ASSESSMENT.value,
            ClaimStatus.ESTIMATE_VALIDATION.value,
            ClaimStatus.SETTLEMENT_PENDING_APPROVAL.value,
            ClaimStatus.DECLINED_PARTIAL.value,
        ],
    ),
    ClaimStatus.ASSESSMENT.value: StateContractSpec(
        state=ClaimStatus.ASSESSMENT.value,
        display_name="Assessment",
        phase="4. Assessment & Parallel Fraud",
        description="Conditional Damage Assessment (requires uploaded photos + vehicle details) executed in parallel with Fraud Analysis over claim & evidence.",
        entry_conditions=["Claim triaged (FAST_TRACK / SURVEY_REQUIRED / cleared INVESTIGATION_REQUIRED)"],
        required_data=["vehicle_id / details", "damage_photo evidence (for conditional vision)", "claim + evidence"],
        allowed_actions=[
            "run_conditional_damage_assessment",
            "run_parallel_fraud_analysis",
            "request_guided_photo_recapture",
            "submit_signed_survey_report",
        ],
        exit_conditions=["Damage observations logged (or recapture resolved)", "Parallel fraud analysis completed without unresolved hold"],
        responsible_agent_or_service="DamageAssessmentAgent (Conditional) + FraudIntelligenceAgent (Parallel)",
        sla=SLASpec(stage="assessment_completion", target_hours=48, internal_target_hours=12, warning_pct=75, escalation_role="claims_manager"),
        retry_strategy=RetryStrategySpec(max_retries=2, base_delay_ms=300, backoff_multiplier=2.0, max_delay_ms=5000),
        human_escalation_criteria=["Blurry/dark photos or >3 missing angles", "High-severity SIU indicator", "Exhausted vision model timeouts -> DLQ"],
        next_states=[ClaimStatus.ESTIMATE_VALIDATION.value, ClaimStatus.INVESTIGATION_REQUIRED.value, ClaimStatus.HUMAN_REVIEW.value],
    ),
    ClaimStatus.ESTIMATE_VALIDATION.value: StateContractSpec(
        state=ClaimStatus.ESTIMATE_VALIDATION.value,
        display_name="Estimate Validation",
        phase="4. Estimate & Benchmarking",
        description="Benchmarks garage repair estimate against OEM/OES rate cards, flags duplicate lines and >12% variances, and emits blocking ReworkRequests if repair-vs-replace conflicts arise.",
        entry_conditions=["Damage assessment completed", "Garage itemized estimate submitted"],
        required_data=["estimate_lines", "rate_card (RC-IN-2026-DEMO-V1)", "damage_assessments"],
        allowed_actions=[
            "benchmark_oem_rate_card",
            "detect_duplicate_estimate_lines",
            "emit_rework_to_damage_assessment",
            "review_estimate_line",
        ],
        exit_conditions=["Estimate lines reviewed/benchmarked", "No open blocking rework requests", "Signed survey report attached if mandatory survey"],
        responsible_agent_or_service="EstimateValidationAgent + Adjuster / Surveyor",
        sla=SLASpec(stage="estimate_validation_sla", target_hours=48, internal_target_hours=12, warning_pct=75, escalation_role="claims_manager"),
        retry_strategy=RetryStrategySpec(max_retries=2, base_delay_ms=250, backoff_multiplier=2.0, max_delay_ms=3000),
        human_escalation_criteria=["Duplicate lines or >12% OEM rate variance", "Repair-vs-replace conflict with visual damage", "Supplement pushes total >= INR 50k"],
        next_states=[ClaimStatus.SETTLEMENT_PENDING_APPROVAL.value, ClaimStatus.ASSESSMENT.value, ClaimStatus.HUMAN_REVIEW.value],
    ),
    ClaimStatus.SETTLEMENT_PENDING_APPROVAL.value: StateContractSpec(
        state=ClaimStatus.SETTLEMENT_PENDING_APPROVAL.value,
        display_name="Settlement Pending Approval",
        phase="5. Settlement & DoA Gate",
        description="Deterministic Python Decimal settlement calculated across 4 scenarios (within IDV & CTL thresholds) and held at mandatory Maker-Checker DoA human approval gate.",
        entry_conditions=["Assessment, coverage, validated estimate, and fraud checks all satisfied"],
        required_data=["policy (IDV, deductibles, addons)", "vehicle_first_registration_date", "approved_estimate_lines"],
        allowed_actions=["calculate_decimal_scenarios", "generate_doa_approval_task", "submit_checker_decision", "trigger_compensation_on_rejection"],
        exit_conditions=["Independent Checker approves within IN-DOA-MATRIX-2026 authority tier (maker_user_id != checker_user_id)"],
        responsible_agent_or_service="SettlementCalculator + SettlementRecommendationAgent + Independent Human Checker",
        sla=SLASpec(stage="claim_decision", target_hours=168, internal_target_hours=48, warning_pct=75, escalation_role="claims_manager"),
        retry_strategy=RetryStrategySpec(max_retries=2, base_delay_ms=200, backoff_multiplier=2.0, max_delay_ms=2000),
        human_escalation_criteria=[
            "Always gated on independent human Checker approval",
            "Net > INR 75,000, EV battery, CTL total loss, or open SIU escalates to L2 Claims Manager",
            "TP injury escalates to L3 Legal/TP Specialist",
        ],
        next_states=[ClaimStatus.APPROVED.value, ClaimStatus.HUMAN_REVIEW.value, ClaimStatus.DECLINED_PARTIAL.value],
    ),
    ClaimStatus.APPROVED.value: StateContractSpec(
        state=ClaimStatus.APPROVED.value,
        display_name="Approved",
        phase="5. Settlement Approved",
        description="Settlement approved by independent Maker-Checker authority. Unlocks Finance-gated payment execution.",
        entry_conditions=["Approval.decision == 'approved'", "Settlement.approval_status == 'approved'"],
        required_data=["approved_settlement_id", "checker_user_id", "authority_rule_version"],
        allowed_actions=["validate_payee_bank_penny_drop", "initiate_idempotent_payment", "update_repair_milestone"],
        exit_conditions=["Finance Approver initiates payment with Idempotency-Key"],
        responsible_agent_or_service="Finance Approver + PaymentGatewayAdapter",
        sla=SLASpec(stage="payout_initiation", target_hours=48, internal_target_hours=12, warning_pct=75, escalation_role="finance_approver"),
        retry_strategy=RetryStrategySpec(max_retries=2, base_delay_ms=500, backoff_multiplier=2.0, max_delay_ms=5000),
        human_escalation_criteria=["Bank penny-drop mismatch", "Finance role authority required"],
        next_states=[ClaimStatus.PAYMENT_PENDING.value, ClaimStatus.HUMAN_REVIEW.value],
    ),
    ClaimStatus.PAYMENT_PENDING.value: StateContractSpec(
        state=ClaimStatus.PAYMENT_PENDING.value,
        display_name="Payment Pending",
        phase="6. Payment",
        description="Approval-gated payment instruction dispatched idempotently to bank/payment gateway. Protects against double debit on timeouts.",
        entry_conditions=["Claim is APPROVED", "Finance Approver executed payment with Idempotency-Key"],
        required_data=["payment_id", "idempotency_key", "gateway_reference", "amount_inr"],
        allowed_actions=["replay_idempotent_payment", "transition_to_reconciliation", "hold_timed_out_payment"],
        exit_conditions=["Gateway reference recorded (confirmed or timeout_reconcile_pending)"],
        responsible_agent_or_service="PaymentGatewayAdapter + ClaimOrchestrator",
        sla=SLASpec(stage="payment_settlement", target_hours=24, internal_target_hours=4, warning_pct=75, escalation_role="finance_approver"),
        retry_strategy=RetryStrategySpec(max_retries=3, base_delay_ms=500, backoff_multiplier=2.0, max_delay_ms=8000),
        human_escalation_criteria=["Gateway timeout -> freeze blind retry and escalate for safe UTR reconciliation"],
        next_states=[ClaimStatus.PAYMENT_RECONCILIATION.value, ClaimStatus.HUMAN_REVIEW.value],
    ),
    ClaimStatus.PAYMENT_RECONCILIATION.value: StateContractSpec(
        state=ClaimStatus.PAYMENT_RECONCILIATION.value,
        display_name="Payment Reconciliation",
        phase="6. Reconciliation & Handover",
        description="Verifies UTR confirmation parity against approved settlement amount, resolves gateway timeouts safely, and tracks garage handover before QA closure.",
        entry_conditions=["Payment row created in PAYMENT_PENDING"],
        required_data=["payment_id", "gateway_reference", "settlement_net_payable_inr"],
        allowed_actions=["reconcile_gateway_utr", "update_repair_milestone", "run_qa_closure_checks", "compensate_failed_payout"],
        exit_conditions=["Payment.status == 'confirmed'", "Zero open grievances", "All QA compliance controls passed"],
        responsible_agent_or_service="ReconciliationService + QAComplianceAgent + ClaimOrchestrator",
        sla=SLASpec(stage="payment_reconciliation_sla", target_hours=48, internal_target_hours=12, warning_pct=75, escalation_role="finance_approver"),
        retry_strategy=RetryStrategySpec(max_retries=3, base_delay_ms=500, backoff_multiplier=2.0, max_delay_ms=8000),
        human_escalation_criteria=["Unreconciled UTR mismatch", "Open policyholder grievance blocks closure"],
        next_states=[ClaimStatus.CLOSED.value, ClaimStatus.HUMAN_REVIEW.value],
    ),
    ClaimStatus.CLOSED.value: StateContractSpec(
        state=ClaimStatus.CLOSED.value,
        display_name="Closed",
        phase="7. Closure & Audit Retention",
        description="Terminal audited state after QA compliance verification, confirmed payment UTR, zero open grievances, and customer closure communication.",
        entry_conditions=[
            "QAComplianceAgent closure_eligible == true",
            "Confirmed payment UTR or formal partial/decline disposition",
            "Zero open grievances or unresolved doc mismatches",
        ],
        required_data=["qa_checklist", "audit_readiness_score == 1.0", "confirmed_payment_or_declined"],
        allowed_actions=["retain_immutable_audit_ledger", "send_closure_notification", "reopen_claim_if_warranted"],
        exit_conditions=["Claim archived (only reopenable by Claims Manager / Admin via REOPENED state)"],
        responsible_agent_or_service="QAComplianceAgent + CustomerCommunicationAgent + ClaimOrchestrator",
        sla=SLASpec(stage="closure_archive", target_hours=24, internal_target_hours=1, warning_pct=90, escalation_role="auditor"),
        retry_strategy=RetryStrategySpec(max_retries=1, base_delay_ms=200, backoff_multiplier=1.0, max_delay_ms=500, dlq_on_exhaustion=False),
        human_escalation_criteria=["Post-closure grievance or supplement triggers formal Reopen workflow"],
        next_states=[ClaimStatus.REOPENED.value],
    ),
}


def compute_exponential_backoff_ms(attempt: int, strategy: RetryStrategySpec) -> int:
    """Computes bounded exponential backoff in milliseconds for attempt >= 1."""
    if attempt <= 0:
        return 0
    raw = strategy.base_delay_ms * (strategy.backoff_multiplier ** (attempt - 1))
    capped = min(int(round(raw)), strategy.max_delay_ms)
    if strategy.jitter_pct > 0 and capped > 0:
        jitter_span = int(round(capped * strategy.jitter_pct))
        if jitter_span > 0:
            capped = max(1, capped + random.randint(-jitter_span, jitter_span))
    return min(capped, strategy.max_delay_ms)


def evaluate_state_entry_conditions(db: Session, claim: Claim, target_state: str) -> tuple[bool, list[str]]:
    """Deterministic entry guard evaluator for orchestrator-owned state transitions."""
    unmet: list[str] = []
    if target_state == ClaimStatus.REGISTERED.value:
        if not claim.policy_number_input or not claim.vehicle_reg_input:
            unmet.append("Missing policy_number_input or vehicle_reg_input")
    elif target_state == ClaimStatus.APPROVED.value:
        approved = db.query(Approval).filter(Approval.claim_id == claim.id, Approval.decision == "approved").first()
        stl = db.query(Settlement).filter(Settlement.claim_id == claim.id, Settlement.approval_status == "approved").first()
        if not approved or not stl:
            unmet.append("Independent Maker-Checker Approval & approved Settlement required before APPROVED")
    elif target_state in {ClaimStatus.PAYMENT_PENDING.value, ClaimStatus.PAYMENT_INITIATED.value}:
        stl = db.query(Settlement).filter(Settlement.claim_id == claim.id, Settlement.approval_status == "approved").first()
        if not stl:
            unmet.append("Approved Settlement required before PAYMENT_PENDING")
    elif target_state == ClaimStatus.PAYMENT_RECONCILIATION.value:
        pmt = db.query(Payment).filter(Payment.claim_id == claim.id).first()
        if not pmt:
            unmet.append("Payment record required before PAYMENT_RECONCILIATION")
    elif target_state == ClaimStatus.CLOSED.value:
        pmt = db.query(Payment).filter(Payment.claim_id == claim.id, Payment.status == "confirmed").first()
        open_griev = db.query(Grievance).filter(Grievance.claim_id == claim.id, Grievance.status != "resolved").first()
        mismatch = (
            db.query(ExtractedFact)
            .filter(ExtractedFact.claim_id == claim.id, ExtractedFact.validation_status == "mismatch")
            .first()
        )
        signed_surv = (
            db.query(SurveyAssignment)
            .filter(SurveyAssignment.claim_id == claim.id, SurveyAssignment.signed_by_surveyor.is_(True))
            .first()
        )
        if not pmt and claim.status != ClaimStatus.DECLINED_PARTIAL.value:
            unmet.append("Confirmed payment UTR required before CLOSED")
        if open_griev:
            unmet.append("Open policyholder grievance blocks CLOSED")
        if mismatch:
            unmet.append("Unresolved document fact mismatch blocks CLOSED")
        if claim.requires_mandatory_survey and not signed_surv:
            unmet.append("Signed IIISLA surveyor report required before CLOSED")

    return (len(unmet) == 0, unmet)


def evaluate_state_exit_conditions(db: Session, claim: Claim, current_state: str) -> tuple[bool, list[str]]:
    """Deterministic exit guard evaluator indicating whether a claim is ready to leave its current state."""
    unmet: list[str] = []
    wf = claim.workflow_state or {}
    statuses = wf.get("stage_statuses", {})
    if current_state == ClaimStatus.VALIDATION.value:
        if statuses.get("document_intelligence") != "completed":
            unmet.append("document_extraction not completed")
        if statuses.get("coverage_intelligence") != "completed":
            unmet.append("policy_validation not completed")
        if db.query(Evidence).filter(Evidence.claim_id == claim.id, Evidence.prompt_injection_flagged.is_(True)).count() > 0:
            if db.query(ExtractedFact).filter(ExtractedFact.claim_id == claim.id, ExtractedFact.validation_status == "mismatch").count() > 0:
                unmet.append("Unresolved document mismatch / quarantined prompt injection")
    elif current_state == ClaimStatus.ASSESSMENT.value:
        dmg_cnt = db.query(DamageAssessment).filter(DamageAssessment.claim_id == claim.id).count()
        if dmg_cnt == 0 and statuses.get("damage_assessment") != "completed":
            unmet.append("Damage assessment observations not recorded")
    elif current_state == ClaimStatus.ESTIMATE_VALIDATION.value:
        est_cnt = db.query(Estimate).filter(Estimate.claim_id == claim.id).count()
        if est_cnt == 0:
            unmet.append("Garage repair estimate not submitted")
    elif current_state == ClaimStatus.INVESTIGATION_REQUIRED.value:
        open_alerts = (
            db.query(FraudAlert)
            .filter(FraudAlert.claim_id == claim.id, FraudAlert.status.in_(["new", "assigned", "investigating"]))
            .count()
        )
        if open_alerts > 0:
            unmet.append(f"{open_alerts} open SIU alert(s) pending disposition")
    elif current_state == ClaimStatus.SETTLEMENT_PENDING_APPROVAL.value:
        approved = db.query(Approval).filter(Approval.claim_id == claim.id, Approval.decision == "approved").first()
        if not approved:
            unmet.append("Independent Checker approval pending")
    return (len(unmet) == 0, unmet)


def describe_workflow_model() -> dict[str, Any]:
    """Serializable summary of the canonical state machine, state contracts, and task scheduling DAG."""
    return {
        "model_name": "Enterprise Claim Orchestration Workflow Model",
        "version": "2.0.0",
        "recommended_flow": [
            "SUBMITTED",
            "REGISTERED",
            "VALIDATION",
            "TRIAGE -> [FAST_TRACK | SURVEY_REQUIRED | INVESTIGATION_REQUIRED | HUMAN_REVIEW]",
            "ASSESSMENT (Damage Conditional + Fraud Parallel)",
            "ESTIMATE_VALIDATION",
            "SETTLEMENT_PENDING_APPROVAL",
            "APPROVED",
            "PAYMENT_PENDING",
            "PAYMENT_RECONCILIATION",
            "CLOSED",
        ],
        "states": [spec.model_dump() for spec in WORKFLOW_STATE_SPECS.values()],
        "task_dag": [t.model_dump() for t in TASK_DAG_SPECS],
    }
