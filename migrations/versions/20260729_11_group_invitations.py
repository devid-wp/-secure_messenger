"""Add expiring group invitations.

Revision ID: 20260729_11
Revises: 20260729_10
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260729_11"
down_revision: str | None = "20260729_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_invitations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("inviter_user_id", sa.Integer(), nullable=False),
        sa.Column("invitee_user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'revoked')", name=op.f("ck_chat_invitations_status")),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE", name=op.f("fk_chat_invitations_chat_id_chats")),
        sa.ForeignKeyConstraint(["invitee_user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_chat_invitations_invitee_user_id_users")),
        sa.ForeignKeyConstraint(["inviter_user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_chat_invitations_inviter_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_invitations")),
    )
    op.create_index(op.f("ix_chat_invitations_chat_id"), "chat_invitations", ["chat_id"])
    op.create_index(op.f("ix_chat_invitations_invitee_user_id"), "chat_invitations", ["invitee_user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_invitations_invitee_user_id"), table_name="chat_invitations")
    op.drop_index(op.f("ix_chat_invitations_chat_id"), table_name="chat_invitations")
    op.drop_table("chat_invitations")
