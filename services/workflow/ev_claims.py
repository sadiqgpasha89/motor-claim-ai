"""Electric-vehicle (EV) claims workflow.

An EV claim is not an ordinary vehicle-damage claim. The expensive and dangerous part of an EV is a high-voltage
traction battery whose condition cannot be read from the outside: a pack that looks fine in a photograph can
carry hidden cell damage, an insulation fault or a delayed thermal event. Treating that as bodywork would risk
injury and fire as well as a wrong repair-versus-replace decision.

This module therefore runs a dedicated, safety-first lifecycle (``EVStage``) next to the Own Damage (OD) claim:

* every EV claim opens an HV safety hold; ``operation_status`` can only be released by a physical post-repair
  recertification by an EV-qualified human, never by software and never from photographs;
* a deterministic signal engine detects battery-pack impact, thermal, HV and charging risk, and the resulting
  risk class can only go up (``battery_critical`` > ``hv_suspected`` > ``screening_only``);
* the specialist surveyor and the OEM diagnostic provider must hold EV-HV qualifications;
* battery repair-vs-replace is advisory software output plus a human decision with an OEM engineer reference;
* EV parts are benchmarked against synthetic EV cost bands;
* a safety escalation (for example a thermal signal reported by the policyholder) blocks every stage, and
  revokes nothing silently: it is acknowledged and resolved by humans with evidence;
* damaged packs follow salvage and disposal chain-of-custody controls;
* OD settlement, approval and payment are refused until a human technical sign-off clears the EV hold.

All data is DEMO / SYNTHETIC. Every threshold in the rule file needs OEM engineering and safety sign-off before
production use (``IN-EV-CLAIMS-2026``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import Enum
from typing import Any, Optional

from sqlalchemy.orm import Session

from packages.contracts.errors import DomainError, ErrorCode
from packages.security.auth import Role, UserContext
from packages.security.sanitizer import sanitize_untrusted_text
from services.claims.audit import emit_outbox_event, record_audit_event
from services.claims.models import Claim, ClaimTask, Communication, EVClaimCase, Policy, Provider, Settlement, Vehicle
from services.rules_engine.loader import get_active_rule

EV_RULE_ID = "IN-EV-CLAIMS-2026"
EV_WORDING_DOC_ID = "POL-WORDING-EV-2025"

RISK_CLASS_ORDER: list[str] = ["screening_only", "hv_suspected", "battery_critical"]
OPERATION_HOLD = "hold_do_not_operate_pending_inspection"
OPERATION_RELEASED = "released_after_recertification"

ROLES_INTAKE = {Role.FNOL_EXECUTIVE, Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.ADMIN}
ROLES_HANDLING = {Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.ADMIN}
ROLES_MANAGER = {Role.CLAIMS_MANAGER, Role.ADMIN}
ROLES_SURVEY = {Role.SURVEYOR, Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.ADMIN}
ROLES_DIAGNOSTICS = {Role.GARAGE, Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.ADMIN}
ROLES_RECOVERY = {Role.GARAGE, Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.ADMIN}
ROLES_RECERT = {Role.GARAGE, Role.SURVEYOR, Role.CLAIMS_MANAGER, Role.ADMIN}
ROLES_SALVAGE = {Role.GARAGE, Role.CLAIMS_HANDLER, Role.CLAIMS_MANAGER, Role.ADMIN}
ROLES_ESCALATE = {
    Role.POLICYHOLDER,
    Role.FNOL_EXECUTIVE,
    Role.CLAIMS_HANDLER,
    Role.CLAIMS_MANAGER,
    Role.SURVEYOR,
    Role.GARAGE,
    Role.ADMIN,
}
ROLES_VIEW_FULL = {
    Role.FNOL_EXECUTIVE,
    Role.CLAIMS_HANDLER,
    Role.SURVEYOR,
    Role.GARAGE,
    Role.CLAIMS_MANAGER,
    Role.SIU_INVESTIGATOR,
    Role.LEGAL_TP,
    Role.FINANCE_APPROVER,
    Role.AUDITOR,
    Role.ADMIN,
}


class EVStage(str, Enum):
    INTAKE_TRIAGE = "INTAKE_TRIAGE"
    SAFE_RECOVERY_ISOLATION = "SAFE_RECOVERY_ISOLATION"
    SPECIALIST_SURVEY = "SPECIALIST_SURVEY"
    OEM_DIAGNOSTICS = "OEM_DIAGNOSTICS"
    BATTERY_DISPOSITION = "BATTERY_DISPOSITION"
    COST_BENCHMARKING = "COST_BENCHMARKING"
    TECHNICAL_SIGN_OFF = "TECHNICAL_SIGN_OFF"
    SETTLEMENT_CLEARED = "SETTLEMENT_CLEARED"
    REPAIR_RECERTIFICATION = "REPAIR_RECERTIFICATION"
    SALVAGE_DISPOSAL = "SALVAGE_DISPOSAL"
    CLOSED = "CLOSED"


STAGE_ORDER: list[str] = [s.value for s in EVStage]

# Stages advanced by the generic human /advance action once the exit gate is clear. TECHNICAL_SIGN_OFF is
# advanced only by its own controlled action, and CLOSED only by the closure review.
ADVANCE_ACTION_STAGES = {s for s in STAGE_ORDER if s not in {EVStage.TECHNICAL_SIGN_OFF.value, EVStage.CLOSED.value}}

SCREENING_ONLY_SKIPPED = {
    EVStage.SAFE_RECOVERY_ISOLATION.value,
    EVStage.SPECIALIST_SURVEY.value,
    EVStage.BATTERY_DISPOSITION.value,
}
# Stages that, when the risk class goes up, must have their artefact on file before the case may stay beyond them.
STAGE_ARTEFACT_FIELD = {
    EVStage.SAFE_RECOVERY_ISOLATION.value: "recovery",
    EVStage.SPECIALIST_SURVEY.value: "survey",
    EVStage.OEM_DIAGNOSTICS.value: "diagnostics",
    EVStage.BATTERY_DISPOSITION.value: "disposition",
}
# Stages up to and including TECHNICAL_SIGN_OFF own the claim queue; afterwards the OD engine's queues take over.
QUEUE_OWNING_STAGES = set(STAGE_ORDER[: STAGE_ORDER.index(EVStage.TECHNICAL_SIGN_OFF.value) + 1])

_LEVEL_RANK = {"urgent": 1, "emergency": 2}
_SEVERITY_RANK = {"moderate": 1, "high": 2, "critical": 3}


# ----------------------------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> Optional[str]:
    return dt.isoformat() if dt else None


def _aware(dt: datetime | None) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _money(value: Any, *, field: str = "amount_inr") -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise DomainError(ErrorCode.VALIDATION_ERROR, f"'{field}' must be a valid INR amount", status_code=400) from exc


def _decimal(value: Any, *, field: str, positive: bool = True) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise DomainError(ErrorCode.VALIDATION_ERROR, f"'{field}' must be a number", status_code=400) from exc
    if positive and d <= 0:
        raise DomainError(ErrorCode.VALIDATION_ERROR, f"'{field}' must be greater than zero", status_code=400)
    return d


def _clean(text: str | None, *, max_len: int = 2000) -> str:
    cleaned, _, _ = sanitize_untrusted_text((text or "").strip())
    return cleaned[:max_len]


def _actor(user: UserContext) -> dict[str, str]:
    return {"user_id": user.user_id, "name": user.name, "role": user.role.value}


def _require_role(user: UserContext, allowed: set[Role], action: str) -> None:
    if user.role not in allowed:
        raise DomainError(
            ErrorCode.NOT_AUTHORISED,
            f"Role '{user.role.value}' is not permitted to {action} on an EV claim",
            status_code=403,
        )


def ev_rule(db: Session | None) -> dict[str, Any]:
    return get_active_rule(db, EV_RULE_ID)


def _risk_rank(risk_class: str) -> int:
    return RISK_CLASS_ORDER.index(risk_class) if risk_class in RISK_CLASS_ORDER else 1


# ----------------------------------------------------------------------------------------------
# Applicability and the guard placed on OD-only paths
# ----------------------------------------------------------------------------------------------
def claim_requires_ev_workflow(claim: Claim, vehicle: Vehicle | None = None) -> bool:
    """True when the claim concerns an electric vehicle's own damage and must use the EV lifecycle.

    Third-party claims (the insured EV caused damage to someone else) use the TP workflow, and theft involves no
    physical vehicle to inspect, so both stay out of the EV lifecycle.
    """
    if claim.claim_type == "third_party" or (claim.peril_cause or "") in {"theft", "tp_bodily_injury", "tp_fatality", "tp_property_damage"}:
        return False
    return bool(claim.ev_battery_impacted) or (claim.peril_cause or "") == "ev_high_voltage" or bool(vehicle is not None and vehicle.is_ev)


def get_ev_case(db: Session, claim: Claim) -> EVClaimCase | None:
    return db.query(EVClaimCase).filter(EVClaimCase.claim_id == claim.id).first()


def _case_for(db: Session, claim: Claim) -> EVClaimCase:
    case = get_ev_case(db, claim)
    if not case:
        raise DomainError(
            ErrorCode.NOT_FOUND,
            f"No EV case is open for claim {claim.claim_number}; open one via POST /claims/{claim.id}/ev/open",
            status_code=404,
        )
    return case


def open_escalations(case: EVClaimCase) -> list[dict[str, Any]]:
    return [e for e in (case.safety_escalations or []) if e.get("status") != "resolved"]


def ev_od_hold_blockers(db: Session, claim: Claim, *, require_closed: bool = False) -> list[dict[str, str]]:
    """Reasons the OD settlement / approval / payment (or closure) path must stay shut for an EV claim."""
    vehicle = db.query(Vehicle).filter(Vehicle.id == claim.vehicle_id).first() if claim.vehicle_id else None
    if not claim_requires_ev_workflow(claim, vehicle):
        return []
    case = get_ev_case(db, claim)
    if not case:
        return [{"code": "EV_CASE_REQUIRED", "message": "Open the EV case: an EV claim needs the EV safety workflow before any settlement."}]
    blockers: list[dict[str, str]] = []
    if (case.settlement_clearance or {}).get("status") != "granted":
        blockers.append(
            {
                "code": "EV_TECHNICAL_SIGN_OFF_REQUIRED",
                "message": f"EV technical sign-off has not cleared settlement (case stage {case.stage}). Battery condition cannot be inferred from photographs.",
            }
        )
    if open_escalations(case):
        blockers.append({"code": "EV_SAFETY_ESCALATION_OPEN", "message": "An EV safety escalation is open; resolve it before settlement or payment."})
    if require_closed and case.stage != EVStage.CLOSED.value:
        blockers.append({"code": "EV_CASE_NOT_CLOSED", "message": f"EV case {case.case_number} must be closed (recertification and salvage controls) before the claim closes."})
    return blockers


def assert_ev_clearance_for_od_path(db: Session, claim: Claim, *, operation: str, require_closed: bool = False) -> None:
    """Guard on OD settlement, approval, payment and closure for EV claims (IN-EV-CLAIMS-2026)."""
    blockers = ev_od_hold_blockers(db, claim, require_closed=require_closed)
    if blockers:
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            (
                f"'{operation}' is held for this electric-vehicle claim. EV claims run the dedicated EV workflow "
                f"(/api/v1/claims/{claim.id}/ev); battery safety and condition are never inferred from photographs "
                f"(IN-EV-CLAIMS-2026). " + "; ".join(b["message"] for b in blockers)
            ),
            status_code=409,
            details={"ev_workflow_url": f"/api/v1/claims/{claim.id}/ev", "rule_id": EV_RULE_ID, "blockers": blockers},
        )


def _audit(db: Session, case: EVClaimCase, user: UserContext, action: str, details: dict[str, Any] | None = None) -> None:
    record_audit_event(
        db,
        tenant_id=case.tenant_id,
        claim_id=case.claim_id,
        actor_id=user.user_id,
        actor_role=user.role.value,
        action=action,
        object_type="ev_claim_case",
        object_id=case.id,
        after_state={"stage": case.stage, "risk_class": case.risk_class, "operation_status": case.operation_status},
        details=details or {},
    )


# ----------------------------------------------------------------------------------------------
# Provider qualification (specialist surveyor, OEM diagnostics, recovery)
# ----------------------------------------------------------------------------------------------
def provider_qualification(
    provider: Provider | None,
    requirements: dict[str, Any],
    *,
    need_oem: bool = False,
    need_flatbed: bool = False,
) -> dict[str, Any]:
    """Deterministic check of an EV-HV qualification. Returns the reasons so a rejection is explainable."""
    reasons: list[str] = []
    if provider is None:
        return {"qualified": False, "provider_id": None, "reasons": ["Provider not found"]}
    skills = list(provider.skills or [])
    if requirements.get("ev_capable_flag_required", True) and not provider.ev_capable:
        reasons.append("Provider is not flagged EV-capable")
    req_skill = requirements.get("required_skill")
    if req_skill and req_skill not in skills:
        reasons.append(f"Missing required skill '{req_skill}' (EV high-voltage certification)")
    if requirements.get("licence_status_required") and provider.licence_status != requirements["licence_status_required"]:
        reasons.append(f"Licence status is '{provider.licence_status}', '{requirements['licence_status_required']}' required")
    expiry = _aware(provider.licence_expiry_at)
    if requirements.get("licence_must_be_unexpired") and expiry is not None and expiry < _utcnow():
        reasons.append("Licence has expired")
    if need_oem:
        prefix = str(requirements.get("oem_skill_prefix", "oem_"))
        if not any(str(s).startswith(prefix) for s in skills):
            reasons.append("Provider has no OEM authorisation skill (oem_*)")
    if need_flatbed:
        flat = str(requirements.get("flatbed_skill", "flatbed_recovery"))
        if flat not in skills and not (provider.provider_type == "garage" and provider.ev_capable):
            reasons.append(f"Provider lacks '{flat}' recovery capability")
    return {
        "qualified": not reasons,
        "provider_id": provider.id,
        "provider_name": provider.name,
        "provider_type": provider.provider_type,
        "reasons": reasons,
    }


def _resolve_provider(
    db: Session,
    user: UserContext,
    case: EVClaimCase,
    provider_id: str | None,
    *,
    own_roles: set[Role],
) -> Provider:
    """The acting provider: a partner user acts only for their own organisation; staff name the provider."""
    if user.role in own_roles:
        if not user.partner_id:
            raise DomainError(ErrorCode.NOT_AUTHORISED, "Partner user has no provider linkage", status_code=403)
        if provider_id and provider_id != user.partner_id:
            raise DomainError(ErrorCode.NOT_AUTHORISED, "A partner user can record work only for their own organisation", status_code=403)
        provider_id = user.partner_id
    if not provider_id:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "provider_id is required", status_code=400)
    provider = db.query(Provider).filter(Provider.id == provider_id, Provider.tenant_id == case.tenant_id).first()
    if not provider:
        raise DomainError(ErrorCode.NOT_FOUND, f"Provider '{provider_id}' not found", status_code=404)
    return provider


def _require_qualified(qual: dict[str, Any], *, what: str) -> None:
    if not qual["qualified"]:
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            f"{what} requires an EV-HV qualified provider: " + "; ".join(qual["reasons"]),
            status_code=403,
            details={"qualification": qual},
        )


# ----------------------------------------------------------------------------------------------
# EV-specific intelligence (deterministic, explainable, NON-BINDING)
# ----------------------------------------------------------------------------------------------
def classify_signals(rule: dict[str, Any], signals: list[str], claim: Claim) -> dict[str, Any]:
    """Battery-pack impact detection and thermal risk signals.

    There is deliberately no "safe" outcome: the lowest band is ``not_excluded``.
    """
    catalogue = rule["signals"]
    unknown = [s for s in signals if s not in catalogue]
    if unknown:
        raise DomainError(
            ErrorCode.VALIDATION_ERROR,
            f"Unknown EV signal(s): {', '.join(unknown)}. Valid signals: {', '.join(sorted(catalogue))}",
            status_code=400,
        )
    matched = sorted(set(signals))
    score = min(100, sum(int(catalogue[s]["weight"]) for s in matched))
    critical = [s for s in matched if catalogue[s]["severity"] == "critical"]
    high = [s for s in matched if catalogue[s]["severity"] == "high"]
    flagged = bool(claim.ev_battery_impacted) or (claim.peril_cause or "") == "ev_high_voltage"
    if flagged:
        score = max(score, int(rule["impact_bands"]["probable"]["min_score"]))

    if critical or len(high) >= 2 or flagged:
        risk_class = "battery_critical"
    elif matched or (claim.peril_cause or "") in rule["perils_that_imply_hv_suspected"]:
        risk_class = "hv_suspected"
    else:
        risk_class = "screening_only"

    bands = sorted(rule["impact_bands"].items(), key=lambda kv: kv[1]["min_score"])
    band_key = "not_excluded"
    for key, spec in bands:
        if score >= spec["min_score"]:
            band_key = key

    by_category: dict[str, list[str]] = {}
    for s in matched:
        by_category.setdefault(catalogue[s]["category"], []).append(s)
    thermal = by_category.get("thermal", [])
    if any(catalogue[s]["severity"] == "critical" for s in thermal):
        thermal_level = "emergency"
    elif thermal or "coolant_leak_near_pack" in matched:
        thermal_level = "elevated"
    elif risk_class == "battery_critical":
        thermal_level = "watch"
    else:
        thermal_level = "not_excluded"

    # Escalation level is the highest severity category: thermal-critical is an emergency, other criticals urgent.
    escalation_level: Optional[str] = None
    if thermal_level == "emergency":
        escalation_level = "emergency"
    elif critical or any(by_category.get(c) for c in ("hv", "charging", "water", "thermal")):
        escalation_level = "urgent"

    return {
        "signals": matched,
        "signals_by_category": by_category,
        "impact_score": score,
        "impact_band": band_key,
        "impact_label": rule["impact_bands"][band_key]["label"],
        "risk_class": risk_class,
        "thermal_level": thermal_level,
        "escalation_level": escalation_level,
        "safe_to_operate": "not_determinable_from_photographs",
        "note": rule["impact_bands"]["not_excluded"]["note"],
    }


def _derived_signals(claim: Claim) -> list[str]:
    """Signals implied by the FNOL flags. Software proposes; a human confirms in the triage action."""
    derived: list[str] = []
    peril = claim.peril_cause or ""
    if claim.airbags_deployed:
        derived.append("airbags_deployed")
    if claim.vehicle_immobile:
        derived.append("loss_of_drive_power")
    if peril in {"road_accident", "collision"}:
        derived.append("collision_impact_any")
    if peril == "flood":
        derived.append("flood_or_immersion")
    if peril == "fire":
        derived.append("smoke_or_fire")
    return derived


def thermal_watch_for(rule: dict[str, Any], risk_class: str, started_at: datetime | None = None) -> dict[str, Any]:
    required = bool(rule["risk_classes"][risk_class]["thermal_watch_required"])
    th = rule["thermal"]
    if not required:
        return {"required": False, "cleared": False}
    start = started_at or _utcnow()
    return {
        "required": True,
        "cleared": False,
        "started_at": _iso(start),
        "review_due_at": _iso(start + timedelta(hours=int(th["watch_review_hours"]))),
        "quarantine_monitoring_days": th["quarantine_monitoring_days"],
        "quarantine_min_clearance_m": th["quarantine_min_clearance_m"],
    }


def evaluate_diagnostics(rule: dict[str, Any], risk_class: str, tests: list[dict[str, Any]]) -> dict[str, Any]:
    spec = rule["oem_diagnostics"]
    required = list(spec["screening_only_required_tests"] if risk_class == "screening_only" else spec["required_tests"])
    thresholds = spec["thresholds"]
    by_name: dict[str, dict[str, Any]] = {}
    for t in tests:
        name = str(t.get("test", ""))
        if name not in spec["required_tests"]:
            raise DomainError(ErrorCode.VALIDATION_ERROR, f"Unknown diagnostic test '{name}'. Valid tests: {', '.join(spec['required_tests'])}", status_code=400)
        result = str(t.get("result", ""))
        if result not in spec["allowed_results"]:
            raise DomainError(ErrorCode.VALIDATION_ERROR, f"Test '{name}' result must be one of {spec['allowed_results']}", status_code=400)
        value = t.get("value")
        if value is not None:
            try:
                numeric = Decimal(str(value))
            except (InvalidOperation, ValueError) as exc:
                raise DomainError(ErrorCode.VALIDATION_ERROR, f"Test '{name}' value must be numeric", status_code=400) from exc
            breach = (
                (name == "insulation_resistance" and numeric < Decimal(str(thresholds["insulation_resistance_min_ohm_per_volt"])))
                or (name == "bms_cell_voltage_delta" and numeric > Decimal(str(thresholds["bms_cell_voltage_delta_max_mv"])))
                or (name == "state_of_health" and numeric < Decimal(str(thresholds["state_of_health_floor_pct"])))
            )
            if breach and result == "pass":
                raise DomainError(
                    ErrorCode.VALIDATION_ERROR,
                    f"Test '{name}' is reported as pass but the measured value {numeric} breaches the OEM threshold; record it as fail or inconclusive.",
                    status_code=400,
                )
        by_name[name] = {
            "test": name,
            "result": result,
            "value": str(value) if value is not None else None,
            "unit": _clean(str(t.get("unit") or ""), max_len=32),
            "note": _clean(t.get("note"), max_len=400),
        }
    missing = [t for t in required if t not in by_name]
    results = [by_name[t]["result"] for t in required if t in by_name]
    critical_fail = any(by_name[t]["result"] == "fail" for t in spec["critical_fail_tests"] if t in by_name)
    if "fail" in results:
        outcome = "fail"
    elif "inconclusive" in results or missing:
        outcome = "inconclusive"
    else:
        outcome = "pass"
    return {
        "tests": list(by_name.values()),
        "required_tests": required,
        "missing_tests": missing,
        "complete": not missing,
        "outcome": outcome,
        "critical_fail": critical_fail,
    }


def compute_disposition_advisory(db: Session, case: EVClaimCase, claim: Claim, rule: dict[str, Any] | None = None) -> dict[str, Any]:
    """Battery repair-versus-replacement analysis. Advisory only; a human decides with an OEM engineer reference."""
    rule = rule or ev_rule(db)
    spec = rule["disposition"]
    diag = case.diagnostics or {}
    survey = case.survey or {}
    drivers: list[str] = []
    if not diag.get("complete"):
        return {
            "recommended": "insufficient_data",
            "drivers": ["OEM diagnostics are not complete; a repair-versus-replace view cannot be formed from photographs."],
            "binding": False,
            "note": spec["advisory_note"],
        }
    policy = db.query(Policy).filter(Policy.id == claim.policy_id).first() if claim.policy_id else None
    idv = Decimal(str(policy.idv_inr)) if policy else Decimal("0.00")
    pack_max = Decimal(rule["benchmarks"]["parts"]["PRT-EV-PACK-FULL"]["max"])
    ratio = (pack_max / idv) if idv > 0 else None
    tests = {t["test"]: t for t in diag.get("tests", [])}
    failed = [name for name, t in tests.items() if t["result"] == "fail"]
    inconclusive = [name for name, t in tests.items() if t["result"] == "inconclusive"]
    module_level = [n for n in failed if n in {"bms_cell_voltage_delta", "state_of_health"}]
    pack_findings = bool(survey.get("pack_findings"))

    if diag.get("critical_fail"):
        drivers.append("A critical OEM test failed (" + ", ".join(n for n in failed if n in rule["oem_diagnostics"]["critical_fail_tests"]) + "): in-place repair is not acceptable.")
        recommended = "replace_pack"
        if ratio is not None and ratio >= Decimal(spec["pack_replacement_total_loss_review_ratio_of_idv"]):
            drivers.append(f"Pack replacement cost is about {ratio:.0%} of IDV (threshold {Decimal(spec['pack_replacement_total_loss_review_ratio_of_idv']):.0%}): total-loss review.")
            recommended = "total_loss_review"
    elif module_level:
        recommended = "replace_modules"
        drivers.append("Cell imbalance / state-of-health outside OEM limits: module-level replacement indicated.")
    elif inconclusive:
        recommended = "repeat_oem_tests"
        drivers.append("Inconclusive tests (" + ", ".join(inconclusive) + ") must be repeated before any decision.")
    elif pack_findings:
        recommended = "repair_in_place"
        drivers.append("OEM tests pass but the surveyor recorded enclosure/tray damage: repair the enclosure, re-test, recertify.")
    else:
        recommended = "no_battery_work"
        drivers.append("OEM tests pass and no pack findings were recorded by the physical survey.")
    return {
        "recommended": recommended,
        "drivers": drivers,
        "pack_replacement_to_idv_ratio": f"{ratio:.4f}" if ratio is not None else None,
        "binding": False,
        "note": spec["advisory_note"],
    }


def compute_benchmark(rule: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any]:
    spec = rule["benchmarks"]
    tol = Decimal(spec["variance_tolerance_pct"]) / Decimal("100")
    low_ratio = Decimal(spec["suspiciously_low_ratio"])
    out: list[dict[str, Any]] = []
    flagged = 0
    total = Decimal("0.00")
    for raw in lines:
        kind = str(raw.get("kind") or "part")
        if kind == "labour":
            hours = _decimal(raw.get("hours"), field="hours")
            rate = _money(raw.get("rate_inr"), field="rate_inr")
            band = spec["labour_hv_certified_per_hour_inr"]
            lo, hi = Decimal(band["min"]), Decimal(band["max"])
            line_total = (rate * hours).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            unit = rate
            code = "LABOUR-HV"
            name = _clean(raw.get("description"), max_len=160) or "HV-certified labour (per hour)"
            qty = hours
        else:
            code = str(raw.get("part_code", ""))
            qty = _decimal(raw.get("quantity", 1), field="quantity")
            unit = _money(raw.get("unit_quoted_inr"), field="unit_quoted_inr")
            line_total = (unit * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            bench = spec["parts"].get(code)
            name = _clean(raw.get("description"), max_len=160) or (bench["name"] if bench else code)
            lo, hi = (Decimal(bench["min"]), Decimal(bench["max"])) if bench else (Decimal("0"), Decimal("0"))
            if not bench:
                out.append({"part_code": code, "description": name, "quantity": str(qty), "unit_quoted_inr": str(unit), "line_total_inr": str(line_total), "status": "no_benchmark", "benchmark_min_inr": None, "benchmark_max_inr": None})
                flagged += 1
                total += line_total
                continue
        if unit > hi * (Decimal("1") + tol):
            status = "above_benchmark"
        elif unit < lo * low_ratio:
            status = "suspiciously_low"
        else:
            status = "within_benchmark"
        if status != "within_benchmark":
            flagged += 1
        total += line_total
        out.append(
            {
                "part_code": code,
                "description": name,
                "quantity": str(qty),
                "unit_quoted_inr": str(unit),
                "line_total_inr": str(line_total),
                "status": status,
                "benchmark_min_inr": str(lo),
                "benchmark_max_inr": str(hi),
            }
        )
    needs_manager = flagged > 0 or total > Decimal(spec["manager_review_above_inr"])
    return {
        "lines": out,
        "flagged_lines": flagged,
        "total_quoted_inr": str(total),
        "requires_manager_review": needs_manager,
        "currency": spec["currency"],
        "vehicle_class": spec["vehicle_class"],
        "binding": False,
    }


def requires_salvage(case: EVClaimCase, rule: dict[str, Any]) -> bool:
    return (case.disposition or {}).get("decision") in rule["disposition"]["decisions_requiring_removal"]


def _salvage_status(case: EVClaimCase, rule: dict[str, Any]) -> dict[str, Any]:
    spec = rule["salvage"]
    events = (case.salvage or {}).get("events", [])
    done = {e["event"] for e in events}
    missing = [e for e in spec["required_events"] if e not in done]
    return {"required": requires_salvage(case, rule), "events": events, "missing_events": missing, "complete": not missing, "battery_serial": (case.salvage or {}).get("battery_serial")}


def build_advisory(db: Session, case: EVClaimCase, claim: Claim, rule: dict[str, Any] | None = None) -> dict[str, Any]:
    rule = rule or ev_rule(db)
    sigs = list((case.triage or {}).get("signals", []))
    cls = classify_signals(rule, sigs, claim)
    flagged_components: set[str] = set()
    cats = cls["signals_by_category"]
    if cats.get("impact"):
        flagged_components.update({"traction_battery_pack_enclosure_and_seals", "battery_modules_and_cell_taps", "bms_and_cell_monitoring_harness"})
    if cats.get("hv"):
        flagged_components.update({"hv_junction_box_and_contactors", "service_disconnect_and_hv_interlock_loop", "orange_hv_cable_harness", "pyro_fuse_and_crash_disconnect"})
    if cats.get("thermal"):
        flagged_components.update({"battery_thermal_management_coolant_circuit", "traction_battery_pack_enclosure_and_seals"})
    if cats.get("water"):
        flagged_components.update({"traction_battery_pack_enclosure_and_seals", "hv_junction_box_and_contactors", "onboard_charger", "dc_dc_converter"})
    charging_flagged = bool(cats.get("charging")) or bool(cats.get("water"))
    survey_qual = (case.survey or {}).get("qualification")
    assigned = db.query(Provider).filter(Provider.id == claim.assigned_surveyor_id).first() if claim.assigned_surveyor_id else None
    assigned_qual = provider_qualification(assigned, rule["surveyor_requirements"]) if assigned else None
    return {
        "battery_pack_impact": {
            "score": cls["impact_score"],
            "band": cls["impact_band"],
            "label": cls["impact_label"],
            "signals": cls["signals"],
            "never_cleared_from_photographs": True,
        },
        "thermal_risk": {
            "level": cls["thermal_level"],
            "signals": cls["signals_by_category"].get("thermal", []),
            "watch": case.thermal_watch or {},
        },
        "hv_system": {
            "inspection_checklist": rule["hv_components_checklist"],
            "priority_components": sorted(flagged_components),
            "hv_signals": cats.get("hv", []),
        },
        "charging_system": {
            "inspection_checklist": rule["charging_components_checklist"],
            "flagged": charging_flagged,
            "charging_signals": cats.get("charging", []),
            "instruction": "Do not charge the vehicle until the charging system and pack are cleared by an EV-qualified inspection.",
        },
        "specialist_surveyor": {
            "requirements": rule["surveyor_requirements"],
            "assigned_surveyor_id": claim.assigned_surveyor_id,
            "assigned_surveyor_qualified": assigned_qual["qualified"] if assigned_qual else None,
            "assigned_surveyor_reasons": assigned_qual["reasons"] if assigned_qual else [],
            "recorded_survey_qualification": survey_qual,
        },
        "oem_diagnostics": {
            "required_tests": (case.diagnostics or {}).get("required_tests") or (rule["oem_diagnostics"]["screening_only_required_tests"] if case.risk_class == "screening_only" else rule["oem_diagnostics"]["required_tests"]),
            "missing_tests": (case.diagnostics or {}).get("missing_tests"),
            "outcome": (case.diagnostics or {}).get("outcome"),
            "thresholds": rule["oem_diagnostics"]["thresholds"],
        },
        "battery_disposition": compute_disposition_advisory(db, case, claim, rule),
        "parts_cost_benchmark": {
            "status": (case.benchmark or {}).get("status", "not_started"),
            "flagged_lines": (case.benchmark or {}).get("flagged_lines"),
            "vehicle_class": rule["benchmarks"]["vehicle_class"],
        },
        "salvage_and_disposal": _salvage_status(case, rule),
        "safety_escalation": {
            "open": len(open_escalations(case)),
            "suggested_level": cls["escalation_level"],
        },
        "operation": {
            "operation_status": case.operation_status,
            "safe_to_operate": "not_determinable_from_photographs",
            "photo_only_clearance_allowed": rule["controls"]["photo_only_clearance_allowed"],
        },
        "binding": False,
    }


# ----------------------------------------------------------------------------------------------
# Stage path, gates and queues
# ----------------------------------------------------------------------------------------------
def stage_path(case: EVClaimCase, rule: dict[str, Any]) -> list[str]:
    path: list[str] = []
    for stage in STAGE_ORDER:
        if case.risk_class == "screening_only" and stage in SCREENING_ONLY_SKIPPED:
            continue
        if stage == EVStage.SALVAGE_DISPOSAL.value and not requires_salvage(case, rule):
            continue
        path.append(stage)
    return path


def next_stage_after(case: EVClaimCase, rule: dict[str, Any]) -> Optional[str]:
    cur = STAGE_ORDER.index(case.stage)
    for stage in stage_path(case, rule):
        if STAGE_ORDER.index(stage) > cur:
            return stage
    return None


def _settlement_approved(db: Session, claim_id: str) -> bool:
    return db.query(Settlement).filter(Settlement.claim_id == claim_id, Settlement.approval_status == "approved").first() is not None


def _signoff_prerequisites(db: Session, case: EVClaimCase, rule: dict[str, Any]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []

    def block(code: str, message: str) -> None:
        blockers.append({"code": code, "message": message})

    if not (case.diagnostics or {}).get("complete"):
        block("OEM_DIAGNOSTICS_INCOMPLETE", "OEM diagnostics must be complete before sign-off.")
    if case.risk_class != "screening_only" and not (case.disposition or {}).get("decision"):
        block("BATTERY_DISPOSITION_REQUIRED", "A battery disposition decision with an OEM engineer reference is required.")
    if (case.benchmark or {}).get("status") != "reviewed":
        block("BENCHMARK_REVIEW_REQUIRED", "The EV parts cost benchmark must be reviewed by a human.")
    return blockers


def evaluate_gates(db: Session, case: EVClaimCase, rule: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Exit conditions for the current stage. An empty list means a human may advance."""
    rule = rule or ev_rule(db)
    blockers: list[dict[str, str]] = []
    stage = case.stage

    def block(code: str, message: str) -> None:
        blockers.append({"code": code, "message": message})

    if stage == EVStage.CLOSED.value:
        return blockers
    if stage == EVStage.INTAKE_TRIAGE.value:
        # An escalation is what sends the case to recovery and isolation, so leaving triage needs it acknowledged,
        # not resolved. Every later stage needs it resolved with evidence.
        if any(e.get("status") == "open" for e in case.safety_escalations or []):
            block("SAFETY_ESCALATION_UNACKNOWLEDGED", "A safety escalation is open: an EV safety officer (claims manager) must acknowledge it and record the actions taken.")
    elif open_escalations(case):
        block("SAFETY_ESCALATION_OPEN", "An EV safety escalation is open; a human must acknowledge and resolve it with evidence before the case can move.")

    if stage == EVStage.INTAKE_TRIAGE.value:
        if not (case.triage or {}).get("recorded"):
            block("TRIAGE_CONFIRMATION_REQUIRED", "A human must confirm the EV safety triage (signals, HV hold and customer safety instructions).")
    elif stage == EVStage.SAFE_RECOVERY_ISOLATION.value:
        rec = case.recovery or {}
        if not rec.get("hv_isolation_verified"):
            block("HV_ISOLATION_REQUIRED", "Record flatbed recovery or on-site isolation by an EV-qualified provider with HV isolation verified.")
        if not rec.get("quarantine_location"):
            block("QUARANTINE_REQUIRED", "Record the quarantine location with the required clearance from other vehicles and buildings.")
    elif stage == EVStage.SPECIALIST_SURVEY.value:
        sv = case.survey or {}
        if not sv.get("recorded"):
            block("SPECIALIST_SURVEY_REQUIRED", "A physical survey by an EV-HV certified surveyor is mandatory.")
        elif not sv.get("hv_isolation_verified"):
            block("SURVEY_ISOLATION_UNVERIFIED", "The surveyor must confirm HV isolation before any pack inspection.")
    elif stage == EVStage.OEM_DIAGNOSTICS.value:
        d = case.diagnostics or {}
        if not d.get("complete"):
            block("OEM_DIAGNOSTICS_INCOMPLETE", "Missing OEM tests: " + (", ".join(d.get("missing_tests") or []) or "all required tests") + ".")
    elif stage == EVStage.BATTERY_DISPOSITION.value:
        dp = case.disposition or {}
        if not dp.get("decision"):
            block("BATTERY_DISPOSITION_REQUIRED", "Record the battery repair/replace decision with the OEM engineer reference.")
    elif stage == EVStage.COST_BENCHMARKING.value:
        bm = case.benchmark or {}
        if bm.get("status") != "reviewed":
            block("BENCHMARK_REVIEW_REQUIRED", "Compute the EV parts benchmark and record the human review (flagged lines need a review note).")
    elif stage == EVStage.TECHNICAL_SIGN_OFF.value:
        blockers.extend(_signoff_prerequisites(db, case, rule))
        if (case.settlement_clearance or {}).get("status") != "granted":
            block("TECHNICAL_SIGN_OFF_REQUIRED", "An EV technical sign-off by a claims manager (distinct from the disposition recorder) is mandatory.")
    elif stage == EVStage.SETTLEMENT_CLEARED.value:
        if not _settlement_approved(db, case.claim_id):
            block("OD_SETTLEMENT_APPROVAL_REQUIRED", "Settlement must be approved in the OD engine (maker-checker) before repair can start.")
    elif stage == EVStage.REPAIR_RECERTIFICATION.value:
        rc = case.recertification or {}
        if not rc.get("passed"):
            block("RECERTIFICATION_REQUIRED", "A passed post-repair HV recertification by an EV-qualified provider is required before the vehicle is released.")
        tw = case.thermal_watch or {}
        if tw.get("required") and not tw.get("cleared"):
            block("THERMAL_WATCH_NOT_CLEARED", "The thermal watch must be cleared with an OEM reference before release.")
    elif stage == EVStage.SALVAGE_DISPOSAL.value:
        sv = _salvage_status(case, rule)
        if not sv["complete"]:
            block("SALVAGE_CHAIN_INCOMPLETE", "Salvage chain of custody incomplete; missing: " + ", ".join(sv["missing_events"]) + ".")
    return blockers


def _open_stage_task(db: Session, case: EVClaimCase, claim: Claim, rule: dict[str, Any], stage: str) -> ClaimTask:
    for t in (
        db.query(ClaimTask)
        .filter(ClaimTask.claim_id == claim.id, ClaimTask.task_type.startswith("ev_case_stage_", autoescape=True), ClaimTask.status == "open")
        .all()
    ):
        t.status = "completed"
        t.completed_at = _utcnow()
    spec = rule["stage_catalogue"][stage]
    case.queue_name = spec["queue"]
    if stage in QUEUE_OWNING_STAGES:
        claim.queue_name = spec["queue"]
    now = _utcnow()
    task = ClaimTask(
        tenant_id=case.tenant_id,
        claim_id=claim.id,
        task_type=f"ev_case_stage_{stage.lower()}",
        title=f"[EV] {spec['label']} - {case.case_number}",
        description=f"Human-gated EV stage '{stage}'. Autonomous completion is prohibited ({EV_RULE_ID}).",
        assigned_role=spec["owner_role"],
        created_by_agent="ev_workflow_engine",
        priority="urgent" if case.risk_class == "battery_critical" else "high",
        status="open" if stage != EVStage.CLOSED.value else "completed",
        reason_code="EV_STAGE_HUMAN_GATE",
        due_at=(now + timedelta(hours=int(spec["sla_hours"]))) if spec["sla_hours"] else None,
        metadata_json={"ev_case_id": case.id, "queue": spec["queue"], "stage": stage, "human_gate": spec["human_gate"], "risk_class": case.risk_class},
    )
    db.add(task)
    return task


def _next_action_text(case: EVClaimCase, rule: dict[str, Any]) -> str:
    spec = rule["stage_catalogue"].get(case.stage, {})
    role = spec.get("owner_role", "claims_handler").replace("_", " ")
    return f"EV {spec.get('label', case.stage)}: {role} action required (human-gated, queue {spec.get('queue', '')}); vehicle on HV hold - do not drive or charge"


def _enter_stage(
    db: Session,
    case: EVClaimCase,
    claim: Claim,
    rule: dict[str, Any],
    stage: str,
    user: UserContext,
    *,
    note: str = "",
    skipped: list[str] | None = None,
) -> None:
    prev = case.stage
    case.stage = stage
    case.stage_history = [
        *(case.stage_history or []),
        {"from": prev, "to": stage, "at": _iso(_utcnow()), "by": _actor(user), "note": note, "skipped_by_rule": skipped or []},
    ]
    _open_stage_task(db, case, claim, rule, stage)
    claim.workflow_state = {**(claim.workflow_state or {}), "ev_stage": stage, "ev_case_number": case.case_number, "ev_risk_class": case.risk_class}
    claim.next_expected_action = _next_action_text(case, rule)[:200]


# ----------------------------------------------------------------------------------------------
# Opening a case and triage
# ----------------------------------------------------------------------------------------------
def _coverage_note(db: Session, claim: Claim) -> dict[str, Any]:
    policy = db.query(Policy).filter(Policy.id == claim.policy_id).first() if claim.policy_id else None
    if not policy:
        return {"status": "unmatched", "note": "No matched policy; coverage is a human decision."}
    has_ev_wording = policy.wording_doc_id == EV_WORDING_DOC_ID
    return {
        "status": "ev_endorsement_present" if has_ev_wording else "ev_endorsement_not_confirmed",
        "wording_doc_id": policy.wording_doc_id,
        "clauses": ["EV-BAT-01", "EV-SAFE-01"] if has_ev_wording else [],
        "note": (
            "EV traction battery & HV safety endorsement on the policy."
            if has_ev_wording
            else "EV battery endorsement not confirmed on the policy wording; a human must clarify battery cover. Never auto-declined."
        ),
    }


def open_ev_case(
    db: Session,
    claim: Claim,
    user: UserContext,
    *,
    vehicle: Vehicle | None = None,
    system_initiated: bool = False,
) -> EVClaimCase:
    """Open the EV case and the HV safety hold. The platform opens it at FNOL for any EV claim."""
    if not system_initiated:
        _require_role(user, ROLES_INTAKE, "open an EV case")
    existing = get_ev_case(db, claim)
    if existing:
        return existing
    if vehicle is None and claim.vehicle_id:
        vehicle = db.query(Vehicle).filter(Vehicle.id == claim.vehicle_id).first()
    if not claim_requires_ev_workflow(claim, vehicle):
        raise DomainError(
            ErrorCode.STATE_CONFLICT,
            "This claim does not concern an electric vehicle's own damage, so it cannot carry an EV case.",
            status_code=409,
        )
    rule = ev_rule(db)
    derived = _derived_signals(claim)
    cls = classify_signals(rule, derived, claim)
    now = _utcnow()
    case = EVClaimCase(
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        case_number=f"EV-{claim.claim_number.split('CLM-')[-1]}",
        stage=EVStage.INTAKE_TRIAGE.value,
        queue_name="ev_triage_intake",
        risk_class=cls["risk_class"],
        operation_status=OPERATION_HOLD,
        triage={
            "recorded": False,
            "signals": cls["signals"],
            "signal_sources": {s: "claim_fnol_flags" for s in cls["signals"]},
            "impact_score": cls["impact_score"],
            "impact_band": cls["impact_band"],
            "thermal_level": cls["thermal_level"],
            "coverage": _coverage_note(db, claim),
            "customer_declared_drivable": None,
            "note": "Signals derived from FNOL flags only; a human must confirm the triage. Declared drivability is never accepted as clearance.",
        },
        thermal_watch=thermal_watch_for(rule, cls["risk_class"], now),
        created_by=user.user_id,
        stage_history=[{"from": None, "to": EVStage.INTAKE_TRIAGE.value, "at": _iso(now), "by": _actor(user), "note": "EV case opened with HV safety hold", "skipped_by_rule": []}],
    )
    db.add(case)
    db.flush()
    claim.workflow_state = {**(claim.workflow_state or {}), "ev_workflow": True, "ev_case_number": case.case_number, "ev_risk_class": case.risk_class, "ev_stage": case.stage}
    _open_stage_task(db, case, claim, rule, EVStage.INTAKE_TRIAGE.value)
    claim.next_expected_action = _next_action_text(case, rule)[:200]
    _audit(db, case, user, "EV_CASE_OPENED", {"risk_class": case.risk_class, "signals": cls["signals"], "operation_status": OPERATION_HOLD})
    emit_outbox_event(
        db,
        tenant_id=case.tenant_id,
        aggregate_id=claim.id,
        event_type="EVCaseOpened",
        payload={"ev_case_id": case.id, "risk_class": case.risk_class},
        idempotency_key=f"EVCaseOpened:{case.id}",
    )
    if cls["escalation_level"]:
        _raise_escalation(
            db, case, claim, user, rule, level=cls["escalation_level"], signals=cls["signals"],
            description="Automatically raised at FNOL from the declared signals.", source="system_fnol",
        )
    return case


def _safety_message(rule: dict[str, Any], level: str | None) -> str:
    lvl = level or "urgent"
    return str(rule["safety_escalation"]["levels"][lvl]["customer_message"])


def _send_safety_message(db: Session, claim: Claim, rule: dict[str, Any], level: str | None, *, subject: str) -> None:
    # Safety instructions are transactional and never withheld for marketing-consent reasons.
    db.add(
        Communication(
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            channel="portal",
            language=claim.preferred_language,
            template_id="EV_SAFETY_INSTRUCTION",
            trigger_event="ev_safety_triage",
            claim_state_snapshot=claim.status,
            subject=subject,
            body=_safety_message(rule, level),
            requires_human_review=False,
            delivery_status="sent_mock",
            consent_verified=True,
        )
    )


def _apply_class_change(db: Session, case: EVClaimCase, claim: Claim, rule: dict[str, Any], new_class: str, user: UserContext) -> None:
    """Risk class can only go up. If stricter stages became mandatory, rewind and revoke any settlement clearance."""
    if _risk_rank(new_class) <= _risk_rank(case.risk_class):
        return
    old = case.risk_class
    case.risk_class = new_class
    if rule["risk_classes"][new_class]["thermal_watch_required"] and not (case.thermal_watch or {}).get("required"):
        case.thermal_watch = thermal_watch_for(rule, new_class)
    path = stage_path(case, rule)
    cur_idx = STAGE_ORDER.index(case.stage)
    rewind_to: Optional[str] = None
    for stage in path:
        field = STAGE_ARTEFACT_FIELD.get(stage)
        if field and STAGE_ORDER.index(stage) < cur_idx and not getattr(case, field):
            rewind_to = stage
            break
    revoked = False
    if rewind_to:
        if (case.settlement_clearance or {}).get("status") == "granted":
            case.settlement_clearance = {**case.settlement_clearance, "status": "revoked", "revoked_at": _iso(_utcnow()), "revoked_reason": f"Risk class escalated {old} -> {new_class}"}
            revoked = True
        _enter_stage(db, case, claim, rule, rewind_to, user, note=f"Rewound: risk class escalated {old} -> {new_class}")
    _audit(db, case, user, "EV_RISK_CLASS_ESCALATED", {"from": old, "to": new_class, "rewound_to": rewind_to, "clearance_revoked": revoked})


def record_triage(
    db: Session,
    case: EVClaimCase,
    claim: Claim,
    user: UserContext,
    *,
    signals: list[str],
    notes: str = "",
    customer_declared_drivable: bool | None = None,
    charging_in_progress: bool = False,
    vehicle_location: str = "",
) -> EVClaimCase:
    """Human-confirmed EV safety triage. Signals are append-only and the risk class can never be lowered."""
    _require_role(user, ROLES_INTAKE, "record the EV safety triage")
    _assert_open(case)
    rule = ev_rule(db)
    previously_recorded = set((case.triage or {}).get("signals", []))
    merged = sorted(previously_recorded | set(signals))
    cls = classify_signals(rule, merged, claim)
    sources = dict((case.triage or {}).get("signal_sources", {}))
    for s in signals:
        sources.setdefault(s, f"human:{user.role.value}")
    first_confirmation = not (case.triage or {}).get("recorded")
    case.triage = {
        **(case.triage or {}),
        "recorded": True,
        "recorded_by": _actor(user),
        "recorded_at": _iso(_utcnow()),
        "signals": cls["signals"],
        "signal_sources": sources,
        "signals_by_category": cls["signals_by_category"],
        "impact_score": cls["impact_score"],
        "impact_band": cls["impact_band"],
        "thermal_level": cls["thermal_level"],
        "customer_declared_drivable": customer_declared_drivable,
        "drivability_note": (
            "Customer says the vehicle is drivable. This is recorded but NOT accepted: HV condition cannot be judged by the customer or from photographs."
            if customer_declared_drivable
            else ""
        ),
        "charging_in_progress": bool(charging_in_progress),
        "vehicle_location": _clean(vehicle_location, max_len=240),
        "notes": _clean(notes, max_len=1000),
        "safe_to_operate": "not_determinable_from_photographs",
        "customer_instructions_sent": True,
    }
    if first_confirmation:
        _send_safety_message(db, claim, rule, cls["escalation_level"], subject=f"Safety instructions for your electric vehicle - claim {claim.claim_number}")
    _apply_class_change(db, case, claim, rule, cls["risk_class"], user)
    case.operation_status = OPERATION_HOLD
    _audit(db, case, user, "EV_TRIAGE_RECORDED", {"signals": cls["signals"], "risk_class": case.risk_class, "impact_band": cls["impact_band"]})
    added = sorted(set(signals) - previously_recorded)
    if added:
        added_cls = classify_signals(rule, added, claim)
        if added_cls["escalation_level"]:
            _raise_escalation(
                db, case, claim, user, rule, level=added_cls["escalation_level"], signals=added,
                description="Raised from the confirmed EV safety triage.", source="triage",
            )
    return case


# ----------------------------------------------------------------------------------------------
# Safety escalation
# ----------------------------------------------------------------------------------------------
def _raise_escalation(
    db: Session,
    case: EVClaimCase,
    claim: Claim,
    user: UserContext,
    rule: dict[str, Any],
    *,
    level: str,
    signals: list[str],
    description: str,
    source: str,
) -> dict[str, Any]:
    spec = rule["safety_escalation"]["levels"][level]
    now = _utcnow()
    esc = {
        "id": uuid.uuid4().hex[:12],
        "level": level,
        "label": spec["label"],
        "signals": sorted(set(signals)),
        "description": _clean(description, max_len=1000),
        "source": source,
        "status": "open",
        "raised_by": _actor(user),
        "raised_at": _iso(now),
        "sla_due_at": _iso(now + timedelta(minutes=int(spec["sla_minutes"]))),
        "customer_message": spec["customer_message"],
        "acknowledged_by": None,
        "acknowledged_at": None,
        "actions_taken": "",
        "resolved_by": None,
        "resolved_at": None,
        "resolution": "",
        "evidence_ref": "",
    }
    case.safety_escalations = [*(case.safety_escalations or []), esc]
    case.operation_status = OPERATION_HOLD
    db.add(
        ClaimTask(
            tenant_id=case.tenant_id,
            claim_id=claim.id,
            task_type="ev_case_escalation",
            title=f"[EV SAFETY] {spec['label']} - {case.case_number}",
            description=f"Safety escalation {esc['id']}. Acknowledge within {spec['sla_minutes']} minutes. Signals: {', '.join(esc['signals']) or 'n/a'}.",
            assigned_role=rule["safety_escalation"]["owner_role"],
            created_by_agent="ev_workflow_engine",
            priority="urgent",
            status="open",
            reason_code="EV_SAFETY_ESCALATION",
            due_at=now + timedelta(minutes=int(spec["sla_minutes"])),
            metadata_json={"ev_case_id": case.id, "escalation_id": esc["id"], "level": level, "queue": "ev_safety_escalation"},
        )
    )
    _send_safety_message(db, claim, rule, level, subject=f"URGENT safety instruction - claim {claim.claim_number}")
    claim.workflow_state = {**(claim.workflow_state or {}), "ev_safety_escalation_open": True}
    _audit(db, case, user, "EV_SAFETY_ESCALATION_RAISED", {"escalation_id": esc["id"], "level": level, "signals": esc["signals"], "source": source})
    emit_outbox_event(
        db,
        tenant_id=case.tenant_id,
        aggregate_id=claim.id,
        event_type="EVSafetyEscalationRaised",
        payload={"ev_case_id": case.id, "escalation_id": esc["id"], "level": level},
        idempotency_key=f"EVSafetyEscalationRaised:{esc['id']}",
    )
    return esc


def raise_safety_escalation(
    db: Session,
    case: EVClaimCase,
    claim: Claim,
    user: UserContext,
    *,
    signals: list[str],
    description: str,
    level: str | None = None,
) -> EVClaimCase:
    """Anyone involved in the claim, including the policyholder, can raise a safety escalation.

    The level is derived from the signals. A caller can ask for a higher level but never a lower one.
    """
    _require_role(user, ROLES_ESCALATE, "raise a safety escalation")
    _assert_open(case)
    rule = ev_rule(db)
    if level is not None and level not in rule["safety_escalation"]["levels"]:
        raise DomainError(ErrorCode.VALIDATION_ERROR, f"level must be one of {list(rule['safety_escalation']['levels'])}", status_code=400)
    merged = sorted(set((case.triage or {}).get("signals", [])) | set(signals))
    cls = classify_signals(rule, merged, claim)
    new_cls = classify_signals(rule, sorted(set(signals)), claim)
    derived = new_cls["escalation_level"] or "urgent"
    chosen = derived
    if level and _LEVEL_RANK[level] > _LEVEL_RANK[derived]:
        chosen = level
    sources = dict((case.triage or {}).get("signal_sources", {}))
    for s in signals:
        sources.setdefault(s, f"escalation:{user.role.value}")
    case.triage = {
        **(case.triage or {}),
        "signals": cls["signals"],
        "signal_sources": sources,
        "signals_by_category": cls["signals_by_category"],
        "impact_score": cls["impact_score"],
        "impact_band": cls["impact_band"],
        "thermal_level": cls["thermal_level"],
    }
    _apply_class_change(db, case, claim, rule, cls["risk_class"], user)
    _raise_escalation(db, case, claim, user, rule, level=chosen, signals=signals, description=description, source=f"reported_by_{user.role.value}")
    return case


def acknowledge_safety_escalation(db: Session, case: EVClaimCase, user: UserContext, *, escalation_id: str, actions_taken: str) -> EVClaimCase:
    _require_role(user, ROLES_MANAGER, "acknowledge a safety escalation")
    esc = _find_escalation(case, escalation_id)
    if esc["status"] != "open":
        raise DomainError(ErrorCode.STATE_CONFLICT, f"Escalation is already {esc['status']}", status_code=409)
    if not actions_taken.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, "actions_taken is required to acknowledge a safety escalation", status_code=400)
    esc.update({"status": "acknowledged", "acknowledged_by": _actor(user), "acknowledged_at": _iso(_utcnow()), "actions_taken": _clean(actions_taken, max_len=1000)})
    _replace_escalation(case, esc)
    _audit(db, case, user, "EV_SAFETY_ESCALATION_ACKNOWLEDGED", {"escalation_id": escalation_id})
    return case


def resolve_safety_escalation(
    db: Session,
    case: EVClaimCase,
    claim: Claim,
    user: UserContext,
    *,
    escalation_id: str,
    resolution: str,
    evidence_ref: str,
    thermal_stable_confirmed: bool = False,
) -> EVClaimCase:
    _require_role(user, ROLES_MANAGER, "resolve a safety escalation")
    rule = ev_rule(db)
    esc = _find_escalation(case, escalation_id)
    if esc["status"] == "resolved":
        raise DomainError(ErrorCode.STATE_CONFLICT, "Escalation is already resolved", status_code=409)
    if esc["status"] != "acknowledged":
        raise DomainError(ErrorCode.STATE_CONFLICT, "Acknowledge the escalation before resolving it", status_code=409)
    if esc["raised_by"]["user_id"] == user.user_id:
        raise DomainError(ErrorCode.NOT_AUTHORISED, "Separation of duties: the user who raised an escalation cannot be the one to resolve it", status_code=403)
    if rule["safety_escalation"]["resolution_requires_evidence_reference"] and not evidence_ref.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, "An evidence reference (OEM scan, fire-service or EV safety officer report) is required to resolve an escalation", status_code=400)
    if esc["level"] == "emergency" and not thermal_stable_confirmed:
        raise DomainError(ErrorCode.HUMAN_REVIEW_REQUIRED, "An emergency escalation can only be resolved with a confirmed thermal-stable assessment", status_code=409)
    esc.update(
        {
            "status": "resolved",
            "resolved_by": _actor(user),
            "resolved_at": _iso(_utcnow()),
            "resolution": _clean(resolution, max_len=1000),
            "evidence_ref": _clean(evidence_ref, max_len=200),
            "thermal_stable_confirmed": bool(thermal_stable_confirmed),
        }
    )
    _replace_escalation(case, esc)
    for t in db.query(ClaimTask).filter(ClaimTask.claim_id == claim.id, ClaimTask.task_type == "ev_case_escalation", ClaimTask.status == "open").all():
        if (t.metadata_json or {}).get("escalation_id") == escalation_id:
            t.status = "completed"
            t.completed_at = _utcnow()
    if not open_escalations(case):
        claim.workflow_state = {**(claim.workflow_state or {}), "ev_safety_escalation_open": False}
    _audit(db, case, user, "EV_SAFETY_ESCALATION_RESOLVED", {"escalation_id": escalation_id, "evidence_ref": esc["evidence_ref"]})
    return case


def _find_escalation(case: EVClaimCase, escalation_id: str) -> dict[str, Any]:
    for e in case.safety_escalations or []:
        if e["id"] == escalation_id:
            return dict(e)
    raise DomainError(ErrorCode.NOT_FOUND, f"Escalation '{escalation_id}' not found", status_code=404)


def _replace_escalation(case: EVClaimCase, esc: dict[str, Any]) -> None:
    case.safety_escalations = [esc if e["id"] == esc["id"] else e for e in case.safety_escalations or []]


def _assert_open(case: EVClaimCase) -> None:
    if case.stage == EVStage.CLOSED.value:
        raise DomainError(ErrorCode.STATE_CONFLICT, "The EV case is closed", status_code=409)


def _assert_stage_in(case: EVClaimCase, stages: set[EVStage], action: str) -> None:
    """An artefact is recorded at its own stage only, so a later stage can never silently rewrite an earlier one."""
    if case.stage not in {s.value for s in stages}:
        wanted = ", ".join(sorted(s.value for s in stages))
        raise DomainError(
            ErrorCode.STATE_CONFLICT,
            f"Cannot {action}: the case is at {case.stage}; this is recorded at {wanted}.",
            status_code=409,
        )


# ----------------------------------------------------------------------------------------------
# Stage actions
# ----------------------------------------------------------------------------------------------
def record_recovery(
    db: Session,
    case: EVClaimCase,
    claim: Claim,
    user: UserContext,
    *,
    provider_id: str | None,
    tow_method: str,
    hv_isolation_method: str,
    hv_isolation_verified: bool,
    quarantine_location: str,
    quarantine_clearance_m: Decimal | None = None,
    notes: str = "",
) -> EVClaimCase:
    _require_role(user, ROLES_RECOVERY, "record recovery and HV isolation")
    _assert_open(case)
    _assert_stage_in(case, {EVStage.SAFE_RECOVERY_ISOLATION}, "record recovery and isolation")
    rule = ev_rule(db)
    controls = rule["controls"]
    if tow_method in controls["rejected_tow_methods"]:
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            f"Tow method '{tow_method}' is not permitted for an EV with unverified HV condition. Use {controls['acceptable_tow_methods']}.",
            status_code=409,
        )
    if tow_method not in controls["acceptable_tow_methods"]:
        raise DomainError(ErrorCode.VALIDATION_ERROR, f"tow_method must be one of {controls['acceptable_tow_methods']}", status_code=400)
    provider = _resolve_provider(db, user, case, provider_id, own_roles={Role.GARAGE})
    qual = provider_qualification(provider, rule["recovery_provider_requirements"], need_flatbed=tow_method == "flatbed")
    _require_qualified(qual, what="Recovery and HV isolation")
    min_clear = Decimal(str(rule["thermal"]["quarantine_min_clearance_m"]))
    if quarantine_clearance_m is not None and Decimal(str(quarantine_clearance_m)) < min_clear:
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            f"Quarantine clearance {quarantine_clearance_m} m is below the required {min_clear} m from other vehicles and buildings.",
            status_code=409,
        )
    case.recovery = {
        "provider_id": provider.id,
        "provider_name": provider.name,
        "qualification": qual,
        "tow_method": tow_method,
        "hv_isolation_method": _clean(hv_isolation_method, max_len=200),
        "hv_isolation_verified": bool(hv_isolation_verified),
        "quarantine_location": _clean(quarantine_location, max_len=240),
        "quarantine_clearance_m": str(quarantine_clearance_m) if quarantine_clearance_m is not None else None,
        "notes": _clean(notes, max_len=800),
        "recorded_by": _actor(user),
        "recorded_at": _iso(_utcnow()),
    }
    case.operation_status = OPERATION_HOLD
    _audit(db, case, user, "EV_RECOVERY_RECORDED", {"provider_id": provider.id, "tow_method": tow_method, "isolation_verified": hv_isolation_verified})
    return case


def record_specialist_survey(
    db: Session,
    case: EVClaimCase,
    claim: Claim,
    user: UserContext,
    *,
    surveyor_provider_id: str | None,
    inspection_mode: str,
    hv_isolation_verified: bool,
    pack_findings: list[str],
    hv_system_findings: list[str],
    charging_system_findings: list[str],
    thermal_indicators_observed: bool,
    pack_removal_required: bool,
    report_ref: str,
    notes: str = "",
) -> EVClaimCase:
    _require_role(user, ROLES_SURVEY, "record the specialist EV survey")
    _assert_open(case)
    _assert_stage_in(case, {EVStage.SPECIALIST_SURVEY}, "record the specialist survey")
    rule = ev_rule(db)
    controls = rule["controls"]
    if inspection_mode in controls["rejected_inspection_modes"]:
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            f"Inspection mode '{inspection_mode}' is rejected: EV battery and HV condition cannot be assessed from photographs, video or customer declarations. Use {controls['acceptable_inspection_modes']}.",
            status_code=409,
        )
    if inspection_mode not in controls["acceptable_inspection_modes"]:
        raise DomainError(ErrorCode.VALIDATION_ERROR, f"inspection_mode must be one of {controls['acceptable_inspection_modes']}", status_code=400)
    provider = _resolve_provider(db, user, case, surveyor_provider_id, own_roles={Role.SURVEYOR})
    qual = provider_qualification(provider, rule["surveyor_requirements"])
    if provider.provider_type != rule["surveyor_requirements"]["provider_type"]:
        qual = {**qual, "qualified": False, "reasons": [*qual["reasons"], "Provider is not a surveyor"]}
    _require_qualified(qual, what="The EV survey")
    case.survey = {
        "recorded": True,
        "surveyor_provider_id": provider.id,
        "surveyor_name": provider.name,
        "qualification": qual,
        "inspection_mode": inspection_mode,
        "hv_isolation_verified": bool(hv_isolation_verified),
        "pack_findings": [_clean(x, max_len=300) for x in pack_findings],
        "hv_system_findings": [_clean(x, max_len=300) for x in hv_system_findings],
        "charging_system_findings": [_clean(x, max_len=300) for x in charging_system_findings],
        "thermal_indicators_observed": bool(thermal_indicators_observed),
        "pack_removal_required": bool(pack_removal_required),
        "report_ref": _clean(report_ref, max_len=120),
        "notes": _clean(notes, max_len=1000),
        "recorded_by": _actor(user),
        "recorded_at": _iso(_utcnow()),
    }
    case.operation_status = OPERATION_HOLD
    _audit(db, case, user, "EV_SPECIALIST_SURVEY_RECORDED", {"surveyor_provider_id": provider.id, "thermal_indicators_observed": thermal_indicators_observed})
    if thermal_indicators_observed:
        merged = sorted(set((case.triage or {}).get("signals", [])) | {"abnormal_heat_from_pack"})
        cls = classify_signals(rule, merged, claim)
        case.triage = {**(case.triage or {}), "signals": cls["signals"], "impact_score": cls["impact_score"], "impact_band": cls["impact_band"], "thermal_level": cls["thermal_level"]}
        _apply_class_change(db, case, claim, rule, cls["risk_class"], user)
        _raise_escalation(
            db, case, claim, user, rule, level="emergency", signals=["abnormal_heat_from_pack"],
            description="Thermal indicators observed by the surveyor during the physical inspection.", source="specialist_survey",
        )
    return case


def record_oem_diagnostics(
    db: Session,
    case: EVClaimCase,
    claim: Claim,
    user: UserContext,
    *,
    provider_id: str | None,
    tool: str,
    report_ref: str,
    tests: list[dict[str, Any]],
) -> EVClaimCase:
    _require_role(user, ROLES_DIAGNOSTICS, "record OEM diagnostics")
    _assert_open(case)
    _assert_stage_in(case, {EVStage.OEM_DIAGNOSTICS}, "record OEM diagnostics")
    rule = ev_rule(db)
    spec = rule["oem_diagnostics"]
    if spec["oem_report_reference_required"] and not report_ref.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, "The OEM scan report reference is required", status_code=400)
    provider = _resolve_provider(db, user, case, provider_id, own_roles={Role.GARAGE})
    qual = provider_qualification(provider, rule["diagnostic_provider_requirements"], need_oem=True)
    if provider.provider_type != rule["diagnostic_provider_requirements"]["provider_type"]:
        qual = {**qual, "qualified": False, "reasons": [*qual["reasons"], "Provider is not a workshop"]}
    _require_qualified(qual, what="OEM diagnostics")
    result = evaluate_diagnostics(rule, case.risk_class, tests)
    case.diagnostics = {
        **result,
        "provider_id": provider.id,
        "provider_name": provider.name,
        "qualification": qual,
        "tool": _clean(tool, max_len=120),
        "report_ref": _clean(report_ref, max_len=120),
        "recorded_by": _actor(user),
        "recorded_at": _iso(_utcnow()),
    }
    case.operation_status = OPERATION_HOLD
    _audit(db, case, user, "EV_OEM_DIAGNOSTICS_RECORDED", {"outcome": result["outcome"], "critical_fail": result["critical_fail"], "missing": result["missing_tests"]})
    return case


def record_disposition(
    db: Session,
    case: EVClaimCase,
    claim: Claim,
    user: UserContext,
    *,
    decision: str,
    rationale: str,
    oem_engineer_name: str,
    oem_engineer_ref: str,
    oem_engineer_org: str = "",
) -> EVClaimCase:
    """Human battery repair/replace decision. The software advisory is shown but never binding."""
    _require_role(user, ROLES_HANDLING, "record the battery disposition")
    _assert_open(case)
    _assert_stage_in(case, {EVStage.BATTERY_DISPOSITION}, "record the battery disposition")
    rule = ev_rule(db)
    spec = rule["disposition"]
    if case.risk_class == "screening_only":
        raise DomainError(ErrorCode.STATE_CONFLICT, "A screening-only EV case has no battery disposition stage", status_code=409)
    if decision not in spec["decisions"]:
        raise DomainError(ErrorCode.VALIDATION_ERROR, f"decision must be one of {spec['decisions']}", status_code=400)
    if not (case.diagnostics or {}).get("complete"):
        raise DomainError(ErrorCode.HUMAN_REVIEW_REQUIRED, "A battery decision needs complete OEM diagnostics first.", status_code=409)
    if (case.diagnostics or {}).get("critical_fail") and decision in spec["decisions_barred_after_critical_fail"]:
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            f"A critical OEM test failed; '{decision}' is barred. Choose replace_modules, replace_pack or total_loss_review.",
            status_code=409,
        )
    if not rationale.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, "A reasoned rationale is required", status_code=400)
    if rule["controls"]["battery_decision_requires_oem_engineer_signoff"] and not (oem_engineer_name.strip() and oem_engineer_ref.strip()):
        raise DomainError(ErrorCode.VALIDATION_ERROR, "An OEM engineer name and reference are required for the battery decision", status_code=400)
    survey = case.survey or {}
    inspectors = {str(n).strip().lower() for n in (survey.get("surveyor_name"), (survey.get("recorded_by") or {}).get("name")) if n}
    if oem_engineer_name.strip().lower() in inspectors:
        raise DomainError(ErrorCode.NOT_AUTHORISED, "Separation of duties: the surveyor who inspected the vehicle cannot also be the OEM engineer signing off the battery decision", status_code=403)
    advisory = compute_disposition_advisory(db, case, claim, rule)
    case.disposition = {
        "decision": decision,
        "rationale": _clean(rationale, max_len=1500),
        "oem_engineer": {"name": _clean(oem_engineer_name, max_len=120), "ref": _clean(oem_engineer_ref, max_len=120), "org": _clean(oem_engineer_org, max_len=120)},
        "advisory_at_decision": advisory,
        "followed_advisory": advisory.get("recommended") == decision,
        "requires_pack_removal": decision in spec["decisions_requiring_removal"],
        "recorded_by": _actor(user),
        "recorded_at": _iso(_utcnow()),
    }
    if decision == "total_loss_review":
        claim.workflow_state = {**(claim.workflow_state or {}), "ev_total_loss_review_required": True}
    _audit(db, case, user, "EV_BATTERY_DISPOSITION_RECORDED", {"decision": decision, "followed_advisory": case.disposition["followed_advisory"]})
    return case


def record_benchmark(db: Session, case: EVClaimCase, claim: Claim, user: UserContext, *, lines: list[dict[str, Any]]) -> EVClaimCase:
    _require_role(user, ROLES_HANDLING, "compute the EV parts cost benchmark")
    _assert_open(case)
    _assert_stage_in(case, {EVStage.COST_BENCHMARKING}, "compute the EV parts benchmark")
    if not lines:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "At least one estimate line is required", status_code=400)
    rule = ev_rule(db)
    result = compute_benchmark(rule, lines)
    case.benchmark = {**result, "status": "computed", "computed_by": _actor(user), "computed_at": _iso(_utcnow()), "rule_version": rule["version"]}
    _audit(db, case, user, "EV_BENCHMARK_COMPUTED", {"flagged_lines": result["flagged_lines"], "total_quoted_inr": result["total_quoted_inr"]})
    return case


def review_benchmark(db: Session, case: EVClaimCase, user: UserContext, *, note: str) -> EVClaimCase:
    _require_role(user, ROLES_HANDLING, "review the EV parts cost benchmark")
    _assert_open(case)
    _assert_stage_in(case, {EVStage.COST_BENCHMARKING}, "review the EV parts benchmark")
    bm = case.benchmark or {}
    if bm.get("status") not in {"computed", "reviewed"}:
        raise DomainError(ErrorCode.STATE_CONFLICT, "Compute the benchmark before reviewing it", status_code=409)
    if bm.get("requires_manager_review") and user.role not in ROLES_MANAGER:
        raise DomainError(ErrorCode.NOT_AUTHORISED, "Flagged or high-value benchmarks need a claims manager review", status_code=403)
    if bm.get("flagged_lines") and not note.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, "A review note is required when lines are flagged", status_code=400)
    case.benchmark = {**bm, "status": "reviewed", "reviewed_by": _actor(user), "reviewed_at": _iso(_utcnow()), "review_note": _clean(note, max_len=800)}
    _audit(db, case, user, "EV_BENCHMARK_REVIEWED", {"flagged_lines": bm.get("flagged_lines")})
    return case


def clear_thermal_watch(db: Session, case: EVClaimCase, user: UserContext, *, basis: str, oem_reference: str) -> EVClaimCase:
    _require_role(user, ROLES_MANAGER, "clear the thermal watch")
    _assert_open(case)
    if STAGE_ORDER.index(case.stage) < STAGE_ORDER.index(EVStage.OEM_DIAGNOSTICS.value):
        raise DomainError(ErrorCode.STATE_CONFLICT, "The thermal watch can be cleared only after OEM diagnostics stage is reached", status_code=409)
    tw = case.thermal_watch or {}
    if not tw.get("required"):
        raise DomainError(ErrorCode.STATE_CONFLICT, "No thermal watch is required for this case", status_code=409)
    diag = case.diagnostics or {}
    if not diag.get("complete") or diag.get("critical_fail") or diag.get("outcome") == "fail":
        raise DomainError(ErrorCode.HUMAN_REVIEW_REQUIRED, "The thermal watch cannot be cleared until OEM diagnostics are complete and not failing", status_code=409)
    if open_escalations(case):
        raise DomainError(ErrorCode.HUMAN_REVIEW_REQUIRED, "Resolve open safety escalations before clearing the thermal watch", status_code=409)
    if not basis.strip() or not oem_reference.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, "basis and oem_reference are required", status_code=400)
    case.thermal_watch = {**tw, "cleared": True, "cleared_by": _actor(user), "cleared_at": _iso(_utcnow()), "basis": _clean(basis, max_len=600), "oem_reference": _clean(oem_reference, max_len=120)}
    _audit(db, case, user, "EV_THERMAL_WATCH_CLEARED", {"oem_reference": oem_reference})
    return case


def technical_sign_off(db: Session, case: EVClaimCase, claim: Claim, user: UserContext, *, notes: str = "") -> EVClaimCase:
    """Human technical sign-off. It is the only way the OD settlement hold on an EV claim is lifted."""
    _require_role(user, ROLES_MANAGER, "give the EV technical sign-off")
    _assert_open(case)
    rule = ev_rule(db)
    if case.stage != EVStage.TECHNICAL_SIGN_OFF.value:
        raise DomainError(ErrorCode.STATE_CONFLICT, f"The case is at {case.stage}; technical sign-off applies only at TECHNICAL_SIGN_OFF", status_code=409)
    blockers = [b for b in evaluate_gates(db, case, rule) if b["code"] != "TECHNICAL_SIGN_OFF_REQUIRED"]
    if blockers:
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            "Sign-off prerequisites not met: " + "; ".join(b["message"] for b in blockers),
            status_code=409,
            details={"blockers": blockers, "stage": case.stage},
        )
    recorder = (case.disposition or {}).get("recorded_by", {}).get("user_id")
    if recorder and recorder == user.user_id:
        raise DomainError(ErrorCode.NOT_AUTHORISED, "Separation of duties: the user who recorded the battery disposition cannot give the technical sign-off", status_code=403)
    now = _utcnow()
    case.technical_signoff = {"by": _actor(user), "at": _iso(now), "notes": _clean(notes, max_len=800), "risk_class": case.risk_class}
    case.settlement_clearance = {"status": "granted", "granted_by": _actor(user), "granted_at": _iso(now), "basis": "human_technical_sign_off"}
    nxt = next_stage_after(case, rule)
    assert nxt is not None
    _enter_stage(db, case, claim, rule, nxt, user, note="Technical sign-off granted; EV hold on OD settlement lifted")
    _audit(db, case, user, "EV_TECHNICAL_SIGN_OFF", {"clearance": "granted"})
    emit_outbox_event(
        db,
        tenant_id=case.tenant_id,
        aggregate_id=claim.id,
        event_type="EVSettlementClearanceGranted",
        payload={"ev_case_id": case.id},
        idempotency_key=f"EVSettlementClearanceGranted:{case.id}:{int(now.timestamp())}",
    )
    return case


def record_recertification(
    db: Session,
    case: EVClaimCase,
    claim: Claim,
    user: UserContext,
    *,
    provider_id: str | None,
    insulation_resistance_ohm_per_volt: Decimal,
    dtc_cleared: bool,
    hv_interlock_ok: bool,
    charge_test_ok: bool,
    thermal_scan_ok: bool,
    physical_road_test_done: bool,
    oem_certificate_ref: str,
    notes: str = "",
) -> EVClaimCase:
    """Post-repair HV recertification. A pass is the only thing that can release the operating hold."""
    _require_role(user, ROLES_RECERT, "record the post-repair HV recertification")
    _assert_open(case)
    _assert_stage_in(case, {EVStage.REPAIR_RECERTIFICATION}, "record the recertification")
    rule = ev_rule(db)
    if (case.settlement_clearance or {}).get("status") != "granted":
        raise DomainError(ErrorCode.HUMAN_REVIEW_REQUIRED, "Settlement clearance is not granted; repair and recertification cannot proceed", status_code=409)
    own = {Role.GARAGE, Role.SURVEYOR}
    provider = _resolve_provider(db, user, case, provider_id, own_roles=own)
    req = rule["diagnostic_provider_requirements"] if provider.provider_type == "garage" else rule["surveyor_requirements"]
    qual = provider_qualification(provider, req, need_oem=provider.provider_type == "garage")
    _require_qualified(qual, what="Post-repair recertification")
    if not oem_certificate_ref.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, "The OEM recertification certificate reference is required", status_code=400)
    floor = Decimal(str(rule["oem_diagnostics"]["thresholds"]["insulation_resistance_min_ohm_per_volt"]))
    checks = {
        "insulation_resistance_ok": Decimal(str(insulation_resistance_ohm_per_volt)) >= floor,
        "dtc_cleared": bool(dtc_cleared),
        "hv_interlock_ok": bool(hv_interlock_ok),
        "charge_test_ok": bool(charge_test_ok),
        "thermal_scan_ok": bool(thermal_scan_ok),
        "physical_road_test_done": bool(physical_road_test_done),
    }
    passed = all(checks.values())
    reasons: list[str] = []
    if open_escalations(case):
        passed = False
        reasons.append("An open safety escalation prevents release.")
    tw = case.thermal_watch or {}
    if tw.get("required") and not tw.get("cleared"):
        passed = False
        reasons.append("The thermal watch has not been cleared.")
    reasons.extend(k for k, v in checks.items() if not v)
    case.recertification = {
        "passed": passed,
        "checks": checks,
        "insulation_resistance_ohm_per_volt": str(insulation_resistance_ohm_per_volt),
        "failed_or_blocking": reasons,
        "provider_id": provider.id,
        "provider_name": provider.name,
        "qualification": qual,
        "oem_certificate_ref": _clean(oem_certificate_ref, max_len=120),
        "notes": _clean(notes, max_len=800),
        "recorded_by": _actor(user),
        "recorded_at": _iso(_utcnow()),
    }
    case.operation_status = OPERATION_RELEASED if passed else OPERATION_HOLD
    if passed:
        claim.workflow_state = {**(claim.workflow_state or {}), "ev_released_for_operation": True}
    _audit(db, case, user, "EV_RECERTIFICATION_RECORDED", {"passed": passed, "failed_or_blocking": reasons})
    return case


def record_salvage_event(
    db: Session,
    case: EVClaimCase,
    claim: Claim,
    user: UserContext,
    *,
    event: str,
    battery_serial: str,
    location: str,
    performed_by_provider_id: str | None = None,
    recycler_registration_no: str = "",
    transport_dg_compliant: bool = False,
    certificate_ref: str = "",
    note: str = "",
) -> EVClaimCase:
    """Battery salvage and disposal chain of custody. A damaged pack is never resold or retained."""
    _require_role(user, ROLES_SALVAGE, "record a battery salvage event")
    _assert_open(case)
    _assert_stage_in(case, {EVStage.REPAIR_RECERTIFICATION, EVStage.SALVAGE_DISPOSAL}, "record a battery salvage event")
    rule = ev_rule(db)
    spec = rule["salvage"]
    if event in spec["forbidden_events"]:
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            f"'{event}' is prohibited: a damaged traction battery cannot be resold as a used part or retained by the insured.",
            status_code=409,
        )
    if event not in spec["allowed_events"]:
        raise DomainError(ErrorCode.VALIDATION_ERROR, f"event must be one of {spec['allowed_events']}", status_code=400)
    if not requires_salvage(case, rule):
        raise DomainError(ErrorCode.STATE_CONFLICT, "The recorded battery disposition does not remove the pack, so no salvage chain applies", status_code=409)
    salvage = dict(case.salvage or {})
    events: list[dict[str, Any]] = list(salvage.get("events", []))
    order = spec["allowed_events"]
    if events:
        last = events[-1]["event"]
        if order.index(event) <= order.index(last) and event != "received_by_recycler":
            raise DomainError(ErrorCode.STATE_CONFLICT, f"Salvage events are sequential; '{event}' cannot follow '{last}'", status_code=409)
        if order.index(event) > order.index(last) + 1 and not (event == "disposal_certified" and last == "handed_over"):
            raise DomainError(ErrorCode.STATE_CONFLICT, f"Salvage chain cannot skip steps: '{event}' cannot follow '{last}'", status_code=409)
    elif event != "pack_removed":
        raise DomainError(ErrorCode.STATE_CONFLICT, "The chain must start with 'pack_removed'", status_code=409)
    if not battery_serial.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, "battery_serial is required on every salvage event", status_code=400)
    known = salvage.get("battery_serial")
    if spec["serial_number_continuity_required"] and known and known != battery_serial.strip():
        raise DomainError(ErrorCode.HUMAN_REVIEW_REQUIRED, "Battery serial mismatch: the chain of custody must track one pack throughout", status_code=409)
    qual: dict[str, Any] | None = None
    if event == "pack_removed":
        provider = _resolve_provider(db, user, case, performed_by_provider_id, own_roles={Role.GARAGE})
        qual = provider_qualification(provider, rule["diagnostic_provider_requirements"])
        _require_qualified(qual, what="Battery pack removal")
    if event == "handed_over":
        if spec["recycler_registration_required"] and not recycler_registration_no.strip():
            raise DomainError(ErrorCode.VALIDATION_ERROR, "The registered recycler's registration number is required for hand-over", status_code=400)
        if spec["dangerous_goods_compliant_transport_required"] and not transport_dg_compliant:
            raise DomainError(ErrorCode.HUMAN_REVIEW_REQUIRED, "Hand-over requires dangerous-goods compliant transport of the damaged pack", status_code=409)
    if event == "disposal_certified" and not certificate_ref.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, "The disposal / recycling certificate reference is required", status_code=400)
    events.append(
        {
            "event": event,
            "at": _iso(_utcnow()),
            "by": _actor(user),
            "location": _clean(location, max_len=240),
            "performed_by_provider_id": performed_by_provider_id,
            "qualification": qual,
            "recycler_registration_no": _clean(recycler_registration_no, max_len=80),
            "transport_dg_compliant": bool(transport_dg_compliant),
            "certificate_ref": _clean(certificate_ref, max_len=120),
            "note": _clean(note, max_len=500),
        }
    )
    case.salvage = {**salvage, "battery_serial": battery_serial.strip(), "events": events, "regulation_reference": spec["regulation_reference"]}
    _audit(db, case, user, "EV_SALVAGE_EVENT_RECORDED", {"event": event, "battery_serial": battery_serial.strip()})
    return case


def advance_stage(db: Session, case: EVClaimCase, claim: Claim, user: UserContext, *, note: str = "") -> EVClaimCase:
    """Human-initiated stage advance. Blocked unless every exit gate of the current stage is satisfied."""
    _require_role(user, ROLES_HANDLING, "advance the EV stage")
    _assert_open(case)
    rule = ev_rule(db)
    if case.stage not in ADVANCE_ACTION_STAGES:
        raise DomainError(
            ErrorCode.STATE_CONFLICT,
            f"Stage {case.stage} is advanced only by its controlled action (technical sign-off or closure review)",
            status_code=409,
        )
    stage_owner = rule["stage_catalogue"][case.stage]["owner_role"]
    if stage_owner == "claims_manager" and user.role not in ROLES_MANAGER:
        raise DomainError(ErrorCode.NOT_AUTHORISED, f"Stage {case.stage} is owned by a claims manager; only a manager can advance it", status_code=403)
    blockers = evaluate_gates(db, case, rule)
    if blockers:
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            f"Stage gate(s) not satisfied for {case.stage}: " + "; ".join(b["message"] for b in blockers),
            status_code=409,
            details={"blockers": blockers, "stage": case.stage},
        )
    nxt = next_stage_after(case, rule)
    if not nxt or nxt == EVStage.CLOSED.value:
        raise DomainError(ErrorCode.STATE_CONFLICT, "No further stage is available; use the closure review", status_code=409)
    cur_idx = STAGE_ORDER.index(case.stage)
    skipped = STAGE_ORDER[cur_idx + 1 : STAGE_ORDER.index(nxt)]
    _enter_stage(db, case, claim, rule, nxt, user, note=_clean(note, max_len=300), skipped=skipped)
    _audit(db, case, user, "EV_STAGE_ADVANCED", {"to": nxt, "skipped_by_rule": skipped})
    return case


def close_case(db: Session, case: EVClaimCase, claim: Claim, user: UserContext, *, closure_notes: str) -> EVClaimCase:
    _require_role(user, ROLES_MANAGER, "close the EV case")
    _assert_open(case)
    rule = ev_rule(db)
    blockers = evaluate_gates(db, case, rule)
    nxt = next_stage_after(case, rule)
    if nxt != EVStage.CLOSED.value:
        blockers.append({"code": "PATH_INCOMPLETE", "message": f"The case is at {case.stage}; complete the remaining stages before closing."})
    if (case.recertification or {}).get("passed") is not True:
        blockers.append({"code": "RECERTIFICATION_REQUIRED", "message": "A passed post-repair recertification is required before closure."})
    if blockers:
        raise DomainError(
            ErrorCode.HUMAN_REVIEW_REQUIRED,
            "Closure blocked: " + "; ".join(b["message"] for b in blockers),
            status_code=409,
            details={"blockers": blockers},
        )
    if not closure_notes.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, "closure_notes are required", status_code=400)
    case.closure = {"by": _actor(user), "at": _iso(_utcnow()), "notes": _clean(closure_notes, max_len=800), "salvage_certificate_ref": _last_certificate(case)}
    _enter_stage(db, case, claim, rule, EVStage.CLOSED.value, user, note="EV closure review complete")
    _audit(db, case, user, "EV_CASE_CLOSED", {})
    emit_outbox_event(
        db,
        tenant_id=case.tenant_id,
        aggregate_id=claim.id,
        event_type="EVCaseClosed",
        payload={"ev_case_id": case.id},
        idempotency_key=f"EVCaseClosed:{case.id}",
    )
    return case


def _last_certificate(case: EVClaimCase) -> Optional[str]:
    for e in reversed((case.salvage or {}).get("events", [])):
        if e.get("certificate_ref"):
            return str(e["certificate_ref"])
    return None


# ----------------------------------------------------------------------------------------------
# Serialization and dashboards
# ----------------------------------------------------------------------------------------------
def customer_safety_view(case: EVClaimCase, rule: dict[str, Any]) -> dict[str, Any]:
    """What a policyholder may see: the operating hold and the safety instruction, nothing internal."""
    open_esc = open_escalations(case)
    level = None
    if open_esc:
        level = max((e["level"] for e in open_esc), key=lambda lv: _LEVEL_RANK[lv])
    return {
        "case_number": case.case_number,
        "stage_label": rule["stage_catalogue"][case.stage]["label"],
        "operation_status": case.operation_status,
        "do_not_drive_or_charge": case.operation_status != OPERATION_RELEASED,
        "safety_instruction": _safety_message(rule, level),
        "open_safety_escalation": bool(open_esc),
        "photo_only_clearance_allowed": False,
        "report_a_safety_concern_url": f"/api/v1/claims/{case.claim_id}/ev/safety-escalations",
    }


def serialize_ev_case(db: Session, case: EVClaimCase, claim: Claim, user: UserContext) -> dict[str, Any]:
    rule = ev_rule(db)
    if user.role == Role.POLICYHOLDER:
        return {"customer_view": customer_safety_view(case, rule)}
    path = stage_path(case, rule)
    blockers = evaluate_gates(db, case, rule)
    spec = rule["stage_catalogue"][case.stage]
    od_blockers = ev_od_hold_blockers(db, claim)
    tasks = (
        db.query(ClaimTask)
        .filter(ClaimTask.claim_id == claim.id, ClaimTask.task_type.startswith("ev_case_", autoescape=True))
        .order_by(ClaimTask.created_at.desc())
        .all()
    )
    return {
        "ev_case_id": case.id,
        "case_number": case.case_number,
        "claim_id": claim.id,
        "claim_number": claim.claim_number,
        "risk_class": case.risk_class,
        "risk_class_label": rule["risk_classes"][case.risk_class]["label"],
        "stage": case.stage,
        "stage_label": spec["label"],
        "queue": case.queue_name,
        "owner_role": spec["owner_role"],
        "stage_sla_hours": spec["sla_hours"],
        "stage_path": path,
        "stage_history": case.stage_history,
        "gate_blockers": blockers,
        "can_advance": not blockers and case.stage in ADVANCE_ACTION_STAGES,
        "next_stage": next_stage_after(case, rule),
        "operation_status": case.operation_status,
        "safe_to_operate": "not_determinable_from_photographs",
        "triage": case.triage,
        "safety_escalations": case.safety_escalations,
        "thermal_watch": case.thermal_watch,
        "recovery": case.recovery,
        "survey": case.survey,
        "diagnostics": case.diagnostics,
        "disposition": case.disposition,
        "benchmark": case.benchmark,
        "technical_signoff": case.technical_signoff,
        "settlement_clearance": case.settlement_clearance,
        "recertification": case.recertification,
        "salvage": _salvage_status(case, rule),
        "closure": case.closure,
        "advisory": build_advisory(db, case, claim, rule),
        "od_hold": {"held": bool(od_blockers), "blockers": od_blockers},
        "tasks": [
            {"id": t.id, "task_type": t.task_type, "status": t.status, "assigned_role": t.assigned_role, "queue": (t.metadata_json or {}).get("queue"), "due_at": _iso(t.due_at)}
            for t in tasks
        ],
        "controls": {
            "rule_id": rule["rule_id"],
            "rule_version": rule["version"],
            "photo_only_clearance_allowed": rule["controls"]["photo_only_clearance_allowed"],
            "ai_may_declare_vehicle_safe_to_operate": rule["controls"]["ai_may_declare_vehicle_safe_to_operate"],
            "ai_may_authorise_battery_repair_or_replacement": rule["controls"]["ai_may_authorise_battery_repair_or_replacement"],
            "shared_with_od_fast_track": rule["controls"]["shared_with_od_fast_track"],
            "separation_of_duties": rule["controls"]["separation_of_duties"],
        },
    }


def serialize_ev_summary(case: EVClaimCase) -> dict[str, Any]:
    return {
        "ev_case_id": case.id,
        "case_number": case.case_number,
        "risk_class": case.risk_class,
        "stage": case.stage,
        "queue": case.queue_name,
        "operation_status": case.operation_status,
        "open_safety_escalations": len(open_escalations(case)),
        "settlement_clearance": (case.settlement_clearance or {}).get("status", "not_granted"),
        "workflow_url": f"/api/v1/claims/{case.claim_id}/ev",
        "photo_only_clearance_allowed": False,
    }


def build_ev_dashboard(db: Session, tenant_id: str) -> dict[str, Any]:
    rule = ev_rule(db)
    cases = db.query(EVClaimCase).filter(EVClaimCase.tenant_id == tenant_id).all()
    now = _utcnow()
    by_stage = {s: 0 for s in STAGE_ORDER}
    by_class = {c: 0 for c in RISK_CLASS_ORDER}
    queues: dict[str, dict[str, Any]] = {}
    for stage, spec in rule["stage_catalogue"].items():
        queues.setdefault(spec["queue"], {"queue": spec["queue"], "stage": stage, "owner_role": spec["owner_role"], "open_cases": 0, "overdue": 0})
    holds = 0
    esc_open = 0
    for c in cases:
        by_stage[c.stage] = by_stage.get(c.stage, 0) + 1
        by_class[c.risk_class] = by_class.get(c.risk_class, 0) + 1
        if c.stage != EVStage.CLOSED.value:
            queues[c.queue_name]["open_cases"] += 1
        if c.operation_status != OPERATION_RELEASED:
            holds += 1
        esc_open += len(open_escalations(c))
    tasks = (
        db.query(ClaimTask)
        .filter(ClaimTask.tenant_id == tenant_id, ClaimTask.task_type.startswith("ev_case_", autoescape=True), ClaimTask.status == "open")
        .all()
    )
    for t in tasks:
        q = (t.metadata_json or {}).get("queue")
        due = _aware(t.due_at)
        if q in queues and due and due < now:
            queues[q]["overdue"] += 1
    safety_q = {"queue": "ev_safety_escalation", "stage": "ANY", "owner_role": rule["safety_escalation"]["owner_role"], "open_cases": esc_open, "overdue": 0}
    for t in tasks:
        due = _aware(t.due_at)
        if (t.metadata_json or {}).get("queue") == "ev_safety_escalation" and due and due < now:
            safety_q["overdue"] += 1
    return {
        "rule_id": rule["rule_id"],
        "total_cases": len(cases),
        "open_cases": len([c for c in cases if c.stage != EVStage.CLOSED.value]),
        "by_stage": by_stage,
        "by_risk_class": by_class,
        "queues": sorted(queues.values(), key=lambda q: STAGE_ORDER.index(q["stage"])) + [safety_q],
        "vehicles_on_hv_hold": holds,
        "open_safety_escalations": esc_open,
        "photo_only_clearance_allowed": rule["controls"]["photo_only_clearance_allowed"],
    }


def lifecycle_definition(db: Session) -> dict[str, Any]:
    rule = ev_rule(db)
    return {
        "rule_id": rule["rule_id"],
        "rule_version": rule["version"],
        "stages": [{"stage": s, **rule["stage_catalogue"][s]} for s in STAGE_ORDER],
        "risk_classes": rule["risk_classes"],
        "signals": rule["signals"],
        "impact_bands": rule["impact_bands"],
        "oem_diagnostics": rule["oem_diagnostics"],
        "disposition": rule["disposition"],
        "benchmarks": rule["benchmarks"],
        "salvage": rule["salvage"],
        "safety_escalation": rule["safety_escalation"],
        "controls": rule["controls"],
        "od_vs_ev": {
            "ordinary_vehicle_damage": ["Photo-led damage assessment", "Garage estimate", "Depreciation & deductible", "Settlement / cashless", "Payment"],
            "ev": [s.replace("_", " ").title() for s in STAGE_ORDER],
        },
    }
