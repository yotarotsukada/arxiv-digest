"""パイプラインオーケストレーション (設計書 §5 のフロー [1]-[9])。"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from datetime import datetime, timezone

from app.config import AppSettings, get_app_settings, get_secrets
from app.core.fetcher import ArxivFetcher
from app.core.filter import PreFilter
from app.core.formatter import format_digest_message
from app.providers.llm.base import LLMProvider
from app.providers.llm.groq import GroqProvider
from app.providers.notification.base import Notifier
from app.providers.notification.line import LineNotifier
from app.storage.base import Storage
from app.storage.factory import create_storage
from app.storage.models import DigestPaper, DigestRecord, Paper
from app.utils.exceptions import CostLimitExceededError, LineAPIError
from app.utils.logger import configure_logging, get_logger

_logger = get_logger(__name__)


class Pipeline:
    """論文取得 → 粗フィルタ → コスト確認 → スコア → 上位 N 選出 → 要約 → 通知 → 永続化。

    設計書 §5 のフロー [1]-[9] を担う。`notifier=None` の場合 [8] はスキップ。
    """

    def __init__(
        self,
        settings: AppSettings,
        fetcher: ArxivFetcher,
        prefilter: PreFilter,
        llm: LLMProvider,
        storage: Storage,
        notifier: Notifier | None = None,
    ) -> None:
        self._settings = settings
        self._fetcher = fetcher
        self._prefilter = prefilter
        self._llm = llm
        self._storage = storage
        self._notifier = notifier

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

        # `GroqProvider._usage` はインスタンス累積。run() を使い回すと
        # add_cost が二次関数的に膨張するため、run の開始時点との差分だけを
        # 当 run のコストとして扱う。
        cost_before = self._llm.get_usage().total_cost_usd

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
            record = self._build_record(
                digest_id, trigger, [], start, now, status="success", run_cost=0.0,
            )
            self._persist(record, selected=[], trigger=trigger)
            return record

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

        # 当 run のコスト = 終了時 - 開始時
        run_cost = max(0.0, self._llm.get_usage().total_cost_usd - cost_before)
        self._storage.add_cost(run_cost, now.date())

        # [8] NOTIFY
        status: str = "success"
        error: str | None = None
        if trigger != "dry_run" and self._notifier is not None and selected:
            preview = self._build_record(
                digest_id, trigger, selected, start, now, status=status, run_cost=run_cost,
            )
            try:
                self._notifier.send_text(format_digest_message(preview))
            except LineAPIError as exc:
                # 設計書 §9: LINE 障害は status=partial で digest_history に記録
                status = "partial"
                error = f"LINE 通知失敗: {exc}"
                _logger.error(
                    "notify_failed",
                    extra={"digest_id": digest_id, "error": str(exc)},
                )

        record = self._build_record(
            digest_id, trigger, selected, start, now,
            status=status, run_cost=run_cost, error=error,
        )

        # [9] PERSIST
        self._persist(record, selected=selected, trigger=trigger)

        _logger.info(
            "pipeline_complete",
            extra={
                "digest_id": digest_id,
                "selected_count": len(selected),
                "status": status,
                "cost_usd": round(run_cost, 6),
            },
        )
        return record

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

    def _persist(
        self,
        record: DigestRecord,
        *,
        selected: list[Paper],
        trigger: str,
    ) -> None:
        """設計書 §9 (Firestore 障害はログのみで処理続行)。"""
        try:
            self._storage.save_digest(record)
        except Exception as exc:
            _logger.error(
                "save_digest_failed",
                extra={"digest_id": record.digest_id, "error": str(exc)},
            )
        if trigger == "dry_run" or not selected:
            return
        try:
            self._storage.mark_as_sent(selected, record.digest_id)
        except Exception as exc:
            _logger.error(
                "mark_as_sent_failed",
                extra={"digest_id": record.digest_id, "error": str(exc)},
            )

    def _build_record(
        self,
        digest_id: str,
        trigger: str,
        papers: list[Paper],
        start: float,
        executed_at: datetime,
        *,
        status: str,
        run_cost: float,
        error: str | None = None,
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
        return DigestRecord(
            digest_id=digest_id,
            executed_at=executed_at,
            trigger=trigger,
            papers=digest_papers,
            llm_provider=self._llm.name,
            llm_model=self._llm.model,
            total_cost_usd=run_cost,
            duration_sec=time.monotonic() - start,
            status=status,
            error=error,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_default_pipeline(
    settings: AppSettings | None = None,
    storage: Storage | None = None,
    *,
    with_notifier: bool = True,
) -> Pipeline:
    """既定の Pipeline を組み立てる。`with_notifier=False` で LINE 送信を省略する。"""
    settings = settings or get_app_settings()
    storage = storage or create_storage()
    fetcher = ArxivFetcher()
    prefilter = PreFilter(settings.prefilter, storage)
    llm = GroqProvider(model=settings.llm.default_model)
    notifier: Notifier | None = LineNotifier() if with_notifier else None
    return Pipeline(settings, fetcher, prefilter, llm, storage, notifier=notifier)


def _print_digest(record: DigestRecord) -> None:
    print(f"\n=== Digest {record.digest_id} ({record.status}) ===", file=sys.stdout)
    print(
        f"papers: {len(record.papers)}  "
        f"cost_usd: ${record.total_cost_usd:.4f}  "
        f"duration: {record.duration_sec:.1f}s",
        file=sys.stdout,
    )
    if record.error:
        print(f"error: {record.error}", file=sys.stdout)
    for i, p in enumerate(record.papers, 1):
        print(f"\n[{i}] score={p.score:.1f}  {p.title}")
        print(f"    {p.url}")
        if p.summary_ja:
            for line in p.summary_ja.splitlines():
                print(f"    {line}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="arXiv Digest Pipeline")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="LINE 送信をスキップして結果プレビューのみ表示する",
    )
    parser.add_argument("--top-n", type=int, default=None, help="上位 N 件 (デフォルトは settings.yaml)")
    parser.add_argument("--force", action="store_true", help="コスト上限チェックをバイパス")
    args = parser.parse_args(argv)

    configure_logging()
    # 起動時に必須環境変数を検証 (T02)
    get_secrets()

    pipeline = build_default_pipeline(with_notifier=not args.dry_run)
    trigger = "dry_run" if args.dry_run else "manual"
    record = pipeline.run(trigger=trigger, top_n=args.top_n, force=args.force)
    _print_digest(record)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
