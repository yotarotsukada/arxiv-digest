from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.config import (
    AppSettings,
    ArxivConfig,
    CostConfig,
    DigestConfig,
    LLMConfig,
    LineConfig,
    PrefilterConfig,
)
from app.core.filter import PreFilter
from app.core.pipeline import Pipeline
from app.providers.llm.base import LLMProvider, TokenUsage, Usage
from app.storage.memory import InMemoryStorage
from app.storage.models import Paper
from app.utils.exceptions import CostLimitExceededError


class _FakeLLM(LLMProvider):
    def __init__(
        self,
        *,
        scores: dict[str, float] | None = None,
        summaries: dict[str, str] | None = None,
        estimate: float = 0.001,
        cost_per_call: float = 0.0,
    ) -> None:
        self._scores = scores or {}
        self._summaries = summaries or {}
        self._estimate = estimate
        self._cost_per_call = cost_per_call
        self._usage = Usage()

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    def score(self, papers):
        self._usage.by_task.setdefault("score", TokenUsage()).requests += 1
        self._usage.total_cost_usd += self._cost_per_call
        return [self._scores.get(p.arxiv_id, 5.0) for p in papers]

    def summarize(self, paper):
        self._usage.by_task.setdefault("summarize", TokenUsage()).requests += 1
        self._usage.total_cost_usd += self._cost_per_call
        return self._summaries.get(paper.arxiv_id, f"要約: {paper.arxiv_id}")

    def estimate_cost(self, papers, task):
        return self._estimate

    def get_usage(self) -> Usage:
        return self._usage


def _paper(arxiv_id: str) -> Paper:
    return Paper(
        arxiv_id=arxiv_id,
        title=f"Paper {arxiv_id}",
        abstract="An abstract.",
        authors=["A"],
        categories=["cs.AI"],
        published_at=datetime.now(timezone.utc),
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
    )


def _settings(daily_limit: float = 1.0, top_n: int = 3) -> AppSettings:
    return AppSettings(
        arxiv=ArxivConfig(categories=["cs.AI"], fetch_window_hours=36),
        prefilter=PrefilterConfig(max_papers=20),
        digest=DigestConfig(top_n=top_n),
        llm=LLMConfig(default_provider="fake", default_model="fake-model"),
        cost=CostConfig(daily_limit_usd=daily_limit),
        line=LineConfig(),
    )


def _make_pipeline(
    *,
    settings: AppSettings,
    papers: list[Paper],
    llm: LLMProvider,
    storage: InMemoryStorage | None = None,
) -> tuple[Pipeline, InMemoryStorage]:
    storage = storage or InMemoryStorage()
    fetcher = MagicMock()
    fetcher.fetch_recent.return_value = papers
    prefilter = PreFilter(settings.prefilter, storage)
    pipeline = Pipeline(settings, fetcher, prefilter, llm, storage)
    return pipeline, storage


def test_pipeline_selects_top_n_and_summarizes():
    settings = _settings(top_n=3)
    papers = [_paper(f"id{i}") for i in range(10)]
    llm = _FakeLLM(scores={f"id{i}": float(i) for i in range(10)})
    pipeline, _ = _make_pipeline(settings=settings, papers=papers, llm=llm)

    record = pipeline.run(trigger="dry_run")

    assert record.status == "success"
    assert len(record.papers) == 3
    assert [p.arxiv_id for p in record.papers] == ["id9", "id8", "id7"]
    assert all(p.summary_ja for p in record.papers)
    assert record.llm_provider == "fake"
    assert record.trigger == "dry_run"


def test_pipeline_blocks_on_cost_limit():
    settings = _settings(daily_limit=0.0001)
    papers = [_paper("a")]
    llm = _FakeLLM(estimate=0.01)
    pipeline, _ = _make_pipeline(settings=settings, papers=papers, llm=llm)

    with pytest.raises(CostLimitExceededError):
        pipeline.run()


def test_pipeline_force_bypasses_cost_limit():
    settings = _settings(daily_limit=0.0001)
    papers = [_paper("a")]
    llm = _FakeLLM(estimate=0.01)
    pipeline, _ = _make_pipeline(settings=settings, papers=papers, llm=llm)

    record = pipeline.run(force=True)
    assert record.status == "success"


def test_pipeline_handles_empty_fetch():
    settings = _settings()
    llm = _FakeLLM()
    pipeline, _ = _make_pipeline(settings=settings, papers=[], llm=llm)

    record = pipeline.run()
    assert record.status == "success"
    assert record.papers == []


def test_pipeline_skips_already_sent_papers():
    settings = _settings(top_n=2)
    storage = InMemoryStorage()
    p_sent = _paper("seen")
    storage.mark_as_sent([p_sent], "previous")
    papers = [p_sent, _paper("new1"), _paper("new2")]
    llm = _FakeLLM(scores={"new1": 9.0, "new2": 5.0})
    pipeline, _ = _make_pipeline(
        settings=settings, papers=papers, llm=llm, storage=storage
    )

    record = pipeline.run()
    assert [p.arxiv_id for p in record.papers] == ["new1", "new2"]


def test_pipeline_records_cost():
    settings = _settings()
    papers = [_paper("a"), _paper("b")]
    llm = _FakeLLM(cost_per_call=0.005)
    pipeline, storage = _make_pipeline(settings=settings, papers=papers, llm=llm)

    record = pipeline.run()
    # score 1 回 + summarize 2 回 (top_n=3 だが候補 2 件しかないので 2 件要約) = 0.015
    assert record.total_cost_usd == pytest.approx(0.015)
    today = datetime.now(timezone.utc).date()
    assert storage.get_cost_today(today) == pytest.approx(0.015)
