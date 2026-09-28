import os
from uuid import uuid4

import pytest

from slideai.infrastructure.vector.chroma_store import ChromaVectorStore


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vector_search_never_returns_other_task_chunks() -> None:
    if os.getenv("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_INTEGRATION_TESTS=1 when Compose dependencies are available")
    store = ChromaVectorStore(
        host=os.getenv("CHROMA_HOST", "chroma"),
        port=8000,
        collection_name=f"slideai_test_{uuid4().hex}",
    )
    task_id = str(uuid4())
    foreign_task_id = str(uuid4())
    own_id = str(uuid4())
    foreign_id = str(uuid4())
    vectors = [[1.0, 0.0], [0.999, 0.001]]

    await store.upsert(
        chunks=[
            {"id": own_id, "task_id": task_id, "file_id": str(uuid4()), "content": "own"},
            {
                "id": foreign_id,
                "task_id": foreign_task_id,
                "file_id": str(uuid4()),
                "content": "foreign",
            },
        ],
        embeddings=vectors,
    )
    try:
        results = await store.search(
            task_id=task_id,
            query_vector=[1.0, 0.0],
            file_ids=None,
            top_k=10,
        )

        assert [result.id for result in results] == [own_id]
        assert all(result.task_id == task_id for result in results)
    finally:
        await store.delete_collection()
