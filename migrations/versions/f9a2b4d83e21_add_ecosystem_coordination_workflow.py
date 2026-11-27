"""add_ecosystem_coordination_workflow

Revision ID: f9a2b4d83e21
Revises: e8f1a3c92d14
Create Date: 2026-11-27 17:15:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f9a2b4d83e21"
down_revision: Union[str, None] = "e8f1a3c92d14"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("providers", sa.Column("licence_expiry_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("providers", sa.Column("service_zones", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("providers", sa.Column("skills", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("providers", sa.Column("contract_tier", sa.String(length=32), nullable=False, server_default="preferred_network"))
    op.add_column("providers", sa.Column("sla_target_hours", sa.Integer(), nullable=False, server_default="24"))
    op.add_column("providers", sa.Column("sla_status", sa.String(length=24), nullable=False, server_default="within_sla"))
    op.add_column("providers", sa.Column("avg_turnaround_hours", sa.Integer(), nullable=False, server_default="18"))
    op.add_column("providers", sa.Column("parts_stock_status", sa.String(length=24), nullable=False, server_default="in_stock"))
    op.add_column("providers", sa.Column("parts_lead_time_days", sa.Integer(), nullable=False, server_default="2"))
    op.add_column("providers", sa.Column("pickup_drop_available", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("providers", sa.Column("towing_capable", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.add_column("survey_assignments", sa.Column("inspection_location", sa.String(length=240), nullable=False, server_default=""))
    op.add_column("survey_assignments", sa.Column("reschedule_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("survey_assignments", sa.Column("reschedule_reason", sa.String(length=240), nullable=True))
    op.add_column("survey_assignments", sa.Column("followup_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("survey_assignments", sa.Column("last_followup_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "ecosystem_coordinations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("claim_id", sa.String(length=36), sa.ForeignKey("claims.id"), nullable=False, unique=True),
        sa.Column("surveyor_id", sa.String(length=36), nullable=True),
        sa.Column("surveyor_license_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("surveyor_license_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("surveyor_selection_explanation", sa.Text(), nullable=False, server_default=""),
        sa.Column("surveyor_score_breakdown", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("garage_id", sa.String(length=36), nullable=True),
        sa.Column("customer_preferred_garage_id", sa.String(length=36), nullable=True),
        sa.Column("customer_preference_honoured", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("override_applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("override_authorized", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("override_authorized_by", sa.String(length=120), nullable=True),
        sa.Column("override_reason_code", sa.String(length=80), nullable=True),
        sa.Column("override_justification", sa.Text(), nullable=False, server_default=""),
        sa.Column("garage_selection_explanation", sa.Text(), nullable=False, server_default=""),
        sa.Column("garage_score_breakdown", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("inspection_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("inspection_scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inspection_reschedule_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inspection_reschedule_reason", sa.String(length=240), nullable=True),
        sa.Column("towing_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("towing_status", sa.String(length=32), nullable=False, server_default="not_required"),
        sa.Column("towing_provider_id", sa.String(length=36), nullable=True),
        sa.Column("towing_ev_flatbed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pickup_delivery_status", sa.String(length=32), nullable=False, server_default="not_scheduled"),
        sa.Column("pickup_scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pickup_driver_note", sa.String(length=240), nullable=False, server_default=""),
        sa.Column("parts_status", sa.String(length=32), nullable=False, server_default="pending_check"),
        sa.Column("parts_availability", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("repair_status", sa.String(length=32), nullable=False, server_default="not_started"),
        sa.Column("repair_milestones", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("repair_completion_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("repair_confirmed_by", sa.String(length=120), nullable=True),
        sa.Column("repair_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("surveyor_followup_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_surveyor_followup_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("surveyor_followup_status", sa.String(length=32), nullable=False, server_default="none"),
        sa.Column("customer_notifications", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("contractual_compliance", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("coordination_explanation", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ecosystem_coordinations")
    op.drop_column("survey_assignments", "last_followup_at")
    op.drop_column("survey_assignments", "followup_count")
    op.drop_column("survey_assignments", "reschedule_reason")
    op.drop_column("survey_assignments", "reschedule_count")
    op.drop_column("survey_assignments", "inspection_location")
    op.drop_column("providers", "towing_capable")
    op.drop_column("providers", "pickup_drop_available")
    op.drop_column("providers", "parts_lead_time_days")
    op.drop_column("providers", "parts_stock_status")
    op.drop_column("providers", "avg_turnaround_hours")
    op.drop_column("providers", "sla_status")
    op.drop_column("providers", "sla_target_hours")
    op.drop_column("providers", "contract_tier")
    op.drop_column("providers", "skills")
    op.drop_column("providers", "service_zones")
    op.drop_column("providers", "licence_expiry_at")
