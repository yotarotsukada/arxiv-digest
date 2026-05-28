import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.providers.llm.groq import GroqProvider
from app.providers.llm.pricing import ModelPricing, PricingTable
from app.storage.models import Paper
from app.utils.exceptions import LLMAPIError


def _paper(arxiv_id: str) -> Paper:
    return Paper(
        arxiv_id=arxiv_id,
        title=f"Paper {arxiv_id}",
        abstract="An interesting paper about large language models and agents.",
        authors=["A"],
        categories=["cs.AI"],
        published_at=datetime.now(timezone.utc),
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
    )


def _fake_response(
    content: str,
    *,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    status: int = 200,
):
    res = MagicMock()
    res.status_code = status
    res.json.return_value = {
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    }
    res.text = content
    return res


@pytest.fixture
def pricing() -> PricingTable:
    return PricingTable(
        providers={
            "groq": {
                "llama-3.3-70b-versatile": ModelPricing(
                    input_per_million_usd=0.59,
                    output_per_million_usd=0.79,
                )
            }
        }
    )


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)


def test_score_parses_batch_json(pricing):
    http = MagicMock()
    http.post.return_value = _fake_response(
        json.dumps(
            {
                "scores": [
                    {"arxiv_id": "a", "score": 8.5},
                    {"arxiv_id": "b", "score": 4.0},
                ]
            }
        )
    )
    provider = GroqProvider(api_key="x", pricing=pricing, http_client=http)

    scores = provider.score([_paper("a"), _paper("b")])

    assert scores == [8.5, 4.0]
    usage = provider.get_usage()
    assert usage.by_task["score"].requests == 1
    assert usage.total_cost_usd > 0


def test_score_preserves_input_order_with_missing_items(pricing):
    http = MagicMock()
    http.post.return_value = _fake_response(
        json.dumps({"scores": [{"arxiv_id": "b", "score": 7.0}]})
    )
    provider = GroqProvider(api_key="x", pricing=pricing, http_client=http)
    scores = provider.score([_paper("a"), _paper("b")])
    assert scores == [0.0, 7.0]  # a は欠落して 0 埋め


def test_score_batches_papers(pricing):
    http = MagicMock()
    http.post.side_effect = [
        _fake_response(json.dumps({"scores": [{"arxiv_id": f"id{i}", "score": 5.0}]}))
        for i in range(3)
    ]
    provider = GroqProvider(api_key="x", pricing=pricing, http_client=http, score_batch_size=1)
    papers = [_paper(f"id{i}") for i in range(3)]
    scores = provider.score(papers)
    assert scores == [5.0, 5.0, 5.0]
    assert http.post.call_count == 3


def test_summarize_returns_text(pricing):
    http = MagicMock()
    http.post.return_value = _fake_response(
        "【何の研究か】xxx\n【提案手法】yyy\n【結果・インパクト】zz\n【なぜ読む価値があるか】w"
    )
    provider = GroqProvider(api_key="x", pricing=pricing, http_client=http)
    summary = provider.summarize(_paper("a"))
    assert "【何の研究か】" in summary
    assert "【なぜ読む価値があるか】" in summary


def test_5xx_retries_then_succeeds(pricing):
    http = MagicMock()
    http.post.side_effect = [
        _fake_response("server error", status=500),
        _fake_response(json.dumps({"scores": [{"arxiv_id": "a", "score": 7.0}]})),
    ]
    provider = GroqProvider(api_key="x", pricing=pricing, http_client=http)
    scores = provider.score([_paper("a")])
    assert scores == [7.0]
    assert http.post.call_count == 2


def test_4xx_raises_llmapierror_without_extensive_retry(pricing):
    http = MagicMock()
    http.post.return_value = _fake_response("bad request", status=400)
    provider = GroqProvider(api_key="x", pricing=pricing, http_client=http)
    with pytest.raises(LLMAPIError):
        provider.summarize(_paper("a"))
    # 4xx は再試行対象外なので 1 回しか呼ばれない
    assert http.post.call_count == 1


def test_estimate_cost_positive_when_pricing_known(pricing):
    provider = GroqProvider(
        api_key="x", pricing=pricing, http_client=MagicMock()
    )
    cost_score = provider.estimate_cost([_paper("a"), _paper("b")], "score")
    cost_sum = provider.estimate_cost([_paper("a"), _paper("b")], "summarize")
    assert cost_score > 0
    assert cost_sum > 0
    # 要約のほうが (出力トークンが多いので) 高い
    assert cost_sum > cost_score


def test_estimate_cost_zero_when_pricing_missing():
    provider = GroqProvider(
        api_key="x",
        model="unknown-model",
        pricing=PricingTable(),
        http_client=MagicMock(),
    )
    assert provider.estimate_cost([_paper("a")], "score") == 0.0


def test_score_invalid_json_raises(pricing):
    http = MagicMock()
    http.post.return_value = _fake_response("not json")
    provider = GroqProvider(api_key="x", pricing=pricing, http_client=http)
    with pytest.raises(LLMAPIError):
        provider.score([_paper("a")])
