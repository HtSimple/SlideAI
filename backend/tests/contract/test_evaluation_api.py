from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from slideai.api.dependencies import get_task_service
from slideai.api.dependencies_workflows import get_workflow_control_service
from slideai.api.main import create_app
from slideai.application.tasks.service import TaskService
from slideai.application.workflows.service import WorkflowControlService
from slideai.domain.evaluation.models import EvaluationResult
from slideai.domain.tasks.models import (
    RawRequirement,
    TaskRecord,
    TaskStatus,
    initial_complexity,
)


class MemoryTasks:
    def __init__(self, task: TaskRecord) -> None:
        self.task = task

    async def get(self, task_id):
        return self.task if task_id == self.task.id else None

    async def update(self, task, *, expected_version):
        assert expected_version == self.task.version
        self.task = task


class MemoryFiles:
    async def list(self, task_id):
        return []


class MemoryQueue:
    def __init__(self) -> None:
        self.resumes = []

    def enqueue_start(self, task_id):
        return None

    def enqueue_resume(self, task_id, resume):
        self.resumes.append((task_id, resume))


class MemoryRevisions:
    async def list_for_task(self, task_id):
        return []


class MemorySlides:
    async def list_for_task(self, task_id):
        return []


def _client() -> tuple[TestClient, TaskRecord, MemoryTasks, MemoryQueue]:
    now = datetime.now(UTC)
    raw = RawRequirement(topic="市场趋势", target_page_count=3)
    task = TaskRecord(
        id=uuid4(),
        name=raw.topic,
        status=TaskStatus.WAITING_USER_FEEDBACK,
        current_stage="evaluation_review",
        raw_requirement=raw,
        model_preference={"mode": "auto"},
        complexity=initial_complexity(raw),
        evaluation_result=EvaluationResult(
            total_score=84,
            passed=False,
            threshold=85,
            hard_checks=[],
            dimensions=[
                {"name": name, "score": 84, "feedback": "需要继续完善。"}
                for name in (
                    "completeness",
                    "logic",
                    "content_quality",
                    "requirement_alignment",
                )
            ],
            issues=[],
            suggestions=[],
        ),
        revision_count=2,
        version=5,
        created_at=now,
        updated_at=now,
    )
    tasks = MemoryTasks(task)
    queue = MemoryQueue()
    app = create_app(readiness_probe=lambda: {"postgres": "ok", "redis": "ok"})
    app.dependency_overrides[get_task_service] = lambda: TaskService(tasks)
    app.dependency_overrides[get_workflow_control_service] = lambda: WorkflowControlService(
        tasks, MemoryFiles(), queue
    )
    app.state.revision_repository = MemoryRevisions()
    app.state.slide_repository = MemorySlides()
    return TestClient(app), task, tasks, queue


def test_evaluation_and_revisions_are_task_scoped() -> None:
    client, task, _, _ = _client()

    evaluation = client.get(f"/api/v1/tasks/{task.id}/evaluation")
    revisions = client.get(f"/api/v1/tasks/{task.id}/revisions")
    unknown = client.get(f"/api/v1/tasks/{uuid4()}/revisions")

    assert evaluation.status_code == 200
    assert evaluation.json()["evaluation_result"]["total_score"] == 84
    assert evaluation.json()["revision_count"] == 2
    assert revisions.status_code == 200
    assert revisions.json() == {"task_id": str(task.id), "items": []}
    assert unknown.status_code == 404


def test_evaluation_decision_checks_version_and_resumes_checkpoint() -> None:
    client, task, tasks, queue = _client()

    response = client.post(
        f"/api/v1/tasks/{task.id}/evaluation/decision",
        json={"expected_version": task.version, "action": "accept"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "RUNNING"
    assert tasks.task.status == TaskStatus.RUNNING
    assert queue.resumes == [(task.id, {"action": "accept", "feedback": None, "scope": []})]


def test_refinement_requires_feedback() -> None:
    client, task, _, _ = _client()

    response = client.post(
        f"/api/v1/tasks/{task.id}/evaluation/decision",
        json={"expected_version": task.version, "action": "refine", "feedback": "  "},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_refinement_rejects_a_page_outside_the_task() -> None:
    client, task, tasks, queue = _client()

    response = client.post(
        f"/api/v1/tasks/{task.id}/evaluation/decision",
        json={
            "expected_version": task.version,
            "action": "refine",
            "feedback": "修改第一页",
            "scope": [str(uuid4())],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SLIDE_REVISION_SCOPE_INVALID"
    assert tasks.task.status == TaskStatus.WAITING_USER_FEEDBACK
    assert queue.resumes == []
