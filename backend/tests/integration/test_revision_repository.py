import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from slideai.core.config import get_settings
from slideai.domain.content.models import SlideContent
from slideai.domain.evaluation.models import Revision
from slideai.domain.tasks.models import RawRequirement, TaskRecord, initial_complexity
from slideai.infrastructure.db.revision_repository import SqlRevisionRepository
from slideai.infrastructure.db.session import create_engine
from slideai.infrastructure.db.task_repository import SqlTaskRepository

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 when Compose dependencies are available",
)


@pytest.mark.asyncio
async def test_revision_snapshots_round_trip_and_remain_task_scoped() -> None:
    engine = create_engine(get_settings())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tasks = SqlTaskRepository(sessions)
    revisions = SqlRevisionRepository(sessions)
    first = _task()
    second = _task()
    await tasks.add(first)
    await tasks.add(second)
    slide = SlideContent(
        id=uuid4(),
        task_id=first.id,
        page_number=1,
        section_id="market",
        outline_item_id="signals",
        title="市场变化",
        bullets=["需求增长", "供给调整"],
    )
    after = slide.model_copy(update={"title": "修订后的市场变化"})
    revision = Revision(
        task_id=first.id,
        revision_number=1,
        revision_type="AUTO",
        scope=[str(slide.id)],
        reason="明确页面结论",
        before_slides=[slide],
        after_slides=[after],
        score_before=80,
        created_at=datetime.now(UTC),
    )
    try:
        await revisions.add(revision)

        assert await revisions.list_for_task(first.id) == [revision]
        assert await revisions.list_for_task(second.id) == []
        assert await revisions.next_revision_number(first.id) == 2
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
