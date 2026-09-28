import asyncio
from typing import Any
from uuid import UUID

from slideai.application.files.embedding import create_embedding_gateway
from slideai.application.files.processor import FileProcessor
from slideai.core.config import get_settings
from slideai.infrastructure.db.file_repository import SqlFileRepository
from slideai.infrastructure.db.session import create_engine
from slideai.infrastructure.files.local_storage import LocalFileStorage
from slideai.infrastructure.vector.chroma_store import ChromaVectorStore
from slideai.workers.celery_app import celery_app


async def _process(task_id: UUID, file_id: UUID) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        processor = FileProcessor(
            SqlFileRepository(sessions),
            LocalFileStorage(settings.file_storage_root),
            create_embedding_gateway(settings),
            ChromaVectorStore(
                host=settings.chroma_host,
                port=settings.chroma_port,
                collection_name=settings.embedding_collection_name,
            ),
            max_extracted_chars=settings.max_extracted_chars_per_file,
            chunk_size=settings.chunk_size_tokens,
            chunk_overlap=settings.chunk_overlap_tokens,
            embedding_version=settings.embedding_version,
        )
        await processor.process(task_id, file_id)
    finally:
        await engine.dispose()


async def _cleanup(task_id: UUID, file_id: UUID) -> bool:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        processor = FileProcessor(
            SqlFileRepository(sessions),
            LocalFileStorage(settings.file_storage_root),
            create_embedding_gateway(settings),
            ChromaVectorStore(
                host=settings.chroma_host,
                port=settings.chroma_port,
                collection_name=settings.embedding_collection_name,
            ),
            max_extracted_chars=settings.max_extracted_chars_per_file,
            chunk_size=settings.chunk_size_tokens,
            chunk_overlap=settings.chunk_overlap_tokens,
            embedding_version=settings.embedding_version,
        )
        return await processor.cleanup_deleted_file(task_id, file_id)
    finally:
        await engine.dispose()


@celery_app.task(name="slideai.workers.process_source_file", acks_late=True)  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
def process_source_file(task_id: str, file_id: str) -> None:
    asyncio.run(_process(UUID(task_id), UUID(file_id)))


@celery_app.task(bind=True, name="slideai.workers.cleanup_deleted_file", max_retries=None)  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
def cleanup_deleted_file(task: Any, task_id: str, file_id: str) -> None:
    cleaned = asyncio.run(_cleanup(UUID(task_id), UUID(file_id)))
    if not cleaned:
        raise task.retry(countdown=5)
