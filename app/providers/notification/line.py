"""LINE Messaging API (Push) クライアント。

- エンドポイント: `POST https://api.line.me/v2/bot/message/push`
- 1 メッセージあたり 5000 文字、1 リクエストで最大 5 メッセージ
- 5xx / 429 は `LineAPITransientError` でリトライ対象
- それ以外の 4xx は `LineAPIError` で即時失敗 (要件 §9: 1 回リトライ→partial)

LINE Developer Console 設定:
    1. プロバイダーを作成 → Messaging API チャネル追加
    2. チャネルアクセストークン (長期) を発行し `LINE_CHANNEL_ACCESS_TOKEN` に
    3. Bot を友だち追加した自分の `userId` を `LINE_USER_ID` に
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_secrets
from app.providers.notification.base import Notifier
from app.utils.exceptions import LineAPIError, LineAPITransientError
from app.utils.logger import get_logger
from app.utils.retry import retry_with_backoff

_logger = get_logger(__name__)


LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
MAX_TEXT_LENGTH = 5000
MAX_MESSAGES_PER_REQUEST = 5


class LineNotifier(Notifier):
    def __init__(
        self,
        *,
        channel_access_token: str | None = None,
        user_id: str | None = None,
        http_client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        if channel_access_token is None or user_id is None:
            secrets = get_secrets()
            channel_access_token = (
                channel_access_token
                or secrets.line_channel_access_token.get_secret_value()
            )
            user_id = user_id or secrets.line_user_id
        self._token = channel_access_token
        self._user_id = user_id
        self._http = http_client or httpx.Client(timeout=timeout)

    def send_text(self, message: str) -> None:
        if not message:
            return
        chunks = _split_for_line(message, MAX_TEXT_LENGTH)
        for batch in _batched(chunks, MAX_MESSAGES_PER_REQUEST):
            self._push([{"type": "text", "text": c} for c in batch])

    @retry_with_backoff(
        max_attempts=2,
        base_delay=2.0,
        exceptions=(LineAPITransientError,),
    )
    def _push(self, messages: list[dict[str, Any]]) -> None:
        try:
            res = self._http.post(
                LINE_PUSH_URL,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                json={"to": self._user_id, "messages": messages},
            )
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
            raise LineAPITransientError(f"LINE API 通信障害: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LineAPIError(f"LINE API HTTP エラー: {exc}") from exc

        if res.status_code == 429 or res.status_code >= 500:
            raise LineAPITransientError(
                f"LINE API 一時エラー ({res.status_code}): {res.text[:200]}"
            )
        if res.status_code >= 400:
            raise LineAPIError(
                f"LINE API エラー ({res.status_code}): {res.text[:200]}"
            )

        _logger.info("line_push_sent", extra={"message_count": len(messages)})


def _split_for_line(text: str, max_len: int) -> list[str]:
    """LINE の 1 メッセージ制限 (max_len) に収まるよう、可能なら改行境界で分割する。"""
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        cutoff = remaining.rfind("\n", 0, max_len)
        if cutoff <= 0:
            cutoff = max_len
        chunks.append(remaining[:cutoff].rstrip())
        remaining = remaining[cutoff:].lstrip("\n")
    return [c for c in chunks if c]


def _batched(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]
