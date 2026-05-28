from unittest.mock import MagicMock

import pytest

from app.providers.notification.line import (
    MAX_MESSAGES_PER_REQUEST,
    MAX_TEXT_LENGTH,
    LineNotifier,
    _batched,
    _split_for_line,
)
from app.utils.exceptions import LineAPIError


def _fake_response(*, status: int = 200, body: str = "{}"):
    res = MagicMock()
    res.status_code = status
    res.text = body
    return res


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)


def test_send_text_calls_push_endpoint():
    http = MagicMock()
    http.post.return_value = _fake_response()
    notifier = LineNotifier(channel_access_token="t", user_id="U1", http_client=http)

    notifier.send_text("hello LINE")

    assert http.post.call_count == 1
    call = http.post.call_args
    assert call.args[0] == "https://api.line.me/v2/bot/message/push"
    assert call.kwargs["json"] == {
        "to": "U1",
        "messages": [{"type": "text", "text": "hello LINE"}],
    }
    assert call.kwargs["headers"]["Authorization"] == "Bearer t"


def test_send_text_splits_oversized_message_on_newline():
    http = MagicMock()
    http.post.return_value = _fake_response()
    notifier = LineNotifier(channel_access_token="t", user_id="U1", http_client=http)

    paragraph = "x" * 4000
    text = paragraph + "\n" + paragraph + "\n" + paragraph  # 約 12000 文字
    notifier.send_text(text)

    # 1 リクエストで全 3 chunk を送れる (5 通/req まで)
    assert http.post.call_count == 1
    messages = http.post.call_args.kwargs["json"]["messages"]
    assert len(messages) == 3
    for m in messages:
        assert len(m["text"]) <= MAX_TEXT_LENGTH


def test_send_text_chunks_into_multiple_requests_when_over_5_messages():
    http = MagicMock()
    http.post.return_value = _fake_response()
    notifier = LineNotifier(channel_access_token="t", user_id="U1", http_client=http)

    text = "\n".join(["x" * 4500 for _ in range(7)])
    notifier.send_text(text)

    # 7 chunk → 5 + 2 で 2 リクエストに分かれる
    assert http.post.call_count == 2
    first = http.post.call_args_list[0].kwargs["json"]["messages"]
    second = http.post.call_args_list[1].kwargs["json"]["messages"]
    assert len(first) == MAX_MESSAGES_PER_REQUEST
    assert len(second) == 2


def test_send_text_empty_no_request():
    http = MagicMock()
    notifier = LineNotifier(channel_access_token="t", user_id="U1", http_client=http)
    notifier.send_text("")
    assert http.post.call_count == 0


def test_4xx_raises_line_api_error_without_retry():
    http = MagicMock()
    http.post.return_value = _fake_response(status=400, body="bad request")
    notifier = LineNotifier(channel_access_token="t", user_id="U1", http_client=http)

    with pytest.raises(LineAPIError):
        notifier.send_text("hi")

    assert http.post.call_count == 1


def test_5xx_retries_then_succeeds():
    http = MagicMock()
    http.post.side_effect = [_fake_response(status=500), _fake_response()]
    notifier = LineNotifier(channel_access_token="t", user_id="U1", http_client=http)

    notifier.send_text("hi")

    assert http.post.call_count == 2


def test_split_for_line_no_newline_falls_back_to_hard_cut():
    text = "x" * (MAX_TEXT_LENGTH + 100)
    chunks = _split_for_line(text, MAX_TEXT_LENGTH)
    assert len(chunks) == 2
    assert all(len(c) <= MAX_TEXT_LENGTH for c in chunks)
    assert "".join(chunks) == text


def test_batched_groups_items():
    assert _batched(["a", "b", "c", "d", "e", "f", "g"], 3) == [
        ["a", "b", "c"],
        ["d", "e", "f"],
        ["g"],
    ]
