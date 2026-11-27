from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from packages.contracts.errors import DomainError, ErrorCode
from packages.security.auth import Role, UserContext
from services.claims.audit import emit_outbox_event, record_audit_event
from services.claims.models import (
    Claim,
    ClaimTask,
    Communication,
    DamageAssessment,
    EcosystemCoordination,
    Estimate,
    EstimateLine,
    Provider,
    SurveyAssignment,
    Vehicle,
)
from services.integrations.adapters import IntegrationAdapterRegistry
from services.rules_engine.loader import get_active_rule
from services.workflow.sla_engine import complete_stage_sla_timer, create_stage_sla_timer

AUTHORIZED_OVERRIDE_ROLES = {Role.CLAIMS_MANAGER.value, Role.ADMIN.value, "claims_manager", "admin"}

REPAIR_MILESTONE_ORDER: list[str] = [
    "not_started",
    "intake_confirmed",
    "teardown_in_progress",
    "awaiting_parts",
    "body_paint_in_progress",
    "qc_pending",
    "repair_completed",
    "handover_confirmed",
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def compute_provider_load_band(active_load: int, max_capacity: int) -> str:
    cap = max(int(max_capacity or 1), 1)
    ratio = float(active_load or 0) / cap
    if ratio < 0.50:
        return "Low"
    if ratio < 0.80:
        return "Medium"
    return "High"


def compute_availability_label(provider: Provider) -> str:
    if not provider.is_available:
        return "Unavailable"
    if int(provider.active_load or 0) >= int(provider.max_capacity or 1):
        return "Busy"
    ratio = float(provider.active_load or 0) / max(int(provider.max_capacity or 1), 1)
    if ratio >= 0.80:
        return "Busy"
    return "Available"


def compute_sla_label(sla_status: str) -> str:
    mapping = {
        "within_sla": "Within SLA",
        "at_risk": "At Risk",
        "delayed": "Delayed",
    }
    return mapping.get((sla_status or "within_sla").lower(), "Within SLA")


def verify_surveyor_license(provider: Provider) -> dict[str, Any]:
    return IntegrationAdapterRegistry.verify_surveyor_licence(
        licence_id=provider.licence_or_contract_id,
        licence_status=provider.licence_status,
        licence_expiry_at=provider.licence_expiry_at,
    )


def _extract_city_tokens(incident_location: str) -> list[str]:
    text = (incident_location or "").lower()
    known = ["mumbai", "andheri", "bandra", "worli", "thane", "bengaluru", "bangalore", "koramangala", "pune", "delhi", "ncr"]
    tokens = [tok for tok in known if tok in text]
    for part in text.replace(",", " ").split():
        cleaned = part.strip()
        if len(cleaned) >= 4 and cleaned not in tokens:
            tokens.append(cleaned)
    return tokens


def _required_skills_for_claim(
    *,
    ev_required: bool,
    peril_cause: str,
    vehicle_make: str = "",
    requires_adas: bool = False,
) -> list[str]:
    skills: list[str] = []
    if ev_required:
        skills.append("ev_hv")
    if peril_cause in {"fire", "flood", "total_loss", "theft"}:
        skills.append("complex_peril")
    if requires_adas:
        skills.append("adas_calibration")
    make_low = (vehicle_make or "").lower()
    if "maruti" in make_low:
        skills.append("oem_maruti")
    elif "tata" in make_low:
        skills.append("oem_tata")
    elif "hyundai" in make_low:
        skills.append("oem_hyundai")
    return skills


def score_provider_candidate(
    provider: Provider,
    *,
    incident_location: str,
    required_skills: list[str],
    ev_required: bool,
    cashless_required: bool = False,
    preferred_id: str | None = None,
) -> dict[str, Any]:
    """Deterministic multi-factor provider scoring across geography, skill, capacity, SLA, and rating."""
    loc_tokens = _extract_city_tokens(incident_location)
    prov_city = (provider.city or "").lower()
    prov_zones = [str(z).lower() for z in (provider.service_zones or [])]

    # 1. Geography (0 - 30 pts)
    geo_score = 8
    geo_match = "regional_fallback"
    if any(tok == prov_city or tok in prov_city for tok in loc_tokens):
        geo_score = 26
        geo_match = "city_match"
    if any(any(tok in z or z in tok for z in prov_zones) for tok in loc_tokens):
        geo_score = 30
        geo_match = "zone_exact_match"

    # 2. Skill & Safety Capability (0 - 25 pts)
    prov_skills = {str(s).lower() for s in (provider.skills or [])}
    if provider.ev_capable:
        prov_skills.add("ev_hv")
    matched_skills = [s for s in required_skills if s.lower() in prov_skills]
    if required_skills:
        skill_score = round(25 * (len(matched_skills) / len(required_skills)))
    else:
        skill_score = 20
    if ev_required and not provider.ev_capable:
        skill_score = 0

    # 3. Capacity & Availability (0 - 20 pts)
    cap = max(int(provider.max_capacity or 1), 1)
    headroom = max(0, cap - int(provider.active_load or 0))
    headroom_ratio = headroom / cap
    capacity_score = round(20 * headroom_ratio) if provider.is_available else 0

    # 4. SLA Performance (0 - 15 pts)
    sla_st = (provider.sla_status or "within_sla").lower()
    sla_score = 15 if sla_st == "within_sla" else (8 if sla_st == "at_risk" else 2)

    # 5. Rating / Quality (0 - 10 pts)
    rating_val = float(provider.quality_score or Decimal("4.0"))
    rating_score = min(10, round((rating_val / 5.0) * 10, 1))

    # Eligibility gates (licence, capacity, EV safety, network contract)
    eligible = True
    ineligible_reasons: list[str] = []
    if not provider.is_available:
        eligible = False
        ineligible_reasons.append("provider_marked_unavailable")
    if headroom <= 0:
        eligible = False
        ineligible_reasons.append("capacity_exhausted")
    if provider.provider_type == "surveyor":
        lic = verify_surveyor_license(provider)
        if not lic["verified"]:
            eligible = False
            ineligible_reasons.append(f"license_invalid:{lic['reason']}")
    if ev_required and not provider.ev_capable:
        eligible = False
        ineligible_reasons.append("ev_hv_safety_certification_required")
    if cashless_required and provider.provider_type == "garage" and not provider.is_network:
        eligible = False
        ineligible_reasons.append("contractual_cashless_network_required")

    total_score = round(geo_score + skill_score + capacity_score + sla_score + rating_score, 1)
    return {
        "provider_id": provider.id,
        "provider_name": provider.name,
        "provider_type": provider.provider_type,
        "eligible": eligible,
        "ineligible_reasons": ineligible_reasons,
        "is_customer_preferred": bool(preferred_id and provider.id == preferred_id),
        "total_score": total_score,
        "breakdown": {
            "geography_score": geo_score,
            "geography_match": geo_match,
            "skill_score": skill_score,
            "matched_skills": matched_skills,
            "capacity_score": capacity_score,
            "active_load": int(provider.active_load or 0),
            "max_capacity": cap,
            "load_band": compute_provider_load_band(int(provider.active_load or 0), cap),
            "sla_score": sla_score,
            "sla_label": compute_sla_label(sla_st),
            "rating_score": rating_score,
            "rating": float(rating_val),
        },
        "availability_label": compute_availability_label(provider),
        "sla_label": compute_sla_label(sla_st),
        "load_band": compute_provider_load_band(int(provider.active_load or 0), cap),
    }


def serialize_provider_scorecard(provider: Provider) -> dict[str, Any]:
    active_load = int(provider.active_load or 0)
    max_cap = max(int(provider.max_capacity or 1), 1)
    return {
        "id": provider.id,
        "provider_type": provider.provider_type,
        "name": provider.name,
        "licence_or_contract_id": provider.licence_or_contract_id,
        "licence_status": provider.licence_status,
        "licence_expiry_at": provider.licence_expiry_at.isoformat() if provider.licence_expiry_at else None,
        "city": provider.city,
        "service_zones": provider.service_zones or [provider.city],
        "skills": provider.skills or (["ev_hv"] if provider.ev_capable else []),
        "ev_capable": provider.ev_capable,
        "is_network": provider.is_network,
        "contract_tier": provider.contract_tier,
        "active_load": active_load,
        "max_capacity": max_cap,
        "load_ratio_pct": round((active_load / max_cap) * 100),
        "current_load": compute_provider_load_band(active_load, max_cap),
        "availability": compute_availability_label(provider),
        "is_available": provider.is_available,
        "sla": compute_sla_label(provider.sla_status),
        "sla_status": provider.sla_status,
        "sla_target_hours": provider.sla_target_hours,
        "avg_turnaround_hours": provider.avg_turnaround_hours,
        "rating": float(provider.quality_score or Decimal("4.5")),
        "quality_score": str(provider.quality_score),
        "parts_stock_status": provider.parts_stock_status,
        "parts_lead_time_days": provider.parts_lead_time_days,
        "pickup_drop_available": provider.pickup_drop_available,
        "towing_capable": provider.towing_capable,
    }


def select_best_surveyor(
    candidates: list[Provider],
    *,
    incident_location: str,
    required_skills: list[str],
    ev_required: bool,
    preferred_surveyor_id: str | None = None,
    override_authorized: bool = False,
    actor_role: str = "claims_handler",
    override_reason: str = "",
) -> dict[str, Any]:
    scored = [
        score_provider_candidate(
            p,
            incident_location=incident_location,
            required_skills=required_skills,
            ev_required=ev_required,
            preferred_id=preferred_surveyor_id,
        )
        for p in candidates
        if p.provider_type == "surveyor"
    ]
    by_id = {p.id: p for p in candidates if p.provider_type == "surveyor"}
    eligible = [s for s in scored if s["eligible"]]
    eligible.sort(key=lambda s: (-s["total_score"], s["breakdown"]["active_load"], -s["breakdown"]["rating"]))

    if preferred_surveyor_id and preferred_surveyor_id in by_id:
        pref_provider = by_id[preferred_surveyor_id]
        pref_score = next(s for s in scored if s["provider_id"] == preferred_surveyor_id)
        if not pref_score["eligible"]:
            # Contractual / regulatory block: NEVER assign an unverified/expired surveyor even with override
            if any(r.startswith("license_invalid") for r in pref_score["ineligible_reasons"]):
                return {
                    "selected": by_id[eligible[0]["provider_id"]] if eligible else None,
                    "selected_score": eligible[0] if eligible else None,
                    "blocked": bool(not eligible),
                    "blocked_reason": f"Requested surveyor {pref_provider.name} failed IIISLA licence verification ({', '.join(pref_score['ineligible_reasons'])}).",
                    "explanation": (
                        f"Blocked requested surveyor {pref_provider.name} due to IRDAI IIISLA licence verification failure; "
                        + (f"reassigned to verified {eligible[0]['provider_name']} (score {eligible[0]['total_score']})." if eligible else "no verified surveyor available.")
                    ),
                    "candidates_evaluated": scored,
                }
        else:
            return {
                "selected": pref_provider,
                "selected_score": pref_score,
                "blocked": False,
                "blocked_reason": "",
                "explanation": (
                    f"Selected verified IIISLA surveyor {pref_provider.name} (score {pref_score['total_score']}/100: "
                    f"geo={pref_score['breakdown']['geography_match']}, load={pref_score['load_band']} "
                    f"{pref_provider.active_load}/{pref_provider.max_capacity}, SLA={pref_score['sla_label']}, rating={pref_score['breakdown']['rating']})."
                ),
                "candidates_evaluated": scored,
            }

    if not eligible:
        return {
            "selected": None,
            "selected_score": None,
            "blocked": True,
            "blocked_reason": "No verified, available IIISLA surveyor within capacity in roster.",
            "explanation": "Surveyor selection blocked: zero verified IIISLA surveyors have available capacity.",
            "candidates_evaluated": scored,
        }

    winner = eligible[0]
    win_prov = by_id[winner["provider_id"]]
    runner_up = eligible[1] if len(eligible) > 1 else None
    runner_note = (
        f" Outranked {runner_up['provider_name']} (score {runner_up['total_score']}, load {runner_up['load_band']})."
        if runner_up
        else ""
    )
    explanation = (
        f"Selected {win_prov.name} (score {winner['total_score']}/100) based on geography ({winner['breakdown']['geography_match']} in {win_prov.city}), "
        f"skills ({', '.join(winner['breakdown']['matched_skills']) or 'general_motor'}), "
        f"capacity ({winner['load_band']}: {win_prov.active_load}/{win_prov.max_capacity}), "
        f"SLA ({winner['sla_label']}), and rating ({winner['breakdown']['rating']}/5.0).{runner_note}"
    )
    return {
        "selected": win_prov,
        "selected_score": winner,
        "blocked": False,
        "blocked_reason": "",
        "explanation": explanation,
        "candidates_evaluated": scored,
    }


def select_best_garage(
    candidates: list[Provider],
    *,
    incident_location: str,
    required_skills: list[str],
    ev_required: bool,
    cashless_required: bool = True,
    customer_preferred_garage_id: str | None = None,
    requested_override_garage_id: str | None = None,
    override_authorized: bool = False,
    actor_role: str = "claims_handler",
    override_reason: str = "",
) -> dict[str, Any]:
    """Selects workshop while strictly protecting customer preference and contractual rules."""
    garages = [p for p in candidates if p.provider_type == "garage"]
    by_id = {p.id: p for p in garages}
    scored = [
        score_provider_candidate(
            p,
            incident_location=incident_location,
            required_skills=required_skills,
            ev_required=ev_required,
            cashless_required=cashless_required,
            preferred_id=customer_preferred_garage_id,
        )
        for p in garages
    ]
    eligible = [s for s in scored if s["eligible"]]
    eligible.sort(key=lambda s: (-s["total_score"], s["breakdown"]["active_load"], -s["breakdown"]["rating"]))

    has_manager_auth = override_authorized and actor_role in AUTHORIZED_OVERRIDE_ROLES and bool(override_reason.strip())

    # Guardrail 1: Check explicit attempt to override customer's preferred garage
    if (
        customer_preferred_garage_id
        and requested_override_garage_id
        and requested_override_garage_id != customer_preferred_garage_id
    ):
        pref_score = next((s for s in scored if s["provider_id"] == customer_preferred_garage_id), None)
        pref_is_eligible = bool(pref_score and pref_score["eligible"])
        if pref_is_eligible and not has_manager_auth:
            return {
                "selected": by_id.get(customer_preferred_garage_id),
                "selected_score": pref_score,
                "customer_preference_honoured": True,
                "override_applied": False,
                "ev_safety_override_applied": False,
                "authorization_blocked": True,
                "blocked_reason": (
                    "Customer choice protection: cannot override eligible customer-preferred garage without "
                    "Claims Manager / Admin authorization and documented override_reason."
                ),
                "explanation": (
                    f"Retained customer-preferred garage {by_id[customer_preferred_garage_id].name}; "
                    "unauthorized override request was blocked by policy."
                ),
                "candidates_evaluated": scored,
            }

    # Guardrail 2: Customer preferred garage exists -> evaluate contractual & safety compliance
    if customer_preferred_garage_id and customer_preferred_garage_id in by_id:
        pref_prov = by_id[customer_preferred_garage_id]
        pref_score = next(s for s in scored if s["provider_id"] == customer_preferred_garage_id)

        # If manager explicitly authorized switching to another eligible garage
        if requested_override_garage_id and requested_override_garage_id != customer_preferred_garage_id and has_manager_auth:
            target_prov = by_id.get(requested_override_garage_id)
            target_score = next((s for s in scored if s["provider_id"] == requested_override_garage_id), None)
            if not target_prov or not target_score or not target_score["eligible"]:
                return {
                    "selected": None,
                    "selected_score": None,
                    "customer_preference_honoured": False,
                    "override_applied": False,
                    "ev_safety_override_applied": False,
                    "authorization_blocked": True,
                    "blocked_reason": (
                        f"Contractual guardrail: cannot override to garage '{requested_override_garage_id}' "
                        "because it fails mandatory contractual/EV/capacity requirements."
                    ),
                    "explanation": "Authorized override rejected because target garage violates contractual/EV safety rules.",
                    "candidates_evaluated": scored,
                }
            return {
                "selected": target_prov,
                "selected_score": target_score,
                "customer_preference_honoured": False,
                "override_applied": True,
                "ev_safety_override_applied": ev_required and not pref_prov.ev_capable,
                "authorization_blocked": False,
                "blocked_reason": "",
                "explanation": (
                    f"Authorized override by {actor_role}: selected {target_prov.name} over customer-preferred "
                    f"{pref_prov.name}. Rationale: {override_reason}"
                ),
                "candidates_evaluated": scored,
            }

        # Customer preferred garage violates mandatory EV HV safety contractual rule -> contractual safety redirect
        if not pref_score["eligible"]:
            ev_blocked = "ev_hv_safety_certification_required" in pref_score["ineligible_reasons"]
            contract_blocked = "contractual_cashless_network_required" in pref_score["ineligible_reasons"]
            if ev_blocked:
                if eligible:
                    win_score = eligible[0]
                    win_prov = by_id[win_score["provider_id"]]
                    return {
                        "selected": win_prov,
                        "selected_score": win_score,
                        "customer_preference_honoured": False,
                        "override_applied": True,
                        "ev_safety_override_applied": True,
                        "authorization_blocked": False,
                        "blocked_reason": "",
                        "explanation": (
                            f"Contractual EV HV safety mandate (POL-WORDING-EV-2025:EV-SAFE-01) prevented assignment to "
                            f"non-EV workshop {pref_prov.name}; selected EV-certified {win_prov.name} "
                            f"(score {win_score['total_score']}/100, load {win_score['load_band']}, SLA {win_score['sla_label']})."
                        ),
                        "candidates_evaluated": scored,
                    }
            if contract_blocked and not has_manager_auth:
                return {
                    "selected": None,
                    "selected_score": pref_score,
                    "customer_preference_honoured": False,
                    "override_applied": False,
                    "ev_safety_override_applied": False,
                    "authorization_blocked": True,
                    "blocked_reason": (
                        f"Contractual cashless rule: preferred garage {pref_prov.name} is non-network. "
                        "Manager/Admin authorization required to override contractual cashless network rule."
                    ),
                    "explanation": "Blocked non-network garage assignment pending authorized contractual exception.",
                    "candidates_evaluated": scored,
                }
            # Preferred garage is busy/full -> only redirect if capacity exhausted and best alternative exists
            if eligible and "capacity_exhausted" in pref_score["ineligible_reasons"]:
                if not has_manager_auth:
                    return {
                        "selected": None,
                        "selected_score": pref_score,
                        "customer_preference_honoured": True,
                        "override_applied": False,
                        "ev_safety_override_applied": False,
                        "authorization_blocked": True,
                        "blocked_reason": (
                            f"Customer preferred garage {pref_prov.name} is at full capacity; manager authorization or "
                            "customer consent required before redirecting."
                        ),
                        "explanation": f"Held redirect from {pref_prov.name} pending customer/manager authorization.",
                        "candidates_evaluated": scored,
                    }

        # Preferred garage is eligible -> honour customer preference!
        return {
            "selected": pref_prov,
            "selected_score": pref_score,
            "customer_preference_honoured": True,
            "override_applied": False,
            "ev_safety_override_applied": False,
            "authorization_blocked": False,
            "blocked_reason": "",
            "explanation": (
                f"Honoured customer-preferred garage {pref_prov.name} (score {pref_score['total_score']}/100: "
                f"geo={pref_score['breakdown']['geography_match']}, load={pref_score['load_band']} "
                f"{pref_prov.active_load}/{pref_prov.max_capacity}, SLA={pref_score['sla_label']}, rating={pref_score['breakdown']['rating']})."
            ),
            "candidates_evaluated": scored,
        }

    # No customer preferred garage specified -> select highest scoring eligible garage
    if not eligible:
        return {
            "selected": None,
            "selected_score": None,
            "customer_preference_honoured": True,
            "override_applied": False,
            "ev_safety_override_applied": False,
            "authorization_blocked": False,
            "blocked_reason": "No eligible network garage available for claim requirements.",
            "explanation": "No eligible garage matched geography, EV capability, capacity, and contractual network criteria.",
            "candidates_evaluated": scored,
        }

    winner = eligible[0]
    win_prov = by_id[winner["provider_id"]]
    runner_up = eligible[1] if len(eligible) > 1 else None
    runner_note = (
        f" Selected over {runner_up['provider_name']} (score {runner_up['total_score']}, load {runner_up['load_band']}, SLA {runner_up['sla_label']})."
        if runner_up
        else ""
    )
    explanation = (
        f"Selected {win_prov.name} (score {winner['total_score']}/100) based on geography ({winner['breakdown']['geography_match']} in {win_prov.city}), "
        f"skills ({', '.join(winner['breakdown']['matched_skills']) or 'standard_bodyshop'}), "
        f"capacity ({winner['load_band']}: {win_prov.active_load}/{win_prov.max_capacity}), "
        f"SLA ({winner['sla_label']}), and rating ({winner['breakdown']['rating']}/5.0).{runner_note}"
    )
    return {
        "selected": win_prov,
        "selected_score": winner,
        "customer_preference_honoured": True,
        "override_applied": False,
        "ev_safety_override_applied": False,
        "authorization_blocked": False,
        "blocked_reason": "",
        "explanation": explanation,
        "candidates_evaluated": scored,
    }


def _append_notification(coord: EcosystemCoordination, *, event: str, channel: str, message: str) -> None:
    notifs = list(coord.customer_notifications or [])
    notifs.append(
        {
            "event": event,
            "channel": channel,
            "message": message,
            "sent_at": _utcnow().isoformat(),
        }
    )
    coord.customer_notifications = notifs


def get_or_create_ecosystem_coordination(db: Session, claim: Claim) -> EcosystemCoordination:
    coord = db.query(EcosystemCoordination).filter(EcosystemCoordination.claim_id == claim.id).first()
    if coord:
        return coord
    coord = EcosystemCoordination(
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        surveyor_id=claim.assigned_surveyor_id,
        garage_id=claim.assigned_garage_id,
        customer_preferred_garage_id=claim.assigned_garage_id,
        towing_required=bool(claim.towing_needed or claim.vehicle_immobile),
        towing_status="dispatched" if (claim.towing_needed or claim.vehicle_immobile) else "not_required",
        towing_ev_flatbed=bool(claim.ev_battery_impacted),
        repair_status=str((claim.workflow_state or {}).get("repair_milestone") or "not_started"),
    )
    db.add(coord)
    db.flush()
    return coord


def serialize_ecosystem_coordination(db: Session, coord: EcosystemCoordination) -> dict[str, Any]:
    surv = db.query(Provider).filter(Provider.id == coord.surveyor_id).first() if coord.surveyor_id else None
    gar = db.query(Provider).filter(Provider.id == coord.garage_id).first() if coord.garage_id else None
    pref_gar = (
        db.query(Provider).filter(Provider.id == coord.customer_preferred_garage_id).first()
        if coord.customer_preferred_garage_id
        else None
    )
    tow = db.query(Provider).filter(Provider.id == coord.towing_provider_id).first() if coord.towing_provider_id else None
    return {
        "id": coord.id,
        "claim_id": coord.claim_id,
        "surveyor": serialize_provider_scorecard(surv) if surv else None,
        "surveyor_license_verified": coord.surveyor_license_verified,
        "surveyor_license_checked_at": coord.surveyor_license_checked_at.isoformat() if coord.surveyor_license_checked_at else None,
        "surveyor_selection_explanation": coord.surveyor_selection_explanation,
        "surveyor_score_breakdown": coord.surveyor_score_breakdown or {},
        "garage": serialize_provider_scorecard(gar) if gar else None,
        "customer_preferred_garage": serialize_provider_scorecard(pref_gar) if pref_gar else None,
        "customer_preference_honoured": coord.customer_preference_honoured,
        "override_applied": coord.override_applied,
        "override_authorized": coord.override_authorized,
        "override_authorized_by": coord.override_authorized_by,
        "override_reason_code": coord.override_reason_code,
        "override_justification": coord.override_justification,
        "garage_selection_explanation": coord.garage_selection_explanation,
        "garage_score_breakdown": coord.garage_score_breakdown or {},
        "inspection_status": coord.inspection_status,
        "inspection_scheduled_at": coord.inspection_scheduled_at.isoformat() if coord.inspection_scheduled_at else None,
        "inspection_reschedule_count": coord.inspection_reschedule_count,
        "inspection_reschedule_reason": coord.inspection_reschedule_reason,
        "towing_required": coord.towing_required,
        "towing_status": coord.towing_status,
        "towing_provider": serialize_provider_scorecard(tow) if tow else None,
        "towing_ev_flatbed": coord.towing_ev_flatbed,
        "pickup_delivery_status": coord.pickup_delivery_status,
        "pickup_scheduled_at": coord.pickup_scheduled_at.isoformat() if coord.pickup_scheduled_at else None,
        "delivery_scheduled_at": coord.delivery_scheduled_at.isoformat() if coord.delivery_scheduled_at else None,
        "pickup_driver_note": coord.pickup_driver_note,
        "parts_status": coord.parts_status,
        "parts_availability": coord.parts_availability or [],
        "repair_status": coord.repair_status,
        "repair_milestones": coord.repair_milestones or [],
        "repair_completion_confirmed": coord.repair_completion_confirmed,
        "repair_confirmed_by": coord.repair_confirmed_by,
        "repair_confirmed_at": coord.repair_confirmed_at.isoformat() if coord.repair_confirmed_at else None,
        "surveyor_followup_count": coord.surveyor_followup_count,
        "last_surveyor_followup_at": coord.last_surveyor_followup_at.isoformat() if coord.last_surveyor_followup_at else None,
        "surveyor_followup_status": coord.surveyor_followup_status,
        "customer_notifications": coord.customer_notifications or [],
        "contractual_compliance": coord.contractual_compliance or {},
        "coordination_explanation": coord.coordination_explanation,
        "updated_at": coord.updated_at.isoformat() if coord.updated_at else _utcnow().isoformat(),
    }


def _collect_claim_parts(db: Session, claim: Claim) -> list[dict[str, Any]]:
    ests = db.query(Estimate).filter(Estimate.claim_id == claim.id).order_by(Estimate.version.desc()).all()
    if ests:
        lines = db.query(EstimateLine).filter(EstimateLine.estimate_id == ests[0].id, EstimateLine.line_type == "part").all()
        if lines:
            return [{"part_code": ln.part_code, "description": ln.description} for ln in lines]
    dmgs = db.query(DamageAssessment).filter(DamageAssessment.claim_id == claim.id).all()
    if dmgs:
        return [{"part_code": d.part_code or "PRT-BODY-01", "description": d.component_name} for d in dmgs]
    if claim.ev_battery_impacted:
        return [
            {"part_code": "PRT-EV-PACK-01", "description": "EV High-Voltage Battery Tray & Coolant Guard"},
            {"part_code": "PRT-FRT-BMP-01", "description": "Front Bumper & Sensor Housing"},
        ]
    return [
        {"part_code": "PRT-FRT-BMP-01", "description": "Front Bumper Assembly"},
        {"part_code": "PRT-HDL-RH-01", "description": "RH Headlamp Assembly"},
    ]


def coordinate_claim_ecosystem(
    db: Session,
    claim: Claim,
    *,
    user: UserContext,
    preferred_garage_id: str | None = None,
    selected_garage_id: str | None = None,
    preferred_surveyor_id: str | None = None,
    towing_needed: bool | None = None,
    pickup_required: bool = False,
    delivery_required: bool = False,
    appointment_at: datetime | None = None,
    override_customer_preference: bool = False,
    override_contract_rule: bool = False,
    override_reason: str = "",
    notify_customer: bool = True,
) -> EcosystemCoordination:
    """Executes full claims ecosystem coordination while enforcing preference & contractual guardrails."""
    coord = get_or_create_ecosystem_coordination(db, claim)
    vehicle = db.query(Vehicle).filter(Vehicle.id == claim.vehicle_id).first() if claim.vehicle_id else None
    ev_required = bool(claim.ev_battery_impacted or (vehicle and vehicle.is_ev))
    cashless_required = claim.claim_type == "cashless"

    # Explicit unauthorized override check
    has_auth = user.role.value in AUTHORIZED_OVERRIDE_ROLES and bool(override_reason.strip())
    if (override_customer_preference or override_contract_rule) and not has_auth:
        raise DomainError(
            ErrorCode.NOT_AUTHORISED,
            "Overriding customer garage choice or contractual rules requires Claims Manager/Admin authorization and documented override_reason.",
            status_code=403,
        )

    providers = db.query(Provider).filter(Provider.tenant_id == claim.tenant_id).all()
    req_skills = _required_skills_for_claim(
        ev_required=ev_required,
        peril_cause=claim.peril_cause,
        vehicle_make=vehicle.make if vehicle else "",
    )

    cust_pref = preferred_garage_id or coord.customer_preferred_garage_id or claim.assigned_garage_id
    if cust_pref:
        coord.customer_preferred_garage_id = cust_pref

    # 1. Garage selection with customer preference & contractual protection
    gar_sel = select_best_garage(
        providers,
        incident_location=claim.incident_location,
        required_skills=req_skills,
        ev_required=ev_required,
        cashless_required=cashless_required,
        customer_preferred_garage_id=cust_pref,
        requested_override_garage_id=selected_garage_id,
        override_authorized=has_auth,
        actor_role=user.role.value,
        override_reason=override_reason,
    )
    if gar_sel["authorization_blocked"]:
        raise DomainError(ErrorCode.NOT_AUTHORISED, gar_sel["blocked_reason"], status_code=403)

    chosen_garage: Provider | None = gar_sel["selected"]
    if chosen_garage:
        claim.assigned_garage_id = chosen_garage.id
        coord.garage_id = chosen_garage.id
        coord.garage_selection_explanation = gar_sel["explanation"]
        coord.garage_score_breakdown = gar_sel["selected_score"] or {}
    coord.customer_preference_honoured = bool(gar_sel["customer_preference_honoured"])
    coord.override_applied = bool(gar_sel["override_applied"])
    if coord.override_applied:
        coord.override_authorized = bool(has_auth or gar_sel["ev_safety_override_applied"])
        coord.override_authorized_by = f"{user.name} ({user.role.value})" if has_auth else "POL-WORDING-EV-2025:EV-SAFE-01"
        coord.override_reason_code = "RC_EV_SAFETY_CONTRACT_RULE" if gar_sel["ev_safety_override_applied"] else "RC_MANAGER_AUTHORIZED_OVERRIDE"
        coord.override_justification = override_reason or gar_sel["explanation"]

    # 2. Surveyor availability, IIISLA license verification & multi-factor selection
    if claim.requires_mandatory_survey or preferred_surveyor_id:
        surv_sel = select_best_surveyor(
            providers,
            incident_location=claim.incident_location,
            required_skills=req_skills,
            ev_required=ev_required,
            preferred_surveyor_id=preferred_surveyor_id or claim.assigned_surveyor_id,
            override_authorized=has_auth,
            actor_role=user.role.value,
            override_reason=override_reason,
        )
        chosen_surv: Provider | None = surv_sel["selected"]
        if chosen_surv:
            lic = verify_surveyor_license(chosen_surv)
            coord.surveyor_id = chosen_surv.id
            coord.surveyor_license_verified = bool(lic["verified"])
            coord.surveyor_license_checked_at = _utcnow()
            coord.surveyor_selection_explanation = surv_sel["explanation"]
            coord.surveyor_score_breakdown = surv_sel["selected_score"] or {}

            existing_sa = (
                db.query(SurveyAssignment)
                .filter(SurveyAssignment.claim_id == claim.id)
                .order_by(SurveyAssignment.assigned_at.desc())
                .first()
            )
            appt = appointment_at or (_utcnow() + timedelta(hours=12))
            if not existing_sa:
                irdai = get_active_rule(db, "IN-IRDAI-MC-2024")["controls"]
                due_at = _utcnow() + timedelta(days=int(irdai["survey_report_due_days"]))
                sa = SurveyAssignment(
                    tenant_id=claim.tenant_id,
                    claim_id=claim.id,
                    surveyor_id=chosen_surv.id,
                    status="scheduled",
                    appointment_at=appt,
                    inspection_location=chosen_garage.name if chosen_garage else claim.incident_location,
                    report_due_at=due_at,
                )
                db.add(sa)
                chosen_surv.active_load += 1
                claim.assigned_surveyor_id = chosen_surv.id
                complete_stage_sla_timer(db, claim_id=claim.id, stage="surveyor_allocation")
                create_stage_sla_timer(db, tenant_id=claim.tenant_id, claim_id=claim.id, stage="survey_report_submission")
            coord.inspection_status = "scheduled"
            coord.inspection_scheduled_at = appt

    # 3. Parts availability check
    if chosen_garage:
        parts_res = IntegrationAdapterRegistry.check_parts_availability(
            garage_name=chosen_garage.name,
            parts_stock_status=chosen_garage.parts_stock_status,
            parts_lead_time_days=chosen_garage.parts_lead_time_days,
            part_items=_collect_claim_parts(db, claim),
        )
        coord.parts_status = parts_res["parts_status"]
        coord.parts_availability = parts_res["items"]

    # 4. Towing + Vehicle pickup & delivery
    need_tow = bool(towing_needed if towing_needed is not None else (claim.towing_needed or claim.vehicle_immobile))
    coord.towing_required = need_tow
    coord.towing_ev_flatbed = ev_required
    if need_tow:
        tow_provs = [p for p in providers if (p.provider_type == "towing" or p.towing_capable) and p.is_available]
        if ev_required:
            tow_provs = [p for p in tow_provs if p.ev_capable] or tow_provs
        if tow_provs:
            coord.towing_provider_id = tow_provs[0].id
        coord.towing_status = "dispatched"

    if pickup_required or (chosen_garage and chosen_garage.pickup_drop_available and not need_tow and coord.pickup_delivery_status == "not_scheduled"):
        coord.pickup_delivery_status = "pickup_scheduled"
        coord.pickup_scheduled_at = _utcnow() + timedelta(hours=4)
    if delivery_required:
        coord.delivery_scheduled_at = _utcnow() + timedelta(days=3)

    # 5. Contractual compliance & combined explanation
    coord.contractual_compliance = {
        "irdai_iiisla_verified": coord.surveyor_license_verified or not claim.requires_mandatory_survey,
        "ev_hv_safety_enforced": (not ev_required) or bool(chosen_garage and chosen_garage.ev_capable),
        "cashless_network_enforced": (not cashless_required) or bool(chosen_garage and chosen_garage.is_network),
        "customer_preference_protected": coord.customer_preference_honoured or coord.override_authorized,
    }
    parts_summary = f"Parts status: {coord.parts_status}." if chosen_garage else ""
    coord.coordination_explanation = " ".join(
        part for part in [coord.surveyor_selection_explanation, coord.garage_selection_explanation, parts_summary] if part
    ).strip()

    if notify_customer:
        msg = (
            f"Ecosystem coordinated for {claim.claim_number}: "
            + (f"Garage: {chosen_garage.name}. " if chosen_garage else "")
            + (f"Inspection scheduled for {coord.inspection_scheduled_at.strftime('%Y-%m-%d %H:%M UTC')}. " if coord.inspection_scheduled_at else "")
            + ("EV flatbed towing dispatched." if need_tow and ev_required else ("Roadside towing dispatched." if need_tow else ""))
        ).strip()
        _append_notification(coord, event="ECOSYSTEM_COORDINATED", channel="whatsapp", message=msg)
        db.add(
            Communication(
                tenant_id=claim.tenant_id,
                claim_id=claim.id,
                channel="whatsapp",
                language=claim.preferred_language,
                template_id="ECOSYSTEM_COORDINATION_UPDATE",
                subject=f"Garage & Inspection Scheduled: {claim.claim_number}",
                body=msg,
                delivery_status="sent_mock",
            )
        )

    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="ECOSYSTEM_COORDINATED",
        object_type="ecosystem_coordination",
        object_id=coord.id,
        details={
            "surveyor_id": coord.surveyor_id,
            "garage_id": coord.garage_id,
            "customer_preference_honoured": coord.customer_preference_honoured,
            "override_applied": coord.override_applied,
            "parts_status": coord.parts_status,
        },
    )
    db.flush()
    return coord


def reschedule_claim_inspection(
    db: Session,
    claim: Claim,
    *,
    user: UserContext,
    new_appointment_at: datetime,
    reason: str,
    location: str = "",
) -> EcosystemCoordination:
    coord = get_or_create_ecosystem_coordination(db, claim)
    sa = (
        db.query(SurveyAssignment)
        .filter(SurveyAssignment.claim_id == claim.id)
        .order_by(SurveyAssignment.assigned_at.desc())
        .first()
    )
    if sa:
        sa.appointment_at = new_appointment_at
        sa.status = "rescheduled"
        sa.reschedule_count = int(sa.reschedule_count or 0) + 1
        sa.reschedule_reason = reason
        if location:
            sa.inspection_location = location

    coord.inspection_status = "rescheduled"
    coord.inspection_scheduled_at = new_appointment_at
    coord.inspection_reschedule_count = int(coord.inspection_reschedule_count or 0) + 1
    coord.inspection_reschedule_reason = reason

    msg = f"Inspection for {claim.claim_number} rescheduled to {new_appointment_at.strftime('%Y-%m-%d %H:%M UTC')} (Reason: {reason})."
    _append_notification(coord, event="INSPECTION_RESCHEDULED", channel="whatsapp", message=msg)
    db.add(
        Communication(
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            channel="whatsapp",
            language=claim.preferred_language,
            template_id="INSPECTION_RESCHEDULED",
            subject=f"Inspection Rescheduled: {claim.claim_number}",
            body=msg,
            delivery_status="sent_mock",
        )
    )
    emit_outbox_event(
        db,
        tenant_id=claim.tenant_id,
        aggregate_id=claim.id,
        event_type="InspectionRescheduled",
        payload={"appointment_at": new_appointment_at.isoformat(), "reason": reason},
    )
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="INSPECTION_RESCHEDULED",
        object_type="ecosystem_coordination",
        object_id=coord.id,
        details={"appointment_at": new_appointment_at.isoformat(), "reason": reason},
    )
    db.flush()
    return coord


def send_surveyor_report_followup(
    db: Session,
    claim: Claim,
    *,
    user: UserContext,
    notes: str = "",
    escalate_to_manager: bool = False,
) -> EcosystemCoordination:
    coord = get_or_create_ecosystem_coordination(db, claim)
    sa = (
        db.query(SurveyAssignment)
        .filter(SurveyAssignment.claim_id == claim.id)
        .order_by(SurveyAssignment.assigned_at.desc())
        .first()
    )
    now = _utcnow()
    if sa:
        sa.followup_count = int(sa.followup_count or 0) + 1
        sa.last_followup_at = now
    coord.surveyor_followup_count = int(coord.surveyor_followup_count or 0) + 1
    coord.last_surveyor_followup_at = now
    coord.surveyor_followup_status = "escalated_sla" if escalate_to_manager else "reminder_sent"

    task = ClaimTask(
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        task_type="surveyor_report_followup",
        title=f"Follow up surveyor report ({coord.surveyor_followup_count}x) for {claim.claim_number}",
        description=notes or "IRDAI 15-day surveyor report SLA follow-up issued by Ecosystem Coordination.",
        assigned_role="claims_manager" if escalate_to_manager else "surveyor",
        created_by_agent="provider_coordination",
        priority="critical" if escalate_to_manager else "high",
        status="open",
        reason_code="RC_SURVEYOR_REPORT_FOLLOWUP",
        due_at=now + timedelta(hours=12),
        metadata_json={"followup_count": coord.surveyor_followup_count, "escalated": escalate_to_manager},
    )
    db.add(task)
    _append_notification(
        coord,
        event="SURVEYOR_FOLLOWUP_SENT",
        channel="portal",
        message=f"Surveyor report follow-up #{coord.surveyor_followup_count} sent; customer notified of active SLA tracking.",
    )
    emit_outbox_event(
        db,
        tenant_id=claim.tenant_id,
        aggregate_id=claim.id,
        event_type="SurveyorReportFollowupSent",
        payload={"followup_count": coord.surveyor_followup_count, "escalated": escalate_to_manager},
    )
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="SURVEYOR_REPORT_FOLLOWUP",
        object_type="ecosystem_coordination",
        object_id=coord.id,
        details={"followup_count": coord.surveyor_followup_count, "escalated": escalate_to_manager, "notes": notes},
    )
    db.flush()
    return coord


def update_claim_parts_availability(
    db: Session,
    claim: Claim,
    *,
    user: UserContext,
    parts_status: str | None = None,
    parts_items: list[dict[str, Any]] | None = None,
    notify_customer: bool = True,
) -> EcosystemCoordination:
    coord = get_or_create_ecosystem_coordination(db, claim)
    gar = db.query(Provider).filter(Provider.id == coord.garage_id).first() if coord.garage_id else None
    if parts_items:
        coord.parts_availability = parts_items
        if not parts_status:
            any_back = any(i.get("availability") == "backordered" for i in parts_items)
            parts_status = "partial_backorder" if any_back else "all_available"
    elif not coord.parts_availability:
        res = IntegrationAdapterRegistry.check_parts_availability(
            garage_name=gar.name if gar else "Assigned Garage",
            parts_stock_status=gar.parts_stock_status if gar else "in_stock",
            parts_lead_time_days=gar.parts_lead_time_days if gar else 2,
            part_items=_collect_claim_parts(db, claim),
        )
        coord.parts_availability = res["items"]
        parts_status = parts_status or res["parts_status"]

    coord.parts_status = parts_status or coord.parts_status
    if notify_customer and coord.parts_status in {"partial_backorder", "backordered"}:
        _append_notification(
            coord,
            event="PARTS_BACKORDER_ADVISORY",
            channel="whatsapp",
            message=f"Parts availability update for {claim.claim_number}: {coord.parts_status}. OEM dispatch is being expedited.",
        )
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="PARTS_AVAILABILITY_UPDATED",
        object_type="ecosystem_coordination",
        object_id=coord.id,
        details={"parts_status": coord.parts_status},
    )
    db.flush()
    return coord


def update_claim_logistics(
    db: Session,
    claim: Claim,
    *,
    user: UserContext,
    towing_status: str | None = None,
    pickup_delivery_status: str | None = None,
    pickup_driver_note: str = "",
    notify_customer: bool = True,
) -> EcosystemCoordination:
    coord = get_or_create_ecosystem_coordination(db, claim)
    now = _utcnow()
    if towing_status:
        coord.towing_required = towing_status != "not_required"
        coord.towing_status = towing_status
    if pickup_delivery_status:
        coord.pickup_delivery_status = pickup_delivery_status
        if pickup_delivery_status == "pickup_scheduled" and not coord.pickup_scheduled_at:
            coord.pickup_scheduled_at = now + timedelta(hours=3)
        elif pickup_delivery_status == "delivery_scheduled" and not coord.delivery_scheduled_at:
            coord.delivery_scheduled_at = now + timedelta(hours=6)
    if pickup_driver_note:
        coord.pickup_driver_note = pickup_driver_note

    if notify_customer:
        msg = (
            f"Vehicle logistics update for {claim.claim_number}: "
            f"towing={coord.towing_status}, pickup/delivery={coord.pickup_delivery_status}."
        )
        _append_notification(coord, event="LOGISTICS_UPDATED", channel="whatsapp", message=msg)
        db.add(
            Communication(
                tenant_id=claim.tenant_id,
                claim_id=claim.id,
                channel="whatsapp",
                language=claim.preferred_language,
                template_id="LOGISTICS_UPDATE",
                subject=f"Vehicle Towing & Pickup/Delivery Update: {claim.claim_number}",
                body=msg,
                delivery_status="sent_mock",
            )
        )

    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="ECOSYSTEM_LOGISTICS_UPDATED",
        object_type="ecosystem_coordination",
        object_id=coord.id,
        details={"towing_status": coord.towing_status, "pickup_delivery_status": coord.pickup_delivery_status},
    )
    db.flush()
    return coord


def update_repair_milestone_and_confirm(
    db: Session,
    claim: Claim,
    *,
    user: UserContext,
    milestone: str,
    notes: str = "",
    confirm_completion: bool = False,
) -> EcosystemCoordination:
    coord = get_or_create_ecosystem_coordination(db, claim)
    now = _utcnow()
    coord.repair_status = milestone
    milestones = list(coord.repair_milestones or [])
    milestones.append(
        {
            "milestone": milestone,
            "notes": notes,
            "actor": f"{user.name} ({user.role.value})",
            "timestamp": now.isoformat(),
        }
    )
    coord.repair_milestones = milestones

    if confirm_completion or milestone in {"repair_completed", "handover_confirmed"}:
        coord.repair_completion_confirmed = True
        coord.repair_confirmed_by = f"{user.name} ({user.role.value})"
        coord.repair_confirmed_at = now
        if coord.pickup_delivery_status not in {"delivery_scheduled", "delivered"}:
            coord.pickup_delivery_status = "delivery_scheduled"
            coord.delivery_scheduled_at = now + timedelta(hours=4)
        msg = f"Repair completion confirmed for {claim.claim_number} ({milestone}). Vehicle handover/delivery scheduled."
        _append_notification(coord, event="REPAIR_COMPLETION_CONFIRMED", channel="whatsapp", message=msg)
        db.add(
            Communication(
                tenant_id=claim.tenant_id,
                claim_id=claim.id,
                channel="whatsapp",
                language=claim.preferred_language,
                template_id="REPAIR_COMPLETION_CONFIRMED",
                subject=f"Repair Completed & Ready for Delivery: {claim.claim_number}",
                body=msg,
                delivery_status="sent_mock",
            )
        )
    else:
        _append_notification(
            coord,
            event="REPAIR_MILESTONE_UPDATED",
            channel="whatsapp",
            message=f"Repair milestone for {claim.claim_number}: {milestone}. {notes}".strip(),
        )

    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action="REPAIR_COMPLETION_CONFIRMED" if coord.repair_completion_confirmed else "REPAIR_MILESTONE_TRACKED",
        object_type="ecosystem_coordination",
        object_id=coord.id,
        details={"milestone": milestone, "confirmed": coord.repair_completion_confirmed, "notes": notes},
    )
    db.flush()
    return coord


def build_ecosystem_dashboard(db: Session, tenant_id: str) -> dict[str, Any]:
    providers = (
        db.query(Provider)
        .filter(Provider.tenant_id == tenant_id)
        .order_by(Provider.provider_type.asc(), Provider.quality_score.desc())
        .all()
    )
    coords = (
        db.query(EcosystemCoordination)
        .filter(EcosystemCoordination.tenant_id == tenant_id)
        .order_by(EcosystemCoordination.updated_at.desc())
        .all()
    )
    claims_by_id = {c.id: c for c in db.query(Claim).filter(Claim.tenant_id == tenant_id).all()}

    provider_rows = [serialize_provider_scorecard(p) for p in providers]
    available_count = sum(1 for r in provider_rows if r["availability"] == "Available")
    within_sla_count = sum(1 for r in provider_rows if r["sla"] == "Within SLA")
    delayed_count = sum(1 for r in provider_rows if r["sla"] == "Delayed")

    active_coordinations = []
    for cd in coords:
        clm = claims_by_id.get(cd.claim_id)
        serialized = serialize_ecosystem_coordination(db, cd)
        serialized["claim_number"] = clm.claim_number if clm else cd.claim_id
        serialized["claim_status"] = clm.status if clm else "UNKNOWN"
        serialized["vehicle_reg"] = clm.vehicle_reg_input if clm else ""
        active_coordinations.append(serialized)

    return {
        "summary": {
            "total_providers": len(provider_rows),
            "available_providers": available_count,
            "within_sla_providers": within_sla_count,
            "delayed_providers": delayed_count,
            "active_coordinations": len(active_coordinations),
            "scheduled_inspections": sum(1 for cd in coords if cd.inspection_status in {"scheduled", "rescheduled"}),
            "rescheduled_inspections": sum(1 for cd in coords if int(cd.inspection_reschedule_count or 0) > 0),
            "open_surveyor_followups": sum(1 for cd in coords if int(cd.surveyor_followup_count or 0) > 0 and cd.surveyor_followup_status != "report_received"),
            "parts_backorders": sum(1 for cd in coords if cd.parts_status in {"partial_backorder", "backordered"}),
            "repairs_completed_confirmed": sum(1 for cd in coords if cd.repair_completion_confirmed),
            "active_towing_or_pickup": sum(
                1
                for cd in coords
                if cd.towing_status in {"dispatched", "en_route"}
                or cd.pickup_delivery_status in {"pickup_scheduled", "picked_up", "delivery_scheduled"}
            ),
        },
        "providers": provider_rows,
        "coordinations": active_coordinations,
    }
