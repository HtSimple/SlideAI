from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from slideai.application.files.service import FileService
from slideai.application.files.validation import FileLimits
from slideai.core.errors import DomainError
from slideai.domain.files.models import FileStatus, SourceFile


class MemoryFileRepository:
    def __init__(self, task_id: UUID) -> None:
        self.task_id = task_id
        self.records: dict[UUID, SourceFile] = {}
        self.status = "DRAFT"
        self.max_files = 10

    async def add(self, source_file: SourceFile, *, max_files: int) -> None:
        if source_file.task_id != self.task_id:
            raise DomainError("TASK_NOT_FOUND", "Task was not found.")
        if len(self.records) >= min(max_files, self.max_files):
            raise DomainError("FILE_LIMIT_REACHED", "File limit reached.")
        self.records[source_file.id] = source_file
        self.status = "FILES_PROCESSING"

    async def ensure_task(self, task_id: UUID) -> bool:
        return task_id == self.task_id

    async def task_status(self, task_id: UUID) -> str | None:
        return self.status if task_id == self.task_id else None

    async def get(
        self, task_id: UUID, file_id: UUID, *, include_deleted: bool = False
    ) -> SourceFile | None:
        if task_id != self.task_id:
            return None
        source_file = self.records.get(file_id)
        if source_file and source_file.status == FileStatus.DELETED and not include_deleted:
            return None
        return source_file

    async def list(self, task_id: UUID) -> list[SourceFile]:
        if task_id != self.task_id:
            return []
        return [item for item in self.records.values() if item.status != FileStatus.DELETED]

    async def set_status(
        self,
        task_id: UUID,
        file_id: UUID,
        status: FileStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        chunk_count: int | None = None,
    ) -> SourceFile | None:
        source_file = await self.get(task_id, file_id)
        if source_file is None:
            return None
        updated = source_file.model_copy(
            update={
                "status": status,
                "error_code": error_code,
                "error_message": error_message,
                "chunk_count": chunk_count if chunk_count is not None else source_file.chunk_count,
                "updated_at": datetime.now(UTC),
            }
        )
        self.records[file_id] = updated
        return updated

    async def mark_deleted(self, task_id: UUID, file_id: UUID) -> SourceFile | None:
        source_file = await self.get(task_id, file_id)
        if source_file is None:
            return None
        deleted = source_file.model_copy(
            update={"status": FileStatus.DELETED, "deleted_at": datetime.now(UTC)}
        )
        self.records[file_id] = deleted
        return deleted

    async def chunk_ids(self, task_id: UUID, file_id: UUID) -> list[str]:
        return []

    async def delete_chunks(self, task_id: UUID, file_id: UUID) -> None:
        return None


class MemoryStorage:
    def __init__(self) -> None:
        self.files: dict[tuple[UUID, str], bytes] = {}

    def write(self, task_id: UUID, stored_name: str, content: bytes) -> None:
        self.files[(task_id, stored_name)] = content

    def read(self, task_id: UUID, stored_name: str) -> bytes:
        return self.files[(task_id, stored_name)]

    def delete(self, task_id: UUID, stored_name: str) -> None:
        self.files.pop((task_id, stored_name), None)


class MemoryQueue:
    def __init__(self) -> None:
        self.processing: list[tuple[UUID, UUID]] = []
        self.cleanup: list[tuple[UUID, UUID]] = []

    def enqueue_processing(self, task_id: UUID, file_id: UUID) -> None:
        self.processing.append((task_id, file_id))

    def enqueue_cleanup(self, task_id: UUID, file_id: UUID) -> None:
        self.cleanup.append((task_id, file_id))


@pytest.mark.asyncio
async def test_upload_stores_under_generated_name_and_queues_file() -> None:
    task_id = uuid4()
    repository = MemoryFileRepository(task_id)
    storage = MemoryStorage()
    queue = MemoryQueue()
    service = FileService(repository, storage, queue, limits=FileLimits())

    source_file = await service.upload(
        task_id,
        filename="quarterly.md",
        content_type="text/markdown; charset=utf-8",
        content=b"Revenue grew 12%.",
    )

    assert source_file.status == FileStatus.UPLOADED
    assert source_file.stored_name != source_file.original_name
    assert storage.files[(task_id, source_file.stored_name)] == b"Revenue grew 12%."
    assert queue.processing == [(task_id, source_file.id)]
    assert await service.list(task_id) == [source_file]


@pytest.mark.asyncio
async def test_upload_rejects_files_outside_task_scope_and_cleans_storage_on_db_error() -> None:
    task_id = uuid4()
    repository = MemoryFileRepository(task_id)
    repository.max_files = 0
    storage = MemoryStorage()
    service = FileService(repository, storage, MemoryQueue(), limits=FileLimits())

    with pytest.raises(DomainError) as raised:
        await service.upload(
            task_id,
            filename="notes.txt",
            content_type="text/plain",
            content=b"Notes",
        )

    assert raised.value.code == "FILE_LIMIT_REACHED"
    assert not storage.files


@pytest.mark.asyncio
async def test_retry_requires_failed_file_and_uses_requested_task_id() -> None:
    task_id = uuid4()
    other_task_id = uuid4()
    repository = MemoryFileRepository(task_id)
    service = FileService(repository, MemoryStorage(), MemoryQueue(), limits=FileLimits())
    source_file = await service.upload(
        task_id,
        filename="notes.txt",
        content_type="text/plain",
        content=b"Notes",
    )

    with pytest.raises(DomainError) as wrong_task:
        await service.retry(other_task_id, source_file.id)
    assert wrong_task.value.code == "FILE_NOT_FOUND"

    failed = await repository.set_status(
        task_id, source_file.id, FileStatus.FAILED, error_code="FILE_PARSE_FAILED"
    )
    assert failed is not None
    retried = await service.retry(task_id, source_file.id)

    assert retried.status == FileStatus.UPLOADED
