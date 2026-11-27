from __future__ import annotations

from packages.contracts.agents import AgentContractSpec

ORCHESTRATION_ORDER: list[str] = [
    "fnol_concierge",
    "document_intelligence",
    "coverage_intelligence",
    "claim_triage",
    "provider_coordination",
    "damage_assessment",
    "estimate_validation",
    "fraud_intelligence",
    "settlement_recommendation",
    "customer_communication",
    "qa_compliance",
]

# Cross-cutting operations agents. They run on a schedule / on demand over the claims portfolio, not as a
# per-claim stage in the post-FNOL DAG, so they are deliberately not part of ORCHESTRATION_ORDER.
OPERATIONS_AGENTS: list[str] = [
    "sla_intelligence",
]

AGENT_CAPABILITY_CONTRACTS: dict[str, AgentContractSpec] = {
    "fnol_concierge": AgentContractSpec(
        agent_name="fnol_concierge",
        display_name="FNOL Concierge",
        stage="1. FNOL Intake",
        operational_responsibility=(
            "Captures structured motor claim intimations across web, mobile, WhatsApp, and voice channels "
            "in the customer's preferred language without blocking registration for missing documents."
        ),
        required_capabilities=[
            "Voice, WhatsApp, mobile/web intake",
            "Multilingual conversations (en-IN, hi-IN, mr-IN, ta-IN, kn-IN)",
            "Accident location & landmark capture",
            "Structured incident capture (drivable status, airbags, injury, towing, EV HV)",
        ],
        input_contract={
            "policy_number": "string (required)",
            "vehicle_reg": "string (required)",
            "intake_channel": "web | mobile | whatsapp | voice",
            "locale": "BCP-47 language code (en-IN, hi-IN, mr-IN, ta-IN, kn-IN)",
            "incident_location": "string",
            "incident_description": "string (PII-masked)",
            "vehicle_immobile": "boolean",
            "towing_needed": "boolean",
        },
        output_contract={
            "registration_allowed": "boolean (always true per IRDAI 2024)",
            "normalised_channel": "string",
            "structured_incident": "object (location, peril, drivable_status, ev_hv, injury)",
            "localized_acknowledgement": "string",
            "recommended_checklist": "list[string]",
        },
        allowed_tools=[
            "create_intimation",
            "policy_lookup",
            "faq_retrieval",
            "request_upload",
            "create_claim_task",
            "request_documents",
            "dispatch_towing",
            "send_customer_update",
        ],
        authorised_actions=[
            "create_claim_task",
            "request_documents",
            "dispatch_towing",
            "send_customer_update",
        ],
        prohibited_actions=[
            "decide_coverage",
            "repudiate_claim",
            "approve_settlement",
            "initiate_payment",
            "mutate_claim_state_directly",
        ],
        depends_on=[],
        can_request_rework_from=[],
        human_gate_condition="Never blocks intake; missing details create follow-up tasks.",
        timeout_seconds=12,
        max_retries=2,
    ),
    "document_intelligence": AgentContractSpec(
        agent_name="document_intelligence",
        display_name="Document Intelligence",
        stage="2. Validation",
        operational_responsibility=(
            "Extracts structured fields from Policy, RC, DL, FIR, and estimates with per-field confidence, "
            "reconciles multiple documents, quarantines prompt injections, and records full evidence provenance."
        ),
        required_capabilities=[
            "Multi-document reconciliation (Policy vs RC vs DL vs FNOL)",
            "Confidence scores per field",
            "Conflicting data detection across documents",
            "Evidence provenance (SHA-256, document ID, page, bounding box)",
        ],
        input_contract={
            "extracted_facts": "list[object] with field_name, confidence, bbox, validation_status",
            "evidences": "list[object] with doc_type, sha256, filename",
            "prompt_injection_flagged": "boolean",
        },
        output_contract={
            "reconciliation_status": "reconciled | conflicts_detected | pending_documents",
            "field_confidences": "dict[field_name, float]",
            "conflicts": "list[object]",
            "provenance_index": "list[object]",
        },
        allowed_tools=[
            "evidence_read",
            "ocr_extract",
            "schema_validate",
            "duplicate_check",
            "reconcile_documents",
            "create_claim_task",
            "request_documents",
        ],
        authorised_actions=[
            "create_claim_task",
            "request_documents",
        ],
        prohibited_actions=[
            "overwrite_verified_facts",
            "approve_settlement",
            "initiate_payment",
            "mutate_claim_state_directly",
        ],
        depends_on=["fnol_concierge"],
        can_request_rework_from=["fnol_concierge"],
        human_gate_condition="Cross-document conflict, RC/Policy mismatch, or prompt injection forces NEEDS_HUMAN.",
        timeout_seconds=15,
        max_retries=2,
    ),
    "coverage_intelligence": AgentContractSpec(
        agent_name="coverage_intelligence",
        display_name="Coverage Intelligence",
        stage="2. Validation",
        operational_responsibility=(
            "Builds a clause-cited policy coverage matrix covering insured perils, exclusions, add-ons, "
            "deductibles, and coverage ambiguities without ever autonomously repudiating a claim."
        ),
        required_capabilities=[
            "Policy coverage matrix (OD, TP, Zero Dep, Consumables, RSA, EV HV, CTL)",
            "Exclusions verification checklist",
            "Add-ons & deductibles mapping",
            "Exact clause & page citations via Hybrid RAG",
            "Coverage ambiguity detection & rework requests",
        ],
        input_contract={
            "peril_cause": "string",
            "policy_status": "string",
            "period_valid": "boolean",
            "addons": "dict[string, boolean]",
            "has_document_mismatch": "boolean",
        },
        output_contract={
            "coverage_matrix": "list[object]",
            "deductibles_summary": "object (compulsory, voluntary)",
            "exclusions_checklist": "list[object]",
            "ambiguities": "list[string]",
            "retrieved_clauses": "list[object]",
        },
        allowed_tools=[
            "policy_read",
            "policy_rag",
            "deterministic_coverage_rules",
            "create_claim_task",
            "request_rework",
        ],
        authorised_actions=[
            "create_claim_task",
        ],
        prohibited_actions=[
            "repudiate_claim",
            "waive_statutory_exclusions",
            "initiate_payment",
            "mutate_claim_state_directly",
        ],
        depends_on=["fnol_concierge"],
        can_request_rework_from=["document_intelligence", "fnol_concierge"],
        human_gate_condition="Period lapse, inactive policy, TP injury/fatality, or document conflict escalates to Human/Legal.",
        timeout_seconds=15,
        max_retries=2,
    ),
    "claim_triage": AgentContractSpec(
        agent_name="claim_triage",
        display_name="Claim Triage",
        stage="3. Triage",
        operational_responsibility=(
            "Evaluates explainable LOW / MEDIUM / HIGH claim risk, operational path "
            "(fast_track, standard, complex_investigation), severity, injury/TP liability, EV battery, "
            "drivable status, and regulatory thresholds to assign queues and automation eligibility."
        ),
        required_capabilities=[
            "Explainable 3-tier risk classification (LOW / MEDIUM / HIGH) & operational path routing",
            "Injury / fatality, multi-vehicle & TP liability specialist escalation",
            "Vehicle drivable status, EV battery safety & immediate towing triage",
            "Priority routing (P1_URGENT to P4_FAST_TRACK), automated fast-track eligibility & IRDAI ₹50k gate",
        ],
        input_contract={
            "estimated_loss_inr": "decimal string",
            "injury_or_fatality": "boolean",
            "multiple_vehicles_involved": "boolean",
            "ev_battery_impacted": "boolean",
            "vehicle_immobile": "boolean",
            "missing_documents": "list[string]",
            "legal_dispute": "boolean",
            "peril_cause": "string",
        },
        output_contract={
            "risk_tier": "LOW | MEDIUM | HIGH",
            "operational_path": "fast_track | standard | complex_investigation",
            "risk_score": "integer 0-100",
            "risk_drivers": "list[object]",
            "low_risk_criteria_check": "object",
            "automation_eligibility": "object",
            "severity_band": "low | medium | high | critical",
            "complexity_tier": "string",
            "injury_status": "string",
            "liability_indicator": "string",
            "vehicle_drivable": "string",
            "routing_priority": "P1_URGENT | P2_HIGH | P3_NORMAL | P4_FAST_TRACK",
            "recommended_queue": "string",
            "requires_mandatory_survey": "boolean",
        },
        allowed_tools=[
            "claim_facts_read",
            "triage_rules_read",
            "queue_recommend",
            "create_claim_task",
            "dispatch_towing",
        ],
        authorised_actions=[
            "create_claim_task",
            "dispatch_towing",
        ],
        prohibited_actions=[
            "use_protected_demographic_traits",
            "approve_settlement",
            "auto_reject_on_fraud_score",
            "mutate_claim_state_directly",
        ],
        depends_on=["document_intelligence", "coverage_intelligence"],
        can_request_rework_from=["coverage_intelligence", "fnol_concierge"],
        human_gate_condition="HIGH risk (injury/TP, multi-vehicle, EV HV, SIU fraud, significant loss, disputes) routes to specialist human-led investigation; LOW risk <= ₹25k is straight-through eligible.",
        timeout_seconds=10,
        max_retries=2,
    ),
    "provider_coordination": AgentContractSpec(
        agent_name="provider_coordination",
        display_name="Provider & Ecosystem Coordination",
        stage="5. Investigation & Dispatch",
        operational_responsibility=(
            "Orchestrates across the claims ecosystem: surveyor availability & IIISLA license verification, "
            "multi-factor assignment (geography, skill, capacity, SLA), garage selection & customer preference protection, "
            "parts availability, towing, vehicle pickup/delivery, inspection scheduling/rescheduling, customer notifications, "
            "surveyor report follow-ups, and repair completion confirmation — explaining every selection and blocking "
            "unauthorized overrides of customer choice or contractual rules."
        ),
        required_capabilities=[
            "Surveyor availability, IIISLA license verification & geography/skill/capacity/SLA assignment",
            "Customer preferred garage protection & contractual/authorization override guardrails",
            "Parts availability check, towing dispatch & vehicle pickup/delivery scheduling",
            "Inspection scheduling, rescheduling, surveyor report follow-ups, customer updates & repair completion confirmation",
        ],
        input_contract={
            "requires_mandatory_survey": "boolean",
            "ev_capable_required": "boolean",
            "incident_location": "string (geography matching)",
            "preferred_garage_id": "string | null",
            "selected_garage_id": "string | null (optional override request)",
            "override_customer_preference": "boolean",
            "override_contract_rule": "boolean",
            "override_reason": "string",
            "towing_needed": "boolean",
            "pickup_required": "boolean",
            "delivery_required": "boolean",
            "available_providers": "list[object]",
        },
        output_contract={
            "recommended_surveyor": "object | null",
            "recommended_garage": "object | null",
            "surveyor_license_verified": "boolean",
            "selection_explanation": "string (why providers were selected)",
            "score_breakdown": "object (geography, skill, capacity, SLA, rating)",
            "customer_preference_honoured": "boolean",
            "override_blocked": "boolean",
            "parts_availability": "object (status + line items)",
            "inspection_schedule": "object (status, scheduled_at, reschedule_count)",
            "logistics": "object (towing, pickup_delivery_status)",
            "repair_status": "object (milestone, completion_confirmed)",
            "surveyor_followup": "object (count, status)",
            "sla_deadlines": "object",
        },
        allowed_tools=[
            "verified_roster_read",
            "verify_surveyor_license",
            "provider_scorecard",
            "schedule_notify",
            "schedule_inspection",
            "reschedule_inspection",
            "notify_garage",
            "check_parts_availability",
            "dispatch_towing",
            "schedule_pickup_delivery",
            "send_surveyor_followup",
            "confirm_repair_completion",
            "send_customer_update",
            "create_claim_task",
        ],
        authorised_actions=[
            "schedule_inspection",
            "reschedule_inspection",
            "notify_garage",
            "check_parts_availability",
            "dispatch_towing",
            "schedule_pickup_delivery",
            "send_surveyor_followup",
            "confirm_repair_completion",
            "send_customer_update",
            "create_claim_task",
        ],
        prohibited_actions=[
            "assign_unlicensed_surveyor",
            "override_ev_safety_protocol",
            "override_customer_choice_without_authorization",
            "override_contractual_rules_without_authorization",
            "mutate_claim_state_directly",
        ],
        depends_on=["claim_triage"],
        can_request_rework_from=["claim_triage"],
        human_gate_condition="Unlicensed roster, zero city capacity, or unauthorized preference/contract override escalates to Claims Manager.",
        timeout_seconds=12,
        max_retries=2,
    ),
    "damage_assessment": AgentContractSpec(
        agent_name="damage_assessment",
        display_name="Damage Assessment",
        stage="4. Assessment",
        operational_responsibility=(
            "Executes a 10-step visual damage inspection workflow: validates photo quality (good/poor/recapture), "
            "detects vehicle make/model/variant and damaged regions with bounding boxes, classifies components with "
            "per-component confidence (never overclaiming beyond repair from overall image score), compares damage "
            "across angles, detects inconsistencies, estimates parts & labour, requests missing photos, and routes "
            "uncertain cases to a human assessor."
        ),
        required_capabilities=[
            "Vehicle detection (make, model, variant) & damaged region bounding-box evidence",
            "Per-component confidence calibration & repair/replace/uncertain recommendation",
            "Visible damage vs possible hidden damage separation",
            "Cross-photo comparison & FNOL-vs-photo inconsistency detection",
            "Rate-card parts & labour pre-estimation + guided additional photo requests + human assessor routing",
        ],
        input_contract={
            "assessment_payload": "object from Damage AI service (or incident_description + image_records + vehicle_info)",
            "image_records": "list[object] with filename, image_angle, image_quality_status, sha256",
        },
        output_contract={
            "vehicle": "object (make, model, variant, detection_confidence)",
            "observations": "list[object] (location, component, severity, repairability, visible/hidden damage, component_confidence, bbox evidence)",
            "cross_photo_comparison": "list[object]",
            "inconsistencies": "list[object]",
            "parts_labour_estimate": "object (OEM/OES parts, labour, paint)",
            "additional_photo_requests": "list[object]",
            "human_assessor_routing": "object (route_to_human_assessor, trigger_reasons)",
            "visual_workflow_steps": "list[object] (10-step workflow trace)",
        },
        allowed_tools=[
            "vision_model",
            "image_quality_check",
            "vehicle_taxonomy",
            "bbox_localizer",
            "cross_photo_compare",
            "parts_labour_estimator",
            "request_documents",
            "create_claim_task",
            "request_rework",
        ],
        authorised_actions=[
            "request_documents",
            "create_claim_task",
        ],
        prohibited_actions=[
            "confirm_hidden_structural_damage",
            "authorise_ev_battery_replacement",
            "override_low_component_confidence_with_overall_image_score",
            "mutate_claim_state_directly",
        ],
        depends_on=["claim_triage"],
        can_request_rework_from=["document_intelligence"],
        human_gate_condition="Poor/recapture photos, component confidence < 0.72, uncertain repairability, inconsistencies, or EV HV impact routes to human assessor.",
        timeout_seconds=20,
        max_retries=2,
    ),
    "estimate_validation": AgentContractSpec(
        agent_name="estimate_validation",
        display_name="Estimate Validation",
        stage="4. Assessment",
        operational_responsibility=(
            "Validates garage repair quotes against OEM/OES parts, labour, and paint benchmarks, "
            "detecting inflated lines, duplicate parts, and repair-vs-replacement conflicts."
        ),
        required_capabilities=[
            "OEM/OES parts, labour, and paint pricing benchmarks",
            "Inflated estimate detection (>12% variance cap)",
            "Duplicate part & labour overlap detection",
            "Repair vs replacement justification against damage observations",
        ],
        input_contract={
            "estimate_validation": "object (lines, anomalies, benchmark_summary)",
        },
        output_contract={
            "total_claimed_inr": "decimal string",
            "total_recommended_inr": "decimal string",
            "benchmark_summary": "object",
            "anomalies": "list[object]",
            "repair_vs_replace_conflicts": "list[object]",
        },
        allowed_tools=[
            "parts_catalogue",
            "rate_card_read",
            "estimate_parser",
            "duplicate_line_rules",
            "create_claim_task",
            "request_rework",
        ],
        authorised_actions=[
            "create_claim_task",
        ],
        prohibited_actions=[
            "silently_alter_garage_quote",
            "accuse_fraud_on_duplicate_line",
            "mutate_claim_state_directly",
        ],
        depends_on=["damage_assessment"],
        can_request_rework_from=["damage_assessment", "provider_coordination"],
        human_gate_condition="Duplicate lines, >12% rate variance, or repair-vs-replace mismatch routes to Adjuster/Surveyor.",
        timeout_seconds=15,
        max_retries=2,
    ),
    "fraud_intelligence": AgentContractSpec(
        agent_name="fraud_intelligence",
        display_name="Fraud Intelligence",
        stage="5. Investigation",
        operational_responsibility=(
            "Detects network-based fraud patterns, cross-claim hash reuse, garage anomaly clusters, and "
            "timing anomalies with explainable signal factors and mandatory benign explanations."
        ),
        required_capabilities=[
            "Network-based fraud pattern detection (garage/entity rings)",
            "Anomaly detection (early inception, estimate anomalies, repeat claims)",
            "Suspicious connection mapping via entity graph",
            "Explainable signals with weighted factors & benign explanations",
        ],
        input_contract={
            "indicators": "list[object]",
            "entity_graph": "object (nodes, edges, suspicious_connections)",
        },
        output_contract={
            "alert_count": "integer",
            "fraud_signal_score": "decimal string 0.000-1.000 (advisory; never auto-rejects)",
            "fraud_score_can_reject": "boolean (always false)",
            "network_patterns_detected": "list[string]",
            "suspicious_connections": "list[object]",
            "indicators": "list[object]",
        },
        allowed_tools=[
            "fraud_feature_service",
            "fraud_rules",
            "entity_graph_query",
            "create_claim_task",
        ],
        authorised_actions=[
            "create_claim_task",
        ],
        prohibited_actions=[
            "auto_reject_claim",
            "block_fnol_intake",
            "expose_siu_alerts_to_garage_or_customer",
            "mutate_claim_state_directly",
        ],
        depends_on=["claim_triage", "document_intelligence"],
        can_request_rework_from=["document_intelligence", "estimate_validation"],
        human_gate_condition="Any fraud signal routes to SIU Investigator and blocks L1 Handler approval via DoA.",
        timeout_seconds=15,
        max_retries=2,
    ),
    "settlement_recommendation": AgentContractSpec(
        agent_name="settlement_recommendation",
        display_name="Settlement Recommendation",
        stage="6. Settlement & Release",
        operational_responsibility=(
            "Evaluates multiple deterministic Decimal settlement scenarios (cashless, reimbursement, no-addons, "
            "CTL + salvage), enforces IDV limits, prepares DoA approval tasks, and initiates approved payouts via Finance gate."
        ),
        required_capabilities=[
            "Multiple settlement scenarios comparison",
            "Deterministic Decimal depreciation & add-on waiver calculation",
            "Compulsory/voluntary deductible & coverage validation",
            "Salvage & policy IDV limit / CTL >=75% evaluation",
            "Controlled approval request generation & Finance-gated approved payment execution",
        ],
        input_contract={
            "calculation": "object (primary + scenarios)",
            "active_conditions": "list[string] (fraud_alert_open, ev_battery, tp_injury, total_loss, high_risk_complex)",
            "risk_tier": "LOW | MEDIUM | HIGH",
            "straight_through_eligible": "boolean",
            "settlement_approved": "boolean (for payment release)",
        },
        output_contract={
            "recommended_pathway": "string",
            "net_payable_inr": "decimal string",
            "scenarios": "list[object]",
            "required_doa_tier": "string",
            "auto_approved": "boolean",
        },
        allowed_tools=[
            "deterministic_calculator",
            "policy_facts_read",
            "survey_report_read",
            "generate_approval_request",
            "initiate_approved_payment",
            "create_claim_task",
        ],
        authorised_actions=[
            "generate_approval_request",
            "initiate_approved_payment",
            "create_claim_task",
        ],
        prohibited_actions=[
            "self_approve_settlement",
            "bypass_maker_checker_doa",
            "release_unapproved_payment",
            "mutate_claim_state_directly",
        ],
        depends_on=["coverage_intelligence", "damage_assessment", "estimate_validation", "fraud_intelligence", "provider_coordination"],
        can_request_rework_from=["estimate_validation", "coverage_intelligence", "provider_coordination"],
        human_gate_condition="MEDIUM/HIGH or > ₹25k claims always require independent Maker-Checker DoA sign-off; only rule-verified LOW risk claims <= ₹25,000 qualify for straight-through auto-approval limit.",
        timeout_seconds=15,
        max_retries=2,
    ),
    "customer_communication": AgentContractSpec(
        agent_name="customer_communication",
        display_name="Customer Communication",
        stage="8. Proactive Updates & Closure",
        operational_responsibility=(
            "Understands live claim state across all lifecycle stages and proactively synthesizes meaningful, "
            "multilingual updates (10 proactive triggers), enforces WhatsApp opt-in consent & channel preferences, "
            "and provides a direct escalation path to a human specialist."
        ),
        required_capabilities=[
            "State-aware proactive updates across 10 claim triggers (missing docs, photo recapture, survey scheduled/delayed, estimate approved, repair start, parts delay, settlement approval, payout, closure)",
            "Motor Claim Tracker 5-stage customer journey synthesis",
            "Multilingual communication (en-IN, hi-IN, mr-IN, ta-IN, kn-IN)",
            "Communication preference & WhatsApp opt-in consent enforcement",
            "Direct escalation path to human claims specialist",
        ],
        input_contract={
            "trigger_event": "documents_missing | photos_insufficient | survey_scheduled | surveyor_delayed | estimate_approved | repair_begins | parts_delayed | settlement_awaiting_approval | payment_processed | claim_closed | status_update",
            "message_type": "status_update | document_reminder | delay_advisory | next_steps | adverse_or_clarification",
            "locale": "BCP-47 language code (en-IN | hi-IN | mr-IN | ta-IN | kn-IN)",
            "channel": "whatsapp | sms | email | portal",
            "consent_whatsapp": "boolean",
            "is_adverse": "boolean",
        },
        output_contract={
            "trigger_event": "string",
            "language": "string",
            "channel": "string",
            "effective_channel": "string",
            "whatsapp_blocked_no_consent": "boolean",
            "message_type": "string",
            "subject": "string",
            "draft_message": "string",
            "action_cta": "string",
            "requires_human_review": "boolean",
            "human_escalation_available": "boolean",
        },
        allowed_tools=[
            "approved_templates",
            "communication_preference",
            "claim_status_read",
            "send_customer_update",
            "create_claim_task",
        ],
        authorised_actions=[
            "send_customer_update",
            "create_claim_task",
        ],
        prohibited_actions=[
            "send_unapproved_adverse_or_repudiation_notice",
            "send_whatsapp_without_customer_consent",
            "leak_internal_siu_notes",
            "mutate_claim_state_directly",
        ],
        depends_on=["fnol_concierge"],
        can_request_rework_from=[],
        human_gate_condition="Any adverse, partial-decline, or legal communication is held in pending_human_review; WhatsApp dispatch blocked if consent_whatsapp=false.",
        timeout_seconds=10,
        max_retries=2,
    ),
    "qa_compliance": AgentContractSpec(
        agent_name="qa_compliance",
        display_name="QA & Compliance",
        stage="8. Closure",
        operational_responsibility=(
            "Performs checklist-driven quality assurance, evidence verification, audit readiness scoring, "
            "and pre-closure validation — blocking closure or requesting upstream rework if any control fails."
        ),
        required_capabilities=[
            "Checklist-driven QA (9 statutory & operational controls)",
            "Evidence & mismatch verification audit",
            "Audit-chain & outbox readiness scoring",
            "Closure validation & automatic upstream rework dispatch",
        ],
        input_contract={
            "checks": "dict[control_id, boolean]",
            "checklist_context": "object (evidence, survey, estimate, siu, settlement, payment, grievance)",
        },
        output_contract={
            "qa_checklist": "list[object]",
            "audit_readiness_score": "float (0.0 to 1.0)",
            "failed_controls": "list[string]",
            "closure_eligible": "boolean",
        },
        allowed_tools=[
            "readonly_audit",
            "workflow_read",
            "rules_read",
            "evidence_read",
            "create_claim_task",
            "request_rework",
        ],
        authorised_actions=[
            "create_claim_task",
        ],
        prohibited_actions=[
            "mark_failed_controls_passed",
            "close_claim_with_open_grievance_or_unconfirmed_payment",
            "mutate_claim_state_directly",
        ],
        depends_on=["settlement_recommendation"],
        can_request_rework_from=[
            "document_intelligence",
            "estimate_validation",
            "fraud_intelligence",
            "provider_coordination",
            "settlement_recommendation",
        ],
        human_gate_condition="Any failed QA control blocks closure (409 STATE_CONFLICT) and emits remediation tasks/rework.",
        timeout_seconds=12,
        max_retries=2,
    ),
    "sla_intelligence": AgentContractSpec(
        agent_name="sla_intelligence",
        display_name="Predictive SLA Intelligence",
        stage="Cross-cutting: SLA operations",
        operational_responsibility=(
            "Predicts which claims will breach their SLA, which garages and surveyors drive delay, which documents stall "
            "processing and which queues are bottlenecked, then recommends reassignment, escalation, reminder, scheduling "
            "or prioritisation and executes only the actions its guardrails authorise."
        ),
        required_capabilities=[
            "Rule-driven SLA clocks (versioned rules, pause conditions, escalation sequences)",
            "Explainable breach probability with ranked drivers",
            "Surveyor overload, garage delay, document delay and queue bottleneck analysis",
            "Authorised-action gate: autonomous tasks/reminders, human approval for reassignment",
        ],
        input_contract={
            "sla_inputs": "object {instances: list[SLAInstance], signals: ClaimSignals, now: ISO timestamp}",
            "queue_context": "object {queue, pressure, open_clocks, late_clocks} (optional)",
            "mode": "recommend | execute (default recommend)",
        },
        output_contract={
            "predictions": "list[object] breach_probability, risk_band, expected_remaining_hours, drivers",
            "recommended_actions": "list[object] action, urgency, rationale, autonomy, authorisation",
            "suppressed": "list[object] actions withheld by cooldown or customer-choice guardrails",
            "executed_count": "integer",
            "gated_count": "integer (approval tasks raised for a human)",
        },
        allowed_tools=[
            "sla_rules_read",
            "sla_clock_read",
            "predict_sla_breach",
            "provider_load_read",
            "create_claim_task",
            "send_surveyor_followup",
            "request_documents",
        ],
        authorised_actions=[
            "create_claim_task",
            "send_surveyor_followup",
            "request_documents",
        ],
        prohibited_actions=[
            "reassign_surveyor_directly",
            "reassign_garage_directly",
            "override_customer_garage_choice",
            "edit_sla_rules",
            "mutate_claim_state_directly",
            "approve_settlement",
            "initiate_payment",
            "repudiate_claim",
        ],
        depends_on=[],
        can_request_rework_from=[],
        human_gate_condition=(
            "Reassignment and queue rebalancing always raise a claims-manager approval task; third-party claims allow "
            "task-level actions only; execute mode requires a claims manager or admin."
        ),
        timeout_seconds=15,
        max_retries=1,
    ),
}
