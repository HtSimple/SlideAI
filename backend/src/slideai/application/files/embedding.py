import hashlib
import math
import re
from typing import Protocol

import httpx

from slideai.core.config import Settings
from slideai.core.errors import DomainError

_TOKEN = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9]+|[^\s]")


class EmbeddingGateway(Protocol):
    @property
    def model_name(self) -> str: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbeddingGateway:
    def __init__(self, dimensions: int = 64) -> None:
        self.dimensions = dimensions

    @property
    def model_name(self) -> str:
        return "fake-hash-v1"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for match in _TOKEN.finditer(text.casefold()):
            digest = hashlib.sha256(match.group().encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector


class OpenAICompatibleEmbeddingGateway:
    def __init__(
        self,
        *,
        base_url: str,
        model_id: str,
        api_key: str,
        dimensions: int,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not base_url.strip() or not model_id.strip() or not api_key.strip():
            raise DomainError(
                "EMBEDDING_CONFIGURATION_INVALID",
                "Embedding base URL, model ID, and API key must be configured.",
            )
        self.base_url = base_url.rstrip("/")
        self.model_id = model_id
        self.api_key = api_key
        self.dimensions = dimensions
        self.timeout_seconds = timeout_seconds

    @property
    def model_name(self) -> str:
        return self.model_id

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        endpoint = (
            self.base_url
            if self.base_url.endswith("/embeddings")
            else f"{self.base_url}/embeddings"
        )
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model_id,
                        "input": texts,
                        "dimensions": self.dimensions,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise DomainError(
                "EMBEDDING_PROVIDER_ERROR", "The embedding service could not process this file."
            ) from error

        try:
            items = sorted(payload["data"], key=lambda item: item["index"])
            vectors = [[float(value) for value in item["embedding"]] for item in items]
        except (KeyError, TypeError, ValueError) as error:
            raise DomainError(
                "EMBEDDING_RESPONSE_INVALID", "The embedding service returned an invalid response."
            ) from error
        if len(vectors) != len(texts) or any(len(vector) != self.dimensions for vector in vectors):
            raise DomainError(
                "EMBEDDING_DIMENSION_MISMATCH",
                "The embedding service returned an unexpected vector size.",
            )
        return vectors


def create_embedding_gateway(settings: Settings) -> EmbeddingGateway:
    if settings.embedding_provider == "fake":
        return FakeEmbeddingGateway(settings.embedding_dimensions)
    if settings.embedding_provider == "openai_compatible":
        return OpenAICompatibleEmbeddingGateway(
            base_url=settings.embedding_base_url,
            model_id=settings.embedding_model_id,
            api_key=settings.embedding_api_key,
            dimensions=settings.embedding_dimensions,
        )
    raise DomainError(
        "EMBEDDING_CONFIGURATION_INVALID",
        "The configured embedding provider is not supported.",
    )
