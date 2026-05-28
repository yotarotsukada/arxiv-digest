"""パイプラインオーケストレーション (設計書 §5 のフロー [1]-[7])。

LINE 通知 [8] と Firestore 永続化 [9] は T11 で統合する。
T08 完了時点では CLI から `python -m app.core.pipeline --dry-run` で
論文取得 → 粗フィルタ → スコアリング → 要約までを一気通貫で動かせる。
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from datetime import datetime, timezone

from app.config import AppSettings, get_app_settings, get_secrets
from app.core.fetcher import ArxivFetcher
from app.core.filter import PreFilter
from app.providers.llm.base import LLMProvider
from app.providers.llm.groq import GroqProvider
from app.storage.base import Storage
from app.storage.factory import create_storage
from app.storage.models import DigestPaper, DigestRecord, Paper
from app.utils.exceptions import CostLimitExceededError
from app.utils.logger import configure_logging, get_logger

_logger = get_logger(__name__)


class Pipeline:
    """論文取得 → 粗フィルタ → コスト確認 → スコア → 上位 N 選出 → 要約。"""

    def __init__(
        self,
        settings: AppSettings,
        fetcher: ArxivFetcher,
        prefilter: PreFilter,
        llm: LLMProvider,
        storage: Storage,
    ) -> None:
        self._settings = settings
        self._fetcher = fetcher
        self._prefilter = prefilter
        self._llm = llm
        self._storage = storage

    def run(
        self,
        *,
        trigger: str = "manual",
        top_n: int | None = None,
        force: bool = False,
        now: datetime | None = None,
    ) -> DigestRecord:
        start = time.monotonic()
        now = now or datetime.now(timezone.utc)
        digest_id = f"digest_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        target_top_n = top_n or self._settings.digest.top_n

        _logger.info("pipeline_start", extra={"digest_id": digest_id, "trigger": trigger})

        # [1] FETCH
        fetched = self._fetcher.fetch_recent(
            categories=self._settings.arxiv.categories,
            hours=self._settings.arxiv.fetch_window_hours,
            now=now,
        )

        # [2][3] DEDUPE + PREFILTER
        filtered = self._prefilter.apply(fetched)
        if not filtered:
            _logger.info("pipeline_no_candidates", extra={"digest_id": digest_id})
            return self._build_record(digest_id, trigger, [], start, now, "success")

        # [4] COST CHECK
        self._enforce_cost_limit(filtered, target_top_n, now, force)

        # [5] SCORE
        scores = self._llm.score(filtered)
        for paper, score in zip(filtered, scores, strict=True):
            paper.score = score

        # [6] SELECT
        selected = sorted(filtered, key=lambda p: p.score or 0.0, reverse=True)[:target_top_n]

        # [7] SUMMARIZE
        for paper in selected:
            paper.summary_ja = self._llm.summarize(paper)

        # コスト集計
        usage = self._llm.get_usage()
        self._storage.add_cost(usage.total_cost_usd, now.date())

        _logger.info(
            "pipeline_complete",
            extra={
                "digest_id": digest_id,
                "selected_count": len(selected),
                "cost_usd": round(usage.total_cost_usd, 6),
            },
        )
        return self._build_record(digest_id, trigger, selected, start, now, "success")

    # ----- internal -----

    def _enforce_cost_limit(
        self,
        filtered: list[Paper],
        top_n: int,
        now: datetime,
        force: bool,
    ) -> None:
        if force:
            return
        estimated = self._llm.estimate_cost(filtered, "score") + self._llm.estimate_cost(
            filtered[:top_n], "summarize"
        )
        current = self._storage.get_cost_today(now.date())
        limit = self._settings.cost.daily_limit_usd
        if current + estimated > limit:
            raise CostLimitExceededError(
                f"日次コスト上限 ${limit:.2f} を超過予測 "
                f"(現在 ${current:.4f} + 推定 ${estimated:.4f})。"
                f"force=True で上書き可能"
            )

    def _build_record(
        self,
        digest_id: str,
        trigger: str,
        papers: list[Paper],
        start: float,
        executed_at: datetime,
        status: str,
    ) -> DigestRecord:
        digest_papers = [
            DigestPaper(
                arxiv_id=p.arxiv_id,
                title=p.title,
                authors=p.authors,
                categories=p.categories,
                score=p.score or 0.0,
                summary_ja=p.summary_ja or "",
                url=f"https://arxiv.org/abs/{p.arxiv_id}",
            )
            for p in papers
        ]
        usage = self._llm.get_usage()
        return DigestRecord(
            digest_id=digest_id,
            executed_at=executed_at,
            trigger=trigger,
            papers=digest_papers,
            llm_provider=self._llm.name,
            llm_model=self._llm.model,
            total_cost_usd=usage.total_cost_usd,
            duration_sec=time.monotonic() - start,
            status=status,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_default_pipeline(
    settings: AppSettings | None = None,
    storage: Storage | None = None,
) -> Pipeline:
    settings = settings or get_app_settings()
    storage = storage or create_storage()
    fetcher = ArxivFetcher()
    prefilter = PreFilter(settings.prefilter, storage)
    llm = GroqProvider(model=settings.llm.default_model)
    return Pipeline(settings, fetcher, prefilter, llm, storage)


def _print_digest(record: DigestRecord) -> None:
    print(f"\n=== Digest {record.digest_id} ({record.status}) ===", file=sys.stdout)
    print(
        f"papers: {len(record.papers)}  "
        f"cost_usd: ${record.total_cost_usd:.4f}  "
        f"duration: {record.duration_sec:.1f}s",
        file=sys.stdout,
    )
    for i, p in enumerate(record.papers, 1):
        print(f"\n[{i}] score={p.score:.1f}  {p.title}")
        print(f"    {p.url}")
        if p.summary_ja:
            for line in p.summary_ja.splitlines():
                print(f"    {line}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="arXiv Digest Pipeline (T08)")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="LINE 送信せず結果プレビューのみ (T08 時点では常に dry_run 相当)",
    )
    parser.add_argument("--top-n", type=int, default=None, help="上位 N 件 (デフォルトは settings.yaml)")
    parser.add_argument("--force", action="store_true", help="コスト上限チェックをバイパス")
    args = parser.parse_args(argv)

    configure_logging()
    # 起動時に必須環境変数を検証 (T02)
    get_secrets()

    pipeline = build_default_pipeline()
    trigger = "dry_run" if args.dry_run else "manual"
    record = pipeline.run(trigger=trigger, top_n=args.top_n, force=args.force)
    _print_digest(record)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
