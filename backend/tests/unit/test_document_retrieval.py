from uuid import uuid4

import pytest

from slideai.application.files.retrieval import DocumentRetriever
from slideai.core.errors import DomainError
from slideai.domain.files.models import RetrievedChunk


class StubEmbedding:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts = texts
        return [[0.25, 0.75]]

    @property
    def model_name(self) -> str:
        return "test-embedding"


class StubVectorStore:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks

    async def search(self, **kwargs):  # type: ignore[no-untyped-def]
        self.query = kwargs
        return self.chunks


class StubFileNames:
    def __init__(self, names: dict[str, str]) -> None:
        self.names = names

    async def file_names(self, task_id, file_ids):  # type: ignore[no-untyped-def]
        self.task_id = task_id
        self.file_ids = file_ids
        return self.names


@pytest.mark.asyncio
async def test_retrieval_returns_task_scoped_citations_with_source_locations() -> None:
    task_id = uuid4()
    file_id = uuid4()
    chunk_id = uuid4()
    content = "Quarterly revenue increased by 12%. " * 12
    embedding = StubEmbedding()
    vector_store = StubVectorStore(
        [
            RetrievedChunk(
                id=str(chunk_id),
                task_id=str(task_id),
                file_id=str(file_id),
                content=content,
                score=0.92,
                page_number=4,
                section_title="Growth",
            ),
            RetrievedChunk(
                id=str(uuid4()),
                task_id=str(uuid4()),
                file_id=str(uuid4()),
                content="foreign task evidence",
                score=0.99,
            ),
        ]
    )
    file_names = StubFileNames({str(file_id): "quarterly-report.pdf"})
    retriever = DocumentRetriever(embedding, vector_store, file_names)

    citations = await retriever.search(
        task_id,
        "  quarterly revenue  ",
        file_ids=[file_id],
        top_k=3,
    )

    assert embedding.texts == ["quarterly revenue"]
    assert vector_store.query == {
        "task_id": str(task_id),
        "query_vector": [0.25, 0.75],
        "file_ids": [str(file_id)],
        "top_k": 3,
    }
    assert file_names.task_id == task_id
    assert file_names.file_ids == [file_id]
    assert len(citations) == 1
    assert citations[0].chunk_id == chunk_id
    assert citations[0].display_name == "quarterly-report.pdf"
    assert citations[0].page_number == 4
    assert citations[0].section_title == "Growth"
    assert len(citations[0].excerpt) == 280


@pytest.mark.asyncio
async def test_retrieval_rejects_blank_queries_and_invalid_result_limits() -> None:
    retriever = DocumentRetriever(StubEmbedding(), StubVectorStore([]), StubFileNames({}))

    with pytest.raises(DomainError) as blank:
        await retriever.search(uuid4(), "  ")
    with pytest.raises(DomainError) as out_of_range:
        await retriever.search(uuid4(), "query", top_k=101)

    assert blank.value.code == "VALIDATION_ERROR"
    assert out_of_range.value.code == "VALIDATION_ERROR"
