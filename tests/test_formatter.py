from datetime import datetime, timezone

import pytest

from app.core.formatter import format_digest_message
from app.providers.notification.line import MAX_MESSAGES_PER_REQUEST, MAX_TEXT_LENGTH
from app.storage.models import DigestPaper, DigestRecord


def _digest_paper(
    arxiv_id: str,
    *,
    title: str = "Sample paper",
    authors: list[str] | None = None,
    categories: list[str] | None = None,
    score: float = 8.0,
    summary_ja: str = "【何の研究か】テスト用要約。",
) -> DigestPaper:
    return DigestPaper(
        arxiv_id=arxiv_id,
        title=title,
        authors=authors or ["Alice"],
        categories=categories or ["cs.AI"],
        score=score,
        summary_ja=summary_ja,
        url=f"https://arxiv.org/abs/{arxiv_id}",
    )


def _digest_record(papers: list[DigestPaper]) -> DigestRecord:
    return DigestRecord(
        digest_id="d1",
        executed_at=datetime(2026, 5, 28, 6, 30, tzinfo=timezone.utc),
        trigger="scheduled",
        papers=papers,
        llm_provider="groq",
        llm_model="llama-3.3-70b-versatile",
        total_cost_usd=0.012,
        duration_sec=10.0,
        status="success",
    )


def test_format_includes_all_papers():
    record = _digest_record(
        [
            _digest_paper("2405.001", title="Paper A"),
            _digest_paper("2405.002", title="Paper B"),
            _digest_paper("2405.003", title="Paper C"),
        ]
    )
    msg = format_digest_message(record)
    assert "Paper A" in msg
    assert "Paper B" in msg
    assert "Paper C" in msg
    assert "https://arxiv.org/abs/2405.001" in msg


def test_format_empty_papers_returns_no_papers_message():
    record = _digest_record([])
    msg = format_digest_message(record)
    assert "本日は配信対象の論文がありませんでした" in msg


def test_format_authors_truncated_with_count_note():
    record = _digest_record(
        [_digest_paper("a", authors=["A1", "A2", "A3", "A4", "A5"])]
    )
    msg = format_digest_message(record)
    assert "A1, A2, A3" in msg
    assert "ほか 2 名" in msg
    assert "A4" not in msg


def test_format_5_long_papers_within_line_budget():
    """5 本のサンプルから整形済みメッセージが LINE 配信制限内に収まる。"""
    long_summary = "【何の研究か】" + ("テスト" * 80) + "\n【提案手法】" + ("内容" * 80)
    record = _digest_record(
        [
            _digest_paper(
                f"2405.{i:03d}",
                title=f"Long title {i} " + ("x" * 100),
                summary_ja=long_summary,
                authors=[f"Author{j}" for j in range(8)],
            )
            for i in range(5)
        ]
    )
    msg = format_digest_message(record)

    # 1 メッセージ × 5 通の上限
    assert len(msg) <= MAX_TEXT_LENGTH * MAX_MESSAGES_PER_REQUEST


def test_format_includes_date():
    record = _digest_record([_digest_paper("a")])
    msg = format_digest_message(record)
    # 整形日付の表示は astimezone 結果に依存するが 2026 と 05 の桁は含まれる
    assert "2026-05-2" in msg
