from datetime import UTC, datetime
from uuid import UUID

import pytest

from slideai.application.tasks.service import TaskService
from slideai.core.errors import DomainError
from slideai.domain.models.catalog import ModelCatalog
from slideai.domain.tasks.models import (
    CreateTaskCommand,
    ModelPreference,
    RawRequirement,
    TaskRecord,
)


class MemoryTaskRepository:
    def __init__(self) -> None:
        self.records: dict[UUID, TaskRecord] = {}

    async def add(self, task: TaskRecord) -> None:
        self.records[task.id] = task

    async def get(self, task_id: UUID) -> TaskRecord | None:
        return self.records.get(task_id)

    async def list(
        self, *, offset: int, limit: int, status: str | None = None, query: str | None = None
    ) -> tuple[list[TaskRecord], int]:
        rows = list(self.records.values())
        if status is not None:
            rows = [row for row in rows if row.status.value == status]
        if query:
            rows = [row for row in rows if query.casefold() in row.name.casefold()]
        rows.sort(key=lambda row: row.updated_at, reverse=True)
        return rows[offset : offset + limit], len(rows)

    async def update(self, task: TaskRecord, *, expected_version: int) -> None:
        current = self.records[task.id]
        if current.version != expected_version:
            raise DomainError(
                "VERSION_CONFLICT",
                "Task changed since it was loaded.",
                {"expected_version": expected_version, "actual_version": current.version},
            )
        self.records[task.id] = task

    async def delete(self, task_id: UUID) -> None:
        self.records.pop(task_id, None)

    async def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for task in self.records.values():
            counts[task.status.value] = counts.get(task.status.value, 0) + 1
        return counts


def command(topic: str) -> CreateTaskCommand:
    return CreateTaskCommand(
        raw_requirement=RawRequirement(topic=topic, target_page_count=12),
        model_preference=ModelPreference(),
    )


@pytest.mark.asyncio
async def test_create_task_starts_draft_at_version_one() -> None:
    service = TaskService(MemoryTaskRepository())

    task = await service.create(command("AI 行业趋势"))

    assert task.status.value == "DRAFT"
    assert task.version == 1
    assert task.name == "AI 行业趋势"
    assert task.raw_requirement.target_page_count == 12


@pytest.mark.asyncio
async def test_task_list_is_paginated_and_ordered_by_updated_at() -> None:
    clock_values = iter(datetime(2026, 9, 28, 10, minute, tzinfo=UTC) for minute in (1, 2, 3, 4))
    service = TaskService(MemoryTaskRepository(), clock=lambda: next(clock_values))
    first = await service.create(command("First task"))
    second = await service.create(command("Second task"))
    await service.patch(
        first.id,
        expected_version=1,
        changes={"name": "First task updated"},
    )

    page = await service.list_tasks(offset=0, limit=1)

    assert page.total == 2
    assert len(page.items) == 1
    assert page.items[0].id == first.id
    assert page.items[0].updated_at > second.updated_at


@pytest.mark.asyncio
async def test_patch_requires_expected_version() -> None:
    service = TaskService(MemoryTaskRepository())
    task = await service.create(command("Quarterly review"))
    saved = await service.patch(task.id, expected_version=1, changes={"name": "Updated review"})

    assert saved.version == 2
    assert saved.name == "Updated review"

    with pytest.raises(DomainError) as raised:
        await service.patch(task.id, expected_version=1, changes={"name": "Stale update"})

    assert raised.value.code == "VERSION_CONFLICT"
    assert raised.value.details == {"expected_version": 1, "actual_version": 2}


@pytest.mark.asyncio
async def test_manual_task_rejects_model_outside_catalog() -> None:
    service = TaskService(MemoryTaskRepository(), model_catalog=ModelCatalog(models={}))
    manual_command = CreateTaskCommand(
        raw_requirement=RawRequirement(topic="Quarterly review", target_page_count=12),
        model_preference=ModelPreference(mode="manual", model_key="not-configured"),
    )

    with pytest.raises(DomainError) as raised:
        await service.create(manual_command)

    assert raised.value.code == "MODEL_NOT_AVAILABLE"
