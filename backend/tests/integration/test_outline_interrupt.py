import os
from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from pydantic import BaseModel

from slideai.application.models.gateway import ModelGateway
from slideai.core.config import get_settings
from slideai.domain.models.catalog import ModelCatalog, ModelDefinition, NodePolicy
from slideai.domain.requirements.models import Outline, OutlineItem, OutlineSection
from slideai.domain.tasks.complexity import ComplexityTier
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
    catalog = ModelCatalog(
        models={
            key: ModelDefinition(
                key=key,
                display_name=key,
                provider="fake",
                model_id=key,
                base_url="",
                api_key_env="",
                tier=tier,
            )
            for key, tier in (("fast", ComplexityTier.FAST), ("balanced", ComplexityTier.BALANCED))
        },
        node_policies={"plan_outline": NodePolicy(minimum_tier=ComplexityTier.BALANCED)},
    )
    return ModelGateway(model_catalog=catalog, providers={"fake": SequenceProvider(responses)})


def _task() -> TaskRecord:
    requirement = RawRequirement(
        topic="Industry outlook",
        target_page_count=12,
        scenario="Annual strategy review",
        audience="Leadership team",
        style="Evidence-led",
    )
    now = datetime.now(UTC)
    return TaskRecord(
        name=requirement.topic,
        raw_requirement=requirement,
        model_preference=ModelPreference(),
        complexity=initial_complexity(requirement),
        created_at=now,
        updated_at=now,
    )


def _requirement() -> dict[str, Any]:
    return {
        "topic": "Industry outlook",
        "target_page_count": 12,
        "scenario": "Annual strategy review",
        "audience": "Leadership team",
        "style": "Evidence-led",
        "constraints": [],
        "language": "zh-CN",
        "source_usage": "preferred",
        "original_text": None,
        "domain_expertise": "general",
        "analysis_depth": "overview",
    }


def _outline() -> Outline:
    return Outline(
        title="Industry outlook",
        sections=[
            OutlineSection(
                id="market",
                title="Market",
                objective="Explain the market context",
                page_count=12,
                items=[
                    OutlineItem(
                        id="market-size",
                        title="Market size",
                        objective="Describe market scale",
                        page_count=12,
                    )
                ],
            )
        ],
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_outline_interrupt_resumes_after_worker_restart() -> None:
    if os.getenv("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_INTEGRATION_TESTS=1 when Compose dependencies are available")

    settings = get_settings()
    task = _task()
    config = {"configurable": {"thread_id": str(task.id)}}
    outline = _outline()
    gateway = _gateway([_requirement(), outline.model_dump(mode="json")])

    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_database_url) as saver:
        await saver.setup()
        graph = build_slide_graph(gateway, checkpointer=saver)
        paused = await graph.ainvoke(build_initial_state(task), config)

    assert [item.value["kind"] for item in paused["__interrupt__"]] == ["outline"]

    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_database_url) as saver:
        await saver.setup()
        graph = build_slide_graph(_gateway([]), checkpointer=saver)
        resumed = await graph.ainvoke(
            Command(
                resume={"kind": "outline_confirmed", "outline": outline.model_dump(mode="json")}
            ),
            config,
        )
        assert resumed["outline_confirmed"] is True
        await saver.adelete_thread(str(task.id))
