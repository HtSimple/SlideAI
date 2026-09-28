from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from slideai.application.files.validation import FileLimits, validate_upload
from slideai.core.errors import DomainError
from slideai.domain.files.models import DocumentChunk, FileStatus, SourceFile


class FileRepository(Protocol):
    async def add(self, source_file: SourceFile, *, max_files: int) -> None: ...
    async def ensure_task(self, task_id: UUID) -> bool: ...
    async def task_status(self, task_id: UUID) -> str | None: ...
    async def get(
        self, task_id: UUID, file_id: UUID, *, include_deleted: bool = False
    ) -> SourceFile | None: ...
    async def list(self, task_id: UUID) -> list[SourceFile]: ...
    async def replace_chunks(
        self, task_id: UUID, file_id: UUID, chunks: list[DocumentChunk]
    ) -> None: ...
    async def set_status(
        self,
        task_id: UUID,
        file_id: UUID,
        status: FileStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        chunk_count: int | None = None,
    ) -> SourceFile | None: ...
    async def mark_deleted(self, task_id: UUID, file_id: UUID) -> SourceFile | None: ...
    async def chunk_ids(self, task_id: UUID, file_id: UUID) -> list[str]: ...
    async def delete_chunks(self, task_id: UUID, file_id: UUID) -> None: ...


class FileStorage(Protocol):
    def write(self, task_id: UUID, stored_name: str, content: bytes) -> None: ...
    def read(self, task_id: UUID, stored_name: str) -> bytes: ...
    def delete(self, task_id: UUID, stored_name: str) -> None: ...


class FileQueue(Protocol):
    def enqueue_processing(self, task_id: UUID, file_id: UUID) -> None: ...
    def enqueue_cleanup(self, task_id: UUID, file_id: UUID) -> None: ...


class FileCleanup(Protocol):
    async def cleanup_deleted_file(self, task_id: UUID, file_id: UUID) -> bool: ...


class FileService:
    def __init__(
        self,
        repository: FileRepository,
        storage: FileStorage,
        queue: FileQueue,
        *,
        limits: FileLimits,
        cleanup: FileCleanup | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.queue = queue
        self.limits = limits
        self.cleanup = cleanup
        self.clock = clock or (lambda: datetime.now(UTC))

    async def upload(
        self,
        task_id: UUID,
        *,
        filename: str | None,
        content_type: str | None,
        content: bytes,
    ) -> SourceFile:
        if len(content) > self.limits.max_file_size_bytes:
            raise DomainError("FILE_TOO_LARGE", "The file exceeds the configured size limit.")
        upload = validate_upload(
            filename=filename,
            content_type=content_type,
            content=content,
            limits=self.limits,
        )
        file_id = uuid4()
        timestamp = self.clock()
        source_file = SourceFile(
            id=file_id,
            task_id=task_id,
            original_name=upload.original_name,
            stored_name=f"{uuid4()}.{upload.extension}",
            mime_type=upload.mime_type,
            extension=upload.extension,
            size_bytes=upload.size_bytes,
            sha256=upload.sha256,
            status=FileStatus.UPLOADED,
            created_at=timestamp,
            updated_at=timestamp,
        )
        await asyncio.to_thread(self.storage.write, task_id, source_file.stored_name, content)
        try:
            await self.repository.add(source_file, max_files=self.limits.max_files_per_task)
        except BaseException:
            await asyncio.to_thread(self.storage.delete, task_id, source_file.stored_name)
            raise

        try:
            self.queue.enqueue_processing(task_id, file_id)
        except Exception:
            failed = await self.repository.set_status(
                task_id,
                file_id,
                FileStatus.FAILED,
                error_code="FILE_QUEUE_UNAVAILABLE",
                error_message="The file could not be queued for processing. Retry it to continue.",
            )
            return failed or source_file
        return source_file

    async def list(self, task_id: UUID) -> list[SourceFile]:
        if not await self.repository.ensure_task(task_id):
            raise DomainError("TASK_NOT_FOUND", "Task was not found.")
        return await self.repository.list(task_id)

    async def ensure_task(self, task_id: UUID) -> None:
        if not await self.repository.ensure_task(task_id):
            raise DomainError("TASK_NOT_FOUND", "Task was not found.")

    async def retry(self, task_id: UUID, file_id: UUID) -> SourceFile:
        source_file = await self.repository.get(task_id, file_id)
        if source_file is None:
            raise DomainError("FILE_NOT_FOUND", "File was not found for this task.")
        if source_file.status != FileStatus.FAILED:
            raise DomainError("FILE_CONFLICT", "Only failed files can be retried.")
        queued = await self.repository.set_status(task_id, file_id, FileStatus.UPLOADED)
        if queued is None:
            raise DomainError("FILE_NOT_FOUND", "File was not found for this task.")
        try:
            self.queue.enqueue_processing(task_id, file_id)
        except Exception as error:
            await self.repository.set_status(
                task_id,
                file_id,
                FileStatus.FAILED,
                error_code="FILE_QUEUE_UNAVAILABLE",
                error_message="The file could not be queued for processing. Retry it to continue.",
            )
            raise DomainError(
                "FILE_QUEUE_UNAVAILABLE", "The file could not be queued for processing."
            ) from error
        return queued

    async def remove(self, task_id: UUID, file_id: UUID) -> SourceFile:
        source_file = await self.repository.mark_deleted(task_id, file_id)
        if source_file is None:
            raise DomainError("FILE_NOT_FOUND", "File was not found for this task.")
        try:
            self.queue.enqueue_cleanup(task_id, file_id)
        except Exception as error:
            try:
                cleaned = (
                    await self.cleanup.cleanup_deleted_file(task_id, file_id)
                    if self.cleanup is not None
                    else False
                )
            except Exception as cleanup_error:
                raise DomainError(
                    "FILE_CLEANUP_UNAVAILABLE",
                    "The file was marked removed but cleanup could not be completed.",
                ) from cleanup_error
            if not cleaned:
                raise DomainError(
                    "FILE_CLEANUP_UNAVAILABLE",
                    "The file was marked removed; cleanup waits for the active task to finish.",
                ) from error
        return source_file
