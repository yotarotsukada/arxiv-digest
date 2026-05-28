"""ドメインモデル。

- `Paper`: パイプライン内で取り回す論文の表現
- `DigestPaper`: 配信履歴用に確定したスコア・要約を含む論文
- `DigestRecord`: 1 回の配信記録 (digest_history コレクション)
- `CostRecord`: 日次コスト記録 (cost_tracker コレクション)
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Paper(BaseModel):
    """パイプライン内部の論文表現 (score/summary は段階的に埋まる)。"""

    model_config = ConfigDict(extra="ignore")

    arxiv_id: str
    title: str
    abstract: str
    authors: list[str]
    categories: list[str]
    published_at: datetime
    pdf_url: str
    score: float | None = None
    summary_ja: str | None = None


class DigestPaper(BaseModel):
    """配信記録の中の確定済み論文情報。"""

    arxiv_id: str
    title: str
    authors: list[str]
    categories: list[str]
    score: float
    summary_ja: str
    url: str


class DigestRecord(BaseModel):
    """1 回の配信実行記録。"""

    digest_id: str
    executed_at: datetime
    trigger: str  # "scheduled" | "manual" | "dry_run"
    papers: list[DigestPaper]
    llm_provider: str
    llm_model: str
    total_cost_usd: float
    duration_sec: float
    status: str  # "success" | "failed" | "partial"
    error: str | None = None


class CostRecord(BaseModel):
    """日次コスト記録。`date` は ISO 形式 YYYY-MM-DD。"""

    date: str
    total_cost_usd: float
    request_count: int
    updated_at: datetime
