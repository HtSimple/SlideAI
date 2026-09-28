import asyncio
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from slideai.application.content.progress import TaskProgressReporter
from slideai.application.files.embedding import create_embedding_gateway
from slideai.application.files.retrieval import DocumentRetriever
from slideai.application.models.factory import create_model_runtime
from slideai.core.config import get_settings
from slideai.infrastructure.db.file_repository import SqlFileRepository
from slideai.infrastructure.db.session import create_engine
from slideai.infrastructure.db.slide_repository import SqlSlideRepository
from slideai.infrastructure.db.task_repository import SqlTaskRepository
from slideai.infrastructure.vector.chroma_store import ChromaVectorStore
from slideai.workers.celery_app import celery_app
from slideai.workflow.runtime import execute_persisted_workflow


async def _run(task_id: UUID, resume: dict[str, Any] | None = None) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        repository = SqlTaskRepository(sessions)
        file_repository = SqlFileRepository(sessions)
        retriever = DocumentRetriever(
            create_embedding_gateway(settings),
            ChromaVectorStore(
                host=settings.chroma_host,
                port=settings.chroma_port,
                collection_name=settings.embedding_collection_name,
            ),
            file_repository,
            default_top_k=settings.retrieval_top_k,
        )
        _, gateway = create_model_runtime(settings, audit_writer=repository.record_model_call)
        await execute_persisted_workflow(
            settings,
            repository,
            gateway,
            task_id,
            resume=resume,
            retriever=retriever,
            slide_repository=SqlSlideRepository(sessions),
            progress_reporter=TaskProgressReporter(repository),
        )
    finally:
        await engine.dispose()


@celery_app.task(name="slideai.workers.start_workflow", acks_late=True)  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
def start_workflow(task_id: str) -> None:
    asyncio.run(_run(UUID(task_id)))


@celery_app.task(name="slideai.workers.resume_workflow", acks_late=True)  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
def resume_workflow(task_id: str, resume: dict[str, Any]) -> None:
    asyncio.run(_run(UUID(task_id), resume))
