import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from slideai.application.files.embedding import create_embedding_gateway
from slideai.application.files.processor import FileProcessor
from slideai.application.files.retrieval import DocumentRetriever
from slideai.application.files.service import FileService
from slideai.application.files.validation import FileLimits
from slideai.core.config import get_settings
from slideai.domain.tasks.models import (
    ModelPreference,
    RawRequirement,
    TaskRecord,
    initial_complexity,
)
from slideai.infrastructure.db.file_repository import SqlFileRepository
from slideai.infrastructure.db.session import create_engine
from slideai.infrastructure.db.task_repository import SqlTaskRepository
from slideai.infrastructure.files.local_storage import LocalFileStorage
from slideai.infrastructure.vector.chroma_store import ChromaVectorStore


class IntegrationQueue:
    def enqueue_processing(self, task_id, file_id):  # type: ignore[no-untyped-def]
        return None

    def enqueue_cleanup(self, task_id, file_id):  # type: ignore[no-untyped-def]
        return None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upload_process_and_citation_round_trip_postgres_and_chroma() -> None:
    if os.getenv("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_INTEGRATION_TESTS=1 when Compose dependencies are available")

    settings = get_settings()
    engine = create_engine(settings)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tasks = SqlTaskRepository(sessions)
    files = SqlFileRepository(sessions)
    storage = LocalFileStorage(settings.file_storage_root)
    queue = IntegrationQueue()
    embedding = create_embedding_gateway(settings)
    vectors = ChromaVectorStore(
        host=settings.chroma_host,
        port=settings.chroma_port,
        collection_name=f"slideai_test_{uuid4().hex}",
    )
    processor = FileProcessor(
        files,
        storage,
        embedding,
        vectors,
        max_extracted_chars=settings.max_extracted_chars_per_file,
        chunk_size=settings.chunk_size_tokens,
        chunk_overlap=settings.chunk_overlap_tokens,
        embedding_version=settings.embedding_version,
    )
    now = datetime.now(UTC)
    requirement = RawRequirement(topic="Industry outlook", target_page_count=12)
    task = TaskRecord(
        name=requirement.topic,
        raw_requirement=requirement,
        model_preference=ModelPreference(),
        complexity=initial_complexity(requirement),
        created_at=now,
        updated_at=now,
    )
    await tasks.add(task)
    source_file_id = None
    try:
        service = FileService(
            files,
            storage,
            queue,
            limits=FileLimits(),
            cleanup=processor,
        )
        source_file = await service.upload(
            task.id,
            filename="industry-outlook.txt",
            content_type="text/plain",
            content=b"Industry outlook. Revenue growth reached 12 percent this year.",
        )
        source_file_id = source_file.id

        await processor.process(task.id, source_file.id)

        ready_file = await files.get(task.id, source_file.id)
        assert ready_file is not None
        assert ready_file.status.value == "READY", (
            f"status={ready_file.status.value}, code={ready_file.error_code}"
        )
        assert ready_file.chunk_count > 0
        assert await files.chunk_ids(task.id, source_file.id)

        retriever = DocumentRetriever(embedding, vectors, files, default_top_k=6)
        citations = await retriever.search(task.id, "revenue growth")
        assert citations
        assert citations[0].file_id == source_file.id
        assert citations[0].display_name == "industry-outlook.txt"
        assert "growth" in citations[0].content.casefold()

        await service.remove(task.id, source_file.id)
        assert await processor.cleanup_deleted_file(task.id, source_file.id)
        assert await files.chunk_ids(task.id, source_file.id) == []
    finally:
        if source_file_id is not None:
            await processor.cleanup_deleted_file(task.id, source_file_id)
        await tasks.delete(task.id)
        await vectors.delete_collection()
        await engine.dispose()
