import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal, NotRequired, TypedDict, cast
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from slideai.application.content.gateway_writer import GatewayBatchWriter
from slideai.application.content.markdown import render_markdown
from slideai.application.content.writer import (
    PageRetriever,
    ProgressReporter,
    SlideRepository,
    write_slide_batches,
)
from slideai.application.evaluation.ports import RevisionRepository
from slideai.application.models.gateway import ModelGateway
from slideai.core.config import Settings
from slideai.domain.content.models import SlideContent
from slideai.domain.evaluation.models import (
    EvaluationDraft,
    EvaluationResult,
    Revision,
    SlideRefinementDraft,
)
from slideai.domain.evaluation.policy import can_auto_refine
from slideai.domain.requirements.models import Outline, StructuredRequirement
from slideai.domain.requirements.validation import validate_outline
from slideai.domain.tasks.complexity import score_complexity
from slideai.domain.tasks.models import ModelPreference, RawRequirement, TaskRecord
from slideai.workflow.nodes.checks import run_hard_checks
from slideai.workflow.nodes.evaluate import evaluate_quality
from slideai.workflow.nodes.refine import refine_content


class SlideState(TypedDict):
    task_id: str
    raw_requirement: dict[str, Any]
    model_preference: dict[str, Any]
    task_complexity: dict[str, Any]
    run_id: NotRequired[str]
    structured_requirement: NotRequired[dict[str, Any]]
    outline: NotRequired[dict[str, Any]]
    workflow_stage: NotRequired[str]
    outline_issues: NotRequired[list[dict[str, Any]]]
    outline_confirmed: NotRequired[bool]
    slides_content: NotRequired[list[dict[str, Any]]]
    final_markdown: NotRequired[str]
    evaluation_result: NotRequired[dict[str, Any]]
    revision_count: NotRequired[int]
    revision_total: NotRequired[int]
    user_decision: NotRequired[str]
    user_feedback: NotRequired[str]
    user_scope: NotRequired[list[str]]
    workflow_cancelled: NotRequired[bool]


def build_initial_state(task: TaskRecord) -> SlideState:
    return {
        "task_id": str(task.id),
        "raw_requirement": task.raw_requirement.model_dump(mode="json"),
        "model_preference": task.model_preference.model_dump(mode="json"),
        "task_complexity": task.complexity.model_dump(mode="json"),
        "workflow_stage": "parse_requirement",
    }


def build_slide_graph(
    gateway: ModelGateway,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    retriever: PageRetriever | None = None,
    slide_repository: SlideRepository | None = None,
    progress_reporter: ProgressReporter | None = None,
    settings: Settings | None = None,
    revision_repository: RevisionRepository | None = None,
    chunk_id_loader: Callable[[UUID], Awaitable[set[UUID]]] | None = None,
) -> Any:
    configured = settings or Settings()

    async def parse_requirement(state: SlideState) -> dict[str, object]:
        raw = RawRequirement.model_validate(state["raw_requirement"])
        requirement_context = raw.model_dump(mode="json")
        result = await gateway.invoke_structured(
            task_id=state["task_id"],
            node="parse_requirement",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract a presentation requirement. Do not invent information. "
                        "Return null for any field the user did not provide or clearly imply."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(requirement_context, ensure_ascii=False),
                },
            ],
            output_schema=StructuredRequirement,
            preference=ModelPreference.model_validate(state["model_preference"]),
            complexity=_complexity(state),
            idempotency_key=f"{state['task_id']}:parse_requirement",
        )
        return {
            "structured_requirement": result.output.model_dump(mode="json"),
            "workflow_stage": "requirement_review",
        }

    def requirement_route(state: SlideState) -> Literal["clarify", "complete"]:
        requirement = StructuredRequirement.model_validate(state.get("structured_requirement"))
        return "clarify" if requirement.missing_fields() else "complete"

    def review_requirement(state: SlideState) -> dict[str, object]:
        requirement = StructuredRequirement.model_validate(state.get("structured_requirement"))
        response = cast(
            dict[str, Any],
            interrupt(
                {
                    "kind": "requirement",
                    "requirement": requirement.model_dump(mode="json"),
                    "missing_fields": requirement.missing_fields(),
                }
            ),
        )
        confirmed = StructuredRequirement.model_validate(response.get("structured_requirement"))
        return {
            "structured_requirement": confirmed.model_dump(mode="json"),
            "workflow_stage": "requirement_review",
        }

    def calculate_complexity(state: SlideState) -> dict[str, object]:
        requirement = StructuredRequirement.model_validate(state.get("structured_requirement"))
        raw = RawRequirement.model_validate(state["raw_requirement"])
        complexity = score_complexity(
            target_page_count=requirement.target_page_count or raw.target_page_count,
            estimated_reference_tokens=raw.estimated_reference_tokens,
            constraint_count=len(requirement.constraints),
            domain_expertise=requirement.domain_expertise,
            analysis_depth=requirement.analysis_depth,
        )
        return {
            "task_complexity": complexity.model_dump(mode="json"),
            "workflow_stage": "plan_outline",
        }

    async def plan_outline(state: SlideState) -> dict[str, object]:
        requirement = StructuredRequirement.model_validate(state.get("structured_requirement"))
        result = await gateway.invoke_structured(
            task_id=state["task_id"],
            node="plan_outline",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Plan a hierarchical presentation outline. Section page counts and "
                        "their item page counts must each add up to target_page_count. "
                        "Use stable unique IDs and do not draft slide body text."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(requirement.model_dump(mode="json"), ensure_ascii=False),
                },
            ],
            output_schema=Outline,
            preference=ModelPreference.model_validate(state["model_preference"]),
            complexity=_complexity(state),
            idempotency_key=f"{state['task_id']}:plan_outline",
        )
        return {
            "outline": result.output.model_dump(mode="json"),
            "workflow_stage": "outline_review",
        }

    def validate_outline_node(state: SlideState) -> dict[str, object]:
        outline = Outline.model_validate(state.get("outline"))
        requirement = StructuredRequirement.model_validate(state.get("structured_requirement"))
        issues = validate_outline(outline, requirement.target_page_count or 0)
        return {
            "outline_issues": [issue.model_dump(mode="json") for issue in issues],
        }

    def review_outline(state: SlideState) -> dict[str, object]:
        response = cast(
            dict[str, Any],
            interrupt(
                {
                    "kind": "outline",
                    "outline": state.get("outline"),
                    "issues": state.get("outline_issues", []),
                }
            ),
        )
        outline = Outline.model_validate(response.get("outline"))
        requirement = StructuredRequirement.model_validate(state.get("structured_requirement"))
        issues = validate_outline(outline, requirement.target_page_count or 0)
        if issues:
            raise ValueError("An invalid outline cannot be confirmed.")
        return {
            "outline": outline.model_dump(mode="json"),
            "outline_issues": [],
            "outline_confirmed": True,
            "workflow_stage": "outline_confirmed",
        }

    async def write_slides(state: SlideState) -> dict[str, object]:
        if retriever is None or slide_repository is None:
            raise RuntimeError("Slide writing requires a retriever and slide repository.")
        requirement = StructuredRequirement.model_validate(state.get("structured_requirement"))
        outline = Outline.model_validate(state.get("outline"))
        slides = await write_slide_batches(
            task_id=UUID(state["task_id"]),
            requirement=requirement,
            outline=outline,
            writer=GatewayBatchWriter(gateway),
            retriever=retriever,
            repository=slide_repository,
            preference=ModelPreference.model_validate(state["model_preference"]),
            complexity=_complexity(state),
            progress_reporter=progress_reporter,
        )
        return {
            "slides_content": [slide.model_dump(mode="json") for slide in slides],
            "workflow_stage": "generate_markdown",
        }

    def generate_markdown(state: SlideState) -> dict[str, object]:
        outline = Outline.model_validate(state.get("outline"))
        slides = [SlideContent.model_validate(item) for item in state.get("slides_content", [])]
        return {
            "final_markdown": render_markdown(outline, slides),
            "workflow_stage": "evaluate",
        }

    async def evaluate(state: SlideState) -> dict[str, object]:
        requirement = StructuredRequirement.model_validate(state.get("structured_requirement"))
        outline = Outline.model_validate(state.get("outline"))
        slides = [SlideContent.model_validate(item) for item in state.get("slides_content", [])]
        allowed_chunk_ids = (
            await chunk_id_loader(UUID(state["task_id"])) if chunk_id_loader is not None else None
        )
        hard_checks = run_hard_checks(
            slides,
            requirement,
            outline,
            allowed_chunk_ids=allowed_chunk_ids,
        )
        output = await gateway.invoke_structured(
            task_id=state["task_id"],
            node="evaluate_quality",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Evaluate the complete presentation across exactly four dimensions: "
                        "completeness, logic, content_quality, requirement_alignment. Use equal "
                        "weights totaling 100. Scores are 0..100. Every issue must include a "
                        "code, severity, affected slide ID scope, description and executable "
                        "suggestion. Do not modify the presentation."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "requirement": requirement.model_dump(mode="json"),
                            "outline": outline.model_dump(mode="json"),
                            "slides": [
                                {
                                    "id": str(slide.id),
                                    "page_number": slide.page_number,
                                    "section_id": slide.section_id,
                                    "outline_item_id": slide.outline_item_id,
                                    "title": slide.title,
                                    "bullets": slide.bullets,
                                    "speaker_notes": slide.speaker_notes,
                                }
                                for slide in slides
                            ],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            output_schema=EvaluationDraft,
            preference=ModelPreference.model_validate(state["model_preference"]),
            complexity=_complexity(state),
            idempotency_key=f"{state['task_id']}:evaluate:{state.get('revision_total', 0)}",
        )
        result = evaluate_quality(
            slides,
            requirement,
            outline,
            output.output,
            threshold=configured.evaluation_pass_score,
            allowed_chunk_ids=allowed_chunk_ids,
            hard_checks=hard_checks,
        )
        return {
            "evaluation_result": result.model_dump(mode="json"),
            "revision_count": state.get("revision_count", 0),
            "revision_total": state.get("revision_total", 0),
            "workflow_stage": "evaluate",
        }

    def evaluation_route(state: SlideState) -> Literal["complete", "refine", "review"]:
        result = EvaluationResult.model_validate(state.get("evaluation_result"))
        if result.passed:
            return "complete"
        if can_auto_refine(
            result,
            revision_count=state.get("revision_count", 0),
            max_auto_revisions=configured.max_auto_revisions,
        ):
            return "refine"
        return "review"

    def review_evaluation(state: SlideState) -> dict[str, object]:
        response = cast(
            dict[str, Any],
            interrupt(
                {
                    "kind": "evaluation_limit",
                    "evaluation_result": state.get("evaluation_result"),
                    "revision_count": state.get("revision_count", 0),
                    "actions": ["accept", "refine", "cancel"],
                }
            ),
        )
        action = response.get("action")
        if action == "accept":
            return {"user_decision": "accept", "workflow_stage": "completed"}
        if action == "cancel":
            return {
                "user_decision": "cancel",
                "workflow_cancelled": True,
                "workflow_stage": "cancelled",
            }
        if action != "refine":
            raise ValueError("An evaluation decision must be accept, refine or cancel.")
        feedback = response.get("feedback")
        if not isinstance(feedback, str) or not feedback.strip():
            raise ValueError("User feedback is required to refine the presentation.")
        scope_value: object = response.get("scope", [])
        if not isinstance(scope_value, list) or any(
            not isinstance(item, str) for item in cast(list[object], scope_value)
        ):
            raise ValueError("A refinement scope must contain slide IDs.")
        return {
            "user_decision": "refine",
            "user_feedback": feedback.strip(),
            "user_scope": cast(list[str], scope_value),
            "workflow_stage": "refine_content",
        }

    def review_decision_route(state: SlideState) -> Literal["complete", "refine", "cancel"]:
        if state.get("user_decision") == "accept":
            return "complete"
        if state.get("user_decision") == "cancel":
            return "cancel"
        return "refine"

    async def refine(state: SlideState) -> dict[str, object]:
        if slide_repository is None:
            raise RuntimeError("Slide refinement requires a slide repository.")
        task_id = UUID(state["task_id"])
        slides = [SlideContent.model_validate(item) for item in state.get("slides_content", [])]
        result = EvaluationResult.model_validate(state.get("evaluation_result"))
        is_user_revision = state.get("user_decision") == "refine"
        if is_user_revision:
            raw_scope = state.get("user_scope", [])
            scope = (
                {UUID(item) for item in raw_scope} if raw_scope else _issue_scope(result, slides)
            )
            feedback = state.get("user_feedback", "")
            revision_type = "USER"
        else:
            scope = _issue_scope(result, slides)
            feedback = (
                "\n".join(
                    [
                        *(
                            f"{issue.description} 建议：{issue.suggestion}"
                            for issue in result.issues
                        ),
                        *result.suggestions,
                    ]
                )
                or "请结合整体逻辑摘要提升完整性、逻辑性和需求符合度。"
            )
            revision_type = "AUTO"

        async def call_refiner(
            selected: list[SlideContent], neighbors: list[dict[str, object]], notes: str
        ) -> list[Any]:
            output = await gateway.invoke_structured(
                task_id=task_id,
                node="refine_content",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Revise only the supplied target slides. Preserve each stable slide "
                            "ID, respond with exactly those IDs, keep citations and page identity "
                            "outside your output, and keep each page to 2..6 concise bullets. "
                            "Use adjacent slide summaries only to preserve transitions."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "slides": [
                                    {
                                        "id": str(slide.id),
                                        "title": slide.title,
                                        "bullets": slide.bullets,
                                        "speaker_notes": slide.speaker_notes,
                                        "verification_notes": slide.verification_notes,
                                    }
                                    for slide in selected
                                ],
                                "adjacent_summaries": neighbors,
                                "feedback": notes,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                output_schema=SlideRefinementDraft,
                preference=ModelPreference.model_validate(state["model_preference"]),
                complexity=_complexity(state),
                idempotency_key=(f"{state['task_id']}:refine:{state.get('revision_total', 0)}"),
            )
            return output.output.slides

        revised = await refine_content(slides, scope, feedback, call_refiner)
        changed = [slide for slide in revised if slide.id in scope]
        await slide_repository.upsert_batch(task_id, changed)
        revision_total = state.get("revision_total", 0) + 1
        revision_number = (
            await revision_repository.next_revision_number(task_id)
            if revision_repository is not None
            else revision_total
        )
        revision = Revision(
            task_id=task_id,
            revision_number=revision_number,
            revision_type=revision_type,
            scope=[str(item) for item in sorted(scope, key=str)],
            reason=feedback,
            before_slides=slides,
            after_slides=revised,
            score_before=result.total_score,
            created_at=datetime.now(UTC),
        )
        if revision_repository is not None:
            await revision_repository.add(revision)
        return {
            "slides_content": [slide.model_dump(mode="json") for slide in revised],
            "final_markdown": render_markdown(
                Outline.model_validate(state.get("outline")), revised
            ),
            "revision_total": revision_total,
            "revision_count": state.get("revision_count", 0) + (1 if not is_user_revision else 0),
            "user_decision": "",
            "user_feedback": "",
            "user_scope": [],
            "workflow_stage": "evaluate",
        }

    def complete(state: SlideState) -> dict[str, object]:
        slides = [SlideContent.model_validate(item) for item in state.get("slides_content", [])]
        outline = Outline.model_validate(state.get("outline"))
        return {
            "final_markdown": render_markdown(outline, slides),
            "workflow_stage": "completed",
        }

    def cancel_evaluation(_: SlideState) -> dict[str, object]:
        return {"workflow_cancelled": True, "workflow_stage": "cancelled"}

    builder = cast(Any, StateGraph(SlideState))
    builder.add_node("parse_requirement", parse_requirement)
    builder.add_node("review_requirement", review_requirement)
    builder.add_node("calculate_complexity", calculate_complexity)
    builder.add_node("plan_outline", plan_outline)
    builder.add_node("validate_outline", validate_outline_node)
    builder.add_node("review_outline", review_outline)
    builder.add_node("write_slides", write_slides)
    builder.add_node("generate_markdown", generate_markdown)
    builder.add_node("evaluate_quality", evaluate)
    builder.add_node("review_evaluation", review_evaluation)
    builder.add_node("refine_content", refine)
    builder.add_node("complete", complete)
    builder.add_node("cancel_evaluation", cancel_evaluation)
    builder.add_edge(START, "parse_requirement")
    builder.add_conditional_edges(
        "parse_requirement",
        requirement_route,
        {"clarify": "review_requirement", "complete": "calculate_complexity"},
    )
    builder.add_conditional_edges(
        "review_requirement",
        requirement_route,
        {"clarify": "review_requirement", "complete": "calculate_complexity"},
    )
    builder.add_edge("calculate_complexity", "plan_outline")
    builder.add_edge("plan_outline", "validate_outline")
    builder.add_edge("validate_outline", "review_outline")
    builder.add_edge("review_outline", "write_slides")
    builder.add_edge("write_slides", "generate_markdown")
    builder.add_edge("generate_markdown", "evaluate_quality")
    builder.add_conditional_edges(
        "evaluate_quality",
        evaluation_route,
        {"complete": "complete", "refine": "refine_content", "review": "review_evaluation"},
    )
    builder.add_conditional_edges(
        "review_evaluation",
        review_decision_route,
        {
            "complete": "complete",
            "refine": "refine_content",
            "cancel": "cancel_evaluation",
        },
    )
    builder.add_edge("refine_content", "evaluate_quality")
    builder.add_edge("complete", END)
    builder.add_edge("cancel_evaluation", END)
    return builder.compile(checkpointer=checkpointer)


def _issue_scope(result: EvaluationResult, slides: list[SlideContent]) -> set[UUID]:
    known_ids = {slide.id for slide in slides}
    selected = {
        UUID(item)
        for issue in result.issues
        for item in issue.scope
        if _is_uuid(item) and UUID(item) in known_ids
    }
    return selected or known_ids


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except ValueError:
        return False


def _complexity(state: SlideState) -> Any:
    from slideai.domain.tasks.complexity import TaskComplexity

    return TaskComplexity.model_validate(state.get("task_complexity"))
