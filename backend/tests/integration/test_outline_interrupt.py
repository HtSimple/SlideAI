import os
from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from pydantic import BaseModel

from slideai.application.models.gateway import ModelGateway
from slideai.core.config import get_settings
from slideai.domain.content.models import SlideBatch, SlideContent, SlideDraft
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


def _slide_batches() -> list[dict[str, Any]]:
    return [
        SlideBatch(
            slides=[
                SlideDraft(
                    page_number=page_number,
                    title=f"Page {page_number}",
                    bullets=["Evidence-led finding", "Actionable implication"],
                )
                for page_number in range(first, last + 1)
            ]
        ).model_dump(mode="json")
        for first, last in ((1, 5), (6, 10), (11, 12))
    ]


def _evaluation_draft() -> dict[str, Any]:
    return {
        "dimensions": [
            {"name": name, "score": 90, "weight": 25, "feedback": "Clear and complete."}
            for name in (
                "completeness",
                "logic",
                "content_quality",
                "requirement_alignment",
            )
        ],
        "issues": [],
        "suggestions": [],
    }


class EmptyRetriever:
    async def search(self, task_id: UUID, query: str):
        return []


class MemorySlides:
    def __init__(self) -> None:
        self.slides: list[SlideContent] = []

    async def list_for_task(self, task_id: UUID) -> list[SlideContent]:
        return list(self.slides)

    async def upsert_batch(self, task_id: UUID, slides: list[SlideContent]) -> None:
        self.slides.extend(slides)


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
        slide_repository = MemorySlides()
        graph = build_slide_graph(
            _gateway([*_slide_batches(), _evaluation_draft()]),
            checkpointer=saver,
            retriever=EmptyRetriever(),
            slide_repository=slide_repository,
        )
        resumed = await graph.ainvoke(
            Command(
                resume={"kind": "outline_confirmed", "outline": outline.model_dump(mode="json")}
            ),
            config,
        )
        assert resumed["outline_confirmed"] is True
        assert [slide["page_number"] for slide in resumed["slides_content"]] == list(range(1, 13))
        assert len(slide_repository.slides) == 12
        assert resumed["evaluation_result"]["passed"] is True
        assert resumed["final_markdown"].startswith("# Industry outlook\n")
        await saver.adelete_thread(str(task.id))
