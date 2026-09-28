from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from slideai.api.dependencies_files import get_file_service
from slideai.api.main import create_app
from slideai.core.errors import DomainError
from slideai.domain.files.models import FileStatus, SourceFile


class MemoryFileService:
    def __init__(self) -> None:
        self.task_id = uuid4()
        self.files: dict[UUID, SourceFile] = {}

    async def upload(self, task_id, *, filename, content_type, content):  # type: ignore[no-untyped-def]
        if task_id != self.task_id:
            raise DomainError("TASK_NOT_FOUND", "Task was not found.")
        source_file = _source_file(task_id, filename or "notes.md", content_type or "text/markdown")
        self.files[source_file.id] = source_file
        return source_file

    async def list(self, task_id):  # type: ignore[no-untyped-def]
        if task_id != self.task_id:
            raise DomainError("TASK_NOT_FOUND", "Task was not found.")
        return list(self.files.values())

    async def retry(self, task_id, file_id):  # type: ignore[no-untyped-def]
        source_file = self.files.get(file_id)
        if task_id != self.task_id or source_file is None:
            raise DomainError("FILE_NOT_FOUND", "File was not found for this task.")
        return source_file

    async def remove(self, task_id, file_id):  # type: ignore[no-untyped-def]
        source_file = self.files.get(file_id)
        if task_id != self.task_id or source_file is None:
            raise DomainError("FILE_NOT_FOUND", "File was not found for this task.")
        del self.files[file_id]
        return source_file


def test_file_routes_upload_list_and_enforce_task_scope() -> None:
    app = create_app(readiness_probe=lambda: {"postgres": "ok", "redis": "ok", "chroma": "ok"})
    service = MemoryFileService()
    app.dependency_overrides[get_file_service] = lambda: service
    client = TestClient(app)

    uploaded = client.post(
        f"/api/v1/tasks/{service.task_id}/files",
        files={"file": ("notes.md", b"# Notes\n\nText", "text/markdown")},
    )

    assert uploaded.status_code == 202
    payload = uploaded.json()
    assert payload["original_name"] == "notes.md"
    assert payload["status"] == "UPLOADED"
    assert "stored_name" not in payload
    assert "sha256" not in payload

    listed = client.get(f"/api/v1/tasks/{service.task_id}/files")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [payload["id"]]

    foreign = client.get(f"/api/v1/tasks/{uuid4()}/files")
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "TASK_NOT_FOUND"

    removed = client.delete(f"/api/v1/tasks/{service.task_id}/files/{payload['id']}")
    assert removed.status_code == 204


def _source_file(task_id: UUID, filename: str, mime_type: str) -> SourceFile:
    now = datetime.now(UTC)
    extension = filename.rsplit(".", maxsplit=1)[-1]
    return SourceFile(
        id=uuid4(),
        task_id=task_id,
        original_name=filename,
        stored_name=f"{uuid4()}.{extension}",
        mime_type=mime_type,
        extension=extension,
        size_bytes=1,
        sha256="0" * 64,
        status=FileStatus.UPLOADED,
        created_at=now,
        updated_at=now,
    )
