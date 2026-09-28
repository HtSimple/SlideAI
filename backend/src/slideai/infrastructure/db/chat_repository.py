from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from slideai.core.errors import DomainError
from slideai.domain.changes.models import ChangeRequest, ChatMessage
from slideai.domain.content.models import SlideContent
from slideai.domain.evaluation.models import Revision
from slideai.domain.tasks.models import TaskRecord
from slideai.infrastructure.db.models import (
    ChangeRequestRow,
    ChatConversationRow,
    ChatMessageRow,
    GenerationTaskRow,
    RevisionRow,
    SlidePageRow,
)


class SqlChatRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def add_message(self, message: ChatMessage) -> None:
        async with self.sessions() as session, session.begin():
            statement = (
                insert(ChatConversationRow)
                .values(id=uuid4(), task_id=message.task_id)
                .on_conflict_do_nothing(index_elements=["task_id"])
            )
            await session.execute(statement)
            conversation_id = await session.scalar(
                select(ChatConversationRow.id).where(ChatConversationRow.task_id == message.task_id)
            )
            if conversation_id is None:
                raise RuntimeError("Conversation could not be created for this task.")
            conversation = await session.get(ChatConversationRow, conversation_id)
            if conversation is not None:
                from datetime import UTC, datetime

                conversation.updated_at = datetime.now(UTC)
            session.add(
                ChatMessageRow(
                    id=message.id,
                    task_id=message.task_id,
                    conversation_id=conversation_id,
                    role=message.role,
                    content=message.content,
                    target=message.target.model_dump(mode="json") if message.target else None,
                    change_request=(
                        message.change_request.model_dump(mode="json")
                        if message.change_request
                        else None
                    ),
                    revision_id=message.revision_id,
                    can_undo=message.can_undo,
                    created_at=message.created_at,
                )
            )

    async def list_messages(
        self, task_id: UUID, *, offset: int = 0, limit: int = 100
    ) -> list[ChatMessage]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(ChatMessageRow)
                    .where(ChatMessageRow.task_id == task_id)
                    .order_by(ChatMessageRow.created_at, ChatMessageRow.id)
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
            return [
                ChatMessage.model_validate(
                    {
                        "id": row.id,
                        "task_id": row.task_id,
                        "role": row.role,
                        "content": row.content,
                        "target": row.target,
                        "change_request": row.change_request,
                        "revision_id": row.revision_id,
                        "can_undo": row.can_undo,
                        "created_at": row.created_at,
                    }
                )
                for row in rows
            ]

    async def add_change(self, change: ChangeRequest) -> None:
        async with self.sessions() as session, session.begin():
            session.add(_change_row(change))

    async def get_change(self, task_id: UUID, change_id: UUID) -> ChangeRequest | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(ChangeRequestRow).where(
                    ChangeRequestRow.task_id == task_id,
                    ChangeRequestRow.id == change_id,
                )
            )
            return _to_change(row) if row else None

    async def update_change(self, change: ChangeRequest) -> None:
        async with self.sessions() as session, session.begin():
            row = await session.scalar(
                select(ChangeRequestRow)
                .where(
                    ChangeRequestRow.task_id == change.task_id,
                    ChangeRequestRow.id == change.id,
                )
                .with_for_update()
            )
            if row is not None:
                _apply_change(row, change)

    async def commit_revision(
        self,
        task: TaskRecord,
        *,
        expected_version: int,
        slides: list[SlideContent] | None,
        revision: Revision,
    ) -> None:
        if task.version != expected_version + 1:
            raise DomainError("VERSION_CONFLICT", "The revision has an invalid task version.")
        if revision.task_id != task.id:
            raise DomainError("TASK_SCOPE_VIOLATION", "A revision belongs to another task.")

        async with self.sessions() as session, session.begin():
            row = await session.scalar(
                select(GenerationTaskRow).where(GenerationTaskRow.id == task.id).with_for_update()
            )
            actual_version = row.version if row is not None else None
            if row is None or actual_version != expected_version:
                raise DomainError(
                    "VERSION_CONFLICT",
                    "Task changed since it was loaded.",
                    {"expected_version": expected_version, "actual_version": actual_version},
                )

            if slides is not None:
                if any(slide.task_id != task.id for slide in slides):
                    raise DomainError("TASK_SCOPE_VIOLATION", "A page belongs to a different task.")
                page_numbers = [slide.page_number for slide in slides]
                if len(page_numbers) != len(set(page_numbers)):
                    raise DomainError(
                        "SLIDE_BATCH_INVALID", "A batch cannot contain duplicate pages."
                    )
                existing_rows = (
                    await session.scalars(
                        select(SlidePageRow)
                        .where(SlidePageRow.task_id == task.id)
                        .with_for_update()
                    )
                ).all()
                by_page = {page.page_number: page for page in existing_rows}
                for slide in slides:
                    page = by_page.get(slide.page_number)
                    if page is None:
                        session.add(_slide_row(slide))
                    elif page.id != slide.id:
                        raise DomainError(
                            "SLIDE_PLAN_CONFLICT", "A saved page does not match the task plan."
                        )
                    else:
                        _apply_slide(page, slide)
                stale_pages = set(by_page) - set(page_numbers)
                if stale_pages:
                    await session.execute(
                        delete(SlidePageRow).where(
                            SlidePageRow.task_id == task.id,
                            SlidePageRow.page_number.in_(stale_pages),
                        )
                    )

            _apply_task(row, task)
            session.add(_revision_row(revision))


def _change_row(change: ChangeRequest) -> ChangeRequestRow:
    return ChangeRequestRow(
        id=change.id,
        task_id=change.task_id,
        source_message_id=change.source_message_id,
        target_type=change.target_type,
        target_ids=change.target_ids,
        affected_pages=change.affected_pages,
        operation=change.operation,
        instruction=change.instruction,
        replacement_text=change.replacement_text,
        impact_scope=change.impact_scope,
        risk_level=change.risk_level,
        needs_clarification=change.needs_clarification,
        clarification_question=change.clarification_question,
        status=change.status,
        expected_task_version=change.expected_task_version,
        created_at=change.created_at,
        resolved_at=change.resolved_at,
    )


def _apply_change(row: ChangeRequestRow, change: ChangeRequest) -> None:
    row.target_type = change.target_type
    row.target_ids = change.target_ids
    row.affected_pages = change.affected_pages
    row.operation = change.operation
    row.instruction = change.instruction
    row.replacement_text = change.replacement_text
    row.impact_scope = change.impact_scope
    row.risk_level = change.risk_level
    row.needs_clarification = change.needs_clarification
    row.clarification_question = change.clarification_question
    row.status = change.status
    row.expected_task_version = change.expected_task_version
    row.resolved_at = change.resolved_at


def _to_change(row: ChangeRequestRow) -> ChangeRequest:
    return ChangeRequest.model_validate(
        {
            "id": row.id,
            "task_id": row.task_id,
            "source_message_id": row.source_message_id,
            "target_type": row.target_type,
            "target_ids": row.target_ids,
            "affected_pages": row.affected_pages,
            "operation": row.operation,
            "instruction": row.instruction,
            "replacement_text": row.replacement_text,
            "impact_scope": row.impact_scope,
            "risk_level": row.risk_level,
            "needs_clarification": row.needs_clarification,
            "clarification_question": row.clarification_question,
            "status": row.status,
            "expected_task_version": row.expected_task_version,
            "created_at": row.created_at,
            "resolved_at": row.resolved_at,
        }
    )


def _slide_row(slide: SlideContent) -> SlidePageRow:
    return SlidePageRow(
        id=slide.id,
        task_id=slide.task_id,
        page_number=slide.page_number,
        section_id=slide.section_id,
        outline_item_id=slide.outline_item_id,
        title=slide.title,
        bullets=slide.bullets,
        speaker_notes=slide.speaker_notes,
        citations=[citation.model_dump(mode="json") for citation in slide.citations],
        verification_notes=slide.verification_notes,
    )


def _apply_slide(row: SlidePageRow, slide: SlideContent) -> None:
    from datetime import UTC, datetime

    row.section_id = slide.section_id
    row.outline_item_id = slide.outline_item_id
    row.title = slide.title
    row.bullets = slide.bullets
    row.speaker_notes = slide.speaker_notes
    row.citations = [citation.model_dump(mode="json") for citation in slide.citations]
    row.verification_notes = slide.verification_notes
    row.updated_at = datetime.now(UTC)


def _apply_task(row: GenerationTaskRow, task: TaskRecord) -> None:
    row.name = task.name
    row.status = task.status.value
    row.current_stage = task.current_stage
    row.raw_requirement = task.raw_requirement.model_dump(mode="json")
    row.model_preference = task.model_preference.model_dump(mode="json")
    row.complexity = task.complexity.model_dump(mode="json")
    row.structured_requirement = (
        task.structured_requirement.model_dump(mode="json")
        if task.structured_requirement is not None
        else None
    )
    row.outline = task.outline.model_dump(mode="json") if task.outline is not None else None
    row.generation_progress = (
        task.generation_progress.model_dump(mode="json")
        if task.generation_progress is not None
        else None
    )
    row.evaluation_result = (
        task.evaluation_result.model_dump(mode="json")
        if task.evaluation_result is not None
        else None
    )
    row.revision_count = task.revision_count
    row.version = task.version
    row.updated_at = task.updated_at


def _revision_row(revision: Revision) -> RevisionRow:
    return RevisionRow(
        id=revision.id,
        task_id=revision.task_id,
        revision_number=revision.revision_number,
        revision_type=revision.revision_type,
        scope=revision.scope,
        reason=revision.reason,
        before_slides=[slide.model_dump(mode="json") for slide in revision.before_slides],
        after_slides=[slide.model_dump(mode="json") for slide in revision.after_slides],
        before_outline=(
            revision.before_outline.model_dump(mode="json")
            if revision.before_outline is not None
            else None
        ),
        after_outline=(
            revision.after_outline.model_dump(mode="json")
            if revision.after_outline is not None
            else None
        ),
        score_before=revision.score_before,
        score_after=revision.score_after,
        created_at=revision.created_at,
    )
