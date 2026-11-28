from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from gateway import metrics
from gateway.auth import verify_token
from gateway.cache import embedder, policy, semantic
from gateway.config import settings
from gateway.connectors.base import ChatResponse, Message
from gateway.knowledge import store

router = APIRouter()


class CompletionRequest(BaseModel):
    model: str = "auto"
    messages: list[dict]
    stream: bool = False
    max_tokens: Optional[int] = None
    metadata: Optional[dict] = None


def _build_connector(provider: str):
    providers = settings.llm.providers
    if provider == "claude":
        from gateway.connectors.anthropic import AnthropicConnector
        cfg = providers.get("claude")
        return AnthropicConnector(api_key=cfg.api_key or "", model=cfg.model)
    if provider == "openai":
        from gateway.connectors.openai_connector import OpenAIConnector
        cfg = providers.get("openai")
        return OpenAIConnector(api_key=cfg.api_key or "", model=cfg.model)
    if provider == "ollama" or provider == "local":
        from gateway.connectors.ollama import OllamaConnector
        cfg = providers.get("ollama")
        return OllamaConnector(
            base_url=cfg.base_url or settings.ollama_base_url,
            model=cfg.model,
        )
    if provider == "gemini":
        from gateway.connectors.gemini import GeminiConnector
        cfg = providers.get("gemini")
        return GeminiConnector(api_key=cfg.api_key or "", model=cfg.model)
    raise ValueError(f"Unknown provider: {provider}")


def _messages_to_model(raw: list[dict]) -> list[Message]:
    return [Message(role=m["role"], content=m["content"]) for m in raw]


def _openai_response(content: str, model: str, source: str, usage: dict) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
        "metadata": {"source": source},
    }


def _sse_chunk(content: str, model: str, finish: bool = False) -> str:
    delta = {} if finish else {"content": content}
    finish_reason = "stop" if finish else None
    data = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_response(
    gen: AsyncIterator[str],
    model: str,
    query_text: str,
    provider: str,
    source: str,
    app: str,
    tenant: str,
) -> AsyncIterator[str]:
    full = []
    async for chunk in gen:
        full.append(chunk)
        yield _sse_chunk(chunk, model)
    yield _sse_chunk("", model, finish=True)
    yield "data: [DONE]\n\n"
    # Knowledge Store は有効なときだけ保存する（ストリーミングの答えはキャッシュしない）
    if _should_store_knowledge(source):
        asyncio.create_task(
            store.save(query_text=query_text, response_text="".join(full), provider=provider, app=app, tenant=tenant)
        )


def _resolve_provider(model: str) -> str:
    """要求の model から使うプロバイダーを決める（auto は既定のプロバイダー。local は Ollama）。"""
    if model in ("local", "ollama"):
        return "ollama"
    if model == "auto":
        return "ollama" if settings.llm.default_provider in ("local", "ollama") else settings.llm.default_provider
    return model


def _should_store_knowledge(source: str) -> bool:
    k = settings.knowledge
    return k.enabled and (source == "local" or not k.local_only)


@router.post("/v1/chat/completions")
async def chat_completions(
    req: CompletionRequest,
    _: str = Depends(verify_token),
):
    messages = _messages_to_model(req.messages)
    query_text = next(
        (m.content for m in reversed(messages) if m.role == "user"), ""
    )
    meta = req.metadata or {}
    app = meta.get("app", "")
    tenant = meta.get("tenant", "")
    opt_out = policy.request_opt_out(meta)

    start = time.time()

    # 1. プロバイダーを決める（以前は、キャッシュの類似度とローカルモデルの精度から自動で振り分けていたが、
    #    キャッシュをローカルモデルの要求だけに限ったため、明示の指定と既定のプロバイダーで決める）
    provider_name = _resolve_provider(req.model)

    # 2. セマンティックキャッシュ（設定の cache.enabled / cache.local_only。埋め込みはローカルだけで作る）
    query_vec: list[float] = []
    if policy.lookup_allowed(settings.cache, provider_name, app, tenant, opt_out):
        try:
            # ローカルモデルの要求は、埋め込みもローカルだけで作る（外部に送らない）。
            # 外部の LLM の要求（local_only: false のときだけ来る）は、質問文をもともと外部に送るため、従来の経路（Ollama → OpenAI）で作る
            embed = embedder.embed_local if provider_name == policy.LOCAL_PROVIDER else embedder.embed
            query_vec = await embed(query_text)
            cached = await semantic.search(query_vec, app=app, tenant=tenant)
        except Exception:
            query_vec = []
            cached = None
        if cached:
            duration = time.time() - start
            metrics.requests_total.labels(source="cache").inc()
            metrics.request_duration.labels(source="cache").observe(duration)
            cached["metadata"] = {"source": "cache"}
            return cached

    connector = _build_connector(provider_name)
    model_label = settings.llm.providers.get(provider_name, {})
    model_str = model_label.model if hasattr(model_label, "model") else provider_name

    kwargs = {}
    if req.max_tokens:
        kwargs["max_tokens"] = req.max_tokens

    source = "local" if provider_name == "ollama" else "external"

    # 3. ストリーミング
    if req.stream:
        try:
            gen = connector.chat_stream(messages, **kwargs)
        except Exception:
            if settings.router.fallback_to_external and provider_name == "ollama":
                provider_name = settings.llm.default_provider if settings.llm.default_provider not in ("local", "ollama") else "claude"
                connector = _build_connector(provider_name)
                gen = connector.chat_stream(messages, **kwargs)
                source = "external"
            else:
                raise

        return StreamingResponse(
            _stream_response(gen, model_str, query_text, provider_name, source, app, tenant),
            media_type="text/event-stream",
            headers={"X-Cache": "MISS", "X-Source": source},
        )

    # 4. 通常レスポンス
    try:
        resp: ChatResponse = await connector.chat(messages, **kwargs)
    except Exception:
        if settings.router.fallback_to_external and provider_name == "ollama":
            provider_name = settings.llm.default_provider if settings.llm.default_provider not in ("local", "ollama") else "claude"
            connector = _build_connector(provider_name)
            resp = await connector.chat(messages, **kwargs)
            source = "external"
        else:
            raise

    duration = time.time() - start
    metrics.requests_total.labels(source=source).inc()
    metrics.request_duration.labels(source=source).observe(duration)
    if source == "external":
        metrics.external_tokens_total.labels(provider=provider_name).inc(
            resp.prompt_tokens + resp.completion_tokens
        )

    usage = {
        "prompt_tokens": resp.prompt_tokens,
        "completion_tokens": resp.completion_tokens,
        "total_tokens": resp.prompt_tokens + resp.completion_tokens,
    }
    body = _openai_response(resp.content, model_str, source, usage)

    # 5. Knowledge Store（有効なときだけ）・キャッシュ（設定で許した答えだけ）に非同期保存
    async def _save():
        if _should_store_knowledge(source):
            await store.save(
                query_text=query_text,
                response_text=resp.content,
                provider=provider_name,
                app=app,
                tenant=tenant,
            )
        if query_vec and policy.store_allowed(settings.cache, source, app, tenant, opt_out):
            await semantic.store(
                query_text=query_text,
                query_vec=query_vec,
                response=body,
                source=source,
                app=app,
                tenant=tenant,
            )

    asyncio.create_task(_save())

    return body
