from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
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
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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
