"""add_risk_based_claim_processing

Revision ID: d7e2f4a81b10
Revises: c4d9a2e17b05
Create Date: 2026-11-27 12:15:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7e2f4a81b10"
down_revision: Union[str, None] = "c4d9a2e17b05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("claims", sa.Column("risk_tier", sa.String(length=16), nullable=False, server_default="MEDIUM"))
    op.add_column("claims", sa.Column("operational_path", sa.String(length=32), nullable=False, server_default="standard"))
    op.add_column("claims", sa.Column("risk_score", sa.Integer(), nullable=False, server_default="35"))
    op.add_column("claims", sa.Column("fraud_signal_score", sa.Numeric(precision=4, scale=3), nullable=False, server_default="0.000"))
    op.add_column("claims", sa.Column("multiple_vehicles_involved", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("claims", sa.Column("involved_vehicles_count", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("claims", sa.Column("legal_dispute", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("claims", sa.Column("risk_assessment", sa.JSON(), nullable=True))
    op.add_column("claims", sa.Column("risk_history", sa.JSON(), nullable=False, server_default="[]"))
    op.create_index(op.f("ix_claims_operational_path"), "claims", ["operational_path"], unique=False)
    op.create_index(op.f("ix_claims_risk_tier"), "claims", ["risk_tier"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_claims_risk_tier"), table_name="claims")
    op.drop_index(op.f("ix_claims_operational_path"), table_name="claims")
    op.drop_column("claims", "risk_history")
    op.drop_column("claims", "risk_assessment")
    op.drop_column("claims", "legal_dispute")
    op.drop_column("claims", "involved_vehicles_count")
    op.drop_column("claims", "multiple_vehicles_involved")
    op.drop_column("claims", "fraud_signal_score")
    op.drop_column("claims", "risk_score")
    op.drop_column("claims", "operational_path")
    op.drop_column("claims", "risk_tier")
