from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from slideai.infrastructure.db.base import Base


class GenerationTaskRow(Base):
    __tablename__ = "generation_tasks"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    current_stage: Mapped[str | None] = mapped_column(String(80))
    raw_requirement: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    model_preference: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    complexity: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    structured_requirement: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    outline: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    generation_progress: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    evaluation_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    revision_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active_workflow_event_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    workflow_fencing_generation: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )


class ModelCallRow(Base):
    __tablename__ = "model_calls"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("generation_tasks.id", ondelete="CASCADE"), index=True
    )
    workflow_node: Mapped[str] = mapped_column(String(80), nullable=False)
    requested_tier: Mapped[str] = mapped_column(String(24), nullable=False)
    preferred_model_key: Mapped[str] = mapped_column(String(100), nullable=False)
    actual_model_key: Mapped[str] = mapped_column(String(100), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    fallback_from: Mapped[str | None] = mapped_column(String(100))
    route_reason: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    request_tokens: Mapped[int | None] = mapped_column(Integer)
    response_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OutboxEventRow(Base):
    __tablename__ = "outbox_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SourceFileRow(Base):
    __tablename__ = "source_files"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_source_files_size_positive"),
        UniqueConstraint("task_id", "id", name="uq_source_files_task_id"),
        Index(
            "uq_source_files_task_sha256_active",
            "task_id",
            "sha256",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_source_files_task_status", "task_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("generation_tasks.id", ondelete="CASCADE"), index=True
    )
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(160), nullable=False)
    extension: Mapped[str] = mapped_column(String(12), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentChunkRow(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "file_id"],
            ["source_files.task_id", "source_files.id"],
            ondelete="CASCADE",
        ),
        Index("uq_document_chunks_file_ordinal", "task_id", "file_id", "ordinal", unique=True),
        Index("ix_document_chunks_task_file", "task_id", "file_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("generation_tasks.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_title: Mapped[str | None] = mapped_column(String(500))
    paragraph_index: Mapped[int | None] = mapped_column(Integer)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SlidePageRow(Base):
    __tablename__ = "slide_pages"
    __table_args__ = (
        UniqueConstraint("task_id", "page_number", name="uq_slide_pages_task_page"),
        CheckConstraint("page_number > 0", name="ck_slide_pages_page_number_positive"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("generation_tasks.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    section_id: Mapped[str] = mapped_column(String(80), nullable=False)
    outline_item_id: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    bullets: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    speaker_notes: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    verification_notes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RevisionRow(Base):
    __tablename__ = "revisions"
    __table_args__ = (
        UniqueConstraint("task_id", "revision_number", name="uq_revisions_task_number"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("generation_tasks.id", ondelete="CASCADE"), index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_type: Mapped[str] = mapped_column(String(24), nullable=False)
    scope: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    before_slides: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    after_slides: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    before_outline: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_outline: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    score_before: Mapped[int | None] = mapped_column(Integer)
    score_after: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ChatConversationRow(Base):
    __tablename__ = "chat_conversations"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_chat_conversations_task"),
        UniqueConstraint("task_id", "id", name="uq_chat_conversations_task_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("generation_tasks.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ChatMessageRow(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "conversation_id"],
            ["chat_conversations.task_id", "chat_conversations.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("task_id", "id", name="uq_chat_messages_task_id"),
        Index("ix_chat_messages_task_created", "task_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("generation_tasks.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    change_request: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    revision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    can_undo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ChangeRequestRow(Base):
    __tablename__ = "change_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "source_message_id"],
            ["chat_messages.task_id", "chat_messages.id"],
            ondelete="CASCADE",
        ),
        Index("ix_change_requests_task_status", "task_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("generation_tasks.id", ondelete="CASCADE"), index=True
    )
    source_message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    target_type: Mapped[str] = mapped_column(String(24), nullable=False)
    target_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    affected_pages: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    operation: Mapped[str] = mapped_column(String(24), nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    replacement_text: Mapped[str | None] = mapped_column(String(1000))
    impact_scope: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(24), nullable=False)
    needs_clarification: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    clarification_question: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_task_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
