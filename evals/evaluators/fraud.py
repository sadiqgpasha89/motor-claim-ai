"""Fraud Intelligence: signal precision / recall / false-positive rate and the never-reject guarantee."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from evals.core import AgentEval, Case, CaseResult, Checks, load_dataset
from evals.db_scenarios import (
    NOW,
    scenario_db,
    seed_claim,
    seed_customer,
    seed_estimate,
    seed_evidence,
    seed_policy,
    seed_tenant,
    seed_vehicle,
)
from evals.harness import dump, run_agent, took_adverse_decision
from evals.metrics import precision_recall_f1, r4, safe_div
from services.fraud_intelligence.detector import build_entity_relationship_graph, run_fraud_and_anomaly_checks

AGENT = "fraud_intelligence"
ALL_CODES = (
    "FRD-EARLY-INCIDENT",
    "FRD-EST-ANOMALY",
    "FRD-IMG-HASH-REUSE",
    "FRD-REPEAT-VEHICLE",
    "FRD-GARAGE-ANOMALY-NETWORK",
    "FRD-ENTITY-RING-CLUSTER",
)
_INCIDENT_AT = NOW - timedelta(days=2)


def build_scenario(db: Session, spec: dict[str, Any]) -> Any:
    """Materialise a declarative scenario spec into rows; returns the claim under test."""
    tenant = seed_tenant(db)
    cust = seed_customer(db, tenant)
    veh = seed_vehicle(db, tenant, "MH02AB1234")
    pol = None
    if not spec.get("no_policy"):
        pol = seed_policy(db, tenant, cust, veh)
        pol.period_start = _INCIDENT_AT - timedelta(days=int(spec.get("days_since_inception", 200)))
        pol.period_end = pol.period_start + timedelta(days=365)
        db.commit()
    garage_id = "garage-eval-0001" if spec.get("garage_disputed_peers") else None
    overrides: dict[str, Any] = {"incident_at": _INCIDENT_AT, "assigned_garage_id": garage_id}
    if "estimated_loss_inr" in spec:
        overrides["estimated_loss_inr"] = Decimal(spec["estimated_loss_inr"])
    if "incident_description" in spec:
        overrides["incident_description"] = spec["incident_description"]
    claim = seed_claim(db, tenant, cust, veh, pol, **overrides)

    for i in range(int(spec.get("prior_vehicle_claims", 0))):
        other_cust = seed_customer(db, tenant, f"Other {i}")
        seed_claim(db, tenant, other_cust, veh, None, vehicle_reg_input=f"KA01ZZ{i:04d}")
    for i in range(int(spec.get("prior_customer_claims", 0))):
        other_veh = seed_vehicle(db, tenant, f"DL01CC{i:04d}")
        seed_claim(db, tenant, cust, other_veh, None, vehicle_reg_input=other_veh.registration_number)
    for i in range(int(spec.get("garage_disputed_peers", 0))):
        peer_cust = seed_customer(db, tenant, f"Peer {i}")
        peer_veh = seed_vehicle(db, tenant, f"TN01PP{i:04d}")
        peer = seed_claim(db, tenant, peer_cust, peer_veh, None, vehicle_reg_input=peer_veh.registration_number)
        seed_estimate(db, tenant, peer, garage_id=garage_id, status="disputed")
    if spec.get("shared_evidence_hash"):
        sha = "ab" * 32
        other_cust = seed_customer(db, tenant, "Reuse")
        other_veh = seed_vehicle(db, tenant, "GJ01RR0001")
        other = seed_claim(db, tenant, other_cust, other_veh, None, vehicle_reg_input=other_veh.registration_number)
        seed_evidence(db, tenant, other, sha=sha, filename="prior.jpg")
        seed_evidence(db, tenant, claim, sha=sha, filename="front.jpg")
    if spec.get("estimate_anomalies"):
        seed_estimate(
            db,
            tenant,
            claim,
            anomalies=[
                {"type": "duplicate_line", "message": f"anomaly {n}"} for n in range(int(spec["estimate_anomalies"]))
            ],
        )
    return claim


def detect(spec: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with scenario_db() as db:
        claim = build_scenario(db, spec)
        indicators = run_fraud_and_anomaly_checks(db, claim)
        graph = build_entity_relationship_graph(db, claim)
    # Decimals / datetimes are made JSON-safe exactly as they would be crossing the agent boundary.
    return json.loads(json.dumps(indicators, default=str)), json.loads(json.dumps(graph, default=str))


def evaluate_case(case: Case) -> tuple[Checks, dict[str, Any]]:
    indicators, graph = detect(case.input)
    resp = run_agent(AGENT, {"indicators": indicators, "entity_graph": graph})
    got = {i["indicator_code"] for i in indicators}
    want = set(case.expected["codes"])
    ck = Checks()
    ck.eq("indicator_codes", sorted(got), sorted(want))
    expect_flagged = bool(want)
    ck.eq("agent_status", resp.status.value, "needs_human" if expect_flagged else "completed")
    ck.eq(
        "agent_routing",
        resp.decision.routing_outcome if resp.decision else None,
        "refer_to_siu_investigation" if expect_flagged else "siu_clean_pass",
    )
    ck.eq("fraud_score_can_reject", resp.result["fraud_score_can_reject"], False)
    ck.expect("no_adverse_decision", not took_adverse_decision(resp))
    ck.expect(
        "score_in_range",
        Decimal("0") <= Decimal(resp.result["fraud_signal_score"]) <= Decimal("1"),
        observed=resp.result["fraud_signal_score"],
    )
    if expect_flagged:
        tasks = [a for a in resp.actions_executed if a.action_type == "create_claim_task"]
        ck.expect(
            "siu_task",
            any("siu_investigator" in a.summary or a.payload.get("assigned_role") == "siu_investigator" for a in tasks),
            observed=[a.summary for a in tasks],
        )
    for ind in indicators:
        ck.expect(
            f"explainable[{ind['indicator_code']}]",
            bool(ind.get("benign_explanation")) and bool(ind.get("recommended_action")),
        )
    ck.expect("response_serialisable", bool(dump(resp)))
    return ck, {"got": got, "want": want}


def evaluate() -> AgentEval:
    ds = load_dataset("fraud")
    results: list[CaseResult] = []
    tp = fp = fn = 0
    benign_cases = benign_flagged = 0
    never_reject = never_reject_total = 0

    for case in ds.cases:
        ck, sets = evaluate_case(case)
        got, want = sets["got"], sets["want"]
        tp += len(got & want)
        fp += len(got - want)
        fn += len(want - got)
        if not want:
            benign_cases += 1
            benign_flagged += int(bool(got))
        never_reject_total += 1
        never_reject += int(
            ck.items.get("fraud_score_can_reject", False) and ck.items.get("no_adverse_decision", False)
        )
        results.append(ck.result(case, AGENT))

    prf = precision_recall_f1(tp, fp, fn)
    metrics = {
        "signal_precision": r4(prf["precision"]),
        "signal_recall": r4(prf["recall"]),
        "false_positive_rate": r4(safe_div(benign_flagged, benign_cases, default=0.0)),
        "never_reject_compliance": r4(safe_div(never_reject, never_reject_total)),
    }
    return AgentEval(agent=AGENT, metrics=metrics, cases=results)
