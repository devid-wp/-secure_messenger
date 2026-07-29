"""Add user profile customization fields.

Revision ID: 20260729_14
Revises: 20260729_13
"""

from alembic import op
import sqlalchemy as sa


revision = "20260729_14"
down_revision = "20260729_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("display_name", sa.String(64)))
        batch_op.add_column(sa.Column("bio", sa.String(160)))
        batch_op.add_column(sa.Column("avatar_url", sa.String(2048)))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("avatar_url")
        batch_op.drop_column("bio")
        batch_op.drop_column("display_name")
