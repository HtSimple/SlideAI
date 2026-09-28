from uuid import uuid4

import pytest

from slideai.application.evaluation.evaluator import evaluate_quality
from slideai.application.evaluation.refiner import merge_revised_slides
from slideai.domain.content.models import SlideContent
from slideai.domain.evaluation.models import EvaluationDraft
from slideai.domain.evaluation.policy import can_auto_refine
from slideai.domain.requirements.models import (
    Outline,
    OutlineItem,
    OutlineSection,
    StructuredRequirement,
)


def _fixture(
    *, outline_pages: int = 3
) -> tuple[list[SlideContent], StructuredRequirement, Outline]:
    task_id = uuid4()
    requirement = StructuredRequirement(
        topic="产业分析",
        target_page_count=3,
        scenario="年度经营分析",
        audience="管理层",
        style="结论先行",
    )
    outline = Outline(
        title="产业分析",
        sections=[
            OutlineSection(
                id="market",
                title="市场概览",
                objective="解释主要趋势",
                page_count=outline_pages,
                items=[
                    OutlineItem(
                        id="signals",
                        title="变化信号",
                        objective="分析市场变化",
                        page_count=outline_pages,
                    )
                ],
            )
        ],
    )
    slides = [
        SlideContent(
            id=uuid4(),
            task_id=task_id,
            page_number=page_number,
            section_id="market",
            outline_item_id="signals",
            title=f"市场变化 {page_number}",
            bullets=["市场需求持续增长", "供给结构正在调整"],
        )
        for page_number in range(1, 4)
    ]
    return slides, requirement, outline


def _draft(score: int) -> EvaluationDraft:
    return EvaluationDraft(
        dimensions=[
            {"name": "completeness", "score": score, "feedback": "覆盖完整"},
            {"name": "logic", "score": score, "feedback": "逻辑清晰"},
            {"name": "content_quality", "score": score, "feedback": "表达准确"},
            {"name": "requirement_alignment", "score": score, "feedback": "符合需求"},
        ],
        issues=[],
        suggestions=[],
    )


def test_hard_check_failure_forces_failed_evaluation() -> None:
    slides, requirement, outline = _fixture(outline_pages=2)

    result = evaluate_quality(slides, requirement, outline, _draft(100))

    assert result.total_score == 100
    assert result.passed is False
    assert any(not check.passed and check.blocking for check in result.hard_checks)


def test_score_threshold_is_eighty_five() -> None:
    slides, requirement, outline = _fixture()

    below = evaluate_quality(slides, requirement, outline, _draft(84))
    at_threshold = evaluate_quality(slides, requirement, outline, _draft(85))

    assert below.total_score == 84
    assert below.passed is False
    assert at_threshold.total_score == 85
    assert at_threshold.passed is True


def test_quality_dimensions_use_equal_weights() -> None:
    payload = _draft(90).model_dump()
    payload["dimensions"][0]["weight"] = 40
    payload["dimensions"][1]["weight"] = 10

    with pytest.raises(ValueError, match="equal 25 percent"):
        EvaluationDraft.model_validate(payload)


def test_auto_refinement_stops_after_two_attempts() -> None:
    slides, requirement, outline = _fixture()
    failed_result = evaluate_quality(slides, requirement, outline, _draft(84))

    assert can_auto_refine(failed_result, revision_count=0, max_auto_revisions=2)
    assert can_auto_refine(failed_result, revision_count=1, max_auto_revisions=2)
    assert not can_auto_refine(failed_result, revision_count=2, max_auto_revisions=2)


def test_refiner_preserves_out_of_scope_slides() -> None:
    slides, _, _ = _fixture()
    before = slides[1].model_dump(mode="json")
    revised_target = slides[0].model_copy(update={"title": "修订后的市场变化"})

    merged = merge_revised_slides(slides, [revised_target], {slides[0].id})

    assert merged[0].title == "修订后的市场变化"
    assert merged[1].model_dump(mode="json") == before
    assert merged[2] is slides[2]
