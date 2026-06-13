from __future__ import annotations

from typing import AsyncIterator

import anthropic

from gateway.connectors.base import BaseLLMConnector, ChatResponse, Message


class AnthropicConnector(BaseLLMConnector):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6") -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    def _split_system(self, messages: list[Message]) -> tuple[str, list[dict]]:
        system = ""
        msgs = []
        for m in messages:
            if m.role == "system":
                system = m.content
            else:
                msgs.append({"role": m.role, "content": m.content})
        return system, msgs

    async def chat(self, messages: list[Message], **kwargs) -> ChatResponse:
        system, msgs = self._split_system(messages)
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=kwargs.get("max_tokens", 4096),
            system=system or anthropic.NOT_GIVEN,
            messages=msgs,
        )
        return ChatResponse(
            content=resp.content[0].text,
            prompt_tokens=resp.usage.input_tokens,
            completion_tokens=resp.usage.output_tokens,
            model=self._model,
        )

    async def chat_stream(
        self, messages: list[Message], **kwargs
    ) -> AsyncIterator[str]:
        system, msgs = self._split_system(messages)
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=kwargs.get("max_tokens", 4096),
            system=system or anthropic.NOT_GIVEN,
            messages=msgs,
        ) as stream:
            async for text in stream.text_stream:
                yield text
