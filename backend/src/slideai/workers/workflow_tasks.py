import asyncio
import logging
from asyncio import Event
from typing import Any, NoReturn
from uuid import UUID

from celery import Task
from psycopg import Error as PsycopgError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import async_sessionmaker

from slideai.application.content.progress import TaskProgressReporter
from slideai.application.files.embedding import create_embedding_gateway
from slideai.application.files.retrieval import DocumentRetriever
from slideai.application.models.factory import create_model_runtime
from slideai.core.config import get_settings
from slideai.infrastructure.db.file_repository import SqlFileRepository
from slideai.infrastructure.db.revision_repository import SqlRevisionRepository
from slideai.infrastructure.db.session import create_engine
from slideai.infrastructure.db.slide_repository import SqlSlideRepository
from slideai.infrastructure.db.task_repository import SqlTaskRepository
from slideai.infrastructure.redis.task_lock import TaskLock
from slideai.infrastructure.vector.chroma_store import ChromaVectorStore
from slideai.workers.celery_app import celery_app
from slideai.workflow.runtime import execute_persisted_workflow

logger = logging.getLogger("slideai.worker.workflow")


async def _run(
    task_id: UUID, resume: dict[str, Any] | None = None, *, event_id: UUID | None = None
) -> bool:
    settings = get_settings()
    engine = create_engine(settings)
    redis_client = Redis.from_url(  # pyright: ignore[reportUnknownMemberType]
        settings.redis_url, decode_responses=True
    )
    lock = TaskLock(redis_client, ttl_seconds=settings.workflow_lock_ttl_seconds)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        repository = SqlTaskRepository(sessions)
        task = await repository.get(task_id)
        if task is None or task.status.value != "RUNNING":
            return True
        minimum_generation = await repository.workflow_fencing_generation(task_id)
        lease = await lock.acquire(task_id, minimum_generation=minimum_generation)
        if lease is None:
            if await _delivery_is_current(repository, task_id, event_id):
                return False
            return True
        try:
            if not await repository.claim_workflow_lease(task_id, event_id, lease.generation):
                return True
            current = await repository.get(task_id)
            if current is None or current.status.value != "RUNNING":
                return True

            stop_renewal = Event()
            lock_lost = Event()
            renewal = asyncio.create_task(
                _renew_task_lock(
                    lock,
                    task_id,
                    lease.token,
                    settings.workflow_lock_ttl_seconds,
                    stop_renewal,
                    lock_lost,
                )
            )
            try:
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
                _, gateway = create_model_runtime(
                    settings, audit_writer=repository.record_model_call
                )

                async def cancellation_requested() -> bool:
                    latest = await repository.get(task_id)
                    return latest is None or latest.status.value == "CANCELLED"

                result = await execute_persisted_workflow(
                    settings,
                    repository,
                    gateway,
                    task_id,
                    resume=resume,
                    retriever=retriever,
                    slide_repository=SqlSlideRepository(
                        sessions, require_running=True, fencing_generation=lease.generation
                    ),
                    progress_reporter=TaskProgressReporter(
                        repository, fencing_generation=lease.generation
                    ),
                    revision_repository=SqlRevisionRepository(
                        sessions, fencing_generation=lease.generation
                    ),
                    chunk_id_loader=file_repository.list_chunk_ids,
                    cancellation_requested=cancellation_requested,
                    lock_lost=lock_lost,
                    workflow_fencing_generation=lease.generation,
                )
                if lock_lost.is_set() or result.get("workflow_lock_lost"):
                    return False
                return True
            finally:
                stop_renewal.set()
                await renewal
        finally:
            await lock.release(task_id, lease.token)
    except (DBAPIError, PsycopgError, RedisError, SQLAlchemyTimeoutError, OSError) as error:
        logger.warning(
            "workflow dependency unavailable; retrying delivery",
            extra={
                "event": "workflow.dependency_retry",
                "error_type": type(error).__name__,
            },
        )
        return False
    finally:
        await redis_client.aclose()
        await engine.dispose()


async def _delivery_is_current(
    repository: SqlTaskRepository, task_id: UUID, event_id: UUID | None
) -> bool:
    task = await repository.get(task_id)
    if task is None or task.status.value != "RUNNING":
        return False
    return event_id is None or await repository.is_active_workflow_event(task_id, event_id)


def _retry_workflow_delivery(task: Any) -> NoReturn:
    raise task.retry(countdown=2, max_retries=None)


async def _renew_task_lock(
    lock: TaskLock,
    task_id: UUID,
    token: str,
    ttl_seconds: int,
    stop: Event,
    lost: Event,
) -> None:
    interval = max(1, ttl_seconds // 3)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            pass
        try:
            renewed = await lock.renew(task_id, token)
        except Exception as error:
            logger.warning(
                "workflow lock renewal failed",
                extra={
                    "event": "workflow.lock_renewal_failed",
                    "error_type": type(error).__name__,
                },
            )
            lost.set()
            return
        if not renewed:
            lost.set()
            return


@celery_app.task(name="slideai.workers.start_workflow", bind=True, acks_late=True, max_retries=None)  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
def start_workflow(task: Task, task_id: str, event_id: str | None = None) -> None:
    retry = asyncio.run(_run(UUID(task_id), event_id=UUID(event_id) if event_id else None))
    if not retry:
        _retry_workflow_delivery(task)


@celery_app.task(  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
    name="slideai.workers.resume_workflow", bind=True, acks_late=True, max_retries=None
)
def resume_workflow(
    task: Task, task_id: str, resume: dict[str, Any], event_id: str | None = None
) -> None:
    retry = asyncio.run(_run(UUID(task_id), resume, event_id=UUID(event_id) if event_id else None))
    if not retry:
        _retry_workflow_delivery(task)
