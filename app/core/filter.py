"""LLM 前段のルールベース絞り込み (粗フィルタ)。

1. `Storage.is_already_sent` と突合し、過去配信済みを除外
2. キーワード正規表現と著者名でスコア加点 (baseline 1.0)
3. スコア降順で `max_papers` 件に切り詰め
"""

from __future__ import annotations

import re
from typing import Pattern

from app.config import PrefilterConfig
from app.storage.base import Storage
from app.storage.models import Paper
from app.utils.logger import get_logger

_logger = get_logger(__name__)


class PreFilter:
    def __init__(self, config: PrefilterConfig, storage: Storage) -> None:
        self._config = config
        self._storage = storage
        self._keyword_patterns: list[tuple[Pattern[str], float]] = [
            (re.compile(kb.pattern, re.IGNORECASE), kb.weight)
            for kb in config.keywords_boost
        ]
        self._author_weights: dict[str, float] = {
            ab.name: ab.weight for ab in config.authors_boost
        }

    def apply(self, papers: list[Paper]) -> list[Paper]:
        scored: list[tuple[float, Paper]] = []
        skipped_dedupe = 0
        for p in papers:
            if self._storage.is_already_sent(p.arxiv_id):
                skipped_dedupe += 1
                continue
            scored.append((self._score(p), p))

        scored.sort(key=lambda x: x[0], reverse=True)
        result = [p for _, p in scored[: self._config.max_papers]]

        _logger.info(
            "prefilter_applied",
            extra={
                "input_count": len(papers),
                "skipped_dedupe": skipped_dedupe,
                "output_count": len(result),
                "max_papers": self._config.max_papers,
            },
        )
        return result

    def _score(self, paper: Paper) -> float:
        score = 1.0
        text = f"{paper.title}\n{paper.abstract}"
        for pattern, weight in self._keyword_patterns:
            if pattern.search(text):
                score += weight
        for author in paper.authors:
            if author in self._author_weights:
                score += self._author_weights[author]
        return score
