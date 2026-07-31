"""Add trusted multi-device lifecycle.

Revision ID: 20260731_17
Revises: 20260730_16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260731_17"
down_revision: str | None = "20260730_16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("status", sa.String(16), nullable=False, server_default="active"))
    op.add_column("devices", sa.Column("approved_by_device_id", sa.String(36)))
    op.add_column("devices", sa.Column("approved_at", sa.DateTime(timezone=True)))
    op.add_column("devices", sa.Column("pairing_code_hash", sa.String(64)))
    op.add_column("devices", sa.Column("pairing_expires_at", sa.DateTime(timezone=True)))
    op.add_column("devices", sa.Column("history_policy", sa.String(24), nullable=False, server_default="new_only"))
    if op.get_bind().dialect.name != "sqlite":
        op.create_foreign_key(
            op.f("fk_devices_approved_by_device_id_devices"),
            "devices", "devices", ["approved_by_device_id"], ["id"], ondelete="SET NULL",
        )
        op.create_check_constraint(
            op.f("ck_devices_status"), "devices", "status IN ('pending', 'active', 'revoked')",
        )
        op.create_check_constraint(
            op.f("ck_devices_history_policy"), "devices", "history_policy IN ('new_only', 'transfer_requested')",
        )
    op.create_table(
        "security_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("recipient_user_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("subject_user_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(36)),
        sa.Column("fingerprint", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_security_events_recipient_user_id_users")),
        sa.ForeignKeyConstraint(["subject_user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_security_events_subject_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_security_events")),
    )
    op.create_index(op.f("ix_security_events_recipient_user_id"), "security_events", ["recipient_user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_security_events_recipient_user_id"), table_name="security_events")
    op.drop_table("security_events")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(op.f("ck_devices_history_policy"), "devices", type_="check")
        op.drop_constraint(op.f("ck_devices_status"), "devices", type_="check")
        op.drop_constraint(op.f("fk_devices_approved_by_device_id_devices"), "devices", type_="foreignkey")
    for column in ("history_policy", "pairing_expires_at", "pairing_code_hash", "approved_at", "approved_by_device_id", "status"):
        op.drop_column("devices", column)
