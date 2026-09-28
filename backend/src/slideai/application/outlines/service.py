from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from slideai.application.workflows.ports import WorkflowQueue
from slideai.core.errors import DomainError
from slideai.domain.requirements.models import Outline
from slideai.domain.requirements.validation import validate_outline
from slideai.domain.tasks.models import TaskRecord, TaskStatus


class TaskRepository(Protocol):
    async def get(self, task_id: UUID) -> TaskRecord | None: ...

    async def update(self, task: TaskRecord, *, expected_version: int) -> None: ...


class OutlineService:
    def __init__(
        self,
        repository: TaskRepository,
        queue: WorkflowQueue,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.queue = queue
        self.clock = clock or (lambda: datetime.now(UTC))

    async def get(self, task_id: UUID) -> tuple[TaskRecord, list[dict[str, Any]]]:
        task = await self._get(task_id)
        return task, self._issues(task, task.outline) if task.outline else []

    async def update(
        self,
        task_id: UUID,
        *,
        expected_version: int,
        outline: Outline,
    ) -> TaskRecord:
        task = await self._get(task_id)
        self._expect_waiting(task)
        self._expect_version(task, expected_version)
        issues = self._issues(task, outline)
        if issues:
            raise DomainError("OUTLINE_INVALID", "Fix the outline page allocation issues.", issues)
        updated = task.model_copy(
            update={
                "outline": outline,
                "version": task.version + 1,
                "updated_at": self.clock(),
            }
        )
        await self.repository.update(updated, expected_version=expected_version)
        return updated

    async def confirm(self, task_id: UUID, *, expected_version: int) -> TaskRecord:
        task = await self._get(task_id)
        self._expect_waiting(task)
        self._expect_version(task, expected_version)
        if task.outline is None:
            raise DomainError("OUTLINE_INVALID", "Create an outline before confirming it.")
        issues = self._issues(task, task.outline)
        if issues:
            raise DomainError("OUTLINE_INVALID", "Fix the outline page allocation issues.", issues)
        updated = task.model_copy(
            update={
                "status": TaskStatus.RUNNING,
                "current_stage": "outline_confirmed",
                "version": task.version + 1,
                "updated_at": self.clock(),
            }
        )
        await self.repository.update(updated, expected_version=expected_version)
        self.queue.enqueue_resume(
            task_id,
            {"kind": "outline_confirmed", "outline": task.outline.model_dump(mode="json")},
        )
        return updated

    async def _get(self, task_id: UUID) -> TaskRecord:
        task = await self.repository.get(task_id)
        if task is None:
            raise DomainError("TASK_NOT_FOUND", "Task was not found.")
        return task

    @staticmethod
    def _expect_waiting(task: TaskRecord) -> None:
        if task.status != TaskStatus.WAITING_OUTLINE_CONFIRMATION:
            raise DomainError("TASK_CONFLICT", "The task is not waiting for outline review.")

    @staticmethod
    def _expect_version(task: TaskRecord, expected_version: int) -> None:
        if task.version != expected_version:
            raise DomainError(
                "VERSION_CONFLICT",
                "Task changed since it was loaded.",
                {"expected_version": expected_version, "actual_version": task.version},
            )

    @staticmethod
    def _issues(task: TaskRecord, outline: Outline) -> list[dict[str, Any]]:
        page_count = (
            task.structured_requirement.target_page_count
            if task.structured_requirement is not None
            else task.raw_requirement.target_page_count
        )
        return [
            issue.model_dump(mode="json") for issue in validate_outline(outline, page_count or 0)
        ]
