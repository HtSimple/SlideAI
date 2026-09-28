from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from slideai.core.errors import DomainError
from slideai.domain.content.models import SlideContent
from slideai.domain.evaluation.models import SlideRevisionDraft

RefineSlides = Callable[
    [list[SlideContent], list[dict[str, object]], str], Awaitable[list[SlideRevisionDraft]]
]


async def refine_content(
    current: Sequence[SlideContent],
    scope: set[UUID],
    feedback: str,
    refiner: RefineSlides,
) -> list[SlideContent]:
    if not scope:
        raise DomainError("SLIDE_REVISION_SCOPE_INVALID", "A refinement scope is required.")
    by_id = {slide.id: slide for slide in current}
    if not scope.issubset(by_id):
        raise DomainError("SLIDE_REVISION_SCOPE_INVALID", "The refinement scope is unknown.")
    selected = [slide for slide in current if slide.id in scope]
    selected_pages = {slide.page_number for slide in selected}
    neighbors: list[dict[str, object]] = [
        {
            "page_number": slide.page_number,
            "title": slide.title,
            "bullets": slide.bullets,
        }
        for slide in current
        if slide.id not in scope
        and any(abs(slide.page_number - page) == 1 for page in selected_pages)
    ]
    outputs = await refiner(selected, neighbors, feedback)
    output_ids = [item.id for item in outputs]
    if len(output_ids) != len(set(output_ids)) or set(output_ids) != scope:
        raise DomainError(
            "SLIDE_REVISION_SCOPE_INVALID",
            "A refinement must return exactly the requested pages.",
        )
    updates = {
        item.id: by_id[item.id].model_copy(
            update={
                "title": item.title,
                "bullets": item.bullets,
                "speaker_notes": item.speaker_notes,
                "verification_notes": item.verification_notes,
            }
        )
        for item in outputs
    }
    return merge_revised_slides(current, list(updates.values()), scope)


def merge_revised_slides(
    current: Sequence[SlideContent],
    revised: Sequence[SlideContent],
    scope: set[UUID],
) -> list[SlideContent]:
    current_by_id = {slide.id: slide for slide in current}
    if len(current_by_id) != len(current):
        raise DomainError("SLIDE_REVISION_INVALID", "Current slide IDs must be unique.")
    revised_by_id = {slide.id: slide for slide in revised}
    if len(revised_by_id) != len(revised) or set(revised_by_id) != scope:
        raise DomainError(
            "SLIDE_REVISION_SCOPE_INVALID", "A refinement must return exactly the requested pages."
        )
    if not scope.issubset(current_by_id):
        raise DomainError("SLIDE_REVISION_SCOPE_INVALID", "The refinement scope is unknown.")

    merged: list[SlideContent] = []
    for before in current:
        after = revised_by_id.get(before.id)
        if after is None:
            merged.append(before)
            continue
        if (after.task_id, after.page_number) != (before.task_id, before.page_number):
            raise DomainError(
                "SLIDE_REVISION_IDENTITY_INVALID",
                "A refinement cannot change task or page identity.",
            )
        merged.append(after)
    return merged
