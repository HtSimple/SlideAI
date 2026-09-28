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

    def publish_event(
        self, event_id: UUID, event_type: str, aggregate_id: UUID, payload: dict[str, Any]
    ) -> None:
        if event_type == "workflow.start":
            task_name = "slideai.workers.start_workflow"
            args: list[Any] = [str(aggregate_id), str(event_id)]
        elif event_type == "workflow.resume":
            resume = payload.get("resume")
            if not isinstance(resume, dict):
                raise ValueError("A workflow resume event requires a resume payload.")
            task_name = "slideai.workers.resume_workflow"
            args = [str(aggregate_id), resume, str(event_id)]
        else:
            raise ValueError(f"Unsupported outbox event type: {event_type}")

        celery_client = cast(Any, celery_app)
        celery_client.send_task(task_name, args=args, task_id=str(event_id))
