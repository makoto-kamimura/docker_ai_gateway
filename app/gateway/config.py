from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel


class CacheConfig(BaseModel):
    similarity_threshold: float = 0.92
    default_ttl_hours: Optional[int] = None


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
        "cache": merged.get("cache", {}),
        "router": merged.get("router", {}),
        "llm": merged.get("llm", {}),
        "finetuning": merged.get("finetuning", {}),
        "database_url": os.environ.get("DATABASE_URL", "postgresql+asyncpg://gateway:gateway@postgres:5432/ai_gateway"),
        "alembic_database_url": os.environ.get("ALEMBIC_DATABASE_URL", "postgresql://gateway:gateway@postgres:5432/ai_gateway"),
        "ollama_base_url": os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434"),
    }

    return Settings.model_validate(data)


settings = load_settings()
