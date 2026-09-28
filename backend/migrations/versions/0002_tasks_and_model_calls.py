"""Add tasks, model call audit, and outbox tables.

Revision ID: 0002_tasks_and_model_calls
Revises: 0001_initial
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_tasks_and_model_calls"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "generation_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("current_stage", sa.String(80)),
        sa.Column("raw_requirement", postgresql.JSONB, nullable=False),
        sa.Column("model_preference", postgresql.JSONB, nullable=False),
        sa.Column("complexity", postgresql.JSONB, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_generation_tasks_status", "generation_tasks", ["status"])
    op.create_index("ix_generation_tasks_updated_at", "generation_tasks", ["updated_at"])
    op.create_table(
        "model_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generation_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workflow_node", sa.String(80), nullable=False),
        sa.Column("requested_tier", sa.String(24), nullable=False),
        sa.Column("preferred_model_key", sa.String(100), nullable=False),
        sa.Column("actual_model_key", sa.String(100), nullable=False),
        sa.Column("attempt_no", sa.Integer, nullable=False),
        sa.Column("fallback_from", sa.String(100)),
        sa.Column("route_reason", postgresql.JSONB, nullable=False),
        sa.Column("request_tokens", sa.Integer),
        sa.Column("response_tokens", sa.Integer),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("error_type", sa.String(80)),
        sa.Column("error_message", sa.Text),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_model_calls_task_id", "model_calls", ["task_id"])
    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_outbox_events_aggregate_id", "outbox_events", ["aggregate_id"])


def downgrade() -> None:
    op.drop_index("ix_outbox_events_aggregate_id", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_model_calls_task_id", table_name="model_calls")
    op.drop_table("model_calls")
    op.drop_index("ix_generation_tasks_updated_at", table_name="generation_tasks")
    op.drop_index("ix_generation_tasks_status", table_name="generation_tasks")
    op.drop_table("generation_tasks")
