"""Persist structured requirements and outline review state.

Revision ID: 0004_requirement_outline
Revises: 0003_files_chunks
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_requirement_outline"
down_revision: str | None = "0003_files_chunks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generation_tasks", sa.Column("structured_requirement", postgresql.JSONB, nullable=True)
    )
    op.add_column("generation_tasks", sa.Column("outline", postgresql.JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("generation_tasks", "outline")
    op.drop_column("generation_tasks", "structured_requirement")
