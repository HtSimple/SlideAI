from typing import Any, cast
from uuid import UUID

from slideai.application.workflows.ports import WorkflowQueue
from slideai.workers.celery_app import celery_app


class CeleryWorkflowQueue(WorkflowQueue):
    def enqueue_start(self, task_id: UUID) -> None:
        celery_client = cast(Any, celery_app)
        celery_client.send_task("slideai.workers.start_workflow", args=[str(task_id)])

    def enqueue_resume(self, task_id: UUID, resume: dict[str, Any]) -> None:
        celery_client = cast(Any, celery_app)
        celery_client.send_task("slideai.workers.resume_workflow", args=[str(task_id), resume])
