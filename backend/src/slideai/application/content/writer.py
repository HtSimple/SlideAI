from collections.abc import Sequence
from typing import Protocol
from uuid import UUID, uuid5

from slideai.core.errors import DomainError
from slideai.domain.content.models import (
    Citation,
    PagePlan,
    SlideBatch,
    SlideContent,
    SlideProgress,
)
from slideai.domain.files.models import SourceCitation
from slideai.domain.requirements.models import Outline, StructuredRequirement
from slideai.domain.requirements.validation import validate_outline
from slideai.domain.tasks.complexity import ComplexityTier, TaskComplexity
from slideai.domain.tasks.models import ModelPreference


class BatchWriter(Protocol):
    async def write_batch(
        self,
        *,
        task_id: UUID,
        requirement: StructuredRequirement,
        page_plans: list[PagePlan],
        sources_by_page: dict[int, list[SourceCitation]],
        previous_summary: str,
        preference: ModelPreference,
        complexity: TaskComplexity,
    ) -> SlideBatch: ...


class PageRetriever(Protocol):
    async def search(self, task_id: UUID, query: str) -> list[SourceCitation]: ...


class SlideRepository(Protocol):
    async def list_for_task(self, task_id: UUID) -> list[SlideContent]: ...

    async def upsert_batch(self, task_id: UUID, slides: list[SlideContent]) -> None: ...


class ProgressReporter(Protocol):
    async def update(self, task_id: UUID, progress: SlideProgress) -> None: ...


async def write_slide_batches(
    *,
    task_id: UUID,
    requirement: StructuredRequirement,
    outline: Outline,
    writer: BatchWriter,
    retriever: PageRetriever,
    repository: SlideRepository,
    preference: ModelPreference | None = None,
    complexity: TaskComplexity | None = None,
    progress_reporter: ProgressReporter | None = None,
    max_batch_size: int = 5,
    max_attempts: int = 2,
) -> list[SlideContent]:
    if not 1 <= max_batch_size <= 5:
        raise ValueError("max_batch_size must be between one and five")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least one")
    target_page_count = requirement.target_page_count
    if target_page_count is None:
        raise DomainError("REQUIREMENT_INCOMPLETE", "A target page count is required.")
    issues = validate_outline(outline, target_page_count)
    if issues:
        raise DomainError(
            "OUTLINE_INVALID",
            "Fix the outline before writing slide content.",
            [issue.model_dump(mode="json") for issue in issues],
        )

    plans = _page_plans(outline)
    batches = [
        batch for section in _section_plans(plans) for batch in _chunks(section, max_batch_size)
    ]
    existing = await repository.list_for_task(task_id)
    existing_by_page = {slide.page_number: slide for slide in existing}
    if set(existing_by_page) - {plan.page_number for plan in plans}:
        raise DomainError("SLIDE_PLAN_CONFLICT", "Saved pages do not match the current outline.")

    await _report_progress(
        progress_reporter,
        task_id,
        SlideProgress(
            total_pages=len(plans),
            completed_pages=len(existing_by_page),
            total_batches=len(batches),
            completed_batches=sum(
                all(plan.page_number in existing_by_page for plan in batch) for batch in batches
            ),
        ),
    )

    completed_batches = sum(
        all(plan.page_number in existing_by_page for plan in batch) for batch in batches
    )
    for batch in batches:
        pending = [plan for plan in batch if plan.page_number not in existing_by_page]
        if not pending:
            continue

        sources_by_page: dict[int, list[SourceCitation]] = {}
        for plan in pending:
            query = " ".join(
                (
                    requirement.topic or "",
                    _section_title(outline, plan.section_id),
                    plan.title,
                    plan.objective,
                )
            )
            sources_by_page[plan.page_number] = await retriever.search(task_id, query)

        previous_summary = _previous_summary(existing_by_page)
        await _report_progress(
            progress_reporter,
            task_id,
            SlideProgress(
                total_pages=len(plans),
                completed_pages=len(existing_by_page),
                total_batches=len(batches),
                completed_batches=completed_batches,
                current_section_id=pending[0].section_id,
                current_batch_pages=[plan.page_number for plan in pending],
            ),
        )

        last_error: Exception | None = None
        generated: list[SlideContent] | None = None
        for _attempt in range(max_attempts):
            try:
                output = await writer.write_batch(
                    task_id=task_id,
                    requirement=requirement,
                    page_plans=pending,
                    sources_by_page=sources_by_page,
                    previous_summary=previous_summary,
                    preference=preference or ModelPreference(),
                    complexity=complexity
                    or TaskComplexity(tier=ComplexityTier.FAST, total_score=0, factors={}),
                )
                generated = validate_slide_batch(
                    task_id=task_id,
                    page_plans=pending,
                    output=output,
                    sources_by_page=sources_by_page,
                )
                break
            except Exception as error:
                last_error = error
        if generated is None:
            assert last_error is not None
            raise last_error

        await repository.upsert_batch(task_id, generated)
        existing_by_page.update({slide.page_number: slide for slide in generated})
        completed_batches += 1
        await _report_progress(
            progress_reporter,
            task_id,
            SlideProgress(
                total_pages=len(plans),
                completed_pages=len(existing_by_page),
                total_batches=len(batches),
                completed_batches=completed_batches,
                current_section_id=pending[0].section_id,
            ),
        )

    result = [existing_by_page[plan.page_number] for plan in plans]
    _validate_page_sequence(result, target_page_count)
    return result


def validate_slide_batch(
    *,
    task_id: UUID,
    page_plans: Sequence[PagePlan],
    output: SlideBatch,
    sources_by_page: dict[int, list[SourceCitation]],
) -> list[SlideContent]:
    expected = [plan.page_number for plan in page_plans]
    actual = [slide.page_number for slide in output.slides]
    if actual != expected:
        raise ValueError(f"Slide batch page numbers must exactly match {expected}.")

    validated: list[SlideContent] = []
    for plan, draft in zip(page_plans, output.slides, strict=True):
        available = {
            source.chunk_id: source for source in sources_by_page.get(plan.page_number, [])
        }
        citations: list[Citation] = []
        for reference in draft.citations:
            source = available.get(reference.chunk_id)
            if source is None:
                raise ValueError("Slide citations must reference retrieved sources for this page.")
            citations.append(
                Citation(
                    chunk_id=source.chunk_id,
                    file_id=source.file_id,
                    display_name=source.display_name,
                    page_number=source.page_number,
                    section_title=source.section_title,
                    excerpt=source.excerpt,
                )
            )
        validated.append(
            SlideContent(
                id=uuid5(task_id, f"slide-page:{plan.page_number}"),
                task_id=task_id,
                page_number=plan.page_number,
                section_id=plan.section_id,
                outline_item_id=plan.outline_item_id,
                title=draft.title,
                bullets=draft.bullets,
                speaker_notes=draft.speaker_notes,
                citations=citations,
                verification_notes=draft.verification_notes,
            )
        )
    return validated


def _page_plans(outline: Outline) -> list[PagePlan]:
    plans: list[PagePlan] = []
    for section in outline.sections:
        for item in section.items:
            for _ in range(item.page_count):
                plans.append(
                    PagePlan(
                        page_number=len(plans) + 1,
                        section_id=section.id,
                        outline_item_id=item.id,
                        title=item.title,
                        objective=item.objective,
                    )
                )
    return plans


def _section_plans(plans: list[PagePlan]) -> list[list[PagePlan]]:
    sections: list[list[PagePlan]] = []
    for plan in plans:
        if not sections or sections[-1][0].section_id != plan.section_id:
            sections.append([])
        sections[-1].append(plan)
    return sections


def _chunks(plans: list[PagePlan], size: int) -> list[list[PagePlan]]:
    return [plans[index : index + size] for index in range(0, len(plans), size)]


def _section_title(outline: Outline, section_id: str) -> str:
    return next(section.title for section in outline.sections if section.id == section_id)


def _previous_summary(slides_by_page: dict[int, SlideContent]) -> str:
    previous = sorted(slides_by_page.values(), key=lambda slide: slide.page_number)[-5:]
    return "\n".join(
        f"{slide.page_number}. {slide.title}: {slide.bullets[0]}" for slide in previous
    )


async def _report_progress(
    reporter: ProgressReporter | None, task_id: UUID, progress: SlideProgress
) -> None:
    if reporter is not None:
        await reporter.update(task_id, progress)


def _validate_page_sequence(slides: list[SlideContent], target_page_count: int) -> None:
    actual = [slide.page_number for slide in slides]
    expected = list(range(1, target_page_count + 1))
    if actual != expected:
        raise DomainError(
            "SLIDE_PAGE_SEQUENCE_INVALID",
            "Generated slide page numbers must be continuous and match the target count.",
            {"expected": expected, "actual": actual},
        )
