"""Add opaque MLS delivery envelopes.

Revision ID: 20260804_19
Revises: 20260801_18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260804_19"
down_revision: str | None = "20260801_18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mls_envelopes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("sender_device_id", sa.String(36), nullable=False),
        sa.Column("recipient_device_id", sa.String(36)),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(16), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("message_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("epoch >= 0", name=op.f("ck_mls_envelopes_epoch")),
        sa.CheckConstraint("content_type IN ('application', 'commit', 'proposal', 'welcome')", name=op.f("ck_mls_envelopes_content_type")),
        sa.CheckConstraint("length(payload) BETWEEN 1 AND 1048576", name=op.f("ck_mls_envelopes_payload_size")),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE", name=op.f("fk_mls_envelopes_chat_id_chats")),
        sa.ForeignKeyConstraint(["sender_device_id"], ["devices.id"], ondelete="RESTRICT", name=op.f("fk_mls_envelopes_sender_device_id_devices")),
        sa.ForeignKeyConstraint(["recipient_device_id"], ["devices.id"], ondelete="CASCADE", name=op.f("fk_mls_envelopes_recipient_device_id_devices")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mls_envelopes")),
        sa.UniqueConstraint("sender_device_id", "message_hash", name="uq_mls_envelope_sender_hash"),
    )
    op.create_index("ix_mls_envelopes_chat_id_id", "mls_envelopes", ["chat_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_mls_envelopes_chat_id_id", table_name="mls_envelopes")
    op.drop_table("mls_envelopes")
