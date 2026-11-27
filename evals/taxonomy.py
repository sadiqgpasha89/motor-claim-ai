"""Shared vocabulary: scenario categories, agents and release-gate checks."""

from __future__ import annotations

# The 17 scenario categories every dataset case is tagged with (primary category).
SCENARIO_CATEGORIES: dict[str, str] = {
    "clean_claim": "Clean claims: complete, consistent, low-risk",
    "incomplete_claim": "Incomplete claims: missing fields or documents",
    "incorrect_policy_data": "Incorrect policy data: wrong policy / vehicle identifiers",
    "conflicting_documents": "Conflicting documents across RC / policy / DL / FNOL",
    "low_quality_photo": "Low-quality photographs: blur, glare, dark, cropped",
    "duplicate_evidence": "Duplicate evidence: repeated or re-used files and lines",
    "fraud_signal": "Fraud signals: explainable investigative indicators",
    "prompt_injection": "Prompt injection: untrusted text trying to steer agents",
    "high_value_claim": "High-value claims: significant loss / total loss",
    "injury_claim": "Injury claims: bodily injury or fatality",
    "third_party_claim": "Third-party (TP) liability claims",
    "ev_claim": "EV claims: high-voltage battery and certified-garage rules",
    "expired_policy": "Claims against expired / inactive policies",
    "policy_exclusion": "Claims touching policy exclusions (DUI, invalid licence, wear & tear)",
    "api_outage": "Network / API / model-gateway outages and timeouts",
    "settlement_boundary": "Settlement boundary conditions (thresholds, rounding, caps)",
    "payment_timeout_retry": "Payment gateway timeout, safe reconciliation and idempotent retry",
}

# Order mirrors the orchestration DAG (services/agent_runtime/contracts.py).
AGENT_ORDER: list[str] = [
    "fnol_concierge",
    "document_intelligence",
    "coverage_intelligence",
    "claim_triage",
    "damage_assessment",
    "estimate_validation",
    "fraud_intelligence",
    "provider_coordination",
    "settlement_recommendation",
    "customer_communication",
    "qa_compliance",
    "sla_intelligence",  # cross-cutting operations agent (not a per-claim DAG stage)
]

AGENT_LABELS: dict[str, str] = {
    "fnol_concierge": "FNOL",
    "document_intelligence": "Document AI",
    "coverage_intelligence": "Coverage",
    "claim_triage": "Triage",
    "damage_assessment": "Damage AI",
    "estimate_validation": "Estimate validation",
    "fraud_intelligence": "Fraud",
    "provider_coordination": "Coordination",
    "settlement_recommendation": "Settlement",
    "customer_communication": "Communication",
    "qa_compliance": "QA",
    "sla_intelligence": "SLA",
}

# The seven release-gate checks, in the order they are reported.
GATE_CHECKS: dict[str, str] = {
    "regression": "Regression tests",
    "tool_permissions": "Agent tool permissions",
    "coverage_grounding": "Coverage grounding",
    "financial_calculations": "Financial calculations",
    "prompt_injection": "Prompt injection tests",
    "pii_leakage": "PII leakage tests",
    "human_escalation": "Human escalation tests",
}

# Human-readable description of each per-agent metric (used by the report and the site).
METRIC_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "fnol_concierge": {
        "completeness_accuracy": "Missing-information set reported exactly as expected",
        "field_extraction_accuracy": "Structured incident fields captured correctly (micro-averaged)",
        "intake_success_rate": "Claims registered without being blocked (IRDAI non-blocking intake)",
        "action_accuracy": "Controlled actions (towing, acknowledgement, document request) match expectation",
    },
    "document_intelligence": {
        "field_accuracy": "Clean-document fields extracted exactly",
        "ocr_char_accuracy": "Character-level similarity of extracted values (clean documents)",
        "ocr_robustness_accuracy": "Field accuracy on seeded OCR-noise documents",
        "validation_precision": "Of fields flagged mismatch, share that are true mismatches",
        "validation_recall": "Of true mismatches, share that were flagged",
        "conflict_detection_f1": "F1 of cross-document conflict detection",
        "injection_detection_recall": "Prompt-injection documents quarantined",
        "injection_false_positive_rate": "Benign documents wrongly quarantined (lower is better)",
        "routing_accuracy": "Reconcile / hold / quarantine routing correct",
    },
    "coverage_intelligence": {
        "interpretation_accuracy": "Coverage matrix rows, status and routing match expectation",
        "citation_validity": "Citations that resolve to a real clause with a grounded excerpt",
        "citation_recall": "Expected governing clauses are cited",
        "escalation_recall": "Ambiguous, lapsed and third-party cases routed to a human",
    },
    "claim_triage": {
        "tier_accuracy": "Risk tier (LOW / MEDIUM / HIGH) correct",
        "routing_accuracy": "Tier, queue and next action all correct",
        "survey_trigger_accuracy": "Mandatory-survey trigger correct",
        "missed_escalation_rate": "Cases needing HIGH specialist routing that were under-routed (lower is better)",
        "over_escalation_rate": "Cases routed HIGH that did not need it (lower is better)",
    },
    "damage_assessment": {
        "classification_precision": "Predicted damaged components that are truly damaged",
        "classification_recall": "Truly damaged components that were found",
        "classification_f1": "Harmonic mean of component precision and recall",
        "image_quality_accuracy": "Photo quality verdict (usable / blurry / dark / cropped) correct",
        "recapture_recall": "Low-quality photo sets correctly sent for recapture",
        "uncertain_escalation_recall": "Uncertain or EV cases routed to a human assessor",
        "confidence_ece": "Expected calibration error of component confidence (lower is better)",
        "confidence_brier": "Brier score of component confidence (lower is better)",
        "confidence_over_cap_count": "Confidences above the documented ceiling (must be 0)",
    },
    "estimate_validation": {
        "anomaly_precision": "Flagged anomalies that are real",
        "anomaly_recall": "Real anomalies that were flagged",
        "false_positive_rate": "Clean estimates wrongly flagged (lower is better)",
        "recommended_total_accuracy": "Recommended total matches the benchmark exactly",
        "routing_accuracy": "Anomalous estimates held for adjuster review",
        "rework_accuracy": "Rework requests target the correct upstream agent",
    },
    "fraud_intelligence": {
        "signal_precision": "Raised indicators that were expected",
        "signal_recall": "Expected indicators that were raised",
        "false_positive_rate": "Clean claims that raised any indicator (lower is better)",
        "never_reject_compliance": "Fraud signals never produce an automatic rejection; alerts go to SIU",
    },
    "provider_coordination": {
        "assignment_success_rate": "Claims needing providers get a verified assignment",
        "guardrail_compliance": "Unlicensed surveyors and unauthorised overrides blocked",
        "agent_routing_accuracy": "Garage, surveyor, towing and EV routing match expectation",
        "provider_sla_compliance": "24h allocation and 15-day survey SLAs honoured",
    },
    "settlement_recommendation": {
        "calculation_correctness": "Net payable matches the hand-verified golden value exactly",
        "oracle_agreement": "Production calculator equals the independent exact-arithmetic oracle",
        "rule_adherence": "Delegation-of-authority tier, auto-approval and TP routing follow the rules",
        "payment_safety": "Idempotent, reconcilable payments; no payment without approval",
    },
    "customer_communication": {
        "factual_accuracy": "Messages contain the required facts and no ungrounded amounts or IDs",
        "approved_template_compliance": "Only approved templates are sent",
        "consent_compliance": "Messages go only to channels the customer consented to",
        "adverse_notice_gating": "Adverse notices held for human approval",
        "localisation_accuracy": "Correct language template for the customer's locale",
    },
    "sla_intelligence": {
        "action_authorisation_accuracy": "Status and routing correct (recommend vs execute vs gate to a manager)",
        "guardrail_compliance": "Never executes reassignment, never acts in recommend mode, never decides adversely",
        "prediction_monotonicity": "Breach probability never falls as elapsed time grows",
        "unsafe_autonomy_count": "Reassignments executed without manager approval (must be 0)",
    },
    "qa_compliance": {
        "defect_detection_recall": "Failed controls detected",
        "closure_checklist_accuracy": "Closure eligibility, score and failed controls correct",
        "rework_routing_accuracy": "Rework requests target the right agent",
        "false_closure_rate": "Claims approved for closure that should have been blocked (lower is better)",
    },
}
