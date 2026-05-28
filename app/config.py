"""設定読み込み層。

- `AppSettings`: `config/settings.yaml` 由来の非機密設定 (デフォルト値あり)
- `Secrets`: 環境変数由来のシークレット (一部は起動時に必須)

CLI / FastAPI 起動時に `get_secrets()` を呼ぶことで必須環境変数の欠落を
ValidationError として即座に検出する。
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# settings.yaml 由来の設定 (Phase 1 では起動を妨げないようすべてデフォルト値付き)
# ---------------------------------------------------------------------------


class ArxivConfig(BaseModel):
    categories: list[str] = Field(
        default_factory=lambda: ["cs.AI", "cs.LG", "cs.CL", "cs.CV", "cs.NE", "stat.ML"]
    )
    fetch_window_hours: int = 36


class KeywordBoost(BaseModel):
    pattern: str
    weight: float


class AuthorBoost(BaseModel):
    name: str
    weight: float


class PrefilterConfig(BaseModel):
    max_papers: int = 200
    keywords_boost: list[KeywordBoost] = Field(default_factory=list)
    authors_boost: list[AuthorBoost] = Field(default_factory=list)


class DigestConfig(BaseModel):
    top_n: int = 5
    schedule_jst: str = "06:30"


class LLMConfig(BaseModel):
    default_provider: str = "groq"
    default_model: str = "llama-3.3-70b-versatile"


class CostConfig(BaseModel):
    daily_limit_usd: float = 1.0
    alert_threshold_ratio: float = 0.8


class LineConfig(BaseModel):
    message_format: str = "text"


class AppSettings(BaseModel):
    arxiv: ArxivConfig = Field(default_factory=ArxivConfig)
    prefilter: PrefilterConfig = Field(default_factory=PrefilterConfig)
    digest: DigestConfig = Field(default_factory=DigestConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    cost: CostConfig = Field(default_factory=CostConfig)
    line: LineConfig = Field(default_factory=LineConfig)


DEFAULT_SETTINGS_PATH = Path("config/settings.yaml")


def load_app_settings(path: Path | str = DEFAULT_SETTINGS_PATH) -> AppSettings:
    """YAML を読み込んで `AppSettings` を返す。ファイルが無ければデフォルト値。"""
    path = Path(path)
    data: dict[str, Any] = {}
    if path.exists():
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    return AppSettings.model_validate(data)


# ---------------------------------------------------------------------------
# 環境変数由来のシークレット
# ---------------------------------------------------------------------------


class Secrets(BaseSettings):
    """必須環境変数を起動時に検証する。

    必須:
        - `API_AUTH_SECRET`
        - `LINE_CHANNEL_ACCESS_TOKEN`
        - `LINE_USER_ID`

    任意 (使用時に `get_llm_api_key()` で検証):
        - `LLM_API_KEY_GROQ` / `_TOGETHER` / `_OPENAI` / `_ANTHROPIC`
        - `GOOGLE_CLOUD_PROJECT`
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    api_auth_secret: SecretStr
    line_channel_access_token: SecretStr
    line_user_id: str

    llm_api_key_groq: SecretStr | None = None
    llm_api_key_together: SecretStr | None = None
    llm_api_key_openai: SecretStr | None = None
    llm_api_key_anthropic: SecretStr | None = None

    google_cloud_project: str | None = None

    def get_llm_api_key(self, provider: str) -> SecretStr:
        attr = f"llm_api_key_{provider.lower()}"
        key = getattr(self, attr, None)
        if key is None:
            raise ValueError(
                f"LLM プロバイダ '{provider}' の API キーが未設定です "
                f"(環境変数 {attr.upper()} を設定してください)"
            )
        return key


# ---------------------------------------------------------------------------
# キャッシュ付きアクセサ
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def get_secrets() -> Secrets:
    return Secrets()  # type: ignore[call-arg]


@functools.lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    return load_app_settings()


def reset_cache() -> None:
    """テスト用にモジュールキャッシュをクリアする。"""
    get_secrets.cache_clear()
    get_app_settings.cache_clear()
