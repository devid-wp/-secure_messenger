"""Add a unique stable key for direct-message participant pairs.

Revision ID: 20260727_03
Revises: 20260726_02
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260727_03"
down_revision: str | None = "20260726_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chats", sa.Column("direct_key", sa.String(length=64)))
    connection = op.get_bind()
    direct_chat_ids = connection.execute(
        sa.text("SELECT id FROM chats WHERE type = 'dm' ORDER BY id")
    ).scalars()
    seen_keys: set[str] = set()
    for chat_id in direct_chat_ids:
        member_ids = list(
            connection.execute(
                sa.text(
                    """
                    SELECT user_id
                    FROM chat_members
                    WHERE chat_id = :chat_id
                    ORDER BY user_id
                    """
                ),
                {"chat_id": chat_id},
            ).scalars()
        )
        if len(member_ids) != 2:
            continue
        direct_key = f"{member_ids[0]}:{member_ids[1]}"
        if direct_key in seen_keys:
            continue
        seen_keys.add(direct_key)
        connection.execute(
            sa.text("UPDATE chats SET direct_key = :key WHERE id = :chat_id"),
            {"key": direct_key, "chat_id": chat_id},
        )
    op.create_index(
        op.f("ix_chats_direct_key"),
        "chats",
        ["direct_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_chats_direct_key"), table_name="chats")
    op.drop_column("chats", "direct_key")
