"""convert findings.suggested_fix to jsonb

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-22

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # suggested_fix is a Text column today, but its rows are NOT uniformly
    # free text. Task 1 (commit 7329c5e) changed services/agent to write new
    # rows as a JSON-encoded string of the typed action dict (e.g. the text
    # '{"type": "rollback", "deployment": "cartservice", "reason": "..."}')
    # as a bridge while this column was still Text. Any row written before
    # Task 1 landed may still hold genuinely free text (e.g. "set REDIS_ADDR").
    #
    # We cannot distinguish these two shapes with a plain cast: a bare
    # `suggested_fix::jsonb` fails outright on legacy free text, and
    # `jsonb_build_object('type', 'manual', 'reason', suggested_fix)` for
    # every row would double-wrap every row Task 1 already wrote correctly,
    # turning `{"type": "rollback", ...}` into
    # `{"type": "manual", "reason": "{\"type\": \"rollback\", ...}"}`.
    #
    # Instead we do this in two passes:
    #   1. An UPDATE that wraps as a manual action ONLY the rows that don't
    #      look like a JSON object to begin with (a cheap heuristic: every
    #      JSON-encoded dict from Task 1 starts with '{' once whitespace is
    #      stripped; real free text from before Task 1 essentially never
    #      does). This is pre-production data with no real legacy rows
    #      expected in practice, so the heuristic is sufficient here rather
    #      than needing a PL/pgSQL exception-catching helper.
    #   2. A plain `suggested_fix::jsonb` cast in alter_column, which is now
    #      safe because every row is valid JSON text after step 1.
    op.execute(
        r"""
        UPDATE findings
        SET suggested_fix = jsonb_build_object('type', 'manual', 'reason', suggested_fix)::text
        WHERE suggested_fix !~ '^\s*\{'
        """
    )
    op.alter_column(
        "findings",
        "suggested_fix",
        type_=postgresql.JSONB(),
        postgresql_using="suggested_fix::jsonb",
    )


def downgrade() -> None:
    op.alter_column(
        "findings",
        "suggested_fix",
        type_=sa.Text(),
        postgresql_using="suggested_fix::text",
    )
