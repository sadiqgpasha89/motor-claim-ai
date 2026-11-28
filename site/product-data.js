/* GENERATED FILE - do not edit by hand.
 * Source: live calls to the Phase 5 portal API (DEMO / SYNTHETIC data).
 * Regenerate with: python scripts/export_product_demo_data.py
 */
window.PRODUCT_DEMO = {
 "generated_for": "DEMO / SYNTHETIC",
 "executive_dashboard": {
  "claims_total": 22,
  "by_status": {
   "ESTIMATE_REVIEW": 4,
   "EVIDENCE_PENDING": 3,
   "CLARIFICATION_REQUESTED": 1,
   "TRIAGED": 1,
   "SURVEY_ASSIGNED": 2,
   "REPAIR_IN_PROGRESS": 3,
   "HUMAN_REVIEW": 3,
   "PAYMENT_INITIATED": 1,
   "APPROVED": 1,
   "SURVEY_REQUIRED": 1,
   "CLOSED": 2
  },
  "by_risk_tier": {
   "HIGH": 5,
   "MEDIUM": 13,
   "LOW": 4
  },
  "by_claim_type": {
   "cashless": 12,
   "own_damage": 8,
   "reimbursement": 1,
   "third_party": 1
  },
  "settlement_net_total_inr": 213700.0,
  "fraud_alerts_open": 2,
  "fraud_alerts_total": 3,
  "human_tasks_open": 18,
  "headline_kpis": [
   {
    "id": "avg_processing_time",
    "name": "Average claim processing time",
    "why": "Overall efficiency",
    "unit": "hours",
    "direction": "lower",
    "traditional_illustrative": 120,
    "agentic_target_illustrative": 60,
    "value": 224.0,
    "n": 2,
    "basis": "closed claims, created to last update"
   },
   {
    "id": "stp_rate",
    "name": "Straight-through processing rate",
    "why": "Automation maturity",
    "unit": "percent",
    "direction": "higher",
    "traditional_illustrative": 0,
    "agentic_target_illustrative": 30,
    "value": 0.0,
    "n": 4,
    "basis": "claims with AI activity and no human task or approval"
   },
   {
    "id": "sla_breach_rate",
    "name": "SLA breach rate",
    "why": "Service quality",
    "unit": "percent",
    "direction": "lower",
    "traditional_illustrative": 15,
    "agentic_target_illustrative": 8,
    "value": 25.0,
    "n": 4,
    "basis": "SLA timers in breached state"
   },
   {
    "id": "human_touchpoints",
    "name": "Human touchpoints per claim",
    "why": "Operational efficiency",
    "unit": "count",
    "direction": "lower",
    "traditional_illustrative": 12,
    "agentic_target_illustrative": 6,
    "value": 4.5,
    "n": 4,
    "basis": "human tasks plus approvals per claim with AI activity"
   },
   {
    "id": "ai_cost_per_claim",
    "name": "AI cost per claim",
    "why": "Technology economics",
    "unit": "inr",
    "direction": "lower",
    "traditional_illustrative": null,
    "agentic_target_illustrative": 25,
    "value": 1.4844,
    "n": 4,
    "basis": "estimated token cost from the trace store"
   },
   {
    "id": "rework_rate",
    "name": "Rework rate",
    "why": "Quality of processing",
    "unit": "percent",
    "direction": "lower",
    "traditional_illustrative": null,
    "agentic_target_illustrative": null,
    "value": 0.0,
    "n": 14,
    "basis": "agent executions that requested rework"
   }
  ],
  "note": "Computed live from DEMO / SYNTHETIC data. Targets are illustrative."
 },
 "kpi_framework": {
  "kpis": [
   {
    "id": "avg_processing_time",
    "name": "Average claim processing time",
    "why": "Overall efficiency",
    "unit": "hours",
    "direction": "lower",
    "traditional_illustrative": 120,
    "agentic_target_illustrative": 60,
    "value": 224.0,
    "n": 2,
    "basis": "closed claims, created to last update"
   },
   {
    "id": "fnol_to_registration",
    "name": "FNOL-to-registration time",
    "why": "Intake experience",
    "unit": "hours",
    "direction": "lower",
    "traditional_illustrative": 8,
    "agentic_target_illustrative": 0.5,
    "value": null,
    "n": 0,
    "basis": "not measured: completed 'fnol_acknowledgement' SLA timers (proxy)"
   },
   {
    "id": "registration_to_survey",
    "name": "Registration-to-survey time",
    "why": "Operational responsiveness",
    "unit": "hours",
    "direction": "lower",
    "traditional_illustrative": 48,
    "agentic_target_illustrative": 24,
    "value": null,
    "n": 0,
    "basis": "not measured: completed 'surveyor_allocation' SLA timers (proxy)"
   },
   {
    "id": "survey_to_approval",
    "name": "Survey-to-approval time",
    "why": "Claims productivity",
    "unit": "hours",
    "direction": "lower",
    "traditional_illustrative": 72,
    "agentic_target_illustrative": 36,
    "value": null,
    "n": 0,
    "basis": "not measured: completed 'claim_decision' SLA timers (proxy)"
   },
   {
    "id": "approval_to_payment",
    "name": "Approval-to-payment time",
    "why": "Settlement efficiency",
    "unit": "hours",
    "direction": "lower",
    "traditional_illustrative": 48,
    "agentic_target_illustrative": 12,
    "value": 20.0,
    "n": 2,
    "basis": "approval decision to payment record"
   },
   {
    "id": "claims_per_handler",
    "name": "Claims processed per handler",
    "why": "Workforce productivity",
    "unit": "claims",
    "direction": "higher",
    "traditional_illustrative": null,
    "agentic_target_illustrative": null,
    "value": 15.0,
    "n": 1,
    "basis": "claims with an assigned handler"
   },
   {
    "id": "stp_rate",
    "name": "Straight-through processing rate",
    "why": "Automation maturity",
    "unit": "percent",
    "direction": "higher",
    "traditional_illustrative": 0,
    "agentic_target_illustrative": 30,
    "value": 0.0,
    "n": 4,
    "basis": "claims with AI activity and no human task or approval"
   },
   {
    "id": "human_touchpoints",
    "name": "Human touchpoints per claim",
    "why": "Operational efficiency",
    "unit": "count",
    "direction": "lower",
    "traditional_illustrative": 12,
    "agentic_target_illustrative": 6,
    "value": 4.5,
    "n": 4,
    "basis": "human tasks plus approvals per claim with AI activity"
   },
   {
    "id": "sla_breach_rate",
    "name": "SLA breach rate",
    "why": "Service quality",
    "unit": "percent",
    "direction": "lower",
    "traditional_illustrative": 15,
    "agentic_target_illustrative": 8,
    "value": 25.0,
    "n": 4,
    "basis": "SLA timers in breached state"
   },
   {
    "id": "avg_settlement",
    "name": "Average settlement amount",
    "why": "Financial impact",
    "unit": "inr",
    "direction": "context",
    "traditional_illustrative": null,
    "agentic_target_illustrative": null,
    "value": 35616.67,
    "n": 6,
    "basis": "latest settlement version per claim"
   },
   {
    "id": "estimate_variance",
    "name": "Estimate variance",
    "why": "Cost control",
    "unit": "percent",
    "direction": "lower",
    "traditional_illustrative": null,
    "agentic_target_illustrative": null,
    "value": 24.14,
    "n": 1,
    "basis": "mean gap between claimed and approved totals on reviewed estimates"
   },
   {
    "id": "fraud_yield",
    "name": "Fraud investigation yield",
    "why": "SIU effectiveness",
    "unit": "percent",
    "direction": "higher",
    "traditional_illustrative": null,
    "agentic_target_illustrative": null,
    "value": 0.0,
    "n": 1,
    "basis": "closed alerts that were not dismissed"
   },
   {
    "id": "false_positive_rate",
    "name": "False positive rate",
    "why": "Avoid unnecessary investigation",
    "unit": "percent",
    "direction": "lower",
    "traditional_illustrative": null,
    "agentic_target_illustrative": null,
    "value": 100.0,
    "n": 1,
    "basis": "closed alerts dispositioned as not substantiated"
   },
   {
    "id": "customer_satisfaction",
    "name": "Customer satisfaction",
    "why": "Customer outcome",
    "unit": "score",
    "direction": "higher",
    "traditional_illustrative": null,
    "agentic_target_illustrative": null,
    "value": null,
    "n": 0,
    "basis": "not measured: no data source in this platform"
   },
   {
    "id": "cost_per_claim",
    "name": "Cost per claim",
    "why": "Operational economics",
    "unit": "inr",
    "direction": "lower",
    "traditional_illustrative": null,
    "agentic_target_illustrative": null,
    "value": null,
    "n": 0,
    "basis": "not measured: no data source in this platform"
   },
   {
    "id": "ai_cost_per_claim",
    "name": "AI cost per claim",
    "why": "Technology economics",
    "unit": "inr",
    "direction": "lower",
    "traditional_illustrative": null,
    "agentic_target_illustrative": 25,
    "value": 1.4844,
    "n": 4,
    "basis": "estimated token cost from the trace store"
   },
   {
    "id": "rework_rate",
    "name": "Rework rate",
    "why": "Quality of processing",
    "unit": "percent",
    "direction": "lower",
    "traditional_illustrative": null,
    "agentic_target_illustrative": null,
    "value": 0.0,
    "n": 14,
    "basis": "agent executions that requested rework"
   }
  ],
  "measured_count": 12,
  "total_count": 17,
  "outcome_targets": [
   {
    "name": "Manual effort reduction",
    "target_pct": 45
   },
   {
    "name": "Processing time reduction",
    "target_pct": 50
   },
   {
    "name": "SLA breach reduction",
    "target_pct": 35
   },
   {
    "name": "Rework reduction",
    "target_pct": 30
   },
   {
    "name": "Customer effort reduction",
    "target_pct": 40
   }
  ],
  "before_after": [
   {
    "process": "Claim registration",
    "traditional": "Manual",
    "agentic_target": "Automated intake",
    "state": "built",
    "built_as": "FNOL Concierge agent and intake API"
   },
   {
    "process": "Document verification",
    "traditional": "Manual",
    "agentic_target": "AI-assisted",
    "state": "built",
    "built_as": "Document Intelligence agent, OCR and validation"
   },
   {
    "process": "Policy validation",
    "traditional": "Manual lookup",
    "agentic_target": "Automated rules + grounded retrieval",
    "state": "built",
    "built_as": "Coverage agent with a rules engine and a cited clause corpus"
   },
   {
    "process": "Claim routing",
    "traditional": "Manual",
    "agentic_target": "Risk-based routing",
    "state": "built",
    "built_as": "Claim Triage agent and the risk tiering rules"
   },
   {
    "process": "Damage assessment",
    "traditional": "Manual inspection",
    "agentic_target": "AI-assisted assessment",
    "state": "built",
    "built_as": "Damage agent, multimodal fusion and repair or replace rules. Vision is simulated."
   },
   {
    "process": "Estimate review",
    "traditional": "Manual",
    "agentic_target": "Automated anomaly detection",
    "state": "built",
    "built_as": "Estimate Validation agent and the benchmarking rules"
   },
   {
    "process": "Fraud screening",
    "traditional": "Reactive",
    "agentic_target": "Proactive intelligence",
    "state": "built",
    "built_as": "Fraud agent, weighted entity graph and SIU lead"
   },
   {
    "process": "Survey coordination",
    "traditional": "Manual calls",
    "agentic_target": "Automated coordination",
    "state": "built",
    "built_as": "Provider Coordination agent. Provider systems are sandbox adapters."
   },
   {
    "process": "Settlement calculation",
    "traditional": "Manual spreadsheets",
    "agentic_target": "Deterministic calculation",
    "state": "built",
    "built_as": "Deterministic settlement engine checked against an oracle"
   },
   {
    "process": "Customer updates",
    "traditional": "Reactive",
    "agentic_target": "Proactive communication",
    "state": "built",
    "built_as": "Customer Communication agent. Channels are sandbox adapters."
   },
   {
    "process": "SLA monitoring",
    "traditional": "Manual",
    "agentic_target": "Predictive",
    "state": "built",
    "built_as": "SLA engine and predictive SLA agent"
   },
   {
    "process": "Audit",
    "traditional": "Manual collection",
    "agentic_target": "Traceable evidence",
    "state": "built",
    "built_as": "Audit hash chain and the agent trace store"
   }
  ],
  "targets_note": "Illustrative targets only. These are proposed ambition levels, not measured results or guaranteed outcomes.",
  "note": "Measured from DEMO / SYNTHETIC data in the database. Targets are illustrative, not results. A KPI without data is shown as not measured."
 },
 "demos": {
  "demos": [
   {
    "id": "demo-1",
    "title": "Zero-touch eligible OD claim",
    "tag": "Automation",
    "claim_number": "CLM-DEMO-2026-0012",
    "summary": "Complete documents, valid policy, low damage and no anomalies. The agents run the workflow and move the claim with little human work, inside the approved authority.",
    "steps": [
     "FNOL and documents verified",
     "Coverage confirmed with cited clauses",
     "Low-risk fast-track routing",
     "Damage assessed and estimate validated",
     "Settlement calculated by rules",
     "Approval within authority",
     "Payment through the sandbox gateway"
    ],
    "portal_sections": "Claim 360 and Agent Command Center",
    "available": true,
    "claim_id": "clm-demo-0012",
    "status": "APPROVED",
    "risk_tier": "LOW",
    "claim_360_path": "/claims/clm-demo-0012/claim-360"
   },
   {
    "id": "demo-2",
    "title": "Complex damage and estimate anomaly",
    "tag": "AI intelligence",
    "claim_number": "CLM-DEMO-2026-0001",
    "summary": "The AI finds a duplicate repair line and cost variance. It recommends extra review and a supplementary estimate if hidden damage appears.",
    "steps": [
     "Duplicate bumper line detected",
     "OEM cost variance flagged",
     "Repair or replace analysis",
     "Benchmark against peer garages",
     "Reviewer task created",
     "Supplementary estimate guard"
    ],
    "portal_sections": "Damage Assessment and Settlement Workbench",
    "available": true,
    "claim_id": "clm-demo-0001",
    "status": "ESTIMATE_REVIEW",
    "risk_tier": "HIGH",
    "claim_360_path": "/claims/clm-demo-0001/claim-360"
   },
   {
    "id": "demo-3",
    "title": "Fraud intelligence",
    "tag": "Risk investigation",
    "claim_number": "CLM-DEMO-2026-0008",
    "summary": "A weighted entity graph, evidence comparison and signals support an SIU case. The score never rejects a claim.",
    "steps": [
     "Early inception signal",
     "Entity graph and shared-entity links",
     "Evidence comparison",
     "SIU lead created",
     "Investigator disposition",
     "Benign explanation recorded"
    ],
    "portal_sections": "Fraud and SIU",
    "available": true,
    "claim_id": "clm-demo-0008",
    "status": "HUMAN_REVIEW",
    "risk_tier": "LOW",
    "claim_360_path": "/claims/clm-demo-0008/claim-360"
   },
   {
    "id": "demo-4",
    "title": "EV accident",
    "tag": "Specialist handling",
    "claim_number": "CLM-DEMO-2026-0011",
    "summary": "Battery risk is detected. The claim goes to a safety escalation, a specialist inspection and a certified garage.",
    "steps": [
     "High-voltage battery risk flagged",
     "Thermal watch and isolation check",
     "Certified garage rule",
     "Specialist inspection task",
     "Complex repair assessment",
     "Clearance before payment"
    ],
    "portal_sections": "Claim 360 and Human Review",
    "available": true,
    "claim_id": "clm-demo-0011",
    "status": "HUMAN_REVIEW",
    "risk_tier": "HIGH",
    "claim_360_path": "/claims/clm-demo-0011/claim-360"
   },
   {
    "id": "demo-5",
    "title": "Third-party injury claim",
    "tag": "Human-led",
    "claim_number": "CLM-DEMO-2026-0010",
    "summary": "A bodily-injury case with an FIR. Humans lead. The agents prepare evidence and keep the legal record.",
    "steps": [
     "Injury and FIR captured",
     "Legal hold on evidence",
     "Liability investigation",
     "Legal workflow tasks",
     "Reserve and authority checks",
     "Specialist human oversight"
    ],
    "portal_sections": "Human Review",
    "available": true,
    "claim_id": "clm-demo-0010",
    "status": "HUMAN_REVIEW",
    "risk_tier": "HIGH",
    "claim_360_path": "/claims/clm-demo-0010/claim-360"
   }
  ],
  "note": "Demo claims are seeded synthetic data. Demos 2 to 5 are seeded with one agent run that stops at the first human gate. Demo 1 is seeded already approved. Start a new run with POST /api/v1/claims/{id}/orchestrate, or use scripts/od_claim_demo.py. Run the seed reset to restore the claims."
 },
 "demo_claim_360_answers": {
  "demo-1": {
   "what_has_happened": [
    "Claim registered"
   ],
   "what_is_happening_now": "State APPROVED; queue low_risk_od_assisted",
   "what_is_blocked": [],
   "why_blocked": [],
   "what_did_ai_do": [],
   "what_did_ai_find": [],
   "next_action": "LOW RISK Fast-Track auto-approved within INR 25,000 limit; ready for Finance payout",
   "do_i_need_to_act": {
    "required": false,
    "role": "claims_manager",
    "reason": "No action assigned to your role"
   }
  },
  "demo-2": {
   "what_has_happened": [
    "Post-FNOL parallel validation wave",
    "Policy & docs reconciled",
    "Estimated loss >= INR 50,000 IRDAI gate",
    "Conditional Damage + Parallel Fraud wave",
    "Garage estimate submitted for benchmarking"
   ],
   "what_is_happening_now": "State ESTIMATE_VALIDATION; queue siu_investigation",
   "what_is_blocked": [
    "FRAUD_REVIEW_OPEN",
    "TASK_ESTIMATE_REVIEW",
    "TASK_SIU_INVESTIGATION",
    "TASK_RISK_ESCALATION"
   ],
   "why_blocked": [
    "2 fraud signal(s) need SIU review",
    "Review duplicated Front Bumper line & +38.5% Fender rate variance",
    "SIU Review: FRD-EST-ANOMALY (Alert-only lead)",
    "Risk Escalated (MEDIUM -> HIGH): Specialist Investigation Required"
   ],
   "what_did_ai_do": [
    "customer_communication: dispatch_notification (success)",
    "fraud_intelligence: refer_to_siu_queue (escalated_to_human)"
   ],
   "what_did_ai_find": [
    "customer_communication: RC_COMM_REPAIR_BEGINS",
    "customer_communication: RC_COMM_STATUS_UPDATE",
    "fraud_intelligence: FRD-EST-ANOMALY",
    "fraud_intelligence: FRD-REPEAT-VEHICLE"
   ],
   "next_action": "Adjuster/Surveyor to review duplicated estimate line and generate settlement recommendation",
   "do_i_need_to_act": {
    "required": false,
    "role": "claims_manager",
    "reason": "No action assigned to your role"
   }
  },
  "demo-3": {
   "what_has_happened": [
    "Document extraction detected conflict, prompt injection, or missing core docs"
   ],
   "what_is_happening_now": "State HUMAN_REVIEW; queue siu_cleared",
   "what_is_blocked": [
    "DOCUMENTS_MISSING",
    "TASK_DOCUMENT_REQUEST"
   ],
   "why_blocked": [
    "Missing: policy_schedule, registration_certificate, driving_licence",
    "Collect missing evidence: policy_schedule, registration_certificate, driving_licence"
   ],
   "what_did_ai_do": [
    "fnol_concierge: run_document_intelligence (success)",
    "document_intelligence: human_fact_verification (escalated_to_human)",
    "coverage_intelligence: run_triage (success)",
    "customer_communication: dispatch_notification (success)"
   ],
   "what_did_ai_find": [
    "fnol_concierge: RC_CHANNEL_WEB",
    "fnol_concierge: RC_LOCALE_EN_IN",
    "document_intelligence: RC_NO_EXTRACTED_FACTS",
    "coverage_intelligence: RC_HYBRID_POLICY_RAG_CITED",
    "coverage_intelligence: RC_POLICY_ACTIVE_IN_PERIOD",
    "customer_communication: RC_COMM_STATUS_UPDATE",
    "customer_communication: RC_COMM_STATUS_UPDATE"
   ],
   "next_action": "Human adjuster to verify RC/Policy facts or quarantine notice",
   "do_i_need_to_act": {
    "required": false,
    "role": "claims_manager",
    "reason": "No action assigned to your role"
   }
  },
  "demo-4": {
   "what_has_happened": [
    "Document extraction detected conflict, prompt injection, or missing core docs"
   ],
   "what_is_happening_now": "State HUMAN_REVIEW; queue ev_oem_diagnostics",
   "what_is_blocked": [
    "DOCUMENTS_MISSING",
    "TASK_EV_CASE_STAGE_SAFE_RECOVERY_ISOLATION",
    "TASK_EV_CASE_STAGE_SPECIALIST_SURVEY",
    "TASK_EV_CASE_STAGE_OEM_DIAGNOSTICS",
    "TASK_TOWING_DISPATCH",
    "TASK_DOCUMENT_REQUEST"
   ],
   "why_blocked": [
    "Missing: policy_schedule, registration_certificate, driving_licence",
    "[EV] Flatbed recovery, HV isolation & quarantine - EV-DEMO-2026-0011",
    "[EV] EV-HV certified physical survey - EV-DEMO-2026-0011",
    "[EV] OEM diagnostic scan & HV tests - EV-DEMO-2026-0011",
    "Dispatch EV Flatbed Recovery to BKC, Mumbai",
    "Collect missing evidence: policy_schedule, registration_certificate, driving_licence"
   ],
   "what_did_ai_do": [
    "fnol_concierge: run_document_intelligence (success)",
    "document_intelligence: human_fact_verification (escalated_to_human)",
    "coverage_intelligence: run_triage (success)",
    "customer_communication: dispatch_notification (success)"
   ],
   "what_did_ai_find": [
    "fnol_concierge: RC_CHANNEL_WEB",
    "fnol_concierge: RC_LOCALE_EN_IN",
    "document_intelligence: RC_NO_EXTRACTED_FACTS",
    "coverage_intelligence: RC_HYBRID_POLICY_RAG_CITED",
    "coverage_intelligence: RC_POLICY_ACTIVE_IN_PERIOD",
    "customer_communication: RC_COMM_PARTS_DELAYED",
    "customer_communication: RC_COMM_DELAY_ADVISORY"
   ],
   "next_action": "Human adjuster to verify RC/Policy facts or quarantine notice",
   "do_i_need_to_act": {
    "required": false,
    "role": "claims_manager",
    "reason": "No action assigned to your role"
   }
  },
  "demo-5": {
   "what_has_happened": [
    "Claim registered"
   ],
   "what_is_happening_now": "State HUMAN_REVIEW; queue tp_liability_investigation",
   "what_is_blocked": [
    "DOCUMENTS_MISSING",
    "TASK_TP_EVIDENCE_AND_FACTS",
    "TASK_TP_POLICE_FIR",
    "TASK_TP_LIABILITY_INVESTIGATION",
    "TASK_DOCUMENT_REQUEST",
    "TASK_COVERAGE_REVIEW"
   ],
   "why_blocked": [
    "Missing: policy_schedule, registration_certificate, driving_licence",
    "[TP] Evidence And Facts - TP-DEMO-2026-0010",
    "[TP] Police Fir - TP-DEMO-2026-0010",
    "[TP] Liability Investigation - TP-DEMO-2026-0010",
    "Collect missing evidence: policy_schedule, registration_certificate, driving_licence",
    "Human Coverage / Legal Ambiguity Review' (legal_tp)"
   ],
   "what_did_ai_do": [
    "fnol_concierge: run_document_intelligence (success)",
    "document_intelligence: human_fact_verification (escalated_to_human)",
    "coverage_intelligence: human_coverage_review (escalated_to_human)",
    "customer_communication: dispatch_notification (success)"
   ],
   "what_did_ai_find": [
    "fnol_concierge: RC_CHANNEL_WEB",
    "fnol_concierge: RC_LOCALE_EN_IN",
    "document_intelligence: RC_NO_EXTRACTED_FACTS",
    "coverage_intelligence: RC_HYBRID_POLICY_RAG_CITED",
    "coverage_intelligence: RC_POLICY_ACTIVE_IN_PERIOD",
    "customer_communication: RC_COMM_STATUS_UPDATE",
    "customer_communication: RC_COMM_STATUS_UPDATE"
   ],
   "next_action": "Resolve coverage ambiguity / legal TP review before triage",
   "do_i_need_to_act": {
    "required": false,
    "role": "claims_manager",
    "reason": "No action assigned to your role"
   }
  }
 },
 "capability_model": {
  "vision": "An autonomous, governed motor insurance claims operating platform.",
  "capability_model": [
   {
    "capability": "Intake",
    "target_state": "Conversational, multimodal, omnichannel",
    "state": "partial",
    "evidence": "FNOL Concierge agent and intake API. Channels are sandbox adapters."
   },
   {
    "capability": "Documents",
    "target_state": "AI extraction, reconciliation and validation",
    "state": "partial",
    "evidence": "Document Intelligence with OCR. OCR robustness is a tracked gap (GAP-DOC-001)."
   },
   {
    "capability": "Policy",
    "target_state": "Deterministic rules + grounded policy RAG",
    "state": "built",
    "evidence": "Rules engine and a cited clause corpus. Citations are checked by the release gate."
   },
   {
    "capability": "Triage",
    "target_state": "Risk and complexity-based routing",
    "state": "built",
    "evidence": "Risk tiering rules and the complexity predictor."
   },
   {
    "capability": "Damage",
    "target_state": "Vision-based damage intelligence",
    "state": "partial",
    "evidence": "Damage agent with multimodal fusion. The vision model is simulated. Precision is a tracked gap (GAP-DMG-002)."
   },
   {
    "capability": "Estimates",
    "target_state": "Benchmarking and anomaly detection",
    "state": "built",
    "evidence": "Estimate validation and benchmarking rules."
   },
   {
    "capability": "Fraud",
    "target_state": "Explainable graph and signal intelligence",
    "state": "built",
    "evidence": "Signals and the weighted entity graph. No score rejects a claim."
   },
   {
    "capability": "Providers",
    "target_state": "Intelligent surveyor/garage coordination",
    "state": "partial",
    "evidence": "Coordination agent over sandbox provider adapters."
   },
   {
    "capability": "Settlement",
    "target_state": "Deterministic, explainable calculation",
    "state": "built",
    "evidence": "Rules engine with an independent oracle in the release gate."
   },
   {
    "capability": "Payment",
    "target_state": "Controlled execution and reconciliation",
    "state": "partial",
    "evidence": "Maker-checker, idempotency and reconciliation. The gateway is a sandbox. A second-payment gap is tracked (GAP-SET-001)."
   },
   {
    "capability": "Customers",
    "target_state": "Proactive, contextual communication",
    "state": "partial",
    "evidence": "Communication agent with consent and adverse-notice gating. Channels are sandbox."
   },
   {
    "capability": "Workflow",
    "target_state": "Durable, event-driven orchestration",
    "state": "built",
    "evidence": "Outbox, event bus with dead-letter and replay, recovery of stalled workflows."
   },
   {
    "capability": "Governance",
    "target_state": "Human accountability and maker-checker",
    "state": "built",
    "evidence": "Approval matrix, segregation of duties, override tracking."
   },
   {
    "capability": "Security",
    "target_state": "Least privilege, tenant isolation and audit",
    "state": "built",
    "evidence": "RBAC and ABAC, tool gateway, MFA step-up, PII redaction, audit hash chain."
   },
   {
    "capability": "Evaluation",
    "target_state": "Agent-level and end-to-end regression",
    "state": "built",
    "evidence": "Release gate with regression, safety, fairness and hallucination suites."
   },
   {
    "capability": "Operations",
    "target_state": "Real-time monitoring and predictive SLA",
    "state": "built",
    "evidence": "Agent Command Center, platform health and predictive SLA."
   }
  ],
  "assessment": [
   {
    "area": "Architecture and enterprise design",
    "rating": "Strong",
    "basis": "Documented architecture, rule-driven controls and a gate in CI."
   },
   {
    "area": "Agent specialization",
    "rating": "Strong foundation",
    "basis": "Eleven bounded agents plus an SLA agent with capability contracts."
   },
   {
    "area": "Governance and safety boundaries",
    "rating": "Strong foundation",
    "basis": "Tool gateway, maker-checker and a release gate. Open gaps are tracked."
   },
   {
    "area": "Deterministic settlement controls",
    "rating": "Strong",
    "basis": "Oracle-checked calculations. One payment gap is tracked."
   },
   {
    "area": "End-to-end autonomous orchestration",
    "rating": "Strengthen",
    "basis": "Orchestrator, recovery and event bus exist. No real insurer system is connected."
   },
   {
    "area": "Claims officer experience",
    "rating": "Strengthen",
    "basis": "Claim 360 and the nine-section portal exist. They have not been tested with real officers."
   },
   {
    "area": "Multimodal operational intelligence",
    "rating": "Expand",
    "basis": "Fusion logic exists. The vision model is simulated."
   },
   {
    "area": "Agent evaluation and reliability",
    "rating": "Expand",
    "basis": "Suites run on synthetic data and a deterministic model stub. No live model is evaluated."
   },
   {
    "area": "Business outcome measurement",
    "rating": "Expand",
    "basis": "KPIs are measured on demo data. Targets are illustrative."
   },
   {
    "area": "Production integrations",
    "rating": "Validate / implement",
    "basis": "Adapters are sandbox implementations. Real vendors are not connected."
   }
  ],
  "portal_sections": [
   {
    "id": "executive-dashboard",
    "name": "Executive Dashboard",
    "description": "Claims volume, processing time, SLA, settlement, fraud alerts and operational KPIs",
    "href": "/"
   },
   {
    "id": "claims-workbench",
    "name": "Claims Workbench",
    "description": "Search, claim queue, claim details, filters and assignment",
    "href": "/claims"
   },
   {
    "id": "agent-command-center",
    "name": "Agent Command Center",
    "description": "Agent execution, workflow, reasoning summaries, tool calls and actions",
    "href": "/agent-command-center"
   },
   {
    "id": "evidence-intelligence",
    "name": "Evidence Intelligence",
    "description": "Documents, OCR, extracted data, photos, evidence integrity and validation",
    "href": "/evidence-intelligence"
   },
   {
    "id": "damage-assessment",
    "name": "Damage Assessment",
    "description": "Vehicle damage identification, component analysis and estimate validation",
    "href": "/damage-assessment"
   },
   {
    "id": "fraud-siu",
    "name": "Fraud & SIU",
    "description": "Risk signals, entity relationships, investigation cases and review actions",
    "href": "/siu"
   },
   {
    "id": "settlement-workbench",
    "name": "Settlement Workbench",
    "description": "Calculations, scenarios, approvals, deductions and payment status",
    "href": "/settlement-workbench"
   },
   {
    "id": "human-review",
    "name": "Human Review",
    "description": "Approval tasks, escalations, overrides, decisions and reviewer workload",
    "href": "/human-review"
   },
   {
    "id": "performance-evaluation",
    "name": "Performance & Evaluation",
    "description": "Agent quality, accuracy, costs, latency, safety, SLA and business outcomes",
    "href": "/performance"
   }
  ],
  "note": "States are set by the team and checked by tests against the repository. Partial means built with a simulated or sandbox dependency."
 }
};
