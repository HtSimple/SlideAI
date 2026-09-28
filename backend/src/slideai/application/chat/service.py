from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from slideai.application.chat.scope import ChangeScope, resolve_change_scope
from slideai.application.evaluation.checks import run_hard_checks
from slideai.application.evaluation.evaluator import evaluate_quality
from slideai.application.evaluation.refiner import refine_content
from slideai.application.models.gateway import ModelGateway
from slideai.core.errors import DomainError
from slideai.domain.changes.models import (
    ChangeIntent,
    ChangeRequest,
    ChatMessage,
    ChatResult,
    ChatTarget,
    UndoResult,
)
from slideai.domain.content.models import SlideContent
from slideai.domain.evaluation.models import (
    EvaluationDraft,
    Revision,
    SlideRefinementDraft,
    SlideRevisionDraft,
)
from slideai.domain.requirements.models import Outline, OutlineSection
from slideai.domain.tasks.models import TaskRecord, TaskStatus

ChatParser = Callable[..., Awaitable[ChangeIntent]]


class TaskRepository(Protocol):
    async def get(self, task_id: UUID) -> TaskRecord | None: ...

    async def update(self, task: TaskRecord, *, expected_version: int) -> None: ...


class SlideRepository(Protocol):
    async def list_for_task(self, task_id: UUID) -> list[SlideContent]: ...

    async def upsert_batch(self, task_id: UUID, slides: list[SlideContent]) -> None: ...


class RevisionRepository(Protocol):
    async def add(self, revision: Revision) -> None: ...

    async def list_for_task(self, task_id: UUID) -> list[Revision]: ...

    async def next_revision_number(self, task_id: UUID) -> int: ...


class MutationRepository(Protocol):
    async def commit_revision(
        self,
        task: TaskRecord,
        *,
        expected_version: int,
        slides: list[SlideContent] | None,
        revision: Revision,
    ) -> None: ...


class ChatRepository(Protocol):
    async def add_message(self, message: ChatMessage) -> None: ...

    async def list_messages(
        self, task_id: UUID, *, offset: int = 0, limit: int = 100
    ) -> list[ChatMessage]: ...

    async def add_change(self, change: ChangeRequest) -> None: ...

    async def get_change(self, task_id: UUID, change_id: UUID) -> ChangeRequest | None: ...

    async def update_change(self, change: ChangeRequest) -> None: ...


class ChatService:
    def __init__(
        self,
        tasks: TaskRepository,
        slides: SlideRepository,
        revisions: RevisionRepository,
        chats: ChatRepository,
        parser: Any,
        gateway: ModelGateway | None = None,
        *,
        mutation_repository: MutationRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.tasks = tasks
        self.slides = slides
        self.revisions = revisions
        self.chats = chats
        self.parser = parser
        self.gateway = gateway
        self.mutation_repository = mutation_repository
        self.clock = clock or (lambda: datetime.now(UTC))

    async def send_message(
        self,
        task_id: UUID,
        *,
        content: str,
        expected_task_version: int,
        target: ChatTarget | None = None,
    ) -> ChatResult:
        task = await self._get_task(task_id)
        self._expect_version(task, expected_task_version)
        self._expect_chat_ready(task)
        if task.outline is None:
            raise DomainError("CHAT_NOT_READY", "This task has no outline to modify yet.")
        if not content.strip():
            raise DomainError("VALIDATION_ERROR", "Message content cannot be empty.")

        slides = await self.slides.list_for_task(task_id)
        user_message = ChatMessage(
            task_id=task_id,
            role="user",
            content=content.strip(),
            target=target,
            created_at=self.clock(),
        )
        await self.chats.add_message(user_message)
        intent = ChangeIntent.model_validate(
            await self._parse(task, content.strip(), target, slides)
        )
        await self._assert_current_version(task.id, expected_task_version)
        scope = resolve_change_scope(intent, target, task.outline, slides)
        status = (
            "NEEDS_CLARIFICATION"
            if scope.needs_clarification
            else "NEEDS_CONFIRMATION"
            if scope.needs_confirmation
            else "APPLIED"
        )
        change_data = intent.model_dump()
        change_data.update(
            {
                "task_id": task_id,
                "source_message_id": user_message.id,
                "target_ids": scope.target_ids,
                "impact_scope": scope.impact_scope,
                "affected_pages": [
                    slide.page_number for slide in slides if str(slide.id) in scope.slide_ids
                ],
                "risk_level": scope.risk_level,
                "status": status,
                "expected_task_version": expected_task_version,
                "created_at": self.clock(),
            }
        )
        change = ChangeRequest.model_validate(change_data)
        await self.chats.add_change(change)

        revision: Revision | None = None
        current_version = task.version
        if status == "NEEDS_CLARIFICATION":
            response_text = scope.clarification_question or "请说明希望修改的具体对象。"
        elif status == "NEEDS_CONFIRMATION":
            response_text = self._confirmation_summary(change, slides)
        else:
            task, revision, summary = await self._apply(task, change, slides, scope)
            current_version = task.version
            change = change.model_copy(update={"resolved_at": self.clock()})
            await self.chats.update_change(change)
            response_text = summary

        assistant_message = ChatMessage(
            task_id=task_id,
            role="assistant",
            content=response_text,
            target=target,
            change_request=change,
            revision_id=revision.id if revision else None,
            can_undo=revision is not None and revision.revision_type in {"CHAT", "USER"},
            created_at=self.clock(),
        )
        await self.chats.add_message(assistant_message)
        return ChatResult(
            task_id=task_id,
            status=status,
            user_message=user_message,
            assistant_message=assistant_message,
            change_request=change,
            revision_id=revision.id if revision else None,
            task_version=current_version,
        )

    async def confirm_change(
        self,
        task_id: UUID,
        *,
        change_id: UUID,
        expected_task_version: int,
    ) -> ChatResult:
        task = await self._get_task(task_id)
        self._expect_version(task, expected_task_version)
        self._expect_chat_ready(task)
        change = await self.chats.get_change(task_id, change_id)
        if change is None:
            raise DomainError("CHANGE_NOT_FOUND", "Change request was not found.")
        if change.status != "NEEDS_CONFIRMATION":
            raise DomainError(
                "CHANGE_CONFLICT", "This change is no longer waiting for confirmation."
            )
        if change.expected_task_version != expected_task_version:
            raise self._version_conflict(change.expected_task_version, task.version)

        slides = await self.slides.list_for_task(task_id)
        scope = resolve_change_scope(
            ChangeIntent.model_validate(
                {field: getattr(change, field) for field in ChangeIntent.model_fields}
            ),
            None,
            task.outline,
            slides,
        )
        if scope.needs_clarification:
            raise DomainError("CHANGE_CONFLICT", "The change target is no longer valid.")
        task, revision, summary = await self._apply(task, change, slides, scope)
        resolved = change.model_copy(update={"status": "APPLIED", "resolved_at": self.clock()})
        await self.chats.update_change(resolved)
        assistant_message = ChatMessage(
            task_id=task_id,
            role="assistant",
            content=summary,
            target=None,
            change_request=resolved,
            revision_id=revision.id,
            can_undo=True,
            created_at=self.clock(),
        )
        await self.chats.add_message(assistant_message)
        user_message = next(
            (
                item
                for item in await self.chats.list_messages(task_id)
                if item.id == change.source_message_id
            ),
            ChatMessage(
                task_id=task_id,
                role="user",
                content=change.instruction,
                created_at=change.created_at,
            ),
        )
        return ChatResult(
            task_id=task_id,
            status="APPLIED",
            user_message=user_message,
            assistant_message=assistant_message,
            change_request=resolved,
            revision_id=revision.id,
            task_version=task.version,
        )

    async def history(
        self, task_id: UUID, *, offset: int = 0, limit: int = 100
    ) -> list[ChatMessage]:
        await self._get_task(task_id)
        messages: list[ChatMessage] = await self.chats.list_messages(
            task_id, offset=offset, limit=limit
        )
        revisions = await self.revisions.list_for_task(task_id)
        undoable_id: UUID | None = None
        if revisions and revisions[-1].revision_type in {"CHAT", "USER"}:
            undoable_id = revisions[-1].id
        history: list[ChatMessage] = []
        for message in messages:
            change = message.change_request
            if change is not None:
                persisted_change = await self.chats.get_change(task_id, change.id)
                if persisted_change is not None:
                    change = persisted_change
            history.append(
                message.model_copy(
                    update={
                        "change_request": change,
                        "can_undo": message.revision_id == undoable_id,
                    }
                )
            )
        return history

    async def undo(
        self,
        task_id: UUID,
        *,
        revision_id: UUID,
        expected_task_version: int,
    ) -> UndoResult:
        task = await self._get_task(task_id)
        self._expect_version(task, expected_task_version)
        self._expect_chat_ready(task)
        history = await self.revisions.list_for_task(task_id)
        if not history:
            raise DomainError("REVISION_NOT_UNDOABLE", "There is no chat change to undo.")
        latest = history[-1]
        if latest.id != revision_id or latest.revision_type not in {"CHAT", "USER"}:
            raise DomainError("REVISION_NOT_UNDOABLE", "Only the latest chat change can be undone.")

        current = await self.slides.list_for_task(task_id)
        restored = latest.before_slides
        before_outline = task.outline
        after_outline = latest.before_outline or task.outline
        evaluation = (
            await self._evaluate(task, restored, after_outline)
            if restored
            else task.evaluation_result
        )
        undo_revision = Revision(
            task_id=task_id,
            revision_number=await self.revisions.next_revision_number(task_id),
            revision_type="UNDO",
            scope=latest.scope,
            reason=f"撤销修改：{latest.reason}",
            before_slides=current,
            after_slides=restored,
            before_outline=before_outline,
            after_outline=after_outline,
            score_before=task.evaluation_result.total_score if task.evaluation_result else None,
            score_after=evaluation.total_score if evaluation else None,
            created_at=self.clock(),
        )
        updated = task.model_copy(
            update={
                "outline": after_outline,
                "evaluation_result": evaluation,
                "version": task.version + 1,
                "updated_at": self.clock(),
            }
        )
        await self._commit_revision(
            updated,
            expected_version=task.version,
            slides=restored if current or restored else None,
            revision=undo_revision,
        )
        message = ChatMessage(
            task_id=task_id,
            role="assistant",
            content="已撤销最近一次聊天修改，并恢复到修改前的内容。",
            revision_id=undo_revision.id,
            can_undo=False,
            created_at=self.clock(),
        )
        await self.chats.add_message(message)
        return UndoResult(
            task_id=task_id,
            revision=undo_revision,
            task_version=updated.version,
            can_undo=False,
            assistant_message=message,
        )

    async def _parse(
        self,
        task: TaskRecord,
        content: str,
        target: ChatTarget | None,
        slides: list[SlideContent],
    ) -> ChangeIntent:
        parse = getattr(self.parser, "parse", None)
        if parse is None:
            raise DomainError("CHANGE_PARSER_UNAVAILABLE", "The chat change parser is unavailable.")
        try:
            parsed = await parse(task=task, content=content, target=target, slides=slides)
            return ChangeIntent.model_validate(parsed)
        except DomainError:
            raise
        except Exception as error:
            raise DomainError(
                "OUTPUT_VALIDATION_ERROR", "Could not understand the requested change."
            ) from error

    async def _apply(
        self,
        task: TaskRecord,
        change: ChangeRequest,
        before_slides: list[SlideContent],
        scope: ChangeScope,
    ) -> tuple[TaskRecord, Revision, str]:
        if task.outline is None:
            raise DomainError("CHAT_NOT_READY", "This task has no outline to modify yet.")
        before_outline = task.outline
        after_outline = before_outline
        if change.target_type == "outline_item":
            if not change.replacement_text:
                raise DomainError("CHANGE_TARGET_AMBIGUOUS", "The replacement title is missing.")
            sections: list[OutlineSection] = []
            for section in before_outline.sections:
                items = [
                    item.model_copy(update={"title": change.replacement_text})
                    if item.id in scope.target_ids
                    else item
                    for item in section.items
                ]
                sections.append(section.model_copy(update={"items": items}))
            after_outline = before_outline.model_copy(update={"sections": sections})

        affected = [slide for slide in before_slides if str(slide.id) in scope.slide_ids]
        after_slides = before_slides
        if affected:
            gateway = self.gateway
            if gateway is None:
                raise DomainError(
                    "MODEL_NOT_CONFIGURED", "A generation model is required for chat changes."
                )

            async def refiner(
                selected: list[SlideContent], neighbors: list[dict[str, object]], feedback: str
            ) -> list[SlideRevisionDraft]:
                result = await gateway.invoke_structured(
                    task_id=task.id,
                    node="refine_content",
                    messages=[
                        {"role": "system", "content": "仅修改指定页面，保留稳定页面 ID 和页码。"},
                        {
                            "role": "user",
                            "content": self._json(
                                {
                                    "slides": [item.model_dump(mode="json") for item in selected],
                                    "neighbors": neighbors,
                                    "feedback": feedback,
                                }
                            ),
                        },
                    ],
                    output_schema=SlideRefinementDraft,
                    preference=task.model_preference,
                    complexity=task.complexity,
                    idempotency_key=f"{task.id}:chat:{change.id}:refine",
                )
                return result.output.slides

            after_slides = await refine_content(
                before_slides,
                {UUID(value) for value in scope.slide_ids},
                change.instruction,
                refiner,
            )
        evaluation = (
            await self._evaluate(task, after_slides, after_outline)
            if after_slides and task.structured_requirement is not None
            else task.evaluation_result
        )
        revision = Revision(
            task_id=task.id,
            revision_number=await self.revisions.next_revision_number(task.id),
            revision_type="CHAT",
            scope=scope.impact_scope,
            reason=change.instruction,
            before_slides=before_slides,
            after_slides=after_slides,
            before_outline=before_outline,
            after_outline=after_outline,
            score_before=task.evaluation_result.total_score if task.evaluation_result else None,
            score_after=evaluation.total_score if evaluation else None,
            created_at=self.clock(),
        )
        updated = task.model_copy(
            update={
                "outline": after_outline,
                "evaluation_result": evaluation,
                "version": task.version + 1,
                "updated_at": self.clock(),
            }
        )
        await self._commit_revision(
            updated,
            expected_version=task.version,
            slides=after_slides if before_slides or after_slides else None,
            revision=revision,
        )
        return updated, revision, self._applied_summary(change, revision, before_slides)

    async def _commit_revision(
        self,
        task: TaskRecord,
        *,
        expected_version: int,
        slides: list[SlideContent] | None,
        revision: Revision,
    ) -> None:
        await self._assert_current_version(task.id, expected_version)
        if self.mutation_repository is not None:
            await self.mutation_repository.commit_revision(
                task,
                expected_version=expected_version,
                slides=slides,
                revision=revision,
            )
            return

        # Test doubles and alternate adapters still compare the task version before
        # any content write. Production uses the atomic SQL implementation above.
        await self.tasks.update(task, expected_version=expected_version)
        if slides is not None:
            await self.slides.upsert_batch(task.id, slides)
        await self.revisions.add(revision)

    async def _assert_current_version(self, task_id: UUID, expected_version: int) -> None:
        current = await self._get_task(task_id)
        self._expect_version(current, expected_version)

    async def _evaluate(
        self, task: TaskRecord, slides: list[SlideContent], outline: Outline | None
    ):
        gateway = self.gateway
        if gateway is None or task.structured_requirement is None or outline is None:
            return task.evaluation_result
        checks = run_hard_checks(slides, task.structured_requirement, outline)
        result = await gateway.invoke_structured(
            task_id=task.id,
            node="evaluate_quality",
            messages=[
                {"role": "system", "content": "评估修改后的完整页面，返回四项等权评分。"},
                {
                    "role": "user",
                    "content": self._json(
                        {
                            "requirement": task.structured_requirement.model_dump(mode="json"),
                            "outline": outline.model_dump(mode="json"),
                            "slides": [item.model_dump(mode="json") for item in slides],
                        }
                    ),
                },
            ],
            output_schema=EvaluationDraft,
            preference=task.model_preference,
            complexity=task.complexity,
            idempotency_key=f"{task.id}:chat:evaluate:{task.version + 1}",
        )
        return evaluate_quality(
            slides,
            task.structured_requirement,
            outline,
            result.output,
            hard_checks=checks,
        )

    async def _get_task(self, task_id: UUID) -> TaskRecord:
        task = await self.tasks.get(task_id)
        if task is None:
            raise DomainError("TASK_NOT_FOUND", "Task was not found.")
        return task

    @staticmethod
    def _expect_chat_ready(task: TaskRecord) -> None:
        if task.status not in {
            TaskStatus.READY,
            TaskStatus.WAITING_OUTLINE_CONFIRMATION,
            TaskStatus.WAITING_USER_FEEDBACK,
            TaskStatus.COMPLETED,
        }:
            raise DomainError(
                "TASK_CONFLICT", "The task cannot accept chat changes in its current state."
            )

    @classmethod
    def _expect_version(cls, task: TaskRecord, expected: int) -> None:
        if task.version != expected:
            raise cls._version_conflict(expected, task.version)

    @staticmethod
    def _version_conflict(expected: int, actual: int) -> DomainError:
        return DomainError(
            "VERSION_CONFLICT",
            "Task changed since it was loaded.",
            {"expected_version": expected, "actual_version": actual},
        )

    @staticmethod
    def _confirmation_summary(change: ChangeRequest, slides: list[SlideContent]) -> str:
        if change.target_type == "outline_item" and change.impact_scope:
            return (
                f"此大纲修改会影响第 {'、'.join(map(str, change.affected_pages))} 页。"
                "确认后只会重新生成这些页面。"
            )
        if change.affected_pages:
            return (
                f"此修改会影响第 {'、'.join(map(str, change.affected_pages))} 页。确认后继续执行？"
            )
        return f"此修改会影响 {len(change.impact_scope) or len(slides)} 个对象。确认后继续执行？"

    @staticmethod
    def _applied_summary(
        change: ChangeRequest, revision: Revision, before: list[SlideContent]
    ) -> str:
        changed = len(change.impact_scope)
        untouched = max(0, len(before) - changed)
        return f"修改已完成，共修改 {changed} 处，未影响 {untouched} 页。"

    @staticmethod
    def _json(payload: dict[str, object]) -> str:
        import json

        return json.dumps(payload, ensure_ascii=False)
