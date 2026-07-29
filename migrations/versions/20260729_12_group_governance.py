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
    with op.batch_alter_table("chats") as batch_op:
        batch_op.add_column(
            sa.Column(
                "history_visibility",
                sa.String(length=16),
                server_default="since_join",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_chats_history_visibility",
            "history_visibility IN ('all', 'since_join')",
        )

    with op.batch_alter_table("chat_members") as batch_op:
        batch_op.add_column(
            sa.Column(
                "history_from_seq",
                sa.Integer(),
                server_default="1",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_chat_members_history_from_seq",
            "history_from_seq > 0",
        )

    with op.batch_alter_table("messages") as batch_op:
        batch_op.add_column(
            sa.Column(
                "kind",
                sa.String(length=16),
                server_default="user",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_messages_kind",
            "kind IN ('user', 'system')",
        )


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_constraint("ck_messages_kind", type_="check")
        batch_op.drop_column("kind")

    with op.batch_alter_table("chat_members") as batch_op:
        batch_op.drop_constraint(
            "ck_chat_members_history_from_seq",
            type_="check",
        )
        batch_op.drop_column("history_from_seq")

    with op.batch_alter_table("chats") as batch_op:
        batch_op.drop_constraint("ck_chats_history_visibility", type_="check")
        batch_op.drop_column("history_visibility")
