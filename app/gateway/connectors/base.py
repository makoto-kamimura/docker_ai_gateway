from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from pydantic import BaseModel


class Message(BaseModel):
    role: str
    content: str


class ChatResponse(BaseModel):
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""


class BaseLLMConnector(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        **kwargs,
    ) -> ChatResponse: ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[Message],
        **kwargs,
    ) -> AsyncIterator[str]: ...
