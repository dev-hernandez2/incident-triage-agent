"""create tool_calls table

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-20

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_calls",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("args", postgresql.JSONB(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("output_bytes", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_tool_calls_incident_id", "tool_calls", ["incident_id"])


def downgrade() -> None:
    op.drop_index("ix_tool_calls_incident_id", table_name="tool_calls")
    op.drop_table("tool_calls")
