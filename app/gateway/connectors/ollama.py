from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from gateway.connectors.base import BaseLLMConnector, ChatResponse, Message


class OllamaConnector(BaseLLMConnector):
    def __init__(self, base_url: str, model: str = "llama3.1:8b") -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = httpx.Timeout(60.0)

    def _to_ollama(self, messages: list[Message]) -> list[dict]:
        return [{"role": m.role, "content": m.content} for m in messages]

    async def chat(self, messages: list[Message], **kwargs) -> ChatResponse:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": self._to_ollama(messages),
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return ChatResponse(
                content=data["message"]["content"],
                prompt_tokens=data.get("prompt_eval_count", 0),
                completion_tokens=data.get("eval_count", 0),
                model=self._model,
            )

    async def chat_stream(
        self, messages: list[Message], **kwargs
    ) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": self._to_ollama(messages),
                    "stream": True,
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line:
                        chunk = json.loads(line)
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content

    async def is_model_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                tags = resp.json().get("models", [])
                return any(t["name"].startswith(self._model) for t in tags)
        except Exception:
            return False
