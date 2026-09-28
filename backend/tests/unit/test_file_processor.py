from datetime import UTC, datetime
from uuid import uuid4

import pytest

from slideai.application.files.embedding import FakeEmbeddingGateway
from slideai.application.files.processor import FileProcessor
from slideai.core.errors import DomainError
from slideai.domain.files.models import FileStatus, SourceFile
from slideai.infrastructure.documents.parsers import parse_document


class MemoryFileRepository:
    def __init__(self, source_file: SourceFile) -> None:
        self.source_file = source_file
        self.status_history: list[FileStatus] = []
        self.chunks: list[object] = []

    async def ensure_task(self, task_id):  # type: ignore[no-untyped-def]
        return task_id == self.source_file.task_id

    async def task_status(self, task_id):  # type: ignore[no-untyped-def]
        return "FILES_PROCESSING"

    async def get(self, task_id, file_id, *, include_deleted=False):  # type: ignore[no-untyped-def]
        if task_id != self.source_file.task_id or file_id != self.source_file.id:
            return None
        if self.source_file.status == FileStatus.DELETED and not include_deleted:
            return None
        return self.source_file

    async def set_status(
        self,
        task_id,
        file_id,
        status,
        *,
        error_code=None,
        error_message=None,
        chunk_count=None,
    ):  # type: ignore[no-untyped-def]
        if task_id != self.source_file.task_id or file_id != self.source_file.id:
            return None
        self.status_history.append(status)
        self.source_file = self.source_file.model_copy(
            update={
                "status": status,
                "error_code": error_code,
                "error_message": error_message,
                "chunk_count": chunk_count
                if chunk_count is not None
                else self.source_file.chunk_count,
            }
        )
        return self.source_file

    async def replace_chunks(self, task_id, file_id, chunks):  # type: ignore[no-untyped-def]
        assert task_id == self.source_file.task_id
        assert file_id == self.source_file.id
        self.chunks = list(chunks)

    async def chunk_ids(self, task_id, file_id):  # type: ignore[no-untyped-def]
        return [str(chunk.id) for chunk in self.chunks]

    async def delete_chunks(self, task_id, file_id):  # type: ignore[no-untyped-def]
        self.chunks = []


class MemoryStorage:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def read(self, task_id, stored_name):  # type: ignore[no-untyped-def]
        return self.content

    def delete(self, task_id, stored_name):  # type: ignore[no-untyped-def]
        self.content = b""

    def write(self, task_id, stored_name, content):  # type: ignore[no-untyped-def]
        self.content = content


class MemoryVectorStore:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []
        self.vectors: list[list[float]] = []

    async def upsert(self, *, chunks, embeddings):  # type: ignore[no-untyped-def]
        self.records = chunks
        self.vectors = embeddings

    async def delete_by_ids(self, ids):  # type: ignore[no-untyped-def]
        self.records = [record for record in self.records if record["id"] not in ids]

    async def delete_file(self, *, task_id, file_id):  # type: ignore[no-untyped-def]
        self.records = [
            record
            for record in self.records
            if record["task_id"] != task_id or record["file_id"] != file_id
        ]


@pytest.mark.asyncio
async def test_processor_persists_located_chunks_and_marks_file_ready() -> None:
    task_id = uuid4()
    file_id = uuid4()
    source_file = _source_file(task_id, file_id)
    repository = MemoryFileRepository(source_file)
    storage = MemoryStorage(b"# Findings\n\nRevenue grew 12%.")
    vectors = MemoryVectorStore()
    processor = FileProcessor(
        repository,
        storage,
        FakeEmbeddingGateway(dimensions=16),
        vectors,
        chunk_size=20,
        chunk_overlap=2,
    )

    await processor.process(task_id, file_id)

    assert repository.source_file.status == FileStatus.READY
    assert repository.source_file.chunk_count == 1
    assert repository.chunks[0].section_title == "Findings"
    assert repository.chunks[0].task_id == task_id
    assert vectors.records[0]["file_id"] == str(file_id)
    assert len(vectors.vectors[0]) == 16


@pytest.mark.asyncio
async def test_processor_reports_scan_pdf_as_failed_without_fake_chunks() -> None:
    import pymupdf

    document = pymupdf.open()
    document.new_page()
    task_id = uuid4()
    file_id = uuid4()
    repository = MemoryFileRepository(_source_file(task_id, file_id, extension="pdf"))
    storage = MemoryStorage(document.tobytes())
    vectors = MemoryVectorStore()
    processor = FileProcessor(repository, storage, FakeEmbeddingGateway(), vectors)

    await processor.process(task_id, file_id)

    assert repository.source_file.status == FileStatus.FAILED
    assert repository.source_file.error_code == "NO_EXTRACTABLE_TEXT"
    assert not repository.chunks
    assert not vectors.records


def test_parser_reports_extract_size_limit() -> None:
    with pytest.raises(DomainError) as raised:
        parse_document("txt", b"long enough", max_chars=3)

    assert raised.value.code == "FILE_TEXT_TOO_LARGE"


def _source_file(task_id, file_id, *, extension="md"):  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    return SourceFile(
        id=file_id,
        task_id=task_id,
        original_name=f"source.{extension}",
        stored_name=f"{file_id}.{extension}",
        mime_type="text/markdown" if extension == "md" else "application/pdf",
        extension=extension,
        size_bytes=12,
        sha256="0" * 64,
        status=FileStatus.UPLOADED,
        created_at=now,
        updated_at=now,
    )
