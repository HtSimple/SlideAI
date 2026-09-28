from typing import Any, cast

import chromadb
from chromadb.errors import NotFoundError

from slideai.core.errors import DomainError
from slideai.domain.files.models import RetrievedChunk


class ChromaVectorStore:
    collection_name = "slideai_chunks"

    def __init__(
        self,
        *,
        host: str = "chroma",
        port: int = 8000,
        collection_name: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        if collection_name is not None:
            self.collection_name = collection_name
        self._collection: Any | None = None

    async def _get_collection(self) -> Any:
        if self._collection is None:
            try:
                client = await chromadb.AsyncHttpClient(host=self.host, port=self.port)
                self._collection = await client.get_or_create_collection(
                    name=self.collection_name,
                    metadata={"hnsw:space": "cosine"},
                )
            except Exception as error:
                raise DomainError(
                    "VECTOR_STORE_UNAVAILABLE", "The document index is unavailable."
                ) from error
        return self._collection

    async def upsert(
        self,
        *,
        chunks: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("every chunk must have exactly one embedding")
        if not chunks:
            return
        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, str | int]] = []
        for chunk in chunks:
            chunk_id = str(chunk["id"])
            task_id = str(chunk["task_id"])
            file_id = str(chunk["file_id"])
            content = str(chunk["content"])
            metadata: dict[str, str | int] = {
                "chunk_id": chunk_id,
                "task_id": task_id,
                "file_id": file_id,
                "embedding_model": str(chunk.get("embedding_model", "")),
                "embedding_version": str(chunk.get("embedding_version", "v1")),
            }
            for key in ("page_number", "section_title", "paragraph_index"):
                value = chunk.get(key)
                if value is not None:
                    metadata[key] = value
            ids.append(chunk_id)
            documents.append(content)
            metadatas.append(metadata)
        collection = await self._get_collection()
        await collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

    async def search(
        self,
        *,
        task_id: str,
        query_vector: list[float],
        file_ids: list[str] | None,
        top_k: int,
    ) -> list[RetrievedChunk]:
        filters: dict[str, Any] = {"task_id": task_id}
        if file_ids:
            filters = {"$and": [{"task_id": task_id}, {"file_id": {"$in": file_ids}}]}
        collection = await self._get_collection()
        try:
            raw_response = await collection.query(
                query_embeddings=[query_vector],
                n_results=top_k,
                where=filters,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as error:
            raise DomainError(
                "VECTOR_SEARCH_FAILED", "The document index search failed."
            ) from error

        response = cast(dict[str, Any], raw_response)
        ids = cast(list[list[str]], response.get("ids") or [[]])
        documents = cast(list[list[str | None]], response.get("documents") or [[]])
        metadatas = cast(list[list[dict[str, Any] | None]], response.get("metadatas") or [[]])
        distances = cast(list[list[float | None]], response.get("distances") or [[]])
        results: list[RetrievedChunk] = []
        for index, chunk_id in enumerate(ids[0]):
            metadata = metadatas[0][index] or {}
            result_task_id = str(metadata.get("task_id", ""))
            result_file_id = str(metadata.get("file_id", ""))
            if result_task_id != task_id or (file_ids and result_file_id not in file_ids):
                continue
            result = RetrievedChunk(
                id=str(metadata.get("chunk_id", chunk_id)),
                task_id=result_task_id,
                file_id=result_file_id,
                content=str(documents[0][index] or ""),
                score=1.0 - float(distances[0][index] or 0.0),
                page_number=cast(int | None, metadata.get("page_number")),
                section_title=cast(str | None, metadata.get("section_title")),
            )
            results.append(result)
        return results

    async def delete_by_ids(self, ids: list[str]) -> None:
        if not ids:
            return
        collection = await self._get_collection()
        await collection.delete(ids=ids)

    async def delete_collection(self) -> None:
        client = await chromadb.AsyncHttpClient(host=self.host, port=self.port)
        try:
            await client.delete_collection(name=self.collection_name)
        except NotFoundError:
            pass
        self._collection = None

    async def delete_file(self, *, task_id: str, file_id: str) -> None:
        collection = await self._get_collection()
        await collection.delete(where={"$and": [{"task_id": task_id}, {"file_id": file_id}]})
