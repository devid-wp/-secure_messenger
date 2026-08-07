"""Pin MLS envelope wire format version.

Revision ID: 20260807_21
Revises: 20260805_20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260807_21"
down_revision: str | None = "20260805_20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MLS_PROTOCOL_VERSION = 1


def upgrade() -> None:
    with op.batch_alter_table("mls_envelopes") as batch_op:
        batch_op.add_column(
            sa.Column(
                "protocol_version",
                sa.Integer(),
                nullable=False,
                server_default=str(MLS_PROTOCOL_VERSION),
            )
        )
        batch_op.create_check_constraint(
            "ck_mls_envelope_protocol_version",
            f"protocol_version = {MLS_PROTOCOL_VERSION}",
        )


def downgrade() -> None:
    with op.batch_alter_table("mls_envelopes") as batch_op:
        batch_op.drop_constraint("ck_mls_envelope_protocol_version", type_="check")
        batch_op.drop_column("protocol_version")
