import pytest
from pydantic import ValidationError

from app.config import AppSettings, Secrets, load_app_settings, reset_cache


_REQUIRED_ENV = [
    "API_AUTH_SECRET",
    "LINE_CHANNEL_ACCESS_TOKEN",
    "LINE_USER_ID",
    "LLM_API_KEY_GROQ",
    "LLM_API_KEY_TOGETHER",
    "LLM_API_KEY_OPENAI",
    "LLM_API_KEY_ANTHROPIC",
    "GOOGLE_CLOUD_PROJECT",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in _REQUIRED_ENV:
        monkeypatch.delenv(var, raising=False)
    reset_cache()
    yield
    reset_cache()


def _set_required(monkeypatch):
    monkeypatch.setenv("API_AUTH_SECRET", "shared-secret")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "line-token")
    monkeypatch.setenv("LINE_USER_ID", "U1234")


def test_secrets_missing_required_env_raises(monkeypatch):
    with pytest.raises(ValidationError):
        Secrets(_env_file=None)


def test_secrets_loads_required_envs(monkeypatch):
    _set_required(monkeypatch)
    s = Secrets(_env_file=None)
    assert s.api_auth_secret.get_secret_value() == "shared-secret"
    assert s.line_channel_access_token.get_secret_value() == "line-token"
    assert s.line_user_id == "U1234"


def test_secrets_llm_api_key_missing_raises_value_error(monkeypatch):
    _set_required(monkeypatch)
    s = Secrets(_env_file=None)
    with pytest.raises(ValueError):
        s.get_llm_api_key("groq")


def test_secrets_llm_api_key_present(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("LLM_API_KEY_GROQ", "groq-key")
    s = Secrets(_env_file=None)
    assert s.get_llm_api_key("groq").get_secret_value() == "groq-key"


def test_load_app_settings_uses_defaults_when_file_missing(tmp_path):
    settings = load_app_settings(tmp_path / "no-such-file.yaml")
    assert isinstance(settings, AppSettings)
    assert settings.arxiv.fetch_window_hours == 36
    assert settings.digest.top_n == 5
    assert settings.cost.daily_limit_usd == 1.0
    assert settings.llm.default_provider == "groq"


def test_load_app_settings_overrides(tmp_path):
    yaml_path = tmp_path / "settings.yaml"
    yaml_path.write_text(
        """
arxiv:
  categories: [cs.AI]
  fetch_window_hours: 24
digest:
  top_n: 3
prefilter:
  max_papers: 100
  keywords_boost:
    - {pattern: "RAG", weight: 5}
""",
        encoding="utf-8",
    )
    settings = load_app_settings(yaml_path)
    assert settings.arxiv.categories == ["cs.AI"]
    assert settings.arxiv.fetch_window_hours == 24
    assert settings.digest.top_n == 3
    assert settings.prefilter.max_papers == 100
    assert settings.prefilter.keywords_boost[0].pattern == "RAG"
    assert settings.prefilter.keywords_boost[0].weight == 5.0
