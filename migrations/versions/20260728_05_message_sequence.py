"""Add a monotonic server sequence inside every chat.

Revision ID: 20260728_05
Revises: 20260727_04
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260728_05"
down_revision: str | None = "20260727_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chats",
        sa.Column(
            "next_message_seq",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
    )
    op.add_column(
        "messages",
        sa.Column("server_seq", sa.Integer(), nullable=True),
    )
    connection = op.get_bind()
    chat_ids = connection.execute(sa.text("SELECT id FROM chats ORDER BY id")).scalars()
    for chat_id in chat_ids:
        message_ids = list(
            connection.execute(
                sa.text(
                    "SELECT id FROM messages WHERE chat_id = :chat_id ORDER BY id"
                ),
                {"chat_id": chat_id},
            ).scalars()
        )
        for server_seq, message_id in enumerate(message_ids, start=1):
            connection.execute(
                sa.text(
                    "UPDATE messages SET server_seq = :seq WHERE id = :message_id"
                ),
                {"seq": server_seq, "message_id": message_id},
            )
        connection.execute(
            sa.text(
                """
                UPDATE chats
                SET next_message_seq = :next_seq
                WHERE id = :chat_id
                """
            ),
            {"next_seq": len(message_ids) + 1, "chat_id": chat_id},
        )
    with op.batch_alter_table("messages") as batch_op:
        batch_op.alter_column(
            "server_seq",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_unique_constraint(
            op.f("uq_messages_chat_server_seq"),
            ["chat_id", "server_seq"],
        )


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_constraint(
            op.f("uq_messages_chat_server_seq"),
            type_="unique",
        )
        batch_op.drop_column("server_seq")
    op.drop_column("chats", "next_message_seq")
