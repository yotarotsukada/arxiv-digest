import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import reset_cache
from app.main import app


_REQUIRED_ENV = [
    "API_AUTH_SECRET",
    "LINE_CHANNEL_ACCESS_TOKEN",
    "LINE_USER_ID",
]


@pytest.fixture(autouse=True)
def _required_env(monkeypatch):
    for var in _REQUIRED_ENV:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("API_AUTH_SECRET", "test-secret")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("LINE_USER_ID", "U1")
    reset_cache()
    yield
    reset_cache()


def test_healthz_returns_ok():
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_app_lifespan_fails_when_required_env_missing(monkeypatch):
    monkeypatch.delenv("API_AUTH_SECRET", raising=False)
    reset_cache()
    with pytest.raises(ValidationError):
        with TestClient(app):
            pass
