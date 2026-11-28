# AI Gateway — 設計仕様書

## 1. コンセプト

外部 LLM (Claude / OpenAI 等) へのリクエストを中継しながら、Q&A ペアを蓄積してローカル LLM をファインチューニングし続ける**自己学習型 LLM プロキシ**。

- アプリ側のコード変更は**ベース URL の差し替えのみ**
- 使えば使うほど外部 API 依存が下がる
- 学習済みナレッジは社内完結 (プライバシー担保)
- 任意のアプリ (Alexa, Web, CLI, 社内ツール等) から共通利用可能
- `git clone → make setup → make up` だけで環境構築完了

### 1.1 役割の見直し（2026-11）

複数のアプリを 1 台の小さなサーバー（RAM 約 6GB）で動かす環境で使うにあたり、役割を次のように改める。詳細は [10.1 節](#101-役割の見直し2026-11の内容) にまとめる。

| 役割 | 位置づけ |
|---|---|
| **アプリから LLM への共通の経路**（外向き） | 中心の役割。アプリごとのキー・月の上限・利用ログ・プロバイダーの切り替えを 1 か所で扱う |
| **MCP の入口**（内向き） | AI アシスタント（Claude など）から各アプリの MCP サーバーを束ねて使う入口（計画。[10.1 節](#101-役割の見直し2026-11の内容)） |
| セマンティックキャッシュ | 既定では**ローカルモデル（Ollama）が答える要求だけ**で使う。設定の `cache.enabled`・`cache.local_only`（環境変数でも）で、使わない・外部の LLM の答えも使う、に切り替えられる（[3.2 節](#32-semantic-cache)） |
| Knowledge Store・ファインチューニング | 既定で止める。GPU と 16GB 以上の RAM がある環境で、ローカルモデルを育てるときだけ有効にする |
| 自動の振り分け（Router） | 要求の経路では使わない（キャッシュの類似度を入力にしていたため）。`model` の指定と既定のプロバイダーで決める |

---

## 2. アーキテクチャ全体図

```
┌──────────────────────────────────────────────────────────────────┐
│                        AI Gateway                                │
│                                                                  │
│   クライアントアプリ                                               │
│   Alexa / Web / CLI / 社内ツール                                  │
│           │                                                       │
│           ▼                                                       │
│   ┌───────────────────┐                                          │
│   │   API Layer       │  POST /v1/chat/completions (OpenAI 互換) │
│   │   (FastAPI)       │  POST /v1/embeddings                     │
│   └────────┬──────────┘                                          │
│            │                                                      │
│            ▼                                                      │
│   ┌───────────────────┐                                          │
│   │ Semantic Cache    │  pgvector / asyncpg                      │
│   │ (類似クエリ検索)    │  類似度 > 閾値 → キャッシュ応答           │
│   └────────┬──────────┘                                          │
│        ヒットなし                                                  │
│            │                                                      │
│            ▼                                                      │
│   ┌───────────────────┐                                          │
│   │   Router          │  信頼スコア判定                            │
│   │   (local / 外部)  │  score = cache_sim×0.6 + local_acc×0.4  │
│   └──────┬────────────┘                                          │
│      ┌───┴───┐                                                   │
│  信頼高       信頼低                                               │
│      ▼           ▼                                               │
│  ┌────────┐  ┌──────────┐                                        │
│  │Local   │  │外部 LLM  │  Claude / OpenAI / Gemini              │
│  │LLM     │  │Connector │                                        │
│  │(Ollama)│  └────┬─────┘                                        │
│  └────────┘       │                                              │
│                   ▼                                              │
│          ┌─────────────────┐                                     │
│          │ Knowledge Store │  Q&A ペア + メタデータ保存            │
│          │ (PostgreSQL +   │  ドメインタグ自動付与                  │
│          │  pgvector)      │                                     │
│          └────────┬────────┘                                     │
│                   │ 定期バッチ (APScheduler)                      │
│                   ▼                                              │
│          ┌─────────────────┐                                     │
│          │Fine-tuning      │  Unsloth + LoRA                     │
│          │Pipeline         │  ローカル LLM モデル更新              │
│          └─────────────────┘                                     │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. コンポーネント詳細

### 3.1 API Layer

| 項目 | 内容 |
|---|---|
| フレームワーク | FastAPI (Python 3.12) |
| 主エンドポイント | `POST /v1/chat/completions` |
| 補助エンドポイント | `POST /v1/embeddings`, `GET /v1/models`, `GET /health` |
| 管理エンドポイント | `GET|DELETE /v1/admin/cache/*`, `GET /v1/admin/knowledge/*`, `POST|GET /v1/admin/finetuning/*` |
| 互換性 | OpenAI API 互換 (ドロップイン置換) |
| 認証 | Bearer トークン (`gateway/auth.py`) |
| ストリーミング | SSE (Server-Sent Events) 対応 |
| メトリクス | `GET /metrics` (Prometheus 形式) |

リクエスト例:
```json
POST /v1/chat/completions
{
  "model": "auto",
  "messages": [
    {"role": "user", "content": "マウスの在庫は何個ありますか？"}
  ],
  "metadata": {
    "app": "alexa-inventory",
    "tenant": "warehouse-a"
  }
}
```

レスポンスは OpenAI 互換形式。`metadata.source` に `cache` / `local` / `external` を付加。

---

### 3.2 Semantic Cache

| 項目 | 内容 |
|---|---|
| ストレージ | PostgreSQL 16 + pgvector 拡張 |
| DB アクセス | asyncpg (直接接続) + pgvector.asyncpg |
| 有効にする条件 | `cache.enabled: true`（既定）で、`metadata.app` と `metadata.tenant` が両方あり、`metadata.cache` が `false` でない要求。そのうえで `cache.local_only: true`（既定）なら**ローカルモデル（Ollama）が答える要求だけ**、`false` なら外部の LLM の要求も。外部へ振り替えた答えは、`local_only: true` なら残さない。判定は `gateway/cache/policy.py` |
| 切り替え | 設定ファイル（`app/config.yaml` の `cache:`）か、環境変数 `GATEWAY_CACHE_ENABLED`・`GATEWAY_CACHE_LOCAL_ONLY`（`true` / `false`。環境変数が優先。読めない値は起動時にエラー）。2026-11 の一時期の `cache.mode: local_only / off` も読む |
| 検索の範囲 | `app` と `tenant` が両方とも一致するエントリだけ（ほかのアプリ・テナントの答えを返さない） |
| 埋め込みモデル | ローカルモデルの要求は `nomic-embed-text` (Ollama) だけ（キャッシュのために外部へ質問文を送らない）。外部の LLM の要求（`local_only: false` のときだけ）は、質問文をもともと外部に送るため、従来の経路（Ollama → OpenAI `text-embedding-3-small`）で作る |
| ベクトル次元 | 768次元 (nomic-embed-text) |
| 類似度閾値 | デフォルト 0.92 (config.yaml で変更可) |
| TTL | ナレッジタイプ別 (デフォルト: 無期限) |
| インデックス | IVFFlat (lists=100) |

```sql
-- cache_entries テーブル
id          UUID PRIMARY KEY
query_text  TEXT
query_vec   vector(768)
response    JSONB
source      TEXT          ('cache','local','external')
app         TEXT
tenant      TEXT
created_at  TIMESTAMPTZ
hit_count   INTEGER
ttl_expires TIMESTAMPTZ
```

---

### 3.3 Router (local / 外部判定)

> 2026-11 の見直しで、要求の経路では使わなくなった。プロバイダーは `model`（`auto` は `llm.default_provider`、`local` は Ollama）で決める。
> 以下は、ローカルモデルを育てる構成で使っていた以前の設計として残す。

```
信頼スコア = キャッシュ類似度 × 0.6 + ローカルモデル精度履歴 × 0.4

スコア >= local_confidence_threshold (デフォルト 0.85)  → ローカル LLM
それ以外                                                 → 外部 LLM
```

- ローカルモデル精度履歴: `knowledge_entries` の `quality_score` (used_in_ft=TRUE) の平均
- フォールバック: ローカル LLM でエラー / タイムアウト → 自動的に外部 LLM へ

---

### 3.4 ローカル LLM (Ollama)

| 項目 | 内容 |
|---|---|
| ランタイム | Ollama (Docker コンテナ) |
| 埋め込みモデル | `nomic-embed-text` (起動時に自動ダウンロード) |
| ベースモデル | `llama3.1:8b` (起動時に自動ダウンロード) |
| ファインチューニング後モデル | `ai-gateway-custom` (GGUF → Ollama インポート) |
| GPU | NVIDIA GPU 推奨 (docker-compose コメントで切替可) |

---

### 3.5 外部 LLM Connector

複数プロバイダーを `BaseLLMConnector` 抽象クラスで統一:

```python
# gateway/connectors/base.py
class BaseLLMConnector(ABC):
    async def chat(messages, **kwargs) -> ChatResponse
    async def chat_stream(messages, **kwargs) -> AsyncIterator[str]
```

| コネクター | ファイル | SDK |
|---|---|---|
| Claude | `connectors/anthropic.py` | anthropic |
| OpenAI | `connectors/openai_connector.py` | openai |
| Gemini | `connectors/gemini.py` | google-genai |
| Ollama | `connectors/ollama.py` | httpx (REST) |

---

### 3.6 Knowledge Store

```sql
-- knowledge_entries テーブル
id            UUID PRIMARY KEY
query_text    TEXT
response_text TEXT
provider      TEXT           ('claude','openai','ollama')
quality_score FLOAT          (NULL = 未評価)
domain_tags   TEXT[]         ドメイン自動分類 (inventory/hr/general)
app           TEXT
tenant        TEXT
created_at    TIMESTAMPTZ
used_in_ft    BOOLEAN
```

ドメイン自動分類はキーワードマッチング (`gateway/knowledge/store.py`)。  
品質スコアは将来の自動評価拡張を想定し、現在は NULL で格納。

---

### 3.7 Fine-tuning Pipeline

```
[トリガー]
  - APScheduler スケジュール (デフォルト: 毎週日曜 2:00 AM)
  - POST /v1/admin/finetuning/trigger (手動実行)

[フロー]
  1. finetuning/extract.py  — Knowledge Store から未使用・高品質データ抽出 → /tmp/ft_raw.jsonl
  2. finetuning/prepare.py  — ChatML 形式 JSON Lines 変換 + train/eval 8:2 分割
  3. finetuning/train.py    — Unsloth + LoRA 学習 → GGUF 出力 (GPU 必須)
  4. finetuning/evaluate.py — ROUGE-L ベンチマーク評価 → 合格時 Ollama にインポート
```

> **NOTE**: train.py は GPU 環境 (NVIDIA) と `unsloth` パッケージが別途必要。  
> CPU 環境では extract → prepare まで動作し、train でスキップされる。

---

## 4. データフロー

### 4.1 通常リクエスト処理

```
1. クライアント → POST /v1/chat/completions
2. Bearer トークン認証
3. クエリテキストを nomic-embed-text でベクトル化
4. Semantic Cache 検索 (pgvector cosine similarity)
   4a. 類似度 > 0.92: キャッシュ応答を返す → END
   4b. ミス: Router へ
5. Router: 信頼スコア計算
   5a. スコア高: Ollama (ローカル LLM) へ
   5b. スコア低: 外部 LLM へ
6. 応答を非同期で Knowledge Store + Semantic Cache に保存
7. クライアントへ応答返却 (OpenAI 互換 + metadata.source)
```

### 4.2 ファインチューニングバッチ

```
1. APScheduler or 手動トリガー
2. extract.py: quality_score >= 0.8 の未使用データ抽出
3. prepare.py: ChatML JSON Lines 変換・分割
4. train.py:   Unsloth LoRA 学習 → GGUF 変換
5. evaluate.py: ROUGE-L 評価 → 合格で Ollama にモデルインポート
6. 失敗時: エラーログ + finetuning/status API でステータス確認
```

---

## 5. 非機能要件

| 項目 | 要件 |
|---|---|
| レスポンスタイム (キャッシュヒット) | < 100ms |
| レスポンスタイム (ローカル LLM) | < 3s (GPU 環境) |
| レスポンスタイム (外部 LLM) | < 10s |
| 可用性 | 外部 LLM 障害時もローカル / キャッシュで継続動作 |
| スケーラビリティ | Docker Compose → Kubernetes 移行可能な設計 |
| マルチテナント | `tenant` フィールドでナレッジを分離 |
| ログ | uvicorn 構造化ログ (INFO レベル) |
| 監視 | Prometheus + Grafana (自動プロビジョニング) |

---

## 6. デプロイ要件

### 6.1 モード別ハードウェアスペック

Docker Compose プロファイルで起動するサービスを切り替えることで、スペックに応じたモードで動作する。  
Ollama・Prometheus・Grafana はオプションであり、なくても基本機能は動作する。

| モード | 起動コマンド | CPU | RAM | GPU VRAM | ストレージ |
|---|---|---|---|---|---|
| **Lite** ★低スペック向け | `make up-lite` | 1 コア以上 | **2 GB 以上** | 不要 | **5 GB 以上** |
| **Standard** | `make up-standard` | 8 コア以上 | 16 GB 以上 | 不要 | 40 GB 以上 |
| **Full** ★推奨 | `make up` | 8 コア以上 | 16 GB 以上 | 8 GB 以上 | 50 GB 以上 |
| **Fine-tuning** | `make up` + 手動実行 | 8 コア以上 | 32 GB 以上 | 16 GB 以上 | 100 GB 以上 |

#### Lite モード — `make up-lite`

**起動サービス: gateway + postgres のみ**  
Ollama を起動しないため、低スペックマシンや VPS でも動作する。

- 外部 LLM (Claude / OpenAI) でチャットを処理
- セマンティックキャッシュの埋め込みは **OpenAI API** (`text-embedding-3-small`, 768 次元) を使用
- ローカル推論・ファインチューニングは利用不可
- CPU: 1 コア以上
- RAM: **2 GB** (FastAPI ~300 MB + PostgreSQL ~500 MB + 余裕分)
- ストレージ: **5 GB** (OS + Docker + PostgreSQL データ。モデルファイル不要)
- GPU: 不要
- 必須: `ANTHROPIC_API_KEY` または `OPENAI_API_KEY` (埋め込み + チャット両方で使用)

#### Standard モード — `make up-standard`

**起動サービス: gateway + postgres + Ollama (CPU 推論)**

- `llama3.1:8b` を CPU で推論。レスポンスタイムは 30〜120 秒程度
- 埋め込みは `nomic-embed-text` (ローカル)
- CPU: 8 コア以上 (コア数が多いほど推論が速い)
- RAM: 16 GB (`llama3.1:8b` CPU で約 8 GB + サービス分)
- ストレージ: 40 GB (`llama3.1:8b` GGUF 約 4.7 GB 含む)
- GPU: 不要

#### Full モード — `make up` ★推奨

**起動サービス: 全サービス (Standard + Prometheus + Grafana)**

- GPU 推論でレスポンスタイム 2〜5 秒
- CPU: 8 コア以上
- RAM: 16 GB 以上
- GPU: NVIDIA GPU、VRAM 8 GB 以上
  - 動作確認済み例: RTX 4060 (8 GB)、RTX 3060 (12 GB)、RTX 4070 (12 GB)
  - `llama3.1:8b` (Q4_K_M 量子化) が約 5 GB VRAM を使用
- ストレージ: 50 GB 以上
- GPU ドライバー: NVIDIA Driver 550 以上 + `nvidia-container-toolkit`

#### Fine-tuning モード

Full モード + Unsloth LoRA 学習を同一マシンで実行する場合。  
推論サーバーとは別マシン (学習専用 GPU サーバー) への分離も可能。

- CPU: 8 コア以上
- RAM: 32 GB 以上
- GPU: NVIDIA GPU、VRAM 16 GB 以上
  - 動作確認済み例: RTX 3090 (24 GB)、RTX 4080 (16 GB)、A100 (40 GB)
  - 4-bit 量子化 + LoRA rank=16 で約 8〜12 GB VRAM 使用
- ストレージ: 100 GB 以上 (学習中間ファイル・チェックポイント・GGUF 出力)

### 6.2 コンポーネント別リソース消費目安

| コンポーネント | CPU | RAM | ストレージ |
|---|---|---|---|
| FastAPI gateway | 0.1〜0.5 コア | 200〜500 MB | — |
| PostgreSQL 16 + pgvector | 0.1〜0.5 コア | 256〜512 MB | 数 MB〜数 GB (データ量に依存) |
| Ollama (サーバープロセス) | 待機時 ≈ 0 | ~500 MB | モデルファイル (下記参照) |
| nomic-embed-text (埋め込み推論) | 0.5〜2 コア | GPU/CPU 共有 | 274 MB |
| llama3.1:8b (CPU 推論) | 全コア | ~8 GB | 4.7 GB |
| llama3.1:8b (GPU 推論) | ≈ 0 | ~500 MB | 4.7 GB (VRAM 5 GB) |
| Prometheus | ≈ 0 | ~200 MB | — |
| Grafana | ≈ 0 | ~200 MB | — |

### 6.3 ストレージ内訳

| 用途 | サイズ目安 |
|---|---|
| OS + Docker ランタイム | 10 GB |
| `nomic-embed-text` モデル | 274 MB |
| `llama3.1:8b` Q4_K_M モデル | 4.7 GB |
| PostgreSQL データ (初期) | 数 MB |
| PostgreSQL データ (Q&A 1 万件蓄積後) | ~500 MB |
| ファインチューニング作業領域 (`/tmp`) | ~20 GB |
| LoRA アダプター + GGUF 出力 | ~5 GB |

### 6.4 ネットワーク要件

| 用途 | 方向 | 要件 |
|---|---|---|
| 初回モデルダウンロード | アウトバウンド | Ollama Hub へのアクセス (初回のみ約 5 GB) |
| 外部 LLM API | アウトバウンド | `api.anthropic.com` / `api.openai.com` |
| クライアントアプリ → ゲートウェイ | インバウンド | TCP 8080 |
| Grafana 管理画面 | インバウンド | TCP 3000 (任意・社内のみ推奨) |
| Prometheus | インバウンド | TCP 9090 (任意・社内のみ推奨) |
| Ollama (コンテナ間) | 内部のみ | TCP 11434 (外部公開不要) |
| PostgreSQL (コンテナ間) | 内部のみ | TCP 5432 (外部公開不要) |

---

## 7. 技術スタック

| 層 | 技術 |
|---|---|
| API Gateway | Python 3.12 + FastAPI + uvicorn |
| セマンティックキャッシュ | PostgreSQL 16 + pgvector + asyncpg |
| ベクトル埋め込み | nomic-embed-text (Ollama) |
| ローカル LLM | Ollama + llama3.1:8b |
| ファインチューニング | Unsloth + LoRA (GPU 環境のみ) |
| 外部 LLM | anthropic SDK / openai SDK / google-genai SDK |
| スケジューラー | APScheduler (FastAPI lifespan 内) |
| コンテナ | Docker Compose |
| 監視 | Prometheus + Grafana (ダッシュボード自動設定) |

---

## 8. ディレクトリ構成

```
docker_ai_gateway/
├── Makefile                            make up / down / logs / clean
├── .gitignore
├── platform/
│   ├── docker-compose.yml              全サービス定義 (gateway/postgres/ollama/prometheus/grafana)
│   ├── Dockerfile                      ビルドコンテキスト = リポジトリルート
│   ├── entrypoint.sh                   Ollama モデル pull → migration → uvicorn
│   ├── .env.example                    環境変数テンプレート (git 管理)
│   ├── prometheus.yml
│   └── grafana/
│       ├── provisioning/datasources/   Prometheus データソース自動設定
│       ├── provisioning/dashboards/
│       └── dashboards/ai_gateway.json  AI Gateway ダッシュボード
└── app/
    ├── gateway/
    │   ├── main.py                     FastAPI アプリ・lifespan・スケジューラー
    │   ├── config.py                   config.yaml + 環境変数読み込み
    │   ├── db.py                       asyncpg pool (pgvector 登録)
    │   ├── auth.py                     Bearer トークン認証
    │   ├── metrics.py                  Prometheus メトリクス定義
    │   ├── api/
    │   │   ├── completions.py          POST /v1/chat/completions
    │   │   ├── embeddings.py           POST /v1/embeddings
    │   │   └── admin.py               /v1/admin/* 管理エンドポイント
    │   ├── cache/
    │   │   ├── embedder.py             テキスト → ベクトル (Ollama / OpenAI)
    │   │   └── semantic.py             pgvector 検索・保存
    │   ├── connectors/
    │   │   ├── base.py                 BaseLLMConnector 抽象クラス
    │   │   ├── anthropic.py            Claude
    │   │   ├── openai_connector.py     OpenAI
    │   │   ├── gemini.py               Google Gemini
    │   │   └── ollama.py               ローカル LLM
    │   ├── router/
    │   │   └── llm_router.py           信頼スコア計算・ルーティング判定
    │   └── knowledge/
    │       └── store.py                Q&A 保存・エクスポート・統計
    ├── finetuning/
    │   ├── extract.py                  データ抽出
    │   ├── prepare.py                  ChatML 変換・train/eval 分割
    │   ├── train.py                    Unsloth LoRA 学習 (GPU 必須)
    │   └── evaluate.py                 ROUGE-L 評価 + Ollama インポート
    ├── migrations/
    │   ├── env.py
    │   └── versions/001_initial_schema.py
    ├── alembic.ini
    ├── config.yaml                     ゲートウェイ設定ファイル
    └── requirements.txt
```

---

## 9. 設定ファイル (`app/config.yaml`)

```yaml
gateway:
  host: 0.0.0.0
  port: 8080
  api_key: ${GATEWAY_API_KEY}

cache:
  similarity_threshold: 0.92
  default_ttl_hours: null    # null = 無期限

router:
  local_confidence_threshold: 0.85
  fallback_to_external: true

llm:
  default_provider: claude
  providers:
    claude:
      model: claude-sonnet-4-6
      api_key: ${ANTHROPIC_API_KEY}
    openai:
      model: gpt-4o-mini
      api_key: ${OPENAI_API_KEY}
    ollama:
      model: llama3.1:8b
      base_url: ${OLLAMA_BASE_URL}
    gemini:
      model: gemini-2.0-flash
      api_key: ${GOOGLE_API_KEY}

finetuning:
  schedule: "0 2 * * 0"     # 毎週日曜 2:00 AM
  min_samples: 500
  quality_threshold: 0.8
  lora_rank: 16
```

環境変数 (`platform/.env`) で `${...}` を上書き。

---

## 10. 将来拡張

### 10.1 役割の見直し（2026-11）の内容

**背景**

- 中継する要求には、利用者ごとに違う内容（名前・予定・注文・家計など）が入る。外部の LLM の答えを、意味の近い別の質問に使い回すと、ほかの利用者やテナントの内容を返すおそれがある。以前の検索は、`tenant` が空の要求では全テナントを対象にしていた。
- Knowledge Store は、外部の LLM の答えも含めてすべての質問と答えを残していた。ファインチューニングをしない環境では、残す理由がない。
- 小さなサーバーでは、Ollama（16GB）とファインチューニング（GPU）は動かせない。
- 認証なしのステータスページ（`/`・`/stats`）は、件数・プロバイダーの一覧・分野別の件数を誰にでも見せていた。

**変えたこと**（`app/config.yaml`）

| 設定 | 既定 | 内容 |
|---|---|---|
| `cache.enabled` | `true` | キャッシュを使うか（環境変数 `GATEWAY_CACHE_ENABLED`） |
| `cache.local_only` | `true` | ローカルモデルの答えだけをキャッシュするか。`false` で外部の LLM の答えも（環境変数 `GATEWAY_CACHE_LOCAL_ONLY`）。どちらでも `app` と `tenant` が両方ある要求だけ |
| `knowledge.enabled` | `false` | 質問と答えを貯めるか。`true` にしても、`knowledge.local_only: true`（既定）ならローカルモデルの答えだけ |
| `status.public` | `false` | 認証なしのステータスページを出すか。`false` なら `/` と `/stats` は 404 |

**これから足すもの**（計画）

| 項目 | 内容 |
|---|---|
| Anthropic の形の中継 | `POST /v1/messages` をそのまま Anthropic に中継する。アプリは Anthropic の SDK のまま、ツールの利用・構造化出力を使える（OpenAI の形への変換では機能が落ちるため） |
| アプリごとのキー | `GATEWAY_API_KEY` 1 つではなく、アプリごとにキーを発行する。キーごとに使えるモデル・月の上限（トークン・金額）を持ち、超えたら 429 |
| 利用ログ | キー・モデル・トークン数・所要時間・結果だけを残す（本文は残さない） |
| 個人情報の伏せ字 | 外部の LLM へ送る前に、電話番号・メールアドレスなどの形の文字を伏せる（任意） |
| MCP の入口 | 各アプリの MCP サーバー（`/mcp`）を設定ファイルで束ね、1 つの MCP サーバーとして見せる。ツール名にアプリの接頭辞（`<app>.`）を付ける。認可は各アプリと同じ認証サーバー（OAuth 2.1）のアクセストークンで行い、アプリへはトークンを中継せず、アプリごとの対象（audience）のトークンに取り替える。アプリ固有の内容（ツールの定義）はこのリポジトリに置かず、各アプリのリポジトリに置く。束ねるアプリの一覧（URL・名前）は git 管理外の設定ファイルに置く。**ツールの一覧は認証した利用者にだけ返し、その利用者のトークンでつながったアプリのツールだけを入れる**（連携していないアプリ・非公開のアプリの名前やツールを、ほかの人に見せない）。認証なしで入口の一覧や束ねたアプリを返す口は作らない |

**メモリの見込み**：ゲートウェイ（FastAPI）と小さな PostgreSQL だけで数百 MB。Ollama・Prometheus・Grafana は載せない。

### 10.2 そのほかの将来拡張

| 拡張 | 概要 |
|---|---|
| 品質スコア自動評価 | 外部 LLM で応答品質を 0〜1 スコアリング後 knowledge_entries に反映 |
| 重複排除 | 保存時にコサイン類似度 > 0.95 の既存エントリをスキップ |
| マルチテナントナレッジ分離 | テナント別にモデルを育てる |
| ヒューマンフィードバック (RLHF) | 応答に評価ボタンを付け quality_score に反映 |
| ドメイン別ルーティング | 在庫クエリ → 在庫特化モデル、HR クエリ → HR モデル |
| A/B テスト | local vs external の応答品質を自動比較 |
| Kubernetes 対応 | ゲートウェイ水平スケール + GPU ノード分離 |
