"""Add typed messages, sticker packs, and encrypted media metadata.

Revision ID: 20260730_15
Revises: 20260729_14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260730_15"
down_revision: str | None = "20260729_14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_objects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "owner_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("storage_backend", sa.String(16), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("is_encrypted", sa.Boolean(), nullable=False),
        sa.Column("cipher", sa.String(32)),
        sa.Column("nonce", sa.String(64)),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "purpose IN ('attachment', 'sticker')",
            name="ck_media_objects_purpose",
        ),
        sa.CheckConstraint(
            "size_bytes BETWEEN 1 AND 52428800",
            name="ck_media_objects_size",
        ),
        sa.CheckConstraint(
            "(purpose = 'attachment' AND is_encrypted) OR "
            "(purpose = 'sticker' AND NOT is_encrypted)",
            name="ck_media_objects_encryption_policy",
        ),
        sa.CheckConstraint(
            "(width IS NULL AND height IS NULL) OR "
            "(width BETWEEN 1 AND 4096 AND height BETWEEN 1 AND 4096)",
            name="ck_media_objects_dimensions",
        ),
        sa.UniqueConstraint("object_key", name="uq_media_objects_object_key"),
    )
    op.create_index(
        "ix_media_objects_owner_user_id",
        "media_objects",
        ["owner_user_id"],
    )
    op.create_table(
        "sticker_packs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "owner_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(64), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column(
            "visibility",
            sa.String(16),
            nullable=False,
            server_default="private",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "visibility IN ('public', 'private')",
            name="ck_sticker_packs_visibility",
        ),
        sa.CheckConstraint(
            "length(trim(title)) BETWEEN 1 AND 64",
            name="ck_sticker_packs_title_length",
        ),
        sa.UniqueConstraint(
            "owner_user_id",
            "slug",
            name="uq_sticker_packs_owner_slug",
        ),
    )
    op.create_index(
        "ix_sticker_packs_owner_user_id",
        "sticker_packs",
        ["owner_user_id"],
    )
    op.create_table(
        "stickers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "pack_id",
            sa.String(36),
            sa.ForeignKey("sticker_packs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "media_object_id",
            sa.String(36),
            sa.ForeignKey("media_objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("emoji", sa.String(32)),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("position >= 0", name="ck_stickers_position"),
        sa.UniqueConstraint(
            "pack_id",
            "position",
            name="uq_stickers_pack_position",
        ),
        sa.UniqueConstraint(
            "media_object_id",
            name="uq_stickers_media_object",
        ),
    )
    op.create_index("ix_stickers_pack_id", "stickers", ["pack_id"])
    op.create_table(
        "sticker_pack_subscriptions",
        sa.Column(
            "pack_id",
            sa.String(36),
            sa.ForeignKey("sticker_packs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_sticker_pack_subscriptions_user_id",
        "sticker_pack_subscriptions",
        ["user_id"],
    )

    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_constraint("ck_messages_kind", type_="check")
        batch_op.add_column(sa.Column("attachment_id", sa.String(36)))
        batch_op.add_column(sa.Column("sticker_id", sa.String(36)))
        batch_op.add_column(sa.Column("key_envelope", sa.Text()))
        batch_op.create_foreign_key(
            "fk_messages_attachment_id_media_objects",
            "media_objects",
            ["attachment_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_messages_sticker_id_stickers",
            "stickers",
            ["sticker_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    op.execute("UPDATE messages SET kind = 'text' WHERE kind = 'user'")

    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_constraint("content_length", type_="check")
        batch_op.create_check_constraint(
            "kind",
            "kind IN ('text', 'sticker', 'image', 'file', 'system')",
        )
        batch_op.create_check_constraint(
            "content_length",
            "(deleted_at IS NOT NULL AND content = '') OR "
            "(deleted_at IS NULL AND kind IN ('text', 'system') "
            "AND length(content) BETWEEN 1 AND 16384) OR "
            "(deleted_at IS NULL AND kind = 'sticker' AND content = '') OR "
            "(deleted_at IS NULL AND kind IN ('image', 'file') "
            "AND length(content) BETWEEN 0 AND 4096)",
        )
        batch_op.create_check_constraint(
            "typed_payload",
            "(kind = 'sticker' AND sticker_id IS NOT NULL "
            "AND attachment_id IS NULL) OR "
            "(kind IN ('image', 'file') AND attachment_id IS NOT NULL "
            "AND sticker_id IS NULL) OR "
            "(kind IN ('text', 'system') AND attachment_id IS NULL "
            "AND sticker_id IS NULL)",
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM messages WHERE kind IN ('sticker', 'image', 'file')"
    )
    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_constraint("typed_payload", type_="check")
        batch_op.drop_constraint("content_length", type_="check")
        batch_op.drop_constraint("kind", type_="check")

    op.execute("UPDATE messages SET kind = 'user' WHERE kind = 'text'")

    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_constraint(
            "fk_messages_sticker_id_stickers",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_messages_attachment_id_media_objects",
            type_="foreignkey",
        )
        batch_op.drop_column("key_envelope")
        batch_op.drop_column("sticker_id")
        batch_op.drop_column("attachment_id")
        batch_op.create_check_constraint(
            "ck_messages_kind",
            "kind IN ('user', 'system')",
        )
        batch_op.create_check_constraint(
            "content_length",
            "(deleted_at IS NOT NULL AND content = '') OR "
            "(deleted_at IS NULL AND length(content) BETWEEN 1 AND 16384)",
        )
    op.drop_table("sticker_pack_subscriptions")
    op.drop_table("stickers")
    op.drop_table("sticker_packs")
    op.drop_table("media_objects")
