from __future__ import annotations

from decimal import Decimal

from packages.contracts.agents import (
    AgentInvocationRequest,
    AgentInvocationResponse,
    AgentStatus,
    ConfidenceBand,
    EvidenceCitation,
)
from services.agent_runtime.base import BoundedAgent
from services.agent_runtime.gateway import ModelGateway
from services.rules_engine.knowledge import HybridPolicyRetriever
from services.rules_engine.loader import load_rule_files


class FNOLConciergeAgent(BoundedAgent):
    agent_name = "fnol_concierge"
    prompt_version = "fnol-v1.0"
    allowed_tools = {"create_intimation", "policy_lookup", "faq_retrieval", "request_upload"}

    def _run(self, request: AgentInvocationRequest, *, model_id: str, model_version: str) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="fnol_intake", facts=request.minimised_facts)
        facts = request.minimised_facts
        missing = []
        for field in ["policy_number", "vehicle_reg", "incident_description", "incident_location"]:
            if not facts.get(field):
                missing.append(field)

        conf = 0.92 if not missing else 0.72
        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=AgentStatus.COMPLETED if not missing else AgentStatus.INSUFFICIENT_EVIDENCE,
            result={
                "registration_allowed": True,
                "normalised_channel": facts.get("intake_channel", "web"),
                "recommended_checklist": ["Policy Schedule", "Registration Certificate (RC)", "Driving Licence (DL)", "6-Angle Vehicle Photos"],
                "note": "Claim intimation accepted even if documents are pending (IRDAI Master Circular 2024).",
            },
            confidence=conf,
            confidence_band=self._band(conf),
            evidence_refs=[
                EvidenceCitation(
                    source_type="rule",
                    source_id="IN-IRDAI-MC-2024",
                    reference="IRDAI/PP&GR/CIR/MISC/117/9/2024",
                    excerpt="Claim intimation must not be blocked or rejected merely for want of documents.",
                )
            ],
            missing_information=missing,
            limitations=["Does not decide coverage or liability at intake stage."],
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action="request_evidence_upload" if missing else "run_coverage_check",
            tools_invoked=["policy_lookup"],
        )


class DocumentIntelligenceAgent(BoundedAgent):
    agent_name = "document_intelligence"
    prompt_version = "doc-intel-v1.0"
    allowed_tools = {"evidence_read", "ocr_extract", "schema_validate", "duplicate_check"}

    def _run(self, request: AgentInvocationRequest, *, model_id: str, model_version: str) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="document_intelligence", facts=request.minimised_facts)
        facts_list = request.minimised_facts.get("extracted_facts", [])
        mismatches = [f for f in facts_list if f.get("validation_status") == "mismatch"]
        inj_flagged = bool(request.minimised_facts.get("prompt_injection_flagged", False))

        contradictions = []
        if mismatches:
            contradictions.append("Extracted policy or vehicle registration differs from claim intimation; human correction required.")
        if inj_flagged:
            contradictions.append("Untrusted instruction text detected inside uploaded document and quarantined.")

        conf = 0.52 if (mismatches or inj_flagged) else (0.89 if facts_list else 0.45)
        status = AgentStatus.NEEDS_HUMAN if (mismatches or inj_flagged or not facts_list) else AgentStatus.COMPLETED
        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=status,
            result={"fact_count": len(facts_list), "mismatches": mismatches, "injection_quarantined": inj_flagged},
            confidence=conf,
            confidence_band=self._band(conf),
            contradictions=contradictions,
            missing_information=[] if facts_list else ["Readable RC, DL, or Policy Schedule"],
            limitations=["OCR fields are marked unverified until confirmed by an authorised claims handler."],
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action="human_fact_verification" if status == AgentStatus.NEEDS_HUMAN else "run_coverage_check",
            tools_invoked=["evidence_read", "ocr_extract", "schema_validate"],
        )


class CoverageIntelligenceAgent(BoundedAgent):
    agent_name = "coverage_intelligence"
    prompt_version = "coverage-v1.0"
    allowed_tools = {"policy_read", "policy_rag", "deterministic_coverage_rules"}

    def _run(self, request: AgentInvocationRequest, *, model_id: str, model_version: str) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="coverage_check", facts=request.minimised_facts)
        retriever = HybridPolicyRetriever()
        facts = request.minimised_facts
        peril = facts.get("peril_cause", "road_accident")
        is_ev = bool(facts.get("is_ev", False))
        query = f"{peril} own damage exclusions depreciation {'ev battery high voltage' if is_ev else ''}"
        hits = retriever.search(query, top_k=4)

        period_valid = bool(facts.get("period_valid", True))
        policy_active = facts.get("policy_status", "active") == "active"
        has_mismatch = bool(facts.get("has_document_mismatch", False))
        missing_docs = facts.get("missing_documents", [])

        citations = [
            EvidenceCitation(
                source_type="policy_clause",
                source_id=h["document_id"],
                reference=h["reference"],
                excerpt=h["text"][:220],
            )
            for h in hits
        ]

        ambiguities: list[str] = []
        if not period_valid or not policy_active:
            ambiguities.append("Policy period or active status check failed; mandatory human legal/claims review before any adverse decision.")
        if has_mismatch:
            ambiguities.append("Document mismatch on policy/vehicle identity must be resolved by human adjuster.")
        if facts.get("claim_type") == "third_party" or facts.get("injury_or_fatality"):
            ambiguities.append("Third-party injury/fatality requires specialist Legal/TP review; AI cannot determine legal liability.")

        conf = 0.91 if (period_valid and policy_active and not has_mismatch) else 0.55
        status = AgentStatus.NEEDS_HUMAN if ambiguities else AgentStatus.COMPLETED
        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=status,
            result={
                "supported_facts": [
                    f"Policy status: {facts.get('policy_status', 'unknown')}",
                    f"Incident within policy period: {period_valid}",
                    f"Add-ons active: {facts.get('addons', {})}",
                ],
                "possible_exclusions_to_verify": ["Valid driving licence at time of incident (SEC-1-3)", "Intoxication/consequential loss check (SEC-1-3)"],
                "missing_evidence": missing_docs,
                "clauses_requiring_human_interpretation": ambiguities,
                "retrieved_clauses": hits,
            },
            confidence=conf,
            confidence_band=self._band(conf),
            evidence_refs=citations,
            contradictions=ambiguities,
            limitations=["Coverage factsheet is advisory; repudiation requires human claims/legal sign-off."],
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action="human_coverage_review" if ambiguities else "run_triage",
            tools_invoked=["policy_read", "policy_rag", "deterministic_coverage_rules"],
        )


class ClaimTriageAgent(BoundedAgent):
    agent_name = "claim_triage"
    prompt_version = "triage-v1.0"
    allowed_tools = {"claim_facts_read", "triage_rules_read", "queue_recommend"}

    def _run(self, request: AgentInvocationRequest, *, model_id: str, model_version: str) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="claim_triage", facts=request.minimised_facts)
        rules = load_rule_files()["IN-IRDAI-MC-2024"]["controls"]
        threshold = Decimal(str(rules["mandatory_survey_threshold_inr"]))
        facts = request.minimised_facts

        est_loss = Decimal(str(facts.get("estimated_loss_inr", "0.00")))
        injury = bool(facts.get("injury_or_fatality", False))
        ev_impact = bool(facts.get("ev_battery_impacted", False)) or bool(facts.get("is_ev", False))
        claim_type = facts.get("claim_type", "own_damage")
        peril = facts.get("peril_cause", "road_accident")

        requires_survey = est_loss >= threshold or peril in {"theft", "fire", "flood", "total_loss"} or injury or ev_impact

        if injury or claim_type == "third_party":
            queue = "legal_tp_specialist"
            severity = "critical"
        elif ev_impact:
            queue = "ev_specialist"
            severity = "high"
        elif peril in {"theft", "fire", "flood"} or est_loss >= Decimal("250000"):
            queue = "complex_od_survey"
            severity = "high"
        elif requires_survey:
            queue = "standard_survey_queue"
            severity = "medium"
        else:
            queue = "low_risk_od_assisted"
            severity = "low"

        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=AgentStatus.COMPLETED,
            result={
                "severity_band": severity,
                "recommended_queue": queue,
                "requires_mandatory_survey": requires_survey,
                "survey_threshold_inr": str(threshold),
                "signals_used": {
                    "estimated_loss_inr": str(est_loss),
                    "injury_or_fatality": injury,
                    "ev_battery_impacted": ev_impact,
                    "peril_cause": peril,
                },
            },
            confidence=0.93,
            confidence_band=ConfidenceBand.HIGH,
            evidence_refs=[
                EvidenceCitation(
                    source_type="rule",
                    source_id="IN-IRDAI-MC-2024",
                    reference="Mandatory survey >= INR 50,000",
                    excerpt=f"Estimated loss INR {est_loss} vs threshold INR {threshold}.",
                )
            ],
            limitations=["Triage uses operational risk/complexity signals only; never protected traits."],
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action="assign_surveyor" if requires_survey else "ai_damage_assessment",
            tools_invoked=["claim_facts_read", "triage_rules_read", "queue_recommend"],
        )


class DamageAssessmentAgent(BoundedAgent):
    agent_name = "damage_assessment"
    prompt_version = "damage-v1.0"
    allowed_tools = {"vision_model", "image_quality_check", "vehicle_taxonomy"}

    def _run(self, request: AgentInvocationRequest, *, model_id: str, model_version: str) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="damage_assessment", facts=request.minimised_facts)
        res = request.minimised_facts.get("assessment_payload", {})
        recapture = res.get("recapture_required_files", [])
        missing_angles = res.get("missing_angles", [])
        conf = 0.62 if (recapture or len(missing_angles) > 3) else 0.86
        status = AgentStatus.NEEDS_HUMAN if recapture else AgentStatus.COMPLETED
        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=status,
            result=res,
            confidence=conf,
            confidence_band=self._band(conf),
            missing_information=[f"Missing photo angle: {a}" for a in missing_angles],
            limitations=["Assistive visual output only; hidden structural/mechanical damage cannot be confirmed from photos."],
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action="request_photo_recapture" if recapture else "validate_estimate",
            tools_invoked=["vision_model", "image_quality_check"],
        )


class EstimateValidationAgent(BoundedAgent):
    agent_name = "estimate_validation"
    prompt_version = "estimate-v1.0"
    allowed_tools = {"parts_catalogue", "rate_card_read", "estimate_parser", "duplicate_line_rules"}

    def _run(self, request: AgentInvocationRequest, *, model_id: str, model_version: str) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="estimate_validation", facts=request.minimised_facts)
        validation = request.minimised_facts.get("estimate_validation", {})
        anomalies = validation.get("anomalies", [])
        conf = 0.74 if anomalies else 0.92
        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=AgentStatus.NEEDS_HUMAN if anomalies else AgentStatus.COMPLETED,
            result=validation,
            confidence=conf,
            confidence_band=self._band(conf),
            contradictions=[a.get("message", "") for a in anomalies],
            limitations=["Cannot alter garage estimate silently; adjuster/surveyor must accept, amend, or reject lines."],
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action="adjuster_estimate_review" if anomalies else "calculate_settlement",
            tools_invoked=["parts_catalogue", "rate_card_read", "duplicate_line_rules"],
        )


class FraudIntelligenceAgent(BoundedAgent):
    agent_name = "fraud_intelligence"
    prompt_version = "fraud-v1.0"
    allowed_tools = {"fraud_feature_service", "fraud_rules", "entity_graph_query"}

    def _run(self, request: AgentInvocationRequest, *, model_id: str, model_version: str) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="fraud_intelligence", facts=request.minimised_facts)
        indicators = request.minimised_facts.get("indicators", [])
        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=AgentStatus.NEEDS_HUMAN if indicators else AgentStatus.COMPLETED,
            result={"alert_count": len(indicators), "indicators": indicators},
            confidence=0.78 if indicators else 0.90,
            confidence_band=ConfidenceBand.MEDIUM if indicators else ConfidenceBand.HIGH,
            limitations=[
                "Indicators are investigative leads only. Alert alone NEVER establishes fraud or blocks/rejects a claim."
            ],
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action="refer_to_siu_queue" if indicators else "proceed_workflow",
            tools_invoked=["fraud_feature_service", "fraud_rules", "entity_graph_query"],
        )


class ProviderCoordinationAgent(BoundedAgent):
    agent_name = "provider_coordination"
    prompt_version = "provider-v1.0"
    allowed_tools = {"verified_roster_read", "provider_scorecard", "schedule_notify"}

    def _run(self, request: AgentInvocationRequest, *, model_id: str, model_version: str) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="provider_coordination", facts=request.minimised_facts)
        candidate = request.minimised_facts.get("recommended_provider")
        status = AgentStatus.COMPLETED if candidate else AgentStatus.NEEDS_HUMAN
        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=status,
            result={"recommended_provider": candidate},
            confidence=0.91 if candidate else 0.40,
            confidence_band=self._band(0.91 if candidate else 0.40),
            missing_information=[] if candidate else ["No available licensed surveyor/EV-capable garage in city"],
            limitations=["Respects customer choice of network garage and verified licence status."],
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action="confirm_assignment" if candidate else "escalate_sla_capacity",
            tools_invoked=["verified_roster_read", "provider_scorecard"],
        )


class SettlementRecommendationAgent(BoundedAgent):
    agent_name = "settlement_recommendation"
    prompt_version = "settlement-v1.0"
    allowed_tools = {"deterministic_calculator", "policy_facts_read", "survey_report_read"}

    def _run(self, request: AgentInvocationRequest, *, model_id: str, model_version: str) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="settlement_recommendation", facts=request.minimised_facts)
        calc = request.minimised_facts.get("calculation", {})
        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=AgentStatus.NEEDS_HUMAN,  # Settlement always requires authorised human approval
            result=calc,
            confidence=0.95,
            confidence_band=ConfidenceBand.HIGH,
            limitations=["Agent cannot authorise payout; maker-checker and finance approval required."],
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action="route_to_maker_checker_approval",
            tools_invoked=["deterministic_calculator", "policy_facts_read"],
        )


class CustomerCommunicationAgent(BoundedAgent):
    agent_name = "customer_communication"
    prompt_version = "comm-v1.0"
    allowed_tools = {"approved_templates", "communication_preference", "claim_status_read"}

    def _run(self, request: AgentInvocationRequest, *, model_id: str, model_version: str) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="customer_communication", facts=request.minimised_facts)
        is_adverse = bool(request.minimised_facts.get("is_adverse", False))
        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=AgentStatus.NEEDS_HUMAN if is_adverse else AgentStatus.COMPLETED,
            result={"draft_message": request.minimised_facts.get("draft_message", ""), "requires_human_review": is_adverse},
            confidence=0.90,
            confidence_band=ConfidenceBand.HIGH,
            limitations=["Adverse or legal communications cannot be sent without human approval."],
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action="human_comm_review" if is_adverse else "dispatch_notification",
            tools_invoked=["approved_templates", "communication_preference"],
        )


class QAComplianceAgent(BoundedAgent):
    agent_name = "qa_compliance"
    prompt_version = "qa-v1.0"
    allowed_tools = {"readonly_audit", "workflow_read", "rules_read", "evidence_read"}

    def _run(self, request: AgentInvocationRequest, *, model_id: str, model_version: str) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="qa_compliance", facts=request.minimised_facts)
        checks = request.minimised_facts.get("checks", {})
        failures = [k for k, ok in checks.items() if not ok]
        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=AgentStatus.NEEDS_HUMAN if failures else AgentStatus.COMPLETED,
            result={"checks": checks, "failed_controls": failures},
            confidence=0.96,
            confidence_band=ConfidenceBand.HIGH,
            limitations=["Read-only compliance verifier; cannot mark failed controls as passed."],
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action="resolve_compliance_gaps" if failures else "eligible_for_closure",
            tools_invoked=["readonly_audit", "workflow_read", "rules_read"],
        )


AGENT_REGISTRY: dict[str, BoundedAgent] = {
    "fnol_concierge": FNOLConciergeAgent(),
    "document_intelligence": DocumentIntelligenceAgent(),
    "coverage_intelligence": CoverageIntelligenceAgent(),
    "claim_triage": ClaimTriageAgent(),
    "damage_assessment": DamageAssessmentAgent(),
    "estimate_validation": EstimateValidationAgent(),
    "fraud_intelligence": FraudIntelligenceAgent(),
    "provider_coordination": ProviderCoordinationAgent(),
    "settlement_recommendation": SettlementRecommendationAgent(),
    "customer_communication": CustomerCommunicationAgent(),
    "qa_compliance": QAComplianceAgent(),
}
