from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from slideai.api.dependencies_workflows import get_outline_service
from slideai.application.outlines.service import OutlineService
from slideai.domain.requirements.models import Outline
from slideai.domain.tasks.models import TaskRecord

router = APIRouter(prefix="/api/v1/tasks", tags=["outlines"])


class OutlineResponse(BaseModel):
    task_id: UUID
    status: str
    version: int
    outline: Outline | None
    issues: list[dict[str, Any]]


class UpdateOutlineRequest(BaseModel):
    expected_version: int = Field(ge=1)
    outline: Outline


class ConfirmOutlineRequest(BaseModel):
    expected_version: int = Field(ge=1)


class WorkflowStateResponse(BaseModel):
    task_id: UUID
    status: str
    current_stage: str | None
    version: int


@router.get("/{task_id}/outline", response_model=OutlineResponse)
async def get_outline(
    task_id: UUID,
    service: Annotated[OutlineService, Depends(get_outline_service)],
) -> OutlineResponse:
    task, issues = await service.get(task_id)
    return _outline_response(task, issues)


@router.put("/{task_id}/outline", response_model=OutlineResponse)
async def update_outline(
    task_id: UUID,
    body: UpdateOutlineRequest,
    service: Annotated[OutlineService, Depends(get_outline_service)],
) -> OutlineResponse:
    task = await service.update(
        task_id,
        expected_version=body.expected_version,
        outline=body.outline,
    )
    return _outline_response(task, [])


@router.post("/{task_id}/outline/confirm", response_model=WorkflowStateResponse, status_code=202)
async def confirm_outline(
    task_id: UUID,
    body: ConfirmOutlineRequest,
    service: Annotated[OutlineService, Depends(get_outline_service)],
) -> WorkflowStateResponse:
    task = await service.confirm(task_id, expected_version=body.expected_version)
    return WorkflowStateResponse(
        task_id=task.id,
        status=task.status.value,
        current_stage=task.current_stage,
        version=task.version,
    )


def _outline_response(task: TaskRecord, issues: list[dict[str, Any]]) -> OutlineResponse:
    return OutlineResponse(
        task_id=task.id,
        status=task.status.value,
        version=task.version,
        outline=task.outline,
        issues=issues,
    )
