"""Store readable page numbers in chat change impact projections.

Revision ID: 0008_change_impact_pages
Revises: 0007_chat_changes
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_change_impact_pages"
down_revision: str | None = "0007_chat_changes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "change_requests",
        sa.Column(
            "affected_pages",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("change_requests", "affected_pages")
