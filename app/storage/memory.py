"""インメモリストレージ。

ローカル開発・テスト・dry-run 用。プロセス再起動で消える点に注意。
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.storage.base import Storage
from app.storage.models import DigestRecord, Paper


class InMemoryStorage(Storage):
    def __init__(self) -> None:
        self._sent: dict[str, dict] = {}
        self._digests: dict[str, DigestRecord] = {}
        self._cost: dict[str, dict] = {}

    def is_already_sent(self, arxiv_id: str) -> bool:
        return arxiv_id in self._sent

    def mark_as_sent(self, papers: list[Paper], digest_id: str) -> None:
        now = datetime.now(timezone.utc)
        for p in papers:
            self._sent[p.arxiv_id] = {
                "arxiv_id": p.arxiv_id,
                "sent_at": now,
                "digest_id": digest_id,
            }

    def save_digest(self, digest: DigestRecord) -> None:
        self._digests[digest.digest_id] = digest

    def get_digest(self, digest_id: str) -> DigestRecord | None:
        return self._digests.get(digest_id)

    def list_digests(self, limit: int = 10) -> list[DigestRecord]:
        items = sorted(self._digests.values(), key=lambda d: d.executed_at, reverse=True)
        return items[:limit]

    def get_cost_today(self, today: date | None = None) -> float:
        key = (today or date.today()).isoformat()
        return float(self._cost.get(key, {}).get("total_cost_usd", 0.0))

    def add_cost(self, cost_usd: float, today: date | None = None) -> float:
        key = (today or date.today()).isoformat()
        rec = self._cost.setdefault(key, {"total_cost_usd": 0.0, "request_count": 0})
        rec["total_cost_usd"] = float(rec["total_cost_usd"]) + cost_usd
        rec["request_count"] = int(rec["request_count"]) + 1
        return float(rec["total_cost_usd"])
