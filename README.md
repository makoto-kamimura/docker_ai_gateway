# AI Gateway（docker_ai_gateway）

> **使うほど、手元で答えられるように。**

OpenAI 互換の自己学習型 LLM プロキシ。リクエストを Claude / OpenAI / Ollama に振り分けながら Q&A を蓄積し、ローカルモデルを自動ファインチューニングしていきます。

```
クライアント
    │  OpenAI 互換 API
    ▼
AI Gateway (FastAPI)
    ├── セマンティックキャッシュ (pgvector) ── キャッシュヒット → 即返却
    ├── Router (信頼スコア判定)
    │       ├── score 高 → Ollama (ローカル LLM)
    │       └── score 低 → Claude / OpenAI (外部)
    └── Knowledge Store (Q&A 蓄積 → 週次ファインチューニング)
```

## コンセプト

アプリごとに外部の LLM の API を呼ぶと、似た質問にも毎回料金を払うことになり、やり取りの中身は外に出たまま、手元には何も残りません。

AI Gateway は、**問い合わせを1か所で中継し、答えを蓄積してローカルのモデルに学ばせる**ことで、使うほど外部への依存を減らします。

| 考え方 | 内容 |
|---|---|
| 差し替えは、URL だけ | OpenAI 互換の API なので、既存のアプリはベース URL を変えるだけで使える |
| 似た質問には、手元で答える | 似た質問はセマンティックキャッシュから返し、外部に問い合わせない |
| 任せられるものは、ローカルへ | 信頼スコアの高い問い合わせはローカルの LLM（Ollama）に、低いものは Claude / OpenAI / Gemini に振り分ける |
| 使うほど、賢くなる | 蓄積した Q&A で、ローカルのモデルを毎週ファインチューニングする |
| 小さく始められる | API キーだけで RAM 2GB から動き、ローカル LLM や監視はあとから足せる |

| 項目 | 内容 |
|---|---|
| ステータス | **試作**（中継・セマンティックキャッシュ・振り分け・Q&A の蓄積・ファインチューニングの処理を実装済み。自動テストはキャッシュの判定とその周りだけ。2026-11 に役割を見直した（下記）） |
| 作成者 | **Makoto Kamimura** — [@makoto-kamimura](https://github.com/makoto-kamimura) |
| ライセンス | [MIT](LICENSE) |

## 役割の見直し（2026-11）

小さなサーバーで複数のアプリから使うにあたり、次のように改めました（詳細は [設計仕様 1.1 節・10.1 節](docs/design.md#11-役割の見直し2026-11)）。

- **セマンティックキャッシュは、既定ではローカルモデル（Ollama）が答える要求だけ**で使います。設定の 2 つのスイッチで切り替えられます（[設計仕様 3.2 節](docs/design.md#32-semantic-cache)）。
  - `cache.enabled`（環境変数 `GATEWAY_CACHE_ENABLED`）：キャッシュを使うか。既定は `true`。
  - `cache.local_only`（環境変数 `GATEWAY_CACHE_LOCAL_ONLY`）：ローカルモデルの答えだけに限るか。既定は `true`。`false` にすると外部の LLM の答えもキャッシュします。
  - どちらの場合も、検索と保存は `metadata.app` と `metadata.tenant` が両方一致する範囲に限ります。要求ごとに止めるときは `metadata` に `"cache": false` を付けます。
- テストは `make test`（`app/tests/`。DB・LLM には触れません）。
- **Knowledge Store（質問と答えの蓄積）は既定で止めます**（`knowledge.enabled: false`）。
- **認証なしのステータスページは既定で出しません**（`status.public: false`）。
- 中心の役割は「アプリから LLM への共通の経路」（アプリごとのキー・上限・利用ログ）と「MCP の入口」（計画）です。

## クイックスタート

```bash
git clone <repo-url>
cd docker_ai_gateway

make setup          # platform/.env を生成
vim platform/.env   # API キーを設定

make up-lite        # 起動
```

`app/config.yaml` で `status.public: true` にすると、ブラウザで `http://localhost:8080/` を開いて利用方法と蓄積データを確認できます（既定は非公開）。

## 起動モード

| コマンド | 起動サービス | 最低 RAM | 用途 |
|---|---|---|---|
| `make up-lite` | gateway + postgres | **2 GB** | API キーのみで動作。VPS / 低スペック環境 |
| `make up-standard` | + Ollama | 16 GB | ローカル LLM 推論あり |
| `make up` | + Prometheus + Grafana | 16 GB | フル監視スタック |

## セットアップ

### 1. `.env` を設定

```bash
make setup
vim platform/.env
```

```env
# どちらか一方でも可
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

GATEWAY_API_KEY=your-secure-random-key   # 必須: 認証トークン
POSTGRES_PASSWORD=gateway
```

> **Ollama のみで無料運用する場合** は `app/config.yaml` の `llm.default_provider` を `ollama` に変更し `make up-standard` で起動。API キー不要ですが RAM 16GB 以上が必要です。

### 2. 起動

```bash
make up-lite        # 低スペック環境
# make up-standard  # Ollama あり
# make up           # フル構成
```

初回は Docker イメージのビルドがあるため数分かかります。  
Ollama モデル (`llama3.1:8b` 約 4.7 GB) は初回起動時に自動ダウンロードされます。

## 使い方

ベース URL を差し替えるだけで既存アプリから接続できます。

```
変更前: https://api.openai.com
変更後: http://localhost:8080
```

**curl:**
```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer <GATEWAY_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"model": "auto", "messages": [{"role": "user", "content": "在庫は何個ありますか？"}]}'
```

**Python (OpenAI SDK):**
```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8080/v1", api_key="<GATEWAY_API_KEY>")
response = client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "在庫は何個ありますか？"}],
)
print(response.choices[0].message.content)
```

レスポンスの `metadata.source` で応答元を確認できます: `cache` / `local` / `external`

## ステータスページ (認証不要。`status.public: true` のときだけ)

```
http://localhost:8080/
```

蓄積 Q&A 件数・キャッシュ統計・ドメイン別内訳・利用方法コード例を表示します。30 秒ごとに自動更新。

## 主要コマンド

```bash
make up-lite      # 起動 (Lite)
make up-standard  # 起動 (Standard)
make up           # 起動 (Full)
make down         # 停止
make build        # イメージ再ビルド
make logs         # gateway ログを tail
make ps           # サービス一覧
make clean        # 全コンテナ・ボリュームを削除 (データも消える)
```

## アーキテクチャ

| コンポーネント | 技術 |
|---|---|
| Gateway | FastAPI (Python 3.12) + uvicorn |
| セマンティックキャッシュ | PostgreSQL + pgvector (cosine similarity) |
| 埋め込みモデル | nomic-embed-text (Ollama) / text-embedding-3-small (OpenAI) |
| ローカル LLM | Ollama (llama3.1:8b) |
| ファインチューニング | Unsloth + LoRA (GPU 必須) |
| スケジューラ | APScheduler (週次 cron) |
| 監視 | Prometheus + Grafana |

## ファインチューニング

蓄積した Q&A データを使い、毎週日曜 2:00 AM に自動実行されます。

```bash
# 手動実行
curl -X POST http://localhost:8080/v1/admin/finetuning/trigger \
  -H "Authorization: Bearer <GATEWAY_API_KEY>"

# 進捗確認
curl http://localhost:8080/v1/admin/finetuning/status \
  -H "Authorization: Bearer <GATEWAY_API_KEY>"
```

> GPU なし環境では学習ステップ (Step 3/4) がスキップされます。データ抽出・変換 (Step 1-2) は CPU でも動作します。

## ドキュメント

- [設計仕様](docs/design.md) — アーキテクチャ・スペック要件・ルーティングロジック
- [運用マニュアル](docs/operation.md) — 詳細セットアップ・管理 API・トラブルシューティング
- [コスト比較](docs/cost.md) — プロバイダー別料金・推奨構成・コスト削減のポイント

## スペック要件

| モード | RAM | ストレージ | GPU |
|---|---|---|---|
| Lite (`make up-lite`) | 2 GB | 5 GB | 不要 |
| Standard (`make up-standard`) | 16 GB | 40 GB | 不要 (推奨) |
| Full (`make up`) | 16 GB | 50 GB | 推奨 |
| ファインチューニング | 32 GB | 50 GB | 必須 (16 GB VRAM) |
