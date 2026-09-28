from typing import Any, Protocol
from uuid import UUID


class WorkflowQueue(Protocol):
    def enqueue_start(self, task_id: UUID) -> None: ...

    def enqueue_resume(self, task_id: UUID, resume: dict[str, Any]) -> None: ...
