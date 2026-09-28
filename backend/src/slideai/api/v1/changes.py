from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from slideai.api.dependencies_chat import get_chat_service
from slideai.application.chat.service import ChatService
from slideai.domain.changes.models import ChatResult, UndoResult

router = APIRouter(prefix="/api/v1/tasks", tags=["changes", "revisions"])


class ChangeConfirmationRequest(BaseModel):
    expected_task_version: int = Field(ge=1)


class UndoRequest(BaseModel):
    expected_task_version: int = Field(ge=1)


@router.post("/{task_id}/changes/{change_id}/confirm", response_model=ChatResult)
async def confirm_chat_change(
    task_id: UUID,
    change_id: UUID,
    body: ChangeConfirmationRequest,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatResult:
    return await service.confirm_change(
        task_id,
        change_id=change_id,
        expected_task_version=body.expected_task_version,
    )


@router.post(
    "/{task_id}/revisions/{revision_id}/undo",
    response_model=UndoResult,
)
async def undo_chat_change(
    task_id: UUID,
    revision_id: UUID,
    body: UndoRequest,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> UndoResult:
    return await service.undo(
        task_id,
        revision_id=revision_id,
        expected_task_version=body.expected_task_version,
    )
