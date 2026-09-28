from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class RetrievedChunk:
    id: str
    task_id: str
    file_id: str
    content: str
    score: float
    page_number: int | None = None
    section_title: str | None = None


class FileStatus(StrEnum):
    UPLOADED = "UPLOADED"
    PARSING = "PARSING"
    CHUNKING = "CHUNKING"
    EMBEDDING = "EMBEDDING"
    READY = "READY"
    FAILED = "FAILED"
    DELETED = "DELETED"


class SourceFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    task_id: UUID
    original_name: str
    stored_name: str
    mime_type: str
    extension: str
    size_bytes: int = Field(gt=0)
    sha256: str
    status: FileStatus
    error_code: str | None = None
    error_message: str | None = None
    chunk_count: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class DocumentChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    task_id: UUID
    file_id: UUID
    ordinal: int = Field(ge=0)
    content: str = Field(min_length=1)
    token_count: int = Field(gt=0)
    page_number: int | None = Field(default=None, ge=1)
    section_title: str | None = None
    paragraph_index: int | None = Field(default=None, ge=1)
    embedding_model: str
    embedding_version: str


class SourceCitation(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: UUID
    file_id: UUID
    display_name: str
    page_number: int | None = Field(default=None, ge=1)
    section_title: str | None = None
    content: str
    excerpt: str
    similarity_score: float
