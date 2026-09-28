from typing import Protocol
from uuid import UUID

from slideai.domain.evaluation.models import Revision


class RevisionRepository(Protocol):
    async def add(self, revision: Revision) -> None: ...

    async def list_for_task(self, task_id: UUID) -> list[Revision]: ...

    async def next_revision_number(self, task_id: UUID) -> int: ...
