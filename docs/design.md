# arXiv Digest Service — 設計書

## 1. システム全体構成

### 1.1 アーキテクチャ図

```
┌──────────────────────┐      ┌──────────────────────┐
│  Cloud Scheduler     │      │  iOS Shortcut /      │
│  (毎日 06:30 JST)    │      │  手動HTTP叩く        │
└──────────┬───────────┘      └──────────┬───────────┘
           │ HTTPS POST                  │
           └──────────────┬──────────────┘
                          ▼
          ┌───────────────────────────────────┐
          │     Cloud Run (Service)            │
          │  ┌─────────────────────────────┐  │
          │  │  FastAPI Application         │  │
          │  │   POST /digest/run           │  │
          │  │   GET  /digest/history       │  │
          │  │   GET  /healthz              │  │
          │  └─────────────────────────────┘  │
          └─────┬──────────┬──────────┬───────┘
                │          │          │
       ┌────────▼──┐  ┌────▼─────┐  ┌─▼──────────┐
       │ arXiv API │  │ LLM API  │  │ LINE Msg   │
       │           │  │ (Groq等) │  │ API        │
       └───────────┘  └──────────┘  └────────────┘
                │          │          │
                └──────────┼──────────┘
                           ▼
              ┌────────────────────────┐
              │  Firestore             │
              │  - digest_history      │
              │  - sent_papers         │
              │  - cost_tracker        │
              └────────────────────────┘
              ┌────────────────────────┐
              │  Secret Manager        │
              │  - LLM API keys        │
              │  - LINE tokens         │
              │  - API auth secret     │
              └────────────────────────┘
```

### 1.2 技術スタック

|レイヤ       |技術                     |選定理由                      |
|----------|-----------------------|--------------------------|
|実行環境      |Google Cloud Run       |最大60分の実行時間、HTTPトリガ、無料枠が寛大 |
|言語        |Python 3.12            |LLM/データ処理ライブラリが充実         |
|Webフレームワーク|FastAPI                |非同期処理、自動OpenAPIドキュメント     |
|データストア    |Cloud Firestore        |サーバーレス、無料枠あり、Cloud Run親和性高|
|シークレット管理  |Google Secret Manager  |キー管理のベストプラクティス            |
|定期実行      |Cloud Scheduler        |Cloud RunのHTTPエンドポイントを叩く  |
|CI/CD     |GitHub Actions         |標準的、Cloud Runへのデプロイが容易    |
|ローカル開発    |Docker / docker-compose|環境再現性                     |

## 2. モジュール構成

### 2.1 ディレクトリ構造

```
arxiv-digest/
├── app/
│   ├── main.py                  # FastAPIエントリポイント
│   ├── config.py                # 設定読み込み
│   ├── api/
│   │   ├── routes.py            # APIルート定義
│   │   └── auth.py              # 認証ミドルウェア
│   ├── core/
│   │   ├── pipeline.py          # 全体オーケストレーション
│   │   ├── fetcher.py           # arXiv API クライアント
│   │   ├── filter.py            # 粗フィルタ
│   │   ├── scorer.py            # 重要度スコアリング
│   │   ├── summarizer.py        # 日本語要約生成
│   │   └── notifier.py          # LINE配信
│   ├── providers/
│   │   ├── llm/
│   │   │   ├── base.py          # LLMプロバイダ抽象基底
│   │   │   ├── groq.py
│   │   │   ├── together.py
│   │   │   ├── openai.py
│   │   │   └── anthropic.py
│   │   └── notification/
│   │       ├── base.py
│   │       └── line.py
│   ├── storage/
│   │   ├── firestore.py         # Firestore クライアント
│   │   └── models.py            # データモデル
│   └── utils/
│       ├── cost_tracker.py      # コスト計測
│       └── logger.py
├── config/
│   ├── settings.yaml            # 興味分野・キーワード等
│   └── llm_pricing.yaml         # プロバイダ別単価表
├── tests/
├── scripts/
│   └── (精度検証スクリプトは別途、本リポジトリには含まない)
├── Dockerfile
├── requirements.txt
├── .github/workflows/deploy.yml
└── README.md
```

## 3. データモデル

### 3.1 Firestore コレクション設計

**`sent_papers`** (重複防止)

```
{
  arxiv_id: "2401.12345",        // ドキュメントID
  sent_at: Timestamp,
  digest_id: "digest_20260528"
}
```

**`digest_history`** (配信履歴)

```
{
  digest_id: "digest_20260528",  // ドキュメントID
  executed_at: Timestamp,
  trigger: "scheduled" | "manual" | "dry_run",
  papers: [
    {
      arxiv_id: "2401.12345",
      title: "...",
      authors: ["..."],
      categories: ["cs.AI"],
      score: 8.5,
      summary_ja: "...",
      url: "https://arxiv.org/abs/2401.12345"
    }
  ],
  llm_provider: "groq",
  llm_model: "llama-3.3-70b-versatile",
  total_cost_usd: 0.012,
  duration_sec: 87,
  status: "success" | "failed" | "partial"
}
```

**`cost_tracker`** (日次コスト記録)

```
{
  date: "2026-05-28",            // ドキュメントID
  total_cost_usd: 0.34,
  request_count: 12,
  updated_at: Timestamp
}
```

## 4. API仕様

### 4.1 エンドポイント一覧

|Method|Path                 |概要         |認証|
|------|---------------------|-----------|--|
|POST  |`/digest/run`        |Digest実行   |必須|
|GET   |`/digest/history`    |配信履歴取得     |必須|
|GET   |`/digest/{digest_id}`|特定Digestの詳細|必須|
|GET   |`/healthz`           |ヘルスチェック    |不要|

### 4.2 `POST /digest/run`

**リクエスト**

```json
{
  "dry_run": false,
  "target_date": "2026-05-27",
  "top_n": 5,
  "categories": ["cs.AI", "cs.LG", "cs.CL"],
  "llm_provider": "groq",
  "llm_model": "llama-3.3-70b-versatile",
  "force": false
}
```

- すべてオプション（未指定時はsettings.yamlのデフォルト）
- `force`: コスト上限を一時的に無視（手動実行時のみ意味あり）

**レスポンス**

```json
{
  "digest_id": "digest_20260528",
  "status": "success",
  "papers_count": 5,
  "total_cost_usd": 0.012,
  "duration_sec": 87,
  "preview": [
    {"title": "...", "score": 8.5, "summary_ja": "..."}
  ]
}
```

### 4.3 認証

- Bearer Token方式
- `Authorization: Bearer <SHARED_SECRET>`
- SHARED_SECRETはSecret Managerで管理

## 5. パイプライン処理フロー

```
[1] FETCH
    arXiv API から前日投稿の cs.AI, cs.LG, cs.CL, cs.CV, cs.NE, stat.ML を取得
    → 候補論文リスト (~500-1000本)
        │
        ▼
[2] DEDUPE
    Firestore sent_papers と突合し、未送信のものに絞る
        │
        ▼
[3] PREFILTER
    キーワード加点・著者加点でスコア計算、上位200本に絞る
    （LLMコスト抑制のため）
        │
        ▼
[4] COST CHECK
    本日累計コスト + 推定コスト が上限内かチェック
    超過時: スキップして失敗ステータスで終了
        │
        ▼
[5] SCORE
    LLMで各論文の重要度を0-10でスコアリング
    → スコア付き論文リスト
        │
        ▼
[6] SELECT
    スコア上位 N本 (デフォルト5) を選出
        │
        ▼
[7] SUMMARIZE
    各論文のタイトル+Abstractを日本語要約
    出力形式: 3行要約 + なぜ重要か
        │
        ▼
[8] NOTIFY
    LINE Messaging APIで送信 (dry_run時はスキップ)
        │
        ▼
[9] PERSIST
    digest_history に記録、sent_papers に追加、cost_tracker 更新
```

## 6. LLMプロバイダ抽象化

### 6.1 基底クラス設計（概念）

```python
class LLMProvider(ABC):
    @abstractmethod
    async def score(self, papers: list[Paper]) -> list[float]:
        """各論文に0-10のスコアを返す"""

    @abstractmethod
    async def summarize(self, paper: Paper) -> str:
        """日本語要約を返す"""

    @abstractmethod
    def estimate_cost(self, papers: list[Paper], task: str) -> float:
        """事前コスト見積もり (USD)"""

    @property
    @abstractmethod
    def name(self) -> str: ...
```

### 6.2 サポートする初期プロバイダ

|Provider   |Model例                 |用途         |
|-----------|-----------------------|-----------|
|Groq       |llama-3.3-70b-versatile|デフォルト・無料枠活用|
|Together AI|Qwen2.5-72B-Instruct   |バックアップ・比較対象|
|OpenAI     |gpt-4o-mini            |比較対象       |
|Anthropic  |claude-haiku-4-5       |比較対象       |

### 6.3 プロバイダ切り替え

- リクエストパラメータで指定可能
- 未指定時はsettings.yamlのデフォルトを使用

## 7. プロンプト設計

### 7.1 スコアリング用プロンプト（要旨）

```
あなたはAI研究の動向に精通した研究者です。
以下のarXiv論文のタイトルとAbstractを読み、AI分野全般における
新規性・インパクト・話題性を考慮して0-10で重要度をスコアリングしてください。

評価基準:
- 9-10: 分野を変える可能性のあるブレイクスルー
- 7-8: 主要会議で議論されるレベルの貢献
- 5-6: 着実な改善・興味深いアプローチ
- 3-4: 限定的な貢献
- 0-2: 既存研究の小さな変種

【タイトル】{title}
【Abstract】{abstract}
【カテゴリ】{categories}

出力: スコア数値のみ（小数点1桁まで）
```

### 7.2 要約用プロンプト（要旨）

```
以下のarXiv論文を日本語で要約してください。
LINEで読まれることを想定し、簡潔かつ専門用語は最小限に。

出力形式（厳守）:
【何の研究か】1-2文
【提案手法】2-3文
【結果・インパクト】1-2文
【なぜ読む価値があるか】1文

【タイトル】{title}
【Abstract】{abstract}
```

## 8. コスト管理

### 8.1 計測単位

- LLMプロバイダごとに入力/出力トークン単価をconfig/llm_pricing.yamlに定義
- API呼び出し時にトークン数を取得し、`cost_tracker` に加算

### 8.2 上限超過時の挙動

1. 処理開始時: 当日累計 + 推定コスト > 上限 なら即時失敗
1. 処理中: 各LLM呼び出し後に累計を再計算、超過予測なら以降の処理を中断
1. `force=true` 時のみこのチェックをバイパス

## 9. エラーハンドリング・リトライ

|失敗箇所         |対応                                         |
|-------------|-------------------------------------------|
|arXiv API一時障害|指数バックオフで最大3回リトライ                           |
|LLM API一時障害  |指数バックオフで最大3回リトライ、別プロバイダへのフォールバックは将来検討      |
|LINE API障害   |1回リトライ、失敗時はdigest_historyにstatus=partialで記録|
|Firestore障害  |リトライ後失敗ならログのみ（処理続行）                        |
|3日連続全失敗      |管理者へLINEでアラート（別チャネル）                       |

## 10. 設定ファイル例

### 10.1 `config/settings.yaml`

```yaml
arxiv:
  categories: [cs.AI, cs.LG, cs.CL, cs.CV, cs.NE, stat.ML]
  fetch_window_hours: 36   # 前日分を確実にカバーするため少し広めに

prefilter:
  max_papers: 200
  keywords_boost:
    - {pattern: "large language model|LLM", weight: 3}
    - {pattern: "RAG|retrieval[- ]augmented", weight: 3}
    - {pattern: "agent", weight: 2}
    - {pattern: "diffusion", weight: 2}
  authors_boost:
    - {name: "Yann LeCun", weight: 2}

digest:
  top_n: 5
  schedule_jst: "06:30"

llm:
  default_provider: groq
  default_model: llama-3.3-70b-versatile

cost:
  daily_limit_usd: 1.0
  alert_threshold_ratio: 0.8

line:
  message_format: text   # text | flex
```

## 11. デプロイ

### 11.1 ローカル開発

```bash
docker compose up
# http://localhost:8080/digest/run を叩いて動作確認
```

### 11.2 本番デプロイ

- GitHub mainブランチへのpushで GitHub Actions が起動
- Cloud Buildでイメージビルド → Artifact Registryへpush
- Cloud Run サービスを更新

### 11.3 スマホからの実行

- iOS Shortcuts.app に「arXiv Digest 実行」ショートカットを作成
- URL: `https://<cloud-run-url>/digest/run`
- Header: `Authorization: Bearer <SHARED_SECRET>`
- Body: `{"dry_run": false}`

## 12. 監視・ログ

- Cloud Logging: アプリケーションログを集約
- Cloud Monitoring: エラー率・実行時間を可視化
- ダッシュボード: 日次コスト推移、配信成功率

## 13. 精度比較機能の仕様（実装は別リポジトリ / フェーズ別管理）

将来 `/digest/compare` エンドポイントを追加する想定。仕様メモのみ記載:

- 入力: 検証用論文セット（10-20本）、比較対象LLMリスト
- 処理: 同じ論文を各LLMで要約・スコアリングし結果を保存
- 出力: 各LLMの要約・推定コスト・所要時間の比較レポート
- 評価軸（人手）: 簡潔性、情報の正確性、日本語の自然さ、判断の妥当性
- 実装は別途検証スクリプトとして用意し、本サービスのAPIとは独立して運用

## 14. 段階的移行計画

```
Phase 1 (MVP, ~2週間)
  └─ Abstract要約のみ、Groq無料枠、個人配信、定期+手動実行
       │
       ▼
Phase 2 (~1ヶ月後)
  ├─ 論文PDF全文要約への対応 (本文ダウンロード → セクション抽出 → 要約)
  ├─ 精度比較API/スクリプトの整備
  └─ 配信履歴閲覧Web UI
       │
       ▼
Phase 3 (マネタイズ準備)
  ├─ 複数購読者対応 (購読者ごとの興味プロファイル)
  ├─ 興味学習機能 (フィードバック収集)
  └─ ランディングページ
       │
       ▼
Phase 4 (収益化)
  └─ Stripe連携、無料/有料プラン
```
