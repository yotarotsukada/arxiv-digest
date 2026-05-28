"""LINE 配信用メッセージフォーマッタ (Phase 1: プレーンテキスト)。

`DigestRecord` だけを入力に取り、LINE 等の API 固有構造は持たない。
Phase 2 で Flex Message 化する際は本モジュールはそのまま、別の整形関数を
追加して `Notifier` 側のインタフェースを拡張する想定。
"""

from __future__ import annotations

from app.storage.models import DigestRecord


def format_digest_message(record: DigestRecord) -> str:
    """配信レコードを LINE 向けプレーンテキストに整形する。"""
    date_str = record.executed_at.astimezone().strftime("%Y-%m-%d")

    if not record.papers:
        return (
            f"[arXiv Digest {date_str}]\n"
            "本日は配信対象の論文がありませんでした。"
        )

    lines: list[str] = [f"[arXiv Digest {date_str}] {len(record.papers)} 本", ""]
    for i, p in enumerate(record.papers, 1):
        lines.append("-" * 28)
        lines.append(
            f"({i}) score {p.score:.1f}  {', '.join(p.categories)}"
        )
        lines.append(p.title)
        if p.authors:
            shown = p.authors[:3]
            author_line = ", ".join(shown)
            if len(p.authors) > 3:
                author_line += f" ほか {len(p.authors) - 3} 名"
            lines.append(author_line)
        lines.append("")
        lines.append(p.summary_ja)
        lines.append("")
        lines.append(p.url)
        lines.append("")
    return "\n".join(lines).rstrip()
