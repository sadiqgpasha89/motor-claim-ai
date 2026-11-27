"""Portfolio view: SLA dashboard, and the operational insights the predictive agent reasons over.

Answers five questions: which claims will breach, which garages cause delay, which surveyors are overloaded,
which documents delay processing, and which queues are bottlenecked.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from services.claims.models import Provider
from services.sla.engine import SLAInstance
from services.sla.events import ClaimSLAContext
from services.sla.predictor import ClaimSignals, SLAPrediction
from services.sla.rules import SLA_METRICS, SLARulesService

BAND_ORDER = {"breached": 0, "critical": 1, "at_risk": 2, "watch": 3, "on_track": 4}


@dataclass
class SLASnapshot:
    now: datetime
    rules: SLARulesService
    contexts: dict[str, ClaimSLAContext]
    instances: list[SLAInstance]
    signals: dict[str, ClaimSignals]
    predictions: list[SLAPrediction]
    queue_pressure: dict[str, dict[str, Any]] = field(default_factory=dict)
    providers: dict[str, Provider] = field(default_factory=dict)

    def predictions_for(self, claim_id: str) -> list[SLAPrediction]:
        return [p for p in self.predictions if p.claim_id == claim_id]

    def instances_for(self, claim_id: str) -> list[SLAInstance]:
        return [i for i in self.instances if i.claim_id == claim_id]


def _clip(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def compute_queue_pressure(instances: list[SLAInstance], contexts: dict[str, ClaimSLAContext], now: datetime) -> dict[str, dict[str, Any]]:
    """Queue pressure = 60% share of open clocks that are late (>=75% consumed or breached) + 40% overdue-task density."""
    by_queue: dict[str, list[SLAInstance]] = defaultdict(list)
    for inst in instances:
        if inst.is_open:
            by_queue[inst.queue].append(inst)
    out: dict[str, dict[str, Any]] = {}
    for queue, items in by_queue.items():
        claim_ids = {i.claim_id for i in items}
        late = [i for i in items if i.status == "breached" or i.consumed_pct >= 75]
        overdue_tasks = 0
        for cid in claim_ids:
            ctx = contexts.get(cid)
            if ctx is None:
                continue
            for t in ctx.tasks:
                if t.status in {"open", "in_progress"} and t.due_at is not None:
                    due = t.due_at.replace(tzinfo=now.tzinfo) if t.due_at.tzinfo is None else t.due_at
                    if due < now:
                        overdue_tasks += 1
        late_share = len(late) / len(items)
        overdue_density = _clip(overdue_tasks / max(len(claim_ids), 1))
        pressure = round(_clip(0.6 * late_share + 0.4 * overdue_density), 3)
        late_by_metric: dict[str, int] = defaultdict(int)
        for i in late:
            late_by_metric[i.metric] += 1
        out[queue] = {
            "queue": queue,
            "open_claims": len(claim_ids),
            "open_clocks": len(items),
            "late_clocks": len(late),
            "overdue_tasks": overdue_tasks,
            "late_share": round(late_share, 3),
            "pressure": pressure,
            "dominant_metric": max(late_by_metric, key=late_by_metric.get) if late_by_metric else None,  # type: ignore[arg-type]
        }
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------------------------------------------------
def _pctl(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return round(ordered[idx], 2)


def build_dashboard(snap: SLASnapshot) -> dict[str, Any]:
    pred_by_key = {(p.claim_id, p.sla_id): p for p in snap.predictions}
    rows: list[dict[str, Any]] = []
    now = snap.now
    for metric in SLA_METRICS:
        items = [i for i in snap.instances if i.metric == metric]
        open_items = [i for i in items if i.is_open]
        closed = [i for i in items if not i.is_open]
        met = [i for i in closed if i.status == "met"]
        late = [i for i in closed if i.status == "met_late"]
        breached_open = [i for i in open_items if i.status == "breached"]
        paused = [i for i in open_items if i.status == "paused"]
        preds = [pred_by_key[(i.claim_id, i.sla_id)] for i in open_items if (i.claim_id, i.sla_id) in pred_by_key]
        at_risk = [p for p in preds if p.risk_band in {"at_risk", "critical"}]
        judged = len(met) + len(late) + len(breached_open)
        durations = [i.active_elapsed_hours for i in closed]
        versions = sorted({i.rule_version for i in items})
        rules_in_force = sorted({f"{r.sla_id}@{r.rule_version}" for r in snap.rules.rules if r.metric == metric and r.effective_at(now)})
        sample_rule = next((r for r in snap.rules.rules if r.metric == metric and r.effective_at(now)), None)
        inferred = sum(1 for i in items if "inferred" in i.event_sources.values())
        rows.append(
            {
                "metric": metric,
                "title": sample_rule.title if sample_rule else metric.replace("_", " ").title(),
                "target_label": sample_rule.target_label if sample_rule else "Configurable",
                "deadline_hours": round(sample_rule.deadline_hours, 3) if sample_rule else None,
                "regulatory_hours": sample_rule.regulatory_hours if sample_rule else None,
                "rules_in_force": rules_in_force,
                "rule_versions_observed": versions,
                "total_clocks": len(items),
                "open": len(open_items),
                "paused": len(paused),
                "completed": len(closed),
                "met": len(met),
                "met_late": len(late),
                "breached_open": len(breached_open),
                "predicted_at_risk": len(at_risk),
                "attainment_pct": round(len(met) / judged * 100, 1) if judged else None,
                "median_hours": round(statistics.median(durations), 2) if durations else None,
                "p90_hours": _pctl(durations, 0.9),
                "avg_consumed_pct_open": round(statistics.fmean(i.consumed_pct for i in open_items), 1) if open_items else None,
                "penalty_exposure_inr": str(sum((Decimal(i.penalty_accrued_inr) for i in open_items), Decimal("0.00"))),
                "inferred_event_share": round(inferred / len(items), 2) if items else 0.0,
            }
        )
    open_all = [i for i in snap.instances if i.is_open]
    band_counts: dict[str, int] = defaultdict(int)
    for p in snap.predictions:
        band_counts[p.risk_band] += 1
    ranked = sorted(snap.predictions, key=lambda p: (BAND_ORDER.get(p.risk_band, 9), -p.breach_probability))
    return {
        "generated_at": now.isoformat(),
        "catalogue_version": snap.rules.catalogue_version,
        "model_id": snap.rules.risk_model.get("model_id"),
        "totals": {
            "claims_evaluated": len(snap.contexts),
            "open_clocks": len(open_all),
            "breached_now": sum(1 for i in open_all if i.status == "breached"),
            "predicted_breaches": band_counts["at_risk"] + band_counts["critical"],
            "paused_clocks": sum(1 for i in open_all if i.status == "paused"),
        },
        "risk_band_counts": {k: band_counts.get(k, 0) for k in ("breached", "critical", "at_risk", "watch", "on_track")},
        "metrics": rows,
        "top_risks": [p.to_dict() for p in ranked[:8]],
    }


# ---------------------------------------------------------------------------------------------------------------------
# Operational insights
# ---------------------------------------------------------------------------------------------------------------------
def claim_risk_ranking(snap: SLASnapshot, limit: int = 25) -> list[dict[str, Any]]:
    """Which claims are likely to breach: worst clock per claim, ranked."""
    inst_by_key = {(i.claim_id, i.sla_id): i for i in snap.instances}
    best: dict[str, SLAPrediction] = {}
    for p in snap.predictions:
        cur = best.get(p.claim_id)
        if cur is None or (BAND_ORDER.get(p.risk_band, 9), -p.breach_probability) < (BAND_ORDER.get(cur.risk_band, 9), -cur.breach_probability):
            best[p.claim_id] = p
    ranked = sorted(best.values(), key=lambda p: (BAND_ORDER.get(p.risk_band, 9), -p.breach_probability))
    rows = []
    for p in ranked[:limit]:
        inst = inst_by_key[(p.claim_id, p.sla_id)]
        rows.append({**p.to_dict(), "status": inst.status, "consumed_pct": inst.consumed_pct, "responsible_team": inst.responsible_team, "queue": inst.queue})
    return rows


def surveyor_load_report(snap: SLASnapshot) -> list[dict[str, Any]]:
    """Which surveyors are overloaded: capacity ratio + open survey clocks + unscheduled inspections."""
    overload_ratio = float(snap.rules.risk_model.get("overload_ratio", 0.8))
    open_survey = [i for i in snap.instances if i.is_open and i.metric in {"surveyor_assignment", "survey_completion"}]
    pred_by_key = {(p.claim_id, p.sla_id): p for p in snap.predictions}
    per: dict[str, dict[str, Any]] = {}
    for inst in open_survey:
        sig = snap.signals.get(inst.claim_id)
        if not sig or not sig.surveyor:
            continue
        sv = sig.surveyor
        row = per.setdefault(
            sv["id"],
            {"surveyor_id": sv["id"], "name": sv["name"], "city": sv["city"], "load_ratio": sv["load_ratio"], "open_survey_clocks": 0, "at_risk_clocks": 0, "unscheduled_inspections": 0, "followups_outstanding": 0, "claims": []},
        )
        row["open_survey_clocks"] += 1
        pred = pred_by_key.get((inst.claim_id, inst.sla_id))
        if pred and pred.risk_band in {"at_risk", "critical", "breached"}:
            row["at_risk_clocks"] += 1
        if sig.inspection_scheduled is False:
            row["unscheduled_inspections"] += 1
        row["followups_outstanding"] += sig.followup_count
        row["claims"].append(inst.claim_number)
    for pid, p in snap.providers.items():
        if p.provider_type == "surveyor" and pid not in per:
            ratio = round(float(p.active_load or 0) / max(int(p.max_capacity or 1), 1), 3)
            per[pid] = {"surveyor_id": pid, "name": p.name, "city": p.city, "load_ratio": ratio, "open_survey_clocks": 0, "at_risk_clocks": 0, "unscheduled_inspections": 0, "followups_outstanding": 0, "claims": []}
    out = []
    for row in per.values():
        score = _clip(0.55 * _clip(row["load_ratio"] / max(overload_ratio, 0.01) * 0.8) + 0.25 * _clip(row["at_risk_clocks"] / 2.0) + 0.20 * _clip(row["unscheduled_inspections"] / 2.0))
        row["overload_score"] = round(score, 3)
        row["overloaded"] = row["load_ratio"] >= overload_ratio or (row["at_risk_clocks"] >= 2)
        row["reasons"] = [
            r
            for r in (
                f"capacity {row['load_ratio']:.0%} (threshold {overload_ratio:.0%})" if row["load_ratio"] >= overload_ratio else None,
                f"{row['at_risk_clocks']} survey clock(s) at risk" if row["at_risk_clocks"] else None,
                f"{row['unscheduled_inspections']} inspection(s) not yet scheduled" if row["unscheduled_inspections"] else None,
            )
            if r
        ]
        out.append(row)
    return sorted(out, key=lambda r: (-r["overload_score"], r["name"]))


def garage_delay_report(snap: SLASnapshot) -> list[dict[str, Any]]:
    """Which garages are causing delays: at-risk repair clocks, parts waits and turnaround vs target."""
    pred_by_key = {(p.claim_id, p.sla_id): p for p in snap.predictions}
    per: dict[str, dict[str, Any]] = {}
    for inst in snap.instances:
        if inst.metric != "repair_completion" or not inst.is_open:
            continue
        sig = snap.signals.get(inst.claim_id)
        if not sig or not sig.garage:
            continue
        g = sig.garage
        row = per.setdefault(
            g["id"],
            {"garage_id": g["id"], "name": g["name"], "city": g["city"], "load_ratio": g["load_ratio"], "turnaround_ratio": round(g["avg_turnaround_hours"] / max(g["target_hours"], 1.0), 2), "active_repairs": 0, "at_risk_repairs": 0, "parts_delayed": 0, "overrun_hours": [], "customer_chosen_repairs": 0, "claims": []},
        )
        row["active_repairs"] += 1
        pred = pred_by_key.get((inst.claim_id, inst.sla_id))
        if pred:
            row["overrun_hours"].append(pred.projected_overrun_hours)
            if pred.risk_band in {"at_risk", "critical", "breached"}:
                row["at_risk_repairs"] += 1
        if sig.parts_status in {"awaiting_parts", "ordered", "backordered", "partial", "unavailable"}:
            row["parts_delayed"] += 1
        if g.get("customer_chosen"):
            row["customer_chosen_repairs"] += 1
        row["claims"].append(inst.claim_number)
    out = []
    for row in per.values():
        n = max(row["active_repairs"], 1)
        mean_overrun = statistics.fmean(row["overrun_hours"]) if row["overrun_hours"] else 0.0
        delay_index = _clip(0.45 * row["at_risk_repairs"] / n + 0.25 * _clip(mean_overrun / 24.0) + 0.15 * row["parts_delayed"] / n + 0.15 * _clip(row["turnaround_ratio"] - 1.0))
        row.pop("overrun_hours")
        row["mean_projected_overrun_hours"] = round(mean_overrun, 1)
        row["delay_index"] = round(delay_index, 3)
        row["causing_delays"] = delay_index >= 0.4
        row["reasons"] = [
            r
            for r in (
                f"{row['at_risk_repairs']}/{row['active_repairs']} repairs projected to breach" if row["at_risk_repairs"] else None,
                f"parts delaying {row['parts_delayed']} repair(s)" if row["parts_delayed"] else None,
                f"turnaround {row['turnaround_ratio']:.2f}x contract target" if row["turnaround_ratio"] > 1.0 else None,
                f"projected overrun {mean_overrun:.0f}h on average" if mean_overrun >= 1 else None,
            )
            if r
        ]
        out.append(row)
    return sorted(out, key=lambda r: (-r["delay_index"], r["name"]))


def document_delay_report(snap: SLASnapshot) -> dict[str, Any]:
    """Which documents are likely to delay processing: owed documents by age, and extractions needing re-verification."""
    typical = float(snap.rules.risk_model.get("typical_customer_response_hours", 36))
    by_doc: dict[str, dict[str, Any]] = {}
    claims_rows: list[dict[str, Any]] = []
    for cid, sig in snap.signals.items():
        ctx = snap.contexts[cid]
        if ctx.canonical_status == "CLOSED":
            continue
        age = sig.oldest_doc_request_age_hours
        if not sig.missing_documents and not sig.unverified_documents:
            continue
        paused = [i for i in snap.instances_for(cid) if i.is_open and i.pause_codes_active]
        wait_ratio = (age / typical) if age is not None else 0.0
        band = "high" if wait_ratio >= 1.5 else "medium" if wait_ratio >= 1.0 or sig.unverified_documents else "low"
        claims_rows.append(
            {
                "claim_id": cid,
                "claim_number": sig.claim_number,
                "missing_documents": sig.missing_documents,
                "unverified_documents": sig.unverified_documents,
                "oldest_request_age_hours": age,
                "paused_clocks": [i.metric for i in paused],
                "delay_risk": band,
            }
        )
        for doc in sig.missing_documents:
            row = by_doc.setdefault(doc, {"document": doc, "state": "missing", "claims_affected": 0, "wait_hours": []})
            row["claims_affected"] += 1
            if age is not None:
                row["wait_hours"].append(age)
        for doc in sig.unverified_documents:
            row = by_doc.setdefault(f"{doc} (needs re-verification)", {"document": doc, "state": "unverified", "claims_affected": 0, "wait_hours": []})
            row["claims_affected"] += 1
    docs = []
    for key, row in by_doc.items():
        waits = row.pop("wait_hours")
        avg_wait = statistics.fmean(waits) if waits else None
        ratio = (avg_wait / typical) if avg_wait is not None else 0.0
        risk = "high" if ratio >= 1.5 else "medium" if (ratio >= 1.0 or row["state"] == "unverified") else "low"
        docs.append({**row, "label": key, "avg_wait_hours": round(avg_wait, 1) if avg_wait is not None else None, "delay_risk": risk})
    order = {"high": 0, "medium": 1, "low": 2}
    docs.sort(key=lambda d: (order[d["delay_risk"]], -d["claims_affected"]))
    claims_rows.sort(key=lambda r: (order[r["delay_risk"]], -(r["oldest_request_age_hours"] or 0)))
    return {"typical_customer_response_hours": typical, "documents": docs, "claims": claims_rows}


def queue_bottleneck_report(snap: SLASnapshot) -> list[dict[str, Any]]:
    threshold = float(snap.rules.risk_model.get("bottleneck_score_threshold", 0.45))
    rows = []
    for q in snap.queue_pressure.values():
        rows.append({**q, "bottleneck": q["pressure"] >= threshold and q["open_clocks"] >= 2, "threshold": threshold})
    return sorted(rows, key=lambda r: (-r["pressure"], r["queue"]))


def build_insights(snap: SLASnapshot) -> dict[str, Any]:
    return {
        "generated_at": snap.now.isoformat(),
        "claims_likely_to_breach": claim_risk_ranking(snap),
        "surveyors": surveyor_load_report(snap),
        "garages": garage_delay_report(snap),
        "documents": document_delay_report(snap),
        "queues": queue_bottleneck_report(snap),
    }
