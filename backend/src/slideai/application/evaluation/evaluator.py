from collections.abc import Sequence
from uuid import UUID

from slideai.domain.content.models import SlideContent
from slideai.domain.evaluation.models import (
    EvaluationDraft,
    EvaluationIssue,
    EvaluationResult,
    HardCheck,
)
from slideai.domain.requirements.models import Outline, StructuredRequirement


def evaluate_quality(
    slides: Sequence[SlideContent],
    requirement: StructuredRequirement,
    outline: Outline,
    draft: EvaluationDraft,
    *,
    threshold: int = 85,
    allowed_chunk_ids: set[UUID] | None = None,
    hard_checks: list[HardCheck] | None = None,
) -> EvaluationResult:
    if hard_checks is None:
        from slideai.application.evaluation.checks import run_hard_checks

        hard_checks = run_hard_checks(
            slides,
            requirement,
            outline,
            allowed_chunk_ids=allowed_chunk_ids,
        )
    weighted_score = sum(item.score * item.weight for item in draft.dimensions) / 100
    total_score = int(weighted_score + 0.5)
    hard_issues = [
        EvaluationIssue(
            code=check.code,
            severity="blocking",
            scope=check.scope,
            description=check.description,
            suggestion="修复该项硬规则问题后重新运行质量评估。",
        )
        for check in hard_checks
        if not check.passed and check.blocking
    ]
    passed = total_score >= threshold and not hard_issues
    return EvaluationResult(
        total_score=total_score,
        passed=passed,
        threshold=threshold,
        hard_checks=hard_checks,
        dimensions=draft.dimensions,
        issues=[*hard_issues, *draft.issues],
        suggestions=draft.suggestions,
    )
