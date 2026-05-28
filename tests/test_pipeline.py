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
from app.providers.notification.base import Notifier
from app.storage.memory import InMemoryStorage
from app.storage.models import Paper
from app.utils.exceptions import CostLimitExceededError, LineAPIError


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


class _RecordingNotifier(Notifier):
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_text(self, message: str) -> None:
        self.messages.append(message)


class _FailingNotifier(Notifier):
    def send_text(self, message: str) -> None:
        raise LineAPIError("LINE API 400")


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
    notifier: Notifier | None = None,
) -> tuple[Pipeline, InMemoryStorage]:
    storage = storage or InMemoryStorage()
    fetcher = MagicMock()
    fetcher.fetch_recent.return_value = papers
    prefilter = PreFilter(settings.prefilter, storage)
    pipeline = Pipeline(settings, fetcher, prefilter, llm, storage, notifier=notifier)
    return pipeline, storage


def test_pipeline_selects_top_n_and_summarizes():
    settings = _settings(top_n=3)
    papers = [_paper(f"id{i}") for i in range(10)]
    llm = _FakeLLM(scores={f"id{i}": float(i) for i in range(10)})
    pipeline, _ = _make_pipeline(settings=settings, papers=papers, llm=llm)

    record = pipeline.run(trigger="dry_run")

    assert record.status == "success"
    assert [p.arxiv_id for p in record.papers] == ["id9", "id8", "id7"]
    assert all(p.summary_ja for p in record.papers)
    assert record.trigger == "dry_run"


def test_pipeline_blocks_on_cost_limit():
    settings = _settings(daily_limit=0.0001)
    llm = _FakeLLM(estimate=0.01)
    pipeline, _ = _make_pipeline(settings=settings, papers=[_paper("a")], llm=llm)

    with pytest.raises(CostLimitExceededError):
        pipeline.run()


def test_pipeline_force_bypasses_cost_limit():
    settings = _settings(daily_limit=0.0001)
    llm = _FakeLLM(estimate=0.01)
    pipeline, _ = _make_pipeline(settings=settings, papers=[_paper("a")], llm=llm)

    record = pipeline.run(force=True)
    assert record.status == "success"


def test_pipeline_handles_empty_fetch():
    settings = _settings()
    pipeline, storage = _make_pipeline(settings=settings, papers=[], llm=_FakeLLM())

    record = pipeline.run()

    assert record.status == "success"
    assert record.papers == []
    # 空でも履歴は残す (実行があったこと自体は保存する)
    assert storage.get_digest(record.digest_id) is not None


def test_pipeline_skips_already_sent_papers():
    settings = _settings(top_n=2)
    storage = InMemoryStorage()
    p_sent = _paper("seen")
    storage.mark_as_sent([p_sent], "previous")
    papers = [p_sent, _paper("new1"), _paper("new2")]
    llm = _FakeLLM(scores={"new1": 9.0, "new2": 5.0})
    pipeline, _ = _make_pipeline(
        settings=settings, papers=papers, llm=llm, storage=storage,
    )

    record = pipeline.run()
    assert [p.arxiv_id for p in record.papers] == ["new1", "new2"]


def test_pipeline_records_cost_per_run_not_cumulative():
    """P0-2 回帰: 同じ Pipeline / LLM を 2 回 run() しても、当日累計は
    各 run の実コストの合計になる (LLM の累積コストを 2 重計上しない)。
    """
    settings = _settings(top_n=2)
    llm = _FakeLLM(cost_per_call=0.005)
    storage = InMemoryStorage()
    fetcher = MagicMock()
    # 2 run で別々の論文を返すことで、dedupe が発火しても候補ゼロにならない
    fetcher.fetch_recent.side_effect = [
        [_paper("a"), _paper("b")],
        [_paper("c"), _paper("d")],
    ]
    pipeline = Pipeline(
        settings,
        fetcher,
        PreFilter(settings.prefilter, storage),
        llm,
        storage,
    )

    record1 = pipeline.run()
    record2 = pipeline.run()

    # 1 run = score 1 回 + summarize 2 回 = 0.015
    assert record1.total_cost_usd == pytest.approx(0.015)
    assert record2.total_cost_usd == pytest.approx(0.015)
    today = datetime.now(timezone.utc).date()
    assert storage.get_cost_today(today) == pytest.approx(0.030)


def test_pipeline_persists_digest_and_marks_sent():
    """P0-1 回帰: manual 実行で save_digest と mark_as_sent が呼ばれる。"""
    settings = _settings(top_n=2)
    storage = InMemoryStorage()
    llm = _FakeLLM(scores={"a": 9.0, "b": 7.0})
    pipeline, _ = _make_pipeline(
        settings=settings,
        papers=[_paper("a"), _paper("b")],
        llm=llm,
        storage=storage,
    )

    record = pipeline.run(trigger="manual")

    assert storage.get_digest(record.digest_id) is not None
    assert storage.is_already_sent("a") is True
    assert storage.is_already_sent("b") is True


def test_dry_run_does_not_mark_as_sent():
    """dry_run では `mark_as_sent` を呼ばず、再実行できるようにする。"""
    settings = _settings(top_n=2)
    storage = InMemoryStorage()
    pipeline, _ = _make_pipeline(
        settings=settings,
        papers=[_paper("a"), _paper("b")],
        llm=_FakeLLM(),
        storage=storage,
    )

    record = pipeline.run(trigger="dry_run")

    # 履歴 (= digest_history) は残す
    assert storage.get_digest(record.digest_id) is not None
    # 再送防止 (= sent_papers) は登録しない
    assert storage.is_already_sent("a") is False


def test_pipeline_invokes_notifier_on_manual_run():
    settings = _settings(top_n=2)
    notifier = _RecordingNotifier()
    pipeline, _ = _make_pipeline(
        settings=settings,
        papers=[_paper("a"), _paper("b")],
        llm=_FakeLLM(),
        notifier=notifier,
    )

    pipeline.run(trigger="manual")

    assert len(notifier.messages) == 1
    assert "Paper a" in notifier.messages[0]


def test_pipeline_skips_notifier_on_dry_run():
    settings = _settings(top_n=2)
    notifier = _RecordingNotifier()
    pipeline, _ = _make_pipeline(
        settings=settings,
        papers=[_paper("a")],
        llm=_FakeLLM(),
        notifier=notifier,
    )

    pipeline.run(trigger="dry_run")

    assert notifier.messages == []


def test_pipeline_records_partial_on_line_failure():
    settings = _settings(top_n=2)
    storage = InMemoryStorage()
    pipeline, _ = _make_pipeline(
        settings=settings,
        papers=[_paper("a")],
        llm=_FakeLLM(),
        storage=storage,
        notifier=_FailingNotifier(),
    )

    record = pipeline.run(trigger="manual")

    assert record.status == "partial"
    assert record.error is not None and "LINE" in record.error
    # partial でも履歴と再送防止は登録する (重複送信を避けるため)
    assert storage.get_digest(record.digest_id) is not None
    assert storage.is_already_sent("a") is True
