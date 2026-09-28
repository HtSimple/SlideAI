from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from slideai.api.dependencies_content import get_slide_content_service
from slideai.application.content.service import SlideContentService
from slideai.domain.content.models import SlideContent, SlideProgress

router = APIRouter(prefix="/api/v1/tasks", tags=["slides", "markdown"])


class SlideListResponse(BaseModel):
    task_id: UUID
    version: int
    target_page_count: int
    generation_progress: SlideProgress | None
    items: list[SlideContent]


class MarkdownResponse(BaseModel):
    task_id: UUID
    version: int
    markdown: str


@router.get("/{task_id}/slides", response_model=SlideListResponse)
async def get_slides(
    task_id: UUID,
    service: Annotated[SlideContentService, Depends(get_slide_content_service)],
) -> SlideListResponse:
    task, slides = await service.get_slides(task_id)
    target_page_count = (
        (task.structured_requirement.target_page_count or task.raw_requirement.target_page_count)
        if task.structured_requirement is not None
        else task.raw_requirement.target_page_count
    )
    return SlideListResponse(
        task_id=task.id,
        version=task.version,
        target_page_count=target_page_count,
        generation_progress=task.generation_progress,
        items=slides,
    )


@router.get("/{task_id}/markdown", response_model=MarkdownResponse)
async def get_markdown(
    task_id: UUID,
    service: Annotated[SlideContentService, Depends(get_slide_content_service)],
) -> MarkdownResponse:
    task, markdown = await service.get_markdown(task_id)
    return MarkdownResponse(task_id=task.id, version=task.version, markdown=markdown)


@router.get("/{task_id}/markdown/download")
async def download_markdown(
    task_id: UUID,
    service: Annotated[SlideContentService, Depends(get_slide_content_service)],
) -> Response:
    _, markdown = await service.get_markdown(task_id)
    return Response(
        content=markdown.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="slideai-export.md"'},
    )
