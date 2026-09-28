from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ComplexityTier(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    ADVANCED = "advanced"


class TaskComplexity(BaseModel):
    model_config = ConfigDict(frozen=True)

    tier: ComplexityTier
    total_score: int = Field(ge=0, le=10)
    factors: dict[str, int]


def score_complexity(
    *,
    target_page_count: int,
    estimated_reference_tokens: int,
    constraint_count: int,
    domain_expertise: Literal["general", "professional", "specialized"],
    analysis_depth: Literal["overview", "comparison", "strategic"],
) -> TaskComplexity:
    factors = {
        "target_page_count": 0 if target_page_count <= 8 else 1 if target_page_count <= 15 else 2,
        "estimated_reference_tokens": (
            0
            if estimated_reference_tokens <= 20_000
            else 1
            if estimated_reference_tokens <= 100_000
            else 2
        ),
        "constraint_count": 0 if constraint_count <= 2 else 1 if constraint_count <= 5 else 2,
        "domain_expertise": {"general": 0, "professional": 1, "specialized": 2}[domain_expertise],
        "analysis_depth": {"overview": 0, "comparison": 1, "strategic": 2}[analysis_depth],
    }
    score = sum(factors.values())
    tier = (
        ComplexityTier.FAST
        if score <= 3
        else ComplexityTier.BALANCED
        if score <= 6
        else ComplexityTier.ADVANCED
    )
    return TaskComplexity(tier=tier, total_score=score, factors=factors)
