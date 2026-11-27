"""add_orchestration_engine_tables

Revision ID: c4d9a2e17b05
Revises: 8b3e1f2d9c04
Create Date: 2026-11-27 11:50:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d9a2e17b05"
down_revision: Union[str, None] = "8b3e1f2d9c04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "orchestration_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("claim_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=64), nullable=False),
        sa.Column("task_key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("agent_or_service", sa.String(length=64), nullable=False),
        sa.Column("execution_mode", sa.String(length=24), nullable=False),
        sa.Column("parallel_group", sa.String(length=64), nullable=True),
        sa.Column("depends_on", sa.JSON(), nullable=False),
        sa.Column("condition_expression", sa.String(length=200), nullable=True),
        sa.Column("target_state", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("backoff_delay_ms", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_history", sa.JSON(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("output_payload", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_orch_task_idempotency"),
    )
    op.create_index(op.f("ix_orchestration_tasks_agent_or_service"), "orchestration_tasks", ["agent_or_service"], unique=False)
    op.create_index(op.f("ix_orchestration_tasks_claim_id"), "orchestration_tasks", ["claim_id"], unique=False)
    op.create_index(op.f("ix_orchestration_tasks_status"), "orchestration_tasks", ["status"], unique=False)
    op.create_index(op.f("ix_orchestration_tasks_task_key"), "orchestration_tasks", ["task_key"], unique=False)
    op.create_index(op.f("ix_orchestration_tasks_tenant_id"), "orchestration_tasks", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_orchestration_tasks_workflow_run_id"), "orchestration_tasks", ["workflow_run_id"], unique=False)

    op.create_table(
        "orchestration_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("claim_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("processing_status", sa.String(length=32), nullable=False),
        sa.Column("resulting_state", sa.String(length=40), nullable=True),
        sa.Column("duplicate_hits", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "claim_id", "event_id", name="uq_orch_event_dedup"),
    )
    op.create_index(op.f("ix_orchestration_events_claim_id"), "orchestration_events", ["claim_id"], unique=False)
    op.create_index(op.f("ix_orchestration_events_event_id"), "orchestration_events", ["event_id"], unique=False)
    op.create_index(op.f("ix_orchestration_events_event_type"), "orchestration_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_orchestration_events_tenant_id"), "orchestration_events", ["tenant_id"], unique=False)

    op.create_table(
        "dead_letter_queue",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("claim_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("task_key", sa.String(length=64), nullable=False),
        sa.Column("agent_or_service", sa.String(length=64), nullable=False),
        sa.Column("state_at_failure", sa.String(length=40), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("retry_history", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("resolved_by", sa.String(length=64), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dead_letter_queue_claim_id"), "dead_letter_queue", ["claim_id"], unique=False)
    op.create_index(op.f("ix_dead_letter_queue_status"), "dead_letter_queue", ["status"], unique=False)
    op.create_index(op.f("ix_dead_letter_queue_task_id"), "dead_letter_queue", ["task_id"], unique=False)
    op.create_index(op.f("ix_dead_letter_queue_tenant_id"), "dead_letter_queue", ["tenant_id"], unique=False)

    op.create_table(
        "compensation_workflows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("claim_id", sa.String(length=36), nullable=False),
        sa.Column("trigger_reason", sa.String(length=200), nullable=False),
        sa.Column("failed_state", sa.String(length=40), nullable=False),
        sa.Column("compensating_action", sa.String(length=80), nullable=False),
        sa.Column("target_object_type", sa.String(length=64), nullable=False),
        sa.Column("target_object_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_compensation_workflows_claim_id"), "compensation_workflows", ["claim_id"], unique=False)
    op.create_index(op.f("ix_compensation_workflows_tenant_id"), "compensation_workflows", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_compensation_workflows_tenant_id"), table_name="compensation_workflows")
    op.drop_index(op.f("ix_compensation_workflows_claim_id"), table_name="compensation_workflows")
    op.drop_table("compensation_workflows")
    op.drop_index(op.f("ix_dead_letter_queue_task_id"), table_name="dead_letter_queue")
    op.drop_index(op.f("ix_dead_letter_queue_status"), table_name="dead_letter_queue")
    op.drop_index(op.f("ix_dead_letter_queue_claim_id"), table_name="dead_letter_queue")
    op.drop_index(op.f("ix_dead_letter_queue_tenant_id"), table_name="dead_letter_queue")
    op.drop_table("dead_letter_queue")
    op.drop_index(op.f("ix_orchestration_events_tenant_id"), table_name="orchestration_events")
    op.drop_index(op.f("ix_orchestration_events_event_type"), table_name="orchestration_events")
    op.drop_index(op.f("ix_orchestration_events_event_id"), table_name="orchestration_events")
    op.drop_index(op.f("ix_orchestration_events_claim_id"), table_name="orchestration_events")
    op.drop_table("orchestration_events")
    op.drop_index(op.f("ix_orchestration_tasks_workflow_run_id"), table_name="orchestration_tasks")
    op.drop_index(op.f("ix_orchestration_tasks_tenant_id"), table_name="orchestration_tasks")
    op.drop_index(op.f("ix_orchestration_tasks_task_key"), table_name="orchestration_tasks")
    op.drop_index(op.f("ix_orchestration_tasks_status"), table_name="orchestration_tasks")
    op.drop_index(op.f("ix_orchestration_tasks_claim_id"), table_name="orchestration_tasks")
    op.drop_index(op.f("ix_orchestration_tasks_agent_or_service"), table_name="orchestration_tasks")
    op.drop_table("orchestration_tasks")
