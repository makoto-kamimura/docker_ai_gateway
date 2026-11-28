COMPOSE := docker compose -f platform/docker-compose.yml
.DEFAULT_GOAL := help

.PHONY: help setup up up-lite up-standard up-full down build logs ps clean test

help:
	@echo "Usage:"
	@echo "  make setup        .env を作成 (初回のみ)"
	@echo ""
	@echo "  make up-lite      【低スペック】 外部 LLM + キャッシュのみ"
	@echo "                    必要: ANTHROPIC_API_KEY or OPENAI_API_KEY"
	@echo "                    RAM 2GB / ストレージ 5GB で動作"
	@echo ""
	@echo "  make up-standard  【標準】 ローカル LLM 推論あり (CPU/GPU)"
	@echo "                    RAM 16GB / ストレージ 40GB"
	@echo ""
	@echo "  make up           【フル】 標準 + Prometheus + Grafana 監視"
	@echo "                    RAM 16GB / ストレージ 50GB"
	@echo ""
	@echo "  make down         全サービスを停止"
	@echo "  make build        イメージを再ビルド"
	@echo "  make logs         gateway のログを tail"
	@echo "  make ps           サービス一覧を表示"
	@echo "  make clean        全コンテナ・ボリュームを削除"
	@echo "  make test         自動テスト（app/tests。DB・LLM には触れない）"

setup:
	@if [ ! -f platform/.env ]; then \
	  cp platform/.env.example platform/.env; \
	  echo "platform/.env を作成しました。API キーを設定してください:"; \
	  echo "  vim platform/.env"; \
	else \
	  echo "platform/.env はすでに存在します"; \
	fi

# 低スペック: gateway + postgres のみ (Ollama なし、外部 LLM + OpenAI 埋め込みで動作)
up-lite:
	$(COMPOSE) up -d

# 標準: + ローカル LLM (Ollama)
up-standard:
	COMPOSE_PROFILES=local-llm $(COMPOSE) up -d

# フル: + Prometheus + Grafana 監視スタック
up:
	COMPOSE_PROFILES=local-llm,monitoring $(COMPOSE) up -d

down:
	COMPOSE_PROFILES=local-llm,monitoring $(COMPOSE) down

build:
	COMPOSE_PROFILES=local-llm,monitoring $(COMPOSE) build --no-cache

logs:
	$(COMPOSE) logs -f gateway

ps:
	COMPOSE_PROFILES=local-llm,monitoring $(COMPOSE) ps

clean:
	COMPOSE_PROFILES=local-llm,monitoring $(COMPOSE) down -v --remove-orphans

# 自動テスト（DB・Ollama・外部の LLM には触れない）。メモリ上限を付けたコンテナで動かす
test:
	docker run --rm -m 1200m -v $(CURDIR)/app:/app -w /app python:3.12-slim \
	  sh -c 'pip install -q --no-cache-dir --root-user-action=ignore -r requirements-dev.txt && python -m pytest -q'
