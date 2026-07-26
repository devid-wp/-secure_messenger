"""Add persistent device records for revocable sessions.

Revision ID: 20260726_02
Revises: 20260726_01
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260726_02"
down_revision: str | None = "20260726_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 128",
            name=op.f("ck_devices_name_length"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_devices_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devices")),
    )
    op.create_index(op.f("ix_devices_user_id"), "devices", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_devices_user_id"), table_name="devices")
    op.drop_table("devices")
