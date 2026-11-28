from __future__ import annotations

import httpx

from gateway.config import settings

# DB スキーマ (vector(768)) に合わせた統一次元数
_VECTOR_DIM = 768


async def embed(text: str) -> list[float]:
    """
    テキストをベクトル化する。
    優先順: Ollama nomic-embed-text → OpenAI text-embedding-3-small (dimensions=768)
    いずれも利用できない場合は RuntimeError。
    """
    try:
        return await _ollama_embed(text)
    except Exception:
        pass

    openai_cfg = settings.llm.providers.get("openai")
    if openai_cfg and openai_cfg.api_key:
        return await _openai_embed(text)

    raise RuntimeError(
        "No embedding provider available. "
        "Start Ollama (make up-standard) or set OPENAI_API_KEY."
    )


async def embed_local(text: str) -> list[float]:
    """ローカル（Ollama）だけでベクトル化する。キャッシュの検索・保存はこちらを使い、外部には送らない。"""
    return await _ollama_embed(text)


async def is_available() -> bool:
    """埋め込みプロバイダーが 1 つ以上利用可能かどうかを確認する。"""
    try:
        await _ollama_embed("test")
        return True
    except Exception:
        pass
    openai_cfg = settings.llm.providers.get("openai")
    return bool(openai_cfg and openai_cfg.api_key)


async def _ollama_embed(text: str) -> list[float]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        resp = await client.post(
            f"{settings.ollama_base_url}/api/embed",
            json={"model": "nomic-embed-text", "input": text},
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings = data.get("embeddings") or [data.get("embedding")]
        return embeddings[0]


async def _openai_embed(text: str) -> list[float]:
    from openai import AsyncOpenAI

    provider = settings.llm.providers.get("openai")
    client = AsyncOpenAI(api_key=provider.api_key if provider else "")
    resp = await client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
        dimensions=_VECTOR_DIM,  # DB の vector(768) に合わせる
    )
    return resp.data[0].embedding
