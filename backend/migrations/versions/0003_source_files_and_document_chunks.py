"""Add task-scoped source files and document chunks.

Revision ID: 0003_files_chunks
Revises: 0002_tasks_and_model_calls
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_files_chunks"
down_revision: str | None = "0002_tasks_and_model_calls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generation_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("stored_name", sa.String(80), nullable=False, unique=True),
        sa.Column("mime_type", sa.String(160), nullable=False),
        sa.Column("extension", sa.String(12), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.Text),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("size_bytes > 0", name="ck_source_files_size_positive"),
        sa.UniqueConstraint("task_id", "id", name="uq_source_files_task_id"),
    )
    op.create_index("ix_source_files_task_id", "source_files", ["task_id"])
    op.create_index("ix_source_files_status", "source_files", ["status"])
    op.create_index("ix_source_files_task_status", "source_files", ["task_id", "status"])
    op.create_index(
        "uq_source_files_task_sha256_active",
        "source_files",
        ["task_id", "sha256"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generation_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "file_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("token_count", sa.Integer, nullable=False),
        sa.Column("page_number", sa.Integer),
        sa.Column("section_title", sa.String(500)),
        sa.Column("paragraph_index", sa.Integer),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("embedding_version", sa.String(80), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "file_id"],
            ["source_files.task_id", "source_files.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_document_chunks_task_id", "document_chunks", ["task_id"])
    op.create_index("ix_document_chunks_file_id", "document_chunks", ["file_id"])
    op.create_index("ix_document_chunks_task_file", "document_chunks", ["task_id", "file_id"])
    op.create_index(
        "uq_document_chunks_file_ordinal",
        "document_chunks",
        ["task_id", "file_id", "ordinal"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_document_chunks_file_ordinal", table_name="document_chunks")
    op.drop_index("ix_document_chunks_task_file", table_name="document_chunks")
    op.drop_index("ix_document_chunks_file_id", table_name="document_chunks")
    op.drop_index("ix_document_chunks_task_id", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("uq_source_files_task_sha256_active", table_name="source_files")
    op.drop_index("ix_source_files_task_status", table_name="source_files")
    op.drop_index("ix_source_files_status", table_name="source_files")
    op.drop_index("ix_source_files_task_id", table_name="source_files")
    op.drop_table("source_files")
