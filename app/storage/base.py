"""ストレージ抽象 (Firestore とメモリ実装を交換可能にする)。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from app.storage.models import DigestRecord, Paper


class Storage(ABC):
    @abstractmethod
    def is_already_sent(self, arxiv_id: str) -> bool: ...

    @abstractmethod
    def mark_as_sent(self, papers: list[Paper], digest_id: str) -> None: ...

    @abstractmethod
    def save_digest(self, digest: DigestRecord) -> None: ...

    @abstractmethod
    def get_digest(self, digest_id: str) -> DigestRecord | None: ...

    @abstractmethod
    def list_digests(self, limit: int = 10) -> list[DigestRecord]: ...

    @abstractmethod
    def get_cost_today(self, today: date | None = None) -> float: ...

    @abstractmethod
    def add_cost(self, cost_usd: float, today: date | None = None) -> float:
        """加算後の当日累計を返す。"""
