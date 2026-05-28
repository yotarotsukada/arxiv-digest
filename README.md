# arxiv-digest

arXiv に毎日投稿される AI 分野の論文から興味度の高い 5 本を自動選出し、日本語要約を LINE に配信するサービス。

詳細は `docs/` 配下を参照:

- `docs/requirements.md` — 要件定義
- `docs/design.md` — 設計
- `docs/tasks.md` — タスク分割

## 必要環境

- Docker / Docker Compose
- (ローカルで直接動かす場合) Python 3.12

## セットアップ

1. リポジトリを clone する。
2. `.env.example` を `.env` にコピーして必要な値を埋める。

   ```bash
   cp .env.example .env
   ```

   Phase 1 段階では `API_AUTH_SECRET` だけ適当な文字列を入れておけば `/healthz` の動作確認はできる。LLM / LINE のキーは該当タスク (T07・T09) で必要になる。

## 開発サーバ起動

```bash
docker compose up --build
```

- `app/` と `config/` がボリュームマウントされており、`--reload` でホットリロードする。
- 起動後に動作確認:

  ```bash
  curl http://localhost:8080/healthz
  # => {"status":"ok"}
  ```

OpenAPI ドキュメントは `http://localhost:8080/docs` で確認できる (FastAPI 標準)。

## ローカル実行 (Docker を使わない場合)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8080
```

## テスト

```bash
pip install -e ".[dev]"
pytest
```

## ディレクトリ構成

`docs/design.md` §2.1 を参照。Phase 1 の段階では空のパッケージのみ用意してあり、各タスクで肉付けしていく。

## ライセンス

未定。
