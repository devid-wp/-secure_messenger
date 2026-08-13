"""Drop unused per-encryption metadata from media_objects.

Revision ID: 20260807_22
Revises: 20260807_21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260807_22"
down_revision: str | None = "20260807_21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Attachments arrive already encrypted by the client; the server stores
    # opaque ciphertext and never reads the per-object cipher or nonce. These
    # columns are leftovers from the pre-MLS era and are no longer referenced
    # by the models or the API.
    with op.batch_alter_table("media_objects") as batch_op:
        batch_op.drop_column("cipher")
        batch_op.drop_column("nonce")


def downgrade() -> None:
    with op.batch_alter_table("media_objects") as batch_op:
        batch_op.add_column(sa.Column("nonce", sa.String(64)))
        batch_op.add_column(sa.Column("cipher", sa.String(32)))
