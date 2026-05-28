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

### T02: 設定ファイル読み込み

**目的**: settings.yaml と環境変数の読み込み層を作る

**作業内容**

- `app/config.py` 実装（pydantic-settings推奨）
- `config/settings.yaml` 雛形作成
- `config/llm_pricing.yaml` 雛形作成
- 必須環境変数: `API_AUTH_SECRET`, `LLM_API_KEY_*`, `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_USER_ID`

**完了条件**

- pytest で設定読み込みのテストが通る
- 必須環境変数欠落時に起動エラーを出す

-----

### T03: ロガー・共通ユーティリティ

**目的**: 構造化ログとエラーハンドリング基盤

**作業内容**

- `app/utils/logger.py`: Cloud Logging互換のJSON形式
- リトライデコレータ（指数バックオフ）
- カスタム例外クラス（ArxivAPIError, LLMAPIError, LineAPIError等）

**完了条件**

- ログ出力テストが通る
- リトライデコレータのテストが通る（モック使用）

-----

## M1: コアパイプライン

### T04: arXiv API クライアント

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

-----

### T05: Firestore ストレージ層

**目的**: 配信履歴・重複防止データの永続化

**作業内容**

- `app/storage/firestore.py` 実装
- `app/storage/models.py`: Pydantic models for Firestore docs
- メソッド: `is_already_sent(arxiv_id) -> bool`, `mark_as_sent(papers)`, `save_digest(digest)`, `get_digest(id)`, `list_digests(limit)`
- ローカル開発用: Firestore emulator対応

**完了条件**

- emulator上でCRUDが動作
- 単体テストが通る

-----

### T06: 粗フィルタ

**目的**: LLM前段でのルールベース絞り込み

**作業内容**

- `app/core/filter.py` 実装
- キーワード/著者によるスコア加算ロジック
- 重複除外（sent_papersとの突合）
- 件数で上位N件に絞る

**完了条件**

- 500件の入力から200件以内に絞れる
- キーワード加点が期待通り動作する単体テストが通る

-----

### T07: LLMプロバイダ抽象化（Groq実装）

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

-----

### T08: パイプラインオーケストレーション

**目的**: T04-T07を組み合わせて E2E実行

**作業内容**

- `app/core/pipeline.py` 実装
- 設計書 §5 のフロー [1]→[7] を実装（LINE送信前まで）
- コスト上限チェック実装
- 失敗時のステータス記録

**完了条件**

- CLIから `python -m app.core.pipeline --dry-run` で実行でき、上位5本の要約がコンソールに出る
- 累積コストが想定範囲内

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
