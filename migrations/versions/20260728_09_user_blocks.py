"""Add user blocking.

Revision ID: 20260728_09
Revises: 20260728_08
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260728_09"
down_revision: str | None = "20260728_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_blocks",
        sa.Column("blocker_id", sa.Integer(), nullable=False),
        sa.Column("blocked_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "blocker_id <> blocked_id",
            name=op.f("ck_user_blocks_different_users"),
        ),
        sa.ForeignKeyConstraint(
            ["blocked_id"],
            ["users.id"],
            name=op.f("fk_user_blocks_blocked_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["blocker_id"],
            ["users.id"],
            name=op.f("fk_user_blocks_blocker_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "blocker_id",
            "blocked_id",
            name=op.f("pk_user_blocks"),
        ),
    )
    op.create_index(
        op.f("ix_user_blocks_blocked_id"),
        "user_blocks",
        ["blocked_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_blocks_blocked_id"), table_name="user_blocks")
    op.drop_table("user_blocks")
