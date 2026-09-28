from fastapi import Request

from slideai.application.files.service import FileService


def get_file_service(request: Request) -> FileService:
    return request.app.state.file_service
