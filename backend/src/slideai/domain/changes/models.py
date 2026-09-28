from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from slideai.domain.evaluation.models import Revision

ChangeTargetType = Literal["outline_item", "section", "slide", "whole_deck"]
ChangeOperation = Literal["replace", "rewrite", "expand", "shorten", "reorder", "regenerate"]
ChangeRisk = Literal["local", "wide", "constraint_change"]
ChangeStatus = Literal[
    "NEEDS_CLARIFICATION",
    "NEEDS_CONFIRMATION",
    "APPLIED",
    "REJECTED",
    "SUPERSEDED",
]


class ChatTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_type: ChangeTargetType
    target_id: str | None = Field(default=None, min_length=1, max_length=100)
    label: str | None = Field(default=None, max_length=200)


class ChangeIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_type: ChangeTargetType
    target_ids: list[str] = Field(default_factory=list, max_length=50)
    operation: ChangeOperation
    instruction: str = Field(min_length=1, max_length=2000)
    replacement_text: str | None = Field(default=None, max_length=1000)
    risk_level: ChangeRisk = "local"
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=500)


class ChangeRequest(ChangeIntent):
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    source_message_id: UUID
    impact_scope: list[str] = Field(default_factory=list, max_length=100)
    affected_pages: list[int] = Field(default_factory=lambda: list[int](), max_length=50)
    status: ChangeStatus
    expected_task_version: int = Field(ge=1)
    created_at: datetime
    resolved_at: datetime | None = None


class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)
    target: ChatTarget | None = None
    change_request: ChangeRequest | None = None
    revision_id: UUID | None = None
    can_undo: bool = False
    created_at: datetime


class ChatResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: UUID
    status: ChangeStatus
    user_message: ChatMessage
    assistant_message: ChatMessage
    change_request: ChangeRequest
    revision_id: UUID | None = None
    task_version: int


class UndoResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: UUID
    revision: Revision
    task_version: int
    can_undo: bool
    assistant_message: ChatMessage
