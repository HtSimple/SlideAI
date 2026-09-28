import json
from uuid import UUID, uuid4

import pytest

from slideai.application.models.factory import create_model_runtime
from slideai.core.config import Settings
from slideai.domain.content.models import SlideBatch
from slideai.domain.requirements.models import Outline, StructuredRequirement
from slideai.domain.tasks.complexity import ComplexityTier, TaskComplexity
from slideai.domain.tasks.models import ModelPreference


@pytest.mark.asyncio
async def test_explicit_fake_runtime_generates_requirement_outline_and_pages() -> None:
    _, gateway = create_model_runtime(Settings(generation_provider="fake", _env_file=None))
    task_id = uuid4()
    complexity = TaskComplexity(tier=ComplexityTier.FAST, total_score=1, factors={})
    raw_requirement = {
        "topic": "储能行业趋势",
        "target_page_count": 6,
        "scenario": "年度经营分析",
        "audience": "管理层",
        "style": "结论先行",
        "special_constraints": ["提供行动建议"],
        "estimated_reference_tokens": 0,
        "original_text": "面向管理层做储能行业趋势分析。",
    }

    requirement = await gateway.invoke_structured(
        task_id=task_id,
        node="parse_requirement",
        messages=[{"role": "user", "content": json.dumps(raw_requirement)}],
        output_schema=StructuredRequirement,
        preference=ModelPreference(),
        complexity=complexity,
        idempotency_key=f"{task_id}:requirement",
    )
    assert requirement.output.topic == "储能行业趋势"
    assert requirement.output.target_page_count == 6
    assert requirement.output.missing_fields() == []

    outline = await gateway.invoke_structured(
        task_id=task_id,
        node="plan_outline",
        messages=[{"role": "user", "content": requirement.output.model_dump_json()}],
        output_schema=Outline,
        preference=ModelPreference(),
        complexity=complexity,
        idempotency_key=f"{task_id}:outline",
    )
    section = outline.output.sections[0]
    assert sum(item.page_count for item in section.items) == 6
    assert section.page_count == 6

    evidence = {
        "1": [
            {
                "chunk_id": str(uuid4()),
                "display_name": "储能报告.pdf",
                "page_number": 7,
                "section_title": "装机趋势",
                "content": "储能装机规模持续增加。",
            }
        ]
    }
    batch = await gateway.invoke_structured(
        task_id=task_id,
        node="write_slides",
        messages=[
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "requirement": requirement.output.model_dump(mode="json"),
                        "page_plans": [
                            {
                                "page_number": 1,
                                "section_id": section.id,
                                "outline_item_id": section.items[0].id,
                                "title": "市场变化",
                                "objective": "说明市场变化",
                            }
                        ],
                        "untrusted_source_evidence": evidence,
                    }
                ),
            }
        ],
        output_schema=SlideBatch,
        preference=ModelPreference(),
        complexity=complexity,
        idempotency_key=f"{task_id}:slides",
    )
    assert batch.output.slides[0].page_number == 1
    assert batch.output.slides[0].citations[0].chunk_id == UUID(evidence["1"][0]["chunk_id"])


def test_model_runtime_uses_the_fake_catalog_only_when_explicitly_selected() -> None:
    fake_catalog, _ = create_model_runtime(Settings(generation_provider="fake", _env_file=None))
    openai_catalog, _ = create_model_runtime(
        Settings(generation_provider="openai_compatible", _env_file=None)
    )

    assert all(model.provider == "fake" for model in fake_catalog.models.values())
    assert all(model.provider == "openai_compatible" for model in openai_catalog.models.values())
