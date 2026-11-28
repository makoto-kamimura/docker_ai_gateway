from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel


class CacheConfig(BaseModel):
    # セマンティックキャッシュ。設定ファイル（cache:）か環境変数（GATEWAY_CACHE_*）で切り替える。
    # enabled: キャッシュを使うか（既定 true。環境変数 GATEWAY_CACHE_ENABLED）
    enabled: bool = True
    # local_only: ローカルモデル（Ollama）の答えだけをキャッシュするか（既定 true。環境変数 GATEWAY_CACHE_LOCAL_ONLY）。
    #   false にすると、外部の LLM の答えもキャッシュする（利用者ごとに内容が違う答えを使い回さないよう、
    #   検索・保存は、要求の metadata の app と tenant が両方とも一致する範囲に限るのは同じ）。
    # どちらの場合も、埋め込みはローカル（nomic-embed-text）だけで作り、外部には送らない。
    # 要求ごとに止めるときは、metadata に "cache": false を付ける。
    local_only: bool = True
    similarity_threshold: float = 0.92
    default_ttl_hours: Optional[int] = None


class KnowledgeConfig(BaseModel):
    # 質問と答えを knowledge_entries に貯める（ファインチューニングの材料）。
    # 外部の LLM の答えも含めて残るため、既定では止める。ローカルモデルを育てるときだけ有効にする
    enabled: bool = False
    # true のときも、ローカルモデルの答えだけを貯める
    local_only: bool = True


class StatusConfig(BaseModel):
    # 認証なしのステータスページ（GET /・GET /stats）を出すか。件数・プロバイダーの一覧が見えるため、既定では出さない
    public: bool = False


class RouterConfig(BaseModel):
    local_confidence_threshold: float = 0.85
    fallback_to_external: bool = True


class ProviderConfig(BaseModel):
    model: str = ""
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class LLMConfig(BaseModel):
    default_provider: str = "claude"
    providers: dict[str, ProviderConfig] = {}


class FinetuningConfig(BaseModel):
    schedule: str = "0 2 * * 0"
    min_samples: int = 500
    quality_threshold: float = 0.8
    lora_rank: int = 16


class Settings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    api_key: str = "changeme"
    cache: CacheConfig = CacheConfig()
    router: RouterConfig = RouterConfig()
    llm: LLMConfig = LLMConfig()
    finetuning: FinetuningConfig = FinetuningConfig()
    knowledge: KnowledgeConfig = KnowledgeConfig()
    status: StatusConfig = StatusConfig()
    database_url: str = "postgresql+asyncpg://gateway:gateway@postgres:5432/ai_gateway"
    alembic_database_url: str = "postgresql://gateway:gateway@postgres:5432/ai_gateway"
    ollama_base_url: str = "http://ollama:11434"


def _resolve(value: object) -> object:
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        key = value[2:-1]
        return os.environ.get(key, "")
    if isinstance(value, dict):
        return {k: _resolve(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v) for v in value]
    return value


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _env_bool(name: str) -> Optional[bool]:
    """環境変数を真偽値として読む。未設定・空なら None（設定ファイルの値を使う）。読めない値はエラー。"""
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return None
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise ValueError(f"{name} は true / false で指定してください（値: {raw!r}）")


def _cache_section(section: object) -> dict:
    """cache: の節に、環境変数 GATEWAY_CACHE_ENABLED・GATEWAY_CACHE_LOCAL_ONLY を上書きする。"""
    cache = dict(section) if isinstance(section, dict) else {}
    # 2026-11 の一時期の書き方（mode: local_only / off）も読む
    mode = cache.pop("mode", None)
    if mode == "off":
        cache.setdefault("enabled", False)
    elif mode == "local_only":
        cache.setdefault("local_only", True)
    for key, env in (("enabled", "GATEWAY_CACHE_ENABLED"), ("local_only", "GATEWAY_CACHE_LOCAL_ONLY")):
        value = _env_bool(env)
        if value is not None:
            cache[key] = value
    return cache


def load_settings() -> Settings:
    for candidate in ("/app/config.yaml", "config.yaml"):
        path = Path(candidate)
        if path.exists():
            with open(path) as f:
                raw = yaml.safe_load(f) or {}
            break
    else:
        raw = {}

    raw = _resolve(raw)

    gateway_section = raw.pop("gateway", {})
    merged: dict = {**gateway_section, **raw}

    # Flatten nested sections
    data: dict = {
        "host": merged.get("host", "0.0.0.0"),
        "port": merged.get("port", 8080),
        "api_key": merged.get("api_key", os.environ.get("GATEWAY_API_KEY", "changeme")),
        "cache": _cache_section(merged.get("cache", {})),
        "router": merged.get("router", {}),
        "llm": merged.get("llm", {}),
        "finetuning": merged.get("finetuning", {}),
        "knowledge": merged.get("knowledge", {}),
        "status": merged.get("status", {}),
        "database_url": os.environ.get("DATABASE_URL", "postgresql+asyncpg://gateway:gateway@postgres:5432/ai_gateway"),
        "alembic_database_url": os.environ.get("ALEMBIC_DATABASE_URL", "postgresql://gateway:gateway@postgres:5432/ai_gateway"),
        "ollama_base_url": os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434"),
    }

    return Settings.model_validate(data)


settings = load_settings()
