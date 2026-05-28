import json
import logging
import sys

from app.utils.logger import JsonFormatter


def test_json_formatter_emits_required_fields():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="x.py",
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    payload = json.loads(formatter.format(record))
    assert payload["message"] == "hello world"
    assert payload["severity"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert "time" in payload


def test_json_formatter_includes_extra_fields():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname="x.py", lineno=1,
        msg="event", args=(), exc_info=None,
    )
    record.event = "custom"
    record.cost_usd = 0.12
    payload = json.loads(formatter.format(record))
    assert payload["event"] == "custom"
    assert payload["cost_usd"] == 0.12


def test_json_formatter_includes_exception():
    formatter = JsonFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            name="t", level=logging.ERROR, pathname="x.py", lineno=1,
            msg="failed", args=(), exc_info=sys.exc_info(),
        )
    payload = json.loads(formatter.format(record))
    assert "exception" in payload
    assert "ValueError" in payload["exception"]
    assert "boom" in payload["exception"]
