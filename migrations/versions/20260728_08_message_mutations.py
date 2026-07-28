"""Add message editing and soft deletion.

Revision ID: 20260728_08
Revises: 20260728_07
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260728_08"
down_revision: str | None = "20260728_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.add_column(sa.Column("edited_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True)))
        batch_op.drop_constraint(
            op.f("ck_messages_content_length"),
            type_="check",
        )
        batch_op.create_check_constraint(
            op.f("ck_messages_content_length"),
            "(deleted_at IS NOT NULL AND content = '') OR "
            "(deleted_at IS NULL AND length(content) BETWEEN 1 AND 16384)",
        )


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_messages_content_length"),
            type_="check",
        )
        batch_op.create_check_constraint(
            op.f("ck_messages_content_length"),
            "length(content) BETWEEN 1 AND 16384",
        )
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("edited_at")
