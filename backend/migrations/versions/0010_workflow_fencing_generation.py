"""Fence writes from expired workflow workers.

Revision ID: 0010_workflow_fencing_generation
Revises: 0009_active_workflow_event
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_workflow_fencing_generation"
down_revision: str | None = "0009_active_workflow_event"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "generation_tasks",
        sa.Column("workflow_fencing_generation", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("generation_tasks", "workflow_fencing_generation")
