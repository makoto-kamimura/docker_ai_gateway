"""/v1/chat/completions でのセマンティックキャッシュの使い方（設定の切り替えごと）。

DB・Ollama・外部の LLM には触れない（埋め込み・キャッシュ・接続先を偽物に差し替える）。
"""
import asyncio
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway import config
from gateway.api import completions
from gateway.auth import verify_token
from gateway.cache import semantic
from gateway.config import CacheConfig, KnowledgeConfig
from gateway.connectors.base import ChatResponse


class Recorder:
    def __init__(self):
        self.embed_local = []
        self.embed = []
        self.search = []
        self.store = []
        self.connectors = []
        self.cached = None  # search が返す値
        self.fail_local = False


@pytest.fixture
def rec(monkeypatch):
    r = Recorder()

    async def embed_local(text):
        r.embed_local.append(text)
        return [0.1] * 768

    async def embed(text):
        r.embed.append(text)
        return [0.2] * 768

    async def search(vec, app, tenant):
        r.search.append((app, tenant))
        return r.cached

    async def store(**kwargs):
        r.store.append(kwargs)

    class FakeConnector:
        def __init__(self, provider):
            self.provider = provider

        async def chat(self, messages, **kwargs):
            if self.provider == "ollama" and r.fail_local:
                raise RuntimeError("ollama is down")
            return ChatResponse(content=f"answer from {self.provider}", prompt_tokens=3, completion_tokens=4)

        def chat_stream(self, messages, **kwargs):
            async def gen():
                yield f"stream from {self.provider}"
            return gen()

    def build_connector(provider):
        r.connectors.append(provider)
        return FakeConnector(provider)

    # 保存は asyncio.create_task で後ろに回すので、テストでは集めておいて、応答のあとに走らせる
    pending = []
    fake_asyncio = types.SimpleNamespace(create_task=lambda coro: pending.append(coro))

    monkeypatch.setattr(completions.embedder, "embed_local", embed_local)
    monkeypatch.setattr(completions.embedder, "embed", embed)
    monkeypatch.setattr(completions.semantic, "search", search)
    monkeypatch.setattr(completions.semantic, "store", store)
    monkeypatch.setattr(completions, "_build_connector", build_connector)
    monkeypatch.setattr(completions, "asyncio", fake_asyncio)
    monkeypatch.setattr(config.settings, "knowledge", KnowledgeConfig(enabled=False))
    monkeypatch.setattr(config.settings.llm, "default_provider", "claude")
    r.pending = pending
    return r


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(completions.router)
    app.dependency_overrides[verify_token] = lambda: "test"
    return TestClient(app)


def use_cache(monkeypatch, **kwargs):
    monkeypatch.setattr(config.settings, "cache", CacheConfig(**kwargs))


def ask(client, rec, model="local", metadata=None, stream=False):
    body = {"model": model, "messages": [{"role": "user", "content": "在庫は何個？"}], "stream": stream}
    if metadata is not False:
        body["metadata"] = metadata if metadata is not None else {"app": "inventory", "tenant": "t1"}
    res = client.post("/v1/chat/completions", json=body)
    for coro in rec.pending:
        asyncio.run(coro)
    rec.pending.clear()
    return res


def test_local_model_miss_searches_and_stores_with_local_embedding(client, rec, monkeypatch):
    use_cache(monkeypatch, enabled=True, local_only=True)
    res = ask(client, rec, model="local")
    assert res.status_code == 200
    assert res.json()["metadata"]["source"] == "local"
    assert rec.embed_local == ["在庫は何個？"] and rec.embed == []
    assert rec.search == [("inventory", "t1")]
    assert len(rec.store) == 1
    assert rec.store[0]["source"] == "local"
    assert (rec.store[0]["app"], rec.store[0]["tenant"]) == ("inventory", "t1")


def test_cache_hit_returns_cached_answer_without_calling_llm(client, rec, monkeypatch):
    use_cache(monkeypatch, enabled=True, local_only=True)
    rec.cached = {"choices": [{"message": {"role": "assistant", "content": "3 個です"}}]}
    res = ask(client, rec, model="local")
    assert res.json()["metadata"] == {"source": "cache"}
    assert res.json()["choices"][0]["message"]["content"] == "3 個です"
    assert rec.connectors == []
    assert rec.store == []


def test_external_model_is_not_cached_when_local_only(client, rec, monkeypatch):
    use_cache(monkeypatch, enabled=True, local_only=True)
    res = ask(client, rec, model="claude")
    assert res.json()["metadata"]["source"] == "external"
    assert rec.embed_local == [] and rec.embed == []
    assert rec.search == [] and rec.store == []


def test_external_model_is_cached_when_local_only_is_off(client, rec, monkeypatch):
    use_cache(monkeypatch, enabled=True, local_only=False)
    res = ask(client, rec, model="claude")
    assert res.json()["metadata"]["source"] == "external"
    # 外部の LLM の要求は、従来の埋め込みの経路（Ollama → OpenAI）を使う
    assert rec.embed == ["在庫は何個？"] and rec.embed_local == []
    assert rec.search == [("inventory", "t1")]
    assert [s["source"] for s in rec.store] == ["external"]


def test_local_model_still_uses_local_embedding_when_local_only_is_off(client, rec, monkeypatch):
    use_cache(monkeypatch, enabled=True, local_only=False)
    ask(client, rec, model="local")
    assert rec.embed_local == ["在庫は何個？"] and rec.embed == []


@pytest.mark.parametrize("model", ["local", "claude"])
def test_disabled_cache_is_never_used(client, rec, monkeypatch, model):
    use_cache(monkeypatch, enabled=False, local_only=False)
    res = ask(client, rec, model=model)
    assert res.status_code == 200
    assert rec.embed_local == [] and rec.embed == []
    assert rec.search == [] and rec.store == []


@pytest.mark.parametrize("metadata", [False, {"app": "inventory"}, {"tenant": "t1"}])
def test_requests_without_app_and_tenant_are_not_cached(client, rec, monkeypatch, metadata):
    use_cache(monkeypatch, enabled=True, local_only=False)
    ask(client, rec, model="local", metadata=metadata)
    assert rec.search == [] and rec.store == []


def test_request_can_opt_out(client, rec, monkeypatch):
    use_cache(monkeypatch, enabled=True, local_only=False)
    ask(client, rec, model="local", metadata={"app": "inventory", "tenant": "t1", "cache": False})
    assert rec.embed_local == [] and rec.search == [] and rec.store == []


def test_fallback_to_external_is_not_stored_when_local_only(client, rec, monkeypatch):
    use_cache(monkeypatch, enabled=True, local_only=True)
    monkeypatch.setattr(config.settings.router, "fallback_to_external", True)
    rec.fail_local = True
    res = ask(client, rec, model="local")
    assert res.json()["metadata"]["source"] == "external"
    assert rec.connectors == ["ollama", "claude"]
    assert rec.search == [("inventory", "t1")]  # 探すのはローカルモデルの要求として
    assert rec.store == []  # 答えたのは外部なので残さない


def test_streaming_answers_are_not_stored(client, rec, monkeypatch):
    use_cache(monkeypatch, enabled=True, local_only=True)
    res = ask(client, rec, model="local", stream=True)
    assert res.status_code == 200
    assert "stream from ollama" in res.text
    assert rec.store == []


def test_semantic_store_refuses_external_answer_when_local_only(monkeypatch):
    # semantic.store は、呼び出し側を通らずに呼ばれても、設定で許さない答えを残さない
    use_cache(monkeypatch, enabled=True, local_only=True)

    async def no_pool():
        raise AssertionError("DB に触れてはいけない")

    monkeypatch.setattr(semantic, "get_pool", no_pool)
    asyncio.run(semantic.store(query_text="q", query_vec=[0.0], response={}, source="external", app="a", tenant="t"))
    use_cache(monkeypatch, enabled=False)
    asyncio.run(semantic.store(query_text="q", query_vec=[0.0], response={}, source="local", app="a", tenant="t"))
