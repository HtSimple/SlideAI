from fastapi import Request

from slideai.application.tasks.service import TaskService


def get_task_service(request: Request) -> TaskService:
    return request.app.state.task_service
