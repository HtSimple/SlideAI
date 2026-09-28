import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from slideai.workers.workflow_tasks import _renew_task_lock


class RedisUnavailableLock:
    async def renew(self, task_id: UUID, token: str) -> bool:
        raise ConnectionError("redis unavailable")


@pytest.mark.asyncio
async def test_lock_renewal_failure_marks_workflow_unsafe_to_continue(monkeypatch) -> None:
    async def expire_immediately(*_: object, **__: object) -> None:
        pending = _[0]
        close = getattr(pending, "close", None)
        if callable(close):
            close()
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", expire_immediately)
    stop = asyncio.Event()
    lost = asyncio.Event()

    await _renew_task_lock(
        RedisUnavailableLock(),
        UUID("70f25504-e0ae-43e0-a85c-7b0d38469c73"),
        "lease-token",
        5,
        stop,
        lost,
    )

    assert lost.is_set()


@pytest.mark.asyncio
async def test_stale_duplicate_delivery_is_discarded_after_acquiring_task_lock(monkeypatch) -> None:
    from slideai.infrastructure.redis.task_lock import TaskLease
    from slideai.workers import workflow_tasks

    task_id = UUID("5b2dcd63-b776-4c77-a374-3d24ef0b6297")
    event_id = UUID("1f7a57d5-0e02-4501-b11a-93aa184acfac")
    current_event_id = UUID("fe4f5d19-740e-4a3b-8dc8-cdff8b20c257")
    operations: list[str] = []
    workflow_calls: list[UUID] = []

    class FakeRedis:
        async def aclose(self) -> None:
            operations.append("redis_closed")

    class FakeEngine:
        async def dispose(self) -> None:
            operations.append("engine_disposed")

    class FakeRepository:
        def __init__(self, _: object) -> None:
            pass

        async def get(self, _: UUID) -> SimpleNamespace:
            operations.append("task_read")
            return SimpleNamespace(status=SimpleNamespace(value="RUNNING"))

        async def is_active_workflow_event(self, _: UUID, received: UUID) -> bool:
            operations.append("event_read")
            return received == current_event_id

        async def workflow_fencing_generation(self, _: UUID) -> int:
            return 0

        async def claim_workflow_lease(
            self, _: UUID, received: UUID | None, generation: int
        ) -> bool:
            operations.append("claim")
            operations.append("event_read")
            return received == current_event_id and generation == 3

    class FakeLock:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def acquire(self, _: UUID, **__: object) -> TaskLease:
            operations.append("lock_acquired")
            return TaskLease("lease", 3)

        async def release(self, *_: object) -> bool:
            return True

        async def renew(self, *_: object) -> bool:
            return True

    redis = FakeRedis()
    engine = FakeEngine()
    monkeypatch.setattr(
        workflow_tasks,
        "get_settings",
        lambda: SimpleNamespace(redis_url="redis://unused", workflow_lock_ttl_seconds=60),
    )
    monkeypatch.setattr(workflow_tasks, "create_engine", lambda _: engine)
    monkeypatch.setattr(workflow_tasks, "async_sessionmaker", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(workflow_tasks.Redis, "from_url", lambda *_args, **_kwargs: redis)
    monkeypatch.setattr(workflow_tasks, "SqlTaskRepository", FakeRepository)
    monkeypatch.setattr(workflow_tasks, "TaskLock", FakeLock)

    async def execute(*_: object, **__: object) -> None:
        workflow_calls.append(task_id)

    monkeypatch.setattr(workflow_tasks, "execute_persisted_workflow", execute)

    assert await workflow_tasks._run(task_id, event_id=event_id) is True

    assert workflow_calls == []
    assert operations.index("lock_acquired") < operations.index("event_read")
    assert operations.count("task_read") == 1


@pytest.mark.asyncio
async def test_current_delivery_is_retried_when_another_worker_holds_the_lock(monkeypatch) -> None:
    from slideai.workers import workflow_tasks

    task_id = UUID("a77b4e8d-7b53-4bc2-aa24-8224f82a2528")
    event_id = UUID("27cb579d-0b1e-4fd0-8c4f-c2a3ad7a7e29")

    class FakeRedis:
        async def aclose(self) -> None:
            return None

    class FakeEngine:
        async def dispose(self) -> None:
            return None

    class FakeRepository:
        def __init__(self, _: object) -> None:
            pass

        async def get(self, _: UUID) -> SimpleNamespace:
            return SimpleNamespace(status=SimpleNamespace(value="RUNNING"))

        async def is_active_workflow_event(self, _: UUID, received: UUID) -> bool:
            return received == event_id

        async def workflow_fencing_generation(self, _: UUID) -> int:
            return 0

    class BusyLock:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def acquire(self, _: UUID, **__: object) -> None:
            return None

    monkeypatch.setattr(
        workflow_tasks,
        "get_settings",
        lambda: SimpleNamespace(redis_url="redis://unused", workflow_lock_ttl_seconds=60),
    )
    monkeypatch.setattr(workflow_tasks, "create_engine", lambda _: FakeEngine())
    monkeypatch.setattr(workflow_tasks, "async_sessionmaker", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(workflow_tasks.Redis, "from_url", lambda *_args, **_kwargs: FakeRedis())
    monkeypatch.setattr(workflow_tasks, "SqlTaskRepository", FakeRepository)
    monkeypatch.setattr(workflow_tasks, "TaskLock", BusyLock)

    assert await workflow_tasks._run(task_id, event_id=event_id) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_location", ["postgres", "postgres_pool", "redis"])
async def test_preflight_dependency_failure_requests_workflow_retry(
    monkeypatch, failure_location: str
) -> None:
    from slideai.workers import workflow_tasks

    task_id = UUID("b9b7e7c9-73c7-4917-b354-5d0b9913a160")
    operations: list[str] = []

    class FakeRedis:
        async def aclose(self) -> None:
            operations.append("redis_closed")

    class FakeEngine:
        async def dispose(self) -> None:
            operations.append("engine_disposed")

    class FakeRepository:
        def __init__(self, _: object) -> None:
            pass

        async def get(self, _: UUID) -> SimpleNamespace:
            return SimpleNamespace(status=SimpleNamespace(value="RUNNING"))

        async def workflow_fencing_generation(self, _: UUID) -> int:
            if failure_location == "postgres":
                raise OperationalError("SELECT generation", {}, OSError("database unavailable"))
            if failure_location == "postgres_pool":
                raise SQLAlchemyTimeoutError("database connection pool is exhausted")
            return 0

    class FailingLock:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def acquire(self, _: UUID, **__: object) -> None:
            if failure_location == "redis":
                raise RedisConnectionError("redis unavailable")
            pytest.fail("lock acquisition should not run after a PostgreSQL failure")

    redis = FakeRedis()
    engine = FakeEngine()
    monkeypatch.setattr(
        workflow_tasks,
        "get_settings",
        lambda: SimpleNamespace(redis_url="redis://unused", workflow_lock_ttl_seconds=60),
    )
    monkeypatch.setattr(workflow_tasks, "create_engine", lambda _: engine)
    monkeypatch.setattr(workflow_tasks, "async_sessionmaker", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(workflow_tasks.Redis, "from_url", lambda *_args, **_kwargs: redis)
    monkeypatch.setattr(workflow_tasks, "SqlTaskRepository", FakeRepository)
    monkeypatch.setattr(workflow_tasks, "TaskLock", FailingLock)

    assert await workflow_tasks._run(task_id) is False
    assert operations == ["redis_closed", "engine_disposed"]


def test_workflow_retry_has_no_retry_limit() -> None:
    from slideai.workers.workflow_tasks import _retry_workflow_delivery

    class RetryRequested(Exception):
        pass

    class FakeTask:
        def __init__(self) -> None:
            self.options: dict[str, object] = {}

        def retry(self, **options: object) -> RetryRequested:
            self.options = options
            return RetryRequested()

    task = FakeTask()
    with pytest.raises(RetryRequested):
        _retry_workflow_delivery(task)

    assert task.options == {"countdown": 2, "max_retries": None}


def test_workflow_celery_tasks_allow_unbounded_retries() -> None:
    from slideai.workers.workflow_tasks import resume_workflow, start_workflow

    assert start_workflow.max_retries is None
    assert resume_workflow.max_retries is None
