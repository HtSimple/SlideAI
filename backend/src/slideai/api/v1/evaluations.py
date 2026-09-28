from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from slideai.api.dependencies import get_task_service
from slideai.api.dependencies_workflows import get_workflow_control_service
from slideai.application.tasks.service import TaskService
from slideai.application.workflows.service import WorkflowControlService
from slideai.core.errors import DomainError
from slideai.domain.evaluation.models import EvaluationResult, Revision

router = APIRouter(prefix="/api/v1/tasks", tags=["evaluation", "revisions"])


class EvaluationResponse(BaseModel):
    task_id: UUID
    version: int
    revision_count: int
    evaluation_result: EvaluationResult


class RevisionListResponse(BaseModel):
    task_id: UUID
    items: list[Revision]


class EvaluationDecisionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    action: Literal["accept", "refine", "cancel"]
    feedback: str | None = Field(default=None, max_length=2000)
    scope: list[str] = Field(default_factory=list, max_length=50)


class EvaluationDecisionResponse(BaseModel):
    task_id: UUID
    status: str
    current_stage: str | None
    version: int


@router.get("/{task_id}/evaluation", response_model=EvaluationResponse)
async def get_evaluation(
    task_id: UUID,
    tasks: Annotated[TaskService, Depends(get_task_service)],
) -> EvaluationResponse:
    task = await tasks.get(task_id)
    if task.evaluation_result is None:
        raise DomainError("EVALUATION_NOT_READY", "The task has no evaluation result yet.")
    return EvaluationResponse(
        task_id=task.id,
        version=task.version,
        revision_count=task.revision_count,
        evaluation_result=task.evaluation_result,
    )


@router.get("/{task_id}/revisions", response_model=RevisionListResponse)
async def list_revisions(
    task_id: UUID,
    request: Request,
    tasks: Annotated[TaskService, Depends(get_task_service)],
) -> RevisionListResponse:
    await tasks.get(task_id)
    revisions = await request.app.state.revision_repository.list_for_task(task_id)
    latest_id = None
    if revisions and revisions[-1].revision_type in {"CHAT", "USER"}:
        latest_id = revisions[-1].id
    return RevisionListResponse(
        task_id=task_id,
        items=[
            revision.model_copy(update={"can_undo": revision.id == latest_id})
            for revision in revisions
        ],
    )


@router.post(
    "/{task_id}/evaluation/decision",
    response_model=EvaluationDecisionResponse,
    status_code=202,
)
async def decide_evaluation(
    task_id: UUID,
    body: EvaluationDecisionRequest,
    request: Request,
    service: Annotated[WorkflowControlService, Depends(get_workflow_control_service)],
) -> EvaluationDecisionResponse:
    if body.action == "refine" and not (body.feedback and body.feedback.strip()):
        raise DomainError("VALIDATION_ERROR", "Feedback is required for a targeted refinement.")
    if body.action == "refine" and body.scope:
        slides = await request.app.state.slide_repository.list_for_task(task_id)
        known_ids = {str(slide.id) for slide in slides}
        if not set(body.scope).issubset(known_ids):
            raise DomainError(
                "SLIDE_REVISION_SCOPE_INVALID",
                "A refinement scope must reference pages in this task.",
            )
    task = await service.decide_evaluation(
        task_id,
        expected_version=body.expected_version,
        decision=body.model_dump(exclude={"expected_version"}),
    )
    return EvaluationDecisionResponse(
        task_id=task.id,
        status=task.status.value,
        current_stage=task.current_stage,
        version=task.version,
    )
