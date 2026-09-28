import os
import re
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field

from slideai.domain.tasks.complexity import ComplexityTier

_ENV_PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")
_TIER_ORDER = {ComplexityTier.FAST: 0, ComplexityTier.BALANCED: 1, ComplexityTier.ADVANCED: 2}


class ModelDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    display_name: str
    provider: str
    model_id: str
    base_url: str
    api_key_env: str
    tier: ComplexityTier
    enabled: bool = True
    timeout_seconds: float = Field(default=60, gt=0)
    fallbacks: list[str] = Field(default_factory=list)

    @property
    def available(self) -> bool:
        if self.provider == "fake":
            return self.enabled
        return bool(
            self.enabled and self.model_id and self.base_url and os.getenv(self.api_key_env)
        )


class NodePolicy(BaseModel):
    minimum_tier: ComplexityTier = ComplexityTier.FAST


class PublicModel(BaseModel):
    key: str
    display_name: str
    tier: ComplexityTier
    enabled: bool
    available: bool


class ModelCatalog(BaseModel):
    models: dict[str, ModelDefinition]
    node_policies: dict[str, NodePolicy] = Field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: Path) -> "ModelCatalog":
        content = cast(dict[str, Any], yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        raw_models = cast(dict[str, dict[str, Any]], content.get("models", {}))

        def expand(value: str) -> str:
            return _ENV_PLACEHOLDER.sub(lambda match: os.getenv(match.group(1), ""), value)

        models: dict[str, ModelDefinition] = {}
        for key, raw in raw_models.items():
            expanded = {
                field: expand(value) if isinstance(value, str) else value
                for field, value in raw.items()
            }
            models[key] = ModelDefinition.model_validate({"key": key, **expanded})
        node_policies = cast(dict[str, NodePolicy], content.get("node_policies", {}))
        return cls(models=models, node_policies=node_policies)

    def public_models(self) -> list[PublicModel]:
        return [
            PublicModel(
                key=model.key,
                display_name=model.display_name,
                tier=model.tier,
                enabled=model.enabled,
                available=model.available,
            )
            for model in self.models.values()
        ]

    def for_tier(self, tier: ComplexityTier) -> ModelDefinition:
        eligible = [
            model
            for model in self.models.values()
            if model.enabled and _TIER_ORDER[model.tier] >= _TIER_ORDER[tier]
        ]
        eligible.sort(key=lambda model: (_TIER_ORDER[model.tier], model.key))
        for model in eligible:
            if model.available:
                return model
        raise ValueError(f"No available model for requested tier: {tier.value}")
