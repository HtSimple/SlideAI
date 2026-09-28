"""Persist generated slide pages and page-level generation progress.

Revision ID: 0005_slide_content
Revises: 0004_requirement_outline
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_slide_content"
down_revision: str | None = "0004_requirement_outline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generation_tasks",
        sa.Column("generation_progress", postgresql.JSONB(), nullable=True),
    )
    op.create_table(
        "slide_pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("section_id", sa.String(length=80), nullable=False),
        sa.Column("outline_item_id", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("bullets", postgresql.JSONB(), nullable=False),
        sa.Column("speaker_notes", sa.Text(), nullable=True),
        sa.Column("citations", postgresql.JSONB(), nullable=False),
        sa.Column("verification_notes", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("page_number > 0", name="ck_slide_pages_page_number_positive"),
        sa.ForeignKeyConstraint(["task_id"], ["generation_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "page_number", name="uq_slide_pages_task_page"),
    )
    op.create_index("ix_slide_pages_task_id", "slide_pages", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_slide_pages_task_id", table_name="slide_pages")
    op.drop_table("slide_pages")
    op.drop_column("generation_tasks", "generation_progress")
