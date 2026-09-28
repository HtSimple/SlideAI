import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from slideai.core.config import get_settings
from slideai.core.errors import DomainError
from slideai.domain.changes.models import ChangeRequest, ChatMessage, ChatTarget
from slideai.domain.content.models import SlideContent
from slideai.domain.evaluation.models import Revision
from slideai.domain.requirements.models import Outline
from slideai.domain.tasks.models import RawRequirement, TaskRecord, initial_complexity
from slideai.infrastructure.db.chat_repository import SqlChatRepository
from slideai.infrastructure.db.revision_repository import SqlRevisionRepository
from slideai.infrastructure.db.session import create_engine
from slideai.infrastructure.db.slide_repository import SqlSlideRepository
from slideai.infrastructure.db.task_repository import SqlTaskRepository

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 when Compose dependencies are available",
)


@pytest.mark.asyncio
async def test_chat_history_and_pending_change_survive_repository_recreation() -> None:
    engine = create_engine(get_settings())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tasks = SqlTaskRepository(sessions)
    first_task = _task()
    other_task = _task()
    chat = SqlChatRepository(sessions)
    message = ChatMessage(
        task_id=first_task.id,
        role="user",
        content="把第四点改成项目分析",
        target=ChatTarget(target_type="outline_item", target_id="item-4", label="第四点"),
        created_at=datetime.now(UTC),
    )
    change = ChangeRequest(
        task_id=first_task.id,
        source_message_id=message.id,
        target_type="outline_item",
        target_ids=["item-4"],
        operation="replace",
        instruction=message.content,
        replacement_text="项目分析",
        impact_scope=["page-4"],
        risk_level="wide",
        needs_clarification=False,
        status="NEEDS_CONFIRMATION",
        expected_task_version=1,
        created_at=datetime.now(UTC),
    )
    try:
        await tasks.add(first_task)
        await tasks.add(other_task)
        await chat.add_message(message)
        await chat.add_change(change)

        reopened_chat = SqlChatRepository(sessions)
        assert await reopened_chat.list_messages(first_task.id) == [message]
        assert await reopened_chat.get_change(first_task.id, change.id) == change
        assert await reopened_chat.list_messages(other_task.id) == []
        assert await reopened_chat.get_change(other_task.id, change.id) is None
    finally:
        await tasks.delete(first_task.id)
        await tasks.delete(other_task.id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_chat_revision_commit_checks_version_and_writes_atomically() -> None:
    engine = create_engine(get_settings())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tasks = SqlTaskRepository(sessions)
    slides = SqlSlideRepository(sessions)
    chat = SqlChatRepository(sessions)
    task = _task()
    original = SlideContent(
        id=uuid4(),
        task_id=task.id,
        page_number=1,
        section_id="section",
        outline_item_id="item-4",
        title="原页面",
        bullets=["背景说明", "建议"],
    )
    changed = original.model_copy(update={"title": "更新页面"})
    revision = Revision(
        task_id=task.id,
        revision_number=1,
        revision_type="CHAT",
        scope=[str(original.id)],
        reason="更新页面标题",
        before_slides=[original],
        after_slides=[changed],
        created_at=datetime.now(UTC),
    )
    try:
        await tasks.add(task)
        await slides.upsert_batch(task.id, [original])
        concurrent_task = task.model_copy(update={"version": task.version + 1})
        await tasks.update(concurrent_task, expected_version=task.version)

        with pytest.raises(DomainError, match="Task changed") as error:
            await chat.commit_revision(
                task.model_copy(update={"version": task.version + 1}),
                expected_version=task.version,
                slides=[changed],
                revision=revision,
            )

        assert error.value.code == "VERSION_CONFLICT"
        assert (await tasks.get(task.id)).version == concurrent_task.version
        assert (await slides.list_for_task(task.id)) == [original]
        assert await SqlRevisionRepository(sessions).list_for_task(task.id) == []

        accepted = concurrent_task.model_copy(update={"version": concurrent_task.version + 1})
        await chat.commit_revision(
            accepted,
            expected_version=concurrent_task.version,
            slides=[changed],
            revision=revision,
        )

        assert (await tasks.get(task.id)).version == accepted.version
        assert (await slides.list_for_task(task.id)) == [changed]
        assert await SqlRevisionRepository(sessions).list_for_task(task.id) == [revision]
    finally:
        await tasks.delete(task.id)
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
        outline=Outline(
            title="市场趋势",
            sections=[
                {
                    "id": "section",
                    "title": "分析",
                    "objective": "识别趋势",
                    "page_count": 3,
                    "items": [
                        {
                            "id": "item-4",
                            "title": "项目分析",
                            "objective": "分析项目",
                            "page_count": 3,
                        }
                    ],
                }
            ],
        ),
        created_at=now,
        updated_at=now,
    )
