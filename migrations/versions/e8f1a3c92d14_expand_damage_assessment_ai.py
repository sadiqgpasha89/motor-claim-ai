"""expand_damage_assessment_ai

Revision ID: e8f1a3c92d14
Revises: d7e2f4a81b10
Create Date: 2026-11-27 17:05:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8f1a3c92d14"
down_revision: Union[str, None] = "d7e2f4a81b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("claims", sa.Column("damage_report", sa.JSON(), nullable=True))
    op.add_column("damage_assessments", sa.Column("damage_location", sa.String(length=64), nullable=False, server_default="front_center"))
    op.add_column("damage_assessments", sa.Column("damage_severity", sa.String(length=24), nullable=False, server_default="moderate"))
    op.add_column("damage_assessments", sa.Column("repairability", sa.String(length=24), nullable=False, server_default="repair"))
    op.add_column("damage_assessments", sa.Column("visible_damage", sa.Text(), nullable=False, server_default=""))
    op.add_column("damage_assessments", sa.Column("possible_hidden_damage", sa.Text(), nullable=False, server_default=""))
    op.add_column("damage_assessments", sa.Column("image_quality", sa.String(length=24), nullable=False, server_default="good"))
    op.add_column("damage_assessments", sa.Column("confidence_factors", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("damage_assessments", sa.Column("evidence_refs", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("damage_assessments", sa.Column("estimated_parts_inr", sa.Numeric(precision=14, scale=2), nullable=False, server_default="0.00"))
    op.add_column("damage_assessments", sa.Column("estimated_labour_inr", sa.Numeric(precision=14, scale=2), nullable=False, server_default="0.00"))
    op.add_column("damage_assessments", sa.Column("estimated_paint_inr", sa.Numeric(precision=14, scale=2), nullable=False, server_default="0.00"))


def downgrade() -> None:
    op.drop_column("damage_assessments", "estimated_paint_inr")
    op.drop_column("damage_assessments", "estimated_labour_inr")
    op.drop_column("damage_assessments", "estimated_parts_inr")
    op.drop_column("damage_assessments", "evidence_refs")
    op.drop_column("damage_assessments", "confidence_factors")
    op.drop_column("damage_assessments", "image_quality")
    op.drop_column("damage_assessments", "possible_hidden_damage")
    op.drop_column("damage_assessments", "visible_damage")
    op.drop_column("damage_assessments", "repairability")
    op.drop_column("damage_assessments", "damage_severity")
    op.drop_column("damage_assessments", "damage_location")
    op.drop_column("claims", "damage_report")
