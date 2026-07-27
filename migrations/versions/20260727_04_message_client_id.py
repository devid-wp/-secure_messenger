"""Add client-generated UUIDs for idempotent message delivery.

Revision ID: 20260727_04
Revises: 20260727_03
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260727_04"
down_revision: str | None = "20260727_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("client_id", sa.String(length=36), nullable=True),
    )
    with op.batch_alter_table("messages") as batch_op:
        batch_op.create_unique_constraint(
            op.f("uq_messages_sender_client_id"),
            ["sender_user_id", "client_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_constraint(
            op.f("uq_messages_sender_client_id"),
            type_="unique",
        )
    op.drop_column("messages", "client_id")
