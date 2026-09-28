from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from pydantic import BaseModel

from slideai.api.dependencies_files import get_file_service
from slideai.application.files.service import FileService
from slideai.domain.files.models import SourceFile

router = APIRouter(prefix="/api/v1", tags=["files"])


class FileResponse(BaseModel):
    id: UUID
    task_id: UUID
    original_name: str
    mime_type: str
    extension: str
    size_bytes: int
    status: str
    error_code: str | None
    error_message: str | None
    chunk_count: int
    created_at: str
    updated_at: str


class FileLimitsResponse(BaseModel):
    max_file_size_bytes: int
    max_files_per_task: int
    allowed_extensions: list[str]


@router.get("/file-limits", response_model=FileLimitsResponse)
async def get_file_limits(request: Request) -> FileLimitsResponse:
    settings = request.app.state.settings
    return FileLimitsResponse(
        max_file_size_bytes=settings.max_file_size_bytes,
        max_files_per_task=settings.max_files_per_task,
        allowed_extensions=["pdf", "docx", "md", "txt"],
    )


@router.post("/tasks/{task_id}/files", response_model=FileResponse, status_code=202)
async def upload_file(
    task_id: UUID,
    request: Request,
    service: Annotated[FileService, Depends(get_file_service)],
    uploaded_file: Annotated[UploadFile, File(alias="file")],
) -> FileResponse:
    settings = request.app.state.settings
    content = await uploaded_file.read(settings.max_file_size_bytes + 1)
    source_file = await service.upload(
        task_id,
        filename=uploaded_file.filename,
        content_type=uploaded_file.content_type,
        content=content,
    )
    return _file_response(source_file)


@router.get("/tasks/{task_id}/files", response_model=list[FileResponse])
async def list_files(
    task_id: UUID, service: Annotated[FileService, Depends(get_file_service)]
) -> list[FileResponse]:
    return [_file_response(source_file) for source_file in await service.list(task_id)]


@router.post("/tasks/{task_id}/files/{file_id}/retry", response_model=FileResponse, status_code=202)
async def retry_file(
    task_id: UUID,
    file_id: UUID,
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileResponse:
    return _file_response(await service.retry(task_id, file_id))


@router.delete("/tasks/{task_id}/files/{file_id}", status_code=204)
async def remove_file(
    task_id: UUID,
    file_id: UUID,
    service: Annotated[FileService, Depends(get_file_service)],
) -> Response:
    await service.remove(task_id, file_id)
    return Response(status_code=204)


def _file_response(source_file: SourceFile) -> FileResponse:
    return FileResponse(
        id=source_file.id,
        task_id=source_file.task_id,
        original_name=source_file.original_name,
        mime_type=source_file.mime_type,
        extension=source_file.extension,
        size_bytes=source_file.size_bytes,
        status=source_file.status.value,
        error_code=source_file.error_code,
        error_message=source_file.error_message,
        chunk_count=source_file.chunk_count,
        created_at=source_file.created_at.isoformat(),
        updated_at=source_file.updated_at.isoformat(),
    )
