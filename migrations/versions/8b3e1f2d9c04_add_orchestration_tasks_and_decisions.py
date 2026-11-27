"""add_orchestration_tasks_and_decisions

Revision ID: 8b3e1f2d9c04
Revises: 521c523feafe
Create Date: 2026-11-27 11:32:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "8b3e1f2d9c04"
down_revision: Union[str, None] = "521c523feafe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "claim_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("claim_id", sa.String(length=36), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("assigned_role", sa.String(length=40), nullable=False),
        sa.Column("assigned_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_agent", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_claim_tasks_claim_id"), "claim_tasks", ["claim_id"], unique=False)
    op.create_index(op.f("ix_claim_tasks_status"), "claim_tasks", ["status"], unique=False)
    op.create_index(op.f("ix_claim_tasks_task_type"), "claim_tasks", ["task_type"], unique=False)
    op.create_index(op.f("ix_claim_tasks_tenant_id"), "claim_tasks", ["tenant_id"], unique=False)

    op.create_table(
        "agent_execution_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("claim_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=64), nullable=False),
        sa.Column("agent_name", sa.String(length=64), nullable=False),
        sa.Column("stage_order", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("dependencies_satisfied", sa.Boolean(), nullable=False),
        sa.Column("depends_on", sa.JSON(), nullable=False),
        sa.Column("published_result", sa.JSON(), nullable=False),
        sa.Column("actions_executed", sa.JSON(), nullable=False),
        sa.Column("rework_requests", sa.JSON(), nullable=False),
        sa.Column("decision", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agent_execution_records_agent_name"), "agent_execution_records", ["agent_name"], unique=False)
    op.create_index(op.f("ix_agent_execution_records_claim_id"), "agent_execution_records", ["claim_id"], unique=False)
    op.create_index(op.f("ix_agent_execution_records_status"), "agent_execution_records", ["status"], unique=False)
    op.create_index(op.f("ix_agent_execution_records_tenant_id"), "agent_execution_records", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_agent_execution_records_workflow_run_id"), "agent_execution_records", ["workflow_run_id"], unique=False)

    op.create_table(
        "decision_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("claim_id", sa.String(length=36), nullable=False),
        sa.Column("agent_name", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("decision_id", sa.String(length=64), nullable=False),
        sa.Column("routing_outcome", sa.String(length=80), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("policy_rule_refs", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("confidence_band", sa.String(length=16), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("alternatives_considered", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_decision_records_agent_name"), "decision_records", ["agent_name"], unique=False)
    op.create_index(op.f("ix_decision_records_claim_id"), "decision_records", ["claim_id"], unique=False)
    op.create_index(op.f("ix_decision_records_decision_id"), "decision_records", ["decision_id"], unique=False)
    op.create_index(op.f("ix_decision_records_tenant_id"), "decision_records", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_decision_records_tenant_id"), table_name="decision_records")
    op.drop_index(op.f("ix_decision_records_decision_id"), table_name="decision_records")
    op.drop_index(op.f("ix_decision_records_claim_id"), table_name="decision_records")
    op.drop_index(op.f("ix_decision_records_agent_name"), table_name="decision_records")
    op.drop_table("decision_records")
    op.drop_index(op.f("ix_agent_execution_records_workflow_run_id"), table_name="agent_execution_records")
    op.drop_index(op.f("ix_agent_execution_records_tenant_id"), table_name="agent_execution_records")
    op.drop_index(op.f("ix_agent_execution_records_status"), table_name="agent_execution_records")
    op.drop_index(op.f("ix_agent_execution_records_claim_id"), table_name="agent_execution_records")
    op.drop_index(op.f("ix_agent_execution_records_agent_name"), table_name="agent_execution_records")
    op.drop_table("agent_execution_records")
    op.drop_index(op.f("ix_claim_tasks_tenant_id"), table_name="claim_tasks")
    op.drop_index(op.f("ix_claim_tasks_task_type"), table_name="claim_tasks")
    op.drop_index(op.f("ix_claim_tasks_status"), table_name="claim_tasks")
    op.drop_index(op.f("ix_claim_tasks_claim_id"), table_name="claim_tasks")
    op.drop_table("claim_tasks")
