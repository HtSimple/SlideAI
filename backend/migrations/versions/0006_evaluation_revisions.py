"""Persist quality evaluations and immutable content revision snapshots.

Revision ID: 0006_evaluation_revisions
Revises: 0005_slide_content
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_evaluation_revisions"
down_revision: str | None = "0005_slide_content"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generation_tasks",
        sa.Column("evaluation_result", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "generation_tasks",
        sa.Column("revision_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_table(
        "revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("revision_type", sa.String(length=24), nullable=False),
        sa.Column("scope", postgresql.JSONB(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("before_slides", postgresql.JSONB(), nullable=False),
        sa.Column("after_slides", postgresql.JSONB(), nullable=False),
        sa.Column("score_before", sa.Integer(), nullable=True),
        sa.Column("score_after", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["task_id"], ["generation_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "revision_number", name="uq_revisions_task_number"),
    )
    op.create_index("ix_revisions_task_id", "revisions", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_revisions_task_id", table_name="revisions")
    op.drop_table("revisions")
    op.drop_column("generation_tasks", "revision_count")
    op.drop_column("generation_tasks", "evaluation_result")
