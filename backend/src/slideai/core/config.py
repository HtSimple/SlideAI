from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: str = "development"
    service_name: str = "slideai-api"
    database_url: str = "postgresql+asyncpg://slideai:local_dev_only@postgres:5432/slideai"
    redis_url: str = "redis://redis:6379/0"
    chroma_host: str = "chroma"
    chroma_port: int = Field(default=8000, ge=1, le=65535)
    file_storage_root: Path = Path("/var/lib/slideai/files")
    model_catalog_path: Path = Path("/app/config/models.yaml")
    cors_origins: str = "http://localhost:4173"
    log_level: str = "INFO"
    max_auto_revisions: int = Field(default=2, ge=0, le=10)
    evaluation_pass_score: int = Field(default=85, ge=0, le=100)
    max_file_size_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_files_per_task: int = Field(default=10, ge=1, le=100)
    max_extracted_chars_per_file: int = Field(default=2_000_000, ge=1)
    chunk_size_tokens: int = Field(default=800, ge=1)
    chunk_overlap_tokens: int = Field(default=120, ge=0)
    retrieval_top_k: int = Field(default=6, ge=1, le=100)
    model_retry_count: int = Field(default=2, ge=0, le=5)
    embedding_provider: str = "fake"
    embedding_base_url: str = ""
    embedding_model_id: str = ""
    embedding_api_key: str = ""
    embedding_dimensions: int = Field(default=64, ge=8, le=8192)
    embedding_version: str = Field(default="v1", pattern=r"^[a-zA-Z0-9_-]{1,80}$")

    @property
    def embedding_collection_name(self) -> str:
        return f"slideai_chunks_d{self.embedding_dimensions}_{self.embedding_version}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
