from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from packages.contracts.errors import DomainError, ErrorCode
from services.claims.audit import emit_outbox_event, record_audit_event
from services.claims.models import (
    Approval,
    Claim,
    ClaimParty,
    ClaimTask,
    DamageAssessment,
    DecisionRecord,
    Estimate,
    Evidence,
    ExtractedFact,
    FraudAlert,
    Grievance,
    Policy,
    Settlement,
    SurveyAssignment,
    Vehicle,
)
from services.claims.state_machine import ClaimStatus, to_canonical_state, validate_transition
from services.rules_engine.loader import get_active_rule, load_rule_files

_SUSPECTED_FRAUD_CODES = {
    "FRD-IMG-HASH-REUSE",
    "FRD-ENTITY-RING-CLUSTER",
    "FRD-GARAGE-ANOMALY-NETWORK",
    "FRD-EARLY-INCIDENT",
    "FRD-REPEAT-VEHICLE",
}
_SPECIAL_HIGH_RISK_PERILS = {"fire", "flood", "theft", "total_loss", "tp_bodily_injury", "tp_fatality"}
_MULTI_VEHICLE_KEYWORDS = ("multiple vehicle", "multi-vehicle", "multi vehicle", "pile-up", "pileup", "chain collision", "three cars", "two other vehicles")


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def sanitize_risk_payload_for_user(
    assessment: dict[str, Any] | None,
    *,
    siu_visible: bool,
) -> dict[str, Any] | None:
    """Masks SIU fraud scores and investigative indicators from non-SIU roles (ABAC isolation)."""
    if assessment is None or siu_visible:
        return assessment

    redacted = dict(assessment)
    redacted["fraud_signal_score"] = None
    dims = dict(redacted.get("evaluated_dimensions") or {})
    dims.pop("open_fraud_alerts_count", None)
    dims.pop("substantiated_fraud_alerts_count", None)
    redacted["evaluated_dimensions"] = dims

    clean_drivers: list[dict[str, Any]] = []
    for drv in redacted.get("drivers") or []:
        if drv.get("code") == "HIGH_SUSPECTED_FRAUD":
            clean_drivers.append(
                {
                    "code": "HIGH_SPECIALIST_REVIEW",
                    "tier": "HIGH",
                    "category": "Specialist verification required",
                    "points": drv.get("points", 40),
                    "summary": "Routed for internal specialist verification before settlement.",
                }
            )
        else:
            clean_drivers.append(drv)
    redacted["drivers"] = clean_drivers
    if "explanation" in redacted and "fraud" in str(redacted["explanation"]).lower():
        redacted["explanation"] = (
            f"{redacted.get('risk_tier', 'HIGH')} RISK — {redacted.get('operational_path_label', '')}: "
            "Routed for specialist human-led review and verification."
        )
    return redacted


def assert_fraud_score_never_rejects(
    *,
    decision: str,
    fraud_signal_score: Decimal | float | str | None = None,
    rationale: str = "",
) -> None:
    """Explicit compliance guardrail: a fraud score alone can NEVER determine claim rejection."""
    norm = decision.strip().lower()
    if norm in {"rejected", "repudiated", "declined", "auto_rejected"}:
        score_val = Decimal(str(fraud_signal_score or "0"))
        if "fraud_score" in rationale.lower() or "auto_reject_fraud" in rationale.lower():
            raise DomainError(
                ErrorCode.HUMAN_REVIEW_REQUIRED,
                (
                    f"Policy violation (IN-RISK-PROCESSING-2026 / IRDAI Fraud Due Process): "
                    f"fraud_signal_score ({score_val}) cannot determine claim rejection. "
                    "Escalate to HIGH risk SIU human investigation instead."
                ),
                status_code=409,
            )


def compute_fraud_signal_score(alerts: list[dict[str, Any]]) -> Decimal:
    """Computes an advisory 0.000-1.000 fraud signal score from indicators. Never rejects a claim."""
    active_weights: list[float] = []
    for a in alerts:
        status = str(a.get("status", "new"))
        if status in {"not_substantiated", "inconclusive", "closed"}:
            continue
        conf = float(a.get("confidence", 0.65) or 0.65)
        sev = str(a.get("severity_band", "medium"))
        code = str(a.get("indicator_code", ""))
        if status == "substantiated":
            active_weights.append(min(0.99, max(0.85, conf + 0.15)))
        elif code == "FRD-EST-ANOMALY" and sev == "low":
            active_weights.append(0.25)
        elif sev == "high":
            active_weights.append(min(0.95, conf))
        elif sev == "medium":
            active_weights.append(min(0.85, conf * 0.90))
        else:
            active_weights.append(min(0.60, conf * 0.50))

    if not active_weights:
        return Decimal("0.000")

    survival = 1.0
    for w in active_weights:
        survival *= 1.0 - max(0.0, min(0.99, w))
    score = round(1.0 - survival, 3)
    return Decimal(f"{min(0.999, max(0.0, score)):.3f}")


def classify_claim_risk_from_facts(
    facts: dict[str, Any],
    *,
    trigger_event: str = "risk_evaluation",
    rules_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic, explainable 3-tier risk classification (LOW / MEDIUM / HIGH)."""
    if rules_payload is None:
        all_rules = load_rule_files()
        rules_payload = all_rules["IN-RISK-PROCESSING-2026"]
    controls = rules_payload["controls"]
    paths = rules_payload["operational_paths"]

    low_max_loss = Decimal(str(controls.get("low_risk_max_estimate_inr", "49999.99")))
    auto_limit = Decimal(str(controls.get("fast_track_auto_approval_limit_inr", "25000.00")))
    sig_loss_threshold = Decimal(str(controls.get("significant_loss_threshold_inr", "250000.00")))
    ctl_ratio = Decimal(str(controls.get("ctl_idv_ratio_threshold", "0.75")))
    fraud_high_thresh = Decimal(str(controls.get("fraud_score_high_threshold", "0.650")))
    survey_threshold = Decimal("50000.00")

    effective_loss = Decimal(str(facts.get("effective_loss_inr") or facts.get("estimated_loss_inr") or "0.00"))
    idv_inr = Decimal(str(facts.get("idv_inr") or "0.00"))
    claim_type = str(facts.get("claim_type", "own_damage"))
    peril = str(facts.get("peril_cause", "road_accident"))
    claim_status = str(facts.get("claim_status", "REGISTERED"))

    injury = bool(facts.get("injury_or_fatality", False))
    multi_vehicle = bool(facts.get("multiple_vehicles_involved", False)) or int(facts.get("involved_vehicles_count", 1) or 1) > 1
    ev_battery = bool(facts.get("ev_battery_impacted", False)) or peril == "ev_high_voltage" or bool(facts.get("has_ev_battery_damage_obs", False))
    airbags = bool(facts.get("airbags_deployed", False))
    immobile = bool(facts.get("vehicle_immobile", False))
    towing = bool(facts.get("towing_needed", False))
    legal_dispute = bool(facts.get("legal_dispute", False))
    is_total_loss = bool(facts.get("is_total_loss", False)) or (idv_inr > Decimal("0.00") and effective_loss >= (idv_inr * ctl_ratio))

    policy_matched = bool(facts.get("policy_matched", True))
    policy_active = bool(facts.get("policy_active", True))
    period_valid = bool(facts.get("period_valid", True))
    policy_valid = policy_matched and policy_active and period_valid

    missing_docs = list(facts.get("missing_documents", []))
    has_doc_mismatch = bool(facts.get("has_doc_mismatch", False))
    prompt_inj = bool(facts.get("prompt_injection_flagged", False))
    doc_conflicts = int(facts.get("doc_conflict_count", 0) or 0)
    duplicate_candidate_id = facts.get("duplicate_candidate_claim_id")

    has_recapture_needed = bool(facts.get("has_recapture_needed", False))
    hidden_damage_found = bool(facts.get("hidden_damage_found", False))
    severe_structural_dmg = bool(facts.get("has_severe_structural_damage", False))
    moderate_dmg_inspection = bool(facts.get("has_inspection_required_damage", False))

    estimate_anomalies = list(facts.get("estimate_anomalies", []))
    estimate_overcharge = Decimal(str(facts.get("estimate_overcharge_inr", "0.00")))
    is_supplement_est = bool(facts.get("has_supplement_estimate", False))

    coverage_clarifications = list(facts.get("coverage_clarifications", []))
    open_dispute_grievances = int(facts.get("open_dispute_grievance_count", 0) or 0)
    has_assigned_garage = bool(facts.get("has_assigned_garage", False))

    fraud_alerts = list(facts.get("fraud_alerts", []))
    fraud_score = compute_fraud_signal_score(fraud_alerts)
    substantiated_alerts = [a for a in fraud_alerts if a.get("status") == "substantiated"]
    open_alerts = [a for a in fraud_alerts if a.get("status") in {"new", "assigned", "investigating"}]
    suspected_open_alerts = [
        a
        for a in open_alerts
        if a.get("indicator_code") in _SUSPECTED_FRAUD_CODES
        or a.get("severity_band") in {"medium", "high"}
    ]
    clerical_est_alerts = [
        a
        for a in open_alerts
        if a.get("indicator_code") == "FRD-EST-ANOMALY" and a.get("severity_band") == "low"
    ]

    drivers: list[dict[str, Any]] = []

    # ---- 1. Evaluate HIGH RISK drivers ----
    if injury or claim_type == "third_party" or peril in {"tp_bodily_injury", "tp_fatality"} or multi_vehicle or facts.get("has_tp_injury_party"):
        drivers.append(
            {
                "code": "HIGH_INJURY_OR_TP_LIABILITY",
                "tier": "HIGH",
                "category": "Injury or third-party liability",
                "points": 45,
                "summary": (
                    "Bodily injury / third-party liability or multi-vehicle collision requires specialist human-led MACT & legal review."
                    if (injury or claim_type == "third_party")
                    else f"Multiple vehicles involved ({facts.get('involved_vehicles_count', 2)}+) require liability & specialist handling."
                ),
            }
        )

    if substantiated_alerts or suspected_open_alerts or fraud_score >= fraud_high_thresh or duplicate_candidate_id:
        codes = [str(a.get("indicator_code", "FRD")) for a in (substantiated_alerts + suspected_open_alerts)]
        if duplicate_candidate_id and "DUPLICATE_OPEN_CLAIM" not in codes:
            codes.append("DUPLICATE_OPEN_CLAIM")
        drivers.append(
            {
                "code": "HIGH_SUSPECTED_FRAUD",
                "tier": "HIGH",
                "category": "Suspected fraud",
                "points": 40,
                "summary": (
                    f"Active SIU fraud/network lead(s) {codes} (advisory fraud_signal_score={fraud_score}); "
                    "routed to SIU investigation — fraud score NEVER auto-rejects."
                ),
            }
        )

    if (
        effective_loss >= sig_loss_threshold
        or is_total_loss
        or peril in _SPECIAL_HIGH_RISK_PERILS
        or airbags
        or severe_structural_dmg
    ):
        drivers.append(
            {
                "code": "HIGH_SIGNIFICANT_LOSS",
                "tier": "HIGH",
                "category": "Significant loss",
                "points": 35,
                "summary": (
                    f"Significant loss indicator (loss INR {effective_loss}, CTL={is_total_loss}, "
                    f"peril={peril}, airbags={airbags}, structural={severe_structural_dmg})."
                ),
            }
        )

    if has_doc_mismatch or prompt_inj or doc_conflicts > 0:
        drivers.append(
            {
                "code": "HIGH_CONFLICTING_EVIDENCE",
                "tier": "HIGH",
                "category": "Conflicting evidence",
                "points": 35,
                "summary": (
                    f"Conflicting/untrusted evidence detected (doc_mismatch={has_doc_mismatch}, "
                    f"prompt_injection={prompt_inj}, conflicts={doc_conflicts}); evidence preserved."
                ),
            }
        )

    if ev_battery:
        drivers.append(
            {
                "code": "HIGH_EV_BATTERY_DAMAGE",
                "tier": "HIGH",
                "category": "EV battery damage",
                "points": 35,
                "summary": "EV high-voltage traction battery / underbody impact requires certified EV specialist & BMS teardown.",
            }
        )

    if not policy_valid or legal_dispute or open_dispute_grievances > 0 or claim_status == "DECLINED_PARTIAL":
        drivers.append(
            {
                "code": "HIGH_LEGAL_OR_COVERAGE_DISPUTE",
                "tier": "HIGH",
                "category": "Legal or coverage disputes",
                "points": 35,
                "summary": (
                    f"Policy validity or legal/coverage dispute active (policy_valid={policy_valid}, "
                    f"legal_dispute={legal_dispute}, open_disputes={open_dispute_grievances})."
                ),
            }
        )

    # ---- 2. Evaluate MEDIUM RISK drivers ----
    requires_survey = (
        effective_loss >= survey_threshold
        or peril in {"theft", "fire", "flood", "total_loss", "ev_high_voltage", "tp_bodily_injury", "tp_fatality"}
        or injury
        or ev_battery
        or bool(facts.get("requires_mandatory_survey", False))
    )
    if (
        requires_survey
        or immobile
        or has_recapture_needed
        or hidden_damage_found
        or moderate_dmg_inspection
    ):
        drivers.append(
            {
                "code": "MEDIUM_DAMAGE_REQUIRES_INSPECTION",
                "tier": "MEDIUM",
                "category": "Damage requires inspection",
                "points": 22,
                "summary": (
                    f"Inspection required (loss INR {effective_loss}, mandatory_survey={requires_survey}, "
                    f"immobile={immobile}, recapture={has_recapture_needed}, hidden={hidden_damage_found})."
                ),
            }
        )

    if estimate_anomalies or clerical_est_alerts or estimate_overcharge > Decimal("0.00") or is_supplement_est:
        drivers.append(
            {
                "code": "MEDIUM_ESTIMATE_DISCREPANCIES",
                "tier": "MEDIUM",
                "category": "Estimate discrepancies",
                "points": 20,
                "summary": (
                    f"Repair estimate discrepancies ({len(estimate_anomalies)} anomaly(s), "
                    f"overcharge=INR {estimate_overcharge}, supplement={is_supplement_est})."
                ),
            }
        )

    if missing_docs:
        drivers.append(
            {
                "code": "MEDIUM_MISSING_DOCUMENTS",
                "tier": "MEDIUM",
                "category": "Missing documents",
                "points": 18,
                "summary": f"{len(missing_docs)} required document(s) pending follow-up: {', '.join(missing_docs[:4])}.",
            }
        )

    if policy_valid and coverage_clarifications:
        drivers.append(
            {
                "code": "MEDIUM_COVERAGE_CLARIFICATION",
                "tier": "MEDIUM",
                "category": "Coverage clarification",
                "points": 15,
                "summary": f"Coverage verification clarification(s): {'; '.join(coverage_clarifications[:2])}.",
            }
        )

    if towing or (claim_status == "REPAIR_IN_PROGRESS") or (
        not has_assigned_garage and claim_type in {"cashless", "own_damage"} and effective_loss >= survey_threshold
    ):
        drivers.append(
            {
                "code": "MEDIUM_REPAIR_COORDINATION",
                "tier": "MEDIUM",
                "category": "Repair coordination",
                "points": 15,
                "summary": f"Repair/provider coordination active (towing={towing}, assigned_garage={has_assigned_garage}).",
            }
        )

    # ---- 3. Determine Risk Tier & Operational Path ----
    high_drivers = [d for d in drivers if d["tier"] == "HIGH"]
    medium_drivers = [d for d in drivers if d["tier"] == "MEDIUM"]

    if high_drivers:
        risk_tier = "HIGH"
        raw_score = 65 + sum(int(d["points"]) for d in high_drivers[:3])
        risk_score = min(100, raw_score)
    elif medium_drivers:
        risk_tier = "MEDIUM"
        raw_score = 25 + sum(int(d["points"]) for d in medium_drivers[:3])
        risk_score = min(64, raw_score)
    else:
        risk_tier = "LOW"
        risk_score = 12
        drivers.append(
            {
                "code": "LOW_FAST_TRACK_ELIGIBLE",
                "tier": "LOW",
                "category": "Fast-track straight-through",
                "points": 12,
                "summary": (
                    f"Minor damage, complete documents, valid policy, low estimate (INR {effective_loss} < INR 50,000), "
                    "and zero material anomalies."
                ),
            }
        )

    path_cfg = paths[risk_tier]
    operational_path = str(path_cfg["path_code"])

    low_criteria = {
        "minor_damage": not (immobile or airbags or injury or ev_battery or severe_structural_dmg or peril in _SPECIAL_HIGH_RISK_PERILS),
        "complete_documents": len(missing_docs) == 0 and not has_recapture_needed,
        "valid_policy": policy_valid,
        "low_estimate": effective_loss <= low_max_loss,
        "no_material_anomalies": not (
            has_doc_mismatch
            or prompt_inj
            or doc_conflicts > 0
            or bool(estimate_anomalies)
            or bool(open_alerts)
            or bool(substantiated_alerts)
            or bool(duplicate_candidate_id)
            or open_dispute_grievances > 0
            or multi_vehicle
            or legal_dispute
        ),
    }

    # Third-Party liability claims are never straight-through eligible (IN-TP-LIABILITY-2026).
    straight_through_eligible = (
        risk_tier == "LOW"
        and all(low_criteria.values())
        and claim_type != "third_party"
        and peril not in {"tp_bodily_injury", "tp_fatality", "tp_property_damage"}
    )
    within_auto_limit = straight_through_eligible and effective_loss <= auto_limit

    if risk_tier == "HIGH":
        if injury or claim_type == "third_party" or peril in {"tp_bodily_injury", "tp_fatality"}:
            recommended_queue = "legal_tp_specialist"
            routing_priority = "P1_URGENT"
            recommended_triage_track = "INVESTIGATION_REQUIRED"
        elif ev_battery:
            recommended_queue = "ev_specialist"
            routing_priority = "P1_URGENT"
            recommended_triage_track = "INVESTIGATION_REQUIRED"
        elif substantiated_alerts or suspected_open_alerts or fraud_score >= fraud_high_thresh:
            recommended_queue = "siu_investigation"
            routing_priority = "P1_URGENT"
            recommended_triage_track = "INVESTIGATION_REQUIRED"
        elif has_doc_mismatch or prompt_inj or doc_conflicts > 0 or not policy_valid:
            recommended_queue = "complex_investigation_queue"
            routing_priority = "P1_URGENT"
            recommended_triage_track = "HUMAN_REVIEW"
        else:
            recommended_queue = "complex_od_survey"
            routing_priority = "P2_HIGH"
            recommended_triage_track = "INVESTIGATION_REQUIRED"
    elif risk_tier == "MEDIUM":
        if missing_docs or has_recapture_needed:
            recommended_queue = "evidence_follow_up"
        elif estimate_anomalies:
            recommended_queue = "estimate_discrepancy_queue"
        else:
            recommended_queue = "standard_survey_queue"
        routing_priority = "P2_HIGH" if immobile else "P3_NORMAL"
        recommended_triage_track = "SURVEY_REQUIRED" if requires_survey else "HUMAN_REVIEW"
    else:
        recommended_queue = "low_risk_od_assisted"
        routing_priority = "P4_FAST_TRACK"
        recommended_triage_track = "FAST_TRACK"

    active_summary = ", ".join(d["category"] for d in drivers[:3])
    explanation = (
        f"{risk_tier} RISK — {path_cfg['label']} ({path_cfg['handling_mode']}): {active_summary}. "
        f"Goal: {path_cfg['goal']}. "
        + (
            f"Eligible for straight-through automated processing (auto-approval limit <= INR {auto_limit}: {'YES' if within_auto_limit else 'L1 Fast-Track up to INR 49,999.99'})."
            if straight_through_eligible
            else (
                f"Evidence preservation active; fraud_signal_score={fraud_score} (never triggers rejection)."
                if risk_tier == "HIGH"
                else "AI-assisted standard handling to reduce handler effort and waiting time."
            )
        )
    )

    return {
        "risk_tier": risk_tier,
        "operational_path": operational_path,
        "operational_path_label": path_cfg["label"],
        "handling_mode": path_cfg["handling_mode"],
        "goal": path_cfg["goal"],
        "risk_score": risk_score,
        "fraud_signal_score": str(fraud_score),
        "fraud_score_can_reject": False,
        "fraud_guardrail_note": "Fraud score is an investigative risk signal only and NEVER determines claim rejection.",
        "rule_version": f"{rules_payload['rule_id']}:{rules_payload['version']}",
        "trigger_event": trigger_event,
        "recalculated_at": datetime.now(timezone.utc).isoformat(),
        "drivers": drivers,
        "low_risk_criteria_check": low_criteria,
        "evaluated_dimensions": {
            "effective_loss_inr": str(effective_loss),
            "survey_threshold_inr": str(survey_threshold),
            "significant_loss_threshold_inr": str(sig_loss_threshold),
            "policy_valid": policy_valid,
            "missing_documents_count": len(missing_docs),
            "estimate_anomalies_count": len(estimate_anomalies),
            "doc_conflicts_count": doc_conflicts + (1 if has_doc_mismatch else 0),
            "prompt_injection_flagged": prompt_inj,
            "open_fraud_alerts_count": len(open_alerts),
            "substantiated_fraud_alerts_count": len(substantiated_alerts),
            "injury_or_fatality": injury,
            "multiple_vehicles_involved": multi_vehicle,
            "ev_battery_impacted": ev_battery,
            "legal_or_coverage_dispute": legal_dispute or not policy_valid or open_dispute_grievances > 0,
        },
        "automation_eligibility": {
            "straight_through_eligible": straight_through_eligible,
            "auto_approval_limit_inr": str(auto_limit),
            "within_auto_approval_limit": within_auto_limit,
            "fast_track_assisted_limit_inr": str(controls.get("fast_track_assisted_limit_inr", "49999.99")),
            "requires_mandatory_survey": requires_survey and not straight_through_eligible,
            "evidence_preservation_active": risk_tier == "HIGH",
            "recommended_queue": recommended_queue,
            "recommended_triage_track": recommended_triage_track,
            "routing_priority": routing_priority,
        },
        "explanation": explanation,
    }


def gather_claim_risk_facts(db: Session, claim: Claim) -> dict[str, Any]:
    """Collects all live evidence, policy, damage, estimate, survey, fraud, and dispute signals for a claim."""
    policy = db.query(Policy).filter(Policy.id == claim.policy_id).first() if claim.policy_id else None
    vehicle = db.query(Vehicle).filter(Vehicle.id == claim.vehicle_id).first() if claim.vehicle_id else None
    parties = db.query(ClaimParty).filter(ClaimParty.claim_id == claim.id).all()
    evidences = db.query(Evidence).filter(Evidence.claim_id == claim.id).all()
    facts_rows = db.query(ExtractedFact).filter(ExtractedFact.claim_id == claim.id).all()
    damages = db.query(DamageAssessment).filter(DamageAssessment.claim_id == claim.id).all()
    estimates = db.query(Estimate).filter(Estimate.claim_id == claim.id).all()
    surveys = db.query(SurveyAssignment).filter(SurveyAssignment.claim_id == claim.id).all()
    alerts = db.query(FraudAlert).filter(FraudAlert.claim_id == claim.id).all()
    grievances = db.query(Grievance).filter(Grievance.claim_id == claim.id).all()
    settlements = db.query(Settlement).filter(Settlement.claim_id == claim.id).all()

    period_valid = False
    if policy:
        ps = policy.period_start.replace(tzinfo=timezone.utc) if policy.period_start.tzinfo is None else policy.period_start
        pe = policy.period_end.replace(tzinfo=timezone.utc) if policy.period_end.tzinfo is None else policy.period_end
        inc = claim.incident_at.replace(tzinfo=timezone.utc) if claim.incident_at.tzinfo is None else claim.incident_at
        period_valid = ps <= inc <= pe

    est_max_claimed = max((Decimal(str(e.total_claimed_inr)) for e in estimates), default=Decimal("0.00"))
    effective_loss = max(Decimal(str(claim.estimated_loss_inr or "0.00")), est_max_claimed)
    est_anomalies = [a for e in estimates for a in (e.anomalies or [])]
    est_overcharge = sum(
        (
            max(Decimal("0.00"), Decimal(str(e.total_claimed_inr)) - Decimal(str(e.total_approved_inr)))
            for e in estimates
            if e.status == "disputed"
        ),
        Decimal("0.00"),
    )

    doc_pub = (claim.workflow_state or {}).get("published_results", {}).get("document_intelligence", {}).get("data", {})
    cov_pub = (claim.coverage_factsheet or {}).get("result", {}) if isinstance(claim.coverage_factsheet, dict) else {}
    desc_lower = (claim.incident_description or "").lower()
    multi_vehicle_detected = (
        bool(claim.multiple_vehicles_involved)
        or int(claim.involved_vehicles_count or 1) > 1
        or any(k in desc_lower for k in _MULTI_VEHICLE_KEYWORDS)
        or any(p.party_role in {"other_vehicle", "third_party_vehicle"} for p in parties)
        or sum(1 for p in parties if p.party_role in {"third_party", "other_vehicle"}) > 1
    )

    return {
        "effective_loss_inr": str(effective_loss),
        "estimated_loss_inr": str(claim.estimated_loss_inr),
        "idv_inr": str(policy.idv_inr) if policy else "0.00",
        "claim_type": claim.claim_type,
        "peril_cause": claim.peril_cause,
        "claim_status": claim.status,
        "injury_or_fatality": bool(claim.injury_or_fatality),
        "multiple_vehicles_involved": multi_vehicle_detected,
        "involved_vehicles_count": max(int(claim.involved_vehicles_count or 1), 2 if multi_vehicle_detected else 1),
        "ev_battery_impacted": bool(claim.ev_battery_impacted),
        "has_ev_battery_damage_obs": any(
            d.damage_class == "ev_hv_alert" or "battery" in (d.component_name or "").lower() for d in damages
        ),
        "airbags_deployed": bool(claim.airbags_deployed),
        "vehicle_immobile": bool(claim.vehicle_immobile),
        "towing_needed": bool(claim.towing_needed),
        "legal_dispute": bool(claim.legal_dispute),
        "requires_mandatory_survey": bool(claim.requires_mandatory_survey),
        "is_total_loss": any(s.is_total_loss for s in settlements),
        "policy_matched": policy is not None,
        "policy_active": (policy.status == "active") if policy else False,
        "period_valid": period_valid,
        "missing_documents": list(claim.missing_documents or []),
        "has_doc_mismatch": any(f.validation_status == "mismatch" for f in facts_rows),
        "prompt_injection_flagged": any(e.prompt_injection_flagged for e in evidences),
        "doc_conflict_count": len(doc_pub.get("conflicts", []) if isinstance(doc_pub, dict) else []),
        "duplicate_candidate_claim_id": claim.duplicate_candidate_claim_id,
        "has_recapture_needed": any(e.image_quality_status == "recapture_needed" for e in evidences),
        "hidden_damage_found": any(bool((s.report_summary or {}).get("hidden_damage_found")) for s in surveys),
        "has_severe_structural_damage": any(
            (d.damage_class == "total_loss")
            or (
                "structural" in (d.limitations or "").lower()
                and d.observation_type == "inferred_possible"
                and effective_loss >= Decimal("100000.00")
            )
            for d in damages
        ),
        "has_inspection_required_damage": any(d.recommended_action == "inspect" for d in damages),
        "has_tp_injury_party": any(p.is_restricted_tp_medical for p in parties),
        "estimate_anomalies": est_anomalies,
        "estimate_overcharge_inr": str(est_overcharge),
        "has_supplement_estimate": any(e.is_supplement for e in estimates),
        "coverage_clarifications": list(cov_pub.get("ambiguities", [])) if policy and policy.status == "active" and period_valid else [],
        "open_dispute_grievance_count": sum(1 for g in grievances if g.status != "resolved" and g.category in {"coverage_dispute", "claim_repudiation", "legal_notice", "liability_dispute"}),
        "has_assigned_garage": claim.assigned_garage_id is not None,
        "is_ev_vehicle": bool(vehicle.is_ev) if vehicle else bool(claim.ev_battery_impacted),
        "fraud_alerts": [
            {
                "indicator_code": a.indicator_code,
                "severity_band": a.severity_band,
                "confidence": str(a.confidence),
                "status": a.status,
            }
            for a in alerts
        ],
    }


def evaluate_and_persist_risk(
    db: Session,
    claim: Claim,
    *,
    trigger_event: str,
    actor_id: str = "risk_engine",
    actor_role: str = "orchestrator",
    record_decision: bool = True,
    escalate_state: bool = True,
) -> dict[str, Any]:
    """Recalculates claim risk tier on latest evidence, persists transitions, and enforces evidence preservation."""
    try:
        rules_payload = get_active_rule(db, "IN-RISK-PROCESSING-2026")
    except KeyError:
        rules_payload = load_rule_files()["IN-RISK-PROCESSING-2026"]

    prev_tier = claim.risk_tier or "MEDIUM"
    prev_path = claim.operational_path or "standard"
    prev_score = int(claim.risk_score or 0)
    prev_codes = [d["code"] for d in (claim.risk_assessment or {}).get("drivers", [])] if isinstance(claim.risk_assessment, dict) else []

    facts = gather_claim_risk_facts(db, claim)
    assessment = classify_claim_risk_from_facts(facts, trigger_event=trigger_event, rules_payload=rules_payload)

    new_tier = assessment["risk_tier"]
    new_path = assessment["operational_path"]
    new_score = int(assessment["risk_score"])
    new_codes = [d["code"] for d in assessment["drivers"]]
    tier_changed = (not claim.risk_history) or (prev_tier != new_tier)

    claim.risk_tier = new_tier
    claim.operational_path = new_path
    claim.risk_score = new_score
    claim.fraud_signal_score = Decimal(str(assessment["fraud_signal_score"]))
    claim.risk_assessment = _json_safe({**assessment, "previous_risk_tier": prev_tier, "tier_changed": prev_tier != new_tier})
    claim.requires_mandatory_survey = bool(assessment["automation_eligibility"]["requires_mandatory_survey"])

    if new_tier == "HIGH":
        claim.severity_band = "critical" if (claim.injury_or_fatality or claim.claim_type == "third_party") else "high"
    elif new_tier == "MEDIUM":
        claim.severity_band = "medium"
    else:
        claim.severity_band = "low"

    if claim.status not in {ClaimStatus.CLOSED.value, ClaimStatus.APPROVED.value, ClaimStatus.PAYMENT_PENDING.value, ClaimStatus.PAYMENT_RECONCILIATION.value}:
        claim.queue_name = assessment["automation_eligibility"]["recommended_queue"]

    history = list(claim.risk_history or [])
    if tier_changed or prev_codes != new_codes:
        history.append(
            {
                "event_id": f"rsk-{uuid.uuid4().hex[:8]}",
                "trigger_event": trigger_event,
                "previous_tier": prev_tier if claim.risk_history else None,
                "new_tier": new_tier,
                "previous_path": prev_path if claim.risk_history else None,
                "new_path": new_path,
                "previous_score": prev_score if claim.risk_history else None,
                "new_score": new_score,
                "fraud_signal_score": assessment["fraud_signal_score"],
                "driver_codes": new_codes,
                "explanation": assessment["explanation"],
                "timestamp": assessment["recalculated_at"],
            }
        )
        claim.risk_history = _json_safe(history)

    # Preserve evidence automatically on HIGH RISK
    preserved_count = 0
    if new_tier == "HIGH":
        evidences = db.query(Evidence).filter(Evidence.claim_id == claim.id).all()
        for ev in evidences:
            if not ev.legal_hold:
                ev.legal_hold = True
                preserved_count += 1

    # Handle dynamic escalation to HIGH RISK
    escalated_to_high = prev_tier != "HIGH" and new_tier == "HIGH" and (len(history) > 1 or bool(prev_codes))
    if escalated_to_high:
        assigned_role = (
            "legal_tp"
            if any(d["code"] == "HIGH_INJURY_OR_TP_LIABILITY" for d in assessment["drivers"])
            else (
                "siu_investigator"
                if any(d["code"] == "HIGH_SUSPECTED_FRAUD" for d in assessment["drivers"])
                else "claims_manager"
            )
        )
        existing_task = (
            db.query(ClaimTask)
            .filter(
                ClaimTask.claim_id == claim.id,
                ClaimTask.task_type == "risk_escalation",
                ClaimTask.status.in_(["open", "in_progress"]),
            )
            .first()
        )
        if not existing_task:
            db.add(
                ClaimTask(
                    tenant_id=claim.tenant_id,
                    claim_id=claim.id,
                    task_type="risk_escalation",
                    title=f"Risk Escalated ({prev_tier} -> HIGH): Specialist Investigation Required",
                    description=assessment["explanation"],
                    assigned_role=assigned_role,
                    created_by_agent=actor_id,
                    priority="critical",
                    reason_code="RC_RISK_ESCALATED_TO_HIGH",
                    metadata_json={"previous_tier": prev_tier, "trigger_event": trigger_event, "drivers": new_codes},
                )
            )

        # Void any pending straight-through / L1 approvals if claim became HIGH risk
        pending_apps = db.query(Approval).filter(Approval.claim_id == claim.id, Approval.decision == "pending").all()
        for app in pending_apps:
            app.decision = "escalated_high_risk"
            app.rationale = f"Escalated from {prev_tier} to HIGH risk ({trigger_event}); requires specialist/manager decision."
        auto_apps = (
            db.query(Approval)
            .filter(Approval.claim_id == claim.id, Approval.action_type == "fast_track_auto_approval", Approval.decision == "approved")
            .all()
        )
        if auto_apps and claim.status not in {ClaimStatus.PAYMENT_PENDING.value, ClaimStatus.PAYMENT_RECONCILIATION.value, ClaimStatus.CLOSED.value}:
            for app in auto_apps:
                app.decision = "superseded_risk_escalation"
                app.rationale = f"Auto fast-track approval superseded after escalation to HIGH risk ({trigger_event})."
                if app.settlement_id:
                    stl = db.query(Settlement).filter(Settlement.id == app.settlement_id).first()
                    if stl:
                        stl.approval_status = "pending_checker"

        if escalate_state and claim.status in {
            ClaimStatus.FAST_TRACK.value,
            ClaimStatus.SURVEY_REQUIRED.value,
            ClaimStatus.SURVEY_ASSIGNED.value,
            ClaimStatus.TRIAGED.value,
            ClaimStatus.ASSESSMENT.value,
            ClaimStatus.ESTIMATE_VALIDATION.value,
            ClaimStatus.ESTIMATE_REVIEW.value,
            ClaimStatus.SETTLEMENT_PENDING_APPROVAL.value,
            ClaimStatus.SETTLEMENT_RECOMMENDED.value,
            ClaimStatus.APPROVAL_PENDING.value,
            ClaimStatus.APPROVED.value,
        }:
            only_doc_conflict = bool(assessment["drivers"]) and all(
                d["code"] == "HIGH_CONFLICTING_EVIDENCE" for d in assessment["drivers"]
            )
            target = (
                ClaimStatus.HUMAN_REVIEW.value
                if only_doc_conflict
                else ClaimStatus.INVESTIGATION_REQUIRED.value
            )
            try:
                validated = validate_transition(claim.status, target)
                before_st = claim.status
                claim.status = validated.value
                wf = dict(claim.workflow_state or {})
                wf["current_state"] = validated.value
                wf["canonical_state"] = to_canonical_state(validated.value)
                wf["triage_track"] = assessment["automation_eligibility"]["recommended_triage_track"]
                st_hist = list(wf.get("state_history", []))
                st_hist.append(
                    {
                        "from_state": before_st,
                        "to_state": validated.value,
                        "canonical_state": to_canonical_state(validated.value),
                        "reason": f"Risk escalated {prev_tier} -> HIGH ({trigger_event})",
                        "trigger_event": "RiskTierEscalated",
                        "actor": "risk_engine",
                        "timestamp": assessment["recalculated_at"],
                    }
                )
                wf["state_history"] = st_hist
                claim.workflow_state = _json_safe(wf)
                claim.next_expected_action = f"HIGH RISK escalation ({trigger_event}): specialist human-led investigation required"
            except DomainError:
                pass

    if tier_changed or prev_codes != new_codes:
        record_audit_event(
            db,
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            actor_id=actor_id,
            actor_role=actor_role,
            action="RISK_TIER_RECALCULATED",
            object_type="claim",
            object_id=claim.id,
            before_state={"risk_tier": prev_tier, "operational_path": prev_path, "risk_score": prev_score},
            after_state={
                "risk_tier": new_tier,
                "operational_path": new_path,
                "risk_score": new_score,
                "fraud_signal_score": assessment["fraud_signal_score"],
                "evidence_legal_hold_updated": preserved_count,
            },
            details={"trigger_event": trigger_event, "drivers": new_codes},
        )
        emit_outbox_event(
            db,
            tenant_id=claim.tenant_id,
            aggregate_id=claim.id,
            event_type="ClaimRiskRecalculated",
            payload={
                "previous_tier": prev_tier,
                "new_tier": new_tier,
                "operational_path": new_path,
                "trigger_event": trigger_event,
                "fraud_signal_score": assessment["fraud_signal_score"],
            },
        )
        if record_decision:
            db.add(
                DecisionRecord(
                    tenant_id=claim.tenant_id,
                    claim_id=claim.id,
                    agent_name="risk_classifier",
                    stage="Risk-Based Processing",
                    decision_id=f"dec-risk-{uuid.uuid4().hex[:8]}",
                    routing_outcome=f"{new_tier}:{new_path}",
                    reason_codes=new_codes,
                    evidence=[d["summary"] for d in assessment["drivers"][:4]],
                    policy_rule_refs=[assessment["rule_version"], "IN-IRDAI-MC-2024:1.0.0"],
                    confidence=Decimal("0.960"),
                    confidence_band="high",
                    explanation=assessment["explanation"],
                    alternatives_considered=[
                        "auto_reject_on_fraud_score (strictly prohibited by IN-RISK-PROCESSING-2026)"
                    ],
                )
            )

    db.flush()
    return assessment
