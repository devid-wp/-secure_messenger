"""Add same-chat message replies.

Revision ID: 20260728_07
Revises: 20260728_06
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260728_07"
down_revision: str | None = "20260728_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.add_column(sa.Column("reply_to_id", sa.Integer()))
        batch_op.create_foreign_key(
            op.f("fk_messages_reply_to_id_messages"),
            "messages",
            ["reply_to_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_constraint(
            op.f("fk_messages_reply_to_id_messages"),
            type_="foreignkey",
        )
        batch_op.drop_column("reply_to_id")
