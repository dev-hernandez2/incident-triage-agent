"""create incidents table

Revision ID: 0001
Revises:
Create Date: 2026-10-16

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("alertname", sa.Text(), nullable=False),
        sa.Column("labels", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_incidents_fingerprint_received",
        "incidents",
        ["fingerprint"],
        unique=True,
        postgresql_where=sa.text("status = 'received'"),
    )


def downgrade() -> None:
    op.drop_index("ix_incidents_fingerprint_received", table_name="incidents")
    op.drop_table("incidents")
