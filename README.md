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

## パイプラインの CLI 実行

M1 (T08) 時点では LINE 送信は未統合。`--dry-run` でコンソールに上位 N 件の要約を表示する。

```bash
# 事前準備: GROQ API キーを .env に設定 (LLM_API_KEY_GROQ)
python -m app.core.pipeline --dry-run --top-n 5
```

- 既定ストレージは `InMemoryStorage` (プロセス再起動で消える)。`GOOGLE_CLOUD_PROJECT` または `FIRESTORE_EMULATOR_HOST` を設定すると `FirestoreStorage` に切り替わる (`pip install '.[firestore]'` が必要)。
- `--force` で日次コスト上限 (settings.yaml の `cost.daily_limit_usd`) をバイパス可能。

## ディレクトリ構成

`docs/design.md` §2.1 を参照。M0-M1 で `app/config.py` / `app/core/{fetcher,filter,pipeline}.py` / `app/providers/llm/{base,groq,prompts,pricing}.py` / `app/storage/{base,memory,firestore,factory,models}.py` / `app/utils/{logger,retry,exceptions}.py` を実装済み。残りは `app/api/`, `app/core/notifier.py`, `app/providers/notification/line.py` 等を以降のタスクで埋めていく。

## ライセンス

未定。
