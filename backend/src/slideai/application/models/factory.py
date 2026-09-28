from collections.abc import Awaitable, Callable
from typing import Any

from slideai.application.models.demo_provider import DeterministicDemoProvider
from slideai.application.models.gateway import (
    ModelGateway,
    OpenAICompatibleProvider,
    StructuredProvider,
)
from slideai.core.config import Settings
from slideai.domain.models.catalog import ModelCatalog

AuditWriter = Callable[[dict[str, Any]], Awaitable[None]]


def create_model_runtime(
    settings: Settings, audit_writer: AuditWriter | None = None
) -> tuple[ModelCatalog, ModelGateway]:
    if settings.generation_provider == "fake":
        catalog = ModelCatalog.for_fake_provider()
        providers: dict[str, StructuredProvider] = {"fake": DeterministicDemoProvider()}
    else:
        catalog = ModelCatalog.from_yaml(settings.model_catalog_path)
        providers = {"openai_compatible": OpenAICompatibleProvider()}
    gateway = ModelGateway(
        model_catalog=catalog,
        providers=providers,
        audit_writer=audit_writer,
        retries=settings.model_retry_count,
    )
    return catalog, gateway
