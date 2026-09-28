import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from slideai.core.config import get_settings
from slideai.core.errors import DomainError
from slideai.domain.content.models import SlideContent
from slideai.domain.tasks.models import RawRequirement, TaskRecord, initial_complexity
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
