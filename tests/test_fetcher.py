from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.core.fetcher import ArxivFetcher
from app.utils.exceptions import ArxivAPIError


class _FakeAuthor:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeResult:
    def __init__(
        self,
        arxiv_id: str,
        title: str,
        summary: str,
        authors: list[str],
        categories: list[str],
        published: datetime,
        pdf_url: str | None = None,
    ) -> None:
        self._arxiv_id = arxiv_id
        self.title = title
        self.summary = summary
        self.authors = [_FakeAuthor(a) for a in authors]
        self.categories = categories
        self.published = published
        self.pdf_url = pdf_url or f"https://arxiv.org/pdf/{arxiv_id}"
        self.entry_id = f"http://arxiv.org/abs/{arxiv_id}"

    def get_short_id(self) -> str:
        return self._arxiv_id


def test_fetch_recent_returns_papers_in_window():
    now = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)
    recent = _FakeResult(
        "2405.12345", "Recent paper", "An abstract", ["Alice", "Bob"], ["cs.AI"],
        now - timedelta(hours=10),
    )
    old = _FakeResult(
        "2405.10000", "Old paper", "abs", ["X"], ["cs.LG"],
        now - timedelta(hours=72),
    )
    client = MagicMock()
    client.results.return_value = [recent, old]

    fetcher = ArxivFetcher(client=client)
    papers = fetcher.fetch_recent(categories=["cs.AI", "cs.LG"], hours=36, now=now)

    assert len(papers) == 1
    p = papers[0]
    assert p.arxiv_id == "2405.12345"
    assert p.title == "Recent paper"
    assert p.authors == ["Alice", "Bob"]
    assert p.categories == ["cs.AI"]
    assert p.pdf_url == "https://arxiv.org/pdf/2405.12345"


def test_fetch_recent_returns_empty_when_categories_empty():
    fetcher = ArxivFetcher(client=MagicMock())
    assert fetcher.fetch_recent(categories=[], hours=36) == []


def test_fetch_recent_retries_then_raises_arxiv_api_error(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    client = MagicMock()
    client.results.side_effect = RuntimeError("network down")
    fetcher = ArxivFetcher(client=client)

    with pytest.raises(ArxivAPIError):
        fetcher.fetch_recent(categories=["cs.AI"], hours=36)
    # 3 回試行されているはず
    assert client.results.call_count == 3


def test_fetch_recent_handles_naive_datetime():
    now = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)
    # tzinfo なしの published
    naive_recent = _FakeResult(
        "2405.99999", "T", "abs", ["A"], ["cs.AI"],
        datetime(2026, 5, 28, 5, 0),  # naive
    )
    client = MagicMock()
    client.results.return_value = [naive_recent]
    fetcher = ArxivFetcher(client=client)
    papers = fetcher.fetch_recent(categories=["cs.AI"], hours=36, now=now)
    assert len(papers) == 1
    assert papers[0].published_at.tzinfo is not None
