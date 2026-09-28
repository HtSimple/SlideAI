import asyncio
import logging
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from slideai.application.files.embedding import EmbeddingGateway
from slideai.application.files.service import FileRepository, FileStorage
from slideai.core.errors import DomainError
from slideai.domain.files.models import DocumentChunk, FileStatus
from slideai.infrastructure.documents.chunking import chunk_located_text
from slideai.infrastructure.documents.parsers import parse_document

logger = logging.getLogger("slideai.files")


class VectorStore(Protocol):
    async def upsert(
        self,
        *,
        chunks: list[dict[str, object]],
        embeddings: list[list[float]],
    ) -> None: ...

    async def delete_by_ids(self, ids: list[str]) -> None: ...

    async def delete_file(self, *, task_id: str, file_id: str) -> None: ...


class FileProcessor:
    def __init__(
        self,
        repository: FileRepository,
        storage: FileStorage,
        embedding: EmbeddingGateway,
        vector_store: VectorStore,
        *,
        max_extracted_chars: int = 2_000_000,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
        embedding_version: str = "v1",
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.embedding = embedding
        self.vector_store = vector_store
        self.max_extracted_chars = max_extracted_chars
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.embedding_version = embedding_version

    async def process(self, task_id: UUID, file_id: UUID) -> None:
        source_file = await self.repository.get(task_id, file_id)
        if source_file is None or source_file.status == FileStatus.READY:
            return
        try:
            if not await self._set_status(task_id, file_id, FileStatus.PARSING):
                return
            content = await asyncio.to_thread(self.storage.read, task_id, source_file.stored_name)
            located = parse_document(
                source_file.extension,
                content,
                max_chars=self.max_extracted_chars,
            )
            if not await self._set_status(task_id, file_id, FileStatus.CHUNKING):
                return
            chunked = chunk_located_text(
                located,
                chunk_size=self.chunk_size,
                overlap=self.chunk_overlap,
            )
            if not chunked:
                raise DomainError("NO_EXTRACTABLE_TEXT", "No readable text was found in this file.")
            if not await self._set_status(task_id, file_id, FileStatus.EMBEDDING):
                return
            vectors = await self.embedding.embed([chunk.content for chunk in chunked])
            records = [
                DocumentChunk(
                    id=uuid5(NAMESPACE_URL, f"{file_id}:{ordinal}"),
                    task_id=task_id,
                    file_id=file_id,
                    ordinal=ordinal,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    page_number=chunk.page_number,
                    section_title=chunk.section_title,
                    paragraph_index=chunk.paragraph_index,
                    embedding_model=self.embedding.model_name,
                    embedding_version=self.embedding_version,
                )
                for ordinal, chunk in enumerate(chunked)
            ]
            await self.repository.replace_chunks(task_id, file_id, records)
            await self.vector_store.upsert(
                chunks=[_vector_record(record) for record in records],
                embeddings=vectors,
            )
            if not await self._set_status(
                task_id,
                file_id,
                FileStatus.READY,
                chunk_count=len(records),
            ):
                await self.cleanup_deleted_file(task_id, file_id)
        except DomainError as error:
            await self._mark_failed(task_id, file_id, error.code, error.message)
        except Exception as error:
            logger.warning(
                "source file processing failed",
                extra={
                    "event": "files.processing_failed",
                    "task_id": str(task_id),
                    "file_id": str(file_id),
                    "error_type": type(error).__name__,
                },
            )
            await self._mark_failed(
                task_id,
                file_id,
                "FILE_PROCESSING_FAILED",
                "The file could not be processed. Remove it or retry processing.",
            )

    async def cleanup_deleted_file(self, task_id: UUID, file_id: UUID) -> bool:
        source_file = await self.repository.get(task_id, file_id, include_deleted=True)
        if source_file is None or source_file.status != FileStatus.DELETED:
            return True
        if await self._task_is_running(task_id):
            return False
        chunk_ids = await self.repository.chunk_ids(task_id, file_id)
        if chunk_ids:
            await self.vector_store.delete_by_ids(chunk_ids)
        await self.vector_store.delete_file(task_id=str(task_id), file_id=str(file_id))
        await asyncio.to_thread(self.storage.delete, task_id, source_file.stored_name)
        await self.repository.delete_chunks(task_id, file_id)
        return True

    async def _set_status(
        self,
        task_id: UUID,
        file_id: UUID,
        status: FileStatus,
        *,
        chunk_count: int | None = None,
    ) -> bool:
        updated = await self.repository.set_status(
            task_id,
            file_id,
            status,
            chunk_count=chunk_count,
        )
        return updated is not None

    async def _mark_failed(
        self, task_id: UUID, file_id: UUID, error_code: str, error_message: str
    ) -> None:
        source_file = await self.repository.get(task_id, file_id, include_deleted=True)
        if source_file is None or source_file.status == FileStatus.DELETED:
            await self.cleanup_deleted_file(task_id, file_id)
            return
        try:
            chunk_ids = await self.repository.chunk_ids(task_id, file_id)
            if chunk_ids:
                await self.vector_store.delete_by_ids(chunk_ids)
                await self.repository.delete_chunks(task_id, file_id)
        except Exception as cleanup_error:
            logger.warning(
                "failed document index cleanup will be retried",
                extra={
                    "event": "files.index_cleanup_failed",
                    "task_id": str(task_id),
                    "file_id": str(file_id),
                    "error_type": type(cleanup_error).__name__,
                },
            )
        await self.repository.set_status(
            task_id,
            file_id,
            FileStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
            chunk_count=0,
        )

    async def _task_is_running(self, task_id: UUID) -> bool:
        status = await self.repository.task_status(task_id)
        return status in {
            "FILES_PROCESSING",
            "RUNNING",
            "WAITING_REQUIREMENT_INPUT",
            "WAITING_OUTLINE_CONFIRMATION",
            "WAITING_USER_FEEDBACK",
        }


def _vector_record(chunk: DocumentChunk) -> dict[str, object]:
    return {
        "id": str(chunk.id),
        "task_id": str(chunk.task_id),
        "file_id": str(chunk.file_id),
        "content": chunk.content,
        "page_number": chunk.page_number,
        "section_title": chunk.section_title,
        "paragraph_index": chunk.paragraph_index,
        "embedding_model": chunk.embedding_model,
        "embedding_version": chunk.embedding_version,
    }
