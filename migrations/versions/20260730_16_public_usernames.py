"""Add changeable public usernames while preserving stable user IDs.

Revision ID: 20260730_16
Revises: 20260730_15
"""

from collections.abc import Sequence
import re

import sqlalchemy as sa
from alembic import op


revision: str = "20260730_16"
down_revision: str | None = "20260730_15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _candidate(login: str, user_id: int, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9_]+", "_", login.strip().lower()).strip("_")
    if not base or not base[0].isalnum():
        base = f"user_{user_id}"
    if len(base) < 3:
        base = f"user_{user_id}"
    base = base[:32]
    candidate = base
    suffix = 1
    while candidate in used:
        ending = f"_{suffix}"
        candidate = f"{base[:32 - len(ending)]}{ending}"
        suffix += 1
    used.add(candidate)
    return candidate


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("username", sa.String(32), nullable=True))

    connection = op.get_bind()
    users = connection.execute(
        sa.text("SELECT id, login FROM users ORDER BY id")
    ).fetchall()
    used: set[str] = set()
    for user_id, login in users:
        connection.execute(
            sa.text("UPDATE users SET username = :username WHERE id = :id"),
            {"username": _candidate(login, user_id, used), "id": user_id},
        )

    if connection.dialect.name == "sqlite":
        # Rebuilding this populated parent table would temporarily violate the
        # foreign keys from chats, messages, devices, and memberships.
        op.create_index("uq_users_username", "users", ["username"], unique=True)
    else:
        op.alter_column(
            "users",
            "username",
            existing_type=sa.String(32),
            nullable=False,
        )
        op.create_unique_constraint("uq_users_username", "users", ["username"])
        op.create_check_constraint(
            "ck_users_username_format",
            "users",
            "length(username) BETWEEN 3 AND 32",
        )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        op.drop_index("uq_users_username", table_name="users")
        with op.batch_alter_table("users") as batch:
            batch.drop_column("username")
    else:
        op.drop_constraint("ck_users_username_format", "users", type_="check")
        op.drop_constraint("uq_users_username", "users", type_="unique")
        op.drop_column("users", "username")
