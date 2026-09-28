import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker

from slideai.core.config import get_settings
from slideai.infrastructure.celery_queue.workflow_queue import CeleryWorkflowQueue
from slideai.infrastructure.db.outbox_repository import SqlOutboxRepository
from slideai.infrastructure.db.session import create_engine
from slideai.workers.celery_app import celery_app


async def _publish_pending() -> int:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        repository = SqlOutboxRepository(sessions)
        return await repository.publish_pending(CeleryWorkflowQueue().publish_event)
    finally:
        await engine.dispose()


@celery_app.task(name="slideai.workers.publish_outbox")  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
def publish_outbox() -> int:
    return asyncio.run(_publish_pending())
