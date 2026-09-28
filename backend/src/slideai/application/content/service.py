from typing import Protocol
from uuid import UUID

from slideai.application.content.markdown import render_markdown
from slideai.core.errors import DomainError
from slideai.domain.content.models import SlideContent
from slideai.domain.tasks.models import TaskRecord


class TaskReader(Protocol):
    async def get(self, task_id: UUID) -> TaskRecord | None: ...


class SlideReader(Protocol):
    async def list_for_task(self, task_id: UUID) -> list[SlideContent]: ...


class SlideContentService:
    def __init__(self, tasks: TaskReader, slides: SlideReader) -> None:
        self.tasks = tasks
        self.slides = slides

    async def get_slides(self, task_id: UUID) -> tuple[TaskRecord, list[SlideContent]]:
        task = await self._get_task(task_id)
        return task, await self.slides.list_for_task(task_id)

    async def get_markdown(self, task_id: UUID) -> tuple[TaskRecord, str]:
        task = await self._get_task(task_id)
        if task.outline is None:
            raise DomainError("CONTENT_NOT_READY", "Slide content is not ready yet.")
        slides = await self.slides.list_for_task(task_id)
        if not slides:
            raise DomainError("CONTENT_NOT_READY", "Slide content is not ready yet.")
        return task, render_markdown(task.outline, slides)

    async def _get_task(self, task_id: UUID) -> TaskRecord:
        task = await self.tasks.get(task_id)
        if task is None:
            raise DomainError("TASK_NOT_FOUND", "Task was not found.")
        return task
