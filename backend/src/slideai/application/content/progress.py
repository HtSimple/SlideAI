from typing import Protocol
from uuid import UUID

from slideai.domain.content.models import SlideProgress


class ProgressRepository(Protocol):
    async def update_progress(self, task_id: UUID, progress: SlideProgress) -> None: ...


class TaskProgressReporter:
    def __init__(self, repository: ProgressRepository) -> None:
        self.repository = repository

    async def update(self, task_id: UUID, progress: SlideProgress) -> None:
        await self.repository.update_progress(task_id, progress)
