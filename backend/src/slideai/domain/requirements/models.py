from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StructuredRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str | None = Field(default=None, min_length=1, max_length=200)
    target_page_count: int | None = Field(default=None, ge=3, le=50)
    scenario: str | None = Field(default=None, max_length=500)
    audience: str | None = Field(default=None, max_length=500)
    style: str | None = Field(default=None, max_length=200)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    language: str = Field(default="zh-CN", min_length=2, max_length=20)
    source_usage: Literal["required", "preferred", "optional"] = "preferred"
    original_text: str | None = Field(default=None, max_length=4000)
    domain_expertise: Literal["general", "professional", "specialized"] = "general"
    analysis_depth: Literal["overview", "comparison", "strategic"] = "overview"

    def missing_fields(self) -> list[str]:
        required_fields = ("topic", "target_page_count", "scenario", "audience", "style")
        return [
            field
            for field in required_fields
            if (value := getattr(self, field)) is None
            or (isinstance(value, str) and not value.strip())
        ]


class OutlineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=1000)
    page_count: int = Field(ge=1, le=50)


class OutlineSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=1000)
    page_count: int = Field(ge=1, le=50)
    items: list[OutlineItem] = Field(min_length=1, max_length=50)


class Outline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    sections: list[OutlineSection] = Field(min_length=1, max_length=30)


class OutlineIssue(BaseModel):
    code: Literal[
        "PAGE_COUNT_MISMATCH",
        "SECTION_ITEM_COUNT_MISMATCH",
        "DUPLICATE_ID",
        "NO_SECTIONS",
    ]
    message: str = Field(min_length=1, max_length=500)
    target_id: str | None = Field(default=None, max_length=80)
