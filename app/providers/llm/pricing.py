"""LLM 単価表 (config/llm_pricing.yaml) の読み込み。"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class ModelPricing(BaseModel):
    input_per_million_usd: float
    output_per_million_usd: float


class PricingTable(BaseModel):
    providers: dict[str, dict[str, ModelPricing]] = {}

    def get(self, provider: str, model: str) -> ModelPricing:
        models = self.providers.get(provider)
        if not models or model not in models:
            raise KeyError(f"pricing not found: {provider}/{model}")
        return models[model]


DEFAULT_PRICING_PATH = Path("config/llm_pricing.yaml")


def load_pricing(path: Path | str = DEFAULT_PRICING_PATH) -> PricingTable:
    path = Path(path)
    if not path.exists():
        return PricingTable()
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    providers: dict[str, dict[str, ModelPricing]] = {}
    for provider, models in raw.items():
        providers[provider] = {
            name: ModelPricing(**pricing) for name, pricing in (models or {}).items()
        }
    return PricingTable(providers=providers)
