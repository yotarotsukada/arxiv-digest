"""LLM プロバイダ抽象基底。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.storage.models import Paper


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0


@dataclass
class Usage:
    """プロバイダインスタンスごとの累積使用量。"""

    by_task: dict[str, TokenUsage] = field(default_factory=dict)
    total_cost_usd: float = 0.0


class LLMProvider(ABC):
    """全プロバイダの共通インタフェース。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """`groq` `openai` `anthropic` `together` などの識別子。"""

    @property
    @abstractmethod
    def model(self) -> str:
        """モデル ID (記録・課金参照に使う)。"""

    @abstractmethod
    def score(self, papers: list[Paper]) -> list[float]:
        """各論文の重要度を 0-10 で返す。入力と同じ並び順・同じ件数。"""

    @abstractmethod
    def summarize(self, paper: Paper) -> str:
        """論文 1 本の日本語要約を返す。"""

    @abstractmethod
    def estimate_cost(self, papers: list[Paper], task: str) -> float:
        """事前コスト見積もり (USD)。task は `score` か `summarize`。"""

    @abstractmethod
    def get_usage(self) -> Usage:
        """累積使用量とコストを返す。"""
