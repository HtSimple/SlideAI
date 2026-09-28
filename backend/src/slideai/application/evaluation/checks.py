from collections.abc import Sequence
from uuid import UUID

from slideai.domain.content.models import SlideContent
from slideai.domain.evaluation.models import HardCheck
from slideai.domain.requirements.models import Outline, StructuredRequirement


def run_hard_checks(
    slides: Sequence[SlideContent],
    requirement: StructuredRequirement,
    outline: Outline,
    *,
    allowed_chunk_ids: set[UUID] | None = None,
) -> list[HardCheck]:
    target_count = requirement.target_page_count or 0
    page_numbers = [slide.page_number for slide in slides]
    page_ids = [slide.id for slide in slides]
    expected_order = list(range(1, target_count + 1))
    checks = [
        HardCheck(
            code="PAGE_COUNT_MATCH",
            passed=len(slides) == target_count,
            description=f"页面数量应为 {target_count} 页，当前为 {len(slides)} 页。",
        ),
        HardCheck(
            code="PAGE_NUMBERS_CONTIGUOUS",
            passed=page_numbers == expected_order,
            description="页码必须从 1 开始连续递增至目标页数。",
            scope=[str(slide.id) for slide in slides],
        ),
        HardCheck(
            code="UNIQUE_PAGE_IDS",
            passed=len(page_ids) == len(set(page_ids)),
            description="每个页面必须拥有唯一且稳定的 ID。",
        ),
        HardCheck(
            code="PAGE_CONTENT_SHAPE",
            passed=all(slide.title.strip() and 2 <= len(slide.bullets) <= 6 for slide in slides),
            description="每页必须有标题及 2 到 6 条核心要点。",
            scope=[
                str(slide.id)
                for slide in slides
                if not slide.title.strip() or not 2 <= len(slide.bullets) <= 6
            ],
        ),
    ]

    outline_count = sum(section.page_count for section in outline.sections)
    item_counts_match = all(
        sum(item.page_count for item in section.items) == section.page_count
        for section in outline.sections
    )
    allocation_matches = outline_count == target_count and item_counts_match
    checks.append(
        HardCheck(
            code="OUTLINE_PAGE_ALLOCATION",
            passed=allocation_matches,
            description="大纲章节及子项的页面分配之和必须等于目标页数。",
        )
    )

    expected_pages: dict[int, tuple[str, str]] = {}
    next_page = 1
    for section in outline.sections:
        for item in section.items:
            for page_number in range(next_page, next_page + item.page_count):
                expected_pages[page_number] = (section.id, item.id)
            next_page += item.page_count
    mapping_errors = [
        slide
        for slide in slides
        if expected_pages.get(slide.page_number) != (slide.section_id, slide.outline_item_id)
    ]
    checks.append(
        HardCheck(
            code="OUTLINE_CONTENT_ALIGNMENT",
            passed=not mapping_errors,
            description="页面的章节和大纲项必须与已确认的大纲分配一致。",
            scope=[str(slide.id) for slide in mapping_errors],
        )
    )

    all_text_parts = [outline.title]
    for slide in slides:
        all_text_parts.extend([slide.title, *slide.bullets])
    all_text = "\n".join(all_text_parts).casefold()
    missing_keywords = [
        keyword
        for keyword in requirement.required_keywords
        if keyword.casefold().strip() not in all_text
    ]
    checks.append(
        HardCheck(
            code="REQUIRED_KEYWORDS_PRESENT",
            passed=not missing_keywords,
            description=(
                "必需关键词均须在页面内容中出现。"
                if not missing_keywords
                else f"缺少必需关键词：{'、'.join(missing_keywords)}。"
            ),
            scope=[str(slide.id) for slide in slides],
        )
    )

    citation_errors = [
        slide
        for slide in slides
        if allowed_chunk_ids is not None
        and any(citation.chunk_id not in allowed_chunk_ids for citation in slide.citations)
    ]
    checks.append(
        HardCheck(
            code="CITATIONS_TASK_SCOPED",
            passed=not citation_errors,
            description="所有资料引用都必须来自当前任务的检索片段。",
            scope=[str(slide.id) for slide in citation_errors],
        )
    )
    return checks
