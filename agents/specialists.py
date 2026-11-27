from __future__ import annotations

from decimal import Decimal

from packages.contracts.agents import (
    AgentActionExecution,
    AgentInvocationRequest,
    AgentInvocationResponse,
    AgentStatus,
    ConfidenceBand,
    DecisionIntelligence,
    EvidenceCitation,
    ReworkRequest,
)
from services.agent_runtime.actions import ControlledActionExecutor
from services.agent_runtime.base import BoundedAgent
from services.agent_runtime.contracts import AGENT_CAPABILITY_CONTRACTS
from services.agent_runtime.gateway import ModelGateway
from services.damage_ai.assessor import assess_damage_from_evidence
from services.document_ai.processor import reconcile_claim_documents
from services.rules_engine.knowledge import HybridPolicyRetriever
from services.rules_engine.loader import load_rule_files
from services.workflow.risk_engine import classify_claim_risk_from_facts, compute_fraud_signal_score

_LOCALIZED_FNOL_ACK: dict[str, str] = {
    "en-IN": "Claim registered safely. Missing documents will never block intake (IRDAI 2024).",
    "hi-IN": "आपका मोटर दावा सफलतापूर्वक पंजीकृत हो गया है। अधूरे दस्तावेज़ों से पंजीकरण नहीं रुकेगा (IRDAI 2024)।",
    "mr-IN": "तुमचा मोटर दावा यशस्वीरित्या नोंदवला गेला आहे. अपूर्ण कागदपत्रांमुळे नोंदणी थांबणार नाही (IRDAI 2024).",
    "ta-IN": "உங்கள் மோட்டார் காப்பீட்டு கோரிக்கை பதிவு செய்யப்பட்டது. ஆவணங்கள் இல்லாததால் பதிவு தடுக்கப்படாது (IRDAI 2024).",
    "kn-IN": "ನಿಮ್ಮ ಮೋಟಾರ್ ಕ್ಲೈಮ್ ಯಶಸ್ವಿಯಾಗಿ ನೋಂದಾಯಿಸಲಾಗಿದೆ. ದಾಖಲೆಗಳ ಕೊರತೆಯಿಂದ ನೋಂದಣಿ ತಡೆಯಲಾಗುವುದಿಲ್ಲ (IRDAI 2024).",
}

_LOCALIZED_COMM_TEMPLATES: dict[str, dict[str, dict[str, str]]] = {
    "en-IN": {
        "status_update": {
            "subject": "Claim Status Update: {claim_number}",
            "body": "Claim {claim_number} ({vehicle}) is currently in '{status}'. Next step: {next_step}.",
        },
        "document_reminder": {
            "subject": "Document Reminder for {claim_number}",
            "body": "Please upload pending items ({missing_docs}) via Web, Mobile, or WhatsApp to keep {claim_number} moving.",
        },
        "delay_advisory": {
            "subject": "Delay Advisory & SLA Escalation Notice: {claim_number}",
            "body": "We detected a stage delay on {claim_number} ({delay_reason}). Priority escalation is active; expected next update within 24 hours.",
        },
        "next_steps": {
            "subject": "Next Steps for Your Motor Claim {claim_number}",
            "body": "Your next step on {claim_number}: {next_step}. Need roadside or garage support? Reply on WhatsApp or portal.",
        },
    },
    "hi-IN": {
        "status_update": {
            "subject": "दावा स्थिति अपडेट: {claim_number}",
            "body": "आपका दावा {claim_number} ({vehicle}) अभी '{status}' चरण में है। अगला कदम: {next_step}।",
        },
        "document_reminder": {
            "subject": "दस्तावेज़ अनुस्मारक: {claim_number}",
            "body": "कृपया {claim_number} के लिए लंबित दस्तावेज़ ({missing_docs}) वेब, मोबाइल या WhatsApp पर अपलोड करें।",
        },
        "delay_advisory": {
            "subject": "विलंब सूचना व प्राथमिकता एस्केलेशन: {claim_number}",
            "body": "आपके दावे {claim_number} में देरी ({delay_reason}) दर्ज की गई है। प्राथमिकता टीम सक्रिय है।",
        },
        "next_steps": {
            "subject": "दावा {claim_number} के अगले चरण",
            "body": "दावा {claim_number} पर अगला आवश्यक कदम: {next_step}।",
        },
    },
    "mr-IN": {
        "status_update": {
            "subject": "दावा स्थिती अद्यतन: {claim_number}",
            "body": "तुमचा दावा {claim_number} ({vehicle}) सध्या '{status}' टप्प्यात आहे. पुढील पाऊल: {next_step}.",
        },
        "document_reminder": {
            "subject": "कागदपत्र स्मरणपत्र: {claim_number}",
            "body": "कृपया {claim_number} साठी प्रलंबित कागदपत्रे ({missing_docs}) अपलोड करा.",
        },
        "delay_advisory": {
            "subject": "विलंब सूचना: {claim_number}",
            "body": "दावा {claim_number} वर विलंब ({delay_reason}) आढळला आहे. प्राधान्याने पाठपुरावा सुरू आहे.",
        },
        "next_steps": {
            "subject": "दावा {claim_number} साठी पुढील पावले",
            "body": "पुढील पाऊल: {next_step}.",
        },
    },
    "ta-IN": {
        "status_update": {
            "subject": "கோரிக்கை நிலை தகவல்: {claim_number}",
            "body": "உங்கள் கோரிக்கை {claim_number} ({vehicle}) தற்போது '{status}' நிலையில் உள்ளது. அடுத்த படி: {next_step}.",
        },
        "document_reminder": {
            "subject": "ஆவண நினைவூட்டல்: {claim_number}",
            "body": "{claim_number} கோரிக்கைக்கு நிலுவையுள்ள ஆவணங்களை ({missing_docs}) பதிவேற்றவும்.",
        },
        "delay_advisory": {
            "subject": "தாமத அறிவிப்பு: {claim_number}",
            "body": "{claim_number} கோரிக்கையில் தாமதம் ({delay_reason}) கண்டறியப்பட்டது; முன்னுரிமை நடவடிக்கை எடுக்கப்படுகிறது.",
        },
        "next_steps": {
            "subject": "அடுத்த கட்ட நடவடிக்கைகள்: {claim_number}",
            "body": "அடுத்த படி: {next_step}.",
        },
    },
    "kn-IN": {
        "status_update": {
            "subject": "ಕ್ಲೈಮ್ ಸ್ಥಿತಿ ನವೀಕರಣ: {claim_number}",
            "body": "ನಿಮ್ಮ ಕ್ಲೈಮ್ {claim_number} ({vehicle}) ಪ್ರಸ್ತುತ '{status}' ಹಂತದಲ್ಲಿದೆ. ಮುಂದಿನ ಹಂತ: {next_step}.",
        },
        "document_reminder": {
            "subject": "ದಾಖಲೆ ಜ್ಞಾಪನೆ: {claim_number}",
            "body": "ದಯವಿಟ್ಟು {claim_number} ಕ್ಕಾಗಿ ಬಾಕಿ ದಾಖಲೆಗಳನ್ನು ({missing_docs}) ಅಪ್‌ಲೋಡ್ ಮಾಡಿ.",
        },
        "delay_advisory": {
            "subject": "ವಿಳಂಬ ಮಾಹಿತಿ: {claim_number}",
            "body": "{claim_number} ಕ್ಲೈಮ್‌ನಲ್ಲಿ ವಿಳಂಬ ({delay_reason}) ಕಂಡುಬಂದಿದೆ; ಆದ್ಯತೆಯ ಕ್ರಮ ಕೈಗೊಳ್ಳಲಾಗಿದೆ.",
        },
        "next_steps": {
            "subject": "ಮುಂದಿನ ಹಂತಗಳು: {claim_number}",
            "body": "ಮುಂದಿನ ಕ್ರಮ: {next_step}.",
        },
    },
}


class FNOLConciergeAgent(BoundedAgent):
    agent_name = "fnol_concierge"
    prompt_version = "fnol-v2.0"
    allowed_tools = set(AGENT_CAPABILITY_CONTRACTS["fnol_concierge"].allowed_tools)

    def _run(
        self,
        request: AgentInvocationRequest,
        *,
        model_id: str,
        model_version: str,
        executor: ControlledActionExecutor,
    ) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="fnol_intake", facts=request.minimised_facts)
        facts = request.minimised_facts
        channel = str(facts.get("intake_channel", "web")).lower()
        if channel not in {"web", "mobile", "whatsapp", "voice"}:
            channel = "web"

        locale = str(facts.get("preferred_language") or request.locale or "en-IN")
        if locale not in _LOCALIZED_FNOL_ACK:
            locale = "en-IN"

        missing = [
            field
            for field in ["policy_number", "vehicle_reg", "incident_description", "incident_location"]
            if not facts.get(field)
        ]

        vehicle_immobile = bool(facts.get("vehicle_immobile", False))
        towing_needed = bool(facts.get("towing_needed", False)) or vehicle_immobile
        ev_impact = bool(facts.get("ev_battery_impacted", False))
        injury = bool(facts.get("injury_or_fatality", False))
        airbags = bool(facts.get("airbags_deployed", False))
        police = bool(facts.get("police_involved", False))
        checklist = list(
            facts.get(
                "missing_documents",
                ["Policy Schedule", "Registration Certificate (RC)", "Driving Licence (DL)", "6-Angle Vehicle Photos"],
            )
        )

        structured_incident = {
            "policy_number": facts.get("policy_number", ""),
            "vehicle_reg": facts.get("vehicle_reg", ""),
            "intake_channel": channel,
            "channel_transcript_captured": channel in {"voice", "whatsapp"} or bool(facts.get("channel_transcript")),
            "language": locale,
            "accident_location": {
                "address": facts.get("incident_location", ""),
                "geo_coords": facts.get("geo_coords"),
                "landmark": facts.get("location_landmark", ""),
            },
            "peril_cause": facts.get("peril_cause", "road_accident"),
            "drivable_status": "immobile" if vehicle_immobile else "drivable",
            "airbags_deployed": airbags,
            "injury_or_fatality": injury,
            "police_involved": police,
            "towing_needed": towing_needed,
            "ev_battery_impacted": ev_impact,
            "estimated_loss_inr": str(facts.get("estimated_loss_inr", "0.00")),
        }

        actions: list[AgentActionExecution] = []
        tools_used = ["policy_lookup", "create_intimation"]
        if checklist:
            actions.append(
                executor.request_documents(
                    agent_name=self.agent_name,
                    documents=checklist,
                    reason_code="RC_FNOL_INITIAL_CHECKLIST",
                    channel="whatsapp" if channel == "whatsapp" else "portal",
                )
            )
            tools_used.extend(["request_documents", "create_claim_task"])
        if towing_needed:
            actions.append(executor.dispatch_towing(agent_name=self.agent_name, ev_flatbed=ev_impact))
            tools_used.append("dispatch_towing")
        if facts.get("auto_send_ack"):
            actions.append(
                executor.send_customer_update(
                    agent_name=self.agent_name,
                    channel=channel if channel in {"whatsapp", "sms", "email"} else "portal",
                    language=locale,
                    template_id="FNOL_MULTILINGUAL_ACK",
                    subject=f"Claim Registered ({facts.get('policy_number', 'Motor')})",
                    body=_LOCALIZED_FNOL_ACK[locale],
                    is_adverse=False,
                )
            )
            tools_used.append("send_customer_update")

        reason_codes = [
            f"RC_CHANNEL_{channel.upper()}",
            f"RC_LOCALE_{locale.replace('-', '_').upper()}",
            "RC_IRDAI_NON_BLOCKING_INTAKE",
        ]
        if towing_needed:
            reason_codes.append("RC_TOWING_DISPATCHED")
        if missing:
            reason_codes.append("RC_STRUCTURED_FIELDS_PENDING")

        conf = 0.94 if not missing else 0.74
        routing = "registered_towing_priority" if towing_needed else ("registered_evidence_pending" if missing else "registered_ready_for_docs")
        result = {
            "registration_allowed": True,
            "normalised_channel": channel,
            "language": locale,
            "localized_acknowledgement": _LOCALIZED_FNOL_ACK[locale],
            "structured_incident": structured_incident,
            "recommended_checklist": checklist,
            "note": "Claim intimation accepted across omnichannel intake even if documents are pending (IRDAI Master Circular 2024).",
        }
        decision = DecisionIntelligence(
            decision_id=self._decision_id(self.agent_name),
            reason_codes=reason_codes,
            evidence=[
                f"Channel={channel}, Locale={locale}",
                f"Location={facts.get('incident_location', 'unspecified')}",
                f"Drivable={'immobile' if vehicle_immobile else 'drivable'}, Towing={towing_needed}",
            ],
            policy_rule_refs=["IN-IRDAI-MC-2024:1.0.0", "OMNICHANNEL-INTAKE-V2"],
            confidence=conf,
            confidence_band=self._band(conf),
            routing_outcome=routing,
            explanation=(
                f"Captured structured FNOL via {channel} ({locale}) at '{facts.get('incident_location', 'N/A')}'. "
                f"{'Dispatched towing priority task. ' if towing_needed else ''}"
                f"Issued {len(checklist)}-item upload checklist without blocking registration."
            ),
            alternatives_considered=["block_until_all_docs_uploaded (rejected per IRDAI Master Circular 2024)"],
        )

        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=AgentStatus.COMPLETED if not missing else AgentStatus.INSUFFICIENT_EVIDENCE,
            result=result,
            published_result=result,
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
            limitations=["Does not decide policy coverage or legal liability at FNOL stage."],
            actions_executed=actions,
            decision=decision,
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action="request_evidence_upload" if missing else "run_document_intelligence",
            tools_invoked=list(dict.fromkeys(tools_used)),
        )


class DocumentIntelligenceAgent(BoundedAgent):
    agent_name = "document_intelligence"
    prompt_version = "doc-intel-v2.0"
    allowed_tools = set(AGENT_CAPABILITY_CONTRACTS["document_intelligence"].allowed_tools)

    def _run(
        self,
        request: AgentInvocationRequest,
        *,
        model_id: str,
        model_version: str,
        executor: ControlledActionExecutor,
    ) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="document_intelligence", facts=request.minimised_facts)
        facts_list = request.minimised_facts.get("extracted_facts", [])
        evidences = request.minimised_facts.get("evidences", [])
        inj_flagged = bool(request.minimised_facts.get("prompt_injection_flagged", False))
        expected_pol = str(request.minimised_facts.get("policy_number", ""))
        expected_reg = str(request.minimised_facts.get("vehicle_reg", ""))

        recon = reconcile_claim_documents(
            evidences=evidences,
            extracted_facts=facts_list,
            expected_policy_number=expected_pol,
            expected_vehicle_reg=expected_reg,
        )
        mismatches = [f for f in facts_list if f.get("validation_status") == "mismatch"]
        conflicts = recon["conflicts"]

        contradictions: list[str] = []
        if mismatches or conflicts:
            contradictions.append(
                f"Detected {len(conflicts)} document discrepancy/conflict(s) across extracted fields; human verification required."
            )
        if inj_flagged:
            contradictions.append("Untrusted instruction text detected inside uploaded document and quarantined.")

        actions: list[AgentActionExecution] = []
        rework_requests: list[ReworkRequest] = []
        tools_used = ["evidence_read", "ocr_extract", "schema_validate", "reconcile_documents"]

        if inj_flagged or mismatches or conflicts:
            actions.append(
                executor.create_claim_task(
                    agent_name=self.agent_name,
                    task_type="document_reconciliation",
                    title="Resolve document conflict / quarantined OCR directive",
                    description="; ".join(contradictions),
                    assigned_role="claims_handler",
                    priority="high",
                    reason_code="RC_DOC_CONFLICT_OR_INJECTION",
                    due_hours=12,
                    metadata={"conflicts": conflicts},
                )
            )
            tools_used.append("create_claim_task")
            actions.append(
                executor.request_documents(
                    agent_name=self.agent_name,
                    documents=["Corrected RC / Policy Schedule verification"],
                    reason_code="RC_DOC_CONFLICT_CLARIFICATION",
                )
            )
            tools_used.append("request_documents")
        elif not facts_list:
            missing_docs = recon["missing_core_docs"] or ["Policy Schedule", "Registration Certificate (RC)", "Driving Licence (DL)"]
            actions.append(
                executor.request_documents(
                    agent_name=self.agent_name,
                    documents=[str(d) for d in missing_docs],
                    reason_code="RC_MISSING_CORE_DOCS",
                )
            )
            tools_used.append("request_documents")

        has_conflict_or_inj = bool(mismatches or conflicts or inj_flagged)
        conf = 0.52 if has_conflict_or_inj else (0.91 if facts_list else 0.45)
        status = AgentStatus.NEEDS_HUMAN if (has_conflict_or_inj or not facts_list) else AgentStatus.COMPLETED

        reason_codes = []
        if inj_flagged:
            reason_codes.append("RC_PROMPT_INJECTION_QUARANTINED")
        if conflicts or mismatches:
            reason_codes.append("RC_MULTI_DOC_CONFLICT_DETECTED")
        if not facts_list:
            reason_codes.append("RC_NO_EXTRACTED_FACTS")
        if not reason_codes:
            reason_codes.append("RC_MULTI_DOC_RECONCILED")

        routing = (
            "quarantine_prompt_injection"
            if inj_flagged
            else ("hold_conflicting_documents" if (conflicts or mismatches) else ("awaiting_core_documents" if not facts_list else "reconciled_ready_for_coverage"))
        )

        result = {
            "fact_count": len(facts_list),
            "mismatches": mismatches,
            "injection_quarantined": inj_flagged,
            "reconciliation_status": recon["reconciliation_status"],
            "field_confidences": recon["field_confidences"],
            "conflicts": conflicts,
            "provenance_index": recon["provenance_index"],
            "missing_core_docs": recon["missing_core_docs"],
        }
        decision = DecisionIntelligence(
            decision_id=self._decision_id(self.agent_name),
            reason_codes=reason_codes,
            evidence=[
                f"Extracted facts={len(facts_list)}, Evidences={len(evidences)}",
                f"Field confidences={recon['field_confidences']}",
                f"Conflicts={len(conflicts)}, Injection={inj_flagged}",
            ],
            policy_rule_refs=["SECURITY-SANITIZER-V1", "UNVERIFIED-OCR-PROVENANCE"],
            confidence=conf,
            confidence_band=self._band(conf),
            routing_outcome=routing,
            explanation=(
                "Quarantined prompt injection and halted auto-progression."
                if inj_flagged
                else (
                    f"Detected {len(conflicts)} conflict(s) across documents and routed to Clarification."
                    if (conflicts or mismatches)
                    else (
                        f"Reconciled {len(facts_list)} field(s) across {len(evidences)} document(s) with full SHA-256 & bbox provenance."
                        if facts_list
                        else "No extracted facts yet; requested core identity documents."
                    )
                )
            ),
            alternatives_considered=["auto_proceed_with_mismatch (blocked by identity guardrail)"],
        )

        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=status,
            result=result,
            published_result=result,
            confidence=conf,
            confidence_band=self._band(conf),
            evidence_refs=[
                EvidenceCitation(
                    source_type="extracted_provenance",
                    source_id=str(p.get("evidence_id") or "ev"),
                    reference=f"{p.get('source_filename', 'doc')} p.{p.get('page_number', 1)}",
                    excerpt=f"{p.get('field_name')}={p.get('value')} (conf={p.get('confidence')})",
                )
                for p in recon["provenance_index"][:5]
            ],
            contradictions=contradictions,
            missing_information=[] if facts_list else ["Readable RC, DL, or Policy Schedule"],
            limitations=["OCR fields remain unverified until spot-checked by an authorised claims handler."],
            actions_executed=actions,
            rework_requests=rework_requests,
            decision=decision,
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action="human_fact_verification" if status == AgentStatus.NEEDS_HUMAN else "run_coverage_check",
            tools_invoked=list(dict.fromkeys(tools_used)),
        )


class CoverageIntelligenceAgent(BoundedAgent):
    agent_name = "coverage_intelligence"
    prompt_version = "coverage-v2.0"
    allowed_tools = set(AGENT_CAPABILITY_CONTRACTS["coverage_intelligence"].allowed_tools)

    def _run(
        self,
        request: AgentInvocationRequest,
        *,
        model_id: str,
        model_version: str,
        executor: ControlledActionExecutor,
    ) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="coverage_check", facts=request.minimised_facts)
        retriever = HybridPolicyRetriever()
        facts = request.minimised_facts
        peril = str(facts.get("peril_cause", "road_accident"))
        is_ev = bool(facts.get("is_ev", False)) or bool(facts.get("ev_battery_impacted", False))
        query = f"{peril} own damage exclusions depreciation {'ev battery high voltage' if is_ev else ''}"
        hits = retriever.search(query, top_k=5)

        period_valid = bool(facts.get("period_valid", True))
        policy_active = facts.get("policy_status", "active") == "active"
        has_mismatch = bool(facts.get("has_document_mismatch", False))
        missing_docs = list(facts.get("missing_documents", []))
        addons = dict(facts.get("addons", {}))
        claim_type = str(facts.get("claim_type", request.claim_type))
        injury = bool(facts.get("injury_or_fatality", False))
        compulsory_excess = str(facts.get("compulsory_deductible_inr", "1000.00"))
        voluntary_excess = str(facts.get("voluntary_deductible_inr", "0.00"))
        idv_inr = str(facts.get("idv_inr", "780000.00"))

        coverage_matrix = [
            {
                "coverage_item": "Section I — Own Damage (Accidental External Means)",
                "status": "covered" if (period_valid and policy_active) else "ambiguous_hold",
                "clause_ref": "POL-WORDING-PC-2024 SEC-1-1 p.3",
                "deductible_impact": f"Compulsory INR {compulsory_excess} + Voluntary INR {voluntary_excess}",
            },
            {
                "coverage_item": "Section II — Third-Party Liability",
                "status": "conditional_legal_review" if (injury or claim_type == "third_party") else "covered_standby",
                "clause_ref": "POL-WORDING-PC-2024 SEC-2-1 p.7",
                "deductible_impact": "Statutory MV Act limits; Legal/TP review mandatory for injury",
            },
            {
                "coverage_item": "Zero Depreciation Waiver",
                "status": "covered" if addons.get("zero_depreciation") else "not_opted",
                "clause_ref": "POL-WORDING-PC-2024 ADDON-ZD-01 p.11",
                "deductible_impact": "Waives metal/plastic/fibreglass/paint part depreciation",
            },
            {
                "coverage_item": "Consumables Cover",
                "status": "covered" if addons.get("consumables") else "not_opted",
                "clause_ref": "POL-WORDING-PC-2024 ADDON-CONS-01 p.12",
                "deductible_impact": "Covers oil, coolant, AC gas, fasteners if opted",
            },
            {
                "coverage_item": "EV Traction Battery & HV Safety Protect",
                "status": "covered_with_bms_scan" if (is_ev and addons.get("ev_protect", True)) else ("ambiguous_ev_endorsement" if is_ev else "not_applicable"),
                "clause_ref": "POL-WORDING-EV-2025 EV-BAT-01 / EV-SAFE-01 p.2-3",
                "deductible_impact": "Requires HV isolation & certified EV garage",
            },
            {
                "coverage_item": "Constructive Total Loss (CTL >= 75% IDV)",
                "status": "covered_cap_idv",
                "clause_ref": "POL-WORDING-PC-2024 SEC-1-4 p.6",
                "deductible_impact": f"IDV Cap INR {idv_inr}; salvage deducted on CTL",
            },
        ]

        exclusions_checklist = [
            {"exclusion": "Valid Driving Licence at incident time", "clause": "SEC-1-3 p.5", "status": "verify_dl"},
            {"exclusion": "Intoxication / DUI", "clause": "SEC-1-3 p.5", "status": "check_fir_if_applicable"},
            {"exclusion": "Consequential Loss / Wear & Tear", "clause": "SEC-1-3 p.5", "status": "screen_estimate"},
        ]

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
        rework_requests: list[ReworkRequest] = []
        actions: list[AgentActionExecution] = []
        tools_used = ["policy_read", "policy_rag", "deterministic_coverage_rules"]

        if not period_valid or not policy_active:
            ambiguities.append("Policy period or active status check failed; mandatory human legal/claims review before any adverse decision.")
        if has_mismatch:
            ambiguities.append("Document mismatch on policy/vehicle identity must be resolved by Document Intelligence / adjuster.")
            rework_requests.append(
                ReworkRequest(
                    from_agent=self.agent_name,
                    to_agent="document_intelligence",
                    reason_code="RC_REWORK_IDENTITY_MISMATCH",
                    instructions="Re-extract and reconcile Policy/RC registration numbers before confirming coverage.",
                    blocking=True,
                )
            )
        if claim_type == "third_party" or injury:
            ambiguities.append("Third-party injury/fatality requires specialist Legal/TP review; AI cannot determine legal liability.")

        if ambiguities:
            actions.append(
                executor.create_claim_task(
                    agent_name=self.agent_name,
                    task_type="coverage_review",
                    title="Human Coverage / Legal Ambiguity Review",
                    description=" | ".join(ambiguities),
                    assigned_role="legal_tp" if (injury or claim_type == "third_party") else "claims_handler",
                    priority="critical" if injury else "high",
                    reason_code="RC_COVERAGE_AMBIGUITY",
                    due_hours=12,
                )
            )
            tools_used.append("create_claim_task")

        conf = 0.92 if not ambiguities else 0.55
        status = AgentStatus.REWORK_REQUIRED if has_mismatch else (AgentStatus.NEEDS_HUMAN if ambiguities else AgentStatus.COMPLETED)
        routing = (
            "rework_document_identity"
            if has_mismatch
            else ("human_legal_coverage_review" if ambiguities else "coverage_confirmed")
        )
        reason_codes = ["RC_HYBRID_POLICY_RAG_CITED"]
        if period_valid and policy_active:
            reason_codes.append("RC_POLICY_ACTIVE_IN_PERIOD")
        if is_ev:
            reason_codes.append("RC_EV_ENDORSEMENT_CHECKED")
        if ambiguities:
            reason_codes.append("RC_AMBIGUITY_DETECTED")

        result = {
            "supported_facts": [
                f"Policy status: {facts.get('policy_status', 'active')}",
                f"Incident within policy period: {period_valid}",
                f"Add-ons active: {addons}",
            ],
            "coverage_matrix": coverage_matrix,
            "deductibles_summary": {
                "compulsory_excess_inr": compulsory_excess,
                "voluntary_excess_inr": voluntary_excess,
                "idv_limit_inr": idv_inr,
            },
            "exclusions_checklist": exclusions_checklist,
            "possible_exclusions_to_verify": [
                "Valid driving licence at time of incident (SEC-1-3)",
                "Intoxication/consequential loss check (SEC-1-3)",
            ],
            "missing_evidence": missing_docs,
            "ambiguities": ambiguities,
            "clauses_requiring_human_interpretation": ambiguities,
            "retrieved_clauses": hits,
        }
        decision = DecisionIntelligence(
            decision_id=self._decision_id(self.agent_name),
            reason_codes=reason_codes,
            evidence=[
                f"Policy={facts.get('policy_status', 'active')}, period_valid={period_valid}",
                f"Matched clauses={[h['reference'] for h in hits[:3]]}",
            ],
            policy_rule_refs=[h["reference"] for h in hits[:4]] + ["IN-IRDAI-MC-2024:1.0.0"],
            confidence=conf,
            confidence_band=self._band(conf),
            routing_outcome=routing,
            explanation=(
                f"Constructed {len(coverage_matrix)}-row coverage matrix with {len(hits)} cited clauses. "
                + (f"Flagged {len(ambiguities)} ambiguity(s) for human review." if ambiguities else "Coverage confirmed with zero ambiguities.")
            ),
            alternatives_considered=["auto_repudiate_on_gap (strictly prohibited by IRDAI & architectural boundary)"],
        )

        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=status,
            result=result,
            published_result=result,
            confidence=conf,
            confidence_band=self._band(conf),
            evidence_refs=citations,
            contradictions=ambiguities,
            limitations=["Coverage factsheet is advisory; repudiation requires human claims/legal sign-off."],
            actions_executed=actions,
            rework_requests=rework_requests,
            decision=decision,
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action="human_coverage_review" if ambiguities else "run_triage",
            tools_invoked=list(dict.fromkeys(tools_used)),
        )


class ClaimTriageAgent(BoundedAgent):
    agent_name = "claim_triage"
    prompt_version = "triage-v3.0"
    allowed_tools = set(AGENT_CAPABILITY_CONTRACTS["claim_triage"].allowed_tools)

    def _run(
        self,
        request: AgentInvocationRequest,
        *,
        model_id: str,
        model_version: str,
        executor: ControlledActionExecutor,
    ) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="claim_triage", facts=request.minimised_facts)
        rules = load_rule_files()["IN-IRDAI-MC-2024"]["controls"]
        threshold = Decimal(str(rules["mandatory_survey_threshold_inr"]))
        facts = dict(request.minimised_facts)
        facts.setdefault("claim_type", request.claim_type)

        risk = classify_claim_risk_from_facts(facts, trigger_event="claim_triage_agent")
        risk_tier = str(risk["risk_tier"])
        auto_elig = risk["automation_eligibility"]

        est_loss = Decimal(str(facts.get("effective_loss_inr") or facts.get("estimated_loss_inr") or "0.00"))
        injury = bool(facts.get("injury_or_fatality", False))
        multi_vehicle = bool(risk["evaluated_dimensions"]["multiple_vehicles_involved"])
        ev_impact = bool(risk["evaluated_dimensions"]["ev_battery_impacted"])
        immobile = bool(facts.get("vehicle_immobile", False))
        airbags = bool(facts.get("airbags_deployed", False))
        police = bool(facts.get("police_involved", False))
        claim_type = str(facts.get("claim_type", request.claim_type))
        peril = str(facts.get("peril_cause", "road_accident"))

        requires_survey = bool(auto_elig["requires_mandatory_survey"])
        queue = str(auto_elig["recommended_queue"])
        priority = str(auto_elig["routing_priority"])
        recommended_triage_track = str(auto_elig["recommended_triage_track"])

        if injury or claim_type == "third_party":
            severity = "critical"
            complexity = "specialist_critical"
            liability_indicator = "statutory_tp_mact"
            injury_status = "tp_bodily_injury_or_fatality"
        elif multi_vehicle:
            severity = "high"
            complexity = "multi_vehicle_liability"
            liability_indicator = "multi_vehicle_collision"
            injury_status = "none"
        elif ev_impact:
            severity = "high"
            complexity = "specialist_ev"
            liability_indicator = "first_party_od_ev_hv"
            injury_status = "none"
        elif risk_tier == "HIGH":
            severity = "high"
            complexity = "complex_investigation"
            liability_indicator = "first_party_od"
            injury_status = "none"
        elif risk_tier == "MEDIUM":
            severity = "medium"
            complexity = "standard"
            liability_indicator = "first_party_od"
            injury_status = "none"
        else:
            severity = "low"
            complexity = "straight_through_eligible"
            liability_indicator = "first_party_od"
            injury_status = "none"

        drivable_status = "unsafe_ev_hv" if (ev_impact and immobile) else ("immobile_towing_required" if immobile else "drivable")

        actions: list[AgentActionExecution] = []
        tools_used = ["claim_facts_read", "triage_rules_read", "queue_recommend"]
        if immobile:
            actions.append(executor.dispatch_towing(agent_name=self.agent_name, ev_flatbed=ev_impact))
            tools_used.append("dispatch_towing")
        if injury or claim_type == "third_party" or multi_vehicle:
            actions.append(
                executor.create_claim_task(
                    agent_name=self.agent_name,
                    task_type="legal_tp_review",
                    title="TP Injury / Multi-Vehicle / Police FIR Legal Review",
                    description="Mandatory Legal/TP specialist review for bodily injury, multi-vehicle liability, or FIR claim.",
                    assigned_role="legal_tp",
                    priority="critical",
                    reason_code="RC_TP_INJURY_OR_MULTI_VEHICLE_PRIORITY",
                    due_hours=6,
                )
            )
            tools_used.append("create_claim_task")

        reason_codes = [
            f"RC_RISK_TIER_{risk_tier}",
            f"RC_PATH_{str(risk['operational_path']).upper()}",
            f"RC_PRIORITY_{priority}",
            f"RC_QUEUE_{queue.upper()}",
        ]
        for drv in risk["drivers"][:3]:
            reason_codes.append(f"RC_{drv['code']}")
        if requires_survey:
            reason_codes.append("RC_MANDATORY_SURVEY_TRIGGERED")
        elif auto_elig["straight_through_eligible"]:
            reason_codes.append("RC_FAST_TRACK_ELIGIBLE")
        if immobile:
            reason_codes.append("RC_VEHICLE_IMMOBILE")

        result = {
            "risk_tier": risk_tier,
            "operational_path": risk["operational_path"],
            "operational_path_label": risk["operational_path_label"],
            "handling_mode": risk["handling_mode"],
            "risk_goal": risk["goal"],
            "risk_score": risk["risk_score"],
            "fraud_signal_score": risk["fraud_signal_score"],
            "fraud_score_can_reject": False,
            "risk_drivers": risk["drivers"],
            "low_risk_criteria_check": risk["low_risk_criteria_check"],
            "automation_eligibility": auto_elig,
            "risk_explanation": risk["explanation"],
            "severity_band": severity,
            "complexity_tier": complexity,
            "injury_status": injury_status,
            "liability_indicator": liability_indicator,
            "vehicle_drivable": drivable_status,
            "routing_priority": priority,
            "recommended_queue": queue,
            "recommended_triage_track": recommended_triage_track,
            "requires_mandatory_survey": requires_survey,
            "survey_threshold_inr": str(threshold),
            "signals_used": {
                "estimated_loss_inr": str(est_loss),
                "injury_or_fatality": injury,
                "multiple_vehicles_involved": multi_vehicle,
                "ev_battery_impacted": ev_impact,
                "vehicle_immobile": immobile,
                "airbags_deployed": airbags,
                "police_involved": police,
                "peril_cause": peril,
            },
        }
        decision = DecisionIntelligence(
            decision_id=self._decision_id(self.agent_name),
            reason_codes=list(dict.fromkeys(reason_codes)),
            evidence=[
                f"Risk Tier={risk_tier} (score={risk['risk_score']}, path={risk['operational_path']})",
                f"Estimated loss INR {est_loss} vs IRDAI survey threshold INR {threshold}",
                f"Drivable={drivable_status}, Injury={injury}, MultiVehicle={multi_vehicle}, EV={ev_impact}",
            ],
            policy_rule_refs=["IN-RISK-PROCESSING-2026:1.0.0", "IN-IRDAI-MC-2024:1.0.0", "COMMON-SLA-CATALOGUE-V1:1.0.0"],
            confidence=0.95,
            confidence_band=ConfidenceBand.HIGH,
            routing_outcome=f"{risk_tier}:{risk['operational_path']}:{queue}",
            explanation=risk["explanation"],
            alternatives_considered=[
                "standard_claims (rejected if LOW straight-through eligible or HIGH specialist escalation required)"
            ],
        )

        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=AgentStatus.COMPLETED,
            result=result,
            published_result=result,
            confidence=0.95,
            confidence_band=ConfidenceBand.HIGH,
            evidence_refs=[
                EvidenceCitation(
                    source_type="rule",
                    source_id="IN-RISK-PROCESSING-2026",
                    reference=f"3-Tier Risk Processing ({risk_tier} -> {risk['operational_path']})",
                    excerpt=risk["explanation"],
                ),
                EvidenceCitation(
                    source_type="rule",
                    source_id="IN-IRDAI-MC-2024",
                    reference="Mandatory survey >= INR 50,000",
                    excerpt=f"Estimated loss INR {est_loss} vs threshold INR {threshold}.",
                ),
            ],
            limitations=["Triage uses operational risk/complexity signals only; never protected traits. Fraud score never rejects claims."],
            actions_executed=actions,
            decision=decision,
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action=(
                "siu_or_specialist_investigation"
                if risk_tier == "HIGH"
                else ("assign_surveyor" if requires_survey else "ai_damage_assessment")
            ),
            tools_invoked=list(dict.fromkeys(tools_used)),
        )


class DamageAssessmentAgent(BoundedAgent):
    agent_name = "damage_assessment"
    prompt_version = "damage-v3.0"
    allowed_tools = set(AGENT_CAPABILITY_CONTRACTS["damage_assessment"].allowed_tools)

    def _run(
        self,
        request: AgentInvocationRequest,
        *,
        model_id: str,
        model_version: str,
        executor: ControlledActionExecutor,
    ) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="damage_assessment", facts=request.minimised_facts)
        raw_payload = request.minimised_facts.get("assessment_payload")
        if isinstance(raw_payload, dict) and raw_payload:
            res = dict(raw_payload)
        else:
            res = assess_damage_from_evidence(
                claim_description=str(request.minimised_facts.get("incident_description", "")),
                is_ev=bool(request.minimised_facts.get("is_ev", False)),
                ev_battery_impacted=bool(request.minimised_facts.get("ev_battery_impacted", False)),
                image_records=list(request.minimised_facts.get("image_records", [])),
                vehicle_info=request.minimised_facts.get("vehicle_info"),
            )

        observations = list(res.get("observations", []))
        recapture = list(res.get("recapture_required_files", []))
        poor_files = list(res.get("poor_quality_files", []))
        missing_angles = list(res.get("missing_angles", []))
        img_q_conf = float(res.get("image_quality_confidence", 0.45 if recapture else 0.88))
        damage_zones = res.get("damage_zones") or sorted({o.get("zone", "exterior") for o in observations})
        overall_sev = res.get("overall_severity", "moderate" if observations else "unassessed")
        inconsistencies = list(res.get("inconsistencies", []))
        additional_reqs = list(res.get("additional_photo_requests", []))
        human_routing = dict(res.get("human_assessor_routing", {}))
        route_to_human = bool(human_routing.get("route_to_human_assessor", bool(recapture)))
        uncertain_components = list(human_routing.get("uncertain_components", []))
        guardrail_triggered = bool(human_routing.get("confidence_guardrail_triggered", False))
        recommended_role = str(human_routing.get("recommended_role", "surveyor"))
        parts_labour = dict(res.get("parts_labour_estimate", {}))

        actions: list[AgentActionExecution] = []
        tools_used = [
            "vision_model",
            "image_quality_check",
            "vehicle_taxonomy",
            "bbox_localizer",
            "cross_photo_compare",
            "parts_labour_estimator",
        ]

        high_or_med_photo_reqs = [r for r in additional_reqs if r.get("priority") in {"high", "medium"}]
        if recapture or poor_files or len(missing_angles) > 3 or high_or_med_photo_reqs:
            doc_reqs = [
                f"{r.get('angle', 'closeup')} photo ({r.get('reason_code', 'PHOTO_REQ')})"
                for r in (high_or_med_photo_reqs or additional_reqs[:3])
            ] or [f"Clear daylight photo ({a})" for a in (recapture or missing_angles[:3])]
            actions.append(
                executor.request_documents(
                    agent_name=self.agent_name,
                    documents=doc_reqs[:4],
                    reason_code="RC_PHOTO_RECAPTURE_NEEDED" if recapture else "RC_ADDITIONAL_PHOTOS_NEEDED",
                )
            )
            tools_used.append("request_documents")

        if route_to_human:
            reasons_text = "; ".join(human_routing.get("trigger_reasons", [])) or "Uncertain component repairability or image quality check."
            actions.append(
                executor.create_claim_task(
                    agent_name=self.agent_name,
                    task_type="human_damage_assessment",
                    title=f"Human Assessor Visual Review ({len(uncertain_components)} uncertain, {len(inconsistencies)} conflicts)",
                    description=reasons_text,
                    assigned_role=recommended_role if recommended_role in {"surveyor", "claims_handler", "claims_manager"} else "surveyor",
                    priority="high",
                    reason_code="RC_HUMAN_DAMAGE_ASSESSOR_ROUTED",
                    due_hours=12,
                    metadata={
                        "uncertain_components": uncertain_components,
                        "inconsistencies": [i.get("type") for i in inconsistencies],
                        "recapture_files": recapture,
                    },
                )
            )
            tools_used.append("create_claim_task")
        elif len(missing_angles) > 3:
            actions.append(
                executor.create_claim_task(
                    agent_name=self.agent_name,
                    task_type="photo_recapture",
                    title="Collect remaining standard vehicle angle photos",
                    description=f"Missing standard angles={missing_angles}",
                    assigned_role="policyholder",
                    priority="medium",
                    reason_code="RC_MISSING_ANGLE_FOLLOWUP",
                    due_hours=24,
                )
            )
            tools_used.append("create_claim_task")

        # Overall response confidence reflects weakest component when uncertain, never inflating over component uncertainty
        comp_confs = [float(o.get("component_confidence", o.get("confidence", img_q_conf))) for o in observations]
        if comp_confs:
            min_comp_conf = min(comp_confs)
            avg_comp_conf = sum(comp_confs) / len(comp_confs)
            conf = round(min(0.94, max(0.35, min_comp_conf if route_to_human else avg_comp_conf)), 3)
        else:
            conf = round(min(0.92, max(0.45, img_q_conf)), 3) if not recapture else 0.45

        status = AgentStatus.NEEDS_HUMAN if route_to_human else AgentStatus.COMPLETED
        routing = (
            "request_photo_recapture"
            if recapture
            else (
                "route_uncertain_to_human_assessor"
                if route_to_human
                else "damage_localized_proceed_estimate"
            )
        )
        reason_codes = [
            "RC_IMAGE_RECAPTURE_NEEDED" if recapture else ("RC_IMAGE_QUALITY_POOR" if poor_files else "RC_IMAGE_QUALITY_PASS"),
            "RC_COMPONENT_CONFIDENCE_CALIBRATED",
            "RC_VISIBLE_VS_INFERRED_SPLIT",
            "RC_PARTS_LABOUR_ESTIMATED",
        ]
        if guardrail_triggered:
            reason_codes.append("RC_COMPONENT_UNCERTAINTY_GUARDRAIL")
        if inconsistencies:
            reason_codes.append("RC_CROSS_PHOTO_INCONSISTENCY_DETECTED")
        if route_to_human:
            reason_codes.append("RC_HUMAN_ASSESSOR_ROUTED")
        if res.get("ev_safety_alerts"):
            reason_codes.append("RC_EV_HV_TEARDOWN_REQUIRED")

        enriched = {
            **res,
            "damage_zones": damage_zones,
            "overall_severity": overall_sev,
            "image_quality_confidence": img_q_conf,
        }
        comp_summary = "; ".join(
            f"{o.get('damaged_component', o.get('component_name'))}={o.get('component_confidence', o.get('confidence'))} ({o.get('repairability')})"
            for o in observations[:4]
        )
        decision = DecisionIntelligence(
            decision_id=self._decision_id(self.agent_name),
            reason_codes=reason_codes,
            evidence=[
                f"Overall image quality={res.get('overall_image_quality', 'good')} ({img_q_conf}), Photos={len(res.get('per_image_quality', []))}",
                f"Per-component confidence: {comp_summary or 'none'}",
                f"Inconsistencies={len(inconsistencies)}, Parts+Labour est INR {parts_labour.get('total_recommended_inr', '0.00')}",
            ],
            policy_rule_refs=[
                "IMAGE-QUALITY-GATE-320X240",
                "COMPONENT-CONFIDENCE-GUARDRAIL-V3",
                "VISIBLE-VS-INFERRED-PROVENANCE",
                f"RATE_CARD:{parts_labour.get('rate_card_id', 'RC-IN-2026-DEMO-V1')}",
            ],
            confidence=conf,
            confidence_band=self._band(conf),
            routing_outcome=routing,
            explanation=(
                f"Executed 10-step visual damage workflow for {res.get('vehicle', {}).get('display_label', 'vehicle')}: "
                f"{len(observations)} component(s) classified ({comp_summary or 'unassessed'}). "
                + (
                    f"Routed to human assessor ({recommended_role}) because: {'; '.join(human_routing.get('trigger_reasons', [])[:2])}."
                    if route_to_human
                    else f"Estimated parts+labour INR {parts_labour.get('total_recommended_inr', '0.00')}; ready for estimate validation."
                )
            ),
            alternatives_considered=[
                "confirm_hidden_damage_from_photos (prohibited; marked possible_hidden_damage)",
                "force_replace_from_overall_image_confidence (prohibited; component-level confidence governs repairability)",
            ],
        )

        evidence_citations = [
            EvidenceCitation(
                source_type="damage_bbox",
                source_id=str(ev.get("evidence_id") or "img"),
                reference=f"{ev.get('filename', 'photo')} ({ev.get('angle', 'angle')}) bbox={ev.get('bbox')}",
                excerpt=f"{obs.get('damaged_component')}: {obs.get('repairability')} (conf={obs.get('component_confidence')})",
            )
            for obs in observations[:4]
            for ev in (obs.get("evidence") or [])[:1]
        ]

        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=status,
            result=enriched,
            published_result=enriched,
            confidence=conf,
            confidence_band=self._band(conf),
            evidence_refs=evidence_citations,
            contradictions=[i.get("summary", "") for i in inconsistencies],
            missing_information=[
                f"{r.get('angle')} photo: {r.get('reason')}" for r in additional_reqs[:4]
            ],
            limitations=[
                "Assistive visual output only; component-level confidence governs repairability and hidden structural/mechanical damage cannot be confirmed from photos."
            ],
            actions_executed=actions,
            decision=decision,
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action=(
                "request_photo_recapture"
                if recapture
                else ("human_assessor_damage_review" if route_to_human else "validate_estimate")
            ),
            tools_invoked=list(dict.fromkeys(tools_used)),
        )


class EstimateValidationAgent(BoundedAgent):
    agent_name = "estimate_validation"
    prompt_version = "estimate-v2.0"
    allowed_tools = set(AGENT_CAPABILITY_CONTRACTS["estimate_validation"].allowed_tools)

    def _run(
        self,
        request: AgentInvocationRequest,
        *,
        model_id: str,
        model_version: str,
        executor: ControlledActionExecutor,
    ) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="estimate_validation", facts=request.minimised_facts)
        validation = dict(request.minimised_facts.get("estimate_validation", {}))
        anomalies = list(validation.get("anomalies", []))
        benchmark_summary = dict(validation.get("benchmark_summary", {}))
        repair_replace_conflicts = [a for a in anomalies if a.get("type") == "repair_vs_replace_conflict"]

        actions: list[AgentActionExecution] = []
        rework_requests: list[ReworkRequest] = []
        tools_used = ["parts_catalogue", "rate_card_read", "estimate_parser", "duplicate_line_rules"]

        if anomalies:
            actions.append(
                executor.create_claim_task(
                    agent_name=self.agent_name,
                    task_type="estimate_review",
                    title=f"Review {len(anomalies)} repair estimate anomaly(s)",
                    description="; ".join(a.get("message", "") for a in anomalies[:3]),
                    assigned_role="claims_handler",
                    priority="high" if len(anomalies) > 1 else "medium",
                    reason_code="RC_ESTIMATE_ANOMALIES",
                    due_hours=12,
                )
            )
            tools_used.append("create_claim_task")

        if repair_replace_conflicts:
            rework_requests.append(
                ReworkRequest(
                    from_agent=self.agent_name,
                    to_agent="damage_assessment",
                    reason_code="RC_REPAIR_VS_REPLACE_REWORK",
                    instructions=(
                        f"Re-evaluate repairability for {', '.join(c.get('part_code', '') for c in repair_replace_conflicts)}: "
                        "garage quoted replacement where visual damage suggested repair."
                    ),
                    blocking=False,
                )
            )

        conf = 0.74 if anomalies else 0.93
        status = AgentStatus.NEEDS_HUMAN if anomalies else AgentStatus.COMPLETED
        routing = (
            "rework_damage_verification"
            if repair_replace_conflicts
            else ("hold_anomalies_flagged" if anomalies else "estimate_within_benchmark")
        )
        reason_codes = ["RC_RATE_CARD_BENCHMARKED"]
        for a in anomalies:
            t = a.get("type", "").upper()
            if t and f"RC_{t}" not in reason_codes:
                reason_codes.append(f"RC_{t}")

        decision = DecisionIntelligence(
            decision_id=self._decision_id(self.agent_name),
            reason_codes=reason_codes,
            evidence=[
                f"Claimed INR {validation.get('total_claimed_inr', '0.00')} vs Recommended INR {validation.get('total_recommended_inr', '0.00')}",
                f"Anomalies={len(anomalies)}, Repair-vs-Replace conflicts={len(repair_replace_conflicts)}",
            ],
            policy_rule_refs=[f"RATE_CARD:{validation.get('rate_card_id', 'RC-IN-2026-DEMO-V1')}"],
            confidence=conf,
            confidence_band=self._band(conf),
            routing_outcome=routing,
            explanation=(
                f"Benchmarked parts, labour, and paint against {validation.get('rate_card_id', 'RC-IN-2026-DEMO-V1')}. "
                + (f"Flagged {len(anomalies)} anomaly(s) for human adjuster disposition." if anomalies else "All lines within OEM/labour benchmark tolerances.")
            ),
            alternatives_considered=["silently_overwrite_garage_quote (prohibited; lines held pending adjuster review)"],
        )

        enriched = {
            **validation,
            "benchmark_summary": benchmark_summary,
            "repair_vs_replace_conflicts": repair_replace_conflicts,
        }
        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=status,
            result=enriched,
            published_result=enriched,
            confidence=conf,
            confidence_band=self._band(conf),
            contradictions=[a.get("message", "") for a in anomalies],
            limitations=["Cannot alter garage estimate silently; adjuster/surveyor must accept, amend, or reject lines."],
            actions_executed=actions,
            rework_requests=rework_requests,
            decision=decision,
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action="adjuster_estimate_review" if anomalies else "run_fraud_checks",
            tools_invoked=list(dict.fromkeys(tools_used)),
        )


class FraudIntelligenceAgent(BoundedAgent):
    agent_name = "fraud_intelligence"
    prompt_version = "fraud-v3.0"
    allowed_tools = set(AGENT_CAPABILITY_CONTRACTS["fraud_intelligence"].allowed_tools)

    def _run(
        self,
        request: AgentInvocationRequest,
        *,
        model_id: str,
        model_version: str,
        executor: ControlledActionExecutor,
    ) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="fraud_intelligence", facts=request.minimised_facts)
        indicators = list(request.minimised_facts.get("indicators", []))
        entity_graph = dict(request.minimised_facts.get("entity_graph", {}))
        suspicious_connections = list(entity_graph.get("suspicious_connections", []))
        network_patterns = [
            i.get("indicator_code")
            for i in indicators
            if i.get("indicator_code") in {"FRD-IMG-HASH-REUSE", "FRD-GARAGE-ANOMALY-NETWORK", "FRD-ENTITY-RING-CLUSTER", "FRD-REPEAT-VEHICLE"}
        ]
        fraud_signal_score = compute_fraud_signal_score(indicators)

        actions: list[AgentActionExecution] = []
        tools_used = ["fraud_feature_service", "fraud_rules", "entity_graph_query"]
        if indicators:
            actions.append(
                executor.create_claim_task(
                    agent_name=self.agent_name,
                    task_type="siu_investigation",
                    title=f"SIU Review: {len(indicators)} explainable fraud indicator(s)",
                    description="; ".join(f"{i.get('indicator_code')}: {i.get('title')}" for i in indicators[:3]),
                    assigned_role="siu_investigator",
                    priority="high" if any(i.get("severity_band") == "high" for i in indicators) else "medium",
                    reason_code="RC_SIU_INVESTIGATIVE_LEAD",
                    due_hours=24,
                )
            )
            tools_used.append("create_claim_task")

        conf = 0.81 if indicators else 0.92
        routing = "refer_to_siu_investigation" if indicators else "siu_clean_pass"
        reason_codes = [str(i.get("indicator_code", "FRD_SIGNAL")) for i in indicators] or ["RC_NO_FRAUD_SIGNALS"]
        if network_patterns:
            reason_codes.append("RC_NETWORK_PATTERN_DETECTED")
        reason_codes.append("RC_FRAUD_SCORE_NON_REJECTION_GUARD")

        result = {
            "alert_count": len(indicators),
            "fraud_signal_score": str(fraud_signal_score),
            "fraud_score_can_reject": False,
            "fraud_guardrail_note": "Fraud score is an investigative risk signal only and NEVER determines claim rejection.",
            "network_patterns_detected": network_patterns,
            "suspicious_connections": suspicious_connections,
            "indicators": indicators,
            "entity_graph_summary": entity_graph.get("network_risk_summary", {}),
        }
        decision = DecisionIntelligence(
            decision_id=self._decision_id(self.agent_name),
            reason_codes=reason_codes,
            evidence=[
                f"Indicators={len(indicators)}, fraud_signal_score={fraud_signal_score} (non-rejecting advisory signal), Network patterns={network_patterns}",
                f"Suspicious entity connections={len(suspicious_connections)}",
            ],
            policy_rule_refs=["IRDAI-FRAUD-DUE-PROCESS", "IN-RISK-PROCESSING-2026:1.0.0", "IN-DOA-MATRIX-2026:fraud_alert_open"],
            confidence=conf,
            confidence_band=self._band(conf),
            routing_outcome=routing,
            explanation=(
                f"Raised {len(indicators)} explainable alert-only lead(s) (fraud_signal_score={fraud_signal_score}) for SIU review; "
                "escalated to HIGH risk human investigation — fraud score NEVER auto-rejects the claim."
                if indicators
                else f"Evaluated entity network, checksum reuse, policy timing, and estimate anomalies; zero fraud signals detected (score={fraud_signal_score})."
            ),
            alternatives_considered=["auto_reject_claim_on_alert (strictly prohibited by IRDAI Fraud Due Process & IN-RISK-PROCESSING-2026)"],
        )

        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=AgentStatus.NEEDS_HUMAN if indicators else AgentStatus.COMPLETED,
            result=result,
            published_result=result,
            confidence=conf,
            confidence_band=self._band(conf),
            limitations=[
                "Indicators and fraud_signal_score are investigative leads only. Fraud score NEVER determines claim rejection or blocks intake."
            ],
            actions_executed=actions,
            decision=decision,
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action="refer_to_siu_queue" if indicators else "calculate_settlement",
            tools_invoked=list(dict.fromkeys(tools_used)),
        )


class ProviderCoordinationAgent(BoundedAgent):
    agent_name = "provider_coordination"
    prompt_version = "provider-v3.0"
    allowed_tools = set(AGENT_CAPABILITY_CONTRACTS["provider_coordination"].allowed_tools)

    def _run(
        self,
        request: AgentInvocationRequest,
        *,
        model_id: str,
        model_version: str,
        executor: ControlledActionExecutor,
    ) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="provider_coordination", facts=request.minimised_facts)
        facts = request.minimised_facts
        requires_survey = bool(facts.get("requires_mandatory_survey", True))
        ev_required = bool(facts.get("ev_battery_impacted", False)) or bool(facts.get("is_ev", False))
        towing_needed = bool(facts.get("towing_needed", False)) or bool(facts.get("vehicle_immobile", False))
        pickup_required = bool(facts.get("pickup_required", False))
        delivery_required = bool(facts.get("delivery_required", False))
        preferred_garage_id = facts.get("preferred_garage_id") or facts.get("assigned_garage_id")
        selected_garage_id = facts.get("selected_garage_id")
        preferred_surveyor_id = facts.get("preferred_surveyor_id")
        override_pref = bool(facts.get("override_customer_preference", False))
        override_contract = bool(facts.get("override_contract_rule", False))
        override_reason = str(facts.get("override_reason", "") or "").strip()
        actor_role = str(facts.get("actor_role") or request.actor_role or "claims_handler")
        authorized_override = actor_role in {"claims_manager", "admin"} and bool(override_reason)

        candidate = facts.get("recommended_provider")
        surveyor_cand = facts.get("recommended_surveyor") or candidate
        garage_cand = facts.get("recommended_garage")

        actions: list[AgentActionExecution] = []
        tools_used = ["verified_roster_read", "verify_surveyor_license", "provider_scorecard"]
        ev_override_applied = bool(facts.get("ev_safety_override_applied", False))
        pref_honoured = not ev_override_applied
        override_blocked = False
        override_block_reason = ""
        selection_reasons: list[str] = []

        # Guardrail: Never override customer choice or contractual rules without proper authorization
        if (override_pref or override_contract or (selected_garage_id and preferred_garage_id and selected_garage_id != preferred_garage_id)) and not authorized_override:
            override_blocked = True
            override_block_reason = (
                "Blocked unauthorized override: customer preferred garage or contractual rules cannot be overridden "
                "without Claims Manager / Admin authorization and documented rationale."
            )
            actions.append(
                AgentActionExecution(
                    action_id=f"act-guard-{self._decision_id('guard')[-6:]}",
                    action_type="override_guardrail",
                    tool_name="provider_scorecard",
                    status="blocked_policy",
                    target_type="claim",
                    target_id=request.claim_id,
                    summary=override_block_reason,
                    payload={
                        "actor_role": actor_role,
                        "preferred_garage_id": preferred_garage_id,
                        "requested_garage_id": selected_garage_id,
                    },
                )
            )
            actions.append(
                executor.create_claim_task(
                    agent_name=self.agent_name,
                    task_type="ecosystem_authorization_review",
                    title="Authorization required for customer preference / contractual override",
                    description=override_block_reason,
                    assigned_role="claims_manager",
                    priority="high",
                    reason_code="RC_UNAUTHORIZED_OVERRIDE_BLOCKED",
                    due_hours=8,
                )
            )
            tools_used.append("create_claim_task")

        # Optional pre-supplied candidate scoring explanation from Ecosystem service or DB
        surveyor_license_verified = bool(facts.get("surveyor_license_verified", True))
        requested_surv_status = str(facts.get("requested_surveyor_licence_status", "verified"))
        if requested_surv_status != "verified":
            surveyor_license_verified = False
            override_blocked = True
            override_block_reason = f"Blocked unlicensed surveyor (IIISLA licence_status={requested_surv_status})."
            actions.append(
                AgentActionExecution(
                    action_id=f"act-lic-{self._decision_id('lic')[-6:]}",
                    action_type="license_verification",
                    tool_name="verify_surveyor_license",
                    status="blocked_policy",
                    target_type="provider",
                    target_id=str(preferred_surveyor_id or ""),
                    summary=override_block_reason,
                    payload={"licence_status": requested_surv_status},
                )
            )

        if requires_survey and not override_blocked:
            sched = executor.schedule_inspection(
                agent_name=self.agent_name,
                surveyor_id=preferred_surveyor_id,
                ev_required=ev_required,
            )
            actions.append(sched)
            tools_used.extend(["schedule_inspection", "schedule_notify"])
            if not surveyor_cand and sched.target_id:
                surveyor_cand = {"id": sched.target_id, "summary": sched.summary}
            if sched.summary:
                selection_reasons.append(sched.summary)

        if facts.get("reschedule_appointment_at"):
            resched = executor.reschedule_inspection(
                agent_name=self.agent_name,
                new_appointment_at=str(facts["reschedule_appointment_at"]),
                reason=str(facts.get("reschedule_reason", "Customer / garage requested slot change")),
            )
            actions.append(resched)
            tools_used.append("reschedule_inspection")

        if not override_blocked and (garage_cand or preferred_garage_id or executor.db is not None):
            target_gar_id = str(selected_garage_id or preferred_garage_id) if (selected_garage_id or preferred_garage_id) else None
            gar_exec = executor.notify_garage(
                agent_name=self.agent_name,
                garage_id=target_gar_id,
                ev_required=ev_required,
            )
            actions.append(gar_exec)
            tools_used.append("notify_garage")
            if preferred_garage_id and gar_exec.target_id and gar_exec.target_id != str(preferred_garage_id):
                pref_honoured = False
                ev_override_applied = ev_required
                selection_reasons.append(
                    f"EV HV contractual safety mandate (POL-WORDING-EV-2025:EV-SAFE-01) redirected non-EV preferred garage "
                    f"{preferred_garage_id} to EV-certified {gar_exec.payload.get('garage_name', gar_exec.target_id)}."
                )
            elif preferred_garage_id and gar_exec.target_id == str(preferred_garage_id):
                selection_reasons.append(f"Honoured customer-preferred garage {gar_exec.payload.get('garage_name', preferred_garage_id)}.")
            elif gar_exec.summary:
                selection_reasons.append(gar_exec.summary)
            if not garage_cand and gar_exec.target_id:
                garage_cand = {"id": gar_exec.target_id, "summary": gar_exec.summary}

        # Parts availability check
        parts_check = executor.check_parts_availability(
            agent_name=self.agent_name,
            garage_name=str((garage_cand or {}).get("name") or (garage_cand or {}).get("summary") or "Network Garage"),
            parts_stock_status=str(facts.get("parts_stock_status", "in_stock")),
            parts_lead_time_days=int(facts.get("parts_lead_time_days", 2)),
            part_items=facts.get("part_items"),
        )
        actions.append(parts_check)
        tools_used.append("check_parts_availability")

        if towing_needed:
            actions.append(executor.dispatch_towing(agent_name=self.agent_name, ev_flatbed=ev_required))
            tools_used.append("dispatch_towing")

        if pickup_required or delivery_required:
            mode = "pickup_and_delivery" if (pickup_required and delivery_required) else ("pickup" if pickup_required else "delivery")
            actions.append(executor.schedule_pickup_delivery(agent_name=self.agent_name, mode=mode, ev_flatbed=ev_required))
            tools_used.append("schedule_pickup_delivery")

        if facts.get("followup_surveyor"):
            actions.append(
                executor.send_surveyor_followup(
                    agent_name=self.agent_name,
                    notes=str(facts.get("followup_notes", "IRDAI 15-day report SLA follow-up")),
                    escalate_to_manager=bool(facts.get("escalate_followup", False)),
                )
            )
            tools_used.append("send_surveyor_followup")

        if facts.get("confirm_repair_completion"):
            actions.append(
                executor.confirm_repair_completion(
                    agent_name=self.agent_name,
                    milestone=str(facts.get("repair_milestone", "repair_completed")),
                    notes=str(facts.get("repair_notes", "Repair & QC verified")),
                )
            )
            tools_used.append("confirm_repair_completion")

        if facts.get("notify_customer", True) and not override_blocked:
            actions.append(
                executor.send_customer_update(
                    agent_name=self.agent_name,
                    channel=str(facts.get("notification_channel", "whatsapp")),
                    language=str(facts.get("language") or request.locale or "en-IN"),
                    template_id="ECOSYSTEM_COORDINATION_UPDATE",
                    subject=f"Claims Ecosystem & Repair Coordination: {request.claim_id}",
                    body=" ".join(selection_reasons) or "Surveyor, garage, parts, and logistics coordinated.",
                    is_adverse=False,
                )
            )
            tools_used.append("send_customer_update")

        has_provider = bool(
            (surveyor_cand or garage_cand or not requires_survey or any(a.status == "executed" for a in actions))
            and not override_blocked
        )
        status = AgentStatus.NEEDS_HUMAN if override_blocked or not has_provider else AgentStatus.COMPLETED
        conf = 0.45 if override_blocked else (0.93 if has_provider else 0.42)
        routing = (
            "blocked_unauthorized_override_or_licence"
            if override_blocked
            else (
                "customer_garage_overridden_ev_safety"
                if ev_override_applied
                else ("ecosystem_coordinated" if has_provider else "escalate_capacity_shortage")
            )
        )
        reason_codes = ["RC_VERIFIED_LICENCE_FILTER", "RC_GEOGRAPHY_SKILL_CAPACITY_SLA_SCORED", "RC_SLA_24H_15D_ENFORCED"]
        if override_blocked:
            reason_codes.append("RC_UNAUTHORIZED_OVERRIDE_OR_LICENCE_BLOCKED")
        elif ev_override_applied:
            reason_codes.append("RC_EV_GARAGE_SAFETY_OVERRIDE")
        elif pref_honoured:
            reason_codes.append("RC_CUSTOMER_PREFERENCE_HONOURED")
        if towing_needed:
            reason_codes.append("RC_TOWING_COORDINATED")
        if pickup_required or delivery_required:
            reason_codes.append("RC_PICKUP_DELIVERY_COORDINATED")
        if parts_check.payload.get("parts_status") in {"partial_backorder", "backordered"}:
            reason_codes.append("RC_PARTS_BACKORDER_FLAGGED")

        selection_explanation = str(facts.get("selection_explanation") or " ".join(selection_reasons)).strip() or (
            "Coordinated verified IIISLA surveyor, network/preferred garage, parts check, and logistics by geography, skill, capacity, and SLA."
        )
        score_breakdown = facts.get("score_breakdown") or {
            "weights": {"geography": 30, "skill": 25, "capacity": 20, "sla": 15, "rating": 10},
            "surveyor_score": facts.get("surveyor_score_breakdown"),
            "garage_score": facts.get("garage_score_breakdown"),
        }

        result = {
            "recommended_provider": candidate or surveyor_cand or garage_cand,
            "recommended_surveyor": surveyor_cand,
            "recommended_garage": garage_cand,
            "surveyor_license_verified": surveyor_license_verified,
            "selection_explanation": selection_explanation,
            "score_breakdown": score_breakdown,
            "towing_coordinated": towing_needed,
            "pickup_delivery_coordinated": pickup_required or delivery_required,
            "ev_capable_required": ev_required,
            "customer_preference_honoured": pref_honoured,
            "ev_safety_override_applied": ev_override_applied,
            "override_blocked": override_blocked,
            "override_block_reason": override_block_reason,
            "parts_availability": parts_check.payload,
            "inspection_schedule": {
                "status": "rescheduled" if facts.get("reschedule_appointment_at") else ("scheduled" if requires_survey and not override_blocked else "not_required"),
                "rescheduled_at": facts.get("reschedule_appointment_at"),
            },
            "repair_status": {
                "milestone": facts.get("repair_milestone", "intake_confirmed" if garage_cand else "not_started"),
                "completion_confirmed": bool(facts.get("confirm_repair_completion", False)),
            },
            "surveyor_followup": {
                "triggered": bool(facts.get("followup_surveyor", False)),
            },
            "sla_deadlines": {"allocation_sla_hours": 24, "survey_report_due_days": 15},
        }
        decision = DecisionIntelligence(
            decision_id=self._decision_id(self.agent_name),
            reason_codes=reason_codes,
            evidence=[
                f"Location={facts.get('incident_location', 'unspecified')}, Mandatory survey={requires_survey}, EV={ev_required}, Towing={towing_needed}",
                f"Surveyor={surveyor_cand}, Garage={garage_cand}, Parts={parts_check.payload.get('parts_status')}",
                f"Explanation={selection_explanation}",
            ],
            policy_rule_refs=[
                "IN-IRDAI-MC-2024:24h_15d_SLA",
                "POL-WORDING-EV-2025:EV-SAFE-01",
                "CUSTOMER-PREFERENCE-AUTH-GUARD-V1",
            ],
            confidence=conf,
            confidence_band=self._band(conf),
            routing_outcome=routing,
            explanation=(
                override_block_reason
                if override_blocked
                else (
                    selection_explanation
                    if has_provider
                    else "No available licensed surveyor/EV-capable garage within city capacity; escalated to SLA Operations."
                )
            ),
            alternatives_considered=[
                "assign_unlicensed_or_non_ev_garage (blocked by safety & IIISLA licence guard)",
                "override_customer_choice_without_manager_auth (strictly prohibited)",
            ],
        )

        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=status,
            result=result,
            published_result=result,
            confidence=conf,
            confidence_band=self._band(conf),
            missing_information=[] if (has_provider and not override_blocked) else [override_block_reason or "No available licensed surveyor/EV-capable garage in city"],
            limitations=[
                "Never overrides customer garage choice or contractual rules without Claims Manager / Admin authorization.",
                "Never assigns an unverified or expired IIISLA surveyor.",
            ],
            actions_executed=actions,
            decision=decision,
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action=(
                "manager_authorization_review"
                if override_blocked
                else ("confirm_assignment" if has_provider else "escalate_sla_capacity")
            ),
            tools_invoked=list(dict.fromkeys(tools_used)),
        )


class SettlementRecommendationAgent(BoundedAgent):
    agent_name = "settlement_recommendation"
    prompt_version = "settlement-v3.0"
    allowed_tools = set(AGENT_CAPABILITY_CONTRACTS["settlement_recommendation"].allowed_tools)

    def _run(
        self,
        request: AgentInvocationRequest,
        *,
        model_id: str,
        model_version: str,
        executor: ControlledActionExecutor,
    ) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="settlement_recommendation", facts=request.minimised_facts)
        facts = request.minimised_facts
        if request.claim_type == "third_party" or facts.get("tp_workflow_required"):
            # Third-Party liability is never settled by the OD calculator / auto-approval logic (IN-TP-LIABILITY-2026).
            tp_result = {
                "auto_approved": False,
                "tp_workflow_required": True,
                "approval_mode": "tp_legal_dual_control",
                "required_doa_tier": "legal_tp",
                "message": "Third-Party liability claims are settled only through the dedicated TP workflow with legal review and dual-control approval.",
            }
            return AgentInvocationResponse(
                agent_name=self.agent_name,
                status=AgentStatus.NEEDS_HUMAN,
                result=tp_result,
                published_result=tp_result,
                confidence=1.0,
                confidence_band=ConfidenceBand.HIGH,
                limitations=["OD settlement calculation and auto-approval do not apply to Third-Party liability claims."],
                actions_executed=[],
                decision=DecisionIntelligence(
                    decision_id=self._decision_id(self.agent_name),
                    reason_codes=["RC_TP_LIABILITY_LEGAL_WORKFLOW_REQUIRED", "RC_NO_AUTONOMOUS_TP_SETTLEMENT"],
                    evidence=["claim_type=third_party", "IN-TP-LIABILITY-2026 controls.autonomous_settlement_allowed=false"],
                    policy_rule_refs=["IN-TP-LIABILITY-2026:1.0.0"],
                    confidence=1.0,
                    confidence_band=ConfidenceBand.HIGH,
                    routing_outcome="route_to_tp_legal_workflow",
                    explanation="Routed to the Third-Party legal workflow; no OD settlement, approval request or payment instruction was created.",
                    alternatives_considered=[],
                ),
                model_id=model_id,
                model_version=model_version,
                prompt_version=self.prompt_version,
                rule_versions=request.rule_versions,
                suggested_next_action="route_to_tp_legal_workflow",
                tools_invoked=["policy_facts_read"],
            )
        calc = dict(facts.get("calculation", {}))
        scenarios = list(facts.get("scenarios") or calc.get("scenarios") or [])
        net_str = str(calc.get("net") or calc.get("net_payable_inr") or "0.00")
        net_amt = Decimal(net_str)
        active_conditions = list(facts.get("active_conditions", []))
        risk_tier = str(facts.get("risk_tier", "MEDIUM"))
        auto_limit = Decimal(str(facts.get("auto_approval_limit_inr", "25000.00")))
        fast_track_auto = (
            risk_tier == "LOW"
            and bool(facts.get("straight_through_eligible", False))
            and bool(facts.get("allow_fast_track_auto_approve", False))
            and not active_conditions
            and Decimal("0.00") < net_amt <= auto_limit
            and not facts.get("initiate_approved_payment")
        )

        if fast_track_auto:
            required_tier = "fast_track_auto_limit"
        elif "tp_injury" in active_conditions or "tp_fatality" in active_conditions:
            required_tier = "legal_tp"
        elif (
            "fraud_alert_open" in active_conditions
            or "ev_battery" in active_conditions
            or "total_loss" in active_conditions
            or "high_risk_complex" in active_conditions
            or risk_tier == "HIGH"
            or net_amt > Decimal("75000.00")
        ):
            required_tier = "claims_manager"
        else:
            required_tier = "claims_handler"

        actions: list[AgentActionExecution] = []
        tools_used = ["deterministic_calculator", "policy_facts_read", "survey_report_read"]

        settlement_id = facts.get("settlement_id")
        if facts.get("initiate_approved_payment") and settlement_id and facts.get("idempotency_key"):
            pay_exec = executor.initiate_approved_payment(
                agent_name=self.agent_name,
                settlement_id=str(settlement_id),
                idempotency_key=str(facts["idempotency_key"]),
                payee_name=str(facts.get("payee_name", "Approved Payee")),
                payee_type=str(facts.get("payee_type", "garage")),
                simulate_timeout=bool(facts.get("simulate_timeout", False)),
            )
            actions.append(pay_exec)
            tools_used.append("initiate_approved_payment")
        elif not fast_track_auto:
            actions.append(
                executor.generate_approval_request(
                    agent_name=self.agent_name,
                    settlement_id=str(settlement_id) if settlement_id else None,
                    amount_inr=net_amt,
                    required_tier=required_tier,
                    rationale=f"Maker-Checker DoA review ({required_tier}) for INR {net_amt} under IN-DOA-MATRIX-2026.",
                )
            )
            tools_used.extend(["generate_approval_request", "create_claim_task"])

        is_ctl = bool(calc.get("is_total_loss", False)) or "total_loss" in active_conditions
        routing = (
            "fast_track_auto_approved_within_limit"
            if fast_track_auto
            else ("ctl_total_loss_escalate_manager" if is_ctl else f"route_to_{required_tier}_checker")
        )
        reason_codes = ["RC_DECIMAL_CALCULATION_VERIFIED", f"RC_DOA_TIER_{required_tier.upper()}"]
        if fast_track_auto:
            reason_codes.append("RC_FAST_TRACK_AUTO_APPROVED")
        if is_ctl:
            reason_codes.append("RC_CTL_EXCEEDS_75PCT_IDV")
        for cond in active_conditions:
            reason_codes.append(f"RC_COND_{str(cond).upper()}")

        enriched = {
            **calc,
            "scenarios": scenarios,
            "required_doa_tier": required_tier,
            "active_conditions": active_conditions,
            "risk_tier": risk_tier,
            "auto_approved": fast_track_auto,
            "approval_mode": "straight_through_automated" if fast_track_auto else "maker_checker_doa",
            "auto_approval_limit_inr": str(auto_limit),
        }
        decision = DecisionIntelligence(
            decision_id=self._decision_id(self.agent_name),
            reason_codes=reason_codes,
            evidence=[
                f"Net payable INR {net_amt}, Risk Tier={risk_tier}, Scenarios evaluated={len(scenarios)}",
                (
                    f"LOW risk straight-through limit <= INR {auto_limit} satisfied with zero anomalies"
                    if fast_track_auto
                    else f"Active DoA conditions={active_conditions}, Required checker tier={required_tier}"
                ),
            ],
            policy_rule_refs=["IN-MOTOR-DEPRECIATION-2024:1.0.0", "IN-DOA-MATRIX-2026:1.0.0", "IN-RISK-PROCESSING-2026:1.0.0"],
            confidence=0.96,
            confidence_band=ConfidenceBand.HIGH,
            routing_outcome=routing,
            explanation=(
                f"LOW RISK straight-through settlement INR {net_amt} auto-approved within IN-RISK-PROCESSING-2026 limit (<= INR {auto_limit}). Ready for Finance payout."
                if fast_track_auto
                else f"Evaluated {max(len(scenarios), 1)} settlement scenario(s) using deterministic Python Decimal math. Net recommended INR {net_amt}; routed to independent {required_tier} under Maker-Checker DoA."
            ),
            alternatives_considered=[
                s.get("label", s.get("scenario_code", "scenario")) for s in scenarios if not s.get("recommended")
            ],
        )

        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=AgentStatus.COMPLETED if fast_track_auto else AgentStatus.NEEDS_HUMAN,
            result=enriched,
            published_result=enriched,
            confidence=0.96,
            confidence_band=ConfidenceBand.HIGH,
            limitations=[
                "Straight-through auto-approval permitted strictly for LOW risk claims <= INR 25,000; Finance payment still gated."
                if fast_track_auto
                else "Agent cannot self-approve payout; independent Maker-Checker and Finance approval required."
            ],
            actions_executed=actions,
            decision=decision,
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action="ready_for_finance_payment" if fast_track_auto else "route_to_maker_checker_approval",
            tools_invoked=list(dict.fromkeys(tools_used)),
        )


class CustomerCommunicationAgent(BoundedAgent):
    agent_name = "customer_communication"
    prompt_version = "comm-v2.0"
    allowed_tools = set(AGENT_CAPABILITY_CONTRACTS["customer_communication"].allowed_tools)

    def _run(
        self,
        request: AgentInvocationRequest,
        *,
        model_id: str,
        model_version: str,
        executor: ControlledActionExecutor,
    ) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="customer_communication", facts=request.minimised_facts)
        facts = request.minimised_facts
        is_adverse = bool(facts.get("is_adverse", False))
        locale = str(facts.get("language") or request.locale or "en-IN")
        if locale not in _LOCALIZED_COMM_TEMPLATES:
            locale = "en-IN"
        channel = str(facts.get("channel", "whatsapp"))
        msg_type = str(facts.get("message_type", "status_update"))
        if msg_type not in {"status_update", "document_reminder", "delay_advisory", "next_steps"}:
            msg_type = "status_update"

        tpl = _LOCALIZED_COMM_TEMPLATES[locale][msg_type]
        ctx = {
            "claim_number": facts.get("claim_number", request.claim_id),
            "vehicle": facts.get("vehicle_reg", "your vehicle"),
            "status": facts.get("claim_status", "IN_PROGRESS"),
            "next_step": facts.get("next_expected_action", "Processing under review"),
            "missing_docs": ", ".join(facts.get("missing_documents", [])) or "pending evidence",
            "delay_reason": facts.get("delay_reason", "surveyor report follow-up"),
        }
        subject = str(facts.get("subject") or tpl["subject"].format(**ctx))
        draft = str(facts.get("draft_message") or tpl["body"].format(**ctx))

        actions = [
            executor.send_customer_update(
                agent_name=self.agent_name,
                channel=channel,
                language=locale,
                template_id=f"COMM_{msg_type.upper()}",
                subject=subject,
                body=draft,
                is_adverse=is_adverse,
            )
        ]

        routing = "held_for_human_comm_approval" if is_adverse else f"proactive_{msg_type}_dispatched"
        reason_codes = [f"RC_COMM_{msg_type.upper()}", f"RC_LOCALE_{locale.replace('-', '_').upper()}"]
        if is_adverse:
            reason_codes.append("RC_ADVERSE_HUMAN_REVIEW_REQUIRED")

        result = {
            "channel": channel,
            "language": locale,
            "message_type": msg_type,
            "subject": subject,
            "draft_message": draft,
            "requires_human_review": is_adverse,
        }
        decision = DecisionIntelligence(
            decision_id=self._decision_id(self.agent_name),
            reason_codes=reason_codes,
            evidence=[f"Channel={channel}, Locale={locale}, Type={msg_type}, Adverse={is_adverse}"],
            policy_rule_refs=["IRDAI-POLICYHOLDER-COMM-2024", "ADVERSE-NOTICE-HUMAN-GATE"],
            confidence=0.93,
            confidence_band=ConfidenceBand.HIGH,
            routing_outcome=routing,
            explanation=(
                f"Prepared localized {msg_type} in {locale} for {channel}. "
                + ("Held in pending_human_review because message is adverse." if is_adverse else "Dispatched proactively without holding claim.")
            ),
            alternatives_considered=["send_english_only_passive (upgraded to multilingual proactive cadence)"],
        )

        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=AgentStatus.NEEDS_HUMAN if is_adverse else AgentStatus.COMPLETED,
            result=result,
            published_result=result,
            confidence=0.93,
            confidence_band=ConfidenceBand.HIGH,
            limitations=["Adverse or legal communications cannot be sent without human approval."],
            actions_executed=actions,
            decision=decision,
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action="human_comm_review" if is_adverse else "dispatch_notification",
            tools_invoked=["approved_templates", "communication_preference", "send_customer_update"],
        )


class QAComplianceAgent(BoundedAgent):
    agent_name = "qa_compliance"
    prompt_version = "qa-v2.0"
    allowed_tools = set(AGENT_CAPABILITY_CONTRACTS["qa_compliance"].allowed_tools)

    def _run(
        self,
        request: AgentInvocationRequest,
        *,
        model_id: str,
        model_version: str,
        executor: ControlledActionExecutor,
    ) -> AgentInvocationResponse:
        ModelGateway.generate_structured_summary(task="qa_compliance", facts=request.minimised_facts)
        checks = dict(request.minimised_facts.get("checks", {}))
        checklist_items = [
            {"code": k, "passed": bool(ok), "remediation_target": self._rework_target_for(k)}
            for k, ok in checks.items()
        ]
        failures = [k for k, ok in checks.items() if not ok]
        total_cnt = max(len(checks), 1)
        readiness_score = round((len(checks) - len(failures)) / total_cnt, 3)

        actions: list[AgentActionExecution] = []
        rework_requests: list[ReworkRequest] = []
        tools_used = ["readonly_audit", "workflow_read", "rules_read", "evidence_read"]
        if failures:
            actions.append(
                executor.create_claim_task(
                    agent_name=self.agent_name,
                    task_type="qa_remediation",
                    title=f"QA Closure Blocked: resolve {len(failures)} control(s)",
                    description=f"Failed controls: {', '.join(failures)}",
                    assigned_role="claims_handler",
                    priority="high",
                    reason_code="RC_QA_CLOSURE_BLOCKED",
                    due_hours=8,
                )
            )
            tools_used.append("create_claim_task")
            for failed in failures:
                target = self._rework_target_for(failed)
                if target:
                    rework_requests.append(
                        ReworkRequest(
                            from_agent=self.agent_name,
                            to_agent=target,
                            reason_code=f"RC_QA_{failed.upper()}",
                            instructions=f"Remediate failed QA compliance control '{failed}' before closure.",
                            blocking=True,
                        )
                    )

        conf = 0.97 if not failures else 0.96
        routing = "closure_approved_audit_ready" if not failures else "block_closure_rework_required"
        reason_codes = ["RC_QA_ALL_CONTROLS_PASSED"] if not failures else [f"RC_QA_FAILED_{f.upper()}" for f in failures]

        result = {
            "checks": checks,
            "qa_checklist": checklist_items,
            "audit_readiness_score": readiness_score,
            "failed_controls": failures,
            "closure_eligible": len(failures) == 0,
        }
        decision = DecisionIntelligence(
            decision_id=self._decision_id(self.agent_name),
            reason_codes=reason_codes,
            evidence=[f"QA Checklist {len(checks) - len(failures)}/{len(checks)} passed (score={readiness_score})"],
            policy_rule_refs=["IN-IRDAI-MC-2024:CLOSURE", "AUDIT-CHAIN-SHA256"],
            confidence=conf,
            confidence_band=ConfidenceBand.HIGH,
            routing_outcome=routing,
            explanation=(
                f"All {len(checks)} QA compliance controls passed (audit readiness={readiness_score}); claim eligible for CLOSED state."
                if not failures
                else f"Blocked closure: {len(failures)} QA control(s) failed ({', '.join(failures)})."
            ),
            alternatives_considered=["force_close_with_open_controls (prohibited by read-only compliance verifier)"],
        )

        return AgentInvocationResponse(
            agent_name=self.agent_name,
            status=AgentStatus.REWORK_REQUIRED if rework_requests else (AgentStatus.NEEDS_HUMAN if failures else AgentStatus.COMPLETED),
            result=result,
            published_result=result,
            confidence=conf,
            confidence_band=ConfidenceBand.HIGH,
            limitations=["Read-only compliance verifier; cannot mark failed controls as passed."],
            actions_executed=actions,
            rework_requests=rework_requests,
            decision=decision,
            model_id=model_id,
            model_version=model_version,
            prompt_version=self.prompt_version,
            rule_versions=request.rule_versions,
            suggested_next_action="resolve_compliance_gaps" if failures else "eligible_for_closure",
            tools_invoked=list(dict.fromkeys(tools_used)),
        )

    @staticmethod
    def _rework_target_for(control_name: str) -> str | None:
        mapping = {
            "no_unresolved_doc_mismatch": "document_intelligence",
            "survey_report_signed": "provider_coordination",
            "no_open_siu_alerts": "fraud_intelligence",
            "estimate_lines_reconciled": "estimate_validation",
            "confirmed_payment_or_declined": "settlement_recommendation",
        }
        return mapping.get(control_name)


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
