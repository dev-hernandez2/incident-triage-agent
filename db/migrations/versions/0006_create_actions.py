"""create actions table

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-22

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "actions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("deployment", sa.Text(), nullable=True),
        sa.Column("replicas", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("approved_by", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_actions_incident_id", "actions", ["incident_id"])
    op.create_index(
        "ix_actions_pending",
        "actions",
        ["status"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_actions_approved",
        "actions",
        ["status"],
        postgresql_where=sa.text("status = 'approved'"),
    )


def downgrade() -> None:
    op.drop_index("ix_actions_approved", table_name="actions")
    op.drop_index("ix_actions_pending", table_name="actions")
    op.drop_index("ix_actions_incident_id", table_name="actions")
    op.drop_table("actions")
