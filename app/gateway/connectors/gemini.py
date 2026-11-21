from __future__ import annotations

from typing import AsyncIterator

from google import genai
from google.genai import types

from gateway.connectors.base import BaseLLMConnector, ChatResponse, Message


class GeminiConnector(BaseLLMConnector):
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def _to_contents(
        self, messages: list[Message]
    ) -> tuple[str | None, list[types.Content]]:
        system: str | None = None
        contents: list[types.Content] = []
        for m in messages:
            if m.role == "system":
                system = m.content
            else:
                role = "model" if m.role == "assistant" else "user"
                contents.append(
                    types.Content(role=role, parts=[types.Part(text=m.content)])
                )
        return system, contents

    async def chat(self, messages: list[Message], **kwargs) -> ChatResponse:
        system, contents = self._to_contents(messages)
        config = types.GenerateContentConfig(
            max_output_tokens=kwargs.get("max_tokens", 4096),
            system_instruction=system,
        )
        resp = await self._client.aio.models.generate_content(
            model=self._model,
            contents=contents,
            config=config,
        )
        usage = resp.usage_metadata
        return ChatResponse(
            content=resp.text or "",
            prompt_tokens=usage.prompt_token_count or 0,
            completion_tokens=usage.candidates_token_count or 0,
            model=self._model,
        )

    async def chat_stream(
        self, messages: list[Message], **kwargs
    ) -> AsyncIterator[str]:
        system, contents = self._to_contents(messages)
        config = types.GenerateContentConfig(
            max_output_tokens=kwargs.get("max_tokens", 4096),
            system_instruction=system,
        )
        async for chunk in self._client.aio.models.generate_content_stream(
            model=self._model,
            contents=contents,
            config=config,
        ):
            if chunk.text:
                yield chunk.text
