"""Operational action planning and authorisation for the predictive SLA agent.

The planner *recommends* (reassignment, escalation, reminder, scheduling, prioritisation). The authoriser decides what
may actually run: only autonomous-class actions, through tools in the agent's allowlist, in ``execute`` mode, within the
per-run action budget, and never beyond tasks/reminders for third-party claims. Everything else becomes a human-approval
task or stays a recommendation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from services.sla.engine import SLAInstance
from services.sla.predictor import ClaimSignals, SLAPrediction
from services.sla.rules import SLARulesService

URGENCY_ORDER = {"immediate": 0, "today": 1, "watch": 2}

# Root-cause fixes first, generic escalation later: when the per-run action budget is tight, the action that removes
# the cause (book the slot, nudge the surveyor, chase the document) beats a generic "someone look at this".
ACTION_RANK = {
    "schedule_slot": 0,
    "chase_documents": 0,
    "remind_surveyor": 1,
    "remind_owner": 1,
    "escalate_team_lead": 2,
    "escalate_manager": 3,
    "prioritize_claim": 4,
    "reassign_surveyor": 5,
    "reassign_garage": 5,
    "rebalance_queue": 6,
}
REMINDER_ACTIONS = {"remind_surveyor", "chase_documents"}

# Escalation actions that are executed as claim tasks, with how each task is routed and prioritised.
TASK_PROFILES: dict[str, dict[str, Any]] = {
    "remind_owner": {"role": "owner", "priority": "medium", "due_hours": 4},
    "escalate_team_lead": {"role": "claims_manager", "priority": "high", "due_hours": 4},
    "escalate_manager": {"role": "claims_manager", "priority": "critical", "due_hours": 2},
    "prioritize_claim": {"role": "claims_handler", "priority": "high", "due_hours": 2},
    "schedule_slot": {"role": "claims_handler", "priority": "high", "due_hours": 6},
    "reassign_surveyor": {"role": "claims_manager", "priority": "high", "due_hours": 4},
    "reassign_garage": {"role": "claims_manager", "priority": "high", "due_hours": 4},
    "rebalance_queue": {"role": "claims_manager", "priority": "high", "due_hours": 6},
}
EXTERNAL_OWNER_ROLES = {"surveyor", "garage", "policyholder"}


@dataclass
class RecommendedAction:
    action: str
    label: str
    claim_id: str
    claim_number: str
    sla_id: str
    metric: str
    urgency: str
    rationale: str
    autonomy: str
    tool: str
    probability: float
    to_team: str = ""
    escalation_step: int | None = None
    approver_role: str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecommendedAction":
        return cls(**data)


def _rationale(pred: SLAPrediction, inst: SLAInstance, extra: str = "") -> str:
    if inst.status == "paused":
        codes = ", ".join(inst.pause_codes_active) or "customer wait"
        return f"{inst.title}: clock paused ({codes}) with {inst.consumed_pct:.0f}% of the SLA used; it resumes only when the customer responds. {extra}".strip()
    lead = (
        f"{inst.title}: {pred.breach_probability:.0%} breach probability "
        f"({inst.consumed_pct:.0f}% of SLA used, ~{pred.expected_remaining_hours:.1f}h of work expected vs {max(pred.remaining_budget_hours, 0):.1f}h left)"
        if inst.status != "breached"
        else f"{inst.title}: SLA already breached ({inst.consumed_pct:.0f}% used)"
    )
    top = [d["label"] for d in pred.drivers[:2]]
    why = f" Drivers: {'; '.join(top)}." if top else ""
    return f"{lead}.{why}{(' ' + extra) if extra else ''}"


def plan_claim_actions(
    instances: list[SLAInstance],
    predictions: list[SLAPrediction],
    signals: ClaimSignals,
    rules: SLARulesService,
    queue_context: dict[str, Any] | None = None,
) -> tuple[list[RecommendedAction], list[dict[str, Any]]]:
    """Recommend operational actions for one claim. Returns (recommendations, suppressed-with-reason)."""
    guard = rules.guardrails
    rm = rules.risk_model
    min_p = float(guard.get("min_probability_to_act", 0.6))
    cooldown = float(guard.get("cooldown_hours", 12))
    typical_wait = float(rm.get("typical_customer_response_hours", 36))
    bottleneck_threshold = float(rm.get("bottleneck_score_threshold", 0.45))
    pred_by_sla = {p.sla_id: p for p in predictions}
    recs: dict[str, RecommendedAction] = {}
    suppressed: list[dict[str, Any]] = []

    def put(rec: RecommendedAction) -> None:
        cur = recs.get(rec.action)
        if cur is None or (URGENCY_ORDER[rec.urgency], -rec.probability) < (URGENCY_ORDER[cur.urgency], -cur.probability):
            recs[rec.action] = rec

    def build(action: str, inst: SLAInstance, pred: SLAPrediction, urgency: str, extra: str = "", step: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> RecommendedAction:
        policy = rules.action_policy(action)
        return RecommendedAction(
            action=action,
            label=policy.get("label", action),
            claim_id=inst.claim_id,
            claim_number=inst.claim_number,
            sla_id=inst.sla_id,
            metric=inst.metric,
            urgency=urgency,
            rationale=_rationale(pred, inst, extra),
            autonomy=policy.get("autonomy", "human_approval"),
            tool=policy.get("tool", "create_claim_task"),
            probability=pred.breach_probability,
            to_team=(step or {}).get("to_team", inst.responsible_team),
            escalation_step=(step or {}).get("step"),
            approver_role=policy.get("approver_role"),
            params=params or {},
        )

    for inst in instances:
        if not inst.is_open:
            continue
        pred = pred_by_sla.get(inst.sla_id)
        if pred is None:
            continue

        # Paused on the customer: nothing to escalate internally, but a stale document request deserves a nudge.
        if inst.status == "paused":
            age = signals.oldest_doc_request_age_hours or 0.0
            if "AWAITING_CUSTOMER_DOCUMENTS" in inst.pause_codes_active and signals.missing_documents and age >= 0.5 * typical_wait:
                since = signals.hours_since_last_doc_request
                if since is not None and since < cooldown:
                    suppressed.append({"action": "chase_documents", "sla_id": inst.sla_id, "reason": f"document request sent {since:.0f}h ago (cooldown {cooldown:.0f}h)"})
                else:
                    put(build("chase_documents", inst, pred, "today", f"Customer has owed documents for {age:.0f}h (typical response {typical_wait:.0f}h).", params={"documents": signals.missing_documents}))
            continue

        actionable = pred.risk_band == "breached" or pred.breach_probability >= min_p
        if not actionable:
            continue
        urgency = "immediate" if pred.risk_band in {"breached", "critical"} else "today"
        codes = {d["code"] for d in pred.drivers}

        threshold_pct = max(inst.consumed_pct, pred.projected_consumed_pct)
        due_steps = [s for s in inst.escalation_sequence if s["at_pct"] <= threshold_pct]
        step = due_steps[-1] if due_steps else None
        action = step["action"] if step else "remind_owner"

        if action == "remind_surveyor":
            since = signals.hours_since_last_followup
            if since is not None and since < cooldown:
                suppressed.append({"action": action, "sla_id": inst.sla_id, "reason": f"surveyor followed up {since:.0f}h ago (cooldown {cooldown:.0f}h)"})
                action = ""
        if action == "chase_documents":
            since = signals.hours_since_last_doc_request
            if since is not None and since < cooldown:
                suppressed.append({"action": action, "sla_id": inst.sla_id, "reason": f"document request sent {since:.0f}h ago (cooldown {cooldown:.0f}h)"})
                action = ""
        if action:
            params: dict[str, Any] = {}
            if action == "remind_surveyor":
                params = {"escalate_to_manager": urgency == "immediate"}
            put(build(action, inst, pred, urgency, step=step, params=params))
        # Earlier reminder-class steps stay useful when the clock jumped past them (they are cheap and idempotent).
        for earlier in due_steps[:-1]:
            if earlier["action"] in REMINDER_ACTIONS and earlier["action"] != action:
                since = signals.hours_since_last_followup if earlier["action"] == "remind_surveyor" else signals.hours_since_last_doc_request
                if since is not None and since < cooldown:
                    suppressed.append({"action": earlier["action"], "sla_id": inst.sla_id, "reason": f"already actioned {since:.0f}h ago (cooldown {cooldown:.0f}h)"})
                    continue
                if earlier["action"] == "chase_documents" and not signals.missing_documents:
                    continue
                reminder_params: dict[str, Any] = {"documents": signals.missing_documents} if earlier["action"] == "chase_documents" else {"escalate_to_manager": False}
                put(build(earlier["action"], inst, pred, urgency, step=earlier, params=reminder_params))

        kind, owner = signals.owner_for(inst.metric)
        if "OWNER_OVERLOADED" in codes and owner:
            candidates = signals.reassign_candidates.get(kind or "", [])
            if kind == "surveyor" and candidates:
                put(build("reassign_surveyor", inst, pred, urgency, f"{owner['name']} is at {owner['load_ratio']:.0%} capacity; {candidates[0]['name']} has headroom ({candidates[0]['load_ratio']:.0%}).", params={"from_provider_id": owner["id"], "candidates": candidates}))
            elif kind == "garage":
                if owner.get("customer_chosen"):
                    suppressed.append({"action": "reassign_garage", "sla_id": inst.sla_id, "reason": "customer-chosen garage is protected; escalate to the garage instead of reassigning"})
                    put(build("escalate_manager", inst, pred, urgency, f"{owner['name']} is overloaded but is the customer's chosen garage, so reassignment is not offered."))
                elif candidates:
                    put(build("reassign_garage", inst, pred, urgency, f"{owner['name']} is at {owner['load_ratio']:.0%} capacity; {candidates[0]['name']} has headroom.", params={"from_provider_id": owner["id"], "candidates": candidates}))
        if "NO_INSPECTION_SLOT" in codes or "INSPECTION_LATE_SLOT" in codes:
            put(build("schedule_slot", inst, pred, urgency, "Book the earliest inspection slot to protect the survey SLA."))
        if "DOCUMENTS_OUTSTANDING" in codes and signals.missing_documents:
            since = signals.hours_since_last_doc_request
            if since is not None and since < cooldown:
                suppressed.append({"action": "chase_documents", "sla_id": inst.sla_id, "reason": f"document request sent {since:.0f}h ago (cooldown {cooldown:.0f}h)"})
            else:
                put(build("chase_documents", inst, pred, urgency, params={"documents": signals.missing_documents}))
        if "QUEUE_PRESSURE" in codes and queue_context and queue_context.get("pressure", 0) >= bottleneck_threshold:
            put(build("prioritize_claim", inst, pred, urgency, f"Queue '{queue_context['queue']}' is bottlenecked ({queue_context['pressure']:.0%} pressure)."))
            if queue_context.get("rebalance_raised"):
                suppressed.append({"action": "rebalance_queue", "sla_id": inst.sla_id, "reason": f"queue rebalance for '{queue_context['queue']}' already raised in this run"})
            else:
                put(build("rebalance_queue", inst, pred, urgency, f"{queue_context['late_clocks']} of {queue_context['open_clocks']} open clocks in '{queue_context['queue']}' are late.", params={"queue": queue_context["queue"]}))

    ordered = sorted(recs.values(), key=lambda r: (URGENCY_ORDER[r.urgency], ACTION_RANK.get(r.action, 9), -r.probability, r.action))
    return ordered, suppressed


@dataclass
class AuthorisationDecision:
    decision: str  # execute | gate_human | recommend_only | block_policy
    reason: str


def authorise_action(
    rec: RecommendedAction,
    *,
    mode: str,
    claim_type: str,
    agent_tools: set[str],
    request_tools: set[str],
    rules: SLARulesService,
    executed_so_far: int,
) -> AuthorisationDecision:
    """Single choke point deciding whether the agent may act on a recommendation."""
    guard = rules.guardrails
    if rec.action in set(guard.get("never_autonomous", [])):
        return AuthorisationDecision("block_policy", f"'{rec.action}' is never autonomous")
    if mode != "execute":
        return AuthorisationDecision("recommend_only", "recommend mode: nothing is executed")
    if rec.tool not in agent_tools or rec.tool not in request_tools:
        return AuthorisationDecision("block_policy", f"tool '{rec.tool}' is outside the agent's authorised allowlist")
    if rec.autonomy == "human_approval":
        return AuthorisationDecision("gate_human", f"requires {rec.approver_role or 'manager'} approval; approval task raised instead of acting")
    if rules.family(claim_type) == "third_party" and guard.get("tp_claims_autonomy") == "tasks_only" and rec.tool != "create_claim_task":
        return AuthorisationDecision("block_policy", "third-party claims allow task-level actions only (no customer/partner contact)")
    if executed_so_far >= int(guard.get("max_autonomous_actions_per_claim_per_run", 2)):
        return AuthorisationDecision("recommend_only", "per-claim action budget for this run is exhausted")
    return AuthorisationDecision("execute", "autonomous-class action within guardrails")


def task_spec(rec: RecommendedAction, inst: SLAInstance | None, *, approval: bool) -> dict[str, Any]:
    """Arguments for ControlledActionExecutor.create_claim_task for an escalation/approval action."""
    profile = TASK_PROFILES.get(rec.action, {"role": "claims_handler", "priority": "medium", "due_hours": 8})
    role = profile["role"]
    if role == "owner":
        owner_role = inst.owner_role if inst else "claims_handler"
        role = "claims_handler" if owner_role in EXTERNAL_OWNER_ROLES else owner_role
    task_type = ("sla_approval_" if approval else "sla_") + rec.action
    title = f"{'Approval needed: ' if approval else 'SLA: '}{rec.label} ({rec.metric.replace('_', ' ')})"
    return {
        "task_type": task_type[:64],
        "title": title[:200],
        "description": rec.rationale,
        "assigned_role": role,
        "priority": profile["priority"],
        "reason_code": f"RC_SLA_{rec.action.upper()}_{rec.metric.upper()}"[:64],
        "due_hours": profile["due_hours"],
        "metadata": {
            "sla_id": rec.sla_id,
            "action": rec.action,
            "breach_probability": rec.probability,
            "requires_approval": approval,
            "approver_role": rec.approver_role,
            **{k: v for k, v in rec.params.items() if k in {"candidates", "from_provider_id", "queue"}},
        },
    }
