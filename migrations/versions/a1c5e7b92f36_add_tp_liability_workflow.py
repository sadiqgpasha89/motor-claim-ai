"""add_tp_liability_workflow

Revision ID: a1c5e7b92f36
Revises: f9a2b4d83e21
Create Date: 2026-11-27 18:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1c5e7b92f36"
down_revision: Union[str, None] = "f9a2b4d83e21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tp_claim_cases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("claim_id", sa.String(length=36), sa.ForeignKey("claims.id"), nullable=False, unique=True),
        sa.Column("case_number", sa.String(length=40), nullable=False, unique=True),
        sa.Column("linked_od_claim_id", sa.String(length=36), nullable=True),
        sa.Column("tp_category", sa.String(length=24), nullable=False, server_default="bodily_injury"),
        sa.Column("stage", sa.String(length=40), nullable=False, server_default="INTAKE"),
        sa.Column("queue_name", sa.String(length=64), nullable=False, server_default="tp_intake"),
        sa.Column("stage_history", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("coverage_status", sa.String(length=24), nullable=False, server_default="unchecked"),
        sa.Column("coverage_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("third_parties", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("accident_facts", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("evidence_items", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("police_report", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("liability_assessment", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("legal_documents", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("tribunal", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("advocates", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("medical_review", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("legal_review", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("reserve_inr", sa.Numeric(14, 2), nullable=False, server_default="0.00"),
        sa.Column("reserve_history", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("settlement_proposals", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("approved_proposal_id", sa.String(length=36), nullable=True),
        sa.Column("payment_authorisation", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("closure", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(length=36), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tp_claim_cases_claim_id", "tp_claim_cases", ["claim_id"])
    op.create_index("ix_tp_claim_cases_tp_category", "tp_claim_cases", ["tp_category"])
    op.create_index("ix_tp_claim_cases_stage", "tp_claim_cases", ["stage"])
    op.create_index("ix_tp_claim_cases_queue_name", "tp_claim_cases", ["queue_name"])


def downgrade() -> None:
    op.drop_index("ix_tp_claim_cases_queue_name", table_name="tp_claim_cases")
    op.drop_index("ix_tp_claim_cases_stage", table_name="tp_claim_cases")
    op.drop_index("ix_tp_claim_cases_tp_category", table_name="tp_claim_cases")
    op.drop_index("ix_tp_claim_cases_claim_id", table_name="tp_claim_cases")
    op.drop_table("tp_claim_cases")
