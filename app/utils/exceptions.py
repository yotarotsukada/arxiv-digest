"""アプリケーション全体で使う例外階層。

- `ArxivDigestError` がベース
- `*TransientError` は再試行可能 (リトライ対象) を意味する
"""


class ArxivDigestError(Exception):
    """全例外の基底クラス。"""


class ConfigError(ArxivDigestError):
    """設定読み込み・解釈エラー。"""


# --- arXiv API ---------------------------------------------------------------


class ArxivAPIError(ArxivDigestError):
    """arXiv API エラー (永続)。"""


class ArxivAPITransientError(ArxivAPIError):
    """arXiv API の一時障害 (再試行可能)。"""


# --- LLM ---------------------------------------------------------------------


class LLMAPIError(ArxivDigestError):
    """LLM API エラー (永続)。"""


class LLMAPITransientError(LLMAPIError):
    """LLM API の一時障害 (再試行可能)。"""


# --- LINE --------------------------------------------------------------------


class LineAPIError(ArxivDigestError):
    """LINE Messaging API エラー (永続)。"""


class LineAPITransientError(LineAPIError):
    """LINE API の一時障害 (再試行可能)。"""


# --- Storage -----------------------------------------------------------------


class FirestoreError(ArxivDigestError):
    """Firestore エラー。"""


# --- Cost --------------------------------------------------------------------


class CostLimitExceededError(ArxivDigestError):
    """日次コスト上限の超過。"""
