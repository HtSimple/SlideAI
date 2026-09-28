from typing import Any

import pytest
from pydantic import BaseModel

from slideai.application.models.gateway import ModelGateway
from slideai.core.errors import ModelAuthenticationError, ModelTransientError
from slideai.domain.models.catalog import ModelCatalog, ModelDefinition, NodePolicy
from slideai.domain.tasks.complexity import ComplexityTier, TaskComplexity
from slideai.domain.tasks.models import ModelPreference


class Summary(BaseModel):
    text: str


class QueueProvider:
    def __init__(self, results: dict[str, list[Any]]) -> None:
        self.results = {key: list(value) for key, value in results.items()}
        self.calls: list[str] = []

    async def invoke_structured(
        self,
        *,
        model: ModelDefinition,
        messages: list[dict[str, str]],
        output_schema: type[BaseModel],
        idempotency_key: str,
    ) -> BaseModel:
        self.calls.append(model.key)
        result = self.results[model.key].pop(0)
        if isinstance(result, Exception):
            raise result
        return output_schema.model_validate(result)


def catalog() -> ModelCatalog:
    return ModelCatalog(
        models={
            "primary": ModelDefinition(
                key="primary",
                display_name="Primary",
                provider="fake",
                model_id="primary-model",
                base_url="http://fake.invalid/v1",
                api_key_env="FAKE_API_KEY",
                tier=ComplexityTier.ADVANCED,
                fallbacks=["fallback"],
            ),
            "fallback": ModelDefinition(
                key="fallback",
                display_name="Fallback",
                provider="fake",
                model_id="fallback-model",
                base_url="http://fake.invalid/v1",
                api_key_env="FAKE_API_KEY",
                tier=ComplexityTier.BALANCED,
            ),
        },
        node_policies={"write_slides": NodePolicy(minimum_tier=ComplexityTier.FAST)},
    )


@pytest.mark.asyncio
async def test_gateway_retries_then_uses_fallback() -> None:
    provider = QueueProvider(
        {
            "primary": [
                ModelTransientError("temporary", error_type="timeout"),
                ModelTransientError("temporary", error_type="timeout"),
                ModelTransientError("temporary", error_type="timeout"),
            ],
            "fallback": [{"text": "Recovered"}],
        }
    )
    gateway = ModelGateway(
        model_catalog=catalog(),
        providers={"fake": provider},
        sleep=lambda _: _no_wait(),
    )
    complexity = TaskComplexity(tier=ComplexityTier.ADVANCED, total_score=9, factors={})

    result = await gateway.invoke_structured(
        task_id="70f25504-e0ae-43e0-a85c-7b0d38469c73",
        node="write_slides",
        messages=[{"role": "user", "content": "summarize"}],
        output_schema=Summary,
        preference=ModelPreference(mode="manual", model_key="primary"),
        complexity=complexity,
        idempotency_key="task:write:1",
    )

    assert result.output.text == "Recovered"
    assert result.actual_model_key == "fallback"
    assert result.fallback_occurred is True
    assert provider.calls == ["primary", "primary", "primary", "fallback"]


@pytest.mark.asyncio
async def test_gateway_does_not_retry_401() -> None:
    provider = QueueProvider({"primary": [ModelAuthenticationError("unauthorized")]})
    gateway = ModelGateway(model_catalog=catalog(), providers={"fake": provider})
    complexity = TaskComplexity(tier=ComplexityTier.ADVANCED, total_score=9, factors={})

    with pytest.raises(ModelAuthenticationError):
        await gateway.invoke_structured(
            task_id="70f25504-e0ae-43e0-a85c-7b0d38469c73",
            node="write_slides",
            messages=[{"role": "user", "content": "summarize"}],
            output_schema=Summary,
            preference=ModelPreference(mode="manual", model_key="primary"),
            complexity=complexity,
            idempotency_key="task:write:1",
        )

    assert provider.calls == ["primary"]


@pytest.mark.asyncio
async def test_gateway_reports_retryable_error_when_every_model_is_exhausted() -> None:
    provider = QueueProvider(
        {
            "primary": [
                ModelTransientError("temporary", error_type="timeout"),
                ModelTransientError("temporary", error_type="timeout"),
                ModelTransientError("temporary", error_type="timeout"),
            ],
            "fallback": [
                ModelTransientError("temporary", error_type="unavailable"),
                ModelTransientError("temporary", error_type="unavailable"),
                ModelTransientError("temporary", error_type="unavailable"),
            ],
        }
    )
    gateway = ModelGateway(
        model_catalog=catalog(),
        providers={"fake": provider},
        sleep=lambda _: _no_wait(),
    )
    complexity = TaskComplexity(tier=ComplexityTier.ADVANCED, total_score=9, factors={})

    with pytest.raises(ModelTransientError, match="All configured models failed") as failure:
        await gateway.invoke_structured(
            task_id="70f25504-e0ae-43e0-a85c-7b0d38469c73",
            node="write_slides",
            messages=[{"role": "user", "content": "summarize"}],
            output_schema=Summary,
            preference=ModelPreference(mode="manual", model_key="primary"),
            complexity=complexity,
            idempotency_key="task:write:1",
        )

    assert failure.value.error_type == "fallback_exhausted"
    assert provider.calls == ["primary"] * 3 + ["fallback"] * 3


@pytest.mark.asyncio
async def test_gateway_repairs_structured_output_once() -> None:
    provider = QueueProvider(
        {"primary": [{"private": "SENSITIVE DOCUMENT BODY"}, {"text": "Recovered"}]}
    )
    audit_records: list[dict[str, Any]] = []

    async def record_call(record: dict[str, Any]) -> None:
        audit_records.append(record)

    gateway = ModelGateway(
        model_catalog=catalog(), providers={"fake": provider}, audit_writer=record_call
    )
    complexity = TaskComplexity(tier=ComplexityTier.ADVANCED, total_score=9, factors={})

    result = await gateway.invoke_structured(
        task_id="70f25504-e0ae-43e0-a85c-7b0d38469c73",
        node="write_slides",
        messages=[{"role": "user", "content": "summarize"}],
        output_schema=Summary,
        preference=ModelPreference(mode="manual", model_key="primary"),
        complexity=complexity,
        idempotency_key="task:write:1",
    )

    assert result.output.text == "Recovered"
    assert provider.calls == ["primary", "primary"]
    assert [record["status"] for record in audit_records] == ["FAILED", "SUCCEEDED"]
    assert "SENSITIVE DOCUMENT BODY" not in str(audit_records)


async def _no_wait() -> None:
    return None
