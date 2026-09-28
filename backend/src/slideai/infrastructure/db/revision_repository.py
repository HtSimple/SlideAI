from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from slideai.domain.evaluation.models import Revision
from slideai.infrastructure.db.models import RevisionRow


class SqlRevisionRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def add(self, revision: Revision) -> None:
        async with self.sessions() as session, session.begin():
            session.add(
                RevisionRow(
                    id=revision.id,
                    task_id=revision.task_id,
                    revision_number=revision.revision_number,
                    revision_type=revision.revision_type,
                    scope=revision.scope,
                    reason=revision.reason,
                    before_slides=[item.model_dump(mode="json") for item in revision.before_slides],
                    after_slides=[item.model_dump(mode="json") for item in revision.after_slides],
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
            )

    async def list_for_task(self, task_id: UUID) -> list[Revision]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(RevisionRow)
                    .where(RevisionRow.task_id == task_id)
                    .order_by(RevisionRow.revision_number)
                )
            ).all()
            return [
                Revision.model_validate(
                    {
                        "id": row.id,
                        "task_id": row.task_id,
                        "revision_number": row.revision_number,
                        "revision_type": row.revision_type,
                        "scope": row.scope,
                        "reason": row.reason,
                        "before_slides": row.before_slides,
                        "after_slides": row.after_slides,
                        "before_outline": row.before_outline,
                        "after_outline": row.after_outline,
                        "score_before": row.score_before,
                        "score_after": row.score_after,
                        "created_at": row.created_at,
                    }
                )
                for row in rows
            ]

    async def next_revision_number(self, task_id: UUID) -> int:
        async with self.sessions() as session:
            current = await session.scalar(
                select(func.max(RevisionRow.revision_number)).where(RevisionRow.task_id == task_id)
            )
            return int(current or 0) + 1
