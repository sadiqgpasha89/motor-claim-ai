# Specialised Agents & Tool Permissions (`agents/specialists.py`)

All 11 agents inherit from `BoundedAgent` (`services/agent_runtime/base.py`), accept `AgentInvocationRequest` with PII-masked `minimised_facts`, and return `AgentInvocationResponse` with `status` (`completed | needs_human | insufficient_evidence | failed`), `confidence_band`, `evidence_refs`, `limitations`, `model_id`, `prompt_version`, and `rule_versions`.

| Agent | Allowed Tools | Hard Guardrail |
|---|---|---|
| `fnol_concierge` | `create_intimation`, `policy_lookup`, `faq_retrieval`, `request_upload` | Cannot decide coverage or close claim |
| `document_intelligence` | `evidence_read`, `ocr_extract`, `schema_validate`, `duplicate_check` | Quarantines prompt injection; marks OCR unverified |
| `coverage_intelligence` | `policy_read`, `policy_rag`, `deterministic_coverage_rules` | Cannot repudiate; routes ambiguity to human |
| `claim_triage` | `claim_facts_read`, `triage_rules_read`, `queue_recommend` | Uses operational risk signals only |
| `damage_assessment` | `vision_model`, `image_quality_check`, `vehicle_taxonomy` | Distinguishes `visible_observed` vs `inferred_possible` |
| `estimate_validation` | `parts_catalogue`, `rate_card_read`, `estimate_parser`, `duplicate_line_rules` | Cannot silently alter garage estimate |
| `fraud_intelligence` | `fraud_feature_service`, `fraud_rules`, `entity_graph_query` | Alert-only; never auto-rejects or holds payout |
| `provider_coordination` | `verified_roster_read`, `provider_scorecard`, `schedule_notify` | Rejects unlicensed surveyors |
| `settlement_recommendation` | `deterministic_calculator`, `policy_facts_read`, `survey_report_read` | Always returns `needs_human` for DoA approval |
| `customer_communication` | `approved_templates`, `communication_preference`, `claim_status_read` | Adverse messages gated on human review |
| `qa_compliance` | `readonly_audit`, `workflow_read`, `rules_read`, `evidence_read` | Read-only verifier; cannot self-override |
