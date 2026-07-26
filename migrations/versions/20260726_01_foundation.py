"""Create the SQLAlchemy foundation and migrate the stage-0 SQLite schema.

Revision ID: 20260726_01
Revises:
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260726_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_definitions(suffix: str = "") -> dict[str, sa.Table]:
    metadata = sa.MetaData()
    users_name = f"users{suffix}"
    chats_name = f"chats{suffix}"
    members_name = f"chat_members{suffix}"
    messages_name = f"messages{suffix}"

    users = sa.Table(
        users_name,
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("login", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.LargeBinary(), nullable=False),
        sa.Column("password_salt", sa.LargeBinary(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "is_placeholder",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "length(trim(login)) > 0",
            name="ck_users_login_not_blank",
        ),
        sa.UniqueConstraint("login", name="uq_users_login"),
        sa.CheckConstraint(
            "NOT is_placeholder OR NOT is_active",
            name="ck_users_placeholder_inactive",
        ),
    )
    chats = sa.Table(
        chats_name,
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("name", sa.String(255)),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey(
                f"{users_name}.id",
                name="fk_chats_created_by_user_id_users",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "type IN ('dm', 'group')",
            name="ck_chats_type",
        ),
        sa.CheckConstraint(
            "(type = 'dm' AND name IS NULL) OR type = 'group'",
            name="ck_chats_dm_has_no_name",
        ),
    )
    members = sa.Table(
        members_name,
        metadata,
        sa.Column(
            "chat_id",
            sa.Integer(),
            sa.ForeignKey(
                f"{chats_name}.id",
                name="fk_chat_members_chat_id_chats",
                ondelete="CASCADE",
            ),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey(
                f"{users_name}.id",
                name="fk_chat_members_user_id_users",
                ondelete="RESTRICT",
            ),
            primary_key=True,
        ),
        sa.Column(
            "role",
            sa.String(16),
            nullable=False,
            server_default="member",
        ),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'member')",
            name="ck_chat_members_role",
        ),
    )
    messages = sa.Table(
        messages_name,
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "chat_id",
            sa.Integer(),
            sa.ForeignKey(
                f"{chats_name}.id",
                name="fk_messages_chat_id_chats",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "sender_user_id",
            sa.Integer(),
            sa.ForeignKey(
                f"{users_name}.id",
                name="fk_messages_sender_user_id_users",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "length(content) BETWEEN 1 AND 16384",
            name="ck_messages_content_length",
        ),
    )
    return {
        "users": users,
        "chats": chats,
        "chat_members": members,
        "messages": messages,
    }


def _create_clean_schema() -> None:
    tables = _table_definitions()
    bind = op.get_bind()
    tables["users"].create(bind)
    tables["chats"].create(bind)
    tables["chat_members"].create(bind)
    tables["messages"].create(bind)
    op.create_index("ix_chat_members_user_id", "chat_members", ["user_id"])
    op.create_index(
        "ix_messages_chat_timestamp",
        "messages",
        ["chat_id", "timestamp", "id"],
    )


def _row_count(table_name: str) -> int:
    return int(
        op.get_bind().execute(
            sa.text(f'SELECT COUNT(*) FROM "{table_name}"')
        ).scalar_one()
    )


def _migrate_stage_zero_schema() -> None:
    bind = op.get_bind()
    tables = _table_definitions("_foundation")
    for table in tables.values():
        table.create(bind)

    bind.execute(
        sa.text(
            """
            INSERT INTO users_foundation
                (id, login, password_hash, password_salt,
                 is_active, is_placeholder, created_at)
            SELECT id, login, hash, salt, true, false, created_at
            FROM users
            """
        )
    )

    referenced_logins = {
        row[0]
        for row in bind.execute(
            sa.text(
                """
                SELECT login FROM chat_members
                UNION
                SELECT created_by FROM chats
                UNION
                SELECT sender FROM messages
                """
            )
        )
    }
    existing_logins = {
        row[0]
        for row in bind.execute(sa.text("SELECT login FROM users_foundation"))
    }
    placeholders = sorted(referenced_logins - existing_logins)
    if placeholders:
        bind.execute(
            tables["users"].insert(),
            [
                {
                    "login": login,
                    "password_hash": b"",
                    "password_salt": b"",
                    "is_active": False,
                    "is_placeholder": True,
                }
                for login in placeholders
            ],
        )

    bind.execute(
        sa.text(
            """
            INSERT INTO chats_foundation
                (id, type, name, created_by_user_id, created_at)
            SELECT c.id, c.type, c.name, u.id, c.created_at
            FROM chats c
            JOIN users_foundation u ON u.login = c.created_by
            """
        )
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO chat_members_foundation
                (chat_id, user_id, role, joined_at)
            SELECT cm.chat_id,
                   u.id,
                   CASE
                       WHEN c.created_by = cm.login THEN 'owner'
                       ELSE 'member'
                   END,
                   cm.joined_at
            FROM chat_members cm
            JOIN users_foundation u ON u.login = cm.login
            JOIN chats c ON c.id = cm.chat_id
            """
        )
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO messages_foundation
                (id, chat_id, sender_user_id, content, timestamp)
            SELECT m.id, m.chat_id, u.id, m.content, m.timestamp
            FROM messages m
            JOIN users_foundation u ON u.login = m.sender
            """
        )
    )

    for table_name in ("chats", "chat_members", "messages"):
        source_count = _row_count(table_name)
        target_count = _row_count(f"{table_name}_foundation")
        if source_count != target_count:
            raise RuntimeError(
                f"Migration verification failed for {table_name}: "
                f"{source_count} != {target_count}"
            )

    op.drop_table("messages")
    op.drop_table("chat_members")
    op.drop_table("chats")
    op.drop_table("users")
    op.rename_table("users_foundation", "users")
    op.rename_table("chats_foundation", "chats")
    op.rename_table("chat_members_foundation", "chat_members")
    op.rename_table("messages_foundation", "messages")
    op.create_index("ix_chat_members_user_id", "chat_members", ["user_id"])
    op.create_index(
        "ix_messages_chat_timestamp",
        "messages",
        ["chat_id", "timestamp", "id"],
    )

    if bind.dialect.name == "postgresql":
        for table_name in ("users", "chats", "messages"):
            bind.execute(
                sa.text(
                    f"""
                    SELECT setval(
                        pg_get_serial_sequence('{table_name}', 'id'),
                        COALESCE((SELECT MAX(id) FROM {table_name}), 1),
                        (SELECT COUNT(*) > 0 FROM {table_name})
                    )
                    """
                )
            )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table_names = set(inspector.get_table_names())
    if "users" not in table_names:
        _create_clean_schema()
        return

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    member_columns = {
        column["name"] for column in inspector.get_columns("chat_members")
    }
    if "password_hash" in user_columns and "user_id" in member_columns:
        return
    required_tables = {"users", "chats", "chat_members", "messages"}
    if not required_tables.issubset(table_names):
        raise RuntimeError(
            "Unsupported partial schema; restore the backup before migration"
        )
    _migrate_stage_zero_schema()


def downgrade() -> None:
    raise RuntimeError("The foundation migration is intentionally forward-only")
