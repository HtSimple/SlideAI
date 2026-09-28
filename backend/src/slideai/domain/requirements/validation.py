from collections import Counter

from slideai.domain.requirements.models import Outline, OutlineIssue


def validate_outline(outline: Outline, target_page_count: int) -> list[OutlineIssue]:
    issues: list[OutlineIssue] = []
    allocated = sum(section.page_count for section in outline.sections)
    if allocated != target_page_count:
        issues.append(
            OutlineIssue(
                code="PAGE_COUNT_MISMATCH",
                message=(
                    f"The outline allocates {allocated} pages, but the task requires "
                    f"{target_page_count}."
                ),
            )
        )

    for section in outline.sections:
        item_pages = sum(item.page_count for item in section.items)
        if item_pages != section.page_count:
            issues.append(
                OutlineIssue(
                    code="SECTION_ITEM_COUNT_MISMATCH",
                    message=(
                        f"Section '{section.title}' allocates {section.page_count} pages, "
                        f"but its items allocate {item_pages}."
                    ),
                    target_id=section.id,
                )
            )

    ids = [section.id for section in outline.sections]
    ids.extend(item.id for section in outline.sections for item in section.items)
    for duplicate_id, count in Counter(ids).items():
        if count > 1:
            issues.append(
                OutlineIssue(
                    code="DUPLICATE_ID",
                    message=f"Outline ID '{duplicate_id}' is used more than once.",
                    target_id=duplicate_id,
                )
            )
    return issues
