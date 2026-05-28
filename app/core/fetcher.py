"""arXiv API クライアント。

`arxiv` パッケージ (公式) でクエリし、指定時間幅の投稿に絞って Paper にして返す。
3 秒インターバルは `arxiv.Client(delay_seconds=3)` が担保する。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import arxiv

from app.storage.models import Paper
from app.utils.exceptions import ArxivAPIError, ArxivAPITransientError
from app.utils.logger import get_logger
from app.utils.retry import retry_with_backoff

_logger = get_logger(__name__)


class _ClientProtocol(Protocol):
    def results(self, search: arxiv.Search) -> Iterable[Any]: ...


class ArxivFetcher:
    """指定カテゴリの最新投稿論文を取得する。"""

    def __init__(
        self,
        *,
        page_size: int = 100,
        delay_seconds: float = 3.0,
        client: _ClientProtocol | None = None,
    ) -> None:
        self._client = client or arxiv.Client(
            page_size=page_size,
            delay_seconds=delay_seconds,
            num_retries=0,  # リトライは @retry_with_backoff 側で行う
        )

    @retry_with_backoff(
        max_attempts=3,
        base_delay=2.0,
        exceptions=(ArxivAPITransientError,),
    )
    def fetch_recent(
        self,
        categories: list[str],
        hours: int = 36,
        *,
        now: datetime | None = None,
        max_results: int = 1000,
    ) -> list[Paper]:
        """`now - hours` 以降に投稿された論文を返す。

        並び順は arXiv の SubmittedDate 降順 (新しいほうが先頭)。
        """
        if not categories:
            return []
        now = now or datetime.now(timezone.utc)
        since = now - timedelta(hours=hours)

        query = " OR ".join(f"cat:{c}" for c in categories)
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )

        try:
            results = list(self._client.results(search))
        except Exception as exc:  # arxiv lib は様々な例外を投げる
            raise ArxivAPITransientError(f"arXiv API 呼び出しに失敗: {exc}") from exc

        papers: list[Paper] = []
        for r in results:
            published = self._to_utc(r.published)
            if published < since:
                # SubmittedDate 降順なので、ここで打ち切ってよい
                break
            try:
                papers.append(self._to_paper(r))
            except Exception as exc:
                _logger.warning(
                    "arxiv_result_parse_failed",
                    extra={"error": str(exc), "arxiv_id": getattr(r, "entry_id", None)},
                )

        _logger.info(
            "arxiv_fetched",
            extra={"count": len(papers), "categories": categories, "hours": hours},
        )
        return papers

    @staticmethod
    def _to_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _to_paper(r: Any) -> Paper:
        return Paper(
            arxiv_id=r.get_short_id(),
            title=r.title.strip(),
            abstract=r.summary.strip(),
            authors=[a.name for a in r.authors],
            categories=list(r.categories),
            published_at=ArxivFetcher._to_utc(r.published),
            pdf_url=r.pdf_url,
        )
