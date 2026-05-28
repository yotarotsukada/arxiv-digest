"""Groq (OpenAI 互換 chat completions) プロバイダ。

API ドキュメント: https://console.groq.com/docs/api-reference

- スコアリングはバッチ送信 (1 リクエストに複数論文) でコスト削減
- 要約は 1 論文 1 リクエスト
- 5xx / 429 は `LLMAPITransientError` → リトライ対象
- それ以外の 4xx は `LLMAPIError` → 即時 raise
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import get_secrets
from app.providers.llm.base import LLMProvider, TokenUsage, Usage
from app.providers.llm.pricing import ModelPricing, PricingTable, load_pricing
from app.providers.llm.prompts import (
    SCORE_SYSTEM_PROMPT,
    SCORE_USER_PROMPT_TEMPLATE,
    SUMMARIZE_SYSTEM_PROMPT,
    SUMMARIZE_USER_PROMPT_TEMPLATE,
)
from app.storage.models import Paper
from app.utils.exceptions import LLMAPIError, LLMAPITransientError
from app.utils.logger import get_logger
from app.utils.retry import retry_with_backoff

_logger = get_logger(__name__)


GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# 事前見積もり用の粗いトークン換算 (英語平均で 4 文字 ≒ 1 トークン)
_CHARS_PER_TOKEN = 4
_SCORE_OUTPUT_TOKENS_PER_PAPER = 20
_SUMMARIZE_OUTPUT_TOKENS = 280


class GroqProvider(LLMProvider):
    def __init__(
        self,
        model: str = "llama-3.3-70b-versatile",
        *,
        api_key: str | None = None,
        pricing: PricingTable | None = None,
        http_client: httpx.Client | None = None,
        score_batch_size: int = 20,
        timeout: float = 60.0,
    ) -> None:
        self._model = model
        self._api_key = api_key or get_secrets().get_llm_api_key("groq").get_secret_value()
        table = pricing or load_pricing()
        try:
            self._pricing: ModelPricing | None = table.get("groq", model)
        except KeyError:
            self._pricing = None
            _logger.warning(
                "llm_pricing_missing",
                extra={"provider": "groq", "model": model},
            )
        self._http = http_client or httpx.Client(timeout=timeout)
        self._score_batch_size = score_batch_size
        self._usage = Usage()

    # ----- LLMProvider 実装 -----

    @property
    def name(self) -> str:
        return "groq"

    @property
    def model(self) -> str:
        return self._model

    def score(self, papers: list[Paper]) -> list[float]:
        if not papers:
            return []
        scores: dict[str, float] = {}
        for i in range(0, len(papers), self._score_batch_size):
            batch = papers[i : i + self._score_batch_size]
            scores.update(self._score_batch(batch))
        # 欠落分は 0 として埋める (LLM 出力が一部欠けた場合の安全策)
        return [scores.get(p.arxiv_id, 0.0) for p in papers]

    def summarize(self, paper: Paper) -> str:
        content = self._chat(
            system=SUMMARIZE_SYSTEM_PROMPT,
            user=SUMMARIZE_USER_PROMPT_TEMPLATE.format(
                title=paper.title, abstract=paper.abstract
            ),
            task="summarize",
        )
        return content.strip()

    def estimate_cost(self, papers: list[Paper], task: str) -> float:
        if not self._pricing or not papers:
            return 0.0
        if task == "score":
            input_chars = sum(len(p.title) + len(p.abstract) + 50 for p in papers)
            input_chars += len(SCORE_SYSTEM_PROMPT)
            output_tokens = _SCORE_OUTPUT_TOKENS_PER_PAPER * len(papers)
        elif task == "summarize":
            input_chars = sum(
                len(SUMMARIZE_SYSTEM_PROMPT) + len(p.title) + len(p.abstract) + 30
                for p in papers
            )
            output_tokens = _SUMMARIZE_OUTPUT_TOKENS * len(papers)
        else:
            raise ValueError(f"未対応の task: {task}")
        input_tokens = input_chars // _CHARS_PER_TOKEN
        return self._compute_cost(input_tokens, output_tokens)

    def get_usage(self) -> Usage:
        return self._usage

    # ----- 内部実装 -----

    def _score_batch(self, batch: list[Paper]) -> dict[str, float]:
        papers_text = "\n\n".join(
            f"[{i + 1}] arxiv_id: {p.arxiv_id}\n"
            f"  title: {p.title}\n"
            f"  categories: {', '.join(p.categories)}\n"
            f"  abstract: {p.abstract[:1200]}"
            for i, p in enumerate(batch)
        )
        content = self._chat(
            system=SCORE_SYSTEM_PROMPT,
            user=SCORE_USER_PROMPT_TEMPLATE.format(papers=papers_text),
            task="score",
            response_format={"type": "json_object"},
        )
        return _parse_scores(content)

    @retry_with_backoff(
        max_attempts=3,
        base_delay=2.0,
        exceptions=(LLMAPITransientError,),
    )
    def _chat(
        self,
        system: str,
        user: str,
        task: str,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        if response_format:
            payload["response_format"] = response_format

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            res = self._http.post(GROQ_API_URL, headers=headers, json=payload)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
            raise LLMAPITransientError(f"Groq API 通信障害: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMAPIError(f"Groq API HTTP エラー: {exc}") from exc

        if res.status_code == 429 or res.status_code >= 500:
            raise LLMAPITransientError(
                f"Groq API 一時エラー ({res.status_code}): {res.text[:200]}"
            )
        if res.status_code >= 400:
            raise LLMAPIError(
                f"Groq API エラー ({res.status_code}): {res.text[:200]}"
            )

        try:
            data = res.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMAPIError(f"Groq API 応答パース失敗: {res.text[:200]}") from exc

        self._track_usage(
            task=task,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
        )
        return content

    def _track_usage(self, task: str, input_tokens: int, output_tokens: int) -> None:
        bucket = self._usage.by_task.setdefault(task, TokenUsage())
        bucket.input_tokens += input_tokens
        bucket.output_tokens += output_tokens
        bucket.requests += 1
        self._usage.total_cost_usd += self._compute_cost(input_tokens, output_tokens)

    def _compute_cost(self, input_tokens: int, output_tokens: int) -> float:
        if not self._pricing:
            return 0.0
        return (
            input_tokens / 1_000_000 * self._pricing.input_per_million_usd
            + output_tokens / 1_000_000 * self._pricing.output_per_million_usd
        )


def _parse_scores(content: str) -> dict[str, float]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMAPIError(f"スコアリング JSON のパース失敗: {content[:200]}") from exc
    if isinstance(parsed, dict) and "scores" in parsed:
        items = parsed["scores"]
    elif isinstance(parsed, list):
        items = parsed
    else:
        raise LLMAPIError(f"スコアリング応答の形式不正: {content[:200]}")

    out: dict[str, float] = {}
    for item in items:
        try:
            out[str(item["arxiv_id"])] = float(item["score"])
        except (KeyError, TypeError, ValueError) as exc:
            _logger.warning("score_item_skipped", extra={"item": str(item), "error": str(exc)})
    return out
