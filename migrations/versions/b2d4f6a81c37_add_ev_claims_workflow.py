"""add_ev_claims_workflow

Revision ID: b2d4f6a81c37
Revises: a1c5e7b92f36
Create Date: 2026-11-27 19:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2d4f6a81c37"
down_revision = "a1c5e7b92f36"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ev_claim_cases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("claim_id", sa.String(length=36), sa.ForeignKey("claims.id"), nullable=False, unique=True),
        sa.Column("case_number", sa.String(length=40), nullable=False, unique=True),
        sa.Column("stage", sa.String(length=40), nullable=False, server_default="INTAKE_TRIAGE"),
        sa.Column("queue_name", sa.String(length=64), nullable=False, server_default="ev_triage_intake"),
        sa.Column("stage_history", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("risk_class", sa.String(length=24), nullable=False, server_default="hv_suspected"),
        sa.Column("operation_status", sa.String(length=48), nullable=False, server_default="hold_do_not_operate_pending_inspection"),
        sa.Column("triage", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("safety_escalations", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("thermal_watch", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("recovery", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("survey", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("diagnostics", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("disposition", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("benchmark", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("technical_signoff", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("settlement_clearance", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("recertification", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("salvage", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("closure", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(length=36), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ev_claim_cases_claim_id", "ev_claim_cases", ["claim_id"])
    op.create_index("ix_ev_claim_cases_stage", "ev_claim_cases", ["stage"])
    op.create_index("ix_ev_claim_cases_queue_name", "ev_claim_cases", ["queue_name"])
    op.create_index("ix_ev_claim_cases_risk_class", "ev_claim_cases", ["risk_class"])


def downgrade() -> None:
    op.drop_index("ix_ev_claim_cases_risk_class", table_name="ev_claim_cases")
    op.drop_index("ix_ev_claim_cases_queue_name", table_name="ev_claim_cases")
    op.drop_index("ix_ev_claim_cases_stage", table_name="ev_claim_cases")
    op.drop_index("ix_ev_claim_cases_claim_id", table_name="ev_claim_cases")
    op.drop_table("ev_claim_cases")
