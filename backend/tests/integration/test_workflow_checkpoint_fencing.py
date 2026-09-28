import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.ext.asyncio import async_sessionmaker

from slideai.core.config import get_settings
from slideai.core.errors import DomainError
from slideai.domain.tasks.models import (
    RawRequirement,
    TaskRecord,
    TaskStatus,
    initial_complexity,
)
from slideai.infrastructure.db.session import create_engine
from slideai.infrastructure.db.task_repository import SqlTaskRepository
from slideai.workflow.runtime import FencedAsyncPostgresSaver

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 when Compose dependencies are available",
)


def _task() -> TaskRecord:
    now = datetime.now(UTC)
    requirement = RawRequirement(topic="市场趋势", target_page_count=3)
    return TaskRecord(
        id=uuid4(),
        name=requirement.topic,
        raw_requirement=requirement,
        model_preference={"mode": "auto"},
        complexity=initial_complexity(requirement),
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_stale_worker_cannot_replace_a_newer_langgraph_checkpoint() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tasks = SqlTaskRepository(sessions)
    task = _task()
    running = task.model_copy(update={"status": TaskStatus.RUNNING, "version": task.version + 1})
    config = {"configurable": {"thread_id": str(task.id), "checkpoint_ns": ""}}

    try:
        await tasks.add(task)
        await tasks.update(running, expected_version=task.version)
        assert await tasks.claim_workflow_lease(task.id, None, 10)

        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_database_url) as saver:
            await saver.setup()
            try:
                stale_worker = FencedAsyncPostgresSaver(saver, tasks, task.id, 10)
                initial_checkpoint = empty_checkpoint()
                initial_checkpoint["channel_values"] = {"worker": "generation-10"}
                await stale_worker.aput(config, initial_checkpoint, {}, {})

                assert await tasks.claim_workflow_lease(task.id, None, 11)
                current_worker = FencedAsyncPostgresSaver(saver, tasks, task.id, 11)
                current_checkpoint = empty_checkpoint()
                current_checkpoint["channel_values"] = {"worker": "generation-11"}
                await current_worker.aput(config, current_checkpoint, {}, {})

                late_checkpoint = empty_checkpoint()
                late_checkpoint["channel_values"] = {"worker": "stale-late-write"}
                with pytest.raises(DomainError) as stale_write:
                    await stale_worker.aput(config, late_checkpoint, {}, {})
                with pytest.raises(DomainError) as stale_write_batch:
                    await stale_worker.aput_writes(
                        config, [("worker", "stale-write")], "stale-worker-task"
                    )

                latest = await saver.aget_tuple(config)
                assert latest is not None
                assert latest.checkpoint["channel_values"] == {"worker": "generation-11"}
                assert stale_write.value.code == "WORKFLOW_LOCK_LOST"
                assert stale_write_batch.value.code == "WORKFLOW_LOCK_LOST"
            finally:
                await saver.adelete_thread(str(task.id))
    finally:
        await tasks.delete(task.id)
        await engine.dispose()
