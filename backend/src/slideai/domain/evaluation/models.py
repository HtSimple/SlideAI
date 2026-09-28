from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from slideai.domain.content.models import SlideContent
from slideai.domain.requirements.models import Outline

DimensionName = Literal["completeness", "logic", "content_quality", "requirement_alignment"]


class HardCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str = Field(min_length=1, max_length=100)
    passed: bool
    blocking: bool = True
    description: str = Field(min_length=1, max_length=1000)
    scope: list[str] = Field(default_factory=list)


class DimensionScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: DimensionName
    score: int = Field(ge=0, le=100)
    weight: int = Field(default=25, ge=0, le=100)
    feedback: str = Field(min_length=1, max_length=1000)


class EvaluationIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str = Field(min_length=1, max_length=100)
    severity: Literal["low", "medium", "high", "blocking"]
    scope: list[str] = Field(default_factory=list, max_length=50)
    description: str = Field(min_length=1, max_length=1000)
    suggestion: str = Field(min_length=1, max_length=1000)


class EvaluationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dimensions: list[DimensionScore] = Field(min_length=4, max_length=4)
    issues: list[EvaluationIssue] = Field(
        default_factory=lambda: list[EvaluationIssue](), max_length=100
    )
    suggestions: list[str] = Field(default_factory=lambda: list[str](), max_length=50)

    @model_validator(mode="after")
    def validate_dimensions(self) -> "EvaluationDraft":
        expected = {
            "completeness",
            "logic",
            "content_quality",
            "requirement_alignment",
        }
        names = [dimension.name for dimension in self.dimensions]
        if set(names) != expected or len(names) != len(set(names)):
            raise ValueError("Evaluation must contain each quality dimension exactly once.")
        if any(dimension.weight != 25 for dimension in self.dimensions):
            raise ValueError("Each quality dimension must have an equal 25 percent weight.")
        return self


class EvaluationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_score: int = Field(ge=0, le=100)
    passed: bool
    threshold: int = Field(default=85, ge=0, le=100)
    hard_checks: list[HardCheck]
    dimensions: list[DimensionScore]
    issues: list[EvaluationIssue] = Field(default_factory=lambda: list[EvaluationIssue]())
    suggestions: list[str] = Field(default_factory=lambda: list[str]())


class SlideRevisionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    title: str = Field(min_length=1, max_length=200)
    bullets: list[str] = Field(min_length=2, max_length=6)
    speaker_notes: str | None = Field(default=None, max_length=4000)
    verification_notes: list[str] = Field(default_factory=list, max_length=20)


class SlideRefinementDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    slides: list[SlideRevisionDraft] = Field(min_length=1, max_length=50)


class Revision(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    revision_number: int = Field(ge=1)
    revision_type: Literal["AUTO", "USER", "CHAT", "UNDO"] = "AUTO"
    scope: list[str] = Field(max_length=50)
    reason: str = Field(min_length=1, max_length=2000)
    before_slides: list[SlideContent]
    after_slides: list[SlideContent]
    before_outline: Outline | None = None
    after_outline: Outline | None = None
    can_undo: bool = False
    score_before: int | None = Field(default=None, ge=0, le=100)
    score_after: int | None = Field(default=None, ge=0, le=100)
    created_at: datetime

    @model_validator(mode="after")
    def snapshots_match_task(self) -> "Revision":
        snapshots = [*self.before_slides, *self.after_slides]
        if any(slide.task_id != self.task_id for slide in snapshots):
            raise ValueError("Revision snapshots must belong to their task.")
        return self
