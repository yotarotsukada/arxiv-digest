from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_secrets
from app.utils.logger import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """起動時に構造化ログを設定し、必須環境変数を検証して落とせるものは落とす。

    `/healthz` を「ZOMBIE な OK」にしないため、`API_AUTH_SECRET` などの欠落は
    プロセス起動段階で `ValidationError` として表面化させる。
    """
    configure_logging()
    get_secrets()
    yield


app = FastAPI(title="arXiv Digest Service", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
