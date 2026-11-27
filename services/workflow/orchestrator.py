from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from agents.specialists import AGENT_REGISTRY
from packages.contracts.agents import (
    AgentActionExecution,
    AgentInvocationRequest,
    AgentInvocationResponse,
    AgentStatus,
    ConfidenceBand,
    DecisionIntelligence,
    ReworkRequest,
)
from packages.contracts.errors import DomainError, ErrorCode
from packages.observability.logging import get_correlation_id
from packages.security.auth import UserContext
from services.agent_runtime.actions import ControlledActionExecutor
from services.agent_runtime.contracts import AGENT_CAPABILITY_CONTRACTS, ORCHESTRATION_ORDER
from services.claims.audit import emit_outbox_event, record_audit_event
from services.claims.models import (
    AgentExecutionRecord,
    Approval,
    Claim,
    ClaimTask,
    CompensationLog,
    DamageAssessment,
    DeadLetterRecord,
    DecisionRecord,
    Estimate,
    Evidence,
    ExtractedFact,
    FraudAlert,
    Grievance,
    OrchestrationEventLog,
    OrchestrationTask,
    Payment,
    Policy,
    Provider,
    Settlement,
    SurveyAssignment,
    Vehicle,
)
from services.claims.state_machine import (
    ClaimStatus,
    TriageTrack,
    to_canonical_state,
    validate_transition,
)
from services.damage_ai.assessor import assess_damage_from_evidence, validate_estimate_lines
from services.fraud_intelligence.detector import build_entity_relationship_graph, run_fraud_and_anomaly_checks
from services.observability.traces import build_trace_fields, resolve_human_intervention
from services.rules_engine.loader import get_active_rule, load_rule_files
from services.settlement.calculator import SettlementCalculator, SettlementLineInput
from services.workflow.risk_engine import evaluate_and_persist_risk, gather_claim_risk_facts
from services.workflow.sla_engine import (
    pause_active_sla_timers,
    resume_paused_sla_timers,
    transition_state_sla_timer,
)
from services.workflow.state_specs import (
    TASK_DAG_SPECS,
    WORKFLOW_STATE_SPECS,
    RetryStrategySpec,
    TaskDAGSpec,
    compute_exponential_backoff_ms,
    evaluate_state_entry_conditions,
)

_BLOCKING_UPSTREAM_STATUSES = {
    AgentStatus.FAILED.value,
    AgentStatus.TIMED_OUT.value,
    AgentStatus.BLOCKED_DEPENDENCY.value,
    AgentStatus.REWORK_REQUIRED.value,
    "rework_invalidated",
    "dlq",
}

_AGENT_TO_TASK_KEY: dict[str, str] = {
    "fnol_concierge": "fnol_intake",
    "coverage_intelligence": "policy_validation",
    "document_intelligence": "document_extraction",
    "customer_communication": "customer_communication",
    "claim_triage": "claim_triage",
    "provider_coordination": "provider_coordination",
    "damage_assessment": "damage_assessment",
    "fraud_intelligence": "fraud_analysis",
    "estimate_validation": "estimate_validation",
    "settlement_recommendation": "settlement_recommendation",
    "qa_compliance": "qa_closure",
}

_TASK_KEY_TO_SPEC: dict[str, TaskDAGSpec] = {spec.task_key: spec for spec in TASK_DAG_SPECS}


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _downstream_dependents(target_agent: str) -> list[str]:
    dependents: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, spec in AGENT_CAPABILITY_CONTRACTS.items():
            if name in dependents:
                continue
            if target_agent in spec.depends_on or any(d in dependents for d in spec.depends_on):
                dependents.add(name)
                changed = True
    return [a for a in ORCHESTRATION_ORDER if a in dependents]


def record_agent_publication(
    db: Session,
    *,
    claim: Claim,
    agent_name: str,
    response: AgentInvocationResponse,
    dependencies_satisfied: bool = True,
    error_message: str | None = None,
    input_facts: dict[str, Any] | None = None,
    retry_count: int = 0,
) -> AgentExecutionRecord:
    """Persists an agent's structured publication, actions, rework, and decision intelligence."""
    wf = dict(claim.workflow_state or {})
    published = dict(wf.get("published_results", {}))
    statuses = dict(wf.get("stage_statuses", {}))
    completed = list(wf.get("steps_completed", []))

    pub_payload = _json_safe(response.published_result or response.result)
    if response.status != AgentStatus.BLOCKED_DEPENDENCY:
        published[agent_name] = {
            "status": response.status.value,
            "confidence": response.confidence,
            "confidence_band": response.confidence_band.value,
            "attempt_number": response.attempt_number,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "data": pub_payload,
        }
        statuses[agent_name] = response.status.value
        if response.status == AgentStatus.COMPLETED and agent_name not in completed:
            completed.append(agent_name)

    wf["published_results"] = published
    wf["stage_statuses"] = statuses
    wf["steps_completed"] = completed
    claim.workflow_state = _json_safe(wf)

    stage_order = ORCHESTRATION_ORDER.index(agent_name) + 1 if agent_name in ORCHESTRATION_ORDER else 99
    spec = AGENT_CAPABILITY_CONTRACTS.get(agent_name)

    rec = AgentExecutionRecord(
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        workflow_run_id=wf.get("workflow_run_id", claim.id),
        agent_name=agent_name,
        stage_order=stage_order,
        attempt_number=response.attempt_number,
        status=response.status.value,
        dependencies_satisfied=dependencies_satisfied,
        depends_on=spec.depends_on if spec else [],
        published_result=pub_payload,
        actions_executed=_json_safe([a.model_dump() for a in response.actions_executed]),
        rework_requests=_json_safe([r.model_dump() for r in response.rework_requests]),
        decision=_json_safe(response.decision.model_dump()) if response.decision else None,
        error_message=error_message,
        duration_ms=response.duration_ms,
        **build_trace_fields(
            claim_id=claim.id,
            agent_name=agent_name,
            agent_version=getattr(AGENT_REGISTRY.get(agent_name), "agent_version", "2.0.0"),
            response=response,
            input_facts=input_facts,
            retry_count=retry_count,
            error_message=error_message,
        ),
    )
    db.add(rec)

    if response.decision:
        dec = response.decision
        db.add(
            DecisionRecord(
                tenant_id=claim.tenant_id,
                claim_id=claim.id,
                agent_name=agent_name,
                stage=spec.stage if spec else agent_name,
                decision_id=dec.decision_id,
                routing_outcome=dec.routing_outcome,
                reason_codes=dec.reason_codes,
                evidence=dec.evidence,
                policy_rule_refs=dec.policy_rule_refs,
                confidence=Decimal(str(round(dec.confidence, 3))),
                confidence_band=dec.confidence_band.value,
                explanation=dec.explanation,
                alternatives_considered=dec.alternatives_considered,
            )
        )

    emit_outbox_event(
        db,
        tenant_id=claim.tenant_id,
        aggregate_id=claim.id,
        event_type="AgentResultPublished",
        payload={
            "agent_name": agent_name,
            "status": response.status.value,
            "attempt": response.attempt_number,
            "actions_count": len(response.actions_executed),
        },
    )
    db.flush()
    return rec


class ClaimOrchestrator:
    """Enterprise Claim Orchestration Engine.

    Exclusively owns claim progression, state transitions, DAG task scheduling,
    safe parallel wave execution, exponential-backoff retries, timeouts,
    dead-letter queues, compensation sagas, SLA tracking, duplicate-event protection,
    and workflow pause/resume/recovery.
    """

    def __init__(self, db: Session, user: UserContext) -> None:
        self.db = db
        self.user = user

    # ------------------------------------------------------------------
    # State Transitions & Contract Enforcement (Orchestrator-Owned)
    # ------------------------------------------------------------------

    def transition_state(
        self,
        claim: Claim,
        target_state: str,
        *,
        reason: str,
        trigger_event: str = "OrchestratorTransition",
        enforce_entry: bool = True,
        next_expected_action: str | None = None,
    ) -> ClaimStatus:
        before = claim.status
        if enforce_entry and before != target_state:
            ok, unmet = evaluate_state_entry_conditions(self.db, claim, target_state)
            if not ok:
                raise DomainError(
                    ErrorCode.STATE_CONFLICT,
                    f"Entry conditions unmet for state '{target_state}': {', '.join(unmet)}",
                    status_code=409,
                )

        validated = validate_transition(before, target_state)
        claim.status = validated.value
        if next_expected_action:
            claim.next_expected_action = next_expected_action[:200]

        wf = dict(claim.workflow_state or {})
        wf.setdefault("workflow_run_id", f"wf-{uuid.uuid4().hex[:10]}")
        wf["current_state"] = validated.value
        wf["canonical_state"] = to_canonical_state(validated.value)
        history = list(wf.get("state_history", []))
        if before != validated.value or not history:
            history.append(
                {
                    "from_state": before,
                    "to_state": validated.value,
                    "canonical_state": to_canonical_state(validated.value),
                    "reason": reason,
                    "trigger_event": trigger_event,
                    "actor": "orchestrator",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            wf["state_history"] = history
        claim.workflow_state = _json_safe(wf)

        if before != validated.value:
            transition_state_sla_timer(
                self.db,
                tenant_id=claim.tenant_id,
                claim_id=claim.id,
                from_state=to_canonical_state(before),
                to_state=to_canonical_state(validated.value),
            )
            emit_outbox_event(
                self.db,
                tenant_id=claim.tenant_id,
                aggregate_id=claim.id,
                event_type="ClaimStateTransitioned",
                payload={
                    "from_state": before,
                    "to_state": validated.value,
                    "canonical_state": to_canonical_state(validated.value),
                    "reason": reason,
                    "trigger_event": trigger_event,
                },
            )
            record_audit_event(
                self.db,
                tenant_id=claim.tenant_id,
                claim_id=claim.id,
                actor_id="orchestrator",
                actor_role="orchestrator",
                action="ORCHESTRATOR_STATE_TRANSITION",
                object_type="claim",
                object_id=claim.id,
                before_state={"status": before},
                after_state={"status": validated.value, "canonical": to_canonical_state(validated.value)},
                details={"reason": reason, "trigger_event": trigger_event},
            )
        self.db.flush()
        return validated

    def _safe_transition(
        self,
        claim: Claim,
        target_state: str,
        *,
        reason: str,
        trigger_event: str = "OrchestratorProgression",
        next_expected_action: str | None = None,
    ) -> bool:
        if claim.status == target_state:
            if next_expected_action:
                claim.next_expected_action = next_expected_action[:200]
            return True
        try:
            self.transition_state(
                claim,
                target_state,
                reason=reason,
                trigger_event=trigger_event,
                enforce_entry=True,
                next_expected_action=next_expected_action,
            )
            return True
        except DomainError:
            return False

    # ------------------------------------------------------------------
    # Task Scheduling & DAG Blueprint Sync
    # ------------------------------------------------------------------

    def sync_task_schedule(self, claim: Claim) -> list[OrchestrationTask]:
        """Materializes and updates all DAG OrchestrationTask rows for the claim."""
        wf = dict(claim.workflow_state or {})
        wf_run_id = wf.get("workflow_run_id") or f"wf-{claim.id[:8]}"
        wf["workflow_run_id"] = wf_run_id
        claim.workflow_state = _json_safe(wf)

        existing = {
            t.task_key: t
            for t in self.db.query(OrchestrationTask)
            .filter(OrchestrationTask.claim_id == claim.id, OrchestrationTask.workflow_run_id == wf_run_id)
            .all()
        }
        stage_statuses = wf.get("stage_statuses", {})
        is_paused = bool(wf.get("paused", False))

        tasks: list[OrchestrationTask] = []
        for spec in TASK_DAG_SPECS:
            task = existing.get(spec.task_key)
            if not task:
                idem = f"{claim.id}:{wf_run_id}:{spec.task_key}"
                task = OrchestrationTask(
                    tenant_id=claim.tenant_id,
                    claim_id=claim.id,
                    workflow_run_id=wf_run_id,
                    task_key=spec.task_key,
                    title=spec.title,
                    agent_or_service=spec.agent_or_service,
                    execution_mode=spec.execution_mode,
                    parallel_group=spec.parallel_group,
                    depends_on=spec.depends_on,
                    condition_expression=spec.condition_description,
                    target_state=spec.target_state,
                    status="paused" if is_paused else "pending",
                    max_retries=spec.max_retries,
                    timeout_seconds=spec.timeout_seconds,
                    idempotency_key=idem,
                )
                self.db.add(task)
                existing[spec.task_key] = task
            else:
                # Sync with any agent status updated externally
                mapped_agent = next(
                    (ag for ag, tk in _AGENT_TO_TASK_KEY.items() if tk == spec.task_key),
                    None,
                )
                if mapped_agent and mapped_agent in stage_statuses:
                    ag_st = stage_statuses[mapped_agent]
                    if ag_st == AgentStatus.COMPLETED.value and task.status not in {"completed", "dlq", "compensated"}:
                        task.status = "completed"
                        task.completed_at = task.completed_at or datetime.now(timezone.utc)
                    elif ag_st == AgentStatus.NEEDS_HUMAN.value and task.status not in {"dlq", "compensated"}:
                        task.status = "waiting_human"
                    elif ag_st in {AgentStatus.REWORK_REQUIRED.value, "rework_invalidated"} and task.status != "compensated":
                        task.status = "rework_required"
            tasks.append(task)

        self.db.flush()
        return tasks

    def _get_or_create_task(self, claim: Claim, task_key: str) -> OrchestrationTask:
        tasks = self.sync_task_schedule(claim)
        for t in tasks:
            if t.task_key == task_key:
                return t
        raise DomainError(ErrorCode.NOT_FOUND, f"Unknown task key '{task_key}'", status_code=404)

    def _task_condition_satisfied(self, claim: Claim, task_key: str) -> tuple[bool, str]:
        if task_key == "provider_coordination":
            ok = bool(
                claim.requires_mandatory_survey
                or claim.towing_needed
                or claim.ev_battery_impacted
                or (claim.risk_tier or "MEDIUM") in {"MEDIUM", "HIGH"}
            )
            return ok, (
                "Mandatory survey / EV / towing / standard-or-complex risk coordination required"
                if ok
                else "LOW RISK fast-track straight-through path: physical survey/towing bypassed"
            )
        if task_key == "damage_assessment":
            has_vehicle = bool(claim.vehicle_id or claim.vehicle_reg_input)
            photos_cnt = (
                self.db.query(Evidence)
                .filter(Evidence.claim_id == claim.id, Evidence.mime_type.like("image/%"))
                .count()
            )
            prior_task = (
                self.db.query(OrchestrationTask)
                .filter(
                    OrchestrationTask.claim_id == claim.id,
                    OrchestrationTask.task_key == "damage_assessment",
                    OrchestrationTask.attempt_count > 0,
                )
                .first()
            )
            prior_exec = (
                self.db.query(AgentExecutionRecord)
                .filter(
                    AgentExecutionRecord.claim_id == claim.id,
                    AgentExecutionRecord.agent_name == "damage_assessment",
                )
                .first()
            )
            if has_vehicle and (photos_cnt > 0 or prior_task is not None or prior_exec is not None):
                return True, f"Photos ({photos_cnt}) + vehicle details present"
            return False, "Conditional gate: awaiting uploaded vehicle damage photos + vehicle details"
        if task_key == "estimate_validation":
            est_cnt = self.db.query(Estimate).filter(Estimate.claim_id == claim.id).count()
            if est_cnt > 0:
                return True, f"{est_cnt} garage estimate(s) available"
            return False, "Awaiting garage repair estimate submission"
        if task_key == "human_approval_gate":
            approved = (
                self.db.query(Approval)
                .filter(Approval.claim_id == claim.id, Approval.decision == "approved")
                .first()
            )
            return (approved is not None), (
                "Independent Maker-Checker approval granted"
                if approved
                else "Approval gate: awaiting independent Checker DoA approval"
            )
        if task_key == "payment_execution":
            stl = (
                self.db.query(Settlement)
                .filter(Settlement.claim_id == claim.id, Settlement.approval_status == "approved")
                .first()
            )
            return (stl is not None), (
                "Approved settlement unlocked for Finance payout"
                if stl
                else "Approval gated: settlement must be approved before payment"
            )
        return True, "Condition satisfied"

    # ------------------------------------------------------------------
    # FNOL Initialization & Duplicate Claim Check
    # ------------------------------------------------------------------

    def initialize_claim_workflow(
        self,
        claim: Claim,
        *,
        fnol_facts: dict[str, Any],
        duplicate_candidate: Claim | None = None,
    ) -> AgentInvocationResponse:
        """Registers claim via SUBMITTED -> REGISTERED and schedules post-FNOL parallel tasks."""
        wf = dict(claim.workflow_state or {})
        wf.setdefault("workflow_run_id", f"wf-{uuid.uuid4().hex[:10]}")
        wf.setdefault("paused", False)
        wf.setdefault("state_history", [])
        wf.setdefault("parallel_waves", [])
        claim.workflow_state = _json_safe(wf)

        if claim.status == ClaimStatus.SUBMITTED.value:
            self.transition_state(
                claim,
                ClaimStatus.REGISTERED.value,
                reason="FNOL payload validated and registered without document blocking (IRDAI 2024)",
                trigger_event="FNOLSubmitted",
                next_expected_action="Run post-FNOL parallel validation wave (Policy, Docs, Duplicate, Customer Ack)",
            )

        self.sync_task_schedule(claim)
        resp = self.run_agent(
            claim,
            "fnol_concierge",
            enforce_dependencies=False,
            override_facts=fnol_facts,
            apply_state_progression=False,
        )

        # Persist duplicate_check result if candidate already identified during intake
        dup_task = self._get_or_create_task(claim, "duplicate_check")
        dup_task.status = "completed"
        dup_task.attempt_count = 1
        dup_task.started_at = dup_task.started_at or datetime.now(timezone.utc)
        dup_task.completed_at = datetime.now(timezone.utc)
        dup_task.output_payload = {
            "duplicate_found": duplicate_candidate is not None,
            "duplicate_candidate_claim_id": duplicate_candidate.id if duplicate_candidate else None,
            "duplicate_claim_number": duplicate_candidate.claim_number if duplicate_candidate else None,
        }
        claim.duplicate_candidate_claim_id = duplicate_candidate.id if duplicate_candidate else claim.duplicate_candidate_claim_id

        evaluate_and_persist_risk(
            self.db,
            claim,
            trigger_event="fnol_intake",
            actor_id=self.user.user_id,
            actor_role=self.user.role.value,
            record_decision=True,
            escalate_state=False,
        )

        self.db.flush()
        return resp

    # ------------------------------------------------------------------
    # Duplicate-Event Protection & Event-Driven Progression
    # ------------------------------------------------------------------

    def handle_event(
        self,
        claim: Claim,
        *,
        event_id: str,
        event_type: str,
        source: str = "api",
        payload: dict[str, Any] | None = None,
        auto_advance: bool = True,
    ) -> dict[str, Any]:
        """Processes an inbound workflow event with strict duplicate-event protection."""
        existing = (
            self.db.query(OrchestrationEventLog)
            .filter(
                OrchestrationEventLog.tenant_id == claim.tenant_id,
                OrchestrationEventLog.claim_id == claim.id,
                OrchestrationEventLog.event_id == event_id,
            )
            .first()
        )
        if existing:
            existing.duplicate_hits += 1
            record_audit_event(
                self.db,
                tenant_id=claim.tenant_id,
                claim_id=claim.id,
                actor_id="orchestrator",
                actor_role="orchestrator",
                action="DUPLICATE_EVENT_IGNORED",
                object_type="orchestration_event",
                object_id=existing.id,
                details={"event_id": event_id, "event_type": event_type, "duplicate_hits": existing.duplicate_hits},
            )
            self.db.flush()
            return {
                "duplicate_ignored": True,
                "event_id": event_id,
                "event_type": event_type,
                "processing_status": "duplicate_ignored",
                "duplicate_hits": existing.duplicate_hits,
                "claim_status": claim.status,
                "original_recorded_at": existing.created_at.isoformat(),
            }

        wf = dict(claim.workflow_state or {})
        is_paused = bool(wf.get("paused", False))
        evt_row = OrchestrationEventLog(
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            event_id=event_id,
            event_type=event_type,
            source=source,
            payload=_json_safe(payload or {}),
            processing_status="paused_queued" if is_paused else "processed",
            resulting_state=claim.status,
        )
        self.db.add(evt_row)
        self.db.flush()

        record_audit_event(
            self.db,
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            actor_id="orchestrator",
            actor_role="orchestrator",
            action="ORCHESTRATION_EVENT_ACCEPTED",
            object_type="orchestration_event",
            object_id=evt_row.id,
            details={"event_id": event_id, "event_type": event_type, "source": source},
        )

        orchestration_summary = None
        if auto_advance and not is_paused:
            orchestration_summary = self.orchestrate_claim(claim)
            evt_row.resulting_state = claim.status

        self.db.flush()
        return {
            "duplicate_ignored": False,
            "event_id": event_id,
            "event_type": event_type,
            "processing_status": evt_row.processing_status,
            "claim_status": claim.status,
            "orchestration": orchestration_summary,
        }

    # ------------------------------------------------------------------
    # Dependency Management & Rework Loops
    # ------------------------------------------------------------------

    def check_dependencies(self, claim: Claim, agent_name: str) -> tuple[bool, list[str]]:
        spec = AGENT_CAPABILITY_CONTRACTS.get(agent_name)
        if not spec:
            raise DomainError(ErrorCode.NOT_FOUND, f"Unknown agent '{agent_name}'", status_code=404)

        wf = claim.workflow_state or {}
        published = wf.get("published_results", {})
        statuses = wf.get("stage_statuses", {})
        rework_queue = [r for r in wf.get("rework_queue", []) if r.get("status") == "open"]

        missing: list[str] = []
        if wf.get("paused"):
            missing.append(f"workflow_paused ({wf.get('pause_reason', 'manual pause')})")

        for req_rework in rework_queue:
            to_agent = req_rework.get("to_agent", "")
            if to_agent != agent_name and req_rework.get("blocking", True):
                # Blocking rework on an earlier or assessment stage halts downstream/peer progression
                if (
                    to_agent in spec.depends_on
                    or agent_name in _downstream_dependents(to_agent)
                    or (to_agent == "damage_assessment" and agent_name == "fraud_intelligence")
                ):
                    missing.append(f"open_rework:{to_agent} ({req_rework.get('reason_code')})")

        for dep in spec.depends_on:
            dep_status = statuses.get(dep)
            if dep == "provider_coordination" and dep_status == "skipped_fast_track":
                continue
            if dep not in published:
                missing.append(f"{dep} (not published)")
                continue
            dep_status = statuses.get(dep, published[dep].get("status", "unknown"))
            if dep_status in _BLOCKING_UPSTREAM_STATUSES:
                missing.append(f"{dep} ({dep_status})")
                continue
            if dep == "document_intelligence" and dep_status == AgentStatus.NEEDS_HUMAN.value:
                missing.append("document_intelligence (needs_human: conflict/injection unresolved)")
            if dep == "coverage_intelligence" and dep_status == AgentStatus.NEEDS_HUMAN.value:
                missing.append("coverage_intelligence (needs_human: coverage ambiguity unresolved)")

        return (len(missing) == 0, missing)

    def apply_rework_request(self, claim: Claim, rework: ReworkRequest) -> dict[str, Any]:
        spec = AGENT_CAPABILITY_CONTRACTS.get(rework.from_agent)
        if spec and rework.to_agent not in spec.can_request_rework_from and self.user.role.value not in {"claims_manager", "admin"}:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR,
                f"Agent '{rework.from_agent}' cannot request rework from '{rework.to_agent}'",
                status_code=400,
            )

        wf = dict(claim.workflow_state or {})
        rework_queue = list(wf.get("rework_queue", []))
        rework_id = f"rwk-{uuid.uuid4().hex[:8]}"
        entry = {
            "id": rework_id,
            "from_agent": rework.from_agent,
            "to_agent": rework.to_agent,
            "reason_code": rework.reason_code,
            "instructions": rework.instructions,
            "blocking": rework.blocking,
            "status": "open",
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }
        rework_queue.append(entry)

        statuses = dict(wf.get("stage_statuses", {}))
        invalidated = _downstream_dependents(rework.to_agent)
        for dep in invalidated:
            if dep in statuses:
                statuses[dep] = "rework_invalidated"
        statuses[rework.to_agent] = AgentStatus.REWORK_REQUIRED.value

        wf["rework_queue"] = rework_queue
        wf["stage_statuses"] = statuses
        claim.workflow_state = _json_safe(wf)
        self.sync_task_schedule(claim)

        executor = ControlledActionExecutor(self.db, claim, self.user)
        executor.create_claim_task(
            agent_name=rework.from_agent,
            task_type="rework",
            title=f"Rework Required -> {rework.to_agent} ({rework.reason_code})",
            description=rework.instructions,
            assigned_role="claims_handler",
            priority="high",
            reason_code=rework.reason_code,
            due_hours=8,
            metadata={"rework_id": rework_id, "to_agent": rework.to_agent},
        )

        if rework.to_agent in {"document_intelligence", "coverage_intelligence"}:
            self._safe_transition(
                claim,
                ClaimStatus.HUMAN_REVIEW.value,
                reason=f"Blocking rework requested to {rework.to_agent}",
                trigger_event="AgentReworkRequested",
                next_expected_action=f"Rework requested by {rework.from_agent} -> {rework.to_agent}",
            )
        elif rework.to_agent == "damage_assessment":
            self._safe_transition(
                claim,
                ClaimStatus.ASSESSMENT.value,
                reason=f"Rework requested back to damage_assessment ({rework.reason_code})",
                trigger_event="AgentReworkRequested",
                next_expected_action=f"Rework requested by {rework.from_agent} -> {rework.to_agent}: {rework.instructions[:100]}",
            )

        claim.next_expected_action = f"Rework requested by {rework.from_agent} -> {rework.to_agent}: {rework.instructions[:100]}"
        emit_outbox_event(
            self.db,
            tenant_id=claim.tenant_id,
            aggregate_id=claim.id,
            event_type="AgentReworkRequested",
            payload=entry,
        )
        record_audit_event(
            self.db,
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            actor_id=self.user.user_id,
            actor_role=self.user.role.value,
            action="AGENT_REWORK_REQUESTED",
            object_type="claim",
            object_id=claim.id,
            after_state={"rework_id": rework_id, "to_agent": rework.to_agent, "invalidated": invalidated},
        )
        self.db.flush()
        return {"rework": entry, "invalidated_downstream_stages": invalidated}

    # ------------------------------------------------------------------
    # Pause, Resume, Recovery, DLQ & Compensation Workflows
    # ------------------------------------------------------------------

    def pause_workflow(self, claim: Claim, *, reason: str = "Paused for manual operational review") -> dict[str, Any]:
        wf = dict(claim.workflow_state or {})
        wf["paused"] = True
        wf["pause_reason"] = reason
        wf["paused_at"] = datetime.now(timezone.utc).isoformat()
        wf["paused_by"] = self.user.user_id
        claim.workflow_state = _json_safe(wf)

        paused_timers = pause_active_sla_timers(self.db, claim_id=claim.id, reason=reason)
        tasks = (
            self.db.query(OrchestrationTask)
            .filter(OrchestrationTask.claim_id == claim.id, OrchestrationTask.status.in_(["pending", "scheduled"]))
            .all()
        )
        for t in tasks:
            t.status = "paused"

        claim.next_expected_action = f"WORKFLOW PAUSED: {reason[:160]}"
        emit_outbox_event(
            self.db,
            tenant_id=claim.tenant_id,
            aggregate_id=claim.id,
            event_type="WorkflowPaused",
            payload={"reason": reason, "paused_timers": paused_timers},
        )
        record_audit_event(
            self.db,
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            actor_id=self.user.user_id,
            actor_role=self.user.role.value,
            action="WORKFLOW_PAUSED",
            object_type="claim",
            object_id=claim.id,
            details={"reason": reason, "paused_timers": paused_timers, "paused_tasks": len(tasks)},
        )
        self.db.flush()
        return {
            "claim_id": claim.id,
            "paused": True,
            "pause_reason": reason,
            "paused_timers": paused_timers,
            "paused_tasks": len(tasks),
        }

    def resume_workflow(
        self,
        claim: Claim,
        *,
        resolution_notes: str = "Resumed workflow from checkpoint",
        run_ready_stages: bool = True,
    ) -> dict[str, Any]:
        wf = dict(claim.workflow_state or {})
        was_paused = bool(wf.get("paused", False))
        wf["paused"] = False
        wf["resumed_at"] = datetime.now(timezone.utc).isoformat()
        wf["resumed_by"] = self.user.user_id
        wf.pop("pause_reason", None)
        claim.workflow_state = _json_safe(wf)

        resumed_timers = resume_paused_sla_timers(self.db, claim_id=claim.id)
        paused_tasks = (
            self.db.query(OrchestrationTask)
            .filter(OrchestrationTask.claim_id == claim.id, OrchestrationTask.status == "paused")
            .all()
        )
        for t in paused_tasks:
            t.status = "pending"

        emit_outbox_event(
            self.db,
            tenant_id=claim.tenant_id,
            aggregate_id=claim.id,
            event_type="WorkflowResumed",
            payload={"was_paused": was_paused, "resumed_timers": resumed_timers, "notes": resolution_notes},
        )
        record_audit_event(
            self.db,
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            actor_id=self.user.user_id,
            actor_role=self.user.role.value,
            action="WORKFLOW_RESUMED",
            object_type="claim",
            object_id=claim.id,
            details={"was_paused": was_paused, "resumed_timers": resumed_timers, "notes": resolution_notes},
        )
        resolve_human_intervention(
            self.db, claim_id=claim.id, actor_id=self.user.user_id, actor_role=self.user.role.value, decision="workflow_resumed"
        )
        self.db.flush()

        resumed_summary = None
        if run_ready_stages:
            resumed_summary = self.orchestrate_claim(claim)

        return {
            "claim_id": claim.id,
            "was_paused": was_paused,
            "resumed_timers": resumed_timers,
            "restored_tasks": len(paused_tasks),
            "orchestration": resumed_summary,
        }

    def recover_orchestration(
        self,
        claim: Claim,
        *,
        resolution_notes: str = "Recovered and cleared transient holds / rework / DLQ",
        resume_pipeline: bool = True,
    ) -> dict[str, Any]:
        wf = dict(claim.workflow_state or {})
        wf["paused"] = False
        wf.pop("pause_reason", None)

        rework_queue = list(wf.get("rework_queue", []))
        resolved_reworks = 0
        for item in rework_queue:
            if item.get("status") == "open":
                item["status"] = "resolved"
                item["resolved_at"] = datetime.now(timezone.utc).isoformat()
                item["resolution_notes"] = resolution_notes
                resolved_reworks += 1

        escalations = list(wf.get("escalations", []))
        cleared_escalations = 0
        for esc in escalations:
            if esc.get("status") == "open":
                esc["status"] = "recovered"
                esc["recovered_at"] = datetime.now(timezone.utc).isoformat()
                cleared_escalations += 1

        statuses = dict(wf.get("stage_statuses", {}))
        for k, v in list(statuses.items()):
            if v in {AgentStatus.TIMED_OUT.value, AgentStatus.FAILED.value, AgentStatus.REWORK_REQUIRED.value, "rework_invalidated", "dlq"}:
                del statuses[k]
                wf.get("published_results", {}).pop(k, None)

        wf["rework_queue"] = rework_queue
        wf["escalations"] = escalations
        wf["stage_statuses"] = statuses
        claim.workflow_state = _json_safe(wf)

        resume_paused_sla_timers(self.db, claim_id=claim.id)

        dlq_items = (
            self.db.query(DeadLetterRecord)
            .filter(DeadLetterRecord.claim_id == claim.id, DeadLetterRecord.status == "open")
            .all()
        )
        for dlq in dlq_items:
            dlq.status = "requeued"
            dlq.resolved_by = self.user.user_id
            dlq.resolution_notes = resolution_notes
            dlq.resolved_at = datetime.now(timezone.utc)

        orch_tasks = (
            self.db.query(OrchestrationTask)
            .filter(
                OrchestrationTask.claim_id == claim.id,
                OrchestrationTask.status.in_(["timed_out", "failed", "dlq", "rework_required", "paused"]),
            )
            .all()
        )
        for ot in orch_tasks:
            ot.status = "pending"
            ot.error_message = None

        open_tasks = (
            self.db.query(ClaimTask)
            .filter(
                ClaimTask.claim_id == claim.id,
                ClaimTask.task_type.in_(["rework", "orchestration_escalation", "dlq_intervention"]),
                ClaimTask.status == "open",
            )
            .all()
        )
        for t in open_tasks:
            t.status = "completed"
            t.completed_at = datetime.now(timezone.utc)

        record_audit_event(
            self.db,
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            actor_id=self.user.user_id,
            actor_role=self.user.role.value,
            action="ORCHESTRATION_RECOVERED",
            object_type="claim",
            object_id=claim.id,
            details={
                "resolved_reworks": resolved_reworks,
                "cleared_escalations": cleared_escalations,
                "requeued_dlq": len(dlq_items),
                "notes": resolution_notes,
            },
        )
        emit_outbox_event(
            self.db,
            tenant_id=claim.tenant_id,
            aggregate_id=claim.id,
            event_type="OrchestrationRecovered",
            payload={
                "resolved_reworks": resolved_reworks,
                "cleared_escalations": cleared_escalations,
                "requeued_dlq": len(dlq_items),
            },
        )
        self.db.flush()

        resumed_summary = None
        if resume_pipeline:
            resumed_summary = self.orchestrate_claim(claim)

        return {
            "resolved_reworks": resolved_reworks,
            "cleared_escalations": cleared_escalations,
            "requeued_dlq": len(dlq_items),
            "resumed": resumed_summary,
        }

    def replay_dlq_item(
        self,
        dlq: DeadLetterRecord,
        *,
        resolution_notes: str = "Replayed from Dead-Letter Queue",
    ) -> dict[str, Any]:
        claim = self.db.query(Claim).filter(Claim.id == dlq.claim_id).first()
        if not claim:
            raise DomainError(ErrorCode.NOT_FOUND, "Claim for DLQ item not found", status_code=404)

        dlq.status = "requeued"
        dlq.resolved_by = self.user.user_id
        dlq.resolution_notes = resolution_notes
        dlq.resolved_at = datetime.now(timezone.utc)

        if dlq.task_id:
            ot = self.db.query(OrchestrationTask).filter(OrchestrationTask.id == dlq.task_id).first()
            if ot:
                ot.status = "pending"
                ot.error_message = None

        wf = dict(claim.workflow_state or {})
        statuses = dict(wf.get("stage_statuses", {}))
        agent_name = dlq.agent_or_service
        if agent_name in statuses:
            del statuses[agent_name]
            wf.get("published_results", {}).pop(agent_name, None)
        for esc in wf.get("escalations", []):
            if esc.get("agent_name") == agent_name and esc.get("status") == "open":
                esc["status"] = "recovered"
                esc["recovered_at"] = datetime.now(timezone.utc).isoformat()
        wf["stage_statuses"] = statuses
        wf["paused"] = False
        claim.workflow_state = _json_safe(wf)

        record_audit_event(
            self.db,
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            actor_id=self.user.user_id,
            actor_role=self.user.role.value,
            action="DLQ_ITEM_REPLAYED",
            object_type="dead_letter_record",
            object_id=dlq.id,
            details={"task_key": dlq.task_key, "agent": agent_name, "notes": resolution_notes},
        )
        self.db.flush()

        if agent_name in AGENT_REGISTRY:
            resp = self.run_agent(claim, agent_name, enforce_dependencies=True)
            return {"dlq_id": dlq.id, "status": dlq.status, "agent_response": resp.model_dump()}

        summary = self.orchestrate_claim(claim)
        return {"dlq_id": dlq.id, "status": dlq.status, "orchestration": summary}

    def run_compensation(
        self,
        claim: Claim,
        *,
        trigger_reason: str,
        target_state: str = ClaimStatus.HUMAN_REVIEW.value,
    ) -> dict[str, Any]:
        """Executes deterministic Saga compensation across reservations, approvals, and tasks."""
        failed_state = claim.status
        executed_actions: list[dict[str, Any]] = []

        # 1. Release active surveyor assignments & decrement provider active_load
        open_surveys = (
            self.db.query(SurveyAssignment)
            .filter(
                SurveyAssignment.claim_id == claim.id,
                SurveyAssignment.status.in_(["assigned", "accepted", "inspected"]),
                SurveyAssignment.signed_by_surveyor.is_(False),
            )
            .all()
        )
        for sa in open_surveys:
            sa.status = "cancelled_compensated"
            prov = self.db.query(Provider).filter(Provider.id == sa.surveyor_id).first()
            if prov and prov.active_load > 0:
                prov.active_load = max(0, prov.active_load - 1)
            comp = CompensationLog(
                tenant_id=claim.tenant_id,
                claim_id=claim.id,
                trigger_reason=trigger_reason,
                failed_state=failed_state,
                compensating_action="release_surveyor_assignment_and_load",
                target_object_type="survey_assignment",
                target_object_id=sa.id,
                status="executed",
                details={"surveyor_id": sa.surveyor_id},
            )
            self.db.add(comp)
            executed_actions.append({"action": comp.compensating_action, "target_id": sa.id})
        if open_surveys:
            claim.assigned_surveyor_id = None

        # 2. Release unconfirmed garage reservation if present
        if claim.assigned_garage_id and not self.db.query(Payment).filter(Payment.claim_id == claim.id, Payment.status == "confirmed").first():
            gar_id = claim.assigned_garage_id
            claim.assigned_garage_id = None
            comp_g = CompensationLog(
                tenant_id=claim.tenant_id,
                claim_id=claim.id,
                trigger_reason=trigger_reason,
                failed_state=failed_state,
                compensating_action="release_garage_intake_allocation",
                target_object_type="provider",
                target_object_id=gar_id,
                status="executed",
                details={"garage_id": gar_id},
            )
            self.db.add(comp_g)
            executed_actions.append({"action": comp_g.compensating_action, "target_id": gar_id})

        # 3. Void pending Maker-Checker Approvals & supersede unapproved Settlements
        pending_apps = (
            self.db.query(Approval)
            .filter(Approval.claim_id == claim.id, Approval.decision == "pending")
            .all()
        )
        for app in pending_apps:
            app.decision = "voided_compensated"
            app.rationale = f"Voided by compensation workflow: {trigger_reason}"
            app.decided_at = datetime.now(timezone.utc)
            comp_a = CompensationLog(
                tenant_id=claim.tenant_id,
                claim_id=claim.id,
                trigger_reason=trigger_reason,
                failed_state=failed_state,
                compensating_action="void_pending_doa_approval",
                target_object_type="approval",
                target_object_id=app.id,
                status="executed",
                details={"settlement_id": app.settlement_id},
            )
            self.db.add(comp_a)
            executed_actions.append({"action": comp_a.compensating_action, "target_id": app.id})

        pending_stls = (
            self.db.query(Settlement)
            .filter(Settlement.claim_id == claim.id, Settlement.approval_status.in_(["pending_maker", "pending_checker"]))
            .all()
        )
        for stl in pending_stls:
            stl.approval_status = "superseded_compensated"
            comp_s = CompensationLog(
                tenant_id=claim.tenant_id,
                claim_id=claim.id,
                trigger_reason=trigger_reason,
                failed_state=failed_state,
                compensating_action="supersede_pending_settlement",
                target_object_type="settlement",
                target_object_id=stl.id,
                status="executed",
                details={"net_payable_inr": str(stl.net_payable_inr)},
            )
            self.db.add(comp_s)
            executed_actions.append({"action": comp_s.compensating_action, "target_id": stl.id})

        # 4. Freeze any timed-out payment instructions cleanly
        pending_pmts = (
            self.db.query(Payment)
            .filter(Payment.claim_id == claim.id, Payment.status == "timeout_reconcile_pending")
            .all()
        )
        for pmt in pending_pmts:
            comp_p = CompensationLog(
                tenant_id=claim.tenant_id,
                claim_id=claim.id,
                trigger_reason=trigger_reason,
                failed_state=failed_state,
                compensating_action="freeze_pending_payment_prevent_double_debit",
                target_object_type="payment",
                target_object_id=pmt.id,
                status="executed",
                details={"idempotency_key": pmt.idempotency_key, "ref": pmt.gateway_reference},
            )
            self.db.add(comp_p)
            executed_actions.append({"action": comp_p.compensating_action, "target_id": pmt.id})

        # 5. Mark open orchestration tasks & open DLQ items as compensated
        open_ot = (
            self.db.query(OrchestrationTask)
            .filter(
                OrchestrationTask.claim_id == claim.id,
                OrchestrationTask.status.in_(["pending", "scheduled", "waiting_human", "timed_out", "dlq", "paused"]),
            )
            .all()
        )
        for ot in open_ot:
            ot.status = "compensated"
            ot.error_message = f"Compensated: {trigger_reason}"

        open_dlqs = (
            self.db.query(DeadLetterRecord)
            .filter(DeadLetterRecord.claim_id == claim.id, DeadLetterRecord.status == "open")
            .all()
        )
        for dlq in open_dlqs:
            dlq.status = "compensated"
            dlq.resolved_by = self.user.user_id
            dlq.resolution_notes = f"Compensated: {trigger_reason}"
            dlq.resolved_at = datetime.now(timezone.utc)

        if not executed_actions:
            comp_noop = CompensationLog(
                tenant_id=claim.tenant_id,
                claim_id=claim.id,
                trigger_reason=trigger_reason,
                failed_state=failed_state,
                compensating_action="checkpoint_rollback_and_human_hold",
                target_object_type="claim",
                target_object_id=claim.id,
                status="executed",
                details={"note": "No open external allocations to unwind; claim moved safely to hold."},
            )
            self.db.add(comp_noop)
            executed_actions.append({"action": comp_noop.compensating_action, "target_id": claim.id})

        self._safe_transition(
            claim,
            target_state,
            reason=f"Compensation workflow executed: {trigger_reason}",
            trigger_event="CompensationExecuted",
            next_expected_action=f"COMPENSATED ({len(executed_actions)} rollback steps): {trigger_reason[:120]}",
        )
        emit_outbox_event(
            self.db,
            tenant_id=claim.tenant_id,
            aggregate_id=claim.id,
            event_type="CompensationExecuted",
            payload={"trigger_reason": trigger_reason, "actions": executed_actions},
        )
        record_audit_event(
            self.db,
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            actor_id=self.user.user_id,
            actor_role=self.user.role.value,
            action="COMPENSATION_WORKFLOW_EXECUTED",
            object_type="claim",
            object_id=claim.id,
            details={"trigger_reason": trigger_reason, "actions": executed_actions},
        )
        self.db.flush()
        return {
            "claim_id": claim.id,
            "claim_status": claim.status,
            "trigger_reason": trigger_reason,
            "actions_executed": executed_actions,
        }

    # ------------------------------------------------------------------
    # Single-Agent & Parallel Wave Execution with Retries + Backoff + DLQ
    # ------------------------------------------------------------------

    def _retry_strategy_for_agent(self, claim: Claim, agent_name: str) -> RetryStrategySpec:
        spec = AGENT_CAPABILITY_CONTRACTS[agent_name]
        canonical = to_canonical_state(claim.status)
        state_spec = WORKFLOW_STATE_SPECS.get(canonical)
        if state_spec and state_spec.retry_strategy.max_retries > 0:
            return RetryStrategySpec(
                max_retries=max(spec.max_retries, state_spec.retry_strategy.max_retries),
                base_delay_ms=state_spec.retry_strategy.base_delay_ms,
                backoff_multiplier=state_spec.retry_strategy.backoff_multiplier,
                max_delay_ms=state_spec.retry_strategy.max_delay_ms,
                jitter_pct=state_spec.retry_strategy.jitter_pct,
                dlq_on_exhaustion=True,
            )
        return RetryStrategySpec(max_retries=spec.max_retries, base_delay_ms=200, backoff_multiplier=2.0, max_delay_ms=3000)

    def _replay_intent_actions(
        self,
        claim: Claim,
        agent_name: str,
        resp: AgentInvocationResponse,
        executor: ControlledActionExecutor,
    ) -> AgentInvocationResponse:
        """Persists stateless action intents produced on worker threads onto the main DB transaction."""
        real_actions: list[AgentActionExecution] = []
        for act in resp.actions_executed:
            if act.status != "simulated" and act.target_id and not act.target_id.startswith("sim-"):
                real_actions.append(act)
                continue
            atype = act.action_type
            pl = act.payload or {}
            if atype == "request_documents":
                real_actions.append(
                    executor.request_documents(
                        agent_name=agent_name,
                        documents=list(pl.get("documents", [])),
                        reason_code=str(pl.get("reason_code", "DOCUMENTS_REQUESTED")),
                        channel=str(pl.get("channel", "whatsapp")),
                    )
                )
            elif atype == "create_claim_task":
                real_actions.append(
                    executor.create_claim_task(
                        agent_name=agent_name,
                        task_type=str(pl.get("task_type", "agent_action")),
                        title=act.summary.replace("[Simulated] Create task ", "").strip("'"),
                        description=act.summary,
                        assigned_role=str(pl.get("assigned_role", "claims_handler")),
                        priority=str(pl.get("priority", "medium")),
                        reason_code=str(pl.get("reason_code", "AGENT_ACTION")),
                    )
                )
            elif atype == "dispatch_towing":
                real_actions.append(
                    executor.dispatch_towing(
                        agent_name=agent_name,
                        ev_flatbed=bool(pl.get("ev_flatbed", False)),
                    )
                )
            elif atype == "send_customer_update":
                res = resp.result or {}
                real_actions.append(
                    executor.send_customer_update(
                        agent_name=agent_name,
                        channel=str(pl.get("requested_channel") or pl.get("channel") or res.get("channel") or "whatsapp"),
                        language=str(pl.get("language") or res.get("language") or claim.preferred_language),
                        template_id=f"PROACTIVE_{str(res.get('trigger_event', 'status_update')).upper()}",
                        subject=str(res.get("subject") or f"Update for {claim.claim_number}"),
                        body=str(res.get("draft_message") or act.summary),
                        is_adverse=bool(pl.get("is_adverse", False)),
                        trigger_event=str(pl.get("trigger_event") or res.get("trigger_event") or "status_update"),
                        consent_whatsapp=bool(pl.get("consent_whatsapp", res.get("consent_whatsapp", claim.whatsapp_consent))),
                        context_summary=dict(pl.get("context_summary") or {}),
                    )
                )
            else:
                real_actions.append(act)

        return resp.model_copy(update={"actions_executed": real_actions})

    def _persist_agent_side_effects(
        self,
        claim: Claim,
        agent_name: str,
        resp: AgentInvocationResponse,
        *,
        attempt_count: int,
        retry_history: list[dict[str, Any]],
        error_message: str | None = None,
        input_facts: dict[str, Any] | None = None,
    ) -> None:
        if agent_name == "damage_assessment" and resp.status in {AgentStatus.COMPLETED, AgentStatus.NEEDS_HUMAN}:
            claim.damage_report = _json_safe(resp.result)
            obs_list = resp.result.get("observations", [])
            if obs_list:
                self.db.query(DamageAssessment).filter(
                    DamageAssessment.claim_id == claim.id, DamageAssessment.reviewer_outcome == "pending"
                ).delete()
                for obs in obs_list:
                    ev_refs = list(obs.get("evidence") or [])
                    first_ev_id = ev_refs[0].get("evidence_id") if ev_refs else None
                    cost = dict(obs.get("estimated_cost") or {})
                    self.db.add(
                        DamageAssessment(
                            tenant_id=claim.tenant_id,
                            claim_id=claim.id,
                            evidence_id=str(first_ev_id) if first_ev_id else None,
                            component_name=obs["component_name"],
                            part_code=obs.get("part_code"),
                            damage_location=str(obs.get("damage_location", obs.get("zone", "front_center"))),
                            damage_severity=str(obs.get("damage_severity", "moderate")),
                            repairability=str(obs.get("repairability", "repair")),
                            damage_class=obs["damage_class"],
                            observation_type=obs["observation_type"],
                            recommended_action=obs["recommended_action"],
                            visible_damage=str(obs.get("visible_damage", "")),
                            possible_hidden_damage=str(obs.get("possible_hidden_damage", "")),
                            image_quality=str(obs.get("image_quality", "good")),
                            confidence=Decimal(str(obs.get("component_confidence", obs["confidence"]))),
                            confidence_factors=_json_safe(obs.get("confidence_factors") or {}),
                            evidence_refs=_json_safe(ev_refs),
                            estimated_parts_inr=Decimal(str(cost.get("parts_oem_inr", "0.00"))),
                            estimated_labour_inr=Decimal(str(cost.get("labour_inr", "0.00"))),
                            estimated_paint_inr=Decimal(str(cost.get("paint_inr", "0.00"))),
                            limitations=obs["limitations"],
                            model_version=str(resp.result.get("model_version", "cv-damage-vision-v3")),
                        )
                    )
                self.db.flush()

        if agent_name == "coverage_intelligence" and resp.status in {AgentStatus.COMPLETED, AgentStatus.NEEDS_HUMAN}:
            claim.coverage_factsheet = _json_safe(resp.model_dump())

        if agent_name == "claim_triage" and resp.status == AgentStatus.COMPLETED:
            res_data = resp.result
            if "severity_band" in res_data:
                claim.severity_band = res_data["severity_band"]
                claim.queue_name = res_data["recommended_queue"]
                claim.requires_mandatory_survey = bool(res_data["requires_mandatory_survey"])
            claim.triage_summary = _json_safe(resp.model_dump())

        if agent_name == "fraud_intelligence":
            for ind in resp.result.get("indicators", []):
                code = ind.get("indicator_code")
                if not code:
                    continue
                exists = (
                    self.db.query(FraudAlert)
                    .filter(FraudAlert.claim_id == claim.id, FraudAlert.indicator_code == code)
                    .first()
                )
                if not exists:
                    self.db.add(
                        FraudAlert(
                            tenant_id=claim.tenant_id,
                            claim_id=claim.id,
                            indicator_code=code,
                            title=ind.get("title", code),
                            severity_band=ind.get("severity_band", "medium"),
                            confidence=Decimal(str(ind.get("confidence", "0.700"))),
                            evidence_summary=ind.get("evidence_summary", ""),
                            benign_explanation=ind.get("benign_explanation", "Requires verification."),
                            recommended_action=ind.get("recommended_action", "Review with SIU"),
                            entity_links=ind.get("entity_links", []),
                            status="new",
                        )
                    )
            self.db.flush()

        record_agent_publication(
            self.db,
            claim=claim,
            agent_name=agent_name,
            response=resp,
            dependencies_satisfied=True,
            error_message=error_message,
            input_facts=input_facts,
            retry_count=len(retry_history),
        )

        # Update scheduled OrchestrationTask record
        task_key = _AGENT_TO_TASK_KEY.get(agent_name)
        if task_key:
            ot = self._get_or_create_task(claim, task_key)
            ot.attempt_count = attempt_count
            ot.retry_history = _json_safe(retry_history)
            ot.backoff_delay_ms = retry_history[-1]["backoff_delay_ms"] if retry_history else 0
            ot.started_at = ot.started_at or datetime.now(timezone.utc)
            ot.output_payload = _json_safe(resp.published_result or resp.result)
            if resp.status == AgentStatus.COMPLETED:
                ot.status = "completed"
                ot.completed_at = datetime.now(timezone.utc)
                ot.error_message = None
            elif resp.status == AgentStatus.NEEDS_HUMAN:
                ot.status = "waiting_human"
            elif resp.status == AgentStatus.REWORK_REQUIRED:
                ot.status = "rework_required"
            elif resp.status in {AgentStatus.TIMED_OUT, AgentStatus.FAILED}:
                ot.status = "dlq"
                ot.error_message = error_message or "Retries exhausted"

        for rw in resp.rework_requests:
            if rw.blocking:
                self.apply_rework_request(claim, rw)

    def _apply_post_agent_state_transition(self, claim: Claim, agent_name: str, resp: AgentInvocationResponse) -> None:
        """Orchestrator deterministically drives ClaimStatus after an agent completes."""
        if agent_name == "document_intelligence":
            if resp.status == AgentStatus.NEEDS_HUMAN:
                self._safe_transition(
                    claim,
                    ClaimStatus.HUMAN_REVIEW.value,
                    reason="Document extraction detected conflict, prompt injection, or missing core docs",
                    trigger_event="DocumentExtractionHeld",
                    next_expected_action="Human adjuster to verify RC/Policy facts or quarantine notice",
                )
            elif claim.status in {ClaimStatus.REGISTERED.value, ClaimStatus.EVIDENCE_PENDING.value}:
                self._safe_transition(
                    claim,
                    ClaimStatus.VALIDATION.value,
                    reason="Document extraction completed; progressing in VALIDATION",
                    trigger_event="DocumentExtracted",
                )

        elif agent_name == "coverage_intelligence":
            if resp.status in {AgentStatus.NEEDS_HUMAN, AgentStatus.REWORK_REQUIRED}:
                self._safe_transition(
                    claim,
                    ClaimStatus.HUMAN_REVIEW.value,
                    reason="Coverage ambiguity, inactive policy, or TP legal review gate triggered",
                    trigger_event="CoverageAmbiguityGate",
                    next_expected_action="Resolve coverage ambiguity / legal TP review before triage",
                )
            elif claim.status in {ClaimStatus.REGISTERED.value, ClaimStatus.EVIDENCE_PENDING.value}:
                self._safe_transition(
                    claim,
                    ClaimStatus.VALIDATION.value,
                    reason="Policy validation passed",
                    trigger_event="PolicyValidated",
                )

        elif agent_name == "claim_triage" and resp.status == AgentStatus.COMPLETED:
            self._safe_transition(
                claim,
                ClaimStatus.TRIAGE.value,
                reason="Policy validation and extracted evidence satisfied triage entry conditions",
                trigger_event="TriageStarted",
            )
            track = str(resp.result.get("recommended_triage_track", ""))
            if track not in {t.value for t in TriageTrack}:
                if claim.injury_or_fatality or claim.claim_type == "third_party" or claim.multiple_vehicles_involved:
                    track = TriageTrack.INVESTIGATION_REQUIRED.value
                elif claim.requires_mandatory_survey or (claim.risk_tier or "MEDIUM") == "MEDIUM":
                    track = TriageTrack.SURVEY_REQUIRED.value
                else:
                    track = TriageTrack.FAST_TRACK.value

            wf = dict(claim.workflow_state or {})
            wf["triage_track"] = track
            claim.workflow_state = _json_safe(wf)
            self._safe_transition(
                claim,
                track,
                reason=f"ClaimTriage routed claim ({resp.result.get('risk_tier', claim.risk_tier)} RISK -> {resp.result.get('operational_path', claim.operational_path)}) to branch {track}",
                trigger_event="ClaimTriaged",
                next_expected_action=f"Triage track: {track} ({resp.result.get('recommended_queue', '')})",
            )

        elif agent_name == "provider_coordination":
            from services.claims.models import EcosystemCoordination
            from services.workflow.ecosystem import coordinate_claim_ecosystem

            if resp.status == AgentStatus.COMPLETED:
                existing_eco = (
                    self.db.query(EcosystemCoordination)
                    .filter(EcosystemCoordination.claim_id == claim.id)
                    .first()
                )
                if not existing_eco or (existing_eco.garage_id is None and existing_eco.surveyor_id is None):
                    try:
                        coordinate_claim_ecosystem(
                            self.db,
                            claim,
                            user=self.user,
                            preferred_garage_id=claim.assigned_garage_id,
                            preferred_surveyor_id=claim.assigned_surveyor_id,
                            towing_needed=bool(resp.result.get("towing_coordinated", claim.towing_needed)),
                            notify_customer=False,
                        )
                    except DomainError:
                        pass
                if claim.requires_mandatory_survey:
                    self._safe_transition(
                        claim,
                        ClaimStatus.SURVEY_REQUIRED.value,
                        reason="Verified IIISLA surveyor & EV-safe garage coordinated across ecosystem",
                        trigger_event="ProviderCoordinated",
                        next_expected_action="Run conditional damage assessment & parallel fraud analysis",
                    )

        elif agent_name == "damage_assessment":
            if resp.status == AgentStatus.NEEDS_HUMAN:
                recapture = resp.result.get("recapture_required_files", [])
                reasons = resp.result.get("human_assessor_routing", {}).get("trigger_reasons", [])
                self._safe_transition(
                    claim,
                    ClaimStatus.HUMAN_REVIEW.value,
                    reason=(
                        "Image quality gate flagged blurry/missing angles requiring photo recapture"
                        if recapture
                        else f"Uncertain damage components or inconsistencies routed to human assessor: {'; '.join(reasons[:2])}"
                    ),
                    trigger_event="ImageRecaptureRequired" if recapture else "UncertainDamageRoutedToAssessor",
                    next_expected_action=(
                        "Customer to recapture daylight photos"
                        if recapture
                        else "Human assessor (surveyor) to review uncertain components & inconsistencies"
                    ),
                )
            elif resp.status == AgentStatus.COMPLETED:
                self._safe_transition(
                    claim,
                    ClaimStatus.ASSESSMENT.value,
                    reason="Visual damage assessment observations persisted",
                    trigger_event="DamageAssessed",
                )

        elif agent_name == "fraud_intelligence":
            if resp.status == AgentStatus.NEEDS_HUMAN and resp.result.get("alert_count", 0) > 0:
                wf = dict(claim.workflow_state or {})
                wf["siu_alert_active"] = True
                claim.workflow_state = _json_safe(wf)

        elif agent_name == "estimate_validation":
            self._safe_transition(
                claim,
                ClaimStatus.ESTIMATE_VALIDATION.value,
                reason="Garage repair estimate benchmarked against OEM rate card",
                trigger_event="EstimateValidated",
                next_expected_action=(
                    "Adjuster/Surveyor to review flagged estimate anomalies"
                    if resp.status == AgentStatus.NEEDS_HUMAN
                    else "Proceed to deterministic settlement calculation"
                ),
            )

        elif agent_name == "settlement_recommendation":
            if resp.status == AgentStatus.COMPLETED and resp.result.get("auto_approved"):
                self._safe_transition(
                    claim,
                    ClaimStatus.APPROVED.value,
                    reason="LOW RISK straight-through settlement auto-approved within IN-RISK-PROCESSING-2026 limit",
                    trigger_event="FastTrackAutoApproved",
                    next_expected_action="Ready for Finance payout execution",
                )
            else:
                self._safe_transition(
                    claim,
                    ClaimStatus.SETTLEMENT_PENDING_APPROVAL.value,
                    reason="Deterministic Decimal settlement queued at Maker-Checker DoA human approval gate",
                    trigger_event="SettlementCalculated",
                    next_expected_action="Independent Maker-Checker DoA approval required before payment",
                )

    def _run_agent_attempts(
        self,
        agent_name: str,
        base_facts: dict[str, Any],
        upstream_results: dict[str, Any],
        claim: Claim,
        *,
        retry_strategy: RetryStrategySpec,
        simulate_timeout: bool = False,
        simulate_transient_timeout_once: bool = False,
        executor: ControlledActionExecutor | None = None,
    ) -> tuple[AgentInvocationResponse, list[dict[str, Any]]]:
        """Executes an agent up to max_retries with exponential backoff calculation & timeout handling."""
        agent = AGENT_REGISTRY[agent_name]
        spec = AGENT_CAPABILITY_CONTRACTS[agent_name]
        max_attempts = retry_strategy.max_retries + 1
        retry_history: list[dict[str, Any]] = []
        final_resp: AgentInvocationResponse | None = None

        for attempt in range(1, max_attempts + 1):
            facts = dict(base_facts)
            if simulate_timeout or (simulate_transient_timeout_once and attempt == 1):
                facts["_simulate_timeout"] = True

            req = AgentInvocationRequest(
                tenant_id=claim.tenant_id,
                claim_id=claim.id,
                correlation_id=get_correlation_id(),
                workflow_run_id=(claim.workflow_state or {}).get("workflow_run_id", claim.id),
                actor_user_id=self.user.user_id,
                actor_role=self.user.role.value,
                product_code="PRIVATE_CAR_PACKAGE",
                claim_type=claim.claim_type,
                locale=claim.preferred_language,
                rule_versions={"irdai": "IN-IRDAI-MC-2024:1.0.0", "dep": "IN-MOTOR-DEPRECIATION-2024:1.0.0"},
                minimised_facts=facts,
                upstream_results=upstream_results,
                allowed_tools=sorted(agent.allowed_tools),
                attempt_number=attempt,
                timeout_seconds=spec.timeout_seconds,
            )
            resp = agent.execute(req, action_executor=executor or ControlledActionExecutor())
            final_resp = resp
            if resp.status != AgentStatus.TIMED_OUT:
                break

            backoff_ms = compute_exponential_backoff_ms(attempt, retry_strategy)
            next_retry_at = (datetime.now(timezone.utc) + timedelta(milliseconds=backoff_ms)).isoformat()
            retry_history.append(
                {
                    "attempt": attempt,
                    "status": resp.status.value,
                    "backoff_delay_ms": backoff_ms,
                    "backoff_formula": f"{retry_strategy.base_delay_ms} * {retry_strategy.backoff_multiplier}^{attempt - 1}",
                    "next_retry_at": next_retry_at,
                }
            )
            # Bounded micro-sleep so retry timestamps advance deterministically without slowing tests
            if backoff_ms > 0:
                time.sleep(min(backoff_ms, 5) / 1000.0)

        assert final_resp is not None
        return final_resp, retry_history

    def run_agent(
        self,
        claim: Claim,
        agent_name: str,
        *,
        enforce_dependencies: bool = True,
        simulate_timeout: bool = False,
        simulate_transient_timeout_once: bool = False,
        override_facts: dict[str, Any] | None = None,
        apply_state_progression: bool = True,
    ) -> AgentInvocationResponse:
        spec = AGENT_CAPABILITY_CONTRACTS.get(agent_name)
        if not spec or agent_name not in AGENT_REGISTRY:
            raise DomainError(ErrorCode.NOT_FOUND, f"Agent '{agent_name}' not found", status_code=404)

        if enforce_dependencies:
            deps_ok, missing = self.check_dependencies(claim, agent_name)
            if not deps_ok:
                blocked_resp = AgentInvocationResponse(
                    agent_name=agent_name,
                    status=AgentStatus.BLOCKED_DEPENDENCY,
                    result={"blocked": True, "missing_dependencies": missing},
                    published_result={"blocked": True, "missing_dependencies": missing},
                    confidence=0.0,
                    confidence_band=ConfidenceBand.LOW,
                    missing_information=missing,
                    limitations=[f"Cannot run '{agent_name}' until upstream dependencies are satisfied."],
                    decision=DecisionIntelligence(
                        decision_id=f"dec-blk-{uuid.uuid4().hex[:8]}",
                        reason_codes=["RC_DEPENDENCY_UNSATISFIED"],
                        evidence=[f"Missing/blocked upstream stages: {missing}"],
                        policy_rule_refs=["ORCH-DEPENDENCY-DAG-V1"],
                        confidence=0.0,
                        confidence_band=ConfidenceBand.LOW,
                        routing_outcome="blocked_waiting_upstream",
                        explanation=f"Downstream agent {agent_name} blocked because prerequisites are unmet: {', '.join(missing)}.",
                    ),
                    model_id="orchestrator-dag",
                    model_version="2.0.0",
                    prompt_version=AGENT_REGISTRY[agent_name].prompt_version,
                    rule_versions={"orchestrator": "ORCH-DAG-V2"},
                    suggested_next_action=f"satisfy_upstream:{missing[0]}",
                )
                record_agent_publication(
                    self.db,
                    claim=claim,
                    agent_name=agent_name,
                    response=blocked_resp,
                    dependencies_satisfied=False,
                    error_message=f"Blocked on dependencies: {', '.join(missing)}",
                )
                return blocked_resp

        wf = claim.workflow_state or {}
        upstream_results = {
            dep: wf.get("published_results", {}).get(dep, {}).get("data", {})
            for dep in spec.depends_on
            if dep in wf.get("published_results", {})
        }
        base_facts = self._build_stage_facts(claim, agent_name)
        if override_facts:
            base_facts.update(override_facts)

        strategy = self._retry_strategy_for_agent(claim, agent_name)
        executor = ControlledActionExecutor(self.db, claim, self.user)
        final_resp, retry_history = self._run_agent_attempts(
            agent_name,
            base_facts,
            upstream_results,
            claim,
            retry_strategy=strategy,
            simulate_timeout=simulate_timeout,
            simulate_transient_timeout_once=simulate_transient_timeout_once,
            executor=executor,
        )

        for rh in retry_history:
            record_audit_event(
                self.db,
                tenant_id=claim.tenant_id,
                claim_id=claim.id,
                actor_id="orchestrator",
                actor_role="orchestrator",
                action="AGENT_TIMEOUT_RETRY",
                object_type="agent_execution",
                object_id=agent_name,
                details={**rh, "max_attempts": strategy.max_retries + 1},
            )

        if final_resp.status == AgentStatus.TIMED_OUT:
            self._move_to_dlq_and_escalate(
                claim,
                agent_name=agent_name,
                reason=f"Exhausted {strategy.max_retries + 1} attempts with exponential backoff due to timeout.",
                retry_history=retry_history,
                payload=base_facts,
            )

        self._persist_agent_side_effects(
            claim,
            agent_name,
            final_resp,
            attempt_count=final_resp.attempt_number,
            retry_history=retry_history,
            error_message="Timed out after exponential-backoff retries -> moved to DLQ"
            if final_resp.status == AgentStatus.TIMED_OUT
            else None,
            input_facts=base_facts,
        )

        if apply_state_progression:
            self._apply_post_agent_state_transition(claim, agent_name, final_resp)

        if agent_name in {
            "document_intelligence",
            "coverage_intelligence",
            "claim_triage",
            "damage_assessment",
            "estimate_validation",
            "fraud_intelligence",
        } and final_resp.status not in {
            AgentStatus.TIMED_OUT,
            AgentStatus.FAILED,
            AgentStatus.BLOCKED_DEPENDENCY,
        }:
            evaluate_and_persist_risk(
                self.db,
                claim,
                trigger_event=f"agent_{agent_name}",
                actor_id=self.user.user_id,
                actor_role=self.user.role.value,
                record_decision=(agent_name in {"damage_assessment", "estimate_validation", "fraud_intelligence"}),
                escalate_state=(agent_name in {"damage_assessment", "estimate_validation", "fraud_intelligence"}),
            )

        return final_resp

    def run_parallel_wave(
        self,
        claim: Claim,
        *,
        wave_name: str,
        agent_names: list[str],
        simulate_timeout_agent: str | None = None,
        simulate_transient_timeout_once_agent: str | None = None,
    ) -> dict[str, AgentInvocationResponse]:
        """Executes independent ready agents concurrently via ThreadPoolExecutor and persists atomically."""
        if not agent_names:
            return {}

        wf = dict(claim.workflow_state or {})
        prepared: list[tuple[str, dict[str, Any], dict[str, Any], RetryStrategySpec]] = []
        for ag in agent_names:
            spec = AGENT_CAPABILITY_CONTRACTS[ag]
            upstream = {
                dep: wf.get("published_results", {}).get(dep, {}).get("data", {})
                for dep in spec.depends_on
                if dep in wf.get("published_results", {})
            }
            facts = self._build_stage_facts(claim, ag)
            strategy = self._retry_strategy_for_agent(claim, ag)
            prepared.append((ag, facts, upstream, strategy))

        wave_start = time.perf_counter()
        wave_id = f"wave-{uuid.uuid4().hex[:8]}"
        results_map: dict[str, tuple[AgentInvocationResponse, list[dict[str, Any]]]] = {}

        def _worker(
            ag: str,
            facts: dict[str, Any],
            upstream: dict[str, Any],
            strategy: RetryStrategySpec,
        ) -> tuple[str, AgentInvocationResponse, list[dict[str, Any]]]:
            resp, rh = self._run_agent_attempts(
                ag,
                facts,
                upstream,
                claim,
                retry_strategy=strategy,
                simulate_timeout=(simulate_timeout_agent == ag),
                simulate_transient_timeout_once=(simulate_transient_timeout_once_agent == ag),
                executor=ControlledActionExecutor(),  # Stateless worker execution; replayed deterministically below
            )
            return ag, resp, rh

        with ThreadPoolExecutor(max_workers=min(len(prepared), 4), thread_name_prefix="orch-wave") as pool:
            futures = [pool.submit(_worker, ag, facts, up, strat) for ag, facts, up, strat in prepared]
            for fut in futures:
                ag, resp, rh = fut.result()
                results_map[ag] = (resp, rh)

        wave_duration_ms = int((time.perf_counter() - wave_start) * 1000)
        executor = ControlledActionExecutor(self.db, claim, self.user)
        final_responses: dict[str, AgentInvocationResponse] = {}

        for ag, facts, _, strategy in prepared:
            raw_resp, rh = results_map[ag]
            replayed_resp = self._replay_intent_actions(claim, ag, raw_resp, executor)

            for r_item in rh:
                record_audit_event(
                    self.db,
                    tenant_id=claim.tenant_id,
                    claim_id=claim.id,
                    actor_id="orchestrator",
                    actor_role="orchestrator",
                    action="AGENT_TIMEOUT_RETRY",
                    object_type="agent_execution",
                    object_id=ag,
                    details={**r_item, "wave_id": wave_id, "max_attempts": strategy.max_retries + 1},
                )

            if replayed_resp.status == AgentStatus.TIMED_OUT:
                self._move_to_dlq_and_escalate(
                    claim,
                    agent_name=ag,
                    reason=f"Parallel wave '{wave_name}' task '{ag}' exhausted {strategy.max_retries + 1} retries.",
                    retry_history=rh,
                    payload=facts,
                )

            self._persist_agent_side_effects(
                claim,
                ag,
                replayed_resp,
                attempt_count=replayed_resp.attempt_number,
                retry_history=rh,
                error_message="Timed out in parallel wave -> moved to DLQ"
                if replayed_resp.status == AgentStatus.TIMED_OUT
                else None,
                input_facts=facts,
            )
            final_responses[ag] = replayed_resp

        # Record parallel wave telemetry
        wf_latest = dict(claim.workflow_state or {})
        waves = list(wf_latest.get("parallel_waves", []))
        waves.append(
            {
                "wave_id": wave_id,
                "wave_name": wave_name,
                "agents": agent_names,
                "wall_duration_ms": wave_duration_ms,
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "outcomes": {k: v.status.value for k, v in final_responses.items()},
            }
        )
        wf_latest["parallel_waves"] = waves
        claim.workflow_state = _json_safe(wf_latest)

        emit_outbox_event(
            self.db,
            tenant_id=claim.tenant_id,
            aggregate_id=claim.id,
            event_type="ParallelWaveCompleted",
            payload={"wave_id": wave_id, "wave_name": wave_name, "agents": agent_names, "wall_ms": wave_duration_ms},
        )
        record_audit_event(
            self.db,
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            actor_id="orchestrator",
            actor_role="orchestrator",
            action="PARALLEL_WAVE_EXECUTED",
            object_type="claim",
            object_id=claim.id,
            details={"wave_id": wave_id, "wave_name": wave_name, "agents": agent_names, "wall_ms": wave_duration_ms},
        )
        self.db.flush()
        return final_responses

    # ------------------------------------------------------------------
    # Full End-to-End DAG & State-Machine Orchestration Loop
    # ------------------------------------------------------------------

    def orchestrate_claim(
        self,
        claim: Claim,
        *,
        stop_on_human_gate: bool = True,
        max_steps: int = 15,
        simulate_timeout_agent: str | None = None,
        simulate_transient_timeout_once_agent: str | None = None,
    ) -> dict[str, Any]:
        """Executes satisfied workflow waves & sequential/conditional/approval-gated steps."""
        wf = dict(claim.workflow_state or {})
        if wf.get("paused"):
            return {
                "claim_id": claim.id,
                "claim_status": claim.status,
                "canonical_state": to_canonical_state(claim.status),
                "steps_executed": [],
                "paused_reason": f"Workflow is paused: {wf.get('pause_reason', 'Manual pause active')}",
                "workflow_state": claim.workflow_state,
            }

        self.sync_task_schedule(claim)
        executed: list[dict[str, Any]] = []
        paused_reason: str | None = None

        def _append_step(ag: str, resp: AgentInvocationResponse, mode: str, wave: str | None = None) -> None:
            executed.append(
                {
                    "agent_name": ag,
                    "status": resp.status.value,
                    "attempt_number": resp.attempt_number,
                    "execution_mode": mode,
                    "parallel_group": wave,
                    "routing_outcome": resp.decision.routing_outcome if resp.decision else "",
                    "actions_count": len(resp.actions_executed),
                    "rework_count": len(resp.rework_requests),
                }
            )

        # 0. Ensure claim starts at least REGISTERED -> VALIDATION
        if claim.status == ClaimStatus.SUBMITTED.value:
            self._safe_transition(
                claim,
                ClaimStatus.REGISTERED.value,
                reason="Orchestrator registered submitted claim",
                trigger_event="FNOLSubmitted",
            )
        if claim.status in {ClaimStatus.REGISTERED.value, ClaimStatus.EVIDENCE_PENDING.value}:
            self._safe_transition(
                claim,
                ClaimStatus.VALIDATION.value,
                reason="Starting post-FNOL parallel validation wave",
                trigger_event="ValidationWaveStarted",
            )

        # 1. Wave 1: Post-FNOL Parallel Fan-Out (Policy Validation + Document Extraction + Customer Comm)
        statuses = (claim.workflow_state or {}).get("stage_statuses", {})
        if statuses.get("fnol_concierge") != AgentStatus.COMPLETED.value:
            fnol_resp = self.run_agent(
                claim,
                "fnol_concierge",
                enforce_dependencies=False,
                simulate_timeout=(simulate_timeout_agent == "fnol_concierge"),
                simulate_transient_timeout_once=(simulate_transient_timeout_once_agent == "fnol_concierge"),
                apply_state_progression=False,
            )
            _append_step("fnol_concierge", fnol_resp, "sequential")

        post_fnol_candidates = ["document_intelligence", "coverage_intelligence", "customer_communication"]
        ready_post_fnol = []
        for ag in post_fnol_candidates:
            st = (claim.workflow_state or {}).get("stage_statuses", {}).get(ag)
            if st == AgentStatus.COMPLETED.value:
                continue
            deps_ok, _ = self.check_dependencies(claim, ag)
            if deps_ok:
                ready_post_fnol.append(ag)

        if ready_post_fnol and len(executed) < max_steps:
            wave1_res = self.run_parallel_wave(
                claim,
                wave_name="post_fnol_parallel",
                agent_names=ready_post_fnol,
                simulate_timeout_agent=simulate_timeout_agent,
                simulate_transient_timeout_once_agent=simulate_transient_timeout_once_agent,
            )
            for ag in ready_post_fnol:
                resp = wave1_res[ag]
                _append_step(ag, resp, "parallel", "post_fnol_parallel")
                self._apply_post_agent_state_transition(claim, ag, resp)

            if stop_on_human_gate:
                for ag in ["document_intelligence", "coverage_intelligence"]:
                    if ag in wave1_res and wave1_res[ag].status in {
                        AgentStatus.NEEDS_HUMAN,
                        AgentStatus.REWORK_REQUIRED,
                        AgentStatus.TIMED_OUT,
                        AgentStatus.FAILED,
                    }:
                        paused_reason = f"Paused at '{ag}' ({wave1_res[ag].status.value}): {wave1_res[ag].suggested_next_action}"
                        return {
                            "claim_id": claim.id,
                            "claim_status": claim.status,
                            "canonical_state": to_canonical_state(claim.status),
                            "steps_executed": executed,
                            "paused_reason": paused_reason,
                            "workflow_state": claim.workflow_state,
                        }

        # 2. Sequential Claim Triage (depends on policy_validation + document_extraction)
        if len(executed) < max_steps:
            st_tri = (claim.workflow_state or {}).get("stage_statuses", {}).get("claim_triage")
            if st_tri != AgentStatus.COMPLETED.value:
                deps_ok, missing = self.check_dependencies(claim, "claim_triage")
                if not deps_ok:
                    paused_reason = f"Dependency gate on 'claim_triage': {', '.join(missing)}"
                    return {
                        "claim_id": claim.id,
                        "claim_status": claim.status,
                        "canonical_state": to_canonical_state(claim.status),
                        "steps_executed": executed,
                        "paused_reason": paused_reason,
                        "workflow_state": claim.workflow_state,
                    }
                tri_resp = self.run_agent(
                    claim,
                    "claim_triage",
                    enforce_dependencies=True,
                    simulate_timeout=(simulate_timeout_agent == "claim_triage"),
                    simulate_transient_timeout_once=(simulate_transient_timeout_once_agent == "claim_triage"),
                )
                _append_step("claim_triage", tri_resp, "sequential")
                if stop_on_human_gate and tri_resp.status in {
                    AgentStatus.TIMED_OUT,
                    AgentStatus.FAILED,
                    AgentStatus.NEEDS_HUMAN,
                }:
                    paused_reason = f"Paused at 'claim_triage' ({tri_resp.status.value}): {tri_resp.suggested_next_action}"
                    return {
                        "claim_id": claim.id,
                        "claim_status": claim.status,
                        "canonical_state": to_canonical_state(claim.status),
                        "steps_executed": executed,
                        "paused_reason": paused_reason,
                        "workflow_state": claim.workflow_state,
                    }

        # 3. Conditional Provider Coordination (MEDIUM/HIGH or survey / towing / EV needed; bypassed on LOW fast-track)
        if len(executed) < max_steps:
            st_prov = (claim.workflow_state or {}).get("stage_statuses", {}).get("provider_coordination")
            if st_prov not in {AgentStatus.COMPLETED.value, "skipped_fast_track"}:
                deps_ok, missing = self.check_dependencies(claim, "provider_coordination")
                cond_prov, cond_reason = self._task_condition_satisfied(claim, "provider_coordination")
                if deps_ok and cond_prov:
                    prov_resp = self.run_agent(
                        claim,
                        "provider_coordination",
                        enforce_dependencies=True,
                        simulate_timeout=(simulate_timeout_agent == "provider_coordination"),
                        simulate_transient_timeout_once=(simulate_transient_timeout_once_agent == "provider_coordination"),
                    )
                    _append_step("provider_coordination", prov_resp, "conditional")
                    if stop_on_human_gate and prov_resp.status in {AgentStatus.NEEDS_HUMAN, AgentStatus.TIMED_OUT, AgentStatus.FAILED}:
                        paused_reason = f"Paused at 'provider_coordination' ({prov_resp.status.value}): {prov_resp.suggested_next_action}"
                        return {
                            "claim_id": claim.id,
                            "claim_status": claim.status,
                            "canonical_state": to_canonical_state(claim.status),
                            "steps_executed": executed,
                            "paused_reason": paused_reason,
                            "workflow_state": claim.workflow_state,
                        }
                elif deps_ok and not cond_prov:
                    prov_task = self._get_or_create_task(claim, "provider_coordination")
                    prov_task.status = "skipped_fast_track"
                    prov_task.started_at = prov_task.started_at or datetime.now(timezone.utc)
                    prov_task.completed_at = datetime.now(timezone.utc)
                    prov_task.output_payload = {
                        "skipped": True,
                        "risk_tier": claim.risk_tier,
                        "operational_path": claim.operational_path,
                        "reason": cond_reason,
                    }
                    wf_prov = dict(claim.workflow_state or {})
                    st_map = dict(wf_prov.get("stage_statuses", {}))
                    st_map["provider_coordination"] = "skipped_fast_track"
                    wf_prov["stage_statuses"] = st_map
                    claim.workflow_state = _json_safe(wf_prov)

        # 4. Wave 2: Conditional Damage Assessment + Parallel Fraud Analysis
        if len(executed) < max_steps:
            wave2_agents: list[str] = []
            st_dmg = (claim.workflow_state or {}).get("stage_statuses", {}).get("damage_assessment")
            if st_dmg != AgentStatus.COMPLETED.value:
                deps_ok_dmg, _ = self.check_dependencies(claim, "damage_assessment")
                cond_dmg, cond_reason = self._task_condition_satisfied(claim, "damage_assessment")
                if deps_ok_dmg and cond_dmg:
                    wave2_agents.append("damage_assessment")
                elif deps_ok_dmg and not cond_dmg:
                    dmg_task = self._get_or_create_task(claim, "damage_assessment")
                    dmg_task.status = "waiting_condition"
                    dmg_task.error_message = cond_reason

            st_frd = (claim.workflow_state or {}).get("stage_statuses", {}).get("fraud_intelligence")
            if st_frd != AgentStatus.COMPLETED.value:
                deps_ok_frd, _ = self.check_dependencies(claim, "fraud_intelligence")
                if deps_ok_frd:
                    wave2_agents.append("fraud_intelligence")

            if wave2_agents:
                if len(wave2_agents) > 1:
                    wave2_res = self.run_parallel_wave(
                        claim,
                        wave_name="assessment_and_fraud_parallel",
                        agent_names=wave2_agents,
                        simulate_timeout_agent=simulate_timeout_agent,
                        simulate_transient_timeout_once_agent=simulate_transient_timeout_once_agent,
                    )
                    for ag in wave2_agents:
                        resp = wave2_res[ag]
                        _append_step(ag, resp, "parallel" if ag == "fraud_intelligence" else "conditional", "assessment_and_fraud_parallel")
                        self._apply_post_agent_state_transition(claim, ag, resp)
                    evaluate_and_persist_risk(
                        self.db,
                        claim,
                        trigger_event="wave2_assessment_and_fraud",
                        actor_id=self.user.user_id,
                        actor_role=self.user.role.value,
                        record_decision=True,
                        escalate_state=True,
                    )
                else:
                    ag = wave2_agents[0]
                    resp = self.run_agent(
                        claim,
                        ag,
                        enforce_dependencies=True,
                        simulate_timeout=(simulate_timeout_agent == ag),
                        simulate_transient_timeout_once=(simulate_transient_timeout_once_agent == ag),
                    )
                    _append_step(ag, resp, "conditional" if ag == "damage_assessment" else "parallel")
                    wave2_res = {ag: resp}

                if stop_on_human_gate:
                    for ag, resp in wave2_res.items():
                        if resp.status in {
                            AgentStatus.NEEDS_HUMAN,
                            AgentStatus.REWORK_REQUIRED,
                            AgentStatus.TIMED_OUT,
                            AgentStatus.FAILED,
                        }:
                            if ag == "fraud_intelligence" and resp.status == AgentStatus.NEEDS_HUMAN:
                                self._safe_transition(
                                    claim,
                                    ClaimStatus.INVESTIGATION_REQUIRED.value,
                                    reason="Fraud analysis raised SIU investigative lead",
                                    trigger_event="FraudAlertRaised",
                                    next_expected_action="SIU Investigator review required",
                                )
                            paused_reason = f"Paused at '{ag}' ({resp.status.value}): {resp.suggested_next_action}"
                            return {
                                "claim_id": claim.id,
                                "claim_status": claim.status,
                                "canonical_state": to_canonical_state(claim.status),
                                "steps_executed": executed,
                                "paused_reason": paused_reason,
                                "workflow_state": claim.workflow_state,
                            }

        # 5. Sequential Estimate Validation -> Settlement Recommendation -> QA Compliance
        for agent_name in ["estimate_validation", "settlement_recommendation", "qa_compliance"]:
            if len(executed) >= max_steps:
                break
            cur_status = (claim.workflow_state or {}).get("stage_statuses", {}).get(agent_name)
            if cur_status == AgentStatus.COMPLETED.value:
                continue
            if agent_name == "qa_compliance" and claim.status not in {
                ClaimStatus.PAYMENT_PENDING.value,
                ClaimStatus.PAYMENT_RECONCILIATION.value,
                ClaimStatus.PAYMENT_INITIATED.value,
                ClaimStatus.REPAIR_IN_PROGRESS.value,
                ClaimStatus.APPROVED.value,
                ClaimStatus.DECLINED_PARTIAL.value,
                ClaimStatus.CLOSED.value,
            }:
                continue

            deps_ok, missing = self.check_dependencies(claim, agent_name)
            if not deps_ok:
                paused_reason = f"Dependency gate on '{agent_name}': {', '.join(missing)}"
                break

            if agent_name == "estimate_validation":
                est_cnt = self.db.query(Estimate).filter(Estimate.claim_id == claim.id).count()
                if est_cnt == 0:
                    executor = ControlledActionExecutor(self.db, claim, self.user)
                    executor.create_claim_task(
                        agent_name=agent_name,
                        task_type="estimate_submission",
                        title="Awaiting Garage Repair Estimate Submission",
                        description="Garage must submit itemized repair estimate before Estimate Validation & Settlement.",
                        assigned_role="garage",
                        priority="medium",
                        reason_code="RC_AWAITING_ESTIMATE",
                        due_hours=24,
                    )
                    est_task = self._get_or_create_task(claim, "estimate_validation")
                    est_task.status = "waiting_condition"
                    est_task.error_message = "Awaiting garage repair estimate submission"
                    paused_reason = "Awaiting garage repair estimate submission before EstimateValidationAgent."
                    break

            if agent_name == "settlement_recommendation":
                stl_cnt = self.db.query(Settlement).filter(Settlement.claim_id == claim.id).count()
                if stl_cnt == 0:
                    self._materialize_settlement_if_ready(claim)

            resp = self.run_agent(
                claim,
                agent_name,
                enforce_dependencies=True,
                simulate_timeout=(simulate_timeout_agent == agent_name),
                simulate_transient_timeout_once=(simulate_transient_timeout_once_agent == agent_name),
            )
            _append_step(agent_name, resp, "sequential")

            if stop_on_human_gate and resp.status in {
                AgentStatus.NEEDS_HUMAN,
                AgentStatus.REWORK_REQUIRED,
                AgentStatus.TIMED_OUT,
                AgentStatus.FAILED,
                AgentStatus.BLOCKED_DEPENDENCY,
            }:
                paused_reason = f"Paused at '{agent_name}' ({resp.status.value}): {resp.suggested_next_action}"
                break

        self.db.flush()
        return {
            "claim_id": claim.id,
            "claim_status": claim.status,
            "canonical_state": to_canonical_state(claim.status),
            "steps_executed": executed,
            "paused_reason": paused_reason,
            "workflow_state": claim.workflow_state,
        }

    # ------------------------------------------------------------------
    # DLQ & Escalation Helpers
    # ------------------------------------------------------------------

    def _move_to_dlq_and_escalate(
        self,
        claim: Claim,
        *,
        agent_name: str,
        reason: str,
        retry_history: list[dict[str, Any]],
        payload: dict[str, Any],
    ) -> DeadLetterRecord:
        task_key = _AGENT_TO_TASK_KEY.get(agent_name, agent_name)
        ot = self._get_or_create_task(claim, task_key)
        ot.status = "dlq"
        ot.error_message = reason

        dlq = DeadLetterRecord(
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            task_id=ot.id,
            task_key=task_key,
            agent_or_service=agent_name,
            state_at_failure=claim.status,
            error_code="ORCH_RETRY_EXHAUSTED",
            failure_reason=reason,
            attempt_count=len(retry_history) or (ot.max_retries + 1),
            retry_history=_json_safe(retry_history),
            payload=_json_safe(payload),
            status="open",
        )
        self.db.add(dlq)
        self.db.flush()

        wf = dict(claim.workflow_state or {})
        escalations = list(wf.get("escalations", []))
        esc = {
            "id": f"esc-{uuid.uuid4().hex[:8]}",
            "agent_name": agent_name,
            "dlq_id": dlq.id,
            "reason": reason,
            "status": "open",
            "escalated_at": datetime.now(timezone.utc).isoformat(),
        }
        escalations.append(esc)
        wf["escalations"] = escalations
        claim.workflow_state = _json_safe(wf)
        claim.next_expected_action = f"DLQ ESCALATED ({agent_name}): {reason[:140]}"

        executor = ControlledActionExecutor(self.db, claim, self.user)
        executor.create_claim_task(
            agent_name="orchestrator",
            task_type="orchestration_escalation",
            title=f"Orchestration Escalation (DLQ): {agent_name} timed out",
            description=reason,
            assigned_role="claims_manager",
            priority="critical",
            reason_code="RC_ORCH_TIMEOUT_ESCALATION",
            due_hours=2,
            metadata={"dlq_id": dlq.id, "task_key": task_key},
        )
        emit_outbox_event(
            self.db,
            tenant_id=claim.tenant_id,
            aggregate_id=claim.id,
            event_type="TaskMovedToDLQ",
            payload={"dlq_id": dlq.id, "agent_name": agent_name, "task_key": task_key, "reason": reason},
        )
        emit_outbox_event(
            self.db,
            tenant_id=claim.tenant_id,
            aggregate_id=claim.id,
            event_type="AgentEscalated",
            payload=esc,
        )
        record_audit_event(
            self.db,
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            actor_id="orchestrator",
            actor_role="orchestrator",
            action="TASK_MOVED_TO_DLQ",
            object_type="dead_letter_record",
            object_id=dlq.id,
            details={"agent_name": agent_name, "task_key": task_key, "attempts": dlq.attempt_count},
        )
        return dlq

    def _materialize_settlement_if_ready(self, claim: Claim) -> None:
        from services.workflow.tp_liability import claim_requires_tp_workflow

        if claim_requires_tp_workflow(claim):
            # Third-Party liability is never materialised from an OD repair estimate (IN-TP-LIABILITY-2026).
            return
        from services.workflow.ev_claims import ev_od_hold_blockers

        if ev_od_hold_blockers(self.db, claim):
            # An EV claim is not settled from a photo-led estimate: the EV technical sign-off must clear it first.
            claim.workflow_state = {**(claim.workflow_state or {}), "ev_settlement_hold": True}
            return
        policy = self.db.query(Policy).filter(Policy.id == claim.policy_id).first() if claim.policy_id else None
        vehicle = self.db.query(Vehicle).filter(Vehicle.id == claim.vehicle_id).first() if claim.vehicle_id else None
        estimates = self.db.query(Estimate).filter(Estimate.claim_id == claim.id).order_by(Estimate.version.desc()).all()
        if not policy or not vehicle or not estimates:
            return
        from services.claims.models import EstimateLine

        lines_input: list[SettlementLineInput] = []
        for est in estimates:
            for ln in self.db.query(EstimateLine).filter(EstimateLine.estimate_id == est.id).all():
                if ln.reviewer_status == "rejected":
                    continue
                amt = Decimal(str(ln.approved_amount_inr if ln.approved_amount_inr is not None else ln.unit_price_inr * ln.quantity))
                if amt <= Decimal("0.00"):
                    continue
                lines_input.append(
                    SettlementLineInput(
                        part_code=ln.part_code,
                        description=ln.description,
                        part_category=ln.part_category,
                        line_type=ln.line_type,
                        approved_amount_inr=amt,
                    )
                )
        if not lines_input:
            return
        scen = SettlementCalculator().calculate_scenarios(
            db=self.db,
            lines=lines_input,
            vehicle_first_reg=vehicle.first_registration_date,
            incident_at=claim.incident_at,
            idv_inr=Decimal(str(policy.idv_inr)),
            compulsory_deductible_inr=Decimal(str(policy.compulsory_deductible_inr)),
            voluntary_deductible_inr=Decimal(str(policy.voluntary_deductible_inr)),
            addons=policy.addons or {},
        )
        calc = scen["primary"]
        try:
            risk_ctrl = get_active_rule(self.db, "IN-RISK-PROCESSING-2026")["controls"]
        except KeyError:
            risk_ctrl = load_rule_files()["IN-RISK-PROCESSING-2026"]["controls"]
        auto_limit = Decimal(str(risk_ctrl.get("fast_track_auto_approval_limit_inr", "25000.00")))
        latest_risk = evaluate_and_persist_risk(
            self.db,
            claim,
            trigger_event="settlement_calculation",
            actor_id=self.user.user_id,
            actor_role=self.user.role.value,
            record_decision=False,
            escalate_state=True,
        )
        open_alerts_cnt = (
            self.db.query(FraudAlert)
            .filter(FraudAlert.claim_id == claim.id, FraudAlert.status.in_(["new", "assigned", "investigating"]))
            .count()
        )
        fast_track_auto_ok = (
            latest_risk["risk_tier"] == "LOW"
            and bool(latest_risk["automation_eligibility"]["straight_through_eligible"])
            and open_alerts_cnt == 0
            and not calc.is_total_loss
            and Decimal("0.00") < calc.net_payable_inr <= auto_limit
        )

        stl = Settlement(
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            version=1,
            pathway=calc.pathway,
            gross_assessed_inr=calc.gross_assessed_inr,
            depreciation_deduction_inr=calc.depreciation_deduction_inr,
            compulsory_excess_inr=calc.compulsory_excess_inr,
            voluntary_excess_inr=calc.voluntary_excess_inr,
            salvage_deduction_inr=calc.salvage_deduction_inr,
            addon_waiver_inr=calc.addon_waiver_inr,
            net_payable_inr=calc.net_payable_inr,
            is_total_loss=calc.is_total_loss,
            calculation_trace=calc.calculation_trace,
            rule_versions=calc.rule_versions,
            policy_citations=calc.policy_citations,
            approval_status="approved" if fast_track_auto_ok else "pending_checker",
            created_by=self.user.user_id,
        )
        self.db.add(stl)
        self.db.flush()

        self._safe_transition(
            claim,
            ClaimStatus.SETTLEMENT_PENDING_APPROVAL.value,
            reason="Deterministic settlement computed",
            trigger_event="SettlementCalculated",
        )
        if fast_track_auto_ok:
            self.db.add(
                Approval(
                    tenant_id=claim.tenant_id,
                    claim_id=claim.id,
                    settlement_id=stl.id,
                    action_type="fast_track_auto_approval",
                    amount_inr=calc.net_payable_inr,
                    maker_user_id="system:fast_track_engine",
                    checker_user_id="rule:IN-RISK-PROCESSING-2026",
                    authority_rule_version="IN-RISK-PROCESSING-2026:1.0.0",
                    decision="approved",
                    rationale=(
                        f"LOW RISK straight-through auto-approval within INR {auto_limit} limit "
                        f"(net payable INR {calc.net_payable_inr}); zero anomalies."
                    ),
                    decided_at=datetime.now(timezone.utc),
                )
            )
            gate_task = self._get_or_create_task(claim, "human_approval_gate")
            gate_task.status = "completed"
            gate_task.started_at = gate_task.started_at or datetime.now(timezone.utc)
            gate_task.completed_at = datetime.now(timezone.utc)
            gate_task.output_payload = {
                "mode": "fast_track_auto_approval",
                "limit_inr": str(auto_limit),
                "net_payable_inr": str(calc.net_payable_inr),
            }
            self.db.flush()
            self._safe_transition(
                claim,
                ClaimStatus.APPROVED.value,
                reason=f"LOW RISK straight-through auto-approved within INR {auto_limit} limit",
                trigger_event="FastTrackAutoApproved",
                next_expected_action="Ready for Finance payout execution",
            )

    def _build_stage_facts(self, claim: Claim, agent_name: str) -> dict[str, Any]:
        policy = self.db.query(Policy).filter(Policy.id == claim.policy_id).first() if claim.policy_id else None
        vehicle = self.db.query(Vehicle).filter(Vehicle.id == claim.vehicle_id).first() if claim.vehicle_id else None
        evidences = self.db.query(Evidence).filter(Evidence.claim_id == claim.id).all()
        facts_rows = self.db.query(ExtractedFact).filter(ExtractedFact.claim_id == claim.id).all()

        if agent_name == "fnol_concierge":
            return {
                "policy_number": claim.policy_number_input,
                "vehicle_reg": claim.vehicle_reg_input,
                "incident_description": claim.incident_description,
                "incident_location": claim.incident_location,
                "intake_channel": claim.intake_channel,
                "preferred_language": claim.preferred_language,
                "peril_cause": claim.peril_cause,
                "vehicle_immobile": claim.vehicle_immobile,
                "airbags_deployed": claim.airbags_deployed,
                "injury_or_fatality": claim.injury_or_fatality,
                "police_involved": claim.police_involved,
                "towing_needed": claim.towing_needed,
                "ev_battery_impacted": claim.ev_battery_impacted,
                "estimated_loss_inr": str(claim.estimated_loss_inr),
                "missing_documents": claim.missing_documents,
            }

        if agent_name == "document_intelligence":
            return {
                "policy_number": claim.policy_number_input,
                "vehicle_reg": claim.vehicle_reg_input,
                "prompt_injection_flagged": any(e.prompt_injection_flagged for e in evidences),
                "evidences": [
                    {"id": e.id, "doc_type": e.doc_type, "filename": e.filename, "sha256": e.sha256}
                    for e in evidences
                ],
                "extracted_facts": [
                    {
                        "id": f.id,
                        "evidence_id": f.evidence_id,
                        "field_name": f.field_name,
                        "extracted_value": f.extracted_value,
                        "verified_value": f.verified_value,
                        "confidence": float(f.confidence),
                        "page_number": f.page_number,
                        "bbox": f.bbox,
                        "validation_status": f.validation_status,
                    }
                    for f in facts_rows
                ],
            }

        if agent_name == "coverage_intelligence":
            period_valid = False
            if policy:
                ps = policy.period_start.replace(tzinfo=timezone.utc) if policy.period_start.tzinfo is None else policy.period_start
                pe = policy.period_end.replace(tzinfo=timezone.utc) if policy.period_end.tzinfo is None else policy.period_end
                inc = claim.incident_at.replace(tzinfo=timezone.utc) if claim.incident_at.tzinfo is None else claim.incident_at
                period_valid = ps <= inc <= pe
            has_mismatch = any(f.validation_status == "mismatch" for f in facts_rows)
            return {
                "peril_cause": claim.peril_cause,
                "claim_type": claim.claim_type,
                "injury_or_fatality": claim.injury_or_fatality,
                "is_ev": vehicle.is_ev if vehicle else claim.ev_battery_impacted,
                "ev_battery_impacted": claim.ev_battery_impacted,
                "period_valid": period_valid,
                "policy_status": policy.status if policy else "not_matched",
                "addons": policy.addons if policy else {},
                "idv_inr": str(policy.idv_inr) if policy else "0.00",
                "compulsory_deductible_inr": str(policy.compulsory_deductible_inr) if policy else "1000.00",
                "voluntary_deductible_inr": str(policy.voluntary_deductible_inr) if policy else "0.00",
                "has_document_mismatch": has_mismatch,
                "missing_documents": claim.missing_documents,
            }

        if agent_name == "claim_triage":
            risk_facts = gather_claim_risk_facts(self.db, claim)
            risk_facts.update(
                {
                    "is_ev": vehicle.is_ev if vehicle else claim.ev_battery_impacted,
                    "police_involved": claim.police_involved,
                }
            )
            return risk_facts

        if agent_name == "provider_coordination":
            return {
                "requires_mandatory_survey": claim.requires_mandatory_survey,
                "ev_battery_impacted": claim.ev_battery_impacted,
                "is_ev": vehicle.is_ev if vehicle else False,
                "incident_location": claim.incident_location,
                "peril_cause": claim.peril_cause,
                "vehicle_make": vehicle.make if vehicle else "",
                "towing_needed": claim.towing_needed,
                "vehicle_immobile": claim.vehicle_immobile,
                "preferred_garage_id": claim.assigned_garage_id,
                "preferred_surveyor_id": claim.assigned_surveyor_id,
            }

        if agent_name == "damage_assessment":
            img_records = [
                {
                    "id": ev.id,
                    "filename": ev.filename,
                    "image_angle": ev.image_angle,
                    "image_quality_status": ev.image_quality_status,
                    "sha256": ev.sha256,
                    "ocr_text": ev.ocr_text,
                }
                for ev in evidences
                if ev.mime_type.startswith("image/")
            ]
            veh_info = (
                {
                    "make": vehicle.make,
                    "model": vehicle.model,
                    "variant": vehicle.cc_class.replace("_", " ").title(),
                    "year": vehicle.year,
                    "registration_number": vehicle.registration_number,
                    "is_ev": vehicle.is_ev,
                    "fuel_type": vehicle.fuel_type,
                }
                if vehicle
                else {"registration_number": claim.vehicle_reg_input, "is_ev": claim.ev_battery_impacted}
            )
            payload = assess_damage_from_evidence(
                claim_description=claim.incident_description,
                is_ev=vehicle.is_ev if vehicle else claim.ev_battery_impacted,
                ev_battery_impacted=claim.ev_battery_impacted,
                image_records=img_records,
                vehicle_info=veh_info,
            )
            return {"assessment_payload": payload}

        if agent_name == "estimate_validation":
            estimates = self.db.query(Estimate).filter(Estimate.claim_id == claim.id).order_by(Estimate.version.desc()).all()
            if estimates:
                from services.claims.models import EstimateLine

                est = estimates[0]
                lines = self.db.query(EstimateLine).filter(EstimateLine.estimate_id == est.id).all()
                raw_lines = [
                    {
                        "part_code": ln.part_code,
                        "description": ln.description,
                        "part_category": ln.part_category,
                        "line_type": ln.line_type,
                        "action": ln.action,
                        "quantity": ln.quantity,
                        "unit_price_inr": str(ln.unit_price_inr),
                    }
                    for ln in lines
                ]
                dmg_rows = self.db.query(DamageAssessment).filter(DamageAssessment.claim_id == claim.id).all()
                dmg_obs = [
                    {
                        "part_code": d.part_code,
                        "recommended_action": d.recommended_action,
                        "repair_vs_replace_rationale": d.limitations,
                    }
                    for d in dmg_rows
                ]
                visible_parts = {d.part_code for d in dmg_rows if d.part_code}
                val = validate_estimate_lines(
                    raw_lines,
                    visible_part_codes=visible_parts or None,
                    damage_observations=dmg_obs or None,
                )
                return {"estimate_validation": val}
            return {"estimate_validation": {}}

        if agent_name == "fraud_intelligence":
            indicators = run_fraud_and_anomaly_checks(self.db, claim)
            graph = build_entity_relationship_graph(self.db, claim)
            return {
                "indicators": [{**i, "confidence": str(i["confidence"])} for i in indicators],
                "entity_graph": graph,
            }

        if agent_name == "settlement_recommendation":
            stl = self.db.query(Settlement).filter(Settlement.claim_id == claim.id).order_by(Settlement.version.desc()).first()
            open_alerts = (
                self.db.query(FraudAlert)
                .filter(FraudAlert.claim_id == claim.id, FraudAlert.status.in_(["new", "assigned", "investigating"]))
                .count()
            )
            active_conditions: list[str] = []
            if open_alerts > 0:
                active_conditions.append("fraud_alert_open")
            if claim.injury_or_fatality:
                active_conditions.append("tp_injury")
            if claim.ev_battery_impacted:
                active_conditions.append("ev_battery")
            if stl and stl.is_total_loss:
                active_conditions.append("total_loss")
            if (claim.risk_tier or "MEDIUM") == "HIGH":
                active_conditions.append("high_risk_complex")
            elig = (claim.risk_assessment or {}).get("automation_eligibility", {}) if isinstance(claim.risk_assessment, dict) else {}
            from services.workflow.ev_claims import claim_requires_ev_workflow, ev_od_hold_blockers

            _veh = self.db.query(Vehicle).filter(Vehicle.id == claim.vehicle_id).first() if claim.vehicle_id else None
            _ev_required = claim_requires_ev_workflow(claim, _veh)
            _ev_blockers = ev_od_hold_blockers(self.db, claim) if _ev_required else []
            return {
                "settlement_id": stl.id if stl else None,
                "active_conditions": active_conditions,
                "risk_tier": claim.risk_tier or "MEDIUM",
                "straight_through_eligible": bool(elig.get("straight_through_eligible", False)),
                "auto_approval_limit_inr": str(elig.get("auto_approval_limit_inr", "25000.00")),
                "allow_fast_track_auto_approve": claim.claim_type != "third_party" and not _ev_required,
                "tp_workflow_required": claim.claim_type == "third_party",
                "ev_workflow_required": _ev_required,
                "ev_settlement_cleared": _ev_required and not _ev_blockers,
                "calculation": {
                    "gross": str(stl.gross_assessed_inr) if stl else "0.00",
                    "net": str(stl.net_payable_inr) if stl else "0.00",
                    "is_total_loss": stl.is_total_loss if stl else False,
                },
            }

        if agent_name == "customer_communication":
            from services.workflow.customer_experience import inspect_claim_communication_context

            cx = inspect_claim_communication_context(self.db, claim)
            prefs = cx["preferences"]
            rec = cx["recommended_message"]
            return {
                **cx["state_context"],
                "language": prefs["preferred_language"],
                "channel": cx["requested_channel"],
                "consent_whatsapp": prefs["consent_whatsapp"],
                "consent_sms": prefs["consent_sms"],
                "consent_email": prefs["consent_email"],
                "phone_masked": prefs["phone_masked"],
                "trigger_event": cx["primary_trigger"],
                "message_type": rec["message_type"],
                "subject": rec["subject"],
                "draft_message": rec["body"],
                "action_cta": rec["action_cta"],
                "detected_triggers": [d["trigger"] for d in cx["detected_triggers"]],
                "is_adverse": claim.status == ClaimStatus.DECLINED_PARTIAL.value,
            }

        # qa_compliance
        confirmed_pmt = self.db.query(Payment).filter(Payment.claim_id == claim.id, Payment.status == "confirmed").first()
        open_grievance = self.db.query(Grievance).filter(Grievance.claim_id == claim.id, Grievance.status != "resolved").first()
        unresolved_mismatch = any(f.validation_status == "mismatch" for f in facts_rows)
        open_alerts = (
            self.db.query(FraudAlert)
            .filter(FraudAlert.claim_id == claim.id, FraudAlert.status.in_(["new", "assigned", "investigating"]))
            .count()
        )
        signed_survey = (
            self.db.query(SurveyAssignment)
            .filter(SurveyAssignment.claim_id == claim.id, SurveyAssignment.signed_by_surveyor.is_(True))
            .first()
        )
        approved_app = (
            self.db.query(Approval)
            .filter(Approval.claim_id == claim.id, Approval.decision == "approved")
            .first()
        )
        checks = {
            "no_unresolved_doc_mismatch": not unresolved_mismatch,
            "coverage_checked": claim.coverage_factsheet is not None,
            "survey_report_signed": (not claim.requires_mandatory_survey) or (signed_survey is not None),
            "no_open_siu_alerts": open_alerts == 0,
            "maker_checker_approved": (approved_app is not None) or claim.status == ClaimStatus.DECLINED_PARTIAL.value,
            "confirmed_payment_or_declined": confirmed_pmt is not None or claim.status == ClaimStatus.DECLINED_PARTIAL.value,
            "no_open_grievance": open_grievance is None,
        }
        return {"checks": checks}
