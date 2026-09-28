from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from slideai.application.chat.service import ChatService
from slideai.core.errors import DomainError
from slideai.domain.content.models import SlideContent
from slideai.domain.evaluation.models import Revision
from slideai.domain.requirements.models import Outline, StructuredRequirement
from slideai.domain.tasks.models import RawRequirement, TaskRecord, TaskStatus, initial_complexity


def _slide(task_id: UUID, page: int, title: str) -> SlideContent:
    return SlideContent(
        id=UUID(int=page),
        task_id=task_id,
        page_number=page,
        section_id=f"section-{1 if page < 3 else 2}",
        outline_item_id=f"item-{page}",
        title=title,
        bullets=["关键背景", "行动建议"],
    )


def _fixtures(*, version: int = 3):
    now = datetime.now(UTC)
    raw = RawRequirement(topic="市场分析", target_page_count=4)
    task_id = uuid4()
    task = TaskRecord(
        id=task_id,
        name=raw.topic,
        status=TaskStatus.COMPLETED,
        current_stage="completed",
        raw_requirement=raw,
        model_preference={"mode": "auto"},
        complexity=initial_complexity(raw),
        structured_requirement=StructuredRequirement(
            topic=raw.topic,
            target_page_count=4,
            scenario="季度汇报",
            audience="管理团队",
            style="结论先行",
        ),
        outline=Outline(
            title="市场分析",
            sections=[
                {
                    "id": "section-1",
                    "title": "市场现状",
                    "objective": "说明现状",
                    "page_count": 2,
                    "items": [
                        {"id": "item-1", "title": "规模", "objective": "说明规模", "page_count": 1},
                        {"id": "item-2", "title": "变化", "objective": "说明变化", "page_count": 1},
                    ],
                },
                {
                    "id": "section-2",
                    "title": "行动建议",
                    "objective": "提出方向",
                    "page_count": 2,
                    "items": [
                        {"id": "item-3", "title": "机会", "objective": "说明机会", "page_count": 1},
                        {
                            "id": "item-4",
                            "title": "项目分析",
                            "objective": "分析项目",
                            "page_count": 1,
                        },
                    ],
                },
            ],
        ),
        version=version,
        created_at=now,
        updated_at=now,
    )
    slides = [_slide(task_id, page, f"页面 {page}") for page in range(1, 5)]
    return task, slides


class MemoryTasks:
    def __init__(self, task: TaskRecord) -> None:
        self.task = task
        self.updates = 0

    async def get(self, task_id: UUID):
        return self.task if task_id == self.task.id else None

    async def update(self, task: TaskRecord, *, expected_version: int) -> None:
        if self.task.version != expected_version:
            raise DomainError("VERSION_CONFLICT", "Task changed since it was loaded.")
        self.task = task
        self.updates += 1


class MemorySlides:
    def __init__(self, slides: list[SlideContent]) -> None:
        self.slides = slides
        self.upserts = 0

    async def list_for_task(self, task_id: UUID):
        return [slide for slide in self.slides if slide.task_id == task_id]

    async def upsert_batch(self, task_id: UUID, slides: list[SlideContent]) -> None:
        assert all(slide.task_id == task_id for slide in slides)
        self.slides = slides
        self.upserts += 1


class MemoryRevisions:
    def __init__(self, revisions: list[Revision] | None = None) -> None:
        self.revisions = revisions or []

    async def add(self, revision: Revision) -> None:
        self.revisions.append(revision)

    async def list_for_task(self, task_id: UUID):
        return [item for item in self.revisions if item.task_id == task_id]

    async def next_revision_number(self, task_id: UUID) -> int:
        return (
            max((item.revision_number for item in await self.list_for_task(task_id)), default=0) + 1
        )


class MemoryChats:
    def __init__(self) -> None:
        self.messages = []
        self.changes = []

    async def add_message(self, message):
        self.messages.append(message)

    async def list_messages(self, task_id: UUID, *, offset=0, limit=100):
        items = [item for item in self.messages if item.task_id == task_id]
        return items[offset : offset + limit]

    async def add_change(self, change):
        self.changes.append(change)

    async def get_change(self, task_id: UUID, change_id: UUID):
        return next(
            (item for item in self.changes if item.task_id == task_id and item.id == change_id),
            None,
        )

    async def update_change(self, change):
        self.changes = [item for item in self.changes if item.id != change.id]
        self.changes.append(change)


class IntentParser:
    def __init__(self, intent) -> None:
        self.intent = intent
        self.calls = 0

    async def parse(self, **kwargs):
        self.calls += 1
        return self.intent


class ConcurrentIntentParser(IntentParser):
    def __init__(self, intent, tasks: MemoryTasks) -> None:
        super().__init__(intent)
        self.tasks = tasks

    async def parse(self, **kwargs):
        self.tasks.task = self.tasks.task.model_copy(
            update={"version": self.tasks.task.version + 1}
        )
        return await super().parse(**kwargs)


class RefinementGateway:
    async def invoke_structured(self, *, task_id, node, messages, output_schema, **_kwargs):
        import json

        payload = json.loads(messages[-1]["content"])
        if output_schema.__name__ == "SlideRefinementDraft":
            return type(
                "Result",
                (),
                {
                    "output": output_schema.model_validate(
                        {
                            "slides": [
                                {
                                    "id": slide["id"],
                                    "title": f"已修改：{slide['title']}",
                                    "bullets": ["更新后的结论", "对应的行动建议"],
                                    "speaker_notes": slide.get("speaker_notes"),
                                    "verification_notes": slide.get("verification_notes", []),
                                }
                                for slide in payload["slides"]
                            ]
                        }
                    )
                },
            )()
        if output_schema.__name__ == "EvaluationDraft":
            return type(
                "Result",
                (),
                {
                    "output": output_schema.model_validate(
                        {
                            "dimensions": [
                                {"name": name, "score": 90, "feedback": "修改后已复核。"}
                                for name in (
                                    "completeness",
                                    "logic",
                                    "content_quality",
                                    "requirement_alignment",
                                )
                            ]
                        }
                    )
                },
            )()
        raise AssertionError(f"Unexpected schema: {output_schema}")


@pytest.mark.asyncio
async def test_unclear_target_does_not_mutate_task_or_slides() -> None:
    task, slides = _fixtures()
    tasks, slide_repository, revisions, chats = (
        MemoryTasks(task),
        MemorySlides(slides),
        MemoryRevisions(),
        MemoryChats(),
    )
    parser = IntentParser(
        {
            "target_type": "slide",
            "target_ids": [],
            "operation": "rewrite",
            "instruction": "改得更有说服力",
            "risk_level": "local",
            "needs_clarification": True,
            "clarification_question": "要修改哪一页？",
        }
    )
    service = ChatService(tasks, slide_repository, revisions, chats, parser)

    result = await service.send_message(
        task.id, content="改得更有说服力", expected_task_version=task.version
    )

    assert result.status == "NEEDS_CLARIFICATION"
    assert result.assistant_message.content == "要修改哪一页？"
    assert slide_repository.upserts == 0
    assert tasks.updates == 0
    assert tasks.task.version == task.version
    assert not revisions.revisions


@pytest.mark.asyncio
async def test_wide_change_requires_confirmation_without_mutating_pages() -> None:
    task, slides = _fixtures()
    tasks, slide_repository, revisions, chats = (
        MemoryTasks(task),
        MemorySlides(slides),
        MemoryRevisions(),
        MemoryChats(),
    )
    parser = IntentParser(
        {
            "target_type": "whole_deck",
            "target_ids": [],
            "operation": "rewrite",
            "instruction": "重写整份内容",
            "risk_level": "local",
            "needs_clarification": False,
            "clarification_question": None,
        }
    )
    service = ChatService(tasks, slide_repository, revisions, chats, parser)

    result = await service.send_message(
        task.id, content="重写整份内容", expected_task_version=task.version
    )

    assert result.status == "NEEDS_CONFIRMATION"
    assert result.change_request.impact_scope == [str(slide.id) for slide in slides]
    assert slide_repository.upserts == 0
    assert tasks.updates == 0
    assert not revisions.revisions


@pytest.mark.asyncio
async def test_stale_version_returns_conflict_before_persisting_message() -> None:
    task, slides = _fixtures(version=7)
    tasks, slide_repository, revisions, chats = (
        MemoryTasks(task),
        MemorySlides(slides),
        MemoryRevisions(),
        MemoryChats(),
    )
    parser = IntentParser(None)
    service = ChatService(tasks, slide_repository, revisions, chats, parser)

    with pytest.raises(DomainError, match="Task changed") as error:
        await service.send_message(task.id, content="改第 1 页", expected_task_version=6)

    assert error.value.code == "VERSION_CONFLICT"
    assert not chats.messages
    assert parser.calls == 0
    assert slide_repository.upserts == 0


@pytest.mark.asyncio
async def test_version_change_during_model_parsing_does_not_write_content() -> None:
    task, slides = _fixtures()
    tasks, slide_repository, revisions, chats = (
        MemoryTasks(task),
        MemorySlides(slides),
        MemoryRevisions(),
        MemoryChats(),
    )
    parser = ConcurrentIntentParser(
        {
            "target_type": "slide",
            "target_ids": [str(slides[0].id)],
            "operation": "rewrite",
            "instruction": "改成行动建议",
            "risk_level": "local",
            "needs_clarification": False,
        },
        tasks,
    )
    service = ChatService(tasks, slide_repository, revisions, chats, parser, RefinementGateway())

    with pytest.raises(DomainError) as error:
        await service.send_message(
            task.id, content="修改第 1 页", expected_task_version=task.version
        )

    assert error.value.code == "VERSION_CONFLICT"
    assert slide_repository.slides == slides
    assert slide_repository.upserts == 0
    assert not revisions.revisions
    assert not chats.changes


@pytest.mark.asyncio
async def test_undo_creates_new_revision_and_restores_snapshot() -> None:
    task, slides = _fixtures(version=9)
    changed = [slide.model_copy(update={"title": f"修改后 {slide.title}"}) for slide in slides]
    chat_revision = Revision(
        task_id=task.id,
        revision_number=1,
        revision_type="CHAT",
        scope=[str(slides[0].id)],
        reason="调整第一页面向受众的表达",
        before_slides=slides,
        after_slides=changed,
        created_at=datetime.now(UTC),
    )
    tasks, slide_repository, revisions, chats = (
        MemoryTasks(task),
        MemorySlides(changed),
        MemoryRevisions([chat_revision]),
        MemoryChats(),
    )
    service = ChatService(
        tasks,
        slide_repository,
        revisions,
        chats,
        IntentParser(None),
    )

    undone = await service.undo(
        task.id,
        revision_id=chat_revision.id,
        expected_task_version=task.version,
    )

    assert slide_repository.slides == slides
    assert undone.revision.revision_type == "UNDO"
    assert undone.revision.revision_number == 2
    assert undone.can_undo is False
    assert tasks.task.version == task.version + 1
    assert all(not message.can_undo for message in await service.history(task.id))


@pytest.mark.asyncio
async def test_local_slide_change_preserves_other_pages_and_re_evaluates() -> None:
    task, slides = _fixtures()
    tasks, slide_repository, revisions, chats = (
        MemoryTasks(task),
        MemorySlides(slides),
        MemoryRevisions(),
        MemoryChats(),
    )
    parser = IntentParser(
        {
            "target_type": "slide",
            "target_ids": [str(slides[0].id)],
            "operation": "rewrite",
            "instruction": "改成面向管理团队的行动建议",
            "risk_level": "local",
            "needs_clarification": False,
        }
    )
    service = ChatService(tasks, slide_repository, revisions, chats, parser, RefinementGateway())

    result = await service.send_message(
        task.id,
        content="请改成面向管理团队的行动建议",
        expected_task_version=task.version,
    )

    assert result.status == "APPLIED"
    assert slide_repository.slides[0].title == "已修改：页面 1"
    assert slide_repository.slides[1:] == slides[1:]
    assert tasks.task.evaluation_result is not None
    assert tasks.task.evaluation_result.total_score == 90
    assert revisions.revisions[0].revision_type == "CHAT"
    assert revisions.revisions[0].before_slides[1:] == slides[1:]
    assert result.revision_id == revisions.revisions[0].id


@pytest.mark.asyncio
async def test_outline_item_change_confirms_affected_page_and_updates_only_that_page() -> None:
    task, slides = _fixtures()
    tasks, slide_repository, revisions, chats = (
        MemoryTasks(task),
        MemorySlides(slides),
        MemoryRevisions(),
        MemoryChats(),
    )
    parser = IntentParser(
        {
            "target_type": "outline_item",
            "target_ids": ["item-4"],
            "operation": "replace",
            "instruction": "把第四點改成具體項目分析",
            "replacement_text": "具体项目分析",
            "risk_level": "local",
            "needs_clarification": False,
        }
    )
    service = ChatService(tasks, slide_repository, revisions, chats, parser, RefinementGateway())

    pending = await service.send_message(
        task.id,
        content="把第四点改成具体项目分析",
        expected_task_version=task.version,
    )
    assert pending.status == "NEEDS_CONFIRMATION"
    assert pending.change_request.impact_scope == [str(slides[3].id)]
    assert slide_repository.slides == slides
    assert tasks.task.version == task.version

    applied = await service.confirm_change(
        task.id,
        change_id=pending.change_request.id,
        expected_task_version=task.version,
    )

    changed_item = tasks.task.outline.sections[1].items[1]
    assert changed_item.title == "具体项目分析"
    assert applied.status == "APPLIED"
    assert slide_repository.slides[:3] == slides[:3]
    assert slide_repository.slides[3].title == "已修改：页面 4"
    history = await service.history(task.id)
    assert [
        message.change_request.status for message in history if message.change_request is not None
    ] == ["APPLIED", "APPLIED"]
    assert history[-1].can_undo is True
