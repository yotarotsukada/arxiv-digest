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

   `API_AUTH_SECRET` / `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_USER_ID` は起動時に必須 (欠落で FastAPI 起動が `ValidationError`)。LLM の API キーは使用する provider のみ (例: `LLM_API_KEY_GROQ`) で良い。

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

## パイプラインの CLI 実行

```bash
# プレビューのみ (LINE 送信なし)
python -m app.core.pipeline --dry-run --top-n 5

# 本実行 (LINE 送信あり)
python -m app.core.pipeline --top-n 5
```

- 既定ストレージは `InMemoryStorage` (プロセス再起動で消える)。`GOOGLE_CLOUD_PROJECT` または `FIRESTORE_EMULATOR_HOST` を設定すると `FirestoreStorage` に切り替わる。
- `--dry-run` は LINE 送信 / 再送防止 (`mark_as_sent`) をスキップする。`digest_history` への保存は実行する。
- `--force` で日次コスト上限 (`settings.yaml` の `cost.daily_limit_usd`) をバイパスする。

## ディレクトリ構成

`docs/design.md` §2.1 を参照。M0-M2 で `app/main.py` (lifespan で必須環境変数検証) / `app/config.py` / `app/core/{fetcher,filter,formatter,pipeline}.py` / `app/providers/llm/{base,groq,prompts,pricing}.py` / `app/providers/notification/{base,line}.py` / `app/storage/{base,memory,firestore,factory,models}.py` / `app/utils/{logger,retry,exceptions}.py` を実装済み。残りは `app/api/{routes,auth}.py` を M3 で埋めていく。

## ライセンス

未定。
