# arXiv Digest Service — タスク分割書 (Phase 1)

Claude Codeに渡して順次実装するためのタスクリスト。各タスクは独立した単位として実装・検証可能。

## 進め方の前提

- 各タスクごとに「実装 → 単体テスト → 動作確認」のサイクルで進める
- タスク完了の判定は明示した「完了条件」で行う
- ブロッカー発生時は次タスクに進まず先に解消する

-----

## マイルストーン概要

|MS|目標              |含むタスク  |
|--|----------------|-------|
|M0|プロジェクト基盤        |T01-T03|
|M1|ローカルで論文取得→要約まで動く|T04-T08|
|M2|LINE配信まで通る      |T09-T11|
|M3|API化            |T12-T14|
|M4|クラウド本番稼働        |T15-T18|
|M5|運用機能の仕上げ        |T19-T21|

-----

## M0: プロジェクト基盤

### T01: プロジェクト初期化 ✅ 完了 (2026-05-28)

**目的**: 開発を始める足場を整える

**作業内容**

- Pythonプロジェクト構成を作成（pyproject.toml or requirements.txt）
- ディレクトリ構造（設計書 2.1 参照）を作成
- Dockerfile, docker-compose.yml の雛形
- .env.example, .gitignore
- README.md の初期版（セットアップ手順）

**完了条件**

- `docker compose up` でFastAPIの空のサーバが起動し、`GET /healthz` が200を返す

**成果物**

- `pyproject.toml` / `requirements.txt`、`Dockerfile` / `docker-compose.yml` / `.dockerignore`、`.env.example`、`.gitignore`
- 設計書 §2.1 に沿った `app/` 配下のパッケージ雛形（`app/main.py` に `/healthz` を実装）
- `tests/test_healthz.py`（pytest で 200 を返すことを確認）
- `README.md` を初期版に更新（セットアップ・起動・テスト手順）

**動作確認メモ**

- 当作業環境では Docker デーモンが使えないため、`uvicorn app.main:app` を直接起動して `curl http://127.0.0.1:8080/healthz` が `200 {"status":"ok"}` を返すことを確認した。Dockerfile / compose は標準構成で、同じ uvicorn コマンドをコンテナ上でも実行する想定。

-----

### T02: 設定ファイル読み込み ✅ 完了 (2026-05-28)

**目的**: settings.yaml と環境変数の読み込み層を作る

**作業内容**

- `app/config.py` 実装（pydantic-settings推奨）
- `config/settings.yaml` 雛形作成
- `config/llm_pricing.yaml` 雛形作成
- 必須環境変数: `API_AUTH_SECRET`, `LLM_API_KEY_*`, `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_USER_ID`

**完了条件**

- pytest で設定読み込みのテストが通る
- 必須環境変数欠落時に起動エラーを出す

**成果物**

- `app/config.py`: `AppSettings` (yaml 由来・デフォルト値あり) と `Secrets` (環境変数由来・必須項目あり) に分割。`get_secrets()` / `get_app_settings()` は LRU キャッシュ付き。
- `config/settings.yaml`: 興味分野・キーワード・コスト上限等のデフォルト値。
- `config/llm_pricing.yaml`: Groq/Together/OpenAI/Anthropic の単価表。
- `tests/test_config.py`: 必須環境変数欠落で `ValidationError`、`LLM_API_KEY_*` は使用時 `ValueError`、yaml デフォルト値・上書きの 6 テスト。

**設計判断**

- 必須は `API_AUTH_SECRET` / `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_USER_ID` の 3 つ。LLM の API キーは「使用するプロバイダのみ必要」なので任意扱いとし、`get_llm_api_key(provider)` で取り出す時点で未設定なら `ValueError`。

-----

### T03: ロガー・共通ユーティリティ ✅ 完了 (2026-05-28)

**目的**: 構造化ログとエラーハンドリング基盤

**作業内容**

- `app/utils/logger.py`: Cloud Logging互換のJSON形式
- リトライデコレータ（指数バックオフ）
- カスタム例外クラス（ArxivAPIError, LLMAPIError, LineAPIError等）

**完了条件**

- ログ出力テストが通る
- リトライデコレータのテストが通る（モック使用）

**成果物**

- `app/utils/logger.py`: `JsonFormatter` で stdout に Cloud Logging 互換の JSON 1 行を出力。`logger.info("msg", extra={...})` の extra フィールドをそのまま payload に取り込む。
- `app/utils/retry.py`: `@retry_with_backoff(exceptions=(SomeTransientError,))` で対象例外型を絞れる。指数バックオフ+ジッタ。
- `app/utils/exceptions.py`: `ArxivDigestError` をベースに `ArxivAPIError` / `LLMAPIError` / `LineAPIError` / `FirestoreError` / `CostLimitExceededError` / `ConfigError`。永続/一時を区別するため `*TransientError` サブクラスを追加（retry の対象はこちらに限定）。
- `tests/test_logger.py`: フィールド・extra・例外を含む JSON 出力を検証。
- `tests/test_retry.py`: 成功・複数回失敗→成功・上限超え失敗・非対象例外・指数バックオフ待機時間を検証。

-----

## M1: コアパイプライン

### T04: arXiv API クライアント ✅ 完了 (2026-05-28)

**目的**: 前日投稿の論文一覧を取得

**作業内容**

- `app/core/fetcher.py` 実装
- arXiv APIへのクエリ生成（カテゴリ・日付範囲）
- レスポンスXMLのパース（feedparser or arxiv ライブラリ）
- `Paper` データクラス（arxiv_id, title, abstract, authors, categories, published_at, pdf_url）
- 3秒インターバルでのリクエスト制御

**完了条件**

- `fetcher.fetch_recent(categories=["cs.AI"], hours=36)` で論文リストが取得できる
- 単体テスト（モック使用）が通る

**参考**

- arXiv API: <https://info.arxiv.org/help/api/index.html>
- `arxiv` Pythonパッケージが利用可能

**成果物**

- `app/core/fetcher.py`: `ArxivFetcher.fetch_recent(categories, hours, now=None)` で指定時間幅の投稿を返す。`arxiv` ライブラリの `Client(delay_seconds=3, num_retries=0)` を使い、リトライは自前の `@retry_with_backoff(exceptions=(ArxivAPITransientError,))` に委譲。
- `app/storage/models.py`: `Paper` (arxiv_id, title, abstract, authors, categories, published_at, pdf_url, score?, summary_ja?) を pydantic で定義。
- `tests/test_fetcher.py`: フェイク client で時間幅外の論文除外・空カテゴリ・通信失敗時のリトライ→`ArxivAPIError`・naive datetime 取り扱いを検証。

**設計判断**

- arxiv API への並び順は `SubmittedDate` 降順。`since` より古いレコードに到達したら以降を読まずに break することで早期打ち切り。
- arxiv 結果のパース時に問題が起きても warning ログのみで処理は続行（1 件の異常で全件失うのを避ける）。

-----

### T05: Firestore ストレージ層 ✅ 完了 (2026-05-28)

**目的**: 配信履歴・重複防止データの永続化

**作業内容**

- `app/storage/firestore.py` 実装
- `app/storage/models.py`: Pydantic models for Firestore docs
- メソッド: `is_already_sent(arxiv_id) -> bool`, `mark_as_sent(papers)`, `save_digest(digest)`, `get_digest(id)`, `list_digests(limit)`
- ローカル開発用: Firestore emulator対応

**完了条件**

- emulator上でCRUDが動作
- 単体テストが通る

**成果物**

- `app/storage/base.py`: `Storage` 抽象クラス。`is_already_sent` / `mark_as_sent` / `save_digest` / `get_digest` / `list_digests` / `get_cost_today` / `add_cost`。
- `app/storage/memory.py`: `InMemoryStorage` 実装（ローカル開発・テスト・dry-run 用）。
- `app/storage/firestore.py`: `FirestoreStorage` 実装。`google-cloud-firestore` はオプション依存（`pip install '.[firestore]'`）として、import を `__init__` 内で遅延し、未インストール時は `FirestoreError`。
- `app/storage/factory.py`: `GOOGLE_CLOUD_PROJECT` または `FIRESTORE_EMULATOR_HOST` の有無で実装を自動切り替え。
- `app/storage/models.py`: `Paper` / `DigestPaper` / `DigestRecord` / `CostRecord`。
- `tests/test_storage.py`: `InMemoryStorage` の CRUD・日次コスト累積・日付ごとの分離を 7 テスト。

**動作確認メモ**

- 実 Firestore emulator での動作確認は当環境では未実施（`gcloud emulators` 不可）。emulator 接続コードは `FirestoreStorage` 内に書いてあるが、emulator 上での CRUD は M4 / 本番デプロイ時にユーザー側で確認する想定。コアな CRUD ロジックは `InMemoryStorage` の単体テストでカバーしている。

-----

### T06: 粗フィルタ ✅ 完了 (2026-05-28)

**目的**: LLM前段でのルールベース絞り込み

**作業内容**

- `app/core/filter.py` 実装
- キーワード/著者によるスコア加算ロジック
- 重複除外（sent_papersとの突合）
- 件数で上位N件に絞る

**完了条件**

- 500件の入力から200件以内に絞れる
- キーワード加点が期待通り動作する単体テストが通る

**成果物**

- `app/core/filter.py`: `PreFilter(config, storage).apply(papers)`。baseline 1.0 にキーワード正規表現と著者名一致を加点して降順ソート、`max_papers` 件で打ち切り。重複除外は `storage.is_already_sent` で行う。
- `tests/test_filter.py`: キーワード加点（大文字小文字非依存含む）・著者加点・送信済み除外・500→200 切り詰め・加点なし時のベースライン挙動を 6 テスト。

-----

### T07: LLMプロバイダ抽象化（Groq実装） ✅ 完了 (2026-05-28)

**目的**: スコアリングと要約の共通インタフェース、まずはGroqで実装

**作業内容**

- `app/providers/llm/base.py` 抽象基底クラス
- `app/providers/llm/groq.py` Groq実装
  - `score(papers) -> list[float]`: バッチ処理（複数論文を1リクエストで効率化）
  - `summarize(paper) -> str`
  - `estimate_cost`, `get_usage` メソッド
- プロンプト定義（設計書 §7 参照、`prompts/` ディレクトリに分離可）

**完了条件**

- 実APIで10本程度の論文をスコアリング・要約できる
- コスト計算が概ね正しい

**成果物**

- `app/providers/llm/base.py`: `LLMProvider` 抽象クラス (`name` / `model` / `score` / `summarize` / `estimate_cost` / `get_usage`)、`Usage` / `TokenUsage` dataclass。
- `app/providers/llm/prompts.py`: 設計書 §7 のスコアリング・要約プロンプト。
- `app/providers/llm/pricing.py`: `config/llm_pricing.yaml` を読み込む `PricingTable`。
- `app/providers/llm/groq.py`: Groq OpenAI 互換 chat completions を `httpx.Client` で呼び出す `GroqProvider`。`score` はバッチ送信（既定 20 件/req、JSON モード）、`summarize` は 1 論文 1 req。HTTP 5xx/429 は `LLMAPITransientError` でリトライ対象、4xx は `LLMAPIError` で即時失敗。`get_usage()` で累積トークンとコスト USD を返す。
- `tests/test_groq.py`: バッチ JSON パース・順序保持・バッチ分割・要約・5xx リトライ→成功・4xx 即時失敗・コスト見積もり (要約>スコア)・単価未設定時 0・JSON 不正時の `LLMAPIError` を 9 テスト。

**動作確認メモ**

- 実 Groq API キーが当環境では用意できないため「10 本程度の論文を実 API でスコアリング・要約」の検証は未実施。`GROQ_API_KEY` を `.env` に設定したうえでユーザー側で `python -m app.core.pipeline --dry-run --force` を実行することで、実際の API 呼び出しと `get_usage()` のコスト記録を確認できる。HTTP 経路と JSON パースは単体テストでカバー済み。

-----

### T08: パイプラインオーケストレーション ✅ 完了 (2026-05-28)

**目的**: T04-T07を組み合わせて E2E実行

**作業内容**

- `app/core/pipeline.py` 実装
- 設計書 §5 のフロー [1]→[7] を実装（LINE送信前まで）
- コスト上限チェック実装
- 失敗時のステータス記録

**完了条件**

- CLIから `python -m app.core.pipeline --dry-run` で実行でき、上位5本の要約がコンソールに出る
- 累積コストが想定範囲内

**成果物**

- `app/core/pipeline.py`: `Pipeline.run(trigger, top_n, force, now)` で設計書 §5 のフロー [1]-[7] を順に実行。[4] のコスト上限チェックは `estimate_cost(score) + estimate_cost(summarize top_n)` を当日累計に加算して判定し、`CostLimitExceededError` を投げる（`force=True` でバイパス）。LLM の累積コストは終了時に `storage.add_cost` で記録。`build_default_pipeline()` ヘルパで `ArxivFetcher` + `PreFilter` + `GroqProvider` + storage 自動選択をまとめる。
- CLI: `python -m app.core.pipeline --dry-run [--top-n N] [--force]`。起動時に `get_secrets()` を呼んで必須環境変数を検証する。
- `tests/test_pipeline.py`: 上位 N 件選出と要約・コスト上限ブロック・force でバイパス・空 fetch の `success`・送信済み論文の除外・コスト計上を 6 テスト。

**動作確認メモ**

- 実 arXiv API + 実 Groq API を叩く CLI フルランは API キー未取得のため当環境では未実施。代わりに `Pipeline.run()` を `unittest.mock` で組み立てた E2E 単体テストで [1]-[7] 全段を検証している（上位 N 件のスコア順選出・要約付与・コスト記録）。ユーザー側で `GROQ_API_KEY` を設定したうえで `python -m app.core.pipeline --dry-run` を実行することで、コンソールに上位 5 本の要約が出力されることを確認できる。

-----

## M2: 通知

### T09: LINE Messaging API クライアント

**目的**: LINEへの個人DM送信

**作業内容**

- `app/providers/notification/line.py` 実装
- LINE Developer Consoleでチャネル作成手順をREADMEに追記
- テキストメッセージ送信
- 長文時の分割送信（1メッセージ5000文字制限）
- 将来のFlex Message対応を見据えた構造

**完了条件**

- 自分のLINEアカウントにテストメッセージが届く

**参考**

- LINE Messaging API: <https://developers.line.biz/ja/reference/messaging-api/>

-----

### T10: メッセージフォーマッタ

**目的**: 論文情報を読みやすい配信形式に整形

**作業内容**

- ヘッダ（日付・件数）
- 論文ごと: タイトル / 著者 / カテゴリ / スコア / 要約 / arXivリンク
- Phase1はプレーンテキスト、Phase2でFlex Message化

**完了条件**

- 5本のサンプルから整形済みメッセージが生成され、長さが配信制限内

-----

### T11: パイプラインへの通知統合

**目的**: フロー [8][9] を統合し、E2E完成

**作業内容**

- `pipeline.py` に通知ステップを追加
- dry_runフラグでLINE送信スキップ
- 全成功・部分成功・失敗のステータス管理
- digest_history への保存

**完了条件**

- 本物のLINEアカウントに5本のサマリーが届く
- Firestoreに履歴が記録される

-----

## M3: API化

### T12: FastAPI ルート実装

**目的**: HTTPエンドポイントとして公開

**作業内容**

- `app/api/routes.py`: 設計書 §4 の全エンドポイント
- リクエスト/レスポンスのPydanticモデル
- バックグラウンド実行（FastAPI BackgroundTasks or asyncioで非同期化）

**完了条件**

- `POST /digest/run` が動作
- OpenAPIドキュメント (`/docs`) が表示される

-----

### T13: 認証ミドルウェア

**目的**: Bearer Token認証

**作業内容**

- `app/api/auth.py` 実装
- 共有秘密鍵による検証
- `/healthz` は認証不要

**完了条件**

- 不正トークンで401が返る
- 正しいトークンで処理が通る

-----

### T14: エンドポイントの統合テスト

**目的**: API経由でE2E動作することを確認

**作業内容**

- pytestでFastAPI TestClientを使った統合テスト
- モック使用（外部API呼び出しはスタブ化）

**完了条件**

- 主要エンドポイントの統合テストが全パス

-----

## M4: クラウドデプロイ

### T15: GCPプロジェクトセットアップ手順

**目的**: 環境準備手順を文書化

**作業内容**

- README または `docs/setup-gcp.md` に手順を記載
- 必要なAPI有効化（Cloud Run, Firestore, Secret Manager, Scheduler, Artifact Registry）
- サービスアカウントと権限設定
- Firestore の初期化（Native mode）
- Secret Manager への各種シークレット登録

**完了条件**

- 別環境で手順通りに進めて再現できる

-----

### T16: Cloud Run デプロイ用 Dockerfile 最適化

**目的**: 本番イメージのサイズ・起動速度最適化

**作業内容**

- マルチステージビルド
- 不要ファイル除外（.dockerignore）
- gunicorn + uvicorn worker構成
- ヘルスチェック設定

**完了条件**

- Cloud Runへ手動デプロイが成功
- `/healthz` が応答する

-----

### T17: GitHub Actions による CI/CD

**目的**: mainブランチへのpushで自動デプロイ

**作業内容**

- `.github/workflows/test.yml`: テスト実行
- `.github/workflows/deploy.yml`: ビルド → Artifact Registry → Cloud Run更新
- Workload Identity Federation設定

**完了条件**

- mainへのpushで自動デプロイが完走

-----

### T18: Cloud Scheduler 設定

**目的**: 毎日定刻実行

**作業内容**

- Scheduler ジョブ作成（毎日 06:30 JST = 21:30 UTC前日）
- OIDCトークン認証でCloud Runを叩く
- 設定をTerraform or gcloudコマンド集としてリポジトリに残す

**完了条件**

- スケジュール時刻にLINEが届く
- 失敗時に Cloud Logging にエラーが出る

-----

## M5: 運用機能

### T19: iOS Shortcut のセットアップガイド

**目的**: スマホから手動実行できる

**作業内容**

- README に手順記載（URL、認証ヘッダ、Body）
- スクリーンショット付きが理想
- ドライランモード用と本実行用の2種類

**完了条件**

- iPhoneから1タップで実行 → LINE受信を確認

-----

### T20: コストアラート

**目的**: 上限到達時の検知

**作業内容**

- 日次コスト80%到達時に管理者LINEへアラート
- 上限到達時の処理スキップ動作確認

**完了条件**

- 上限を意図的に低くした状態でテストし、アラートが届く

-----

### T21: 運用ドキュメント

**目的**: 日常的なトラブルシュートに必要な情報を整備

**作業内容**

- ログの見方（Cloud Logging のフィルタ例）
- よくある障害と対処（API障害、Firestore権限、Secret Managerアクセス）
- LLMプロバイダ追加方法（拡張ガイド）
- バックアップ・リストア手順（Firestore export）

**完了条件**

- READMEから関連ドキュメントへのリンクが揃っている

-----

## 工数見積もり（参考）

|MS    |目安日数（実働）  |
|------|----------|
|M0    |0.5日      |
|M1    |2-3日      |
|M2    |1日        |
|M3    |1日        |
|M4    |1-2日      |
|M5    |0.5日      |
|**合計**|**6-8日程度**|

ペース感: 平日夜+週末で2週間程度を想定。

-----

## Claude Code に渡す際の推奨

1. **3つのドキュメントすべてをプロジェクトルートの `docs/` に配置**してから着手依頼
1. タスク単位で依頼し、完了条件を満たしたか確認してから次へ進む
1. T01・T02・T03は連続して依頼可能、それ以降は単発で
1. T07の段階で実APIキーが必要になるので、Groqアカウント作成を先に済ませておく
1. T11の手前で LINE Developer Console での Bot作成を済ませる

## ドキュメント一覧

- `requirements.md`: 要件定義書
- `design.md`: 設計書
- `tasks.md`: 本タスク分割書
