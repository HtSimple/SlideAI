from slideai.domain.evaluation.models import EvaluationResult


def can_auto_refine(
    result: EvaluationResult, *, revision_count: int, max_auto_revisions: int
) -> bool:
    return not result.passed and 0 <= revision_count < max_auto_revisions
