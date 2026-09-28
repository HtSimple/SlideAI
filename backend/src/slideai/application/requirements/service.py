from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from slideai.application.workflows.ports import WorkflowQueue
from slideai.core.errors import DomainError
from slideai.domain.requirements.models import StructuredRequirement
from slideai.domain.tasks.models import TaskRecord, TaskStatus


class TaskRepository(Protocol):
    async def get(self, task_id: UUID) -> TaskRecord | None: ...

    async def update(self, task: TaskRecord, *, expected_version: int) -> None: ...


class RequirementService:
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

    async def get(self, task_id: UUID) -> tuple[TaskRecord, list[str]]:
        task = await self._get(task_id)
        requirement = task.structured_requirement
        return task, requirement.missing_fields() if requirement else []

    async def update(
        self,
        task_id: UUID,
        *,
        expected_version: int,
        requirement: StructuredRequirement,
    ) -> TaskRecord:
        task = await self._get(task_id)
        self._expect_waiting(task, TaskStatus.WAITING_REQUIREMENT_INPUT)
        self._expect_version(task, expected_version)
        updated = task.model_copy(
            update={
                "structured_requirement": requirement,
                "version": task.version + 1,
                "updated_at": self.clock(),
            }
        )
        await self.repository.update(updated, expected_version=expected_version)
        return updated

    async def confirm(self, task_id: UUID, *, expected_version: int) -> TaskRecord:
        task = await self._get(task_id)
        self._expect_waiting(task, TaskStatus.WAITING_REQUIREMENT_INPUT)
        self._expect_version(task, expected_version)
        requirement = task.structured_requirement
        if requirement is None:
            raise DomainError(
                "REQUIREMENT_INCOMPLETE",
                "Complete the required fields before continuing.",
                {"missing_fields": ["structured_requirement"]},
            )
        missing = requirement.missing_fields()
        if missing:
            raise DomainError(
                "REQUIREMENT_INCOMPLETE",
                "Complete the required fields before continuing.",
                {"missing_fields": missing},
            )
        updated = task.model_copy(
            update={
                "status": TaskStatus.RUNNING,
                "current_stage": "outline",
                "version": task.version + 1,
                "updated_at": self.clock(),
            }
        )
        await self.repository.update(updated, expected_version=expected_version)
        self.queue.enqueue_resume(
            task_id,
            {
                "kind": "requirement_confirmed",
                "structured_requirement": requirement.model_dump(mode="json"),
            },
        )
        return updated

    async def _get(self, task_id: UUID) -> TaskRecord:
        task = await self.repository.get(task_id)
        if task is None:
            raise DomainError("TASK_NOT_FOUND", "Task was not found.")
        return task

    @staticmethod
    def _expect_waiting(task: TaskRecord, expected: TaskStatus) -> None:
        if task.status != expected:
            raise DomainError("TASK_CONFLICT", "The task is not waiting for requirement input.")

    @staticmethod
    def _expect_version(task: TaskRecord, expected_version: int) -> None:
        if task.version != expected_version:
            raise DomainError(
                "VERSION_CONFLICT",
                "Task changed since it was loaded.",
                {"expected_version": expected_version, "actual_version": task.version},
            )
