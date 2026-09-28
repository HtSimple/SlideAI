import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from slideai.core.config import get_settings
from slideai.domain.content.models import SlideProgress
from slideai.domain.tasks.models import RawRequirement, TaskRecord, TaskStatus, initial_complexity
from slideai.infrastructure.db.models import OutboxEventRow
from slideai.infrastructure.db.outbox_repository import SqlOutboxRepository
from slideai.infrastructure.db.session import create_engine
from slideai.infrastructure.db.task_repository import SqlTaskRepository
from slideai.infrastructure.redis.task_lock import TaskLock

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 when Compose dependencies are available",
)


@pytest.mark.asyncio
async def test_redis_lease_generations_increase_across_worker_takeovers() -> None:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    lock = TaskLock(redis, ttl_seconds=12)
    task_id = uuid4()
    try:
        first = await lock.acquire(task_id)
        assert first is not None
        assert await lock.acquire(task_id) is None
        assert await lock.release(task_id, first)

        successor = await lock.acquire(task_id, minimum_generation=first.generation)
        assert successor is not None
        assert successor.generation > first.generation
    finally:
        await redis.delete(lock.key(task_id), lock.generation_key(task_id))
        await redis.aclose()


@pytest.mark.asyncio
async def test_ambiguous_publish_retries_the_same_outbox_event_once() -> None:
    engine = create_engine(get_settings())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tasks = SqlTaskRepository(sessions)
    outbox = SqlOutboxRepository(sessions)
    task = _task()
    event_deliveries: list[object] = []
    started = task.model_copy(
        update={
            "status": TaskStatus.RUNNING,
            "current_stage": "requirement",
            "version": task.version + 1,
        }
    )

    def publish(event_id, event_type, aggregate_id, payload) -> None:
        event_deliveries.append((event_id, event_type, aggregate_id, payload))
        if len(event_deliveries) == 1:
            raise RuntimeError("Broker accepted event but response was lost.")

    try:
        await tasks.add(task)
        event_id = await tasks.update_with_outbox(
            started,
            expected_version=task.version,
            event_type="workflow.start",
            payload={},
        )

        assert await outbox.publish_pending(publish) == 0
        assert await outbox.publish_pending(publish) == 1
        assert await outbox.publish_pending(publish) == 0
        assert event_deliveries == [
            (event_id, "workflow.start", task.id, {}),
            (event_id, "workflow.start", task.id, {}),
        ]
    finally:
        async with sessions() as session, session.begin():
            await session.execute(
                delete(OutboxEventRow).where(OutboxEventRow.aggregate_id == task.id)
            )
        await tasks.delete(task.id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_new_workflow_event_fences_an_old_duplicate_delivery() -> None:
    engine = create_engine(get_settings())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tasks = SqlTaskRepository(sessions)
    task = _task()
    first_run = task.model_copy(
        update={
            "status": TaskStatus.RUNNING,
            "current_stage": "requirement",
            "version": task.version + 1,
        }
    )
    resumed = first_run.model_copy(update={"current_stage": "write_slides", "version": 4})

    try:
        await tasks.add(task)
        first_event = await tasks.update_with_outbox(
            first_run,
            expected_version=task.version,
            event_type="workflow.start",
            payload={},
        )
        assert await tasks.claim_workflow_lease(task.id, first_event, 1)
        await tasks.update_progress(
            task.id,
            SlideProgress(
                total_pages=3,
                completed_pages=0,
                total_batches=1,
                completed_batches=0,
            ),
            fencing_generation=1,
        )
        assert await tasks.is_active_workflow_event(task.id, first_event)
        second_event = await tasks.update_with_outbox(
            resumed,
            expected_version=first_run.version + 1,
            event_type="workflow.resume",
            payload={"resume": {"kind": "outline_confirmed"}},
        )

        assert not await tasks.is_active_workflow_event(task.id, first_event)
        assert await tasks.is_active_workflow_event(task.id, second_event)
    finally:
        async with sessions() as session, session.begin():
            await session.execute(
                delete(OutboxEventRow).where(OutboxEventRow.aggregate_id == task.id)
            )
        await tasks.delete(task.id)
        await engine.dispose()


def _task() -> TaskRecord:
    now = datetime.now(UTC)
    requirement = RawRequirement(topic="运行保障", target_page_count=3)
    return TaskRecord(
        id=uuid4(),
        name=requirement.topic,
        raw_requirement=requirement,
        model_preference={"mode": "auto"},
        complexity=initial_complexity(requirement),
        created_at=now,
        updated_at=now,
    )
