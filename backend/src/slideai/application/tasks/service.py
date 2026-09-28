from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from slideai.core.errors import DomainError
from slideai.domain.models.catalog import ModelCatalog
from slideai.domain.tasks.models import (
    CreateTaskCommand,
    ModelPreference,
    RawRequirement,
    TaskPage,
    TaskRecord,
    TaskStatus,
    initial_complexity,
)


class TaskRepository(Protocol):
    async def add(self, task: TaskRecord) -> None: ...
    async def get(self, task_id: UUID) -> TaskRecord | None: ...
    async def list(
        self, *, offset: int, limit: int, status: str | None = None, query: str | None = None
    ) -> tuple[list[TaskRecord], int]: ...
    async def update(self, task: TaskRecord, *, expected_version: int) -> None: ...
    async def delete(self, task_id: UUID) -> None: ...
    async def status_counts(self) -> dict[str, int]: ...


class TaskService:
    def __init__(
        self,
        repository: TaskRepository,
        *,
        model_catalog: ModelCatalog | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.model_catalog = model_catalog
        self.clock = clock or (lambda: datetime.now(UTC))

    async def create(self, command: CreateTaskCommand) -> TaskRecord:
        self._validate_model_preference(command.model_preference)
        now = self.clock()
        task = TaskRecord(
            name=command.raw_requirement.topic,
            raw_requirement=command.raw_requirement,
            model_preference=command.model_preference,
            complexity=initial_complexity(command.raw_requirement),
            created_at=now,
            updated_at=now,
        )
        await self.repository.add(task)
        return task

    async def list_tasks(
        self, *, offset: int, limit: int, status: str | None = None, query: str | None = None
    ) -> TaskPage:
        items, total = await self.repository.list(
            offset=offset, limit=limit, status=status, query=query
        )
        return TaskPage(
            items=items,
            total=total,
            offset=offset,
            limit=limit,
            status_counts=await self.repository.status_counts(),
        )

    async def get(self, task_id: UUID) -> TaskRecord:
        task = await self.repository.get(task_id)
        if task is None:
            raise DomainError("TASK_NOT_FOUND", "Task was not found.")
        return task

    async def patch(
        self, task_id: UUID, *, expected_version: int, changes: dict[str, object]
    ) -> TaskRecord:
        task = await self.get(task_id)
        if task.status != TaskStatus.DRAFT:
            raise DomainError("TASK_CONFLICT", "Only draft tasks can be edited.")
        if task.version != expected_version:
            raise DomainError(
                "VERSION_CONFLICT",
                "Task changed since it was loaded.",
                {"expected_version": expected_version, "actual_version": task.version},
            )

        raw_requirement = task.raw_requirement
        model_preference = task.model_preference
        if "raw_requirement" in changes and changes["raw_requirement"] is not None:
            raw_requirement = RawRequirement.model_validate(changes["raw_requirement"])
        if "model_preference" in changes and changes["model_preference"] is not None:
            model_preference = ModelPreference.model_validate(changes["model_preference"])
        self._validate_model_preference(model_preference)
        name = str(changes.get("name") or raw_requirement.topic)
        now = self.clock()
        updated = task.model_copy(
            update={
                "name": name,
                "raw_requirement": raw_requirement,
                "model_preference": model_preference,
                "complexity": initial_complexity(raw_requirement),
                "version": task.version + 1,
                "updated_at": now,
            }
        )
        await self.repository.update(updated, expected_version=expected_version)
        return updated

    async def delete(self, task_id: UUID, *, expected_version: int | None = None) -> None:
        task = await self.get(task_id)
        if task.status != TaskStatus.DRAFT:
            raise DomainError("TASK_CONFLICT", "Only draft tasks can be deleted.")
        if expected_version is not None and task.version != expected_version:
            raise DomainError(
                "VERSION_CONFLICT",
                "Task changed since it was loaded.",
                {"expected_version": expected_version, "actual_version": task.version},
            )
        await self.repository.delete(task_id)

    def _validate_model_preference(self, preference: ModelPreference) -> None:
        if preference.mode != "manual" or self.model_catalog is None:
            return
        model = self.model_catalog.models.get(preference.model_key or "")
        if model is None or not model.enabled or not model.available:
            raise DomainError(
                "MODEL_NOT_AVAILABLE",
                "The selected model is not available in the configured model catalog.",
                {"model_key": preference.model_key},
            )
