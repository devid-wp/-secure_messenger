"""Add persistent refresh sessions.

Revision ID: 20260801_18
Revises: 20260731_17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260801_18"
down_revision: str | None = "20260731_17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "refresh_sessions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(36), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False),
        sa.Column("device_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE", name=op.f("fk_refresh_sessions_device_id_devices")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_refresh_sessions_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_sessions")),
        sa.UniqueConstraint("refresh_token_hash", name=op.f("uq_refresh_sessions_refresh_token_hash")),
    )
    op.create_index(op.f("ix_refresh_sessions_device_id"), "refresh_sessions", ["device_id"])
    op.create_index(op.f("ix_refresh_sessions_refresh_token_hash"), "refresh_sessions", ["refresh_token_hash"], unique=True)
    op.create_index(op.f("ix_refresh_sessions_user_id"), "refresh_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_refresh_sessions_user_id"), table_name="refresh_sessions")
    op.drop_index(op.f("ix_refresh_sessions_refresh_token_hash"), table_name="refresh_sessions")
    op.drop_index(op.f("ix_refresh_sessions_device_id"), table_name="refresh_sessions")
    op.drop_table("refresh_sessions")
