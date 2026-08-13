"""Remove server-readable message metadata.

Revision ID: 20260805_20
Revises: 20260804_19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260805_20"
down_revision: str | None = "20260804_19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # This is intentionally destructive: legacy rows contain server-readable
    # plaintext and cannot be converted into authenticated MLS ciphertext.
    op.drop_table("message_receipts")
    op.drop_table("messages")
    connection = op.get_bind()
    sqlite_foreign_keys_disabled = connection.dialect.name == "sqlite"
    if sqlite_foreign_keys_disabled:
        # Alembic rebuilds `chats` for DROP COLUMN on SQLite.  Without this,
        # dropping the old parent table cascades into `chat_members` and loses
        # every conversation membership before the replacement is renamed.
        connection.execute(sa.text("PRAGMA foreign_keys=OFF"))
    try:
        with op.batch_alter_table("chats") as batch_op:
            # `op.f` marks the legacy explicit name as already formatted so the
            # metadata naming convention does not prefix it a second time.
            batch_op.drop_constraint(op.f("ck_chats_dm_has_no_name"), type_="check")
            batch_op.drop_column("name")
            batch_op.drop_column("next_message_seq")
    finally:
        if sqlite_foreign_keys_disabled:
            connection.execute(sa.text("PRAGMA foreign_keys=ON"))
    with op.batch_alter_table("media_objects") as batch_op:
        batch_op.add_column(sa.Column("chat_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_media_objects_chat_id_chats",
            "chats",
            ["chat_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index("ix_media_objects_chat_id", ["chat_id"])


def downgrade() -> None:
    raise RuntimeError(
        "Opaque-only migration cannot restore discarded plaintext messages"
    )
