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
                        "signal_factors": [
                            {"feature": "days_since_policy_inception", "value": days_since_inception, "weight": 0.42},
                            {"feature": "estimated_loss_inr", "value": str(claim.estimated_loss_inr), "weight": 0.30},
                        ],
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
                    "signal_factors": [
                        {"feature": "estimate_anomaly_count", "value": len(est.anomalies), "weight": 0.55},
                        {"feature": "claimed_vs_approved_delta", "value": str(Decimal(str(est.total_claimed_inr)) - Decimal(str(est.total_approved_inr))), "weight": 0.45},
                    ],
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
                    "signal_factors": [
                        {"feature": "sha256_cross_claim_collision", "value": ev.sha256[:12], "weight": 0.86},
                    ],
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
                    "signal_factors": [
                        {"feature": "vehicle_prior_claim_count", "value": prior_count, "weight": 0.65},
                    ],
                    "entity_links": [{"type": "vehicle", "id": claim.vehicle_reg_input}],
                }
            )

    if claim.assigned_garage_id:
        garage_disputed_count = (
            db.query(Estimate)
            .filter(
                Estimate.tenant_id == claim.tenant_id,
                Estimate.garage_id == claim.assigned_garage_id,
                Estimate.claim_id != claim.id,
                Estimate.status == "disputed",
            )
            .count()
        )
        if garage_disputed_count >= 2:
            indicators.append(
                {
                    "indicator_code": "FRD-GARAGE-ANOMALY-NETWORK",
                    "title": f"Assigned garage linked to {garage_disputed_count} other disputed estimates",
                    "severity_band": "medium",
                    "confidence": Decimal("0.740"),
                    "evidence_summary": f"Garage {claim.assigned_garage_id} shows repeated rate variance or duplicate lines across tenant claims.",
                    "benign_explanation": "High-volume cashless repair hubs often submit provisional OEM estimates pending parts availability.",
                    "recommended_action": "Perform line-by-line parts invoice & salvage part return check at garage audit.",
                    "signal_factors": [
                        {"feature": "garage_disputed_estimates_peer_count", "value": garage_disputed_count, "weight": 0.74},
                    ],
                    "entity_links": [
                        {"type": "garage", "id": claim.assigned_garage_id},
                        {"type": "claim", "id": claim.claim_number},
                    ],
                }
            )

    if claim.customer_id:
        related_cluster_count = (
            db.query(Claim)
            .filter(
                Claim.tenant_id == claim.tenant_id,
                Claim.id != claim.id,
                (Claim.customer_id == claim.customer_id) | (Claim.vehicle_reg_input == claim.vehicle_reg_input),
            )
            .count()
        )
        if related_cluster_count >= 3 and not any(i["indicator_code"] == "FRD-REPEAT-VEHICLE" for i in indicators):
            indicators.append(
                {
                    "indicator_code": "FRD-ENTITY-RING-CLUSTER",
                    "title": f"Multi-claim entity network cluster ({related_cluster_count} connected claims)",
                    "severity_band": "medium",
                    "confidence": Decimal("0.690"),
                    "evidence_summary": f"Customer/vehicle entity graph links {related_cluster_count + 1} claims in tenant.",
                    "benign_explanation": "Multi-vehicle household or corporate fleet customers legitimately file multiple claims under one account.",
                    "recommended_action": "Verify distinct incident dates, driver licences, and non-overlapping damage zones.",
                    "signal_factors": [
                        {"feature": "entity_cluster_degree", "value": related_cluster_count + 1, "weight": 0.69},
                    ],
                    "entity_links": [
                        {"type": "customer_token", "id": claim.customer_id},
                        {"type": "vehicle", "id": claim.vehicle_reg_input},
                    ],
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
    suspicious_connections: list[dict[str, Any]] = []

    if claim.assigned_garage_id:
        nodes.append({"id": f"garage:{claim.assigned_garage_id}", "type": "garage", "label": f"Garage {claim.assigned_garage_id[:8]}"})
        edges.append({"from": f"claim:{claim.claim_number}", "to": f"garage:{claim.assigned_garage_id}", "relation": "REPAIR_AT"})

    if claim.assigned_surveyor_id:
        nodes.append({"id": f"surv:{claim.assigned_surveyor_id}", "type": "surveyor", "label": f"Surveyor {claim.assigned_surveyor_id[:8]}"})
        edges.append({"from": f"claim:{claim.claim_number}", "to": f"surv:{claim.assigned_surveyor_id}", "relation": "SURVEYED_BY"})

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
        .limit(8)
        .all()
    )
    for rel in related:
        nodes.append({"id": f"claim:{rel.claim_number}", "type": "related_claim", "label": rel.claim_number})
        edges.append({"from": f"veh:{claim.vehicle_reg_input}", "to": f"claim:{rel.claim_number}", "relation": "SHARED_ENTITY"})
        if claim.assigned_garage_id and rel.assigned_garage_id == claim.assigned_garage_id:
            suspicious_connections.append(
                {
                    "pattern": "SHARED_VEHICLE_AND_GARAGE",
                    "related_claim": rel.claim_number,
                    "shared_entity": claim.assigned_garage_id,
                    "note": "Same vehicle/customer and repair garage across multiple claims (verify non-overlapping repair panels).",
                }
            )

    evidences = db.query(Evidence).filter(Evidence.claim_id == claim.id).all()
    for ev in evidences:
        other = (
            db.query(Evidence)
            .filter(
                Evidence.tenant_id == claim.tenant_id,
                Evidence.sha256 == ev.sha256,
                Evidence.claim_id != claim.id,
            )
            .first()
        )
        if other:
            nodes.append({"id": f"hash:{ev.sha256[:12]}", "type": "evidence_hash", "label": f"SHA256 {ev.sha256[:10]}"})
            edges.append({"from": f"claim:{claim.claim_number}", "to": f"hash:{ev.sha256[:12]}", "relation": "EVIDENCE_HASH_REUSE"})
            suspicious_connections.append(
                {
                    "pattern": "SHARED_EVIDENCE_CHECKSUM",
                    "related_claim_id": other.claim_id,
                    "sha256_prefix": ev.sha256[:12],
                    "note": "Identical file checksum detected across distinct claims.",
                }
            )

    return {
        "nodes": nodes,
        "edges": edges,
        "suspicious_connections": suspicious_connections,
        "network_risk_summary": {
            "connected_claims": len(related),
            "suspicious_link_count": len(suspicious_connections),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
