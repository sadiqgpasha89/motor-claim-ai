"""Human-override tracking: how often people reject or return what the AI recommended."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy.orm import Session

from services.claims.models import AgentExecutionRecord, Approval
from services.rules_engine.responsible_ai import responsible_ai_controls

NOTE = "Computed live from approvals and agent traces over DEMO / SYNTHETIC data. An override is a human decision that is not 'approved'."
ACTION_AGENT = {"settlement_approval": "settlement_recommendation", "payment_approval": "settlement_recommendation"}


def _pct(num: int, den: int) -> float:
    return round(100.0 * num / den, 1) if den else 0.0


def human_override_report(db: Session, tenant_id: str) -> dict[str, Any]:
    cfg = responsible_ai_controls(db)["human_override"]
    approvals = db.query(Approval).filter(Approval.tenant_id == tenant_id).all()
    decided = [a for a in approvals if a.decision != "pending"]
    by_action: dict[str, Counter[str]] = defaultdict(Counter)
    for a in decided:
        by_action[a.action_type][a.decision] += 1
    rows = []
    alerts = []
    for action, counts in sorted(by_action.items()):
        total = sum(counts.values())
        overridden = total - counts.get("approved", 0)
        rate = _pct(overridden, total)
        row = {
            "action_type": action,
            "agent": ACTION_AGENT.get(action, "claim_workflow"),
            "decided": total,
            "approved": counts.get("approved", 0),
            "overridden": overridden,
            "override_rate_pct": rate,
            "decisions": dict(counts),
        }
        rows.append(row)
        if total >= cfg["min_decisions_for_alert"] and rate > cfg["override_rate_alert_pct"]:
            alerts.append(f"{action}: override rate {rate}% is above {cfg['override_rate_alert_pct']}%. Review the agent.")

    traces = db.query(AgentExecutionRecord).filter(AgentExecutionRecord.tenant_id == tenant_id).all()
    required: Counter[str] = Counter()
    resolved: Counter[str] = Counter()
    runs: Counter[str] = Counter()
    for t in traces:
        runs[t.agent_name] += 1
        marker = t.human_intervention or {}
        if marker.get("required"):
            required[t.agent_name] += 1
            if marker.get("resolved"):
                resolved[t.agent_name] += 1
    agents = [
        {
            "agent": name,
            "executions": runs[name],
            "human_required": required[name],
            "human_resolved": resolved[name],
            "intervention_rate_pct": _pct(required[name], runs[name]),
        }
        for name in sorted(runs)
        if required[name]
    ]
    total_decided = len(decided)
    total_overridden = sum(sum(c.values()) - c["approved"] for c in by_action.values())
    return {
        "approvals_decided": total_decided,
        "approvals_pending": len(approvals) - total_decided,
        "overridden": total_overridden,
        "override_rate_pct": _pct(total_overridden, total_decided),
        "by_action": rows,
        "agent_interventions": agents,
        "alert_threshold_pct": cfg["override_rate_alert_pct"],
        "alerts": alerts,
        "note": NOTE,
    }
