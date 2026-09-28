from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from slideai.api.dependencies import get_task_service
from slideai.api.main import create_app
from slideai.application.outlines.service import OutlineService
from slideai.application.requirements.service import RequirementService
from slideai.application.tasks.service import TaskService
from slideai.application.workflows.service import WorkflowControlService
from slideai.core.errors import DomainError
from slideai.domain.files.models import SourceFile
from slideai.domain.requirements.models import (
    Outline,
    OutlineItem,
    OutlineSection,
    StructuredRequirement,
)
from slideai.domain.tasks.models import TaskRecord, TaskStatus


class MemoryTaskRepository:
    def __init__(self) -> None:
        self.records: dict[UUID, TaskRecord] = {}

    async def add(self, task: TaskRecord) -> None:
        self.records[task.id] = task

    async def get(self, task_id: UUID) -> TaskRecord | None:
        return self.records.get(task_id)

    async def list(
        self, *, offset: int, limit: int, status: str | None = None, query: str | None = None
    ) -> tuple[list[TaskRecord], int]:
        rows = list(self.records.values())
        return rows[offset : offset + limit], len(rows)

    async def update(self, task: TaskRecord, *, expected_version: int) -> None:
        current = self.records[task.id]
        if current.version != expected_version:
            raise DomainError("VERSION_CONFLICT", "Task changed.")
        self.records[task.id] = task

    async def delete(self, task_id: UUID) -> None:
        self.records.pop(task_id, None)

    async def status_counts(self) -> dict[str, int]:
        return {}


class EmptyFiles:
    async def list(self, task_id: UUID) -> list[SourceFile]:
        return []


class MemoryQueue:
    def __init__(self) -> None:
        self.started: list[UUID] = []
        self.resumed: list[tuple[UUID, dict[str, Any]]] = []

    def enqueue_start(self, task_id: UUID) -> None:
        self.started.append(task_id)

    def enqueue_resume(self, task_id: UUID, resume: dict[str, Any]) -> None:
        self.resumed.append((task_id, resume))


def _client() -> tuple[TestClient, MemoryTaskRepository, MemoryQueue]:
    repository = MemoryTaskRepository()
    queue = MemoryQueue()
    app = create_app(
        readiness_probe=lambda: {"postgres": "ok", "redis": "ok", "configuration": "ok"}
    )
    app.dependency_overrides[get_task_service] = lambda: TaskService(repository)
    app.state.workflow_control_service = WorkflowControlService(repository, EmptyFiles(), queue)
    app.state.requirement_service = RequirementService(repository, queue)
    app.state.outline_service = OutlineService(repository, queue)
    return TestClient(app), repository, queue


def _create_task(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/v1/tasks",
        json={"raw_requirement": {"topic": "Industry outlook", "target_page_count": 6}},
    )
    assert response.status_code == 201
    return response.json()


def _outline(page_count: int) -> Outline:
    return Outline(
        title="Industry outlook",
        sections=[
            OutlineSection(
                id="market",
                title="Market",
                objective="Explain the market",
                page_count=page_count,
                items=[
                    OutlineItem(
                        id="market-size",
                        title="Market size",
                        objective="Show the market size",
                        page_count=page_count,
                    )
                ],
            )
        ],
    )


def _set_waiting_outline(repository: MemoryTaskRepository, task_id: UUID) -> None:
    task = repository.records[task_id]
    repository.records[task_id] = task.model_copy(
        update={
            "status": TaskStatus.WAITING_OUTLINE_CONFIRMATION,
            "structured_requirement": StructuredRequirement(
                topic=task.name,
                target_page_count=6,
                scenario="Annual review",
                audience="Leadership",
                style="Evidence-led",
            ),
        }
    )


def _set_waiting_requirement(repository: MemoryTaskRepository, task_id: UUID) -> None:
    task = repository.records[task_id]
    repository.records[task_id] = task.model_copy(
        update={
            "status": TaskStatus.WAITING_REQUIREMENT_INPUT,
            "structured_requirement": StructuredRequirement(
                topic=task.name,
                target_page_count=6,
            ),
        }
    )


def _complete_requirement() -> StructuredRequirement:
    return StructuredRequirement(
        topic="Industry outlook",
        target_page_count=6,
        scenario="Annual review",
        audience="Leadership",
        style="Evidence-led",
    )


def test_missing_requirement_enters_clarification() -> None:
    client, _, queue = _client()
    task = _create_task(client)

    started = client.post(f"/api/v1/tasks/{task['id']}/start")

    assert started.status_code == 202
    assert started.json()["status"] == "RUNNING"
    assert queue.started == [UUID(task["id"])]


def test_running_workflow_can_be_cancelled_with_version_check() -> None:
    client, _, queue = _client()
    task = _create_task(client)
    task_id = UUID(task["id"])
    started = client.post(f"/api/v1/tasks/{task_id}/start")
    assert started.status_code == 202

    cancelled = client.post(
        f"/api/v1/tasks/{task_id}/cancel",
        json={"expected_version": started.json()["version"]},
    )
    stale = client.post(
        f"/api/v1/tasks/{task_id}/cancel",
        json={"expected_version": started.json()["version"]},
    )

    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["current_stage"] == "cancelled"
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
    assert queue.started == [task_id]


def test_requirement_can_be_completed_and_resumed() -> None:
    client, repository, queue = _client()
    task = _create_task(client)
    task_id = UUID(task["id"])
    _set_waiting_requirement(repository, task_id)

    requirement_response = client.get(f"/api/v1/tasks/{task_id}/requirement")
    assert requirement_response.status_code == 200
    assert requirement_response.json()["missing_fields"] == [
        "scenario",
        "audience",
        "style",
    ]

    incomplete = client.post(
        f"/api/v1/tasks/{task_id}/requirement/confirm",
        json={"expected_version": 1},
    )
    assert incomplete.status_code == 422
    assert incomplete.json()["error"]["code"] == "REQUIREMENT_INCOMPLETE"

    updated = client.put(
        f"/api/v1/tasks/{task_id}/requirement",
        json={
            "expected_version": 1,
            "structured_requirement": _complete_requirement().model_dump(mode="json"),
        },
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["missing_fields"] == []

    confirmed = client.post(
        f"/api/v1/tasks/{task_id}/requirement/confirm",
        json={"expected_version": 2},
    )
    assert confirmed.status_code == 202
    assert confirmed.json()["status"] == "RUNNING"
    assert confirmed.json()["version"] == 3
    assert queue.resumed == [
        (
            task_id,
            {
                "kind": "requirement_confirmed",
                "structured_requirement": _complete_requirement().model_dump(mode="json"),
            },
        )
    ]


def test_outline_page_allocation_must_equal_target() -> None:
    client, repository, _ = _client()
    task = _create_task(client)
    task_id = UUID(task["id"])
    _set_waiting_outline(repository, task_id)

    response = client.put(
        f"/api/v1/tasks/{task_id}/outline",
        json={"expected_version": 1, "outline": _outline(5).model_dump(mode="json")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "OUTLINE_INVALID"
    assert response.json()["error"]["details"][0]["code"] == "PAGE_COUNT_MISMATCH"


def test_outline_edit_increments_version() -> None:
    client, repository, _ = _client()
    task = _create_task(client)
    task_id = UUID(task["id"])
    _set_waiting_outline(repository, task_id)

    response = client.put(
        f"/api/v1/tasks/{task_id}/outline",
        json={"expected_version": 1, "outline": _outline(6).model_dump(mode="json")},
    )

    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert repository.records[task_id].outline == _outline(6)
