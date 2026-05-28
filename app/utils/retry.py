"""指数バックオフリトライ。

`@retry_with_backoff(exceptions=(SomeTransientError,))` で対象例外型を限定する。
"""

from __future__ import annotations

import functools
import logging
import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Any])

_logger = logging.getLogger(__name__)


def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: bool = True,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[F], F]:
    """指数バックオフでリトライするデコレータ。

    Args:
        max_attempts: 試行回数の上限 (初回呼び出しを含む)
        base_delay: 初回リトライ時の待機秒数。以降 2^n で伸びる
        max_delay: 待機秒数の上限
        jitter: True なら待機時間に [0.5, 1.0) のランダム係数を掛ける
        exceptions: リトライ対象の例外型
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0
            while True:
                attempt += 1
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    if attempt >= max_attempts:
                        raise
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    if jitter:
                        delay = delay * (0.5 + random.random() * 0.5)
                    _logger.warning(
                        "retry",
                        extra={
                            "function": func.__name__,
                            "attempt": attempt,
                            "max_attempts": max_attempts,
                            "delay_sec": round(delay, 3),
                            "error": f"{type(exc).__name__}: {exc}",
                        },
                    )
                    time.sleep(delay)

        return wrapper  # type: ignore[return-value]

    return decorator
