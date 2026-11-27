"""Agent trace store helpers (feedback item 16).

Every agent execution is recorded with model, prompt, tool, token, latency, retry, outcome and
human-intervention data. Token counts are ESTIMATED from payload size while the deterministic stub
model is active. The cost rate card is an illustrative reference price list, not a vendor invoice.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from packages.contracts.agents import AgentInvocationResponse, AgentStatus

# Reference INR price per 1,000 tokens as (input, output). Illustrative only.
COST_RATE_CARD_INR_PER_1K: dict[str, tuple[Decimal, Decimal]] = {
    "motorclaim-deterministic-stub": (Decimal("0.20"), Decimal("0.60")),
    "gemini-2.5-flash": (Decimal("0.25"), Decimal("0.80")),
    "claude-sonnet-4": (Decimal("0.90"), Decimal("4.50")),
}
DEFAULT_RATE = (Decimal("0.50"), Decimal("2.00"))
SYSTEM_PROMPT_OVERHEAD_TOKENS = 450
MAX_TOOL_OUTPUT_CHARS = 600

OUTCOME_BY_STATUS: dict[str, str] = {
    AgentStatus.COMPLETED.value: "success",
    AgentStatus.NEEDS_HUMAN.value: "escalated_to_human",
    AgentStatus.INSUFFICIENT_EVIDENCE.value: "insufficient_evidence",
    AgentStatus.REWORK_REQUIRED.value: "rework_requested",
    AgentStatus.BLOCKED_DEPENDENCY.value: "blocked",
    AgentStatus.TIMED_OUT.value: "timeout",
    AgentStatus.FAILED.value: "failed",
}
FAILED_OUTCOMES = {"failed", "timeout"}


def estimate_tokens(payload: Any) -> int:
    """About four characters per token. Deterministic, so traces are reproducible in tests."""
    text = payload if isinstance(payload, str) else json.dumps(payload, default=str, sort_keys=True)
    return max(1, math.ceil(len(text) / 4))


def estimate_cost_inr(model_name: str, tokens_in: int, tokens_out: int) -> Decimal:
    rate_in, rate_out = COST_RATE_CARD_INR_PER_1K.get(model_name, DEFAULT_RATE)
    cost = (Decimal(tokens_in) * rate_in + Decimal(tokens_out) * rate_out) / Decimal(1000)
    return cost.quantize(Decimal("0.0001"))


def input_reference(claim_id: str, agent_name: str, attempt: int, facts: dict[str, Any] | None) -> str:
    """Reference to the task input. It holds a hash, never the raw (possibly PII) facts."""
    digest = hashlib.sha256(json.dumps(facts or {}, default=str, sort_keys=True).encode()).hexdigest()[:16]
    return f"claim:{claim_id}/agent:{agent_name}/attempt:{attempt}/input-sha256:{digest}"


def _truncate(value: Any) -> Any:
    text = json.dumps(value, default=str)
    if len(text) <= MAX_TOOL_OUTPUT_CHARS:
        return json.loads(text)
    return {"truncated": True, "preview": text[:MAX_TOOL_OUTPUT_CHARS]}


def build_trace_fields(
    *,
    claim_id: str,
    agent_name: str,
    agent_version: str,
    response: AgentInvocationResponse,
    input_facts: dict[str, Any] | None,
    retry_count: int,
    error_message: str | None,
    ended_at: datetime | None = None,
) -> dict[str, Any]:
    """Return the AgentExecutionRecord trace columns for one execution."""
    ended = ended_at or datetime.now(timezone.utc)
    started = ended - timedelta(milliseconds=max(response.duration_ms, 0))
    tool_calls = [
        {
            "tool": a.tool_name,
            "action_type": a.action_type,
            "status": a.status,
            "target": f"{a.target_type}:{a.target_id}",
        }
        for a in response.actions_executed
    ]
    named = {c["tool"] for c in tool_calls}
    tool_calls += [{"tool": t, "action_type": "read", "status": "ok", "target": "claim"} for t in response.tools_invoked if t not in named]
    tool_outputs = [{"tool": a.tool_name, "summary": a.summary, "output": _truncate(a.payload)} for a in response.actions_executed]

    tokens_in = estimate_tokens(input_facts or {}) + SYSTEM_PROMPT_OVERHEAD_TOKENS
    tokens_out = estimate_tokens(response.published_result or response.result)
    outcome = OUTCOME_BY_STATUS.get(response.status.value, "failed")
    needs_human = response.status == AgentStatus.NEEDS_HUMAN or any(a.status == "gated_human_review" for a in response.actions_executed)
    final_action = response.suggested_next_action or (response.actions_executed[-1].action_type if response.actions_executed else "none")

    error_details = None
    if outcome in FAILED_OUTCOMES or error_message:
        error_details = {
            "error_message": error_message or "; ".join(response.limitations) or outcome,
            "reason_codes": list(response.decision.reason_codes) if response.decision else [],
            "retryable": outcome == "timeout",
        }
    return {
        "agent_version": agent_version,
        "model_name": response.model_id,
        "model_version": response.model_version,
        "prompt_version": response.prompt_version,
        "task_input_ref": input_reference(claim_id, agent_name, response.attempt_number, input_facts),
        "tool_calls": tool_calls,
        "tool_outputs": tool_outputs,
        "started_at": started,
        "ended_at": ended,
        "tokens_input": tokens_in,
        "tokens_output": tokens_out,
        "usage_source": "estimated",
        "cost_inr": estimate_cost_inr(response.model_id, tokens_in, tokens_out),
        "retry_count": retry_count,
        "outcome": outcome,
        "confidence": None if response.status == AgentStatus.BLOCKED_DEPENDENCY else Decimal(str(round(response.confidence, 3))),
        "error_details": error_details,
        "human_intervention": {"required": needs_human, "resolved": False, "resolved_by": None, "decision": None} if needs_human else None,
        "final_action": str(final_action)[:160],
    }


def resolve_human_intervention(db: Any, *, claim_id: str, actor_id: str, actor_role: str, decision: str) -> int:
    """Close every open human-intervention marker on the claim's traces. Returns the count closed."""
    from services.claims.models import AgentExecutionRecord

    closed = 0
    now = datetime.now(timezone.utc).isoformat()
    rows = db.query(AgentExecutionRecord).filter(AgentExecutionRecord.claim_id == claim_id).all()
    for rec in rows:
        marker = rec.human_intervention
        if marker and marker.get("required") and not marker.get("resolved"):
            rec.human_intervention = {
                **marker,
                "resolved": True,
                "resolved_by": actor_id,
                "resolved_role": actor_role,
                "decision": decision,
                "resolved_at": now,
            }
            closed += 1
    return closed
