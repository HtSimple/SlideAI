from uuid import UUID, uuid4

import pytest

from slideai.application.content.writer import (
    validate_slide_batch,
    write_slide_batches,
)
from slideai.domain.content.models import (
    PagePlan,
    SlideBatch,
    SlideDraft,
)
from slideai.domain.files.models import SourceCitation
from slideai.domain.requirements.models import (
    Outline,
    OutlineItem,
    OutlineSection,
    StructuredRequirement,
)


def _outline(page_count: int = 12) -> Outline:
    return Outline(
        title="产业分析",
        sections=[
            OutlineSection(
                id="market",
                title="市场概览",
                objective="说明市场变化和机会",
                page_count=page_count,
                items=[
                    OutlineItem(
                        id="signals",
                        title="变化信号",
                        objective="分析主要变化信号",
                        page_count=page_count,
                    )
                ],
            )
        ],
    )


def _requirement() -> StructuredRequirement:
    return StructuredRequirement(
        topic="产业分析",
        target_page_count=12,
        scenario="年度经营分析",
        audience="管理层",
        style="结论先行",
    )


class MemorySlideRepository:
    def __init__(self) -> None:
        self.slides = []
        self.writes: list[list[int]] = []

    async def list_for_task(self, task_id: UUID):
        return list(self.slides)

    async def upsert_batch(self, task_id: UUID, slides) -> None:
        self.writes.append([slide.page_number for slide in slides])
        by_page = {slide.page_number: slide for slide in self.slides}
        by_page.update({slide.page_number: slide for slide in slides})
        self.slides = sorted(by_page.values(), key=lambda slide: slide.page_number)


class EmptyRetriever:
    async def search(self, task_id: UUID, query: str):
        return []


class RecordingWriter:
    def __init__(self, *, fail_page: int | None = None) -> None:
        self.calls: list[list[int]] = []
        self.failed = False
        self.fail_page = fail_page

    async def write_batch(
        self,
        *,
        task_id,
        requirement,
        page_plans,
        sources_by_page,
        previous_summary,
        preference,
        complexity,
    ):
        page_numbers = [plan.page_number for plan in page_plans]
        self.calls.append(page_numbers)
        if self.fail_page in page_numbers and not self.failed:
            self.failed = True
            raise RuntimeError("temporary writer failure")
        return SlideBatch(
            slides=[
                SlideDraft(
                    page_number=plan.page_number,
                    title=plan.title,
                    bullets=["明确市场变化", "说明对应影响"],
                    speaker_notes=None,
                    citations=[],
                    verification_notes=[],
                )
                for plan in page_plans
            ]
        )


@pytest.mark.asyncio
async def test_writer_splits_sections_into_batches_of_five() -> None:
    task_id = uuid4()
    repository = MemorySlideRepository()
    writer = RecordingWriter()

    slides = await write_slide_batches(
        task_id=task_id,
        requirement=_requirement(),
        outline=_outline(),
        writer=writer,
        retriever=EmptyRetriever(),
        repository=repository,
    )

    assert writer.calls == [[1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [11, 12]]
    assert len(slides) == 12
    assert all(len(batch) <= 5 for batch in repository.writes)


@pytest.mark.asyncio
async def test_failed_batch_retries_without_rewriting_completed_batches() -> None:
    task_id = uuid4()
    repository = MemorySlideRepository()
    writer = RecordingWriter(fail_page=6)

    slides = await write_slide_batches(
        task_id=task_id,
        requirement=_requirement(),
        outline=_outline(),
        writer=writer,
        retriever=EmptyRetriever(),
        repository=repository,
        max_attempts=2,
    )

    assert writer.calls == [
        [1, 2, 3, 4, 5],
        [6, 7, 8, 9, 10],
        [6, 7, 8, 9, 10],
        [11, 12],
    ]
    assert repository.writes == [[1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [11, 12]]
    assert len(slides) == 12


def test_page_count_and_page_numbers_are_exact() -> None:
    plans = [
        PagePlan(
            page_number=1,
            section_id="market",
            outline_item_id="signals",
            title="变化信号",
            objective="分析变化",
        ),
        PagePlan(
            page_number=2,
            section_id="market",
            outline_item_id="signals",
            title="变化信号",
            objective="分析变化",
        ),
    ]
    output = SlideBatch(
        slides=[
            SlideDraft(
                page_number=1,
                title="第一页",
                bullets=["要点一", "要点二"],
            ),
            SlideDraft(
                page_number=3,
                title="跳号页面",
                bullets=["要点一", "要点二"],
            ),
        ]
    )

    with pytest.raises(ValueError, match="page numbers"):
        validate_slide_batch(task_id=uuid4(), page_plans=plans, output=output, sources_by_page={})


def test_unknown_citation_chunk_is_rejected() -> None:
    task_id = uuid4()
    chunk_id = uuid4()
    file_id = uuid4()
    source = SourceCitation(
        chunk_id=chunk_id,
        file_id=file_id,
        display_name="source.pdf",
        page_number=4,
        section_title=None,
        content="supported context",
        excerpt="supported context",
        similarity_score=0.91,
    )
    plan = PagePlan(
        page_number=1,
        section_id="market",
        outline_item_id="signals",
        title="变化信号",
        objective="分析变化",
    )
    output = SlideBatch(
        slides=[
            SlideDraft(
                page_number=1,
                title="变化信号",
                bullets=["要点一", "要点二"],
                citations=[{"chunk_id": str(uuid4())}],
            )
        ]
    )

    with pytest.raises(ValueError, match="retrieved sources"):
        validate_slide_batch(
            task_id=task_id,
            page_plans=[plan],
            output=output,
            sources_by_page={1: [source]},
        )


def test_markdown_snapshot_matches_slides() -> None:
    from slideai.application.content.markdown import render_markdown
    from slideai.domain.content.models import Citation, SlideContent

    task_id = UUID("00000000-0000-0000-0000-000000000001")
    outline = _outline(1)
    slides = [
        SlideContent(
            id=UUID("00000000-0000-0000-0000-000000000002"),
            task_id=task_id,
            page_number=1,
            section_id="market",
            outline_item_id="signals",
            title="市场变化",
            bullets=["需求持续增长", "供给侧加快调整"],
            speaker_notes="先说明核心变化。",
            citations=[
                Citation(
                    chunk_id=UUID("00000000-0000-0000-0000-000000000003"),
                    file_id=UUID("00000000-0000-0000-0000-000000000004"),
                    display_name="行业报告.pdf",
                    page_number=4,
                    section_title=None,
                    excerpt="行业规模持续增长。",
                )
            ],
            verification_notes=["核实最新市场规模。"],
        )
    ]

    markdown = render_markdown(outline, slides)

    assert markdown == (
        "# 产业分析\n\n"
        "## 市场概览\n\n"
        "### 第 1 页：市场变化\n\n"
        "- 需求持续增长\n"
        "- 供给侧加快调整\n\n"
        "**演讲备注**\n\n先说明核心变化。\n\n"
        "**资料来源**\n\n"
        "- [来源：行业报告.pdf，第 4 页] 行业规模持续增长。\n\n"
        "**待核实**\n\n"
        "- 核实最新市场规模。\n"
    )
