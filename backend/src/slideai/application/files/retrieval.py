from typing import Protocol
from uuid import UUID

from slideai.application.files.embedding import EmbeddingGateway
from slideai.core.errors import DomainError
from slideai.domain.files.models import RetrievedChunk, SourceCitation


class SearchVectorStore(Protocol):
    async def search(
        self,
        *,
        task_id: str,
        query_vector: list[float],
        file_ids: list[str] | None,
        top_k: int,
    ) -> list[RetrievedChunk]: ...


class FileNameReader(Protocol):
    async def file_names(self, task_id: UUID, file_ids: list[UUID]) -> dict[str, str]: ...


class DocumentRetriever:
    def __init__(
        self,
        embedding: EmbeddingGateway,
        vector_store: SearchVectorStore,
        file_name_reader: FileNameReader,
        *,
        default_top_k: int = 6,
    ) -> None:
        self.embedding = embedding
        self.vector_store = vector_store
        self.file_name_reader = file_name_reader
        self.default_top_k = default_top_k

    async def search(
        self,
        task_id: UUID,
        query: str,
        *,
        file_ids: list[UUID] | None = None,
        top_k: int | None = None,
    ) -> list[SourceCitation]:
        normalized_query = query.strip()
        if not normalized_query:
            raise DomainError("VALIDATION_ERROR", "A non-empty search query is required.")
        result_count = top_k if top_k is not None else self.default_top_k
        if result_count < 1 or result_count > 100:
            raise DomainError("VALIDATION_ERROR", "top_k must be between 1 and 100.")
        normalized_file_ids = [str(file_id) for file_id in file_ids] if file_ids else None
        query_vectors = await self.embedding.embed([normalized_query])
        if len(query_vectors) != 1:
            raise DomainError(
                "EMBEDDING_RESPONSE_INVALID", "The embedding service returned an invalid response."
            )
        chunks = await self.vector_store.search(
            task_id=str(task_id),
            query_vector=query_vectors[0],
            file_ids=normalized_file_ids,
            top_k=result_count,
        )
        parsed_file_ids: list[UUID] = []
        valid_chunks: list[tuple[RetrievedChunk, UUID, UUID]] = []
        allowed_file_ids = set(normalized_file_ids or [])
        for chunk in chunks:
            if chunk.task_id != str(task_id):
                continue
            if allowed_file_ids and chunk.file_id not in allowed_file_ids:
                continue
            try:
                chunk_id = UUID(chunk.id)
                file_id = UUID(chunk.file_id)
            except ValueError:
                continue
            valid_chunks.append((chunk, chunk_id, file_id))
            parsed_file_ids.append(file_id)
        file_names = await self.file_name_reader.file_names(
            task_id,
            list(dict.fromkeys(parsed_file_ids)),
        )
        citations: list[SourceCitation] = []
        for chunk, chunk_id, file_id in valid_chunks:
            display_name = file_names.get(str(file_id))
            if display_name is None:
                continue
            citations.append(
                SourceCitation(
                    chunk_id=chunk_id,
                    file_id=file_id,
                    display_name=display_name,
                    page_number=chunk.page_number,
                    section_title=chunk.section_title,
                    content=chunk.content,
                    excerpt=chunk.content[:280],
                    similarity_score=chunk.score,
                )
            )
        return citations
