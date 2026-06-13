from __future__ import annotations

from typing import AsyncIterator

from openai import AsyncOpenAI

from gateway.connectors.base import BaseLLMConnector, ChatResponse, Message


class OpenAIConnector(BaseLLMConnector):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    def _to_oai(self, messages: list[Message]) -> list[dict]:
        return [{"role": m.role, "content": m.content} for m in messages]

    async def chat(self, messages: list[Message], **kwargs) -> ChatResponse:
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=self._to_oai(messages),
            max_tokens=kwargs.get("max_tokens", 4096),
        )
        choice = resp.choices[0]
        return ChatResponse(
            content=choice.message.content or "",
            prompt_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            completion_tokens=resp.usage.completion_tokens if resp.usage else 0,
            model=self._model,
        )

    async def chat_stream(
        self, messages: list[Message], **kwargs
    ) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=self._to_oai(messages),
            max_tokens=kwargs.get("max_tokens", 4096),
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
