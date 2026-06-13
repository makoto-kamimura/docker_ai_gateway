# LLM コスト比較

## プロバイダー別料金（トークン 100 万あたり）

| プロバイダー | モデル | 入力 | 出力 | 必要 RAM |
|---|---|---|---|---|
| **Ollama（ローカル）** | llama3.1:8b | $0 | $0 | 16 GB |
| **OpenAI** | gpt-4o-mini | ~$0.15 | ~$0.60 | 2 GB（API） |
| **Claude** | claude-haiku-4-5 | $1.00 | $5.00 | 2 GB（API） |
| **Claude** | claude-sonnet-4-6 ← デフォルト | $3.00 | $15.00 | 2 GB（API） |
| **Claude** | claude-opus-4-8 | $5.00 | $25.00 | 2 GB（API） |

## 推奨構成

### 完全無料（RAM 16 GB 以上）

```yaml
# app/config.yaml
llm:
  default_provider: ollama
```

```bash
make up-standard
```

### 有料 API で最安（RAM 2 GB、VPS 可）

```yaml
# app/config.yaml
llm:
  default_provider: openai
  providers:
    openai:
      model: gpt-4o-mini
      api_key: ${OPENAI_API_KEY}
```

```bash
make up-lite
```

### Claude だけで最安

```yaml
# app/config.yaml
llm:
  default_provider: claude
  providers:
    claude:
      model: claude-haiku-4-5   # ← sonnet-4-6 から変更
      api_key: ${ANTHROPIC_API_KEY}
```

## セマンティックキャッシュによるコスト削減

類似質問（cosine similarity ≥ 0.92）はキャッシュから即返却されるため、API は呼ばれません。

社内 FAQ や在庫照会のように**繰り返しパターンが多い用途**では、実際の API 呼び出し回数が大幅に減り、実質コストはほぼゼロに近づく可能性があります。

## 起動モードとコストの関係

| コマンド | プロバイダー | 費用 |
|---|---|---|
| `make up-lite` | Claude / OpenAI（API キー必須） | 従量課金 |
| `make up-standard` | Ollama（+ API フォールバック可） | **無料**（Ollama のみ使用時） |
| `make up` | フル構成（Ollama + 監視） | **無料**（Ollama のみ使用時） |
