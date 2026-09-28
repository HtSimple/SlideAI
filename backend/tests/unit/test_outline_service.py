from datetime import UTC, datetime
from uuid import UUID

import pytest

from slideai.application.outlines.service import OutlineService
from slideai.core.errors import DomainError
from slideai.domain.requirements.models import (
    Outline,
    OutlineItem,
    OutlineSection,
    StructuredRequirement,
)
from slideai.domain.tasks.models import (
    ModelPreference,
    RawRequirement,
    TaskRecord,
    TaskStatus,
    initial_complexity,
)


class MemoryTaskRepository:
    def __init__(self, task: TaskRecord) -> None:
        self.task = task

    async def get(self, task_id: UUID) -> TaskRecord | None:
        return self.task if task_id == self.task.id else None

    async def update(self, task: TaskRecord, *, expected_version: int) -> None:
        if self.task.version != expected_version:
            raise DomainError("VERSION_CONFLICT", "Task changed.")
        self.task = task


class Queue:
    def __init__(self) -> None:
        self.started: list[UUID] = []
        self.resumed: list[tuple[UUID, dict[str, object]]] = []

    def enqueue_start(self, task_id: UUID) -> None:
        self.started.append(task_id)

    def enqueue_resume(self, task_id: UUID, resume: dict[str, object]) -> None:
        self.resumed.append((task_id, resume))


def _outline(page_count: int) -> Outline:
    return Outline(
        title="Industry outlook",
        sections=[
            OutlineSection(
                id="market",
                title="Market",
                objective="Describe market context",
                page_count=page_count,
                items=[
                    OutlineItem(
                        id="market-size",
                        title="Market size",
                        objective="Explain current scale",
                        page_count=page_count,
                    )
                ],
            )
        ],
    )


def _task() -> TaskRecord:
    raw = RawRequirement(topic="Industry outlook", target_page_count=6)
    requirement = StructuredRequirement(
        topic=raw.topic,
        target_page_count=raw.target_page_count,
        scenario="Annual review",
        audience="Leadership",
        style="Clear and evidence-led",
    )
    now = datetime.now(UTC)
    return TaskRecord(
        name=raw.topic,
        status=TaskStatus.WAITING_OUTLINE_CONFIRMATION,
        raw_requirement=raw,
        model_preference=ModelPreference(),
        complexity=initial_complexity(raw),
        structured_requirement=requirement,
        version=4,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_outline_edit_increments_version() -> None:
    task = _task()
    repository = MemoryTaskRepository(task)
    service = OutlineService(repository, Queue())

    saved = await service.update(task.id, expected_version=4, outline=_outline(6))

    assert saved.version == 5
    assert saved.outline == _outline(6)
    assert repository.task.version == 5


@pytest.mark.asyncio
async def test_outline_edit_rejects_page_allocation_mismatch() -> None:
    task = _task()
    service = OutlineService(MemoryTaskRepository(task), Queue())

    with pytest.raises(DomainError) as raised:
        await service.update(task.id, expected_version=4, outline=_outline(5))

    assert raised.value.code == "OUTLINE_INVALID"
