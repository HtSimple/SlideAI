from slideai.domain.requirements.models import (
    Outline,
    OutlineItem,
    OutlineSection,
    StructuredRequirement,
)
from slideai.domain.requirements.validation import validate_outline


def test_outline_page_allocation_must_equal_target() -> None:
    outline = Outline(
        title="Strategy",
        sections=[
            OutlineSection(
                id="section-1",
                title="Market",
                objective="Explain the market",
                page_count=4,
                items=[
                    OutlineItem(
                        id="item-1",
                        title="Market size",
                        objective="Show current scale",
                        page_count=4,
                    )
                ],
            )
        ],
    )

    issues = validate_outline(outline, target_page_count=5)

    assert [issue.code for issue in issues] == ["PAGE_COUNT_MISMATCH"]


def test_outline_requires_section_and_item_allocations_to_match() -> None:
    outline = Outline(
        title="Strategy",
        sections=[
            OutlineSection(
                id="section-1",
                title="Market",
                objective="Explain the market",
                page_count=4,
                items=[
                    OutlineItem(
                        id="item-1",
                        title="Market size",
                        objective="Show current scale",
                        page_count=3,
                    )
                ],
            )
        ],
    )

    issues = validate_outline(outline, target_page_count=4)

    assert [(issue.code, issue.target_id) for issue in issues] == [
        ("SECTION_ITEM_COUNT_MISMATCH", "section-1")
    ]


def test_structured_requirement_keeps_unknown_fields_for_clarification() -> None:
    requirement = StructuredRequirement(
        topic="Strategy update",
        target_page_count=12,
        scenario=None,
        audience="",
        style=None,
    )

    assert requirement.missing_fields() == ["scenario", "audience", "style"]
