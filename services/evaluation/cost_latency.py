"""Cost and latency report with advisory optimisation hints. Token counts and costs are estimates."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from services.claims.models import AgentExecutionRecord
from services.observability.traces import COST_RATE_CARD_INR_PER_1K, DEFAULT_RATE, estimate_cost_inr
from services.rules_engine.responsible_ai import responsible_ai_controls

NOTE = "Computed live from the agent trace store over DEMO / SYNTHETIC data. Tokens and costs are estimates. Hints are advisory."


def _p95(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))] if ordered else 0


def _cheapest_model() -> str:
    return min(COST_RATE_CARD_INR_PER_1K, key=lambda m: sum(COST_RATE_CARD_INR_PER_1K[m]))


def cost_latency_report(db: Session, tenant_id: str) -> dict[str, Any]:
    cfg = responsible_ai_controls(db)
    lat_cfg, cost_cfg, opt = cfg["latency_budget_ms"], cfg["cost_budget_inr"], cfg["optimisation"]
    traces = db.query(AgentExecutionRecord).filter(AgentExecutionRecord.tenant_id == tenant_id).all()
    by_agent: dict[str, list[AgentExecutionRecord]] = defaultdict(list)
    for t in traces:
        by_agent[t.agent_name].append(t)
    total_cost = sum((Decimal(str(t.cost_inr or 0)) for t in traces), Decimal("0"))
    cheapest = _cheapest_model()
    agents: list[dict[str, Any]] = []
    hints: list[str] = []
    for name, rows in sorted(by_agent.items()):
        n = len(rows)
        cost = sum((Decimal(str(t.cost_inr or 0)) for t in rows), Decimal("0"))
        durations = [t.duration_ms for t in rows]
        budget = int(lat_cfg["per_agent"].get(name, lat_cfg["default"]))
        share = round(float(100 * cost / total_cost), 1) if total_cost else 0.0
        retry_rate = round(100.0 * sum(1 for t in rows if t.retry_count) / n, 1)
        model = rows[-1].model_name
        saving = Decimal("0")
        if model and model != cheapest:
            cheap_cost = sum((estimate_cost_inr(cheapest, t.tokens_input, t.tokens_output) for t in rows), Decimal("0"))
            saving = max(cost - cheap_cost, Decimal("0"))
        p95 = _p95(durations)
        agents.append({
            "agent": name, "executions": n, "model": model,
            "avg_duration_ms": round(sum(durations) / n), "p95_duration_ms": p95, "latency_budget_ms": budget,
            "latency_over_budget": p95 > budget,
            "avg_tokens": round(sum(t.tokens_input + t.tokens_output for t in rows) / n),
            "cost_inr": str(cost.quantize(Decimal("0.0001"))), "cost_share_pct": share,
            "retry_rate_pct": retry_rate,
            "estimated_saving_inr_on_cheapest_model": str(saving.quantize(Decimal("0.0001"))),
        })
        if n < opt["min_samples"]:
            continue
        if p95 > budget:
            hints.append(f"{name}: p95 latency {p95} ms is above the {budget} ms budget. Check slow tools and retries.")
        if share > cost_cfg["per_agent_share_alert_pct"]:
            hints.append(f"{name}: uses {share}% of AI cost. Trim the context or use a cheaper model for simple steps.")
        if retry_rate > opt["retry_rate_alert_pct"]:
            hints.append(f"{name}: {retry_rate}% of runs retried. Fix the retry cause before adding capacity.")
    claims = {t.claim_id for t in traces}
    per_claim = (total_cost / max(len(claims), 1)).quantize(Decimal("0.0001"))
    over_budget = per_claim > Decimal(str(cost_cfg["per_claim"]))
    if over_budget:
        hints.append(f"Cost per claim {per_claim} INR is above the {cost_cfg['per_claim']} INR budget.")
    return {
        "agent_executions": len(traces),
        "claims_with_ai_activity": len(claims),
        "cost_per_claim_inr": str(per_claim),
        "cost_per_claim_budget_inr": cost_cfg["per_claim"],
        "cost_over_budget": over_budget,
        "agents": agents,
        "optimisation_hints": hints,
        "cheapest_rate_card_model": cheapest,
        "default_rate_in_use": [str(r) for r in DEFAULT_RATE],
        "note": NOTE,
    }
