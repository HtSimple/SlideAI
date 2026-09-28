from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

from slideai.application.models.gateway import ModelGateway
from slideai.domain.models.catalog import ModelCatalog, ModelDefinition, NodePolicy
from slideai.domain.requirements.models import StructuredRequirement
from slideai.domain.tasks.complexity import ComplexityTier, TaskComplexity
from slideai.domain.tasks.models import (
    ModelPreference,
    RawRequirement,
    TaskRecord,
    initial_complexity,
)
from slideai.workflow.graph import build_initial_state, build_slide_graph


class SequenceProvider:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = deque(responses)

    async def invoke_structured(
        self,
        *,
        model: ModelDefinition,
        messages: Sequence[dict[str, str]],
        output_schema: type[BaseModel],
        idempotency_key: str,
    ) -> BaseModel:
        return output_schema.model_validate(self.responses.popleft())


def _gateway(responses: list[dict[str, Any]]) -> ModelGateway:
    models = ModelCatalog(
        models={
            "fast": ModelDefinition(
                key="fast",
                display_name="Fast fake",
                provider="fake",
                model_id="fast",
                base_url="",
                api_key_env="",
                tier=ComplexityTier.FAST,
            ),
            "balanced": ModelDefinition(
                key="balanced",
                display_name="Balanced fake",
                provider="fake",
                model_id="balanced",
                base_url="",
                api_key_env="",
                tier=ComplexityTier.BALANCED,
            ),
        },
        node_policies={"plan_outline": NodePolicy(minimum_tier=ComplexityTier.BALANCED)},
    )
    return ModelGateway(model_catalog=models, providers={"fake": SequenceProvider(responses)})


def _task() -> TaskRecord:
    requirement = RawRequirement(topic="Industry outlook", target_page_count=12)
    now = datetime.now(UTC)
    return TaskRecord(
        name=requirement.topic,
        raw_requirement=requirement,
        model_preference=ModelPreference(),
        complexity=initial_complexity(requirement),
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_missing_requirement_enters_clarification() -> None:
    incomplete = StructuredRequirement(
        topic="Industry outlook",
        target_page_count=12,
        scenario=None,
        audience="",
        style="Executive",
    )
    graph = build_slide_graph(
        _gateway([incomplete.model_dump(mode="json")]), checkpointer=InMemorySaver()
    )
    task = _task()

    result = await graph.ainvoke(
        build_initial_state(task), {"configurable": {"thread_id": str(task.id)}}
    )

    assert [item.value["kind"] for item in result["__interrupt__"]] == ["requirement"]


def test_workflow_models_use_bounded_target_fields() -> None:
    with pytest.raises(ValueError):
        StructuredRequirement(topic="Industry outlook", target_page_count=51)

    with pytest.raises(ValueError):
        TaskComplexity(tier=ComplexityTier.FAST, total_score=11, factors={})
