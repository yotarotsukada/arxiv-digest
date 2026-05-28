from datetime import date, datetime, timezone

import pytest

from app.storage.memory import InMemoryStorage
from app.storage.models import DigestPaper, DigestRecord, Paper


def _paper(arxiv_id: str = "2401.0001") -> Paper:
    return Paper(
        arxiv_id=arxiv_id,
        title="Test",
        abstract="Abstract",
        authors=["A"],
        categories=["cs.AI"],
        published_at=datetime.now(timezone.utc),
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
    )


def _digest(digest_id: str, executed_at: datetime) -> DigestRecord:
    return DigestRecord(
        digest_id=digest_id,
        executed_at=executed_at,
        trigger="scheduled",
        papers=[
            DigestPaper(
                arxiv_id="x",
                title="t",
                authors=["a"],
                categories=["cs.AI"],
                score=8.5,
                summary_ja="...",
                url="https://arxiv.org/abs/x",
            )
        ],
        llm_provider="groq",
        llm_model="llama-3.3-70b-versatile",
        total_cost_usd=0.012,
        duration_sec=10.5,
        status="success",
    )


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


def test_is_already_sent_returns_false_initially(storage):
    assert storage.is_already_sent("2401.0001") is False


def test_mark_as_sent_and_dedup(storage):
    p = _paper()
    storage.mark_as_sent([p], "digest_x")
    assert storage.is_already_sent(p.arxiv_id) is True


def test_save_and_get_digest(storage):
    digest = _digest("d1", datetime(2026, 5, 28, tzinfo=timezone.utc))
    storage.save_digest(digest)
    got = storage.get_digest("d1")
    assert got is not None
    assert got.digest_id == "d1"
    assert got.papers[0].arxiv_id == "x"


def test_get_digest_missing_returns_none(storage):
    assert storage.get_digest("nope") is None


def test_list_digests_most_recent_first(storage):
    for i, day in enumerate([26, 27, 28]):
        storage.save_digest(_digest(f"d{i}", datetime(2026, 5, day, tzinfo=timezone.utc)))
    items = storage.list_digests(limit=10)
    assert [d.digest_id for d in items] == ["d2", "d1", "d0"]


def test_cost_tracking_accumulates(storage):
    today = date(2026, 5, 28)
    assert storage.get_cost_today(today) == 0.0
    storage.add_cost(0.01, today)
    storage.add_cost(0.05, today)
    assert storage.get_cost_today(today) == pytest.approx(0.06)


def test_cost_tracking_is_per_date(storage):
    storage.add_cost(0.10, date(2026, 5, 28))
    storage.add_cost(0.20, date(2026, 5, 29))
    assert storage.get_cost_today(date(2026, 5, 28)) == pytest.approx(0.10)
    assert storage.get_cost_today(date(2026, 5, 29)) == pytest.approx(0.20)
