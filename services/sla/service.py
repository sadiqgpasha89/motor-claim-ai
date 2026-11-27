"""Snapshot builder: evaluates a tenant's claims into SLA clocks, signals and breach predictions in one pass."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from services.claims.models import Claim, Provider
from services.sla.engine import SLAInstance, build_claim_instances
from services.sla.events import ClaimSLAContext, load_contexts
from services.sla.portfolio import SLASnapshot, compute_queue_pressure
from services.sla.predictor import (
    ClaimSignals,
    SLAPrediction,
    build_signals,
    latest_doc_request_times,
    predict_instance,
)
from services.sla.rules import SLARulesService


def _candidate_providers(kind: str, sig: ClaimSignals, providers: dict[str, Provider], limit: int = 3) -> list[dict[str, Any]]:
    """Same-city, verified, available providers with clear headroom: safe *candidates* for a human-approved reassignment."""
    current = (sig.surveyor if kind == "surveyor" else sig.garage) or {}
    city = (current.get("city") or "").lower()
    out: list[dict[str, Any]] = []
    for p in providers.values():
        if p.provider_type != kind or p.id == current.get("id") or not p.is_available:
            continue
        if kind == "surveyor" and p.licence_status != "verified":
            continue
        if kind == "garage" and not p.is_network:
            continue
        if city and (p.city or "").lower() != city:
            continue
        if sig.ev_involved and not p.ev_capable:
            continue
        ratio = float(p.active_load or 0) / max(int(p.max_capacity or 1), 1)
        if ratio > 0.65:
            continue
        out.append({"id": p.id, "name": p.name, "city": p.city, "load_ratio": round(ratio, 3), "quality_score": float(p.quality_score or 0)})
    out.sort(key=lambda r: (r["load_ratio"], -r["quality_score"]))
    return out[:limit]


def build_snapshot(
    db: Session,
    tenant_id: str,
    *,
    now: datetime | None = None,
    claim_ids: list[str] | None = None,
    rules: SLARulesService | None = None,
) -> SLASnapshot:
    now = now or datetime.now(timezone.utc)
    rules = rules or SLARulesService.load(db)
    q = db.query(Claim).filter(Claim.tenant_id == tenant_id)
    if claim_ids:
        q = q.filter(Claim.id.in_(claim_ids))
    claims = q.all()
    contexts = load_contexts(db, claims, now)
    providers = {p.id: p for p in db.query(Provider).filter(Provider.tenant_id == tenant_id).all()}

    instances: list[SLAInstance] = []
    for ctx in contexts.values():
        instances.extend(build_claim_instances(ctx, rules))

    queue_pressure = compute_queue_pressure(instances, contexts, now)
    doc_requests = latest_doc_request_times(db, list(contexts))
    signals: dict[str, ClaimSignals] = {}
    for cid, ctx in contexts.items():
        sig = build_signals(ctx, doc_requests)
        sig.queue_pressure = queue_pressure.get(ctx.claim.queue_name, {}).get("pressure", 0.0)
        for kind in ("surveyor", "garage"):
            owner = sig.surveyor if kind == "surveyor" else sig.garage
            if owner and owner["load_ratio"] >= float(rules.risk_model.get("overload_ratio", 0.8)) - 0.1:
                sig.reassign_candidates[kind] = _candidate_providers(kind, sig, providers)
        signals[cid] = sig

    predictions: list[SLAPrediction] = []
    for inst in instances:
        if not inst.is_open:
            continue
        pred = predict_instance(inst, signals[inst.claim_id], rules, now)
        if pred is not None:
            predictions.append(pred)

    return SLASnapshot(
        now=now,
        rules=rules,
        contexts=contexts,
        instances=instances,
        signals=signals,
        predictions=predictions,
        queue_pressure=queue_pressure,
        providers=providers,
    )


def claim_sla_view(snap: SLASnapshot, claim_id: str) -> dict[str, Any]:
    """Everything the UI and the agent need for one claim: clocks, predictions, signals."""
    ctx: ClaimSLAContext | None = snap.contexts.get(claim_id)
    return {
        "claim_id": claim_id,
        "claim_number": ctx.claim.claim_number if ctx else None,
        "claim_type": ctx.claim.claim_type if ctx else None,
        "catalogue_version": snap.rules.catalogue_version,
        "instances": [i.to_dict() for i in snap.instances_for(claim_id)],
        "predictions": [p.to_dict() for p in snap.predictions_for(claim_id)],
        "signals": snap.signals[claim_id].to_dict() if claim_id in snap.signals else None,
    }


def agent_inputs(snap: SLASnapshot, claim_id: str) -> dict[str, Any]:
    """Minimised, PII-free facts handed to the SLA agent (instances + signals; the agent re-predicts and plans)."""
    sig = snap.signals[claim_id]
    return {
        "sla_inputs": {
            "instances": [i.to_dict() for i in snap.instances_for(claim_id)],
            "signals": sig.to_dict(),
            "now": snap.now.isoformat(),
        },
        "queue_context": snap.queue_pressure.get(sig.queue),
    }
