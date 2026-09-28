from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from slideai.api.dependencies import get_task_service
from slideai.api.main import create_app
from slideai.application.content.service import SlideContentService
from slideai.application.tasks.service import TaskService
from slideai.domain.content.models import SlideContent, SlideProgress
from slideai.domain.requirements.models import Outline, OutlineItem, OutlineSection
from slideai.domain.tasks.complexity import ComplexityTier, TaskComplexity
from slideai.domain.tasks.models import ModelPreference, RawRequirement, TaskRecord, TaskStatus


class MemoryTaskRepository:
    def __init__(self, tasks: list[TaskRecord]) -> None:
        self.tasks = {task.id: task for task in tasks}

    async def get(self, task_id: UUID) -> TaskRecord | None:
        return self.tasks.get(task_id)


class MemorySlideRepository:
    def __init__(self, slides: list[SlideContent]) -> None:
        self.slides = slides

    async def list_for_task(self, task_id: UUID) -> list[SlideContent]:
        return sorted(
            [slide for slide in self.slides if slide.task_id == task_id],
            key=lambda slide: slide.page_number,
        )


def _client() -> tuple[TestClient, TaskRecord, list[SlideContent]]:
    task_id = uuid4()
    now = datetime.now(UTC)
    outline = Outline(
        title="市场趋势",
        sections=[
            OutlineSection(
                id="market",
                title="市场概览",
                objective="解释主要趋势",
                page_count=3,
                items=[
                    OutlineItem(
                        id="signals",
                        title="变化信号",
                        objective="分析变化",
                        page_count=3,
                    )
                ],
            )
        ],
    )
    task = TaskRecord(
        id=task_id,
        name="市场趋势",
        status=TaskStatus.COMPLETED,
        current_stage="completed",
        raw_requirement=RawRequirement(topic="市场趋势", target_page_count=3),
        model_preference=ModelPreference(),
        complexity=TaskComplexity(tier=ComplexityTier.FAST, total_score=1, factors={}),
        outline=outline,
        generation_progress=SlideProgress(
            total_pages=3,
            completed_pages=3,
            total_batches=1,
            completed_batches=1,
        ),
        created_at=now,
        updated_at=now,
    )
    slides = [
        SlideContent(
            id=uuid4(),
            task_id=task_id,
            page_number=page_number,
            section_id="market",
            outline_item_id="signals",
            title=f"页面 {page_number}",
            bullets=["市场需求增长", "供给侧持续变化"],
        )
        for page_number in (3, 1, 2)
    ]
    tasks = MemoryTaskRepository([task])
    app = create_app(readiness_probe=lambda: {"postgres": "ok", "redis": "ok"})
    app.dependency_overrides[get_task_service] = lambda: TaskService(tasks)
    app.state.slide_content_service = SlideContentService(tasks, MemorySlideRepository(slides))
    return TestClient(app), task, slides


def test_slides_api_is_task_scoped_sorted_and_includes_progress() -> None:
    client, task, _ = _client()

    response = client.get(f"/api/v1/tasks/{task.id}/slides")

    assert response.status_code == 200
    body = response.json()
    assert [slide["page_number"] for slide in body["items"]] == [1, 2, 3]
    assert body["target_page_count"] == 3
    assert body["generation_progress"]["completed_pages"] == 3


def test_markdown_preview_and_download_match_the_structured_slides() -> None:
    client, task, _ = _client()

    preview = client.get(f"/api/v1/tasks/{task.id}/markdown")
    download = client.get(f"/api/v1/tasks/{task.id}/markdown/download")

    assert preview.status_code == 200
    assert preview.json()["markdown"] == download.content.decode("utf-8")
    assert preview.json()["version"] == task.version
    assert download.headers["content-type"].startswith("text/markdown")
    assert 'attachment; filename="slideai-export.md"' in download.headers["content-disposition"]
    assert "### 第 1 页：页面 1" in download.text


def test_slides_and_markdown_return_not_found_for_another_task_id() -> None:
    client, _, _ = _client()
    unknown_task_id = uuid4()

    slides = client.get(f"/api/v1/tasks/{unknown_task_id}/slides")
    markdown = client.get(f"/api/v1/tasks/{unknown_task_id}/markdown")

    assert slides.status_code == markdown.status_code == 404
    assert slides.json()["error"]["code"] == "TASK_NOT_FOUND"
