from uuid import uuid4

from slideai.infrastructure.celery_queue.workflow_queue import CeleryWorkflowQueue
from slideai.workers.celery_app import celery_app


def test_duplicate_outbox_delivery_uses_the_event_id_as_celery_task_id(monkeypatch) -> None:
    calls: list[tuple[str, list[object], str]] = []

    def send_task(name: str, *, args: list[object], task_id: str) -> None:
        calls.append((name, args, task_id))

    monkeypatch.setattr(celery_app, "send_task", send_task)
    queue = CeleryWorkflowQueue()
    event_id = uuid4()
    task_id = uuid4()

    for _ in range(2):
        queue.publish_event(event_id, "workflow.start", task_id, {})

    assert calls == [
        ("slideai.workers.start_workflow", [str(task_id), str(event_id)], str(event_id)),
        ("slideai.workers.start_workflow", [str(task_id), str(event_id)], str(event_id)),
    ]


def test_resume_outbox_delivery_passes_its_event_id_to_the_worker(monkeypatch) -> None:
    calls: list[tuple[str, list[object], str]] = []

    def send_task(name: str, *, args: list[object], task_id: str) -> None:
        calls.append((name, args, task_id))

    monkeypatch.setattr(celery_app, "send_task", send_task)
    queue = CeleryWorkflowQueue()
    event_id = uuid4()
    task_id = uuid4()
    resume = {"kind": "outline_confirmed"}

    queue.publish_event(event_id, "workflow.resume", task_id, {"resume": resume})

    assert calls == [
        (
            "slideai.workers.resume_workflow",
            [str(task_id), resume, str(event_id)],
            str(event_id),
        )
    ]
