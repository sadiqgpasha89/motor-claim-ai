"""add_customer_experience_intelligence

Revision ID: a1c3e5f70912
Revises: f9a2b4d83e21
Create Date: 2026-11-27 17:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1c3e5f70912"
down_revision: Union[str, None] = "f9a2b4d83e21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("preferred_channel", sa.String(length=24), nullable=False, server_default="whatsapp"))
    op.add_column("customers", sa.Column("consent_sms", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("customers", sa.Column("consent_email", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("customers", sa.Column("proactive_updates_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("customers", sa.Column("whatsapp_consent_updated_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("claims", sa.Column("preferred_channel", sa.String(length=24), nullable=False, server_default="whatsapp"))
    op.add_column("claims", sa.Column("whatsapp_consent", sa.Boolean(), nullable=False, server_default=sa.true()))

    op.add_column("communications", sa.Column("trigger_event", sa.String(length=64), nullable=False, server_default="manual_update"))
    op.add_column("communications", sa.Column("claim_state_snapshot", sa.String(length=48), nullable=False, server_default=""))
    op.add_column("communications", sa.Column("consent_verified", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("communications", sa.Column("whatsapp_message_id", sa.String(length=80), nullable=True))
    op.add_column("communications", sa.Column("context_summary", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("communications", "context_summary")
    op.drop_column("communications", "whatsapp_message_id")
    op.drop_column("communications", "consent_verified")
    op.drop_column("communications", "claim_state_snapshot")
    op.drop_column("communications", "trigger_event")

    op.drop_column("claims", "whatsapp_consent")
    op.drop_column("claims", "preferred_channel")

    op.drop_column("customers", "whatsapp_consent_updated_at")
    op.drop_column("customers", "proactive_updates_enabled")
    op.drop_column("customers", "consent_email")
    op.drop_column("customers", "consent_sms")
    op.drop_column("customers", "preferred_channel")
