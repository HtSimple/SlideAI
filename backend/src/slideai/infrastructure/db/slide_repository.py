from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from slideai.core.errors import DomainError
from slideai.domain.content.models import Citation, SlideContent
from slideai.infrastructure.db.models import GenerationTaskRow, SlidePageRow


class SqlSlideRepository:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        require_running: bool = False,
        fencing_generation: int | None = None,
    ) -> None:
        self.sessions = sessions
        self.require_running = require_running
        self.fencing_generation = fencing_generation

    async def list_for_task(self, task_id: UUID) -> list[SlideContent]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(SlidePageRow)
                    .where(SlidePageRow.task_id == task_id)
                    .order_by(SlidePageRow.page_number)
                )
            ).all()
            return [_to_content(row) for row in rows]

    async def upsert_batch(self, task_id: UUID, slides: list[SlideContent]) -> None:
        if any(slide.task_id != task_id for slide in slides):
            raise DomainError("TASK_SCOPE_VIOLATION", "A page belongs to a different task.")
        if not slides:
            return

        page_numbers = [slide.page_number for slide in slides]
        if len(page_numbers) != len(set(page_numbers)):
            raise DomainError("SLIDE_BATCH_INVALID", "A batch cannot contain duplicate pages.")

        async with self.sessions() as session, session.begin():
            if self.require_running:
                task = await session.get(GenerationTaskRow, task_id, with_for_update=True)
                if task is None:
                    raise DomainError("TASK_NOT_FOUND", "Task was not found.")
                if task.status == "CANCELLED":
                    raise DomainError("WORKFLOW_CANCELLED", "The task was cancelled.")
                if task.status != "RUNNING":
                    raise DomainError(
                        "TASK_CONFLICT", "A slide batch can only be saved by a running task."
                    )
                if (
                    self.fencing_generation is None
                    or task.workflow_fencing_generation != self.fencing_generation
                ):
                    raise DomainError(
                        "WORKFLOW_LOCK_LOST", "The workflow worker lost its task lock."
                    )

            rows = (
                await session.scalars(
                    select(SlidePageRow)
                    .where(
                        SlidePageRow.task_id == task_id,
                        SlidePageRow.page_number.in_(page_numbers),
                    )
                    .with_for_update()
                )
            ).all()
            by_page = {row.page_number: row for row in rows}
            for slide in slides:
                row = by_page.get(slide.page_number)
                if row is None:
                    session.add(_to_row(slide))
                elif row.id != slide.id:
                    raise DomainError(
                        "SLIDE_PLAN_CONFLICT", "A saved page does not match the task plan."
                    )
                else:
                    _apply(row, slide)


def _to_row(slide: SlideContent) -> SlidePageRow:
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
        updated_at=datetime.now(UTC),
    )


def _apply(row: SlidePageRow, slide: SlideContent) -> None:
    row.section_id = slide.section_id
    row.outline_item_id = slide.outline_item_id
    row.title = slide.title
    row.bullets = slide.bullets
    row.speaker_notes = slide.speaker_notes
    row.citations = [citation.model_dump(mode="json") for citation in slide.citations]
    row.verification_notes = slide.verification_notes
    row.updated_at = datetime.now(UTC)


def _to_content(row: SlidePageRow) -> SlideContent:
    return SlideContent(
        id=row.id,
        task_id=row.task_id,
        page_number=row.page_number,
        section_id=row.section_id,
        outline_item_id=row.outline_item_id,
        title=row.title,
        bullets=row.bullets,
        speaker_notes=row.speaker_notes,
        citations=[Citation.model_validate(citation) for citation in row.citations],
        verification_notes=row.verification_notes,
    )
