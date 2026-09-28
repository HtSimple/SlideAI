"""Fence stale duplicate workflow deliveries.

Revision ID: 0009_active_workflow_event
Revises: 0008_change_impact_pages
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_active_workflow_event"
down_revision: str | None = "0008_change_impact_pages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "generation_tasks",
        sa.Column("active_workflow_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("generation_tasks", "active_workflow_event_id")
