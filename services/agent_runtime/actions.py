from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from packages.contracts.agents import AgentActionExecution
from packages.security.auth import Role, UserContext
from packages.security.sanitizer import mask_bank_account
from services.claims.audit import emit_outbox_event, record_audit_event
from services.claims.models import (
    Approval,
    Claim,
    ClaimTask,
    Communication,
    Payment,
    Provider,
    Settlement,
    SurveyAssignment,
)
from services.claims.state_machine import ClaimStatus, validate_transition
from services.integrations.adapters import IntegrationAdapterRegistry
from services.rules_engine.loader import get_active_rule
from services.workflow.sla_engine import complete_stage_sla_timer, create_stage_sla_timer


class ControlledActionExecutor:
    """Safe, auditable action execution layer bound to BoundedAgent tool allowlists.

    When `db` is provided, actions persist real operational side effects in PostgreSQL/SQLite.
    When `db` is None (stateless unit evaluation), actions are validated and recorded cleanly as `simulated`.
    """

    def __init__(self, db: Session | None = None, claim: Claim | None = None, user: UserContext | None = None) -> None:
        self.db = db
        self.claim = claim
        self.user = user

    def _aid(self) -> str:
        return f"act-{uuid.uuid4().hex[:10]}"

    def create_claim_task(
        self,
        *,
        agent_name: str,
        task_type: str,
        title: str,
        description: str = "",
        assigned_role: str = "claims_handler",
        priority: str = "medium",
        reason_code: str = "AGENT_ACTION",
        due_hours: int = 24,
        metadata: dict[str, Any] | None = None,
    ) -> AgentActionExecution:
        if self.db is None or self.claim is None:
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="create_claim_task",
                tool_name="create_claim_task",
                status="simulated",
                target_type="claim_task",
                target_id=f"sim-{task_type}",
                summary=f"[Simulated] Create task '{title}' ({assigned_role})",
                payload={"task_type": task_type, "priority": priority, "reason_code": reason_code},
            )

        existing = (
            self.db.query(ClaimTask)
            .filter(
                ClaimTask.claim_id == self.claim.id,
                ClaimTask.task_type == task_type,
                ClaimTask.reason_code == reason_code,
                ClaimTask.status.in_(["open", "in_progress"]),
            )
            .first()
        )
        if existing:
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="create_claim_task",
                tool_name="create_claim_task",
                status="executed",
                target_type="claim_task",
                target_id=existing.id,
                summary=f"Existing open task reused: {existing.title}",
                payload={"task_type": task_type, "priority": existing.priority, "assigned_role": existing.assigned_role},
            )

        task = ClaimTask(
            tenant_id=self.claim.tenant_id,
            claim_id=self.claim.id,
            task_type=task_type,
            title=title[:200],
            description=description,
            assigned_role=assigned_role,
            created_by_agent=agent_name,
            priority=priority,
            status="open",
            reason_code=reason_code,
            due_at=datetime.now(timezone.utc) + timedelta(hours=due_hours),
            metadata_json=metadata or {},
        )
        self.db.add(task)
        self.db.flush()
        record_audit_event(
            self.db,
            tenant_id=self.claim.tenant_id,
            claim_id=self.claim.id,
            actor_id=f"agent:{agent_name}",
            actor_role="bounded_agent",
            action="AGENT_TASK_CREATED",
            object_type="claim_task",
            object_id=task.id,
            after_state={"task_type": task_type, "priority": priority, "assigned_role": assigned_role},
            details={"reason_code": reason_code},
        )
        return AgentActionExecution(
            action_id=self._aid(),
            action_type="create_claim_task",
            tool_name="create_claim_task",
            status="executed",
            target_type="claim_task",
            target_id=task.id,
            summary=f"Created task '{title}' assigned to {assigned_role} (priority={priority})",
            payload={"task_id": task.id, "task_type": task_type, "priority": priority, "assigned_role": assigned_role},
        )

    def request_documents(
        self,
        *,
        agent_name: str,
        documents: list[str],
        reason_code: str = "DOCUMENTS_REQUESTED",
        channel: str = "whatsapp",
    ) -> AgentActionExecution:
        if not documents:
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="request_documents",
                tool_name="request_documents",
                status="simulated",
                target_type="claim",
                target_id=self.claim.id if self.claim else "",
                summary="No missing documents to request.",
                payload={},
            )

        if self.db is None or self.claim is None:
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="request_documents",
                tool_name="request_documents",
                status="simulated",
                target_type="communication",
                target_id="sim-doc-req",
                summary=f"[Simulated] Request documents: {', '.join(documents)}",
                payload={"documents": documents, "channel": channel},
            )

        merged = list(dict.fromkeys([*(self.claim.missing_documents or []), *documents]))
        self.claim.missing_documents = merged
        task_exec = self.create_claim_task(
            agent_name=agent_name,
            task_type="document_request",
            title=f"Collect missing evidence: {', '.join(documents[:3])}",
            description=f"Requested documents from policyholder: {', '.join(documents)}",
            assigned_role="policyholder",
            priority="high",
            reason_code=reason_code,
            due_hours=48,
            metadata={"documents": documents},
        )
        comm = Communication(
            tenant_id=self.claim.tenant_id,
            claim_id=self.claim.id,
            channel=channel,
            language=self.claim.preferred_language,
            template_id="DOCUMENT_REQUEST",
            subject=f"Action Needed: Upload Documents for {self.claim.claim_number}",
            body=f"Please upload: {', '.join(documents)}. Registration remains active without blocking (IRDAI 2024).",
            requires_human_review=False,
            delivery_status="sent_mock",
        )
        self.db.add(comm)
        self.db.flush()
        emit_outbox_event(
            self.db,
            tenant_id=self.claim.tenant_id,
            aggregate_id=self.claim.id,
            event_type="DocumentsRequested",
            payload={"documents": documents, "task_id": task_exec.target_id, "communication_id": comm.id},
        )
        return AgentActionExecution(
            action_id=self._aid(),
            action_type="request_documents",
            tool_name="request_documents",
            status="executed",
            target_type="communication",
            target_id=comm.id,
            summary=f"Requested {len(documents)} document(s) via {channel} & created customer task",
            payload={"documents": documents, "task_id": task_exec.target_id, "communication_id": comm.id},
        )

    def schedule_inspection(
        self,
        *,
        agent_name: str,
        surveyor_id: str | None = None,
        ev_required: bool = False,
    ) -> AgentActionExecution:
        if self.db is None or self.claim is None:
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="schedule_inspection",
                tool_name="schedule_inspection",
                status="simulated",
                target_type="survey_assignment",
                target_id=surveyor_id or "auto-surveyor",
                summary="[Simulated] Schedule licensed IIISLA surveyor inspection",
                payload={"surveyor_id": surveyor_id, "ev_required": ev_required},
            )

        existing = (
            self.db.query(SurveyAssignment)
            .filter(SurveyAssignment.claim_id == self.claim.id)
            .order_by(SurveyAssignment.assigned_at.desc())
            .first()
        )
        if existing:
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="schedule_inspection",
                tool_name="schedule_inspection",
                status="executed",
                target_type="survey_assignment",
                target_id=existing.id,
                summary=f"Survey inspection already scheduled (status={existing.status})",
                payload={"survey_assignment_id": existing.id, "surveyor_id": existing.surveyor_id},
            )

        q = self.db.query(Provider).filter(
            Provider.tenant_id == self.claim.tenant_id,
            Provider.provider_type == "surveyor",
            Provider.licence_status == "verified",
            Provider.is_available.is_(True),
        )
        if surveyor_id:
            cand = self.db.query(Provider).filter(
                Provider.tenant_id == self.claim.tenant_id,
                Provider.provider_type == "surveyor",
                Provider.id == surveyor_id,
            ).first()
            if cand:
                lic = IntegrationAdapterRegistry.verify_surveyor_licence(
                    licence_id=cand.licence_or_contract_id,
                    licence_status=cand.licence_status,
                    licence_expiry_at=cand.licence_expiry_at,
                )
                surveyor = cand if (lic["verified"] and cand.is_available and cand.active_load < cand.max_capacity) else None
            else:
                surveyor = None
        else:
            from services.workflow.ecosystem import select_best_surveyor

            all_provs = q.all()
            sel = select_best_surveyor(
                all_provs,
                incident_location=self.claim.incident_location,
                required_skills=["ev_hv"] if ev_required else [],
                ev_required=ev_required,
            )
            surveyor = sel["selected"]

        if not surveyor:
            self.create_claim_task(
                agent_name=agent_name,
                task_type="survey_escalation",
                title="Escalate SLA capacity: no verified surveyor available",
                description="Roster capacity exhausted for automated surveyor scheduling.",
                assigned_role="claims_manager",
                priority="critical",
                reason_code="NO_SURVEYOR_CAPACITY",
                due_hours=4,
            )
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="schedule_inspection",
                tool_name="schedule_inspection",
                status="gated_human_review",
                target_type="provider",
                target_id="",
                summary="No available verified surveyor within capacity; SLA escalation task created.",
                payload={"ev_required": ev_required},
            )

        irdai = get_active_rule(self.db, "IN-IRDAI-MC-2024")["controls"]
        due_at = datetime.now(timezone.utc) + timedelta(days=int(irdai["survey_report_due_days"]))
        sa = SurveyAssignment(
            tenant_id=self.claim.tenant_id,
            claim_id=self.claim.id,
            surveyor_id=surveyor.id,
            status="assigned",
            appointment_at=datetime.now(timezone.utc) + timedelta(hours=12),
            report_due_at=due_at,
        )
        self.db.add(sa)
        surveyor.active_load += 1
        self.claim.assigned_surveyor_id = surveyor.id
        complete_stage_sla_timer(self.db, claim_id=self.claim.id, stage="surveyor_allocation")
        create_stage_sla_timer(self.db, tenant_id=self.claim.tenant_id, claim_id=self.claim.id, stage="survey_report_submission")
        self.db.flush()
        emit_outbox_event(
            self.db,
            tenant_id=self.claim.tenant_id,
            aggregate_id=self.claim.id,
            event_type="SurveyorScheduled",
            payload={"survey_assignment_id": sa.id, "surveyor_id": surveyor.id},
        )
        return AgentActionExecution(
            action_id=self._aid(),
            action_type="schedule_inspection",
            tool_name="schedule_inspection",
            status="executed",
            target_type="survey_assignment",
            target_id=sa.id,
            summary=f"Scheduled licensed surveyor {surveyor.name} (15-day report SLA set)",
            payload={"survey_assignment_id": sa.id, "surveyor_id": surveyor.id, "report_due_at": due_at.isoformat()},
        )

    def notify_garage(
        self,
        *,
        agent_name: str,
        garage_id: str | None = None,
        ev_required: bool = False,
    ) -> AgentActionExecution:
        if self.db is None or self.claim is None:
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="notify_garage",
                tool_name="notify_garage",
                status="simulated",
                target_type="provider",
                target_id=garage_id or "auto-garage",
                summary="[Simulated] Notify network garage of repair intake",
                payload={"garage_id": garage_id, "ev_required": ev_required},
            )

        q = self.db.query(Provider).filter(
            Provider.tenant_id == self.claim.tenant_id,
            Provider.provider_type == "garage",
            Provider.licence_status == "verified",
            Provider.is_available.is_(True),
        )
        garage: Provider | None = None
        if garage_id:
            cand = q.filter(Provider.id == garage_id).first()
            if cand and (not ev_required or cand.ev_capable):
                garage = cand
        if not garage:
            cands = q.order_by(Provider.active_load.asc(), Provider.quality_score.desc()).all()
            if ev_required:
                ev_cands = [c for c in cands if c.ev_capable]
                cands = ev_cands or cands
            else:
                std_cands = [c for c in cands if not c.ev_capable]
                cands = std_cands or cands
            garage = cands[0] if cands else None

        if not garage:
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="notify_garage",
                tool_name="notify_garage",
                status="gated_human_review",
                target_type="provider",
                target_id="",
                summary="No matching network garage found for repair notification.",
                payload={},
            )

        self.claim.assigned_garage_id = garage.id
        comm = Communication(
            tenant_id=self.claim.tenant_id,
            claim_id=self.claim.id,
            channel="portal",
            language="en-IN",
            template_id="GARAGE_INTAKE_NOTICE",
            subject=f"Repair Intake & Pre-Survey Notice: {self.claim.claim_number}",
            body=f"Vehicle {self.claim.vehicle_reg_input} assigned to {garage.name}. {'Mandatory EV HV isolation required.' if ev_required else 'Standard cashless estimate flow.'}",
            requires_human_review=False,
            delivery_status="sent_mock",
        )
        self.db.add(comm)
        self.db.flush()
        emit_outbox_event(
            self.db,
            tenant_id=self.claim.tenant_id,
            aggregate_id=self.claim.id,
            event_type="GarageNotified",
            payload={"garage_id": garage.id, "garage_name": garage.name, "ev_required": ev_required},
        )
        return AgentActionExecution(
            action_id=self._aid(),
            action_type="notify_garage",
            tool_name="notify_garage",
            status="executed",
            target_type="provider",
            target_id=garage.id,
            summary=f"Notified {garage.name} (EV capable={garage.ev_capable})",
            payload={"garage_id": garage.id, "garage_name": garage.name, "communication_id": comm.id},
        )

    def dispatch_towing(self, *, agent_name: str, ev_flatbed: bool = False) -> AgentActionExecution:
        tow_type = "EV Flatbed Recovery" if ev_flatbed else "Standard Roadside Tow"
        task_exec = self.create_claim_task(
            agent_name=agent_name,
            task_type="towing_dispatch",
            title=f"Dispatch {tow_type} to {self.claim.incident_location[:60] if self.claim else 'accident site'}",
            description=f"{tow_type} requested due to immobile/unsafe vehicle status.",
            assigned_role="claims_handler",
            priority="critical" if ev_flatbed else "high",
            reason_code="TOWING_DISPATCHED",
            due_hours=2,
            metadata={"ev_flatbed": ev_flatbed},
        )
        if self.db is not None and self.claim is not None:
            emit_outbox_event(
                self.db,
                tenant_id=self.claim.tenant_id,
                aggregate_id=self.claim.id,
                event_type="TowingDispatched",
                payload={"ev_flatbed": ev_flatbed, "task_id": task_exec.target_id},
            )
        return AgentActionExecution(
            action_id=self._aid(),
            action_type="dispatch_towing",
            tool_name="dispatch_towing",
            status="executed" if self.db is not None else "simulated",
            target_type="claim_task",
            target_id=task_exec.target_id,
            summary=f"Dispatched {tow_type} task",
            payload={"ev_flatbed": ev_flatbed, "task_id": task_exec.target_id},
        )

    def update_claim_status(
        self,
        *,
        agent_name: str,
        target_status: str,
        next_expected_action: str | None = None,
        actor: str = "agent",
    ) -> AgentActionExecution:
        if actor != "orchestrator":
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="update_claim_status",
                tool_name="update_claim_status",
                status="blocked_policy",
                target_type="claim",
                target_id=self.claim.id if self.claim else "",
                summary=(
                    f"Blocked direct transition to '{target_status}' by '{agent_name}': "
                    "ClaimOrchestrator exclusively owns claim state transitions."
                ),
                payload={"requested_status": target_status, "actor": actor},
            )

        if self.db is None or self.claim is None:
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="update_claim_status",
                tool_name="update_claim_status",
                status="simulated",
                target_type="claim",
                target_id="",
                summary=f"[Simulated] Orchestrator transition status -> {target_status}",
                payload={"target_status": target_status},
            )

        before = self.claim.status
        try:
            validated = validate_transition(self.claim.status, target_status).value
        except Exception as exc:
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="update_claim_status",
                tool_name="update_claim_status",
                status="blocked_policy",
                target_type="claim",
                target_id=self.claim.id,
                summary=f"State machine blocked transition {before} -> {target_status}: {exc}",
                payload={"from": before, "to": target_status},
            )

        self.claim.status = validated
        if next_expected_action:
            self.claim.next_expected_action = next_expected_action[:200]
        self.db.flush()
        record_audit_event(
            self.db,
            tenant_id=self.claim.tenant_id,
            claim_id=self.claim.id,
            actor_id="orchestrator",
            actor_role="orchestrator",
            action="CLAIM_STATUS_UPDATED_BY_ORCHESTRATOR",
            object_type="claim",
            object_id=self.claim.id,
            before_state={"status": before},
            after_state={"status": validated},
            details={"trigger_agent": agent_name},
        )
        return AgentActionExecution(
            action_id=self._aid(),
            action_type="update_claim_status",
            tool_name="update_claim_status",
            status="executed",
            target_type="claim",
            target_id=self.claim.id,
            summary=f"Orchestrator transitioned claim status {before} -> {validated}",
            payload={"from": before, "to": validated},
        )

    def generate_approval_request(
        self,
        *,
        agent_name: str,
        settlement_id: str | None,
        amount_inr: Decimal,
        required_tier: str,
        rationale: str,
    ) -> AgentActionExecution:
        if self.db is None or self.claim is None or not settlement_id:
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="generate_approval_request",
                tool_name="generate_approval_request",
                status="simulated",
                target_type="approval",
                target_id="sim-approval",
                summary=f"[Simulated] Generate DoA approval request for INR {amount_inr} ({required_tier})",
                payload={"amount_inr": str(amount_inr), "required_tier": required_tier},
            )

        existing = (
            self.db.query(Approval)
            .filter(
                Approval.claim_id == self.claim.id,
                Approval.settlement_id == settlement_id,
                Approval.decision == "pending",
            )
            .first()
        )
        if existing:
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="generate_approval_request",
                tool_name="generate_approval_request",
                status="executed",
                target_type="approval",
                target_id=existing.id,
                summary=f"Existing pending DoA approval request linked ({required_tier})",
                payload={"approval_id": existing.id, "required_tier": required_tier},
            )

        maker_id = self.user.user_id if self.user else f"agent:{agent_name}"
        app = Approval(
            tenant_id=self.claim.tenant_id,
            claim_id=self.claim.id,
            settlement_id=settlement_id,
            action_type="settlement_checker",
            amount_inr=amount_inr,
            maker_user_id=maker_id,
            decision="pending",
            rationale=rationale,
        )
        self.db.add(app)
        self.db.flush()
        self.create_claim_task(
            agent_name=agent_name,
            task_type="settlement_approval",
            title=f"Maker-Checker DoA Approval: INR {amount_inr}",
            description=rationale,
            assigned_role=required_tier,
            priority="high",
            reason_code="DOA_APPROVAL_REQUIRED",
            due_hours=24,
            metadata={"approval_id": app.id, "settlement_id": settlement_id},
        )
        return AgentActionExecution(
            action_id=self._aid(),
            action_type="generate_approval_request",
            tool_name="generate_approval_request",
            status="executed",
            target_type="approval",
            target_id=app.id,
            summary=f"Generated DoA approval request ({required_tier}) for INR {amount_inr}",
            payload={"approval_id": app.id, "amount_inr": str(amount_inr), "required_tier": required_tier},
        )

    def initiate_approved_payment(
        self,
        *,
        agent_name: str,
        settlement_id: str,
        idempotency_key: str,
        payee_name: str,
        payee_type: str = "garage",
        account_last4: str = "4821",
        ifsc: str = "HDFC0000123",
        simulate_timeout: bool = False,
    ) -> AgentActionExecution:
        if self.db is None or self.claim is None:
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="initiate_approved_payment",
                tool_name="initiate_approved_payment",
                status="gated_human_review",
                target_type="payment",
                target_id="",
                summary="Payment execution requires persisted approved settlement and Finance authority.",
                payload={},
            )

        if self.user and self.user.role not in {Role.FINANCE_APPROVER, Role.ADMIN}:
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="initiate_approved_payment",
                tool_name="initiate_approved_payment",
                status="blocked_policy",
                target_type="payment",
                target_id="",
                summary=f"Blocked: role '{self.user.role.value}' lacks Finance Approver authority.",
                payload={"required_role": "finance_approver"},
            )

        stl = (
            self.db.query(Settlement)
            .filter(Settlement.id == settlement_id, Settlement.claim_id == self.claim.id)
            .first()
        )
        if not stl or stl.approval_status != "approved":
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="initiate_approved_payment",
                tool_name="initiate_approved_payment",
                status="gated_human_review",
                target_type="settlement",
                target_id=settlement_id,
                summary="Blocked: settlement is not yet Maker-Checker approved.",
                payload={"approval_status": stl.approval_status if stl else "missing"},
            )

        existing = (
            self.db.query(Payment)
            .filter(Payment.tenant_id == self.claim.tenant_id, Payment.idempotency_key == idempotency_key)
            .first()
        )
        if existing:
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="initiate_approved_payment",
                tool_name="initiate_approved_payment",
                status="executed",
                target_type="payment",
                target_id=existing.id,
                summary=f"Idempotent replay of existing payment {existing.id} ({existing.status})",
                payload={"idempotent_replay": True, "payment_id": existing.id, "gateway_reference": existing.gateway_reference},
            )

        bank_res = IntegrationAdapterRegistry.validate_bank_account(account_last4, ifsc)
        pg_res = IntegrationAdapterRegistry.execute_payment(
            idempotency_key=idempotency_key,
            amount_inr=Decimal(str(stl.net_payable_inr)),
            payee_name=payee_name,
            simulate_timeout=simulate_timeout,
        )
        pmt = Payment(
            tenant_id=self.claim.tenant_id,
            claim_id=self.claim.id,
            settlement_id=stl.id,
            idempotency_key=idempotency_key,
            payee_type=payee_type,
            payee_name=payee_name,
            bank_account_masked=mask_bank_account(account_last4),
            bank_verified=bank_res["verified"],
            amount_inr=Decimal(str(stl.net_payable_inr)),
            status=pg_res["status"],
            gateway_reference=pg_res["gateway_reference"],
            approved_by_finance_id=self.user.user_id if self.user else f"agent:{agent_name}",
        )
        self.db.add(pmt)
        self.db.flush()
        if self.claim.status == ClaimStatus.APPROVED.value:
            self.claim.status = validate_transition(self.claim.status, ClaimStatus.PAYMENT_PENDING.value).value
        emit_outbox_event(
            self.db,
            tenant_id=self.claim.tenant_id,
            aggregate_id=self.claim.id,
            event_type="PaymentConfirmed" if pmt.status == "confirmed" else "PaymentRequested",
            payload={"payment_id": pmt.id, "status": pmt.status, "gateway_reference": pmt.gateway_reference},
        )
        record_audit_event(
            self.db,
            tenant_id=self.claim.tenant_id,
            claim_id=self.claim.id,
            actor_id=self.user.user_id if self.user else f"agent:{agent_name}",
            actor_role=self.user.role.value if self.user else "bounded_agent",
            action="AGENT_CONTROLLED_PAYMENT_INITIATED",
            object_type="payment",
            object_id=pmt.id,
            after_state={"status": pmt.status, "amount_inr": str(pmt.amount_inr), "ref": pmt.gateway_reference},
        )
        return AgentActionExecution(
            action_id=self._aid(),
            action_type="initiate_approved_payment",
            tool_name="initiate_approved_payment",
            status="executed",
            target_type="payment",
            target_id=pmt.id,
            summary=f"Initiated approved payment INR {pmt.amount_inr} to {payee_name} ({pmt.status})",
            payload={"payment_id": pmt.id, "status": pmt.status, "gateway_reference": pmt.gateway_reference},
        )

    def send_customer_update(
        self,
        *,
        agent_name: str,
        channel: str,
        language: str,
        template_id: str,
        subject: str,
        body: str,
        is_adverse: bool = False,
    ) -> AgentActionExecution:
        if self.db is None or self.claim is None:
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="send_customer_update",
                tool_name="send_customer_update",
                status="gated_human_review" if is_adverse else "simulated",
                target_type="communication",
                target_id="sim-comm",
                summary=f"[Simulated] {template_id} ({language}) via {channel}",
                payload={"channel": channel, "language": language, "is_adverse": is_adverse},
            )

        delivery_status = "pending_human_review" if is_adverse else "sent_mock"
        comm = Communication(
            tenant_id=self.claim.tenant_id,
            claim_id=self.claim.id,
            channel=channel,
            language=language,
            template_id=template_id,
            subject=subject[:240],
            body=body,
            requires_human_review=is_adverse,
            approved_by=None if is_adverse else f"agent:{agent_name}",
            delivery_status=delivery_status,
        )
        self.db.add(comm)
        self.db.flush()
        if is_adverse:
            self.create_claim_task(
                agent_name=agent_name,
                task_type="adverse_comm_review",
                title=f"Approve adverse communication: {subject[:80]}",
                description=body,
                assigned_role="claims_manager",
                priority="high",
                reason_code="ADVERSE_COMM_GATE",
                due_hours=12,
            )
        emit_outbox_event(
            self.db,
            tenant_id=self.claim.tenant_id,
            aggregate_id=self.claim.id,
            event_type="CustomerNotified" if not is_adverse else "CustomerCommunicationHeldForReview",
            payload={"communication_id": comm.id, "channel": channel, "language": language},
        )
        return AgentActionExecution(
            action_id=self._aid(),
            action_type="send_customer_update",
            tool_name="send_customer_update",
            status="gated_human_review" if is_adverse else "executed",
            target_type="communication",
            target_id=comm.id,
            summary=f"{'Queued adverse notice for human approval' if is_adverse else 'Dispatched update'} ({language}) via {channel}",
            payload={"communication_id": comm.id, "delivery_status": delivery_status, "language": language},
        )

    def reschedule_inspection(
        self,
        *,
        agent_name: str,
        new_appointment_at: str,
        reason: str,
    ) -> AgentActionExecution:
        if self.db is None or self.claim is None:
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="reschedule_inspection",
                tool_name="reschedule_inspection",
                status="simulated",
                target_type="survey_assignment",
                target_id="sim-resched",
                summary=f"[Simulated] Reschedule inspection to {new_appointment_at} ({reason})",
                payload={"new_appointment_at": new_appointment_at, "reason": reason},
            )
        from services.workflow.ecosystem import reschedule_claim_inspection

        dt = datetime.fromisoformat(new_appointment_at.replace("Z", "+00:00"))
        actor = self.user or UserContext(
            user_id=f"agent:{agent_name}",
            tenant_id=self.claim.tenant_id,
            email=f"{agent_name}@system.local",
            name=agent_name,
            role=Role.CLAIMS_HANDLER,
        )
        coord = reschedule_claim_inspection(self.db, self.claim, user=actor, new_appointment_at=dt, reason=reason)
        return AgentActionExecution(
            action_id=self._aid(),
            action_type="reschedule_inspection",
            tool_name="reschedule_inspection",
            status="executed",
            target_type="ecosystem_coordination",
            target_id=coord.id,
            summary=f"Rescheduled inspection to {new_appointment_at} (reschedule #{coord.inspection_reschedule_count})",
            payload={"reschedule_count": coord.inspection_reschedule_count, "reason": reason},
        )

    def check_parts_availability(
        self,
        *,
        agent_name: str,
        garage_name: str = "Network Garage",
        parts_stock_status: str = "in_stock",
        parts_lead_time_days: int = 2,
        part_items: list[dict[str, Any]] | None = None,
    ) -> AgentActionExecution:
        res = IntegrationAdapterRegistry.check_parts_availability(
            garage_name=garage_name,
            parts_stock_status=parts_stock_status,
            parts_lead_time_days=parts_lead_time_days,
            part_items=part_items or [{"part_code": "PRT-FRT-BMP-01", "description": "Front Bumper Assembly"}],
        )
        return AgentActionExecution(
            action_id=self._aid(),
            action_type="check_parts_availability",
            tool_name="check_parts_availability",
            status="executed" if self.db is not None else "simulated",
            target_type="parts_catalogue",
            target_id=res["parts_status"],
            summary=f"Parts check: {res['parts_status']} across {len(res['items'])} part(s)",
            payload=res,
        )

    def schedule_pickup_delivery(
        self,
        *,
        agent_name: str,
        mode: str = "pickup",
        ev_flatbed: bool = False,
    ) -> AgentActionExecution:
        res = IntegrationAdapterRegistry.dispatch_pickup_delivery(
            mode=mode,
            location=self.claim.incident_location if self.claim else "Customer Location",
            garage_name="Assigned Garage",
            ev_flatbed=ev_flatbed,
        )
        return AgentActionExecution(
            action_id=self._aid(),
            action_type="schedule_pickup_delivery",
            tool_name="schedule_pickup_delivery",
            status="executed" if self.db is not None else "simulated",
            target_type="logistics",
            target_id=res["dispatch_ref"],
            summary=f"Scheduled vehicle {mode} ({res['dispatch_ref']})",
            payload=res,
        )

    def send_surveyor_followup(
        self,
        *,
        agent_name: str,
        notes: str = "IRDAI 15-day report SLA follow-up",
        escalate_to_manager: bool = False,
    ) -> AgentActionExecution:
        if self.db is None or self.claim is None:
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="send_surveyor_followup",
                tool_name="send_surveyor_followup",
                status="simulated",
                target_type="survey_assignment",
                target_id="sim-followup",
                summary=f"[Simulated] Surveyor report follow-up ({notes})",
                payload={"escalate_to_manager": escalate_to_manager},
            )
        from services.workflow.ecosystem import send_surveyor_report_followup

        actor = self.user or UserContext(
            user_id=f"agent:{agent_name}",
            tenant_id=self.claim.tenant_id,
            email=f"{agent_name}@system.local",
            name=agent_name,
            role=Role.CLAIMS_HANDLER,
        )
        coord = send_surveyor_report_followup(
            self.db, self.claim, user=actor, notes=notes, escalate_to_manager=escalate_to_manager
        )
        return AgentActionExecution(
            action_id=self._aid(),
            action_type="send_surveyor_followup",
            tool_name="send_surveyor_followup",
            status="executed",
            target_type="ecosystem_coordination",
            target_id=coord.id,
            summary=f"Sent surveyor report follow-up #{coord.surveyor_followup_count}",
            payload={"followup_count": coord.surveyor_followup_count, "status": coord.surveyor_followup_status},
        )

    def confirm_repair_completion(
        self,
        *,
        agent_name: str,
        milestone: str = "repair_completed",
        notes: str = "QC passed and handover ready",
    ) -> AgentActionExecution:
        if self.db is None or self.claim is None:
            return AgentActionExecution(
                action_id=self._aid(),
                action_type="confirm_repair_completion",
                tool_name="confirm_repair_completion",
                status="simulated",
                target_type="ecosystem_coordination",
                target_id="sim-repair-done",
                summary=f"[Simulated] Confirm repair completion ({milestone})",
                payload={"milestone": milestone, "notes": notes},
            )
        from services.workflow.ecosystem import update_repair_milestone_and_confirm

        actor = self.user or UserContext(
            user_id=f"agent:{agent_name}",
            tenant_id=self.claim.tenant_id,
            email=f"{agent_name}@system.local",
            name=agent_name,
            role=Role.CLAIMS_HANDLER,
        )
        coord = update_repair_milestone_and_confirm(
            self.db, self.claim, user=actor, milestone=milestone, notes=notes, confirm_completion=True
        )
        return AgentActionExecution(
            action_id=self._aid(),
            action_type="confirm_repair_completion",
            tool_name="confirm_repair_completion",
            status="executed",
            target_type="ecosystem_coordination",
            target_id=coord.id,
            summary=f"Confirmed repair completion ({milestone})",
            payload={"milestone": milestone, "confirmed": coord.repair_completion_confirmed},
        )
