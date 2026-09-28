from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from slideai.api.dependencies_workflows import (
    get_requirement_service,
    get_workflow_control_service,
)
from slideai.application.requirements.service import RequirementService
from slideai.application.workflows.service import WorkflowControlService
from slideai.domain.requirements.models import StructuredRequirement
from slideai.domain.tasks.models import TaskRecord

router = APIRouter(prefix="/api/v1/tasks", tags=["requirements"])


class WorkflowStateResponse(BaseModel):
    task_id: UUID
    status: str
    current_stage: str | None
    version: int


class RequirementResponse(BaseModel):
    task_id: UUID
    status: str
    version: int
    structured_requirement: StructuredRequirement | None
    missing_fields: list[str]


class UpdateRequirementRequest(BaseModel):
    expected_version: int = Field(ge=1)
    structured_requirement: StructuredRequirement


class ConfirmRequirementRequest(BaseModel):
    expected_version: int = Field(ge=1)


@router.post("/{task_id}/start", response_model=WorkflowStateResponse, status_code=202)
async def start_workflow(
    task_id: UUID,
    service: Annotated[WorkflowControlService, Depends(get_workflow_control_service)],
) -> WorkflowStateResponse:
    return _workflow_response(await service.start(task_id))


@router.get("/{task_id}/requirement", response_model=RequirementResponse)
async def get_requirement(
    task_id: UUID,
    service: Annotated[RequirementService, Depends(get_requirement_service)],
) -> RequirementResponse:
    task, missing = await service.get(task_id)
    return _requirement_response(task, missing)


@router.put("/{task_id}/requirement", response_model=RequirementResponse)
async def update_requirement(
    task_id: UUID,
    body: UpdateRequirementRequest,
    service: Annotated[RequirementService, Depends(get_requirement_service)],
) -> RequirementResponse:
    task = await service.update(
        task_id,
        expected_version=body.expected_version,
        requirement=body.structured_requirement,
    )
    return _requirement_response(task, body.structured_requirement.missing_fields())


@router.post(
    "/{task_id}/requirement/confirm", response_model=WorkflowStateResponse, status_code=202
)
async def confirm_requirement(
    task_id: UUID,
    body: ConfirmRequirementRequest,
    service: Annotated[RequirementService, Depends(get_requirement_service)],
) -> WorkflowStateResponse:
    return _workflow_response(
        await service.confirm(task_id, expected_version=body.expected_version)
    )


def _workflow_response(task: TaskRecord) -> WorkflowStateResponse:
    return WorkflowStateResponse(
        task_id=task.id,
        status=task.status.value,
        current_stage=task.current_stage,
        version=task.version,
    )


def _requirement_response(task: TaskRecord, missing: list[str]) -> RequirementResponse:
    return RequirementResponse(
        task_id=task.id,
        status=task.status.value,
        version=task.version,
        structured_requirement=task.structured_requirement,
        missing_fields=missing,
    )
