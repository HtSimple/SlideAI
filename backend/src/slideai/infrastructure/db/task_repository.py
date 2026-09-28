from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from slideai.core.errors import DomainError
from slideai.domain.content.models import SlideProgress
from slideai.domain.tasks.models import TaskRecord
from slideai.infrastructure.db.models import GenerationTaskRow, ModelCallRow, OutboxEventRow


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

    async def update_with_outbox(
        self,
        task: TaskRecord,
        *,
        expected_version: int,
        event_type: str,
        payload: dict[str, Any],
    ) -> UUID:
        event_id = uuid4()
        async with self.sessions() as session, session.begin():
            row = await session.scalar(
                select(GenerationTaskRow).where(GenerationTaskRow.id == task.id).with_for_update()
            )
            actual_version = row.version if row else None
            if row is None or actual_version != expected_version:
                raise DomainError(
                    "VERSION_CONFLICT",
                    "Task changed since it was loaded.",
                    {"expected_version": expected_version, "actual_version": actual_version},
                )
            _apply_record(row, task)
            if event_type in {"workflow.start", "workflow.resume"}:
                row.active_workflow_event_id = event_id
            session.add(
                OutboxEventRow(
                    id=event_id,
                    event_type=event_type,
                    aggregate_id=task.id,
                    payload=payload,
                )
            )
        return event_id

    async def is_active_workflow_event(self, task_id: UUID, event_id: UUID) -> bool:
        async with self.sessions() as session:
            active_event_id = await session.scalar(
                select(GenerationTaskRow.active_workflow_event_id).where(
                    GenerationTaskRow.id == task_id
                )
            )
            return active_event_id == event_id

    async def claim_workflow_lease(
        self, task_id: UUID, event_id: UUID | None, fencing_generation: int
    ) -> bool:
        async with self.sessions() as session, session.begin():
            row = await session.get(GenerationTaskRow, task_id, with_for_update=True)
            if row is None or row.status != "RUNNING":
                return False
            if event_id is not None and row.active_workflow_event_id != event_id:
                return False
            if fencing_generation <= (row.workflow_fencing_generation or 0):
                return False
            row.workflow_fencing_generation = fencing_generation
            return True

    async def workflow_fencing_generation(self, task_id: UUID) -> int:
        async with self.sessions() as session:
            generation = await session.scalar(
                select(GenerationTaskRow.workflow_fencing_generation).where(
                    GenerationTaskRow.id == task_id
                )
            )
            return generation or 0

    async def update_progress(
        self, task_id: UUID, progress: SlideProgress, *, fencing_generation: int
    ) -> None:
        async with self.sessions() as session, session.begin():
            row = await session.get(GenerationTaskRow, task_id, with_for_update=True)
            if row is None:
                raise DomainError("TASK_NOT_FOUND", "Task was not found.")
            if row.status == "CANCELLED":
                raise DomainError("WORKFLOW_CANCELLED", "The task was cancelled.")
            if row.status != "RUNNING":
                raise DomainError(
                    "TASK_CONFLICT", "Progress can only be updated by a running task."
                )
            if row.workflow_fencing_generation != fencing_generation:
                raise DomainError("WORKFLOW_LOCK_LOST", "The workflow worker lost its task lock.")
            row.generation_progress = progress.model_dump(mode="json")
            row.current_stage = "write_slides"
            row.version += 1
            row.updated_at = datetime.now(UTC)

    async def update_workflow_projection(
        self,
        task: TaskRecord,
        *,
        expected_version: int,
        fencing_generation: int,
    ) -> bool:
        async with self.sessions() as session, session.begin():
            row = await session.get(GenerationTaskRow, task.id, with_for_update=True)
            if (
                row is None
                or row.status != "RUNNING"
                or row.version != expected_version
                or row.workflow_fencing_generation != fencing_generation
            ):
                return False
            _apply_record(row, task)
            return True

    async def mark_failed_if_workflow_current(self, task_id: UUID, fencing_generation: int) -> bool:
        async with self.sessions() as session, session.begin():
            row = await session.get(GenerationTaskRow, task_id, with_for_update=True)
            if (
                row is None
                or row.status != "RUNNING"
                or row.workflow_fencing_generation != fencing_generation
            ):
                return False
            row.status = "FAILED_RETRYABLE"
            row.version += 1
            row.updated_at = datetime.now(UTC)
            return True

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
        structured_requirement=(
            task.structured_requirement.model_dump(mode="json")
            if task.structured_requirement is not None
            else None
        ),
        outline=task.outline.model_dump(mode="json") if task.outline is not None else None,
        generation_progress=(
            task.generation_progress.model_dump(mode="json")
            if task.generation_progress is not None
            else None
        ),
        evaluation_result=(
            task.evaluation_result.model_dump(mode="json")
            if task.evaluation_result is not None
            else None
        ),
        revision_count=task.revision_count,
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
    row.structured_requirement = (
        task.structured_requirement.model_dump(mode="json")
        if task.structured_requirement is not None
        else None
    )
    row.outline = task.outline.model_dump(mode="json") if task.outline is not None else None
    row.generation_progress = (
        task.generation_progress.model_dump(mode="json")
        if task.generation_progress is not None
        else None
    )
    row.evaluation_result = (
        task.evaluation_result.model_dump(mode="json")
        if task.evaluation_result is not None
        else None
    )
    row.revision_count = task.revision_count
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
            "structured_requirement": row.structured_requirement,
            "outline": row.outline,
            "generation_progress": row.generation_progress,
            "evaluation_result": row.evaluation_result,
            "revision_count": row.revision_count,
            "version": row.version,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    )
