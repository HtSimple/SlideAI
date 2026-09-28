from typing import Protocol
from uuid import UUID

from slideai.domain.content.models import SlideProgress


class ProgressRepository(Protocol):
    async def update_progress(
        self, task_id: UUID, progress: SlideProgress, *, fencing_generation: int
    ) -> None: ...


class TaskProgressReporter:
    def __init__(self, repository: ProgressRepository, *, fencing_generation: int) -> None:
        self.repository = repository
        self.fencing_generation = fencing_generation

    async def update(self, task_id: UUID, progress: SlideProgress) -> None:
        await self.repository.update_progress(
            task_id, progress, fencing_generation=self.fencing_generation
        )
