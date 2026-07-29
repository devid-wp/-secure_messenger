"""Add public device identities and one-time MLS KeyPackages.

Revision ID: 20260729_13
Revises: 20260729_12
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260729_13"
down_revision: str | None = "20260729_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("identity_key", sa.LargeBinary()))
    op.add_column(
        "devices",
        sa.Column("identity_fingerprint", sa.String(length=64)),
    )
    op.add_column(
        "devices",
        sa.Column("identity_published_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        op.f("ix_devices_identity_fingerprint"),
        "devices",
        ["identity_fingerprint"],
        unique=True,
    )
    op.create_table(
        "mls_key_packages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("key_package", sa.LargeBinary(), nullable=False),
        sa.Column("cipher_suite", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_by_device_id", sa.String(length=36)),
        sa.CheckConstraint(
            "length(key_package) BETWEEN 64 AND 65536",
            name=op.f("ck_mls_key_packages_size"),
        ),
        sa.ForeignKeyConstraint(
            ["claimed_by_device_id"],
            ["devices.id"],
            ondelete="SET NULL",
            name=op.f(
                "fk_mls_key_packages_claimed_by_device_id_devices"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            ondelete="CASCADE",
            name=op.f("fk_mls_key_packages_device_id_devices"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mls_key_packages")),
    )
    op.create_index(
        op.f("ix_mls_key_packages_device_id"),
        "mls_key_packages",
        ["device_id"],
    )
    op.create_index(
        op.f("ix_mls_key_packages_expires_at"),
        "mls_key_packages",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_mls_key_packages_expires_at"),
        table_name="mls_key_packages",
    )
    op.drop_index(
        op.f("ix_mls_key_packages_device_id"),
        table_name="mls_key_packages",
    )
    op.drop_table("mls_key_packages")
    op.drop_index(
        op.f("ix_devices_identity_fingerprint"),
        table_name="devices",
    )
    op.drop_column("devices", "identity_published_at")
    op.drop_column("devices", "identity_fingerprint")
    op.drop_column("devices", "identity_key")
