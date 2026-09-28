import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ValidationError

from slideai.core.errors import (
    ModelAuthenticationError,
    ModelOutputValidationError,
    ModelPermanentError,
    ModelTransientError,
)
from slideai.domain.models.catalog import ModelCatalog, ModelDefinition
from slideai.domain.tasks.complexity import ComplexityTier, TaskComplexity
from slideai.domain.tasks.models import ModelPreference

T = TypeVar("T", bound=BaseModel)
AuditWriter = Callable[[dict[str, Any]], Awaitable[None]]
ModelMessage = dict[str, str]


class StructuredProvider(Protocol):
    async def invoke_structured(
        self,
        *,
        model: ModelDefinition,
        messages: Sequence[ModelMessage],
        output_schema: type[BaseModel],
        idempotency_key: str,
    ) -> BaseModel: ...


@dataclass(frozen=True)
class ModelResult[T]:
    output: T
    preferred_model_key: str
    actual_model_key: str
    fallback_occurred: bool
    route_reason: dict[str, Any]


class ModelGateway:
    def __init__(
        self,
        *,
        model_catalog: ModelCatalog,
        providers: dict[str, StructuredProvider],
        audit_writer: AuditWriter | None = None,
        retries: int = 2,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self.model_catalog = model_catalog
        self.providers = providers
        self.audit_writer = audit_writer
        self.retries = retries
        self.sleep = sleep
        self.random_value = random_value

    async def invoke_structured(
        self,
        *,
        task_id: str | UUID,
        node: str,
        messages: Sequence[ModelMessage],
        output_schema: type[T],
        preference: ModelPreference,
        complexity: TaskComplexity,
        idempotency_key: str,
    ) -> ModelResult[T]:
        preferred = self._choose_model(node, preference, complexity)
        node_policy = self.model_catalog.node_policies.get(node)
        route_reason = {
            "preference_mode": preference.mode,
            "complexity_tier": complexity.tier.value,
            "complexity_score": complexity.total_score,
            "requested_tier": self._requested_tier(node, preference, complexity, preferred).value,
            "node_minimum_tier": node_policy.minimum_tier.value
            if node_policy
            else ComplexityTier.FAST.value,
        }
        model = preferred
        fallback_from: str | None = None
        attempted: set[str] = set()
        while model.key not in attempted:
            attempted.add(model.key)
            provider = self.providers.get(model.provider)
            if provider is None:
                raise ModelPermanentError(f"Provider {model.provider!r} is not configured.")
            transient_retries = 0
            attempt_number = 0
            schema_repaired = False
            request_messages = messages
            while True:
                attempt_number += 1
                started = time.monotonic()
                try:
                    result = await provider.invoke_structured(
                        model=model,
                        messages=request_messages,
                        output_schema=output_schema,
                        idempotency_key=(
                            f"{idempotency_key}:schema-repair"
                            if schema_repaired
                            else idempotency_key
                        ),
                    )
                    output = output_schema.model_validate(result)
                    await self._audit(
                        task_id=task_id,
                        node=node,
                        preferred=preferred,
                        actual=model,
                        attempt=attempt_number,
                        fallback_from=fallback_from,
                        route_reason=route_reason,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        status="SUCCEEDED",
                    )
                    return ModelResult(
                        output=output,
                        preferred_model_key=preferred.key,
                        actual_model_key=model.key,
                        fallback_occurred=model.key != preferred.key,
                        route_reason=route_reason,
                    )
                except (ValidationError, ModelOutputValidationError) as error:
                    await self._audit(
                        task_id=task_id,
                        node=node,
                        preferred=preferred,
                        actual=model,
                        attempt=attempt_number,
                        fallback_from=fallback_from,
                        route_reason=route_reason,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        status="FAILED",
                        error_type="output_validation",
                        error_message=_safe_error(error),
                    )
                    if schema_repaired:
                        break
                    schema_repaired = True
                    request_messages = [
                        *messages,
                        {
                            "role": "user",
                            "content": (
                                "Return a corrected response that satisfies the required "
                                "JSON schema. "
                                f"Validation error: {_safe_error(error)}"
                            ),
                        },
                    ]
                except ModelTransientError as error:
                    await self._audit(
                        task_id=task_id,
                        node=node,
                        preferred=preferred,
                        actual=model,
                        attempt=attempt_number,
                        fallback_from=fallback_from,
                        route_reason=route_reason,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        status="FAILED",
                        error_type=error.error_type,
                        error_message=_safe_error(error),
                    )
                    if transient_retries < self.retries:
                        await self.sleep(min(2**transient_retries + self.random_value(), 10))
                        transient_retries += 1
                        continue
                    break
                except ModelAuthenticationError as error:
                    await self._audit(
                        task_id=task_id,
                        node=node,
                        preferred=preferred,
                        actual=model,
                        attempt=attempt_number,
                        fallback_from=fallback_from,
                        route_reason=route_reason,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        status="FAILED",
                        error_type="authentication",
                        error_message="Model authentication failed.",
                    )
                    raise error
                except ModelPermanentError as error:
                    await self._audit(
                        task_id=task_id,
                        node=node,
                        preferred=preferred,
                        actual=model,
                        attempt=attempt_number,
                        fallback_from=fallback_from,
                        route_reason=route_reason,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        status="FAILED",
                        error_type=getattr(error, "error_type", "output_validation"),
                        error_message=_safe_error(error),
                    )
                    raise error
            next_model = self._next_fallback(model, attempted)
            if next_model is None:
                break
            fallback_from = model.key
            model = next_model
        raise ModelTransientError("All configured models failed.", error_type="fallback_exhausted")

    def _choose_model(
        self, node: str, preference: ModelPreference, complexity: TaskComplexity
    ) -> ModelDefinition:
        if preference.mode == "manual":
            key = preference.model_key or ""
            model = self.model_catalog.models.get(key)
            if model is None or not model.enabled:
                raise ModelPermanentError(
                    "The selected model is unavailable.", error_type="model_unavailable"
                )
            return model
        node_policy = self.model_catalog.node_policies.get(node)
        tiers = [complexity.tier, node_policy.minimum_tier if node_policy else ComplexityTier.FAST]
        tier = max(tiers, key=lambda item: list(ComplexityTier).index(item))
        try:
            return self.model_catalog.for_tier(tier)
        except ValueError as error:
            raise ModelPermanentError(
                "No configured model is available for the requested task tier.",
                error_type="model_unavailable",
            ) from error

    def _next_fallback(self, model: ModelDefinition, attempted: set[str]) -> ModelDefinition | None:
        for key in model.fallbacks:
            candidate = self.model_catalog.models.get(key)
            if candidate and candidate.enabled and candidate.available and key not in attempted:
                return candidate
        return None

    def _requested_tier(
        self,
        node: str,
        preference: ModelPreference,
        complexity: TaskComplexity,
        preferred: ModelDefinition,
    ) -> ComplexityTier:
        if preference.mode == "manual":
            return preferred.tier
        node_policy = self.model_catalog.node_policies.get(node)
        tiers = [complexity.tier, node_policy.minimum_tier if node_policy else ComplexityTier.FAST]
        return max(tiers, key=lambda item: list(ComplexityTier).index(item))

    async def _audit(
        self,
        *,
        task_id: str | UUID,
        node: str,
        preferred: ModelDefinition,
        actual: ModelDefinition,
        attempt: int,
        fallback_from: str | None,
        route_reason: dict[str, Any],
        latency_ms: int,
        status: str,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if self.audit_writer is None:
            return
        await self.audit_writer(
            {
                "id": uuid4(),
                "task_id": UUID(str(task_id)),
                "workflow_node": node,
                "requested_tier": route_reason["requested_tier"],
                "preferred_model_key": preferred.key,
                "actual_model_key": actual.key,
                "attempt_no": attempt,
                "fallback_from": fallback_from,
                "route_reason": route_reason,
                "latency_ms": latency_ms,
                "status": status,
                "error_type": error_type,
                "error_message": error_message,
            }
        )


class FakeProvider:
    """Predictable provider for local development and test fixtures."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[str] = []

    async def invoke_structured(
        self,
        *,
        model: ModelDefinition,
        messages: Sequence[ModelMessage],
        output_schema: type[BaseModel],
        idempotency_key: str,
    ) -> BaseModel:
        self.calls.append(model.key)
        result = self.responses.get(model.key, {})
        if isinstance(result, Exception):
            raise result
        return output_schema.model_validate(result)


class OpenAICompatibleProvider:
    async def invoke_structured(
        self,
        *,
        model: ModelDefinition,
        messages: Sequence[ModelMessage],
        output_schema: type[BaseModel],
        idempotency_key: str,
    ) -> BaseModel:
        import os

        api_key = os.getenv(model.api_key_env, "")
        if not api_key:
            raise ModelAuthenticationError("Model API key is not configured.")
        headers = {"Authorization": f"Bearer {api_key}", "Idempotency-Key": idempotency_key}
        body = {
            "model": model.model_id,
            "messages": list(messages),
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=model.timeout_seconds) as client:
                response = await client.post(
                    f"{model.base_url.rstrip('/')}/chat/completions", json=body, headers=headers
                )
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise ModelTransientError(
                "Model provider could not be reached.", error_type=type(error).__name__
            ) from error
        if response.status_code in (401, 403):
            raise ModelAuthenticationError("Model authentication failed.")
        if response.status_code == 429 or response.status_code >= 500:
            raise ModelTransientError(
                "Model provider is temporarily unavailable.",
                error_type=f"http_{response.status_code}",
            )
        if response.is_error:
            raise ModelPermanentError(
                "Model provider rejected the request.", error_type=f"http_{response.status_code}"
            )
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            return output_schema.model_validate(json.loads(content))
        except json.JSONDecodeError as error:
            raise ModelOutputValidationError("Model returned invalid JSON output.") from error
        except (KeyError, IndexError, TypeError) as error:
            raise ModelOutputValidationError(
                "Model returned incomplete structured output."
            ) from error


def _safe_error(error: Exception) -> str:
    if isinstance(error, ValidationError):
        issues = error.errors(include_input=False)
        summary = "; ".join(
            f"{'.'.join(str(part) for part in issue['loc'])}: {issue['type']}" for issue in issues
        )
        return f"Structured output validation failed: {summary}"[:500]
    if isinstance(error, ModelAuthenticationError):
        return "Model authentication failed."
    if isinstance(error, ModelTransientError):
        return f"Model request failed ({error.error_type})."
    if isinstance(error, ModelPermanentError):
        return f"Model request failed ({error.error_type})."
    if isinstance(error, ModelOutputValidationError):
        return "Model returned invalid structured output."
    return type(error).__name__
