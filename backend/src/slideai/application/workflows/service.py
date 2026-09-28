from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from slideai.application.workflows.ports import WorkflowQueue
from slideai.core.errors import DomainError
from slideai.domain.files.models import FileStatus, SourceFile
from slideai.domain.tasks.models import TaskRecord, TaskStatus


class TaskRepository(Protocol):
    async def get(self, task_id: UUID) -> TaskRecord | None: ...

    async def update(self, task: TaskRecord, *, expected_version: int) -> None: ...


class FileService(Protocol):
    async def list(self, task_id: UUID) -> list[SourceFile]: ...


class WorkflowControlService:
    def __init__(
        self,
        tasks: TaskRepository,
        files: FileService,
        queue: WorkflowQueue,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.tasks = tasks
        self.files = files
        self.queue = queue
        self.clock = clock or (lambda: datetime.now(UTC))

    async def start(self, task_id: UUID) -> TaskRecord:
        task = await self._get(task_id)
        if task.status not in {TaskStatus.DRAFT, TaskStatus.READY, TaskStatus.FAILED_RETRYABLE}:
            raise DomainError("TASK_CONFLICT", "This task cannot be started in its current state.")
        source_files = await self.files.list(task_id)
        if any(source_file.status != FileStatus.READY for source_file in source_files):
            raise DomainError(
                "FILES_NOT_READY", "Remove failed files or wait for all files to finish processing."
            )

        updated = task.model_copy(
            update={
                "status": TaskStatus.RUNNING,
                "current_stage": "requirement",
                "version": task.version + 1,
                "updated_at": self.clock(),
            }
        )
        await self.tasks.update(updated, expected_version=task.version)
        try:
            self.queue.enqueue_start(task_id)
        except Exception as error:
            raise DomainError(
                "WORKFLOW_QUEUE_UNAVAILABLE", "The task could not be queued for processing."
            ) from error
        return updated

    async def _get(self, task_id: UUID) -> TaskRecord:
        task = await self.tasks.get(task_id)
        if task is None:
            raise DomainError("TASK_NOT_FOUND", "Task was not found.")
        return task
