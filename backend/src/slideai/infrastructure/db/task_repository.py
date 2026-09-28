from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from slideai.domain.tasks.models import TaskRecord
from slideai.infrastructure.db.models import GenerationTaskRow, ModelCallRow


class SqlTaskRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def add(self, task: TaskRecord) -> None:
        async with self.sessions() as session, session.begin():
            session.add(_to_row(task))

    async def get(self, task_id: UUID) -> TaskRecord | None:
        async with self.sessions() as session:
            row = await session.get(GenerationTaskRow, task_id)
            return _to_record(row) if row else None

    async def list(
        self, *, offset: int, limit: int, status: str | None = None, query: str | None = None
    ) -> tuple[list[TaskRecord], int]:
        async with self.sessions() as session:
            statement = select(GenerationTaskRow)
            count_statement = select(func.count()).select_from(GenerationTaskRow)
            if status:
                criterion = (
                    GenerationTaskRow.status.like(f"{status}%")
                    if status.endswith("_")
                    else GenerationTaskRow.status == status
                )
                statement = statement.where(criterion)
                count_statement = count_statement.where(criterion)
            if query:
                statement = statement.where(GenerationTaskRow.name.ilike(f"%{query}%"))
                count_statement = count_statement.where(GenerationTaskRow.name.ilike(f"%{query}%"))
            rows = (
                await session.scalars(
                    statement.order_by(GenerationTaskRow.updated_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
            total = await session.scalar(count_statement)
            return [_to_record(row) for row in rows], total or 0

    async def status_counts(self) -> dict[str, int]:
        async with self.sessions() as session:
            rows = await session.execute(
                select(GenerationTaskRow.status, func.count()).group_by(GenerationTaskRow.status)
            )
            return {status: count for status, count in rows.all()}

    async def update(self, task: TaskRecord, *, expected_version: int) -> None:
        async with self.sessions() as session, session.begin():
            result = await session.execute(
                select(GenerationTaskRow).where(GenerationTaskRow.id == task.id).with_for_update()
            )
            row = result.scalar_one_or_none()
            actual_version = row.version if row else None
            if row is None or actual_version != expected_version:
                from slideai.core.errors import DomainError

                raise DomainError(
                    "VERSION_CONFLICT",
                    "Task changed since it was loaded.",
                    {"expected_version": expected_version, "actual_version": actual_version},
                )
            _apply_record(row, task)

    async def delete(self, task_id: UUID) -> None:
        async with self.sessions() as session, session.begin():
            row = await session.get(GenerationTaskRow, task_id)
            if row is not None:
                await session.delete(row)

    async def record_model_call(self, record: dict[str, Any]) -> None:
        async with self.sessions() as session, session.begin():
            session.add(ModelCallRow(**record))

    async def list_model_calls(self, task_id: UUID) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(ModelCallRow)
                    .where(ModelCallRow.task_id == task_id)
                    .order_by(ModelCallRow.created_at, ModelCallRow.attempt_no)
                )
            ).all()
            return [
                {
                    "id": str(row.id),
                    "task_id": str(row.task_id),
                    "workflow_node": row.workflow_node,
                    "requested_tier": row.requested_tier,
                    "preferred_model_key": row.preferred_model_key,
                    "actual_model_key": row.actual_model_key,
                    "attempt_no": row.attempt_no,
                    "fallback_from": row.fallback_from,
                    "route_reason": row.route_reason,
                    "request_tokens": row.request_tokens,
                    "response_tokens": row.response_tokens,
                    "latency_ms": row.latency_ms,
                    "status": row.status,
                    "error_type": row.error_type,
                    "error_message": row.error_message,
                    "created_at": row.created_at,
                }
                for row in rows
            ]


def _to_row(task: TaskRecord) -> GenerationTaskRow:
    return GenerationTaskRow(
        id=task.id,
        name=task.name,
        status=task.status.value,
        current_stage=task.current_stage,
        raw_requirement=task.raw_requirement.model_dump(mode="json"),
        model_preference=task.model_preference.model_dump(mode="json"),
        complexity=task.complexity.model_dump(mode="json"),
        version=task.version,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _apply_record(row: GenerationTaskRow, task: TaskRecord) -> None:
    row.name = task.name
    row.status = task.status.value
    row.current_stage = task.current_stage
    row.raw_requirement = task.raw_requirement.model_dump(mode="json")
    row.model_preference = task.model_preference.model_dump(mode="json")
    row.complexity = task.complexity.model_dump(mode="json")
    row.version = task.version
    row.updated_at = task.updated_at


def _to_record(row: GenerationTaskRow) -> TaskRecord:
    return TaskRecord.model_validate(
        {
            "id": row.id,
            "name": row.name,
            "status": row.status,
            "current_stage": row.current_stage,
            "raw_requirement": row.raw_requirement,
            "model_preference": row.model_preference,
            "complexity": row.complexity,
            "version": row.version,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    )
