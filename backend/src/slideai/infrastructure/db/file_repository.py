from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from slideai.core.errors import DomainError
from slideai.domain.files.models import DocumentChunk, FileStatus, SourceFile
from slideai.infrastructure.db.models import (
    DocumentChunkRow,
    GenerationTaskRow,
    SourceFileRow,
)

_EDITABLE_TASK_STATUSES = {"DRAFT", "READY", "FILES_PROCESSING"}
_PENDING_FILE_STATUSES = {"UPLOADED", "PARSING", "CHUNKING", "EMBEDDING"}


class SqlFileRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def add(self, source_file: SourceFile, *, max_files: int) -> None:
        async with self.sessions() as session, session.begin():
            task = await session.scalar(
                select(GenerationTaskRow)
                .where(GenerationTaskRow.id == source_file.task_id)
                .with_for_update()
            )
            if task is None:
                raise DomainError("TASK_NOT_FOUND", "Task was not found.")
            if task.status not in _EDITABLE_TASK_STATUSES:
                raise DomainError(
                    "TASK_CONFLICT", "Files cannot be changed while this task is running."
                )

            active_count = await session.scalar(
                select(func.count())
                .select_from(SourceFileRow)
                .where(
                    SourceFileRow.task_id == source_file.task_id,
                    SourceFileRow.deleted_at.is_(None),
                )
            )
            if (active_count or 0) >= max_files:
                raise DomainError("FILE_LIMIT_REACHED", "This task has reached its file limit.")

            duplicate = await session.scalar(
                select(SourceFileRow.id).where(
                    SourceFileRow.task_id == source_file.task_id,
                    SourceFileRow.sha256 == source_file.sha256,
                    SourceFileRow.deleted_at.is_(None),
                )
            )
            if duplicate is not None:
                raise DomainError("FILE_DUPLICATE", "This file is already attached to the task.")

            session.add(_source_file_row(source_file))
            task.status = "FILES_PROCESSING"
            task.current_stage = "files"
            task.version += 1
            task.updated_at = datetime.now(UTC)

    async def ensure_task(self, task_id: UUID) -> bool:
        async with self.sessions() as session:
            return (
                await session.scalar(
                    select(GenerationTaskRow.id).where(GenerationTaskRow.id == task_id)
                )
            ) is not None

    async def task_status(self, task_id: UUID) -> str | None:
        async with self.sessions() as session:
            return await session.scalar(
                select(GenerationTaskRow.status).where(GenerationTaskRow.id == task_id)
            )

    async def get(
        self, task_id: UUID, file_id: UUID, *, include_deleted: bool = False
    ) -> SourceFile | None:
        async with self.sessions() as session:
            statement = select(SourceFileRow).where(
                SourceFileRow.task_id == task_id,
                SourceFileRow.id == file_id,
            )
            if not include_deleted:
                statement = statement.where(SourceFileRow.deleted_at.is_(None))
            row = await session.scalar(statement)
            return _source_file(row) if row else None

    async def list(self, task_id: UUID) -> list[SourceFile]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(SourceFileRow)
                    .where(SourceFileRow.task_id == task_id, SourceFileRow.deleted_at.is_(None))
                    .order_by(SourceFileRow.created_at, SourceFileRow.id)
                )
            ).all()
            return [_source_file(row) for row in rows]

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
        async with self.sessions() as session, session.begin():
            row = await session.scalar(
                select(SourceFileRow)
                .where(
                    SourceFileRow.task_id == task_id,
                    SourceFileRow.id == file_id,
                    SourceFileRow.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if row is None:
                return None
            row.status = status.value
            row.error_code = error_code
            row.error_message = error_message
            if chunk_count is not None:
                row.chunk_count = chunk_count
            row.updated_at = datetime.now(UTC)

            task = await session.get(GenerationTaskRow, task_id, with_for_update=True)
            if task is not None and task.status in _EDITABLE_TASK_STATUSES:
                statuses = list(
                    (
                        await session.scalars(
                            select(SourceFileRow.status).where(
                                SourceFileRow.task_id == task_id,
                                SourceFileRow.deleted_at.is_(None),
                            )
                        )
                    ).all()
                )
                task.status = (
                    "FILES_PROCESSING"
                    if any(file_status in _PENDING_FILE_STATUSES for file_status in statuses)
                    else "READY"
                    if any(file_status == FileStatus.READY.value for file_status in statuses)
                    else "DRAFT"
                )
                task.current_stage = None if task.status != "FILES_PROCESSING" else "files"
                task.version += 1
                task.updated_at = datetime.now(UTC)
            return _source_file(row)

    async def mark_deleted(self, task_id: UUID, file_id: UUID) -> SourceFile | None:
        async with self.sessions() as session, session.begin():
            row = await session.scalar(
                select(SourceFileRow)
                .where(
                    SourceFileRow.task_id == task_id,
                    SourceFileRow.id == file_id,
                    SourceFileRow.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if row is None:
                return None
            row.status = FileStatus.DELETED.value
            now = datetime.now(UTC)
            row.deleted_at = now
            row.updated_at = now

            task = await session.get(GenerationTaskRow, task_id, with_for_update=True)
            if task is not None and task.status in _EDITABLE_TASK_STATUSES:
                remaining_statuses = list(
                    (
                        await session.scalars(
                            select(SourceFileRow.status).where(
                                SourceFileRow.task_id == task_id,
                                SourceFileRow.id != file_id,
                                SourceFileRow.deleted_at.is_(None),
                            )
                        )
                    ).all()
                )
                task.status = (
                    "FILES_PROCESSING"
                    if any(item in _PENDING_FILE_STATUSES for item in remaining_statuses)
                    else "READY"
                    if any(item == FileStatus.READY.value for item in remaining_statuses)
                    else "DRAFT"
                )
                task.current_stage = None if task.status != "FILES_PROCESSING" else "files"
                task.version += 1
                task.updated_at = datetime.now(UTC)
            return _source_file(row)

    async def replace_chunks(
        self, task_id: UUID, file_id: UUID, chunks: list[DocumentChunk]
    ) -> None:
        async with self.sessions() as session, session.begin():
            await session.execute(
                delete(DocumentChunkRow).where(
                    DocumentChunkRow.task_id == task_id,
                    DocumentChunkRow.file_id == file_id,
                )
            )
            session.add_all([_chunk_row(chunk) for chunk in chunks])

    async def chunk_ids(self, task_id: UUID, file_id: UUID) -> list[str]:
        async with self.sessions() as session:
            ids = (
                await session.scalars(
                    select(DocumentChunkRow.id).where(
                        DocumentChunkRow.task_id == task_id,
                        DocumentChunkRow.file_id == file_id,
                    )
                )
            ).all()
            return [str(chunk_id) for chunk_id in ids]

    async def file_names(self, task_id: UUID, file_ids: list[UUID]) -> dict[str, str]:
        if not file_ids:
            return {}
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(SourceFileRow.id, SourceFileRow.original_name).where(
                        SourceFileRow.task_id == task_id,
                        SourceFileRow.id.in_(file_ids),
                        SourceFileRow.deleted_at.is_(None),
                        SourceFileRow.status == FileStatus.READY.value,
                    )
                )
            ).all()
            return {str(file_id): name for file_id, name in rows}

    async def delete_chunks(self, task_id: UUID, file_id: UUID) -> None:
        async with self.sessions() as session, session.begin():
            await session.execute(
                delete(DocumentChunkRow).where(
                    DocumentChunkRow.task_id == task_id,
                    DocumentChunkRow.file_id == file_id,
                )
            )


def _source_file_row(source_file: SourceFile) -> SourceFileRow:
    return SourceFileRow(
        id=source_file.id,
        task_id=source_file.task_id,
        original_name=source_file.original_name,
        stored_name=source_file.stored_name,
        mime_type=source_file.mime_type,
        extension=source_file.extension,
        size_bytes=source_file.size_bytes,
        sha256=source_file.sha256,
        status=source_file.status.value,
        error_code=source_file.error_code,
        error_message=source_file.error_message,
        chunk_count=source_file.chunk_count,
        created_at=source_file.created_at,
        updated_at=source_file.updated_at,
    )


def _source_file(row: SourceFileRow) -> SourceFile:
    return SourceFile.model_validate(
        {
            "id": row.id,
            "task_id": row.task_id,
            "original_name": row.original_name,
            "stored_name": row.stored_name,
            "mime_type": row.mime_type,
            "extension": row.extension,
            "size_bytes": row.size_bytes,
            "sha256": row.sha256,
            "status": row.status,
            "error_code": row.error_code,
            "error_message": row.error_message,
            "chunk_count": row.chunk_count,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "deleted_at": row.deleted_at,
        }
    )


def _chunk_row(chunk: DocumentChunk) -> DocumentChunkRow:
    return DocumentChunkRow(
        id=chunk.id,
        task_id=chunk.task_id,
        file_id=chunk.file_id,
        ordinal=chunk.ordinal,
        content=chunk.content,
        token_count=chunk.token_count,
        page_number=chunk.page_number,
        section_title=chunk.section_title,
        paragraph_index=chunk.paragraph_index,
        embedding_model=chunk.embedding_model,
        embedding_version=chunk.embedding_version,
    )
