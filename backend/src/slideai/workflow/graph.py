import json
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
from slideai.application.models.gateway import ModelGateway
from slideai.domain.content.models import SlideContent
from slideai.domain.requirements.models import Outline, StructuredRequirement
from slideai.domain.requirements.validation import validate_outline
from slideai.domain.tasks.complexity import score_complexity
from slideai.domain.tasks.models import ModelPreference, RawRequirement, TaskRecord


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
) -> Any:
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
        target_count = len(slides)
        if target_count != len({slide.page_number for slide in slides}):
            raise ValueError("Generated pages must not contain duplicate page numbers.")
        if [slide.page_number for slide in slides] != list(range(1, target_count + 1)):
            raise ValueError("Generated page numbers must be continuous.")
        return {
            "final_markdown": render_markdown(outline, slides),
            "workflow_stage": "completed",
        }

    builder = cast(Any, StateGraph(SlideState))
    builder.add_node("parse_requirement", parse_requirement)
    builder.add_node("review_requirement", review_requirement)
    builder.add_node("calculate_complexity", calculate_complexity)
    builder.add_node("plan_outline", plan_outline)
    builder.add_node("validate_outline", validate_outline_node)
    builder.add_node("review_outline", review_outline)
    builder.add_node("write_slides", write_slides)
    builder.add_node("generate_markdown", generate_markdown)
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
    builder.add_edge("generate_markdown", END)
    return builder.compile(checkpointer=checkpointer)


def _complexity(state: SlideState) -> Any:
    from slideai.domain.tasks.complexity import TaskComplexity

    return TaskComplexity.model_validate(state.get("task_complexity"))
