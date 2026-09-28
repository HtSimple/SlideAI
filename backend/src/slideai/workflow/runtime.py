from asyncio import Event
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import ChannelVersions, Checkpoint, CheckpointMetadata
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from slideai.application.content.writer import PageRetriever, ProgressReporter, SlideRepository
from slideai.application.evaluation.ports import RevisionRepository
from slideai.application.models.gateway import ModelGateway
from slideai.core.config import Settings
from slideai.core.errors import DomainError
from slideai.domain.content.models import SlideProgress
from slideai.domain.evaluation.models import EvaluationResult
from slideai.domain.requirements.models import Outline, StructuredRequirement
from slideai.domain.tasks.complexity import TaskComplexity
from slideai.domain.tasks.models import TaskStatus
from slideai.infrastructure.db.models import GenerationTaskRow
from slideai.infrastructure.db.task_repository import SqlTaskRepository
from slideai.workflow.graph import build_initial_state, build_slide_graph


class WorkflowCancelled(Exception):
    """Stop an in-flight graph after a user cancellation request."""


class FencedAsyncPostgresSaver(AsyncPostgresSaver):
    """Serialize checkpoint writes with lease claims and reject stale generations."""

    def __init__(
        self,
        delegate: AsyncPostgresSaver,
        repository: SqlTaskRepository,
        task_id: UUID,
        fencing_generation: int,
    ) -> None:
        super().__init__(delegate.conn, pipe=delegate.pipe, serde=delegate.serde)
        self.repository = repository
        self.task_id = task_id
        self.fencing_generation = fencing_generation

    @asynccontextmanager
    async def _write_guard(self) -> AsyncGenerator[None, None]:
        async with self.repository.sessions() as session, session.begin():
            task = await session.get(GenerationTaskRow, self.task_id, with_for_update=True)
            if task is None:
                raise DomainError("TASK_NOT_FOUND", "Task was not found.")
            if task.status == "CANCELLED":
                raise DomainError("WORKFLOW_CANCELLED", "The task was cancelled.")
            if task.status != "RUNNING":
                raise DomainError("TASK_CONFLICT", "Checkpoint writes require a running task.")
            if task.workflow_fencing_generation != self.fencing_generation:
                raise DomainError("WORKFLOW_LOCK_LOST", "The workflow worker lost its task lock.")
            yield

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        async with self._write_guard():
            return await super().aput(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        async with self._write_guard():
            await super().aput_writes(config, writes, task_id, task_path)


class _GuardedGateway:
    def __init__(
        self,
        gateway: ModelGateway,
        *,
        cancellation_requested: Callable[[], Awaitable[bool]] | None,
        lock_lost: Event | None,
    ) -> None:
        self.gateway = gateway
        self.cancellation_requested = cancellation_requested
        self.lock_lost = lock_lost

    async def invoke_structured(self, **kwargs: Any) -> Any:
        await self._ensure_active()
        result = await self.gateway.invoke_structured(**kwargs)
        await self._ensure_active()
        return result

    async def _ensure_active(self) -> None:
        if self.lock_lost is not None and self.lock_lost.is_set():
            raise DomainError("WORKFLOW_LOCK_LOST", "The workflow worker lost its task lock.")
        if self.cancellation_requested is not None and await self.cancellation_requested():
            raise WorkflowCancelled


async def execute_persisted_workflow(
    settings: Settings,
    repository: SqlTaskRepository,
    gateway: ModelGateway,
    task_id: UUID,
    *,
    resume: dict[str, Any] | None = None,
    retriever: PageRetriever,
    slide_repository: SlideRepository,
    progress_reporter: ProgressReporter | None = None,
    revision_repository: RevisionRepository | None = None,
    chunk_id_loader: Callable[[UUID], Awaitable[set[UUID]]] | None = None,
    cancellation_requested: Callable[[], Awaitable[bool]] | None = None,
    lock_lost: Event | None = None,
    workflow_fencing_generation: int | None = None,
) -> dict[str, Any]:
    task = await repository.get(task_id)
    if task is None:
        raise DomainError("TASK_NOT_FOUND", "Task was not found.")
    config = {"configurable": {"thread_id": str(task_id)}}
    guarded_gateway = cast(
        ModelGateway,
        _GuardedGateway(
            gateway,
            cancellation_requested=cancellation_requested,
            lock_lost=lock_lost,
        ),
    )

    try:
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_database_url) as saver:
            await saver.setup()
            checkpointer = (
                FencedAsyncPostgresSaver(saver, repository, task_id, workflow_fencing_generation)
                if workflow_fencing_generation is not None
                else saver
            )
            graph = build_slide_graph(
                guarded_gateway,
                checkpointer=checkpointer,
                retriever=retriever,
                slide_repository=slide_repository,
                progress_reporter=progress_reporter,
                settings=settings,
                revision_repository=revision_repository,
                chunk_id_loader=chunk_id_loader,
            )
            command: Any = (
                Command(resume=resume) if resume is not None else build_initial_state(task)
            )
            try:
                result = cast(dict[str, Any], await graph.ainvoke(command, config))
            except WorkflowCancelled:
                result = {"workflow_cancelled": True}
            except DomainError as error:
                if error.code == "WORKFLOW_CANCELLED":
                    result = {"workflow_cancelled": True}
                elif error.code == "WORKFLOW_LOCK_LOST":
                    result = {"workflow_lock_lost": True}
                else:
                    raise
        if result.get("workflow_lock_lost"):
            return result
        projection_saved = await _persist_projection(
            repository, task_id, result, fencing_generation=workflow_fencing_generation
        )
        if not projection_saved:
            return {"workflow_lock_lost": True}
        return result
    except Exception:
        if workflow_fencing_generation is not None:
            await repository.mark_failed_if_workflow_current(task_id, workflow_fencing_generation)
        else:
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
    repository: SqlTaskRepository,
    task_id: UUID,
    result: dict[str, Any],
    *,
    fencing_generation: int | None = None,
) -> bool:
    if result.get("workflow_lock_lost"):
        return False
    if result.get("workflow_cancelled"):
        return True
    task = await repository.get(task_id)
    if task is None:
        raise DomainError("TASK_NOT_FOUND", "Task was not found.")
    if task.status == TaskStatus.CANCELLED:
        return True

    update: dict[str, object] = {"version": task.version + 1}
    if requirement_data := result.get("structured_requirement"):
        update["structured_requirement"] = StructuredRequirement.model_validate(requirement_data)
    if outline_data := result.get("outline"):
        update["outline"] = Outline.model_validate(outline_data)
    if complexity_data := result.get("task_complexity"):
        update["complexity"] = TaskComplexity.model_validate(complexity_data)
    if evaluation_data := result.get("evaluation_result"):
        update["evaluation_result"] = EvaluationResult.model_validate(evaluation_data)
    if "revision_count" in result:
        update["revision_count"] = result["revision_count"]

    interrupts = result.get("__interrupt__", ())
    if interrupts:
        interrupt_kind = interrupts[0].value.get("kind")
        if interrupt_kind == "requirement":
            update["status"] = TaskStatus.WAITING_REQUIREMENT_INPUT
            update["current_stage"] = "requirement_review"
        elif interrupt_kind == "outline":
            update["status"] = TaskStatus.WAITING_OUTLINE_CONFIRMATION
            update["current_stage"] = "outline_review"
        elif interrupt_kind == "evaluation_limit":
            update["status"] = TaskStatus.WAITING_USER_FEEDBACK
            update["current_stage"] = "evaluation_review"
    elif result.get("outline_confirmed"):
        update["status"] = TaskStatus.READY
        update["current_stage"] = "outline_confirmed"
    if result.get("workflow_cancelled"):
        update["status"] = TaskStatus.CANCELLED
        update["current_stage"] = "cancelled"
    elif result.get("final_markdown") and not interrupts:
        update["status"] = TaskStatus.COMPLETED
        update["current_stage"] = "completed"
        total_batches = task.generation_progress.total_batches if task.generation_progress else 0
        page_count = len(result.get("slides_content", []))
        update["generation_progress"] = SlideProgress(
            total_pages=page_count,
            completed_pages=page_count,
            total_batches=total_batches,
            completed_batches=total_batches,
        )

    updated = task.model_copy(update=update)
    if fencing_generation is not None:
        return await repository.update_workflow_projection(
            updated,
            expected_version=task.version,
            fencing_generation=fencing_generation,
        )
    await repository.update(updated, expected_version=task.version)
    return True
