# AI Gateway

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

## クイックスタート

```bash
git clone <repo-url>
cd docker_ai_gateway

make setup          # platform/.env を生成
vim platform/.env   # API キーを設定

make up-lite        # 起動
```

ブラウザで `http://localhost:8080/` を開くと利用方法と蓄積データが確認できます。

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

## ステータスページ (認証不要)

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
- [タスク](docs/task.md) — 実装済み機能・残タスク一覧
- [コスト比較](docs/cost.md) — プロバイダー別料金・推奨構成・コスト削減のポイント

## スペック要件

| モード | RAM | ストレージ | GPU |
|---|---|---|---|
| Lite (`make up-lite`) | 2 GB | 5 GB | 不要 |
| Standard (`make up-standard`) | 16 GB | 40 GB | 不要 (推奨) |
| Full (`make up`) | 16 GB | 50 GB | 推奨 |
| ファインチューニング | 32 GB | 50 GB | 必須 (16 GB VRAM) |
