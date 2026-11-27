"""add event deliveries, tool invocations and audit hash chain

Revision ID: d3a6b8c1e275
Revises: c8e5a7b13d90
Create Date: 2026-11-28
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3a6b8c1e275"
down_revision: Union[str, None] = "c8e5a7b13d90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("audit_events") as batch:
        batch.add_column(sa.Column("prev_event_hash", sa.String(64), nullable=False, server_default=""))
        batch.add_column(sa.Column("event_hash", sa.String(64), nullable=False, server_default=""))
    op.create_index("ix_audit_events_tenant_created", "audit_events", ["tenant_id", "created_at"])

    op.create_table(
        "event_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("outbox_event_id", sa.String(36), sa.ForeignKey("outbox_events.id"), nullable=False, index=True),
        sa.Column("consumer", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("outbox_event_id", "consumer", name="uq_event_delivery_consumer"),
    )
    op.create_table(
        "tool_invocations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("claim_id", sa.String(36), sa.ForeignKey("claims.id"), nullable=False, index=True),
        sa.Column("tool", sa.String(64), nullable=False, index=True),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result", sa.JSON, nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "tool", "idempotency_key", name="uq_tool_invocation_idempotency"),
    )


def downgrade() -> None:
    op.drop_table("tool_invocations")
    op.drop_table("event_deliveries")
    op.drop_index("ix_audit_events_tenant_created", table_name="audit_events")
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_column("event_hash")
        batch.drop_column("prev_event_hash")
