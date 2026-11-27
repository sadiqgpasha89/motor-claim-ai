/* GENERATED FILE - do not edit by hand.
 * Source: a live run of scripts/od_claim_demo.py against the API (DEMO / SYNTHETIC data, estimated token counts).
 * Regenerate with: python scripts/export_claim360_demo_data.py
 */
window.CLAIM360_DEMO = {
 "generated_for": "DEMO / SYNTHETIC",
 "journey": [
  {
   "step": "FNOL intake",
   "claim_status": "REGISTERED",
   "note": "risk tier LOW, path fast_track"
  },
  {
   "step": "Evidence upload",
   "claim_status": "REGISTERED",
   "note": "RC and 3 daylight photos stored with sha256"
  },
  {
   "step": "Agent wave 1",
   "claim_status": "ASSESSMENT",
   "note": "agents: coverage_intelligence, customer_communication, claim_triage, damage_assessment, fraud_intelligence"
  },
  {
   "step": "Agent wave 2",
   "claim_status": "APPROVED",
   "note": "estimate validated, settlement calculated, auto-approved inside authority limit"
  },
  {
   "step": "Payment",
   "claim_status": "confirmed",
   "note": "finance approver released idempotent payment"
  },
  {
   "step": "Closure",
   "claim_status": "CLOSED",
   "note": "claim closed"
  }
 ],
 "claim_360": {
  "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
  "overview": {
   "claim_number": "CLM-DEMO-2026-45805C",
   "status": "CLOSED",
   "canonical_state": "CLOSED",
   "claim_type": "cashless",
   "peril_cause": "road_accident",
   "risk_tier": "LOW",
   "operational_path": "fast_track",
   "severity_band": "low",
   "estimated_loss_inr": "12000.00",
   "queue_name": "low_risk_od_assisted",
   "policy": {
    "policy_number": "POL-IN-DEMO-2026-OD01",
    "idv_inr": "720000.00",
    "status": "active"
   },
   "vehicle": {
    "registration": "MH04OD2026",
    "make": "Hyundai",
    "model": "Venue SX",
    "year": 2024,
    "is_ev": false
   },
   "customer": {
    "name": "Rohan Kulkarni (DEMO)",
    "phone": "******4402",
    "email": "ro***@demo.in",
    "language": "en-IN"
   },
   "paused": false,
   "sla": [
    {
     "stage": "surveyor_allocation",
     "status": "completed",
     "due_at": "2026-11-28T18:35:38.377645"
    },
    {
     "stage": "validation_completion",
     "status": "completed",
     "due_at": "2026-11-28T06:35:38.439361"
    },
    {
     "stage": "triage_routing",
     "status": "completed",
     "due_at": "2026-11-27T22:35:38.661871"
    },
    {
     "stage": "fast_track_assessment",
     "status": "completed",
     "due_at": "2026-11-28T06:35:38.666319"
    },
    {
     "stage": "assessment_completion",
     "status": "completed",
     "due_at": "2026-11-29T18:35:38.722327"
    },
    {
     "stage": "estimate_validation_sla",
     "status": "completed",
     "due_at": "2026-11-29T18:35:38.763055"
    },
    {
     "stage": "claim_decision",
     "status": "completed",
     "due_at": "2026-12-04T18:35:38.818342"
    },
    {
     "stage": "payout_initiation",
     "status": "completed",
     "due_at": "2026-11-29T18:35:38.828315"
    },
    {
     "stage": "payment_settlement",
     "status": "completed",
     "due_at": "2026-11-28T18:35:38.951795"
    }
   ]
  },
  "answers": {
   "what_has_happened": [
    "Garage repair estimate benchmarked against OEM rate card",
    "Deterministic settlement computed",
    "LOW RISK straight-through auto-approved within INR 25000.00 limit",
    "Finance initiated idempotent payout instruction",
    "All QA compliance controls passed; payment reconciled"
   ],
   "what_is_happening_now": "State CLOSED; queue low_risk_od_assisted",
   "what_is_blocked": [
    "TASK_ESTIMATE_SUBMISSION",
    "TASK_QA_REMEDIATION",
    "TASK_REWORK"
   ],
   "why_blocked": [
    "Awaiting Garage Repair Estimate Submission",
    "QA Closure Blocked: resolve 1 control(s)",
    "Rework Required -> settlement_recommendation (RC_QA_CONFIRMED_PAYMENT_OR_DECLINED)"
   ],
   "what_did_ai_do": [
    "fraud_intelligence: calculate_settlement (success)",
    "estimate_validation: run_fraud_checks (success)",
    "customer_communication: dispatch_notification (success)",
    "settlement_recommendation: ready_for_finance_payment (success)",
    "qa_compliance: resolve_compliance_gaps (rework_requested)",
    "customer_communication: dispatch_notification (success)",
    "qa_compliance: eligible_for_closure (success)",
    "customer_communication: dispatch_notification (success)"
   ],
   "what_did_ai_find": [
    "fnol_concierge: RC_CHANNEL_WEB",
    "fnol_concierge: RC_LOCALE_EN_IN",
    "document_intelligence: RC_MULTI_DOC_RECONCILED",
    "document_intelligence: RC_MULTI_DOC_RECONCILED",
    "document_intelligence: RC_MULTI_DOC_RECONCILED",
    "document_intelligence: RC_MULTI_DOC_RECONCILED",
    "coverage_intelligence: RC_HYBRID_POLICY_RAG_CITED",
    "coverage_intelligence: RC_POLICY_ACTIVE_IN_PERIOD"
   ],
   "next_action": "Claim closed; audit & evidence retained",
   "do_i_need_to_act": {
    "required": true,
    "role": "claims_handler",
    "reason": "Approval or task assigned to your role"
   }
  },
  "blockers": [
   {
    "code": "TASK_ESTIMATE_SUBMISSION",
    "why": "Awaiting Garage Repair Estimate Submission",
    "owner": "garage"
   },
   {
    "code": "TASK_QA_REMEDIATION",
    "why": "QA Closure Blocked: resolve 1 control(s)",
    "owner": "claims_handler"
   },
   {
    "code": "TASK_REWORK",
    "why": "Rework Required -> settlement_recommendation (RC_QA_CONFIRMED_PAYMENT_OR_DECLINED)",
    "owner": "claims_handler"
   }
  ],
  "workflow": [
   {
    "order": 1,
    "agent_name": "fnol_concierge",
    "display_name": "FNOL Concierge",
    "stage": "1. FNOL Intake",
    "depends_on": [],
    "status": "completed",
    "last_outcome": "success",
    "last_latency_ms": 0,
    "last_confidence": 0.94
   },
   {
    "order": 2,
    "agent_name": "document_intelligence",
    "display_name": "Document Intelligence",
    "stage": "2. Validation",
    "depends_on": [
     "fnol_concierge"
    ],
    "status": "completed",
    "last_outcome": "success",
    "last_latency_ms": 0,
    "last_confidence": 0.91
   },
   {
    "order": 3,
    "agent_name": "coverage_intelligence",
    "display_name": "Coverage Intelligence",
    "stage": "2. Validation",
    "depends_on": [
     "fnol_concierge"
    ],
    "status": "completed",
    "last_outcome": "success",
    "last_latency_ms": 2,
    "last_confidence": 0.92
   },
   {
    "order": 4,
    "agent_name": "claim_triage",
    "display_name": "Claim Triage",
    "stage": "3. Triage",
    "depends_on": [
     "document_intelligence",
     "coverage_intelligence"
    ],
    "status": "completed",
    "last_outcome": "success",
    "last_latency_ms": 1,
    "last_confidence": 0.95
   },
   {
    "order": 5,
    "agent_name": "provider_coordination",
    "display_name": "Provider & Ecosystem Coordination",
    "stage": "5. Investigation & Dispatch",
    "depends_on": [
     "claim_triage"
    ],
    "status": "skipped_fast_track",
    "last_outcome": null,
    "last_latency_ms": null,
    "last_confidence": null
   },
   {
    "order": 6,
    "agent_name": "damage_assessment",
    "display_name": "Damage Assessment",
    "stage": "4. Assessment",
    "depends_on": [
     "claim_triage"
    ],
    "status": "completed",
    "last_outcome": "success",
    "last_latency_ms": 0,
    "last_confidence": 0.92
   },
   {
    "order": 7,
    "agent_name": "estimate_validation",
    "display_name": "Estimate Validation",
    "stage": "4. Assessment",
    "depends_on": [
     "damage_assessment"
    ],
    "status": "completed",
    "last_outcome": "success",
    "last_latency_ms": 0,
    "last_confidence": 0.93
   },
   {
    "order": 8,
    "agent_name": "fraud_intelligence",
    "display_name": "Fraud Intelligence",
    "stage": "5. Investigation",
    "depends_on": [
     "claim_triage",
     "document_intelligence"
    ],
    "status": "completed",
    "last_outcome": "success",
    "last_latency_ms": 0,
    "last_confidence": 0.92
   },
   {
    "order": 9,
    "agent_name": "settlement_recommendation",
    "display_name": "Settlement Recommendation",
    "stage": "6. Settlement & Release",
    "depends_on": [
     "coverage_intelligence",
     "damage_assessment",
     "estimate_validation",
     "fraud_intelligence",
     "provider_coordination"
    ],
    "status": "rework_required",
    "last_outcome": "success",
    "last_latency_ms": 0,
    "last_confidence": 0.96
   },
   {
    "order": 10,
    "agent_name": "customer_communication",
    "display_name": "Customer Communication",
    "stage": "8. Proactive Updates & Closure",
    "depends_on": [
     "fnol_concierge"
    ],
    "status": "completed",
    "last_outcome": "success",
    "last_latency_ms": 1,
    "last_confidence": 0.95
   },
   {
    "order": 11,
    "agent_name": "qa_compliance",
    "display_name": "QA & Compliance",
    "stage": "8. Closure",
    "depends_on": [
     "settlement_recommendation"
    ],
    "status": "completed",
    "last_outcome": "success",
    "last_latency_ms": 0,
    "last_confidence": 0.97
   }
  ],
  "execution_timeline": [
   {
    "at": "2026-11-27T18:35:38.374983+00:00",
    "kind": "state_transition",
    "title": "SUBMITTED \u2192 REGISTERED",
    "detail": "FNOL payload validated and registered without document blocking (IRDAI 2024)",
    "trigger_event": "FNOLSubmitted"
   },
   {
    "at": "2026-11-27T18:35:38.389348",
    "kind": "agent_execution",
    "title": "fnol_concierge \u2192 success",
    "detail": "run_document_intelligence",
    "agent_name": "fnol_concierge",
    "outcome": "success",
    "latency_ms": 0,
    "trace_id": "eec90c4f-bee4-4d72-a1ae-99dfc6696749"
   },
   {
    "at": "2026-11-27T18:35:38.402432",
    "kind": "human_or_audit",
    "title": "RISK_TIER_RECALCULATED",
    "detail": "claims_handler success",
    "actor_role": "claims_handler"
   },
   {
    "at": "2026-11-27T18:35:38.406007",
    "kind": "human_or_audit",
    "title": "CLAIM_INTIMATED_REGISTERED",
    "detail": "claims_handler success",
    "actor_role": "claims_handler"
   },
   {
    "at": "2026-11-27T18:35:38.434207",
    "kind": "agent_execution",
    "title": "document_intelligence \u2192 success",
    "detail": "run_coverage_check",
    "agent_name": "document_intelligence",
    "outcome": "success",
    "latency_ms": 0,
    "trace_id": "c361ff3f-439d-42fd-8b3e-75caf3dc46b0"
   },
   {
    "at": "2026-11-27T18:35:38.437998+00:00",
    "kind": "state_transition",
    "title": "REGISTERED \u2192 VALIDATION",
    "detail": "Document extraction completed; progressing in VALIDATION",
    "trigger_event": "DocumentExtracted"
   },
   {
    "at": "2026-11-27T18:35:38.452060",
    "kind": "human_or_audit",
    "title": "EVIDENCE_UPLOADED_AND_EXTRACTED",
    "detail": "claims_handler success",
    "actor_role": "claims_handler"
   },
   {
    "at": "2026-11-27T18:35:38.505850",
    "kind": "agent_execution",
    "title": "document_intelligence \u2192 success",
    "detail": "run_coverage_check",
    "agent_name": "document_intelligence",
    "outcome": "success",
    "latency_ms": 0,
    "trace_id": "e63b0575-977b-4dbf-a513-0296c7061ee3"
   },
   {
    "at": "2026-11-27T18:35:38.518511",
    "kind": "human_or_audit",
    "title": "EVIDENCE_UPLOADED_AND_EXTRACTED",
    "detail": "claims_handler success",
    "actor_role": "claims_handler"
   },
   {
    "at": "2026-11-27T18:35:38.541319",
    "kind": "agent_execution",
    "title": "document_intelligence \u2192 success",
    "detail": "run_coverage_check",
    "agent_name": "document_intelligence",
    "outcome": "success",
    "latency_ms": 0,
    "trace_id": "b782f0ca-3c82-496e-8ff3-76f1adc06652"
   },
   {
    "at": "2026-11-27T18:35:38.558309",
    "kind": "human_or_audit",
    "title": "EVIDENCE_UPLOADED_AND_EXTRACTED",
    "detail": "claims_handler success",
    "actor_role": "claims_handler"
   },
   {
    "at": "2026-11-27T18:35:38.578242",
    "kind": "agent_execution",
    "title": "document_intelligence \u2192 success",
    "detail": "run_coverage_check",
    "agent_name": "document_intelligence",
    "outcome": "success",
    "latency_ms": 0,
    "trace_id": "0ca75a68-7d2d-4212-850c-f955c4e0a23d"
   },
   {
    "at": "2026-11-27T18:35:38.593911",
    "kind": "human_or_audit",
    "title": "EVIDENCE_UPLOADED_AND_EXTRACTED",
    "detail": "claims_handler success",
    "actor_role": "claims_handler"
   },
   {
    "at": "2026-11-27T18:35:38.637156",
    "kind": "agent_execution",
    "title": "coverage_intelligence \u2192 success",
    "detail": "run_triage",
    "agent_name": "coverage_intelligence",
    "outcome": "success",
    "latency_ms": 2,
    "trace_id": "1acdcd0a-f2de-4fba-8d19-d33ae15304cd"
   },
   {
    "at": "2026-11-27T18:35:38.645503",
    "kind": "agent_execution",
    "title": "customer_communication \u2192 success",
    "detail": "dispatch_notification",
    "agent_name": "customer_communication",
    "outcome": "success",
    "latency_ms": 0,
    "trace_id": "a263a8a0-6b8b-4f3a-9454-d7a65e123a30"
   },
   {
    "at": "2026-11-27T18:35:38.655840",
    "kind": "agent_execution",
    "title": "claim_triage \u2192 success",
    "detail": "ai_damage_assessment",
    "agent_name": "claim_triage",
    "outcome": "success",
    "latency_ms": 1,
    "trace_id": "3c8fb187-342f-42f0-98e0-de639ed8b757"
   },
   {
    "at": "2026-11-27T18:35:38.660660+00:00",
    "kind": "state_transition",
    "title": "VALIDATION \u2192 TRIAGE",
    "detail": "Policy validation and extracted evidence satisfied triage entry conditions",
    "trigger_event": "TriageStarted"
   },
   {
    "at": "2026-11-27T18:35:38.664853+00:00",
    "kind": "state_transition",
    "title": "TRIAGE \u2192 FAST_TRACK",
    "detail": "ClaimTriage routed claim (LOW RISK -> fast_track) to branch FAST_TRACK",
    "trigger_event": "ClaimTriaged"
   },
   {
    "at": "2026-11-27T18:35:38.710278",
    "kind": "agent_execution",
    "title": "damage_assessment \u2192 success",
    "detail": "validate_estimate",
    "agent_name": "damage_assessment",
    "outcome": "success",
    "latency_ms": 0,
    "trace_id": "829fd46a-f91e-4381-aa3e-0491d08e90ce"
   },
   {
    "at": "2026-11-27T18:35:38.714720",
    "kind": "agent_execution",
    "title": "fraud_intelligence \u2192 success",
    "detail": "calculate_settlement",
    "agent_name": "fraud_intelligence",
    "outcome": "success",
    "latency_ms": 0,
    "trace_id": "6a9b9922-67ba-4e6e-8a3e-1e8acd284a2a"
   },
   {
    "at": "2026-11-27T18:35:38.720509+00:00",
    "kind": "state_transition",
    "title": "FAST_TRACK \u2192 ASSESSMENT",
    "detail": "Visual damage assessment observations persisted",
    "trigger_event": "DamageAssessed"
   },
   {
    "at": "2026-11-27T18:35:38.733740",
    "kind": "human_or_audit",
    "title": "AGENT_TASK_CREATED",
    "detail": "bounded_agent success",
    "actor_role": "bounded_agent"
   },
   {
    "at": "2026-11-27T18:35:38.756705",
    "kind": "agent_execution",
    "title": "estimate_validation \u2192 success",
    "detail": "run_fraud_checks",
    "agent_name": "estimate_validation",
    "outcome": "success",
    "latency_ms": 0,
    "trace_id": "14687472-49b7-4012-86f0-a0b7b413c917"
   },
   {
    "at": "2026-11-27T18:35:38.761057+00:00",
    "kind": "state_transition",
    "title": "ASSESSMENT \u2192 ESTIMATE_VALIDATION",
    "detail": "Garage repair estimate benchmarked against OEM rate card",
    "trigger_event": "EstimateValidated"
   },
   {
    "at": "2026-11-27T18:35:38.778532",
    "kind": "human_or_audit",
    "title": "ESTIMATE_SUBMITTED_AND_VALIDATED",
    "detail": "claims_handler success",
    "actor_role": "claims_handler"
   },
   {
    "at": "2026-11-27T18:35:38.779777",
    "kind": "agent_execution",
    "title": "customer_communication \u2192 success",
    "detail": "dispatch_notification",
    "agent_name": "customer_communication",
    "outcome": "success",
    "latency_ms": 1,
    "trace_id": "9ac1b376-28cf-4726-8bc8-64f85761133e"
   },
   {
    "at": "2026-11-27T18:35:38.783652",
    "kind": "human_or_audit",
    "title": "PROACTIVE_CUSTOMER_COMM_DISPATCHED",
    "detail": "claims_handler success",
    "actor_role": "claims_handler"
   },
   {
    "at": "2026-11-27T18:35:38.816885+00:00",
    "kind": "state_transition",
    "title": "ESTIMATE_VALIDATION \u2192 SETTLEMENT_PENDING_APPROVAL",
    "detail": "Deterministic settlement computed",
    "trigger_event": "SettlementCalculated"
   },
   {
    "at": "2026-11-27T18:35:38.826511+00:00",
    "kind": "state_transition",
    "title": "SETTLEMENT_PENDING_APPROVAL \u2192 APPROVED",
    "detail": "LOW RISK straight-through auto-approved within INR 25000.00 limit",
    "trigger_event": "FastTrackAutoApproved"
   },
   {
    "at": "2026-11-27T18:35:38.835314",
    "kind": "agent_execution",
    "title": "settlement_recommendation \u2192 success",
    "detail": "ready_for_finance_payment",
    "agent_name": "settlement_recommendation",
    "outcome": "success",
    "latency_ms": 0,
    "trace_id": "f85f4986-d0fd-44a5-922a-d5b0ddcc6cde"
   },
   {
    "at": "2026-11-27T18:35:38.848710",
    "kind": "agent_execution",
    "title": "qa_compliance \u2192 rework_requested",
    "detail": "resolve_compliance_gaps",
    "agent_name": "qa_compliance",
    "outcome": "rework_requested",
    "latency_ms": 1,
    "trace_id": "462964dc-96a8-4823-a19a-2e3dc0d3260f"
   },
   {
    "at": "2026-11-27T18:35:38.850936",
    "kind": "human_or_audit",
    "title": "AGENT_TASK_CREATED",
    "detail": "bounded_agent success",
    "actor_role": "bounded_agent"
   },
   {
    "at": "2026-11-27T18:35:38.858259",
    "kind": "human_or_audit",
    "title": "AGENT_TASK_CREATED",
    "detail": "bounded_agent success",
    "actor_role": "bounded_agent"
   },
   {
    "at": "2026-11-27T18:35:38.858266",
    "kind": "human_or_audit",
    "title": "AGENT_REWORK_REQUESTED",
    "detail": "claims_handler success",
    "actor_role": "claims_handler"
   },
   {
    "at": "2026-11-27T18:35:38.950035+00:00",
    "kind": "state_transition",
    "title": "APPROVED \u2192 PAYMENT_PENDING",
    "detail": "Finance initiated idempotent payout instruction",
    "trigger_event": "PaymentInitiated"
   },
   {
    "at": "2026-11-27T18:35:38.963902",
    "kind": "human_or_audit",
    "title": "PAYMENT_INITIATED",
    "detail": "finance_approver success",
    "actor_role": "finance_approver"
   },
   {
    "at": "2026-11-27T18:35:38.965064",
    "kind": "agent_execution",
    "title": "customer_communication \u2192 success",
    "detail": "dispatch_notification",
    "agent_name": "customer_communication",
    "outcome": "success",
    "latency_ms": 1,
    "trace_id": "f9fd25f7-37d1-49b4-8b50-3505888e4f24"
   },
   {
    "at": "2026-11-27T18:35:38.969218",
    "kind": "human_or_audit",
    "title": "PROACTIVE_CUSTOMER_COMM_DISPATCHED",
    "detail": "finance_approver success",
    "actor_role": "finance_approver"
   },
   {
    "at": "2026-11-27T18:35:38.993406",
    "kind": "agent_execution",
    "title": "qa_compliance \u2192 success",
    "detail": "eligible_for_closure",
    "agent_name": "qa_compliance",
    "outcome": "success",
    "latency_ms": 0,
    "trace_id": "fd0b0f39-42b6-47db-80b5-7b4a4b3e573c"
   },
   {
    "at": "2026-11-27T18:35:39.002731+00:00",
    "kind": "state_transition",
    "title": "PAYMENT_PENDING \u2192 CLOSED",
    "detail": "All QA compliance controls passed; payment reconciled",
    "trigger_event": "ClaimClosed"
   },
   {
    "at": "2026-11-27T18:35:39.017144",
    "kind": "human_or_audit",
    "title": "CLAIM_CLOSED",
    "detail": "claims_handler success",
    "actor_role": "claims_handler"
   },
   {
    "at": "2026-11-27T18:35:39.017942",
    "kind": "agent_execution",
    "title": "customer_communication \u2192 success",
    "detail": "dispatch_notification",
    "agent_name": "customer_communication",
    "outcome": "success",
    "latency_ms": 1,
    "trace_id": "1fb20f9a-4ff6-4b9e-8368-fb20aeaf63b4"
   },
   {
    "at": "2026-11-27T18:35:39.021383",
    "kind": "human_or_audit",
    "title": "PROACTIVE_CUSTOMER_COMM_DISPATCHED",
    "detail": "claims_handler success",
    "actor_role": "claims_handler"
   }
  ],
  "agent_executions": [
   {
    "id": "eec90c4f-bee4-4d72-a1ae-99dfc6696749",
    "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
    "workflow_id": "wf-cc4268b2f1",
    "agent_name": "fnol_concierge",
    "agent_version": "2.0.0",
    "model_name": "motorclaim-deterministic-stub",
    "model_version": "1.0.0",
    "prompt_version": "fnol-v2.0",
    "task_input_ref": "claim:951fea1a-99b1-48e2-a63a-f35dd6ced7da/agent:fnol_concierge/attempt:1/input-sha256:fc02a4ec8d2d0097",
    "tool_calls": [
     {
      "tool": "policy_lookup",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "create_intimation",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     }
    ],
    "tool_outputs": [],
    "started_at": "2026-11-27T18:35:38.389348+00:00",
    "ended_at": "2026-11-27T18:35:38.389348+00:00",
    "token_usage": {
     "input": 625,
     "output": 212,
     "total": 837,
     "source": "estimated"
    },
    "cost_inr": "0.25",
    "latency_ms": 0,
    "retry_count": 0,
    "attempt_number": 1,
    "status": "completed",
    "outcome": "success",
    "confidence": 0.94,
    "error_details": null,
    "human_intervention": null,
    "final_action": "run_document_intelligence",
    "stage_order": 1,
    "depends_on": [],
    "reason_codes": [
     "RC_CHANNEL_WEB",
     "RC_LOCALE_EN_IN",
     "RC_IRDAI_NON_BLOCKING_INTAKE"
    ],
    "explanation": "Captured structured FNOL via web (en-IN) at 'Powai, Mumbai'. Issued 0-item upload checklist without blocking registration."
   },
   {
    "id": "c361ff3f-439d-42fd-8b3e-75caf3dc46b0",
    "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
    "workflow_id": "wf-cc4268b2f1",
    "agent_name": "document_intelligence",
    "agent_version": "2.0.0",
    "model_name": "motorclaim-deterministic-stub",
    "model_version": "1.0.0",
    "prompt_version": "doc-intel-v2.0",
    "task_input_ref": "claim:951fea1a-99b1-48e2-a63a-f35dd6ced7da/agent:document_intelligence/attempt:1/input-sha256:8035ef13f8e183ee",
    "tool_calls": [
     {
      "tool": "evidence_read",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "ocr_extract",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "schema_validate",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "reconcile_documents",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     }
    ],
    "tool_outputs": [],
    "started_at": "2026-11-27T18:35:38.434207+00:00",
    "ended_at": "2026-11-27T18:35:38.434207+00:00",
    "token_usage": {
     "input": 694,
     "output": 247,
     "total": 941,
     "source": "estimated"
    },
    "cost_inr": "0.29",
    "latency_ms": 0,
    "retry_count": 0,
    "attempt_number": 1,
    "status": "completed",
    "outcome": "success",
    "confidence": 0.91,
    "error_details": null,
    "human_intervention": null,
    "final_action": "run_coverage_check",
    "stage_order": 2,
    "depends_on": [
     "fnol_concierge"
    ],
    "reason_codes": [
     "RC_MULTI_DOC_RECONCILED"
    ],
    "explanation": "Reconciled 2 field(s) across 1 document(s) with full SHA-256 & bbox provenance."
   },
   {
    "id": "e63b0575-977b-4dbf-a513-0296c7061ee3",
    "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
    "workflow_id": "wf-cc4268b2f1",
    "agent_name": "document_intelligence",
    "agent_version": "2.0.0",
    "model_name": "motorclaim-deterministic-stub",
    "model_version": "1.0.0",
    "prompt_version": "doc-intel-v2.0",
    "task_input_ref": "claim:951fea1a-99b1-48e2-a63a-f35dd6ced7da/agent:document_intelligence/attempt:1/input-sha256:960e0e60f016c332",
    "tool_calls": [
     {
      "tool": "evidence_read",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "ocr_extract",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "schema_validate",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "reconcile_documents",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     }
    ],
    "tool_outputs": [],
    "started_at": "2026-11-27T18:35:38.505850+00:00",
    "ended_at": "2026-11-27T18:35:38.505850+00:00",
    "token_usage": {
     "input": 741,
     "output": 247,
     "total": 988,
     "source": "estimated"
    },
    "cost_inr": "0.30",
    "latency_ms": 0,
    "retry_count": 0,
    "attempt_number": 1,
    "status": "completed",
    "outcome": "success",
    "confidence": 0.91,
    "error_details": null,
    "human_intervention": null,
    "final_action": "run_coverage_check",
    "stage_order": 2,
    "depends_on": [
     "fnol_concierge"
    ],
    "reason_codes": [
     "RC_MULTI_DOC_RECONCILED"
    ],
    "explanation": "Reconciled 2 field(s) across 2 document(s) with full SHA-256 & bbox provenance."
   },
   {
    "id": "b782f0ca-3c82-496e-8ff3-76f1adc06652",
    "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
    "workflow_id": "wf-cc4268b2f1",
    "agent_name": "document_intelligence",
    "agent_version": "2.0.0",
    "model_name": "motorclaim-deterministic-stub",
    "model_version": "1.0.0",
    "prompt_version": "doc-intel-v2.0",
    "task_input_ref": "claim:951fea1a-99b1-48e2-a63a-f35dd6ced7da/agent:document_intelligence/attempt:1/input-sha256:1a9edb91f593703b",
    "tool_calls": [
     {
      "tool": "evidence_read",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "ocr_extract",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "schema_validate",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "reconcile_documents",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     }
    ],
    "tool_outputs": [],
    "started_at": "2026-11-27T18:35:38.541319+00:00",
    "ended_at": "2026-11-27T18:35:38.541319+00:00",
    "token_usage": {
     "input": 787,
     "output": 247,
     "total": 1034,
     "source": "estimated"
    },
    "cost_inr": "0.31",
    "latency_ms": 0,
    "retry_count": 0,
    "attempt_number": 1,
    "status": "completed",
    "outcome": "success",
    "confidence": 0.91,
    "error_details": null,
    "human_intervention": null,
    "final_action": "run_coverage_check",
    "stage_order": 2,
    "depends_on": [
     "fnol_concierge"
    ],
    "reason_codes": [
     "RC_MULTI_DOC_RECONCILED"
    ],
    "explanation": "Reconciled 2 field(s) across 3 document(s) with full SHA-256 & bbox provenance."
   },
   {
    "id": "0ca75a68-7d2d-4212-850c-f955c4e0a23d",
    "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
    "workflow_id": "wf-cc4268b2f1",
    "agent_name": "document_intelligence",
    "agent_version": "2.0.0",
    "model_name": "motorclaim-deterministic-stub",
    "model_version": "1.0.0",
    "prompt_version": "doc-intel-v2.0",
    "task_input_ref": "claim:951fea1a-99b1-48e2-a63a-f35dd6ced7da/agent:document_intelligence/attempt:1/input-sha256:70d60f91f3fce742",
    "tool_calls": [
     {
      "tool": "evidence_read",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "ocr_extract",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "schema_validate",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "reconcile_documents",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     }
    ],
    "tool_outputs": [],
    "started_at": "2026-11-27T18:35:38.578242+00:00",
    "ended_at": "2026-11-27T18:35:38.578242+00:00",
    "token_usage": {
     "input": 835,
     "output": 247,
     "total": 1082,
     "source": "estimated"
    },
    "cost_inr": "0.32",
    "latency_ms": 0,
    "retry_count": 0,
    "attempt_number": 1,
    "status": "completed",
    "outcome": "success",
    "confidence": 0.91,
    "error_details": null,
    "human_intervention": null,
    "final_action": "run_coverage_check",
    "stage_order": 2,
    "depends_on": [
     "fnol_concierge"
    ],
    "reason_codes": [
     "RC_MULTI_DOC_RECONCILED"
    ],
    "explanation": "Reconciled 2 field(s) across 4 document(s) with full SHA-256 & bbox provenance."
   },
   {
    "id": "1acdcd0a-f2de-4fba-8d19-d33ae15304cd",
    "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
    "workflow_id": "wf-cc4268b2f1",
    "agent_name": "coverage_intelligence",
    "agent_version": "2.0.0",
    "model_name": "motorclaim-deterministic-stub",
    "model_version": "1.0.0",
    "prompt_version": "coverage-v2.0",
    "task_input_ref": "claim:951fea1a-99b1-48e2-a63a-f35dd6ced7da/agent:coverage_intelligence/attempt:1/input-sha256:3274a47ee1d03d3c",
    "tool_calls": [
     {
      "tool": "policy_read",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "policy_rag",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "deterministic_coverage_rules",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     }
    ],
    "tool_outputs": [],
    "started_at": "2026-11-27T18:35:38.637156+00:00",
    "ended_at": "2026-11-27T18:35:38.639156+00:00",
    "token_usage": {
     "input": 550,
     "output": 1416,
     "total": 1966,
     "source": "estimated"
    },
    "cost_inr": "0.96",
    "latency_ms": 2,
    "retry_count": 0,
    "attempt_number": 1,
    "status": "completed",
    "outcome": "success",
    "confidence": 0.92,
    "error_details": null,
    "human_intervention": null,
    "final_action": "run_triage",
    "stage_order": 3,
    "depends_on": [
     "fnol_concierge"
    ],
    "reason_codes": [
     "RC_HYBRID_POLICY_RAG_CITED",
     "RC_POLICY_ACTIVE_IN_PERIOD"
    ],
    "explanation": "Constructed 6-row coverage matrix with 5 cited clauses. Coverage confirmed with zero ambiguities."
   },
   {
    "id": "a263a8a0-6b8b-4f3a-9454-d7a65e123a30",
    "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
    "workflow_id": "wf-cc4268b2f1",
    "agent_name": "customer_communication",
    "agent_version": "2.0.0",
    "model_name": "motorclaim-deterministic-stub",
    "model_version": "1.0.0",
    "prompt_version": "comm-v3.0",
    "task_input_ref": "claim:951fea1a-99b1-48e2-a63a-f35dd6ced7da/agent:customer_communication/attempt:1/input-sha256:643ca682fee3c8fc",
    "tool_calls": [
     {
      "tool": "send_customer_update",
      "action_type": "send_customer_update",
      "status": "executed",
      "target": "communication:c93c19d3-87e2-4738-99b9-9406c22465df"
     },
     {
      "tool": "approved_templates",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "communication_preference",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "claim_status_read",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     }
    ],
    "tool_outputs": [
     {
      "tool": "send_customer_update",
      "summary": "Dispatched status_update (en-IN) via whatsapp",
      "output": {
       "communication_id": "c93c19d3-87e2-4738-99b9-9406c22465df",
       "channel": "whatsapp",
       "requested_channel": "whatsapp",
       "delivery_status": "delivered_whatsapp_mock",
       "language": "en-IN",
       "trigger_event": "status_update",
       "whatsapp_message_id": "wamid.DEMO-77CFE30B9F1C",
       "whatsapp_blocked_no_consent": false
      }
     }
    ],
    "started_at": "2026-11-27T18:35:38.645503+00:00",
    "ended_at": "2026-11-27T18:35:38.645503+00:00",
    "token_usage": {
     "input": 778,
     "output": 167,
     "total": 945,
     "source": "estimated"
    },
    "cost_inr": "0.26",
    "latency_ms": 0,
    "retry_count": 0,
    "attempt_number": 1,
    "status": "completed",
    "outcome": "success",
    "confidence": 0.95,
    "error_details": null,
    "human_intervention": null,
    "final_action": "dispatch_notification",
    "stage_order": 10,
    "depends_on": [
     "fnol_concierge"
    ],
    "reason_codes": [
     "RC_COMM_STATUS_UPDATE",
     "RC_COMM_STATUS_UPDATE",
     "RC_LOCALE_EN_IN"
    ],
    "explanation": "Synthesized state-aware status_update update in en-IN (claim state=VALIDATION). Dispatched via whatsapp. Proactively notified customer with human escalation option."
   },
   {
    "id": "3c8fb187-342f-42f0-98e0-de639ed8b757",
    "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
    "workflow_id": "wf-cc4268b2f1",
    "agent_name": "claim_triage",
    "agent_version": "2.0.0",
    "model_name": "motorclaim-deterministic-stub",
    "model_version": "1.0.0",
    "prompt_version": "triage-v3.0",
    "task_input_ref": "claim:951fea1a-99b1-48e2-a63a-f35dd6ced7da/agent:claim_triage/attempt:1/input-sha256:24d4c309cc9279f7",
    "tool_calls": [
     {
      "tool": "claim_facts_read",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "triage_rules_read",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "queue_recommend",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     }
    ],
    "tool_outputs": [],
    "started_at": "2026-11-27T18:35:38.655840+00:00",
    "ended_at": "2026-11-27T18:35:38.656840+00:00",
    "token_usage": {
     "input": 743,
     "output": 490,
     "total": 1233,
     "source": "estimated"
    },
    "cost_inr": "0.44",
    "latency_ms": 1,
    "retry_count": 0,
    "attempt_number": 1,
    "status": "completed",
    "outcome": "success",
    "confidence": 0.95,
    "error_details": null,
    "human_intervention": null,
    "final_action": "ai_damage_assessment",
    "stage_order": 4,
    "depends_on": [
     "document_intelligence",
     "coverage_intelligence"
    ],
    "reason_codes": [
     "RC_RISK_TIER_LOW",
     "RC_PATH_FAST_TRACK",
     "RC_PRIORITY_P4_FAST_TRACK",
     "RC_QUEUE_LOW_RISK_OD_ASSISTED",
     "RC_LOW_FAST_TRACK_ELIGIBLE",
     "RC_FAST_TRACK_ELIGIBLE"
    ],
    "explanation": "LOW RISK \u2014 Fast-track claims (Straight-through assisted processing): Fast-track straight-through. Goal: Minimize human touchpoints. Eligible for straight-through automated processing (auto-approval limit <= INR 25000.00: YES)."
   },
   {
    "id": "829fd46a-f91e-4381-aa3e-0491d08e90ce",
    "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
    "workflow_id": "wf-cc4268b2f1",
    "agent_name": "damage_assessment",
    "agent_version": "2.0.0",
    "model_name": "motorclaim-deterministic-stub",
    "model_version": "1.0.0",
    "prompt_version": "damage-v3.0",
    "task_input_ref": "claim:951fea1a-99b1-48e2-a63a-f35dd6ced7da/agent:damage_assessment/attempt:1/input-sha256:82ffb3fbd7a2d3dc",
    "tool_calls": [
     {
      "tool": "vision_model",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "image_quality_check",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "vehicle_taxonomy",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "bbox_localizer",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "cross_photo_compare",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "parts_labour_estimator",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     }
    ],
    "tool_outputs": [],
    "started_at": "2026-11-27T18:35:38.710278+00:00",
    "ended_at": "2026-11-27T18:35:38.710278+00:00",
    "token_usage": {
     "input": 2748,
     "output": 2292,
     "total": 5040,
     "source": "estimated"
    },
    "cost_inr": "1.92",
    "latency_ms": 0,
    "retry_count": 0,
    "attempt_number": 1,
    "status": "completed",
    "outcome": "success",
    "confidence": 0.92,
    "error_details": null,
    "human_intervention": null,
    "final_action": "validate_estimate",
    "stage_order": 6,
    "depends_on": [
     "claim_triage"
    ],
    "reason_codes": [
     "RC_IMAGE_QUALITY_PASS",
     "RC_COMPONENT_CONFIDENCE_CALIBRATED",
     "RC_VISIBLE_VS_INFERRED_SPLIT",
     "RC_PARTS_LABOUR_ESTIMATED"
    ],
    "explanation": "Executed 10-step visual damage workflow for 2024 Hyundai Venue SX Private Car 1000 To 1500Cc: 1 component(s) classified (Bumper=0.92 (repair)). Estimated parts+labour INR 7700.00; ready for estimate validation."
   },
   {
    "id": "6a9b9922-67ba-4e6e-8a3e-1e8acd284a2a",
    "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
    "workflow_id": "wf-cc4268b2f1",
    "agent_name": "fraud_intelligence",
    "agent_version": "2.0.0",
    "model_name": "motorclaim-deterministic-stub",
    "model_version": "1.0.0",
    "prompt_version": "fraud-v3.0",
    "task_input_ref": "claim:951fea1a-99b1-48e2-a63a-f35dd6ced7da/agent:fraud_intelligence/attempt:1/input-sha256:9348aa8472f90a48",
    "tool_calls": [
     {
      "tool": "fraud_feature_service",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "fraud_rules",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "entity_graph_query",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     }
    ],
    "tool_outputs": [],
    "started_at": "2026-11-27T18:35:38.714720+00:00",
    "ended_at": "2026-11-27T18:35:38.714720+00:00",
    "token_usage": {
     "input": 614,
     "output": 89,
     "total": 703,
     "source": "estimated"
    },
    "cost_inr": "0.18",
    "latency_ms": 0,
    "retry_count": 0,
    "attempt_number": 1,
    "status": "completed",
    "outcome": "success",
    "confidence": 0.92,
    "error_details": null,
    "human_intervention": null,
    "final_action": "calculate_settlement",
    "stage_order": 8,
    "depends_on": [
     "claim_triage",
     "document_intelligence"
    ],
    "reason_codes": [
     "RC_NO_FRAUD_SIGNALS",
     "RC_FRAUD_SCORE_NON_REJECTION_GUARD"
    ],
    "explanation": "Evaluated entity network, checksum reuse, policy timing, and estimate anomalies; zero fraud signals detected (score=0.000)."
   },
   {
    "id": "14687472-49b7-4012-86f0-a0b7b413c917",
    "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
    "workflow_id": "wf-cc4268b2f1",
    "agent_name": "estimate_validation",
    "agent_version": "2.0.0",
    "model_name": "motorclaim-deterministic-stub",
    "model_version": "1.0.0",
    "prompt_version": "estimate-v2.0",
    "task_input_ref": "claim:951fea1a-99b1-48e2-a63a-f35dd6ced7da/agent:estimate_validation/attempt:1/input-sha256:47864e9c41dccd84",
    "tool_calls": [
     {
      "tool": "parts_catalogue",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "rate_card_read",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "estimate_parser",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "duplicate_line_rules",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     }
    ],
    "tool_outputs": [],
    "started_at": "2026-11-27T18:35:38.756705+00:00",
    "ended_at": "2026-11-27T18:35:38.756705+00:00",
    "token_usage": {
     "input": 662,
     "output": 214,
     "total": 876,
     "source": "estimated"
    },
    "cost_inr": "0.26",
    "latency_ms": 0,
    "retry_count": 0,
    "attempt_number": 1,
    "status": "completed",
    "outcome": "success",
    "confidence": 0.93,
    "error_details": null,
    "human_intervention": null,
    "final_action": "run_fraud_checks",
    "stage_order": 7,
    "depends_on": [
     "damage_assessment"
    ],
    "reason_codes": [
     "RC_RATE_CARD_BENCHMARKED"
    ],
    "explanation": "Benchmarked parts, labour, and paint against RC-IN-2026-DEMO-V1. All lines within OEM/labour benchmark tolerances."
   },
   {
    "id": "9ac1b376-28cf-4726-8bc8-64f85761133e",
    "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
    "workflow_id": "wf-cc4268b2f1",
    "agent_name": "customer_communication",
    "agent_version": "2.0.0",
    "model_name": "motorclaim-deterministic-stub",
    "model_version": "1.0.0",
    "prompt_version": "comm-v3.0",
    "task_input_ref": "claim:951fea1a-99b1-48e2-a63a-f35dd6ced7da/agent:customer_communication/attempt:1/input-sha256:44136fa355b3678a",
    "tool_calls": [
     {
      "tool": "send_customer_update",
      "action_type": "send_customer_update",
      "status": "executed",
      "target": "communication:bc12fa4d-7454-4591-b7ae-42d1a266ab65"
     },
     {
      "tool": "approved_templates",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "communication_preference",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "claim_status_read",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     }
    ],
    "tool_outputs": [
     {
      "tool": "send_customer_update",
      "summary": "Dispatched estimate_approved (en-IN) via whatsapp",
      "output": {
       "communication_id": "bc12fa4d-7454-4591-b7ae-42d1a266ab65",
       "channel": "whatsapp",
       "requested_channel": "whatsapp",
       "delivery_status": "delivered_whatsapp_mock",
       "language": "en-IN",
       "trigger_event": "estimate_approved",
       "whatsapp_message_id": "wamid.DEMO-94D2931DB21D",
       "whatsapp_blocked_no_consent": false
      }
     }
    ],
    "started_at": "2026-11-27T18:35:38.779777+00:00",
    "ended_at": "2026-11-27T18:35:38.780777+00:00",
    "token_usage": {
     "input": 451,
     "output": 189,
     "total": 640,
     "source": "estimated"
    },
    "cost_inr": "0.20",
    "latency_ms": 1,
    "retry_count": 0,
    "attempt_number": 1,
    "status": "completed",
    "outcome": "success",
    "confidence": 0.95,
    "error_details": null,
    "human_intervention": null,
    "final_action": "dispatch_notification",
    "stage_order": 10,
    "depends_on": [
     "fnol_concierge"
    ],
    "reason_codes": [
     "RC_COMM_ESTIMATE_APPROVED",
     "RC_COMM_STATUS_UPDATE",
     "RC_LOCALE_EN_IN"
    ],
    "explanation": "Synthesized state-aware estimate_approved update in en-IN (claim state=ESTIMATE_VALIDATION). Dispatched via whatsapp. Proactively notified customer with human escalation option."
   },
   {
    "id": "f85f4986-d0fd-44a5-922a-d5b0ddcc6cde",
    "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
    "workflow_id": "wf-cc4268b2f1",
    "agent_name": "settlement_recommendation",
    "agent_version": "2.0.0",
    "model_name": "motorclaim-deterministic-stub",
    "model_version": "1.0.0",
    "prompt_version": "settlement-v3.0",
    "task_input_ref": "claim:951fea1a-99b1-48e2-a63a-f35dd6ced7da/agent:settlement_recommendation/attempt:1/input-sha256:5660b7c03693cce0",
    "tool_calls": [
     {
      "tool": "deterministic_calculator",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "policy_facts_read",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "survey_report_read",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     }
    ],
    "tool_outputs": [],
    "started_at": "2026-11-27T18:35:38.835314+00:00",
    "ended_at": "2026-11-27T18:35:38.835314+00:00",
    "token_usage": {
     "input": 548,
     "output": 71,
     "total": 619,
     "source": "estimated"
    },
    "cost_inr": "0.15",
    "latency_ms": 0,
    "retry_count": 0,
    "attempt_number": 1,
    "status": "completed",
    "outcome": "success",
    "confidence": 0.96,
    "error_details": null,
    "human_intervention": null,
    "final_action": "ready_for_finance_payment",
    "stage_order": 9,
    "depends_on": [
     "coverage_intelligence",
     "damage_assessment",
     "estimate_validation",
     "fraud_intelligence",
     "provider_coordination"
    ],
    "reason_codes": [
     "RC_DECIMAL_CALCULATION_VERIFIED",
     "RC_DOA_TIER_FAST_TRACK_AUTO_LIMIT",
     "RC_FAST_TRACK_AUTO_APPROVED"
    ],
    "explanation": "LOW RISK straight-through settlement INR 11000.00 auto-approved within IN-RISK-PROCESSING-2026 limit (<= INR 25000.00). Ready for Finance payout."
   },
   {
    "id": "462964dc-96a8-4823-a19a-2e3dc0d3260f",
    "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
    "workflow_id": "wf-cc4268b2f1",
    "agent_name": "qa_compliance",
    "agent_version": "2.0.0",
    "model_name": "motorclaim-deterministic-stub",
    "model_version": "1.0.0",
    "prompt_version": "qa-v2.0",
    "task_input_ref": "claim:951fea1a-99b1-48e2-a63a-f35dd6ced7da/agent:qa_compliance/attempt:1/input-sha256:8f05fa812aa173ee",
    "tool_calls": [
     {
      "tool": "create_claim_task",
      "action_type": "create_claim_task",
      "status": "executed",
      "target": "claim_task:4eecf856-f72f-408b-9a2f-d2e3c59092e1"
     },
     {
      "tool": "readonly_audit",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "workflow_read",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "rules_read",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "evidence_read",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     }
    ],
    "tool_outputs": [
     {
      "tool": "create_claim_task",
      "summary": "Created task 'QA Closure Blocked: resolve 1 control(s)' assigned to claims_handler (priority=high)",
      "output": {
       "task_id": "4eecf856-f72f-408b-9a2f-d2e3c59092e1",
       "task_type": "qa_remediation",
       "priority": "high",
       "assigned_role": "claims_handler"
      }
     }
    ],
    "started_at": "2026-11-27T18:35:38.848710+00:00",
    "ended_at": "2026-11-27T18:35:38.849710+00:00",
    "token_usage": {
     "input": 508,
     "output": 249,
     "total": 757,
     "source": "estimated"
    },
    "cost_inr": "0.25",
    "latency_ms": 1,
    "retry_count": 0,
    "attempt_number": 1,
    "status": "rework_required",
    "outcome": "rework_requested",
    "confidence": 0.96,
    "error_details": null,
    "human_intervention": null,
    "final_action": "resolve_compliance_gaps",
    "stage_order": 11,
    "depends_on": [
     "settlement_recommendation"
    ],
    "reason_codes": [
     "RC_QA_FAILED_CONFIRMED_PAYMENT_OR_DECLINED"
    ],
    "explanation": "Blocked closure: 1 QA control(s) failed (confirmed_payment_or_declined)."
   },
   {
    "id": "f9fd25f7-37d1-49b4-8b50-3505888e4f24",
    "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
    "workflow_id": "wf-cc4268b2f1",
    "agent_name": "customer_communication",
    "agent_version": "2.0.0",
    "model_name": "motorclaim-deterministic-stub",
    "model_version": "1.0.0",
    "prompt_version": "comm-v3.0",
    "task_input_ref": "claim:951fea1a-99b1-48e2-a63a-f35dd6ced7da/agent:customer_communication/attempt:1/input-sha256:44136fa355b3678a",
    "tool_calls": [
     {
      "tool": "send_customer_update",
      "action_type": "send_customer_update",
      "status": "executed",
      "target": "communication:2dc9c8fa-b53e-4bb4-9ade-3d7662a4746b"
     },
     {
      "tool": "approved_templates",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "communication_preference",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "claim_status_read",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     }
    ],
    "tool_outputs": [
     {
      "tool": "send_customer_update",
      "summary": "Dispatched payment_processed (en-IN) via whatsapp",
      "output": {
       "communication_id": "2dc9c8fa-b53e-4bb4-9ade-3d7662a4746b",
       "channel": "whatsapp",
       "requested_channel": "whatsapp",
       "delivery_status": "delivered_whatsapp_mock",
       "language": "en-IN",
       "trigger_event": "payment_processed",
       "whatsapp_message_id": "wamid.DEMO-F9E773DE77D0",
       "whatsapp_blocked_no_consent": false
      }
     }
    ],
    "started_at": "2026-11-27T18:35:38.965064+00:00",
    "ended_at": "2026-11-27T18:35:38.966064+00:00",
    "token_usage": {
     "input": 451,
     "output": 193,
     "total": 644,
     "source": "estimated"
    },
    "cost_inr": "0.21",
    "latency_ms": 1,
    "retry_count": 0,
    "attempt_number": 1,
    "status": "completed",
    "outcome": "success",
    "confidence": 0.95,
    "error_details": null,
    "human_intervention": null,
    "final_action": "dispatch_notification",
    "stage_order": 10,
    "depends_on": [
     "fnol_concierge"
    ],
    "reason_codes": [
     "RC_COMM_PAYMENT_PROCESSED",
     "RC_COMM_STATUS_UPDATE",
     "RC_LOCALE_EN_IN"
    ],
    "explanation": "Synthesized state-aware payment_processed update in en-IN (claim state=PAYMENT_PENDING). Dispatched via whatsapp. Proactively notified customer with human escalation option."
   },
   {
    "id": "fd0b0f39-42b6-47db-80b5-7b4a4b3e573c",
    "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
    "workflow_id": "wf-cc4268b2f1",
    "agent_name": "qa_compliance",
    "agent_version": "2.0.0",
    "model_name": "motorclaim-deterministic-stub",
    "model_version": "1.0.0",
    "prompt_version": "qa-v2.0",
    "task_input_ref": "claim:951fea1a-99b1-48e2-a63a-f35dd6ced7da/agent:qa_compliance/attempt:1/input-sha256:a42dc150b02f1ff6",
    "tool_calls": [
     {
      "tool": "readonly_audit",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "workflow_read",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "rules_read",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "evidence_read",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     }
    ],
    "tool_outputs": [],
    "started_at": "2026-11-27T18:35:38.993406+00:00",
    "ended_at": "2026-11-27T18:35:38.993406+00:00",
    "token_usage": {
     "input": 501,
     "output": 210,
     "total": 711,
     "source": "estimated"
    },
    "cost_inr": "0.23",
    "latency_ms": 0,
    "retry_count": 0,
    "attempt_number": 1,
    "status": "completed",
    "outcome": "success",
    "confidence": 0.97,
    "error_details": null,
    "human_intervention": null,
    "final_action": "eligible_for_closure",
    "stage_order": 11,
    "depends_on": [
     "settlement_recommendation"
    ],
    "reason_codes": [
     "RC_QA_ALL_CONTROLS_PASSED"
    ],
    "explanation": "All 6 QA compliance controls passed (audit readiness=1.0); claim eligible for CLOSED state."
   },
   {
    "id": "1fb20f9a-4ff6-4b9e-8368-fb20aeaf63b4",
    "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
    "workflow_id": "wf-cc4268b2f1",
    "agent_name": "customer_communication",
    "agent_version": "2.0.0",
    "model_name": "motorclaim-deterministic-stub",
    "model_version": "1.0.0",
    "prompt_version": "comm-v3.0",
    "task_input_ref": "claim:951fea1a-99b1-48e2-a63a-f35dd6ced7da/agent:customer_communication/attempt:1/input-sha256:44136fa355b3678a",
    "tool_calls": [
     {
      "tool": "send_customer_update",
      "action_type": "send_customer_update",
      "status": "executed",
      "target": "communication:777357b8-0d25-4a81-a454-1d74dc859e11"
     },
     {
      "tool": "approved_templates",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "communication_preference",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     },
     {
      "tool": "claim_status_read",
      "action_type": "read",
      "status": "ok",
      "target": "claim"
     }
    ],
    "tool_outputs": [
     {
      "tool": "send_customer_update",
      "summary": "Dispatched claim_closed (en-IN) via whatsapp",
      "output": {
       "communication_id": "777357b8-0d25-4a81-a454-1d74dc859e11",
       "channel": "whatsapp",
       "requested_channel": "whatsapp",
       "delivery_status": "delivered_whatsapp_mock",
       "language": "en-IN",
       "trigger_event": "claim_closed",
       "whatsapp_message_id": "wamid.DEMO-F56473012C99",
       "whatsapp_blocked_no_consent": false
      }
     }
    ],
    "started_at": "2026-11-27T18:35:39.017942+00:00",
    "ended_at": "2026-11-27T18:35:39.018942+00:00",
    "token_usage": {
     "input": 451,
     "output": 206,
     "total": 657,
     "source": "estimated"
    },
    "cost_inr": "0.21",
    "latency_ms": 1,
    "retry_count": 0,
    "attempt_number": 1,
    "status": "completed",
    "outcome": "success",
    "confidence": 0.95,
    "error_details": null,
    "human_intervention": null,
    "final_action": "dispatch_notification",
    "stage_order": 10,
    "depends_on": [
     "fnol_concierge"
    ],
    "reason_codes": [
     "RC_COMM_CLAIM_CLOSED",
     "RC_COMM_STATUS_UPDATE",
     "RC_LOCALE_EN_IN"
    ],
    "explanation": "Synthesized state-aware claim_closed update in en-IN (claim state=CLOSED). Dispatched via whatsapp. Proactively notified customer with human escalation option."
   }
  ],
  "agent_summary": {
   "executions": 17,
   "total_cost_inr": "6.73",
   "total_tokens": 19673,
   "human_interventions": 0,
   "completed_agents": [
    "fnol_concierge",
    "document_intelligence",
    "document_intelligence",
    "document_intelligence",
    "document_intelligence",
    "coverage_intelligence",
    "customer_communication",
    "claim_triage",
    "damage_assessment",
    "fraud_intelligence",
    "estimate_validation",
    "customer_communication",
    "settlement_recommendation",
    "customer_communication",
    "qa_compliance",
    "customer_communication"
   ]
  },
  "evidence": {
   "documents": [
    {
     "id": "f54c42f2-573a-44cf-8036-55861856998b",
     "doc_type": "registration_certificate",
     "status": "extracted_unverified",
     "filename": "rc_od.txt",
     "sha256": "b677cf580d682bd175494222868139cb31e581005ae31532cf14469bdc38ee39",
     "malware_scan": "clean",
     "prompt_injection_flagged": false,
     "legal_hold": false,
     "image_quality": null
    },
    {
     "id": "4ecb2892-a7d4-46c9-9676-9e67dfd2193f",
     "doc_type": "damage_photo",
     "status": "extracted_unverified",
     "filename": "front_daylight.jpg",
     "sha256": "633d00857a8520beeadb070afbbeb18b5f21f147e51b557a3eed70a40ac5282a",
     "malware_scan": "clean",
     "prompt_injection_flagged": false,
     "legal_hold": false,
     "image_quality": "acceptable"
    },
    {
     "id": "62c4fdfe-e969-4417-9237-553fd9724f77",
     "doc_type": "damage_photo",
     "status": "extracted_unverified",
     "filename": "left_daylight.jpg",
     "sha256": "17d159e530f0dd5929c0c40514af61c73935b2f4bde6c333fc35fe58c524523e",
     "malware_scan": "clean",
     "prompt_injection_flagged": false,
     "legal_hold": false,
     "image_quality": "acceptable"
    },
    {
     "id": "fc278b3e-d27e-4545-be1f-f900c63ef24f",
     "doc_type": "damage_photo",
     "status": "extracted_unverified",
     "filename": "closeup_daylight.jpg",
     "sha256": "8027409d1c86e86e4fd0dc9a36de524a365340f6259b4e6b2c555bae570724a1",
     "malware_scan": "clean",
     "prompt_injection_flagged": false,
     "legal_hold": false,
     "image_quality": "acceptable"
    }
   ],
   "extracted_facts": [
    {
     "evidence_id": "f54c42f2-573a-44cf-8036-55861856998b",
     "field": "vehicle_registration",
     "value": "MH04OD2026",
     "confidence": 0.92,
     "validation_status": "verified"
    },
    {
     "evidence_id": "f54c42f2-573a-44cf-8036-55861856998b",
     "field": "policy_number",
     "value": "POL-IN-DEMO-2026-OD01",
     "confidence": 0.94,
     "validation_status": "verified"
    }
   ],
   "integrity": "sha256 recorded per document"
  },
  "settlement_and_approvals": {
   "settlements": [
    {
     "id": "851e58cd-727e-4457-a15f-453ffd068e62",
     "version": 1,
     "gross_assessed_inr": "12000.00",
     "depreciation_inr": "0.00",
     "compulsory_excess_inr": "1000.00",
     "voluntary_excess_inr": "0.00",
     "salvage_inr": "0.00",
     "net_payable_inr": "11000.00",
     "approval_status": "approved",
     "rule_versions": {
      "depreciation": "IN-MOTOR-DEPRECIATION-2024:1.0.0",
      "irdai_controls": "IN-IRDAI-MC-2024:1.0.0"
     }
    }
   ],
   "approvals": [
    {
     "id": "456fc7af-d810-47de-a0f4-0e5417d78910",
     "action_type": "fast_track_auto_approval",
     "amount_inr": "11000.00",
     "decision": "approved",
     "maker_user_id": "system:fast_track_engine",
     "checker_user_id": "rule:IN-RISK-PROCESSING-2026",
     "authority_rule_version": "IN-RISK-PROCESSING-2026:1.0.0"
    }
   ],
   "payments": [
    {
     "id": "328b4c8d-c792-404a-a493-2ee5bf1329f1",
     "status": "confirmed",
     "amount_inr": "11000.00",
     "payee_type": "customer",
     "bank_account": "4821",
     "gateway_reference": "PG-UTR-3BE0D40C09BB"
    }
   ]
  },
  "fraud": {
   "visible": false
  },
  "is_synthetic_demo": true
 },
 "dashboard": {
  "kpis": {
   "workflow_success_rate_pct": 100.0,
   "human_escalation_rate_pct": 0.0,
   "avg_ai_execution_time_ms": 4,
   "avg_ai_execution_time_min": 0.0001,
   "ai_cost_per_claim_inr": "6.73",
   "workflow_runs": 1,
   "agent_executions": 17,
   "claims_with_ai_activity": 1,
   "total_tokens_estimated": 19673,
   "basis": "measured_from_trace_store"
  },
  "failed_agent_executions": [],
  "stuck_workflows": [
   {
    "claim_id": "clm-sla-0103",
    "claim_number": "CLM-DEMO-2026-0103",
    "status": "REPAIR_IN_PROGRESS",
    "reasons": [
     "no_movement_260h"
    ],
    "idle_hours": 260.0,
    "next_expected_action": "Verify policy and upload documents"
   },
   {
    "claim_id": "clm-sla-0104",
    "claim_number": "CLM-DEMO-2026-0104",
    "status": "REPAIR_IN_PROGRESS",
    "reasons": [
     "no_movement_200h"
    ],
    "idle_hours": 200.0,
    "next_expected_action": "Verify policy and upload documents"
   },
   {
    "claim_id": "clm-sla-0101",
    "claim_number": "CLM-DEMO-2026-0101",
    "status": "SURVEY_ASSIGNED",
    "reasons": [
     "no_movement_150h"
    ],
    "idle_hours": 150.0,
    "next_expected_action": "Verify policy and upload documents"
   },
   {
    "claim_id": "clm-sla-0105",
    "claim_number": "CLM-DEMO-2026-0105",
    "status": "EVIDENCE_PENDING",
    "reasons": [
     "no_movement_90h"
    ],
    "idle_hours": 90.0,
    "next_expected_action": "Verify policy and upload documents"
   },
   {
    "claim_id": "clm-sla-0107",
    "claim_number": "CLM-DEMO-2026-0107",
    "status": "ESTIMATE_REVIEW",
    "reasons": [
     "no_movement_66h"
    ],
    "idle_hours": 66.0,
    "next_expected_action": "Verify policy and upload documents"
   },
   {
    "claim_id": "clm-sla-0106",
    "claim_number": "CLM-DEMO-2026-0106",
    "status": "ESTIMATE_REVIEW",
    "reasons": [
     "no_movement_62h"
    ],
    "idle_hours": 62.0,
    "next_expected_action": "Verify policy and upload documents"
   },
   {
    "claim_id": "clm-sla-0108",
    "claim_number": "CLM-DEMO-2026-0108",
    "status": "ESTIMATE_REVIEW",
    "reasons": [
     "no_movement_60h"
    ],
    "idle_hours": 60.0,
    "next_expected_action": "Verify policy and upload documents"
   },
   {
    "claim_id": "clm-demo-0006",
    "claim_number": "CLM-DEMO-2026-0006",
    "status": "SURVEY_ASSIGNED",
    "reasons": [
     "dead_letter_open"
    ],
    "idle_hours": 0.0,
    "next_expected_action": "SLA BREACHED: Escalate overdue survey report (INR 500/day penalty exposure)"
   }
  ],
  "claims_breaching_sla": [
   {
    "claim_id": "clm-demo-0006",
    "claim_number": "CLM-DEMO-2026-0006",
    "stage": "survey_report_submission",
    "due_at": "2026-11-25T18:35:37.812881+00:00",
    "owner_role": "surveyor"
   }
  ],
  "human_approval_backlog": {
   "pending_approvals": [],
   "open_human_tasks": 15,
   "claims_in_human_review": 1
  },
  "fraud_investigation_queue": {
   "open_alerts": 1,
   "claims_in_investigation": 0,
   "alerts": [
    {
     "alert_id": "85b1894b-843c-4e7c-a03c-eb3d008af620",
     "claim_id": "clm-demo-0001",
     "claim_number": "CLM-DEMO-2026-0001",
     "indicator_code": "FRD-EST-ANOMALY",
     "severity_band": "low",
     "status": "new"
    }
   ]
  },
  "payment_reconciliation_failures": [
   {
    "payment_id": "pmt-demo-0009",
    "claim_id": "clm-demo-0009",
    "claim_number": "CLM-DEMO-2026-0009",
    "status": "timeout_reconcile_pending",
    "amount_inr": "51000.00",
    "gateway_reference": "PG-PEND-DEMO0009"
   }
  ],
  "model_api_outages": {
   "model_gateway_outage_active": false,
   "executions_degraded_by_outage": 0,
   "degraded_adapters": [],
   "adapters_checked": 7
  },
  "cost": {
   "by_claim": [
    {
     "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
     "executions": 17,
     "tokens": 19673,
     "claim_number": "CLM-DEMO-2026-45805C",
     "cost_inr": "6.73"
    }
   ],
   "by_agent": [
    {
     "agent_name": "damage_assessment",
     "executions": 1,
     "tokens": 5040,
     "cost_inr": "1.92"
    },
    {
     "agent_name": "document_intelligence",
     "executions": 4,
     "tokens": 4045,
     "cost_inr": "1.20"
    },
    {
     "agent_name": "coverage_intelligence",
     "executions": 1,
     "tokens": 1966,
     "cost_inr": "0.96"
    },
    {
     "agent_name": "customer_communication",
     "executions": 4,
     "tokens": 2886,
     "cost_inr": "0.88"
    },
    {
     "agent_name": "qa_compliance",
     "executions": 2,
     "tokens": 1468,
     "cost_inr": "0.48"
    },
    {
     "agent_name": "claim_triage",
     "executions": 1,
     "tokens": 1233,
     "cost_inr": "0.44"
    },
    {
     "agent_name": "estimate_validation",
     "executions": 1,
     "tokens": 876,
     "cost_inr": "0.26"
    },
    {
     "agent_name": "fnol_concierge",
     "executions": 1,
     "tokens": 837,
     "cost_inr": "0.25"
    },
    {
     "agent_name": "fraud_intelligence",
     "executions": 1,
     "tokens": 703,
     "cost_inr": "0.18"
    },
    {
     "agent_name": "settlement_recommendation",
     "executions": 1,
     "tokens": 619,
     "cost_inr": "0.15"
    }
   ],
   "by_claim_complexity": [
    {
     "complexity": "LOW",
     "executions": 17,
     "tokens": 19673,
     "cost_inr": "6.73",
     "claims": 1,
     "avg_cost_per_claim_inr": "6.73"
    }
   ],
   "complexity_basis": "claims.risk_tier (LOW=simple, MEDIUM=standard, HIGH=complex)"
  },
  "orchestration_tasks_needing_attention": 1,
  "stuck_threshold_hours": 24,
  "is_synthetic_demo": true,
  "note": "Values are computed live from the agent trace store over DEMO / SYNTHETIC data. Token counts are estimated.",
  "generated_at": "2026-11-27T18:35:39.164411+00:00"
 },
 "approval_queue": {
  "pending_approvals": [],
  "open_human_tasks": [
   {
    "task_id": "49564af8-3114-40bf-8799-725a43c75626",
    "claim_id": "clm-sla-0105",
    "claim_number": "CLM-DEMO-2026-0105",
    "task_type": "document_request",
    "title": "Collect missing evidence: RC, FIR copy",
    "assigned_role": "policyholder",
    "priority": "high",
    "created_by_agent": "document_intelligence",
    "status": "open"
   },
   {
    "task_id": "7bb860d3-e25d-4b3f-b653-531bc463b699",
    "claim_id": "clm-sla-0107",
    "claim_number": "CLM-DEMO-2026-0107",
    "task_type": "estimate_review",
    "title": "Review garage estimate",
    "assigned_role": "claims_handler",
    "priority": "medium",
    "created_by_agent": "estimate_validation",
    "status": "open"
   },
   {
    "task_id": "b37a6b26-f252-4d52-a771-d6a8776abdf5",
    "claim_id": "clm-sla-0106",
    "claim_number": "CLM-DEMO-2026-0106",
    "task_type": "estimate_review",
    "title": "Review garage estimate",
    "assigned_role": "claims_handler",
    "priority": "medium",
    "created_by_agent": "estimate_validation",
    "status": "open"
   },
   {
    "task_id": "c3930f07-9fb0-41d9-9602-9f7596284cf2",
    "claim_id": "clm-sla-0108",
    "claim_number": "CLM-DEMO-2026-0108",
    "task_type": "estimate_review",
    "title": "Review garage estimate",
    "assigned_role": "claims_handler",
    "priority": "medium",
    "created_by_agent": "estimate_validation",
    "status": "open"
   },
   {
    "task_id": "28ef946e-3ca1-4efb-aebe-b84a9ed29d68",
    "claim_id": "clm-demo-0001",
    "claim_number": "CLM-DEMO-2026-0001",
    "task_type": "estimate_review",
    "title": "Review duplicated Front Bumper line & +38.5% Fender rate variance",
    "assigned_role": "claims_handler",
    "priority": "high",
    "created_by_agent": "estimate_validation",
    "status": "open"
   },
   {
    "task_id": "44e3e34a-b89e-4fa7-8753-c21e8dca5c99",
    "claim_id": "clm-demo-0001",
    "claim_number": "CLM-DEMO-2026-0001",
    "task_type": "siu_investigation",
    "title": "SIU Review: FRD-EST-ANOMALY (Alert-only lead)",
    "assigned_role": "siu_investigator",
    "priority": "medium",
    "created_by_agent": "fraud_intelligence",
    "status": "open"
   },
   {
    "task_id": "91299c07-2b4e-4b6e-a4ec-f9f8e35742b6",
    "claim_id": "clm-demo-0010",
    "claim_number": "CLM-DEMO-2026-0010",
    "task_type": "tp_evidence_and_facts",
    "title": "[TP] Evidence And Facts - TP-DEMO-2026-0010",
    "assigned_role": "claims_handler",
    "priority": "high",
    "created_by_agent": "tp_workflow_engine",
    "status": "open"
   },
   {
    "task_id": "bb3dc47c-cf9a-4098-98f4-b615cddd5527",
    "claim_id": "clm-demo-0010",
    "claim_number": "CLM-DEMO-2026-0010",
    "task_type": "tp_police_fir",
    "title": "[TP] Police Fir - TP-DEMO-2026-0010",
    "assigned_role": "claims_handler",
    "priority": "high",
    "created_by_agent": "tp_workflow_engine",
    "status": "open"
   },
   {
    "task_id": "d4b76a45-c46e-4d84-b44f-46b20d0e0f30",
    "claim_id": "clm-demo-0010",
    "claim_number": "CLM-DEMO-2026-0010",
    "task_type": "tp_liability_investigation",
    "title": "[TP] Liability Investigation - TP-DEMO-2026-0010",
    "assigned_role": "claims_handler",
    "priority": "high",
    "created_by_agent": "tp_workflow_engine",
    "status": "open"
   },
   {
    "task_id": "d79087a3-7351-45cc-b784-3d4addfb2c10",
    "claim_id": "clm-demo-0011",
    "claim_number": "CLM-DEMO-2026-0011",
    "task_type": "ev_case_stage_safe_recovery_isolation",
    "title": "[EV] Flatbed recovery, HV isolation & quarantine - EV-DEMO-2026-0011",
    "assigned_role": "claims_handler",
    "priority": "urgent",
    "created_by_agent": "ev_workflow_engine",
    "status": "open"
   },
   {
    "task_id": "7c3b36ad-8f3b-4148-9021-c4c7ed54bb73",
    "claim_id": "clm-demo-0011",
    "claim_number": "CLM-DEMO-2026-0011",
    "task_type": "ev_case_stage_specialist_survey",
    "title": "[EV] EV-HV certified physical survey - EV-DEMO-2026-0011",
    "assigned_role": "surveyor",
    "priority": "urgent",
    "created_by_agent": "ev_workflow_engine",
    "status": "open"
   },
   {
    "task_id": "57a0b3df-6284-47bb-9da3-9ee7a6fef1cb",
    "claim_id": "clm-demo-0011",
    "claim_number": "CLM-DEMO-2026-0011",
    "task_type": "ev_case_stage_oem_diagnostics",
    "title": "[EV] OEM diagnostic scan & HV tests - EV-DEMO-2026-0011",
    "assigned_role": "garage",
    "priority": "urgent",
    "created_by_agent": "ev_workflow_engine",
    "status": "open"
   },
   {
    "task_id": "22d29c22-17c6-4fdb-8bb2-a668c51424c8",
    "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
    "claim_number": "CLM-DEMO-2026-45805C",
    "task_type": "estimate_submission",
    "title": "Awaiting Garage Repair Estimate Submission",
    "assigned_role": "garage",
    "priority": "medium",
    "created_by_agent": "estimate_validation",
    "status": "open"
   },
   {
    "task_id": "4eecf856-f72f-408b-9a2f-d2e3c59092e1",
    "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
    "claim_number": "CLM-DEMO-2026-45805C",
    "task_type": "qa_remediation",
    "title": "QA Closure Blocked: resolve 1 control(s)",
    "assigned_role": "claims_handler",
    "priority": "high",
    "created_by_agent": "qa_compliance",
    "status": "open"
   },
   {
    "task_id": "ac871d50-7938-4b2f-a39d-172b2966c15c",
    "claim_id": "951fea1a-99b1-48e2-a63a-f35dd6ced7da",
    "claim_number": "CLM-DEMO-2026-45805C",
    "task_type": "rework",
    "title": "Rework Required -> settlement_recommendation (RC_QA_CONFIRMED_PAYMENT_OR_DECLINED)",
    "assigned_role": "claims_handler",
    "priority": "high",
    "created_by_agent": "qa_compliance",
    "status": "open"
   }
  ],
  "agent_escalations_awaiting_human": [],
  "claims_in_human_review": [
   {
    "claim_id": "clm-demo-0010",
    "claim_number": "CLM-DEMO-2026-0010",
    "next_expected_action": "TP Liability Investigation: claims handler action required (human-gated, queue tp_liability_investigation)"
   }
  ]
 }
};
