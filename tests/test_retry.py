import pytest

from app.utils.retry import retry_with_backoff


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)


def test_returns_value_on_first_success():
    calls: list[int] = []

    @retry_with_backoff(max_attempts=3, base_delay=0.01, jitter=False)
    def fn() -> str:
        calls.append(1)
        return "ok"

    assert fn() == "ok"
    assert len(calls) == 1


def test_retries_until_success():
    calls: list[int] = []

    @retry_with_backoff(max_attempts=3, base_delay=0.01, jitter=False)
    def fn() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("transient")
        return "ok"

    assert fn() == "ok"
    assert len(calls) == 3


def test_raises_after_max_attempts():
    calls: list[int] = []

    @retry_with_backoff(max_attempts=2, base_delay=0.01, jitter=False)
    def fn() -> None:
        calls.append(1)
        raise ValueError("always")

    with pytest.raises(ValueError):
        fn()
    assert len(calls) == 2


def test_non_matching_exception_not_retried():
    calls: list[int] = []

    @retry_with_backoff(
        max_attempts=3, base_delay=0.01, jitter=False, exceptions=(ValueError,)
    )
    def fn() -> None:
        calls.append(1)
        raise RuntimeError("not retried")

    with pytest.raises(RuntimeError):
        fn()
    assert len(calls) == 1


def test_delay_follows_exponential_backoff(monkeypatch):
    delays: list[float] = []
    monkeypatch.setattr("time.sleep", lambda d: delays.append(d))

    @retry_with_backoff(max_attempts=4, base_delay=1.0, jitter=False)
    def fn() -> None:
        raise ValueError("x")

    with pytest.raises(ValueError):
        fn()

    # 3 回 sleep する (試行 1,2,3 の失敗後)。1, 2, 4 秒
    assert delays == [1.0, 2.0, 4.0]
