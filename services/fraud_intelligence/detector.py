from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from services.claims.models import Claim, Estimate, Evidence, Policy


def run_fraud_and_anomaly_checks(db: Session, claim: Claim) -> list[dict[str, Any]]:
    indicators: list[dict[str, Any]] = []

    if claim.policy_id:
        policy = db.query(Policy).filter(Policy.id == claim.policy_id).first()
        if policy:
            p_start = policy.period_start.replace(tzinfo=timezone.utc) if policy.period_start.tzinfo is None else policy.period_start
            c_inc = claim.incident_at.replace(tzinfo=timezone.utc) if claim.incident_at.tzinfo is None else claim.incident_at
            days_since_inception = (c_inc - p_start).days
            if 0 <= days_since_inception <= 15:
                indicators.append(
                    {
                        "indicator_code": "FRD-EARLY-INCIDENT",
                        "title": f"Incident within {days_since_inception} days of policy inception",
                        "severity_band": "medium",
                        "confidence": Decimal("0.720"),
                        "evidence_summary": f"Policy started {p_start.date()}, incident occurred {c_inc.date()}.",
                        "benign_explanation": "Genuine accidents frequently happen shortly after purchasing or renewing a vehicle policy.",
                        "recommended_action": "Verify break-in inspection photos / prior policy NCB history before settlement.",
                        "entity_links": [
                            {"type": "policy", "id": policy.policy_number},
                            {"type": "vehicle", "id": claim.vehicle_reg_input},
                        ],
                    }
                )

    estimates = db.query(Estimate).filter(Estimate.claim_id == claim.id).all()
    for est in estimates:
        if est.anomalies:
            indicators.append(
                {
                    "indicator_code": "FRD-EST-ANOMALY",
                    "title": f"Repair estimate contains {len(est.anomalies)} pricing/duplicate anomaly(s)",
                    "severity_band": "low",
                    "confidence": Decimal("0.680"),
                    "evidence_summary": "; ".join(a.get("message", "") for a in est.anomalies[:3]),
                    "benign_explanation": "Garage billing clerks commonly copy-paste labour/part lines accidentally in draft estimates.",
                    "recommended_action": "Review estimate lines with garage and surveyor; deduct duplicate before approval.",
                    "entity_links": [
                        {"type": "estimate", "id": est.id},
                        {"type": "garage", "id": est.garage_id or "unassigned"},
                    ],
                }
            )

    evidences = db.query(Evidence).filter(Evidence.claim_id == claim.id).all()
    for ev in evidences:
        other_ev = (
            db.query(Evidence)
            .filter(
                Evidence.tenant_id == claim.tenant_id,
                Evidence.sha256 == ev.sha256,
                Evidence.claim_id != claim.id,
            )
            .first()
        )
        if other_ev:
            indicators.append(
                {
                    "indicator_code": "FRD-IMG-HASH-REUSE",
                    "title": "Uploaded evidence file matches checksum on another claim",
                    "severity_band": "high",
                    "confidence": Decimal("0.860"),
                    "evidence_summary": f"File '{ev.filename}' (sha256 {ev.sha256[:12]}...) also appears on claim {other_ev.claim_id}.",
                    "benign_explanation": "Customer or garage may have accidentally re-attached a policy PDF or prior repair photo from the same phone folder.",
                    "recommended_action": "SIU analyst to inspect metadata and compare incident timestamps with prior claim.",
                    "entity_links": [
                        {"type": "evidence_sha256", "id": ev.sha256[:16]},
                        {"type": "related_claim", "id": other_ev.claim_id},
                    ],
                }
            )

    if claim.vehicle_id:
        prior_count = (
            db.query(Claim)
            .filter(
                Claim.tenant_id == claim.tenant_id,
                Claim.vehicle_id == claim.vehicle_id,
                Claim.id != claim.id,
            )
            .count()
        )
        if prior_count >= 2:
            indicators.append(
                {
                    "indicator_code": "FRD-REPEAT-VEHICLE",
                    "title": f"Vehicle has {prior_count} prior claims in tenant history",
                    "severity_band": "medium",
                    "confidence": Decimal("0.650"),
                    "evidence_summary": f"Vehicle {claim.vehicle_reg_input} linked to {prior_count + 1} total claims.",
                    "benign_explanation": "High-mileage commercial/urban commuter vehicles may legitimately suffer multiple minor incidents.",
                    "recommended_action": "Cross-check damaged panels against prior settled claims to ensure no overlap.",
                    "entity_links": [{"type": "vehicle", "id": claim.vehicle_reg_input}],
                }
            )

    return indicators


def build_entity_relationship_graph(db: Session, claim: Claim) -> dict[str, Any]:
    nodes = [
        {"id": f"claim:{claim.claim_number}", "type": "claim", "label": claim.claim_number},
        {"id": f"veh:{claim.vehicle_reg_input}", "type": "vehicle", "label": claim.vehicle_reg_input},
    ]
    edges = [
        {"from": f"claim:{claim.claim_number}", "to": f"veh:{claim.vehicle_reg_input}", "relation": "INSURED_VEHICLE"}
    ]

    if claim.assigned_garage_id:
        nodes.append({"id": f"garage:{claim.assigned_garage_id}", "type": "garage", "label": f"Garage {claim.assigned_garage_id[:8]}"})
        edges.append({"from": f"claim:{claim.claim_number}", "to": f"garage:{claim.assigned_garage_id}", "relation": "REPAIR_AT"})

    if claim.customer_id:
        nodes.append({"id": f"cust:{claim.customer_id}", "type": "customer_token", "label": f"Insured Token {claim.customer_id[:8]}"})
        edges.append({"from": f"cust:{claim.customer_id}", "to": f"claim:{claim.claim_number}", "relation": "FILED_BY"})

    related = (
        db.query(Claim)
        .filter(
            Claim.tenant_id == claim.tenant_id,
            Claim.id != claim.id,
            (Claim.vehicle_reg_input == claim.vehicle_reg_input) | (Claim.customer_id == claim.customer_id),
        )
        .limit(5)
        .all()
    )
    for rel in related:
        nodes.append({"id": f"claim:{rel.claim_number}", "type": "related_claim", "label": rel.claim_number})
        edges.append({"from": f"veh:{claim.vehicle_reg_input}", "to": f"claim:{rel.claim_number}", "relation": "SHARED_ENTITY"})

    return {"nodes": nodes, "edges": edges, "generated_at": datetime.now(timezone.utc).isoformat()}
