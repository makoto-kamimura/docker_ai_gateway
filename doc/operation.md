# AI Gateway — 運用マニュアル

設計仕様: [design.md](./design.md) | タスク: [task.md](./task.md)

---

## 1. 前提条件

| 項目 | 要件 |
|---|---|
| OS | Linux / macOS (Docker が動けば可) |
| Docker | 24.x 以上 + Docker Compose v2 (`docker compose` コマンド) |
| GPU | NVIDIA GPU 推奨 (CPU のみでも動作可。ファインチューニングは GPU 必須) |
| 外部 API キー | Anthropic または OpenAI のいずれか一方でも可 |

---

## 2. 初期セットアップ (初回のみ)

### スペックに応じたモード選択

| コマンド | 起動サービス | RAM | 必要なキー |
|---|---|---|---|
| `make up-lite` | gateway + postgres のみ | **2 GB** | OPENAI_API_KEY (埋め込み + チャット) |
| `make up-standard` | + Ollama (ローカル LLM) | 16 GB | ANTHROPIC_API_KEY or OPENAI_API_KEY |
| `make up` | 全サービス (+ 監視) | 16 GB | ANTHROPIC_API_KEY or OPENAI_API_KEY |

### 手順

```bash
git clone <repo-url>
cd docker_ai_gateway

make setup              # platform/.env を自動生成
vim platform/.env       # API キーを設定

# スペックに合ったコマンドで起動
make up-lite            # 低スペック環境 (2GB RAM, VPS 等)
# make up-standard      # ローカル LLM あり (16GB RAM)
# make up               # フル構成 + 監視 (GPU 推奨)
```

`platform/.env` の最低限の設定:

```env
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx   # Claude 利用時
OPENAI_API_KEY=sk-xxxxxxxxxxxx          # OpenAI 利用時 (Lite モードでは必須)
GATEWAY_API_KEY=your-secure-random-key  # ゲートウェイ認証トークン
POSTGRES_PASSWORD=gateway               # DB パスワード
```

### 起動時に自動実行される処理

**Lite モード** (`make up-lite`):
1. PostgreSQL の起動待機
2. Alembic マイグレーション実行
3. FastAPI 起動 (Ollama なし。起動は 30 秒以内)

**Standard / Full モード**:
1. PostgreSQL の起動待機
2. Ollama の接続確認 → `nomic-embed-text` / `llama3.1:8b` の自動ダウンロード (未取得時のみ)
3. Alembic マイグレーション実行
4. FastAPI 起動

初回の Ollama モデルダウンロードは数分〜十数分かかります (llama3.1:8b 約 4.7 GB)。

### ヘルスチェック

```bash
curl http://localhost:8080/health
# → {"status": "ok", "version": "0.1.0"}
```

---

## 3. 日常操作 (Makefile)

```bash
make up-lite      # 起動: Lite モード (低スペック)
make up-standard  # 起動: Standard モード (ローカル LLM)
make up           # 起動: Full モード (ローカル LLM + 監視)
make down         # 全サービスを停止
make build        # イメージを再ビルド (コード変更後)
make logs         # gateway のログを tail
make ps           # サービス一覧と状態確認
make clean        # 全コンテナ・ボリュームを削除 (データも消える)
```

ログ全サービス表示:
```bash
docker compose -f platform/docker-compose.yml logs -f
```

---

## 4. ステータスページ (認証不要)

ブラウザで以下を開くと、誰でも利用方法と蓄積データを確認できます。

```
http://localhost:8080/
```

表示内容:
- **蓄積 Q&A 件数** / キャッシュ件数 / ヒット数 (30 秒ごとに自動更新)
- **ドメイン別 Q&A 蓄積件数** (在庫 / HR / 汎用)
- **利用方法** (curl / Python / JavaScript のコード例)
- Ollama の稼働状態

統計のみ JSON で取得する場合:

```bash
curl http://localhost:8080/stats
```

---

## 5. API 利用方法

### ベース URL 差し替え (ドロップイン置換)

```
変更前: https://api.openai.com
変更後: http://localhost:8080
```

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer your-secure-random-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "auto",
    "messages": [
      {"role": "user", "content": "在庫は何個ありますか？"}
    ]
  }'
```

### metadata でアプリ・テナントを識別

```json
{
  "model": "auto",
  "messages": [{"role": "user", "content": "..."}],
  "metadata": {
    "app": "alexa-inventory",
    "tenant": "warehouse-a"
  }
}
```

### レスポンスの `metadata.source` の意味

| source | 意味 |
|---|---|
| `cache` | セマンティックキャッシュからヒット (最速、外部 API コストゼロ) |
| `local` | ローカル LLM (Ollama) が応答 |
| `external` | 外部 LLM (Claude / OpenAI) が応答 |

### ストリーミング

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer your-secure-random-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "auto", "messages": [...], "stream": true}'
```

### モデル指定

| model 値 | 動作 |
|---|---|
| `auto` | Router が自動判定して local / external を選択 |
| `claude` | Claude (Anthropic) を強制指定 |
| `openai` | OpenAI を強制指定 |
| `ollama` | ローカル LLM を強制指定 |

### 利用可能モデル一覧

```bash
curl http://localhost:8080/v1/models \
  -H "Authorization: Bearer your-secure-random-key"
```

---

## 6. 管理 API

全エンドポイントに `Authorization: Bearer <key>` が必要。

| エンドポイント | 内容 |
|---|---|
| `GET /v1/admin/cache/stats` | キャッシュ統計 (件数・ヒット数) |
| `DELETE /v1/admin/cache` | キャッシュ全件クリア |
| `GET /v1/admin/knowledge/stats` | ナレッジ統計 (件数・平均品質スコア・FT 待機数) |
| `POST /v1/admin/knowledge/export` | 学習データを JSON 形式でエクスポート |
| `POST /v1/admin/finetuning/trigger` | ファインチューニングを手動実行 |
| `GET /v1/admin/finetuning/status` | 実行状況確認 |

```bash
# ナレッジ統計の例
curl http://localhost:8080/v1/admin/knowledge/stats \
  -H "Authorization: Bearer your-secure-random-key"
# → {"total_entries": 1234, "avg_quality_score": 0.85, "pending_finetuning": 234}
```

---

## 7. 監視

### Prometheus メトリクス

```bash
curl http://localhost:8080/metrics
```

主要メトリクス:

| メトリクス名 | 内容 |
|---|---|
| `gateway_requests_total{source}` | リクエスト数 (cache / local / external) |
| `gateway_request_duration_seconds{source}` | レイテンシヒストグラム |
| `gateway_cache_hit_ratio` | キャッシュヒット率 |
| `gateway_knowledge_entries_total` | Knowledge Store 蓄積件数 |
| `gateway_external_tokens_total{provider}` | 外部 LLM 消費トークン数 |
| `gateway_finetuning_runs_total{status}` | ファインチューニング実行回数 |
| `gateway_local_model_accuracy` | ローカル LLM 精度スコア推移 |

### Grafana ダッシュボード

```
http://localhost:3000
```

認証: `admin / admin` (初回ログイン後に変更推奨)

Prometheus データソースとダッシュボードは起動時に自動設定されます。

---

## 8. ファインチューニング

### 自動実行スケジュール

デフォルト: 毎週日曜 2:00 AM (`config.yaml` の `finetuning.schedule` で変更可)

自動実行の条件:
- `quality_score >= 0.8` の未使用データが `min_samples` (デフォルト 500) 件以上

### 手動実行

```bash
curl -X POST http://localhost:8080/v1/admin/finetuning/trigger \
  -H "Authorization: Bearer your-secure-random-key"
```

### 進捗確認

```bash
curl http://localhost:8080/v1/admin/finetuning/status \
  -H "Authorization: Bearer your-secure-random-key"
# → {"status": "running", "progress": "2/4 (prepare)", "started_at": "...", "error": null}
```

### 実行フロー

```
Step 1/4 (extract)  — knowledge_entries から Q&A 抽出 → /tmp/ft_raw.jsonl
Step 2/4 (prepare)  — ChatML 形式変換 + 80/20 分割 → /tmp/ft_train.jsonl / ft_eval.jsonl
Step 3/4 (train)    — Unsloth + LoRA 学習 → /tmp/ft_model/*.gguf (GPU 必須)
Step 4/4 (evaluate) — ROUGE-L 評価 → 合格時 Ollama に 'ai-gateway-custom' としてインポート
```

> **GPU なし環境**: Step 3 で `unsloth not installed` エラーになりステータスが `failed` になります。  
> Step 1〜2 のデータ抽出・変換は CPU でも動作します。

---

## 9. 設定変更

`app/config.yaml` を編集後にゲートウェイを再起動:

```bash
# config.yaml を編集してから
make down && make up
# または gateway だけ再起動
docker compose -f platform/docker-compose.yml restart gateway
```

### 主要設定項目

| 設定キー | デフォルト | 内容 |
|---|---|---|
| `cache.similarity_threshold` | `0.92` | キャッシュヒット判定の類似度閾値 (下げると積極的にキャッシュ利用) |
| `router.local_confidence_threshold` | `0.85` | ローカル LLM に回す信頼スコア下限 |
| `router.fallback_to_external` | `true` | ローカル LLM 失敗時に外部 LLM へフォールバック |
| `llm.default_provider` | `claude` | デフォルトの外部 LLM プロバイダー |
| `finetuning.schedule` | `0 2 * * 0` | ファインチューニング実行スケジュール (cron 式) |
| `finetuning.min_samples` | `500` | 自動実行に必要な最低データ件数 |
| `finetuning.quality_threshold` | `0.8` | 学習データに使う品質スコア下限 |

---

## 10. 既存アプリの統合手順

1. アプリの環境変数に以下を追加:
   ```env
   AI_GATEWAY_URL=http://ai-gateway:8080
   AI_GATEWAY_KEY=your-secure-random-key
   ```

2. API 呼び出しのベース URL を差し替え:
   ```javascript
   // 変更前
   baseURL: "https://api.openai.com"
   // 変更後
   baseURL: process.env.AI_GATEWAY_URL
   apiKey: process.env.AI_GATEWAY_KEY
   ```

3. `platform/docker-compose.yml` に対象アプリを追加してネットワーク共有:
   ```yaml
   services:
     your-app:
       networks:
         - ai-gateway-net
   ```

4. リクエストに `metadata.app` / `metadata.tenant` を付与 (任意):
   ```json
   {"model": "auto", "messages": [...], "metadata": {"app": "my-app", "tenant": "team-a"}}
   ```

---

## 11. トラブルシューティング

### ゲートウェイが起動しない

```bash
make logs
```

よくある原因と対処:

| 症状 | 原因 | 対処 |
|---|---|---|
| `GATEWAY_API_KEY が空` | .env 未設定 | `vim platform/.env` で設定 |
| DB 接続エラー | postgres 未起動 | `make ps` で確認後 `make up` |
| `vector type not found` | pgvector 拡張未作成 | マイグレーションが正常に動くはず; `make logs` でマイグレーションログを確認 |

### Ollama モデルのダウンロードが終わらない

- 初回は `nomic-embed-text` (約 274MB) + `llama3.1:8b` (約 4.7GB) をダウンロード
- `make logs` で進捗を確認
- 手動確認: `docker exec <ollama-container-id> ollama list`

### キャッシュが効かない

- 類似度閾値が高すぎる → `app/config.yaml` の `cache.similarity_threshold` を `0.88` に下げる
- 埋め込みモデルが未取得 → `make logs` で `nomic-embed-text` の pull ログを確認

### ローカル LLM が遅い / タイムアウト

- GPU が認識されているか確認:
  ```bash
  docker compose -f platform/docker-compose.yml exec ollama nvidia-smi
  ```
- CPU のみの場合: `router.local_confidence_threshold` を `0.99` に上げて外部 LLM 優先にする

### ファインチューニングが失敗する

- GPU なし環境: `unsloth not installed` エラーは正常 (CPU では学習不可)
- データ不足: `knowledge/stats` を確認し `finetuning.min_samples` を一時的に小さくして手動実行
- GPU メモリ不足: `app/config.yaml` の `finetuning.lora_rank` を `8` に下げる

---

## 12. 日常メンテナンス

### キャッシュクリア (古いエントリの手動削除)

```bash
curl -X DELETE http://localhost:8080/v1/admin/cache \
  -H "Authorization: Bearer your-secure-random-key"
```

### DB バックアップ

```bash
docker compose -f platform/docker-compose.yml exec postgres \
  pg_dump -U gateway ai_gateway > backup_$(date +%Y%m%d).sql
```

### Docker イメージ更新 (コード変更後)

```bash
make build
make up
```

### Ollama モデル一覧確認

```bash
docker compose -f platform/docker-compose.yml exec ollama ollama list
```
