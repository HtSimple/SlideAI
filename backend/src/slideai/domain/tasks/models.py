from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from slideai.domain.content.models import SlideProgress
from slideai.domain.requirements.models import Outline, StructuredRequirement
from slideai.domain.tasks.complexity import TaskComplexity, score_complexity


class TaskStatus(StrEnum):
    DRAFT = "DRAFT"
    FILES_PROCESSING = "FILES_PROCESSING"
    READY = "READY"
    WAITING_REQUIREMENT_INPUT = "WAITING_REQUIREMENT_INPUT"
    WAITING_OUTLINE_CONFIRMATION = "WAITING_OUTLINE_CONFIRMATION"
    RUNNING = "RUNNING"
    WAITING_USER_FEEDBACK = "WAITING_USER_FEEDBACK"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class ModelPreference(BaseModel):
    mode: Literal["auto", "manual"] = "auto"
    model_key: str | None = None

    @model_validator(mode="after")
    def validate_model_choice(self) -> "ModelPreference":
        if self.mode == "manual" and not self.model_key:
            raise ValueError("model_key is required for manual model preference")
        if self.mode == "auto" and self.model_key is not None:
            raise ValueError("model_key is only allowed for manual model preference")
        return self


class RawRequirement(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    target_page_count: int = Field(ge=3, le=50)
    scenario: str = Field(default="", max_length=500)
    audience: str = Field(default="", max_length=500)
    style: str = Field(default="", max_length=200)
    special_constraints: list[str] = Field(default_factory=list)
    estimated_reference_tokens: int = Field(default=0, ge=0)
    original_text: str | None = Field(default=None, max_length=4000)


class CreateTaskCommand(BaseModel):
    raw_requirement: RawRequirement
    model_preference: ModelPreference = Field(default_factory=ModelPreference)


class TaskRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    name: str
    status: TaskStatus = TaskStatus.DRAFT
    current_stage: str | None = None
    raw_requirement: RawRequirement
    model_preference: ModelPreference
    complexity: TaskComplexity
    structured_requirement: StructuredRequirement | None = None
    outline: Outline | None = None
    generation_progress: SlideProgress | None = None
    version: int = 1
    created_at: datetime
    updated_at: datetime


class TaskPage(BaseModel):
    items: list[TaskRecord]
    total: int
    offset: int
    limit: int
    status_counts: dict[str, int] = Field(default_factory=dict)


def initial_complexity(requirement: RawRequirement) -> TaskComplexity:
    return score_complexity(
        target_page_count=requirement.target_page_count,
        estimated_reference_tokens=requirement.estimated_reference_tokens,
        constraint_count=len(requirement.special_constraints),
        domain_expertise="general",
        analysis_depth="overview",
    )
