"""Persist task-scoped chat, change requests and outline-aware revisions.

Revision ID: 0007_chat_changes
Revises: 0006_evaluation_revisions
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_chat_changes"
down_revision: str | None = "0006_evaluation_revisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("revisions", sa.Column("before_outline", postgresql.JSONB(), nullable=True))
    op.add_column("revisions", sa.Column("after_outline", postgresql.JSONB(), nullable=True))
    op.create_table(
        "chat_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["task_id"], ["generation_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_chat_conversations_task"),
        sa.UniqueConstraint("task_id", "id", name="uq_chat_conversations_task_id"),
    )
    op.create_index("ix_chat_conversations_task_id", "chat_conversations", ["task_id"])
    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("target", postgresql.JSONB(), nullable=True),
        sa.Column("change_request", postgresql.JSONB(), nullable=True),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("can_undo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["task_id"], ["generation_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_id", "conversation_id"],
            ["chat_conversations.task_id", "chat_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "id", name="uq_chat_messages_task_id"),
    )
    op.create_index("ix_chat_messages_task_id", "chat_messages", ["task_id"])
    op.create_index("ix_chat_messages_task_created", "chat_messages", ["task_id", "created_at"])
    op.create_table(
        "change_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_type", sa.String(length=24), nullable=False),
        sa.Column("target_ids", postgresql.JSONB(), nullable=False),
        sa.Column("operation", sa.String(length=24), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("replacement_text", sa.String(length=1000), nullable=True),
        sa.Column("impact_scope", postgresql.JSONB(), nullable=False),
        sa.Column("risk_level", sa.String(length=24), nullable=False),
        sa.Column("needs_clarification", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("clarification_question", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expected_task_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["generation_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_id", "source_message_id"],
            ["chat_messages.task_id", "chat_messages.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_change_requests_task_id", "change_requests", ["task_id"])
    op.create_index("ix_change_requests_task_status", "change_requests", ["task_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_change_requests_task_status", table_name="change_requests")
    op.drop_index("ix_change_requests_task_id", table_name="change_requests")
    op.drop_table("change_requests")
    op.drop_index("ix_chat_messages_task_created", table_name="chat_messages")
    op.drop_index("ix_chat_messages_task_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_conversations_task_id", table_name="chat_conversations")
    op.drop_table("chat_conversations")
    op.drop_column("revisions", "after_outline")
    op.drop_column("revisions", "before_outline")
