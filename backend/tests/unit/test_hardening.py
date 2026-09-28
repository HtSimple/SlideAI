from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from slideai.application.tasks.service import TaskService
from slideai.application.workflows.service import WorkflowControlService
from slideai.core.errors import DomainError
from slideai.domain.tasks.models import RawRequirement, TaskRecord, TaskStatus, initial_complexity
from slideai.workflow.runtime import _persist_projection


class MemoryWorkflowRepository:
    def __init__(self, task: TaskRecord) -> None:
        self.task = task
        self.events: list[tuple[str, UUID, dict[str, object]]] = []
        self.deleted = False

    async def get(self, task_id: UUID) -> TaskRecord | None:
        return self.task if task_id == self.task.id else None

    async def update(self, task: TaskRecord, *, expected_version: int) -> None:
        if self.task.version != expected_version:
            raise DomainError("VERSION_CONFLICT", "Task changed.")
        self.task = task

    async def update_with_outbox(
        self,
        task: TaskRecord,
        *,
        expected_version: int,
        event_type: str,
        payload: dict[str, object],
    ) -> UUID:
        await self.update(task, expected_version=expected_version)
        self.events.append((event_type, task.id, payload))
        return uuid4()

    async def delete(self, task_id: UUID) -> None:
        self.deleted = task_id == self.task.id


class MemoryFiles:
    async def list(self, task_id: UUID):
        return []


class MemoryQueue:
    def __init__(self) -> None:
        self.starts: list[UUID] = []
        self.resumes: list[tuple[UUID, dict[str, object]]] = []

    def enqueue_start(self, task_id: UUID) -> None:
        self.starts.append(task_id)

    def enqueue_resume(self, task_id: UUID, resume: dict[str, object]) -> None:
        self.resumes.append((task_id, resume))


def _task(status: TaskStatus = TaskStatus.DRAFT) -> TaskRecord:
    now = datetime.now(UTC)
    requirement = RawRequirement(topic="风险管理", target_page_count=4)
    return TaskRecord(
        id=uuid4(),
        name=requirement.topic,
        status=status,
        current_stage="working" if status == TaskStatus.RUNNING else None,
        raw_requirement=requirement,
        model_preference={"mode": "auto"},
        complexity=initial_complexity(requirement),
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_workflow_start_records_transactional_outbox_without_direct_publish() -> None:
    task = _task()
    repository = MemoryWorkflowRepository(task)
    queue = MemoryQueue()
    service = WorkflowControlService(
        repository,
        MemoryFiles(),
        queue,
        outbox_writer=repository,
    )

    started = await service.start(task.id)

    assert started.status == TaskStatus.RUNNING
    assert repository.events == [("workflow.start", task.id, {})]
    assert queue.starts == []


@pytest.mark.asyncio
async def test_retryable_failure_can_restart_using_the_same_task_checkpoint() -> None:
    task = _task(TaskStatus.FAILED_RETRYABLE)
    repository = MemoryWorkflowRepository(task)
    service = WorkflowControlService(
        repository,
        MemoryFiles(),
        MemoryQueue(),
        outbox_writer=repository,
    )

    restarted = await service.start(task.id)

    assert restarted.status == TaskStatus.RUNNING
    assert repository.events == [("workflow.start", task.id, {})]


@pytest.mark.asyncio
async def test_cancel_uses_version_and_prevents_a_running_workflow_from_resuming() -> None:
    task = _task(TaskStatus.RUNNING)
    repository = MemoryWorkflowRepository(task)
    service = WorkflowControlService(repository, MemoryFiles(), MemoryQueue())

    cancelled = await service.cancel(task.id, expected_version=task.version)

    assert cancelled.status == TaskStatus.CANCELLED
    assert cancelled.current_stage == "cancelled"
    assert cancelled.version == task.version + 1

    with pytest.raises(DomainError) as error:
        await service.start(task.id)
    assert error.value.code == "TASK_CONFLICT"


@pytest.mark.asyncio
async def test_task_delete_cleans_external_assets_before_deleting_aggregate() -> None:
    task = _task()
    repository = MemoryWorkflowRepository(task)
    cleaned: list[UUID] = []

    async def cleanup(task_id: UUID) -> None:
        cleaned.append(task_id)

    service = TaskService(repository, before_delete=cleanup)

    await service.delete(task.id, expected_version=task.version)

    assert cleaned == [task.id]
    assert repository.task.status == TaskStatus.CANCELLED
    assert repository.task.current_stage == "deletion_requested"
    assert repository.deleted


@pytest.mark.asyncio
async def test_task_delete_preserves_database_record_when_asset_cleanup_fails() -> None:
    task = _task()
    repository = MemoryWorkflowRepository(task)
    attempts = 0

    async def cleanup(_: UUID) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise DomainError("FILE_CLEANUP_UNAVAILABLE", "Cleanup is still pending.")

    service = TaskService(repository, before_delete=cleanup)

    with pytest.raises(DomainError) as error:
        await service.delete(task.id, expected_version=task.version)

    assert error.value.code == "FILE_CLEANUP_UNAVAILABLE"
    assert repository.task.status == TaskStatus.CANCELLED
    assert repository.task.current_stage == "deletion_requested"
    assert not repository.deleted

    await service.delete(task.id)

    assert attempts == 2
    assert repository.deleted


@pytest.mark.asyncio
async def test_task_delete_reservation_prevents_a_concurrent_start() -> None:
    task = _task()
    repository = MemoryWorkflowRepository(task)
    workflow = WorkflowControlService(repository, MemoryFiles(), MemoryQueue())
    start_errors: list[DomainError] = []

    async def cleanup(_: UUID) -> None:
        try:
            await workflow.start(task.id)
        except DomainError as error:
            start_errors.append(error)

    service = TaskService(repository, before_delete=cleanup)
    await service.delete(task.id, expected_version=task.version)

    assert len(start_errors) == 1
    assert start_errors[0].code == "TASK_CONFLICT"
    assert repository.events == []
    assert repository.deleted


@pytest.mark.asyncio
async def test_cancelled_task_cannot_be_overwritten_by_late_workflow_projection() -> None:
    task = _task(TaskStatus.CANCELLED)
    repository = MemoryWorkflowRepository(task)

    await _persist_projection(
        repository,  # type: ignore[arg-type]
        task.id,
        {"final_markdown": "# Too late", "slides_content": []},
    )

    assert repository.task.status == TaskStatus.CANCELLED
    assert repository.task.version == task.version
