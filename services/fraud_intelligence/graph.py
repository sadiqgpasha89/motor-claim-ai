"""Weighted fraud relationship graph with explainable ring detection.

The graph links claims through shared entities. Each link type has a weight from
IN-INTELLIGENCE-2026. A high network score opens an SIU lead. It never rejects a claim.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from itertools import combinations
from typing import Any

from sqlalchemy.orm import Session

from services.claims.models import Claim, Evidence, Payment
from services.rules_engine.intelligence import intelligence_controls, intelligence_rule_version


def _link_keys(db: Session, claims: list[Claim], window_days: int) -> dict[tuple[str, str], set[str]]:
    """Return {(link_type, entity_key): {claim_id}} for the given claims."""
    index: dict[tuple[str, str], set[str]] = defaultdict(set)
    by_id = {c.id: c for c in claims}
    for c in claims:
        index[("SHARED_VEHICLE", c.vehicle_reg_input)].add(c.id)
        if c.customer_id:
            index[("SHARED_CUSTOMER", c.customer_id)].add(c.id)
        if c.assigned_garage_id:
            index[("SHARED_GARAGE", c.assigned_garage_id)].add(c.id)
        if c.assigned_surveyor_id:
            index[("SHARED_SURVEYOR", c.assigned_surveyor_id)].add(c.id)
    for ev in db.query(Evidence).filter(Evidence.claim_id.in_(list(by_id))).all():
        index[("SHARED_EVIDENCE_CHECKSUM", ev.sha256)].add(ev.claim_id)
    for p in db.query(Payment).filter(Payment.claim_id.in_(list(by_id))).all():
        index[("SHARED_BANK_ACCOUNT", p.bank_account_masked)].add(p.claim_id)
    # Same place within the window. Location text is the key and dates are checked per pair.
    by_loc: dict[str, list[Claim]] = defaultdict(list)
    for c in claims:
        by_loc[(c.incident_location or "").strip().lower()].append(c)
    for loc, group in by_loc.items():
        if not loc:
            continue
        for a, b in combinations(group, 2):
            if abs(a.incident_at - b.incident_at) <= timedelta(days=window_days):
                index[("SHARED_LOCATION_WINDOW", loc)].update({a.id, b.id})
    return {k: v for k, v in index.items() if len(v) >= 2}


def build_weighted_graph(db: Session, claim: Claim) -> dict[str, Any]:
    ctl = intelligence_controls()["fraud_graph"]
    weights = {k: float(v) for k, v in ctl["edge_weights"].items()}
    claims = db.query(Claim).filter(Claim.tenant_id == claim.tenant_id).all()
    links = _link_keys(db, claims, int(ctl["location_window_days"]))
    num = {c.id: c.claim_number for c in claims}

    pair_edges: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for (ltype, key), ids in links.items():
        for a, b in combinations(sorted(ids), 2):
            pair_edges[(a, b)].append({"link_type": ltype, "weight": weights.get(ltype, 0.1), "entity": key[:12]})

    adj: dict[str, set[str]] = defaultdict(set)
    edges: list[dict[str, Any]] = []
    for (a, b), reasons in pair_edges.items():
        # Combine independent links as 1 - product(1 - w). Repeated weak links add up without passing 1.
        miss = 1.0
        for r in reasons:
            miss *= 1.0 - r["weight"]
        edges.append({"from": num[a], "to": num[b], "weight": round(1.0 - miss, 3), "reasons": reasons})
        adj[a].add(b)
        adj[b].add(a)

    # Connected component that holds this claim.
    component: set[str] = set()
    stack = [claim.id] if claim.id in adj else []
    while stack:
        n = stack.pop()
        if n in component:
            continue
        component.add(n)
        stack.extend(adj[n] - component)

    comp_edges = [e for e in edges if e["from"] in {num[i] for i in component} and e["to"] in {num[i] for i in component}]
    k = len(component)
    max_pairs = k * (k - 1) / 2
    density = round(sum(e["weight"] for e in comp_edges) / max_pairs, 3) if max_pairs else 0.0
    ring = k >= int(ctl["ring_min_claims"]) and density >= float(ctl["ring_min_weighted_density"])

    own = [e for e in edges if num[claim.id] in (e["from"], e["to"])]
    network_score = round(max((e["weight"] for e in own), default=0.0), 3)
    if ring:
        network_score = round(max(network_score, density), 3)
    explanation: list[str] = []
    for e in sorted(own, key=lambda e: -e["weight"])[:5]:
        other = e["to"] if e["from"] == num[claim.id] else e["from"]
        explanation.append(f"{other}: " + ", ".join(r["link_type"] for r in e["reasons"]) + f" (weight {e['weight']})")
    if ring:
        explanation.append(f"{k} claims form a dense cluster (weighted density {density}). Review as a possible ring.")

    return {
        "claim_number": claim.claim_number,
        "nodes": [{"id": num[i], "is_focus": i == claim.id} for i in sorted(component | {claim.id}, key=lambda i: num[i])],
        "edges": comp_edges,
        "component_size": k or 1,
        "weighted_density": density,
        "ring_suspected": ring,
        "network_score": network_score,
        "siu_case_recommended": network_score >= float(ctl["siu_case_threshold"]),
        "explanation": explanation,
        "never_auto_reject": bool(ctl["never_auto_reject"]),
        "rule_version": intelligence_rule_version(),
        "disclaimer": "Links show shared data. They do not prove fraud. SIU reviews every lead.",
    }
