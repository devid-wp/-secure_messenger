"""Add group history policy and system message kind.

Revision ID: 20260729_12
Revises: 20260729_11
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260729_12"
down_revision: str | None = "20260729_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chats",
        sa.Column(
            "history_visibility",
            sa.String(length=16),
            sa.CheckConstraint(
                "history_visibility IN ('all', 'since_join')",
                name="ck_chats_history_visibility",
            ),
            server_default="since_join",
            nullable=False,
        )
    )
    op.add_column(
        "chat_members",
        sa.Column(
            "history_from_seq",
            sa.Integer(),
            sa.CheckConstraint(
                "history_from_seq > 0",
                name="ck_chat_members_history_from_seq",
            ),
            server_default="1",
            nullable=False,
        )
    )
    op.add_column(
        "messages",
        sa.Column(
            "kind",
            sa.String(length=16),
            sa.CheckConstraint(
                "kind IN ('user', 'system')",
                name="ck_messages_kind",
            ),
            server_default="user",
            nullable=False,
        )
    )


def downgrade() -> None:
    op.drop_column("messages", "kind")
    op.drop_column("chat_members", "history_from_seq")
    op.drop_column("chats", "history_visibility")
