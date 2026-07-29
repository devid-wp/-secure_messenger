"""Add group avatar URL.

Revision ID: 20260729_10
Revises: 20260728_09
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260729_10"
down_revision: str | None = "20260728_09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chats", sa.Column("avatar_url", sa.String(length=2048)))


def downgrade() -> None:
    op.drop_column("chats", "avatar_url")
