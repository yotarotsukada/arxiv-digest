from datetime import datetime, timezone

import pytest

from app.config import AuthorBoost, KeywordBoost, PrefilterConfig
from app.core.filter import PreFilter
from app.storage.memory import InMemoryStorage
from app.storage.models import Paper


def _paper(arxiv_id: str, *, title: str = "t", abstract: str = "a",
           authors: tuple[str, ...] = ("X",), categories: tuple[str, ...] = ("cs.AI",)) -> Paper:
    return Paper(
        arxiv_id=arxiv_id,
        title=title,
        abstract=abstract,
        authors=list(authors),
        categories=list(categories),
        published_at=datetime.now(timezone.utc),
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
    )


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


def test_keyword_boost_promotes_matching_paper(storage):
    config = PrefilterConfig(
        max_papers=10,
        keywords_boost=[KeywordBoost(pattern="large language model|LLM", weight=3.0)],
    )
    pf = PreFilter(config, storage)
    matched = _paper("a", title="A Survey of Large Language Models")
    unmatched = _paper("b", title="Image Segmentation")
    out = pf.apply([unmatched, matched])
    assert [p.arxiv_id for p in out] == ["a", "b"]


def test_keyword_boost_case_insensitive(storage):
    config = PrefilterConfig(
        max_papers=10,
        keywords_boost=[KeywordBoost(pattern="RAG", weight=5.0)],
    )
    pf = PreFilter(config, storage)
    matched = _paper("a", title="Retrieval Augmented", abstract="rag system works well")
    unmatched = _paper("b")
    out = pf.apply([unmatched, matched])
    assert out[0].arxiv_id == "a"


def test_author_boost_promotes_target_author(storage):
    config = PrefilterConfig(
        max_papers=10,
        authors_boost=[AuthorBoost(name="Yann LeCun", weight=5.0)],
    )
    pf = PreFilter(config, storage)
    p_alice = _paper("a", authors=("Alice",))
    p_lecun = _paper("b", authors=("Yann LeCun",))
    out = pf.apply([p_alice, p_lecun])
    assert out[0].arxiv_id == "b"


def test_excludes_already_sent_papers(storage):
    config = PrefilterConfig(max_papers=10)
    sent = _paper("a")
    storage.mark_as_sent([sent], "previous_digest")
    pf = PreFilter(config, storage)
    out = pf.apply([sent, _paper("b")])
    assert [p.arxiv_id for p in out] == ["b"]


def test_truncates_to_max_papers(storage):
    config = PrefilterConfig(max_papers=200)
    pf = PreFilter(config, storage)
    papers = [_paper(f"id-{i}") for i in range(500)]
    out = pf.apply(papers)
    assert len(out) == 200


def test_no_keyword_or_author_config_keeps_baseline(storage):
    config = PrefilterConfig(max_papers=10)
    pf = PreFilter(config, storage)
    out = pf.apply([_paper("a"), _paper("b")])
    assert {p.arxiv_id for p in out} == {"a", "b"}
