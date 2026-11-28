"""キャッシュを使うかどうかの判定（gateway/cache/policy.py）。"""
import pytest

from gateway.cache import policy
from gateway.config import CacheConfig

ON_LOCAL = CacheConfig(enabled=True, local_only=True)
ON_ALL = CacheConfig(enabled=True, local_only=False)
OFF = CacheConfig(enabled=False, local_only=False)


def test_defaults_are_on_and_local_only():
    cfg = CacheConfig()
    assert cfg.enabled is True
    assert cfg.local_only is True


@pytest.mark.parametrize(
    ("cfg", "provider", "expected"),
    [
        (ON_LOCAL, "ollama", True),
        (ON_LOCAL, "claude", False),
        (ON_LOCAL, "openai", False),
        (ON_ALL, "ollama", True),
        (ON_ALL, "claude", True),
        (OFF, "ollama", False),
        (OFF, "claude", False),
    ],
)
def test_lookup_allowed_by_switches(cfg, provider, expected):
    assert policy.lookup_allowed(cfg, provider, "inventory", "t1") is expected


@pytest.mark.parametrize(
    ("cfg", "source", "expected"),
    [
        (ON_LOCAL, "local", True),
        (ON_LOCAL, "external", False),
        (ON_ALL, "local", True),
        (ON_ALL, "external", True),
        (OFF, "local", False),
    ],
)
def test_store_allowed_by_switches(cfg, source, expected):
    assert policy.store_allowed(cfg, source, "inventory", "t1") is expected


@pytest.mark.parametrize(("app", "tenant"), [("", "t1"), ("inventory", ""), ("", "")])
def test_requires_app_and_tenant(app, tenant):
    # 利用者ごとに違う答えを使い回さないよう、アプリとテナントが分からない要求はキャッシュしない
    assert policy.lookup_allowed(ON_ALL, "ollama", app, tenant) is False
    assert policy.store_allowed(ON_ALL, "local", app, tenant) is False


def test_request_opt_out_wins_over_settings():
    assert policy.lookup_allowed(ON_ALL, "ollama", "inventory", "t1", request_opt_out=True) is False
    assert policy.store_allowed(ON_ALL, "local", "inventory", "t1", request_opt_out=True) is False


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        (None, False),
        ({}, False),
        ({"cache": True}, False),
        ({"cache": False}, True),
        ({"cache": "false"}, True),
        ({"cache": "OFF"}, True),
        ({"cache": "true"}, False),
        ({"cache": 0}, False),  # 真偽値と文字以外は無視する（既定どおり）
    ],
)
def test_request_opt_out(metadata, expected):
    assert policy.request_opt_out(metadata) is expected
