from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from slideai.api.dependencies import get_task_service
from slideai.application.tasks.service import TaskService
from slideai.domain.content.models import SlideProgress
from slideai.domain.models.catalog import ModelCatalog, PublicModel
from slideai.domain.tasks.models import (
    CreateTaskCommand,
    ModelPreference,
    RawRequirement,
    TaskPage,
    TaskRecord,
)

router = APIRouter(prefix="/api/v1", tags=["tasks"])


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    status: str
    current_stage: str | None
    raw_requirement: RawRequirement
    model_preference: ModelPreference
    complexity: dict[str, Any]
    structured_requirement: dict[str, Any] | None
    outline: dict[str, Any] | None
    generation_progress: SlideProgress | None
    version: int
    created_at: str
    updated_at: str


class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    total: int
    offset: int
    limit: int
    status_counts: dict[str, int]


class CreateTaskRequest(BaseModel):
    raw_requirement: RawRequirement
    model_preference: ModelPreference = Field(default_factory=ModelPreference)


class PatchTaskRequest(BaseModel):
    expected_version: int = Field(ge=0)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    raw_requirement: RawRequirement | None = None
    model_preference: ModelPreference | None = None


@router.get("/models", response_model=list[PublicModel])
async def list_models(request: Request) -> list[PublicModel]:
    catalog: ModelCatalog = request.app.state.model_catalog
    return catalog.public_models()


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    service: Annotated[TaskService, Depends(get_task_service)],
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    status: str | None = None,
    q: str | None = Query(default=None, max_length=200),
) -> TaskListResponse:
    page: TaskPage = await service.list_tasks(offset=offset, limit=limit, status=status, query=q)
    return TaskListResponse(
        items=[_task_response(task) for task in page.items],
        total=page.total,
        offset=page.offset,
        limit=page.limit,
        status_counts=page.status_counts,
    )


@router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(
    body: CreateTaskRequest, service: Annotated[TaskService, Depends(get_task_service)]
) -> TaskResponse:
    return _task_response(await service.create(CreateTaskCommand(**body.model_dump())))


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: UUID, service: Annotated[TaskService, Depends(get_task_service)]
) -> TaskResponse:
    return _task_response(await service.get(task_id))


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
async def patch_task(
    task_id: UUID,
    body: PatchTaskRequest,
    service: Annotated[TaskService, Depends(get_task_service)],
) -> TaskResponse:
    changes = body.model_dump(exclude={"expected_version"}, exclude_unset=True)
    return _task_response(
        await service.patch(task_id, expected_version=body.expected_version, changes=changes)
    )


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: UUID, service: Annotated[TaskService, Depends(get_task_service)]
) -> Response:
    await service.delete(task_id)
    return Response(status_code=204)


@router.get("/tasks/{task_id}/model-calls")
async def list_model_calls(task_id: UUID, request: Request) -> list[dict[str, Any]]:
    # The repository query itself is scoped by task_id, so foreign audit rows are never loaded.
    await request.app.state.task_service.get(task_id)
    repository = request.app.state.task_repository
    return await repository.list_model_calls(task_id)


def _task_response(task: TaskRecord) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        name=task.name,
        status=task.status.value,
        current_stage=task.current_stage,
        raw_requirement=task.raw_requirement,
        model_preference=task.model_preference,
        complexity=task.complexity.model_dump(mode="json"),
        structured_requirement=(
            task.structured_requirement.model_dump(mode="json")
            if task.structured_requirement is not None
            else None
        ),
        outline=task.outline.model_dump(mode="json") if task.outline is not None else None,
        generation_progress=task.generation_progress,
        version=task.version,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
    )
