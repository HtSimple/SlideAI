from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from slideai.api.dependencies_chat import get_chat_service
from slideai.application.chat.service import ChatService
from slideai.domain.changes.models import ChatMessage, ChatResult, ChatTarget

router = APIRouter(prefix="/api/v1/tasks", tags=["chat"])


class ChatMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    expected_task_version: int = Field(ge=1)
    target: ChatTarget | None = None


class ChatHistoryResponse(BaseModel):
    task_id: UUID
    items: list[ChatMessage]


@router.get("/{task_id}/chat/messages", response_model=ChatHistoryResponse)
async def list_chat_messages(
    task_id: UUID,
    service: Annotated[ChatService, Depends(get_chat_service)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ChatHistoryResponse:
    return ChatHistoryResponse(
        task_id=task_id,
        items=await service.history(task_id, offset=offset, limit=limit),
    )


@router.post("/{task_id}/chat/messages", response_model=ChatResult)
async def send_chat_message(
    task_id: UUID,
    body: ChatMessageRequest,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatResult:
    return await service.send_message(
        task_id,
        content=body.content,
        expected_task_version=body.expected_task_version,
        target=body.target,
    )
