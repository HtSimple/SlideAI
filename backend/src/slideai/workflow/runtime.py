from typing import Any, cast
from uuid import UUID

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from slideai.application.models.gateway import ModelGateway
from slideai.core.config import Settings
from slideai.core.errors import DomainError
from slideai.domain.requirements.models import Outline, StructuredRequirement
from slideai.domain.tasks.complexity import TaskComplexity
from slideai.domain.tasks.models import TaskStatus
from slideai.infrastructure.db.task_repository import SqlTaskRepository
from slideai.workflow.graph import build_initial_state, build_slide_graph


async def execute_persisted_workflow(
    settings: Settings,
    repository: SqlTaskRepository,
    gateway: ModelGateway,
    task_id: UUID,
    *,
    resume: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task = await repository.get(task_id)
    if task is None:
        raise DomainError("TASK_NOT_FOUND", "Task was not found.")
    config = {"configurable": {"thread_id": str(task_id)}}

    try:
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_database_url) as saver:
            await saver.setup()
            graph = build_slide_graph(gateway, checkpointer=saver)
            command: Any = (
                Command(resume=resume) if resume is not None else build_initial_state(task)
            )
            result = cast(dict[str, Any], await graph.ainvoke(command, config))
        await _persist_projection(repository, task_id, result)
        return result
    except Exception:
        latest = await repository.get(task_id)
        if latest is not None and latest.status == TaskStatus.RUNNING:
            failed = latest.model_copy(
                update={
                    "status": TaskStatus.FAILED_RETRYABLE,
                    "version": latest.version + 1,
                }
            )
            await repository.update(failed, expected_version=latest.version)
        raise


async def _persist_projection(
    repository: SqlTaskRepository, task_id: UUID, result: dict[str, Any]
) -> None:
    task = await repository.get(task_id)
    if task is None:
        raise DomainError("TASK_NOT_FOUND", "Task was not found.")

    update: dict[str, object] = {"version": task.version + 1}
    if requirement_data := result.get("structured_requirement"):
        update["structured_requirement"] = StructuredRequirement.model_validate(requirement_data)
    if outline_data := result.get("outline"):
        update["outline"] = Outline.model_validate(outline_data)
    if complexity_data := result.get("task_complexity"):
        update["complexity"] = TaskComplexity.model_validate(complexity_data)

    interrupts = result.get("__interrupt__", ())
    if interrupts:
        interrupt_kind = interrupts[0].value.get("kind")
        if interrupt_kind == "requirement":
            update["status"] = TaskStatus.WAITING_REQUIREMENT_INPUT
            update["current_stage"] = "requirement_review"
        elif interrupt_kind == "outline":
            update["status"] = TaskStatus.WAITING_OUTLINE_CONFIRMATION
            update["current_stage"] = "outline_review"
    elif result.get("outline_confirmed"):
        update["status"] = TaskStatus.READY
        update["current_stage"] = "outline_confirmed"

    updated = task.model_copy(update=update)
    await repository.update(updated, expected_version=task.version)
