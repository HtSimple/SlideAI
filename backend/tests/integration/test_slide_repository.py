import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from slideai.application.content.writer import write_slide_batches
from slideai.core.config import get_settings
from slideai.core.errors import DomainError
from slideai.domain.content.models import SlideBatch, SlideContent, SlideDraft, SlideProgress
from slideai.domain.files.models import SourceCitation
from slideai.domain.requirements.models import (
    Outline,
    OutlineItem,
    OutlineSection,
    StructuredRequirement,
)
from slideai.domain.tasks.models import RawRequirement, TaskRecord, TaskStatus, initial_complexity
from slideai.infrastructure.db.session import create_engine
from slideai.infrastructure.db.slide_repository import SqlSlideRepository
from slideai.infrastructure.db.task_repository import SqlTaskRepository

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 when Compose dependencies are available",
)


@pytest.mark.asyncio
async def test_slide_repository_persists_idempotently_and_keeps_task_scope() -> None:
    engine = create_engine(get_settings())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tasks = SqlTaskRepository(sessions)
    slides = SqlSlideRepository(sessions)
    first = _task()
    second = _task()
    await tasks.add(first)
    await tasks.add(second)
    try:
        slide = SlideContent(
            id=uuid4(),
            task_id=first.id,
            page_number=1,
            section_id="opening",
            outline_item_id="context",
            title="市场概览",
            bullets=["市场规模持续增长", "供给结构正在变化"],
            citations=[],
            verification_notes=["核实最新年度数据"],
        )

        await slides.upsert_batch(first.id, [slide])
        saved = await slides.list_for_task(first.id)
        assert saved == [slide]
        assert await slides.list_for_task(second.id) == []

        revised = slide.model_copy(update={"title": "市场背景"})
        await slides.upsert_batch(first.id, [revised])
        assert (await slides.list_for_task(first.id))[0].title == "市场背景"

        with pytest.raises(DomainError, match="different task"):
            await slides.upsert_batch(second.id, [slide])
    finally:
        await tasks.delete(first.id)
        await tasks.delete(second.id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_cancelled_task_fences_an_in_flight_slide_batch_and_progress_write() -> None:
    engine = create_engine(get_settings())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tasks = SqlTaskRepository(sessions)
    worker_generation = 1
    guarded_slides = SqlSlideRepository(
        sessions, require_running=True, fencing_generation=worker_generation
    )
    task = _task()
    running = task.model_copy(update={"status": TaskStatus.RUNNING, "version": task.version + 1})
    cancelled = running.model_copy(
        update={"status": TaskStatus.CANCELLED, "current_stage": "cancelled", "version": 3}
    )
    slide = SlideContent(
        id=uuid4(),
        task_id=task.id,
        page_number=1,
        section_id="opening",
        outline_item_id="context",
        title="市场概览",
        bullets=["市场规模持续增长", "供给结构正在变化"],
        citations=[],
        verification_notes=[],
    )
    writer = BlockingWriter()

    class EmptyRetriever:
        async def search(self, *_: object) -> list[SourceCitation]:
            return []

    try:
        await tasks.add(task)
        await tasks.update(running, expected_version=task.version)
        assert await tasks.claim_workflow_lease(task.id, None, worker_generation)
        generation = asyncio.create_task(
            write_slide_batches(
                task_id=task.id,
                requirement=StructuredRequirement(
                    topic="市场趋势",
                    target_page_count=3,
                    scenario="年度分析",
                    audience="管理层",
                    style="结论先行",
                ),
                outline=Outline(
                    title="市场趋势",
                    sections=[
                        OutlineSection(
                            id="opening",
                            title="市场概览",
                            objective="说明市场变化",
                            page_count=3,
                            items=[
                                OutlineItem(
                                    id="context",
                                    title="行业背景",
                                    objective="梳理行业背景",
                                    page_count=3,
                                )
                            ],
                        )
                    ],
                ),
                writer=writer,
                retriever=EmptyRetriever(),
                repository=guarded_slides,
            )
        )
        await asyncio.wait_for(writer.started.wait(), timeout=5)
        await tasks.update(cancelled, expected_version=running.version)
        writer.finish.set()

        with pytest.raises(DomainError) as batch_error:
            await generation
        with pytest.raises(DomainError) as slide_error:
            await guarded_slides.upsert_batch(task.id, [slide])
        with pytest.raises(DomainError) as progress_error:
            await tasks.update_progress(
                task.id,
                SlideProgress(
                    total_pages=3,
                    completed_pages=0,
                    total_batches=1,
                    completed_batches=0,
                ),
                fencing_generation=worker_generation,
            )

        assert batch_error.value.code == "WORKFLOW_CANCELLED"
        assert slide_error.value.code == "WORKFLOW_CANCELLED"
        assert progress_error.value.code == "WORKFLOW_CANCELLED"
        assert await guarded_slides.list_for_task(task.id) == []
        assert (await tasks.get(task.id)).status == TaskStatus.CANCELLED
    finally:
        if not writer.finish.is_set():
            writer.finish.set()
        await tasks.delete(task.id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_replaced_worker_fencing_token_blocks_stale_writes() -> None:
    from slideai.workflow.runtime import _persist_projection

    engine = create_engine(get_settings())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tasks = SqlTaskRepository(sessions)
    task = _task()
    running = task.model_copy(update={"status": TaskStatus.RUNNING, "version": task.version + 1})
    stale_slide = SlideContent(
        id=uuid4(),
        task_id=task.id,
        page_number=1,
        section_id="opening",
        outline_item_id="context",
        title="旧 Worker 页面",
        bullets=["过期令牌不得写入", "新租约接管后数据库拒绝该页面"],
        citations=[],
        verification_notes=[],
    )

    try:
        await tasks.add(task)
        await tasks.update(running, expected_version=task.version)
        assert await tasks.claim_workflow_lease(task.id, None, 10)
        assert await tasks.claim_workflow_lease(task.id, None, 11)

        with pytest.raises(DomainError) as progress_error:
            await tasks.update_progress(
                task.id,
                SlideProgress(
                    total_pages=3,
                    completed_pages=1,
                    total_batches=1,
                    completed_batches=1,
                ),
                fencing_generation=10,
            )
        with pytest.raises(DomainError) as slide_error:
            await SqlSlideRepository(
                sessions, require_running=True, fencing_generation=10
            ).upsert_batch(task.id, [stale_slide])

        assert not await tasks.mark_failed_if_workflow_current(task.id, 10)
        await _persist_projection(
            tasks,
            task.id,
            {"final_markdown": "# Stale result", "slides_content": []},
            fencing_generation=10,
        )

        latest = await tasks.get(task.id)
        assert latest is not None
        assert latest.status == TaskStatus.RUNNING
        assert latest.version == running.version
        assert progress_error.value.code == "WORKFLOW_LOCK_LOST"
        assert slide_error.value.code == "WORKFLOW_LOCK_LOST"
        assert await SqlSlideRepository(sessions).list_for_task(task.id) == []

        await _persist_projection(
            tasks,
            task.id,
            {"final_markdown": "# Current result", "slides_content": []},
            fencing_generation=11,
        )
        completed = await tasks.get(task.id)
        assert completed is not None
        assert completed.status == TaskStatus.COMPLETED
    finally:
        await tasks.delete(task.id)
        await engine.dispose()


class BlockingWriter:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.finish = asyncio.Event()

    async def write_batch(self, *, page_plans, **_: object) -> SlideBatch:
        self.started.set()
        await self.finish.wait()
        return SlideBatch(
            slides=[
                SlideDraft(
                    page_number=plan.page_number,
                    title=plan.title,
                    bullets=["市场持续变化", "企业需要及时响应"],
                )
                for plan in page_plans
            ]
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
