import asyncio
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from slideai.application.models.gateway import ModelGateway, OpenAICompatibleProvider
from slideai.core.config import get_settings
from slideai.domain.models.catalog import ModelCatalog
from slideai.infrastructure.db.session import create_engine
from slideai.infrastructure.db.task_repository import SqlTaskRepository
from slideai.workers.celery_app import celery_app
from slideai.workflow.runtime import execute_persisted_workflow


async def _run(task_id: UUID, resume: dict[str, Any] | None = None) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        repository = SqlTaskRepository(sessions)
        catalog = ModelCatalog.from_yaml(settings.model_catalog_path)
        gateway = ModelGateway(
            model_catalog=catalog,
            providers={"openai_compatible": OpenAICompatibleProvider()},
            audit_writer=repository.record_model_call,
            retries=settings.model_retry_count,
        )
        await execute_persisted_workflow(
            settings,
            repository,
            gateway,
            task_id,
            resume=resume,
        )
    finally:
        await engine.dispose()


@celery_app.task(name="slideai.workers.start_workflow", acks_late=True)  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
def start_workflow(task_id: str) -> None:
    asyncio.run(_run(UUID(task_id)))


@celery_app.task(name="slideai.workers.resume_workflow", acks_late=True)  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
def resume_workflow(task_id: str, resume: dict[str, Any]) -> None:
    asyncio.run(_run(UUID(task_id), resume))
