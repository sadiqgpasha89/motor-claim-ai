"""add_agent_trace_store_fields

Revision ID: c8e5a7b13d90
Revises: b2d4f6a81c37
Create Date: 2026-11-28 09:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8e5a7b13d90"
down_revision: Union[str, None] = "b2d4f6a81c37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "agent_execution_records"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("agent_version", sa.String(length=24), nullable=False, server_default="2.0.0"))
    op.add_column(_TABLE, sa.Column("model_name", sa.String(length=80), nullable=False, server_default=""))
    op.add_column(_TABLE, sa.Column("model_version", sa.String(length=40), nullable=False, server_default=""))
    op.add_column(_TABLE, sa.Column("prompt_version", sa.String(length=24), nullable=False, server_default=""))
    op.add_column(_TABLE, sa.Column("task_input_ref", sa.String(length=160), nullable=False, server_default=""))
    op.add_column(_TABLE, sa.Column("tool_calls", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column(_TABLE, sa.Column("tool_outputs", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column(_TABLE, sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(_TABLE, sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(_TABLE, sa.Column("tokens_input", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(_TABLE, sa.Column("tokens_output", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(_TABLE, sa.Column("usage_source", sa.String(length=16), nullable=False, server_default="estimated"))
    op.add_column(_TABLE, sa.Column("cost_inr", sa.Numeric(precision=12, scale=4), nullable=False, server_default="0"))
    op.add_column(_TABLE, sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(_TABLE, sa.Column("outcome", sa.String(length=32), nullable=False, server_default="success"))
    op.add_column(_TABLE, sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True))
    op.add_column(_TABLE, sa.Column("error_details", sa.JSON(), nullable=True))
    op.add_column(_TABLE, sa.Column("human_intervention", sa.JSON(), nullable=True))
    op.add_column(_TABLE, sa.Column("final_action", sa.String(length=160), nullable=False, server_default=""))
    op.create_index(op.f("ix_agent_execution_records_outcome"), _TABLE, ["outcome"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_execution_records_outcome"), table_name=_TABLE)
    with op.batch_alter_table(_TABLE) as batch:
        for col in (
            "final_action", "human_intervention", "error_details", "confidence", "outcome", "retry_count",
            "cost_inr", "usage_source", "tokens_output", "tokens_input", "ended_at", "started_at",
            "tool_outputs", "tool_calls", "task_input_ref", "prompt_version", "model_version",
            "model_name", "agent_version",
        ):
            batch.drop_column(col)
