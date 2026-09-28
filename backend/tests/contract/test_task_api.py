from fastapi.testclient import TestClient

from slideai.api.dependencies import get_task_service
from slideai.api.main import create_app
from slideai.application.tasks.service import TaskService
from slideai.core.errors import DomainError
from slideai.domain.tasks.models import TaskRecord


class MemoryTaskRepository:
    def __init__(self) -> None:
        self.records: dict[object, TaskRecord] = {}

    async def add(self, task: TaskRecord) -> None:
        self.records[task.id] = task

    async def get(self, task_id: object) -> TaskRecord | None:
        return self.records.get(task_id)

    async def list(
        self, *, offset: int, limit: int, status: str | None = None, query: str | None = None
    ):
        rows = list(self.records.values())
        rows.sort(key=lambda row: row.updated_at, reverse=True)
        return rows[offset : offset + limit], len(rows)

    async def update(self, task: TaskRecord, *, expected_version: int) -> None:
        current = self.records[task.id]
        if current.version != expected_version:
            raise DomainError("VERSION_CONFLICT", "Task changed.")
        self.records[task.id] = task

    async def delete(self, task_id: object) -> None:
        self.records.pop(task_id, None)

    async def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for task in self.records.values():
            counts[task.status.value] = counts.get(task.status.value, 0) + 1
        return counts


def test_task_create_and_patch_version_contract() -> None:
    app = create_app(
        readiness_probe=lambda: {"postgres": "ok", "redis": "ok", "configuration": "ok"}
    )
    task_service = TaskService(MemoryTaskRepository())
    app.dependency_overrides[get_task_service] = lambda: task_service
    client = TestClient(app)

    created = client.post(
        "/api/v1/tasks",
        json={
            "raw_requirement": {"topic": "Market outlook", "target_page_count": 12},
            "model_preference": {"mode": "auto"},
        },
    )

    assert created.status_code == 201
    task = created.json()
    assert task["status"] == "DRAFT"
    assert task["version"] == 1

    stale = client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"expected_version": 0, "name": "Stale"},
    )

    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"

    listed = client.get("/api/v1/tasks?offset=0&limit=20")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == task["id"]
    assert listed.json()["status_counts"] == {"DRAFT": 1}

    models = client.get("/api/v1/models")
    assert models.status_code == 200
    assert models.json()
    assert set(models.json()[0]) == {"key", "display_name", "tier", "enabled", "available"}
