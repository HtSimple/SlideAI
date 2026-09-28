from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PagePlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    page_number: int = Field(ge=1, le=50)
    section_id: str = Field(min_length=1, max_length=80)
    outline_item_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=1000)


class CitationReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: UUID


class SlideDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: int = Field(ge=1, le=50)
    title: str = Field(min_length=1, max_length=200)
    bullets: list[str] = Field(min_length=2, max_length=6)
    speaker_notes: str | None = Field(default=None, max_length=4000)
    citations: list[CitationReference] = Field(
        default_factory=lambda: list[CitationReference](), max_length=20
    )
    verification_notes: list[str] = Field(default_factory=lambda: list[str](), max_length=20)


class SlideBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    slides: list[SlideDraft] = Field(min_length=1, max_length=5)


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: UUID
    file_id: UUID
    display_name: str = Field(min_length=1, max_length=255)
    page_number: int | None = Field(default=None, ge=1)
    section_title: str | None = Field(default=None, max_length=500)
    excerpt: str = Field(min_length=1, max_length=280)


class SlideContent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    task_id: UUID
    page_number: int = Field(ge=1, le=50)
    section_id: str = Field(min_length=1, max_length=80)
    outline_item_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    bullets: list[str] = Field(min_length=2, max_length=6)
    speaker_notes: str | None = Field(default=None, max_length=4000)
    citations: list[Citation] = Field(default_factory=lambda: list[Citation](), max_length=20)
    verification_notes: list[str] = Field(default_factory=lambda: list[str](), max_length=20)


class SlideProgress(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_pages: int = Field(ge=0, le=50)
    completed_pages: int = Field(ge=0, le=50)
    total_batches: int = Field(ge=0, le=50)
    completed_batches: int = Field(ge=0, le=50)
    current_section_id: str | None = Field(default=None, max_length=80)
    current_batch_pages: list[int] = Field(default_factory=lambda: list[int](), max_length=5)
