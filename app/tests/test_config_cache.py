"""cache: の設定と、環境変数 GATEWAY_CACHE_* での上書き（gateway/config.py）。"""
import pytest

from gateway import config
from gateway.config import CacheConfig


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("GATEWAY_CACHE_ENABLED", raising=False)
    monkeypatch.delenv("GATEWAY_CACHE_LOCAL_ONLY", raising=False)


def test_file_values_are_used_without_env():
    section = config._cache_section({"enabled": False, "local_only": False, "similarity_threshold": 0.9})
    assert section == {"enabled": False, "local_only": False, "similarity_threshold": 0.9}


@pytest.mark.parametrize(
    ("env", "expected"),
    [("true", True), ("1", True), ("on", True), ("YES", True), ("false", False), ("0", False), ("off", False), ("No", False)],
)
def test_env_overrides_enabled(monkeypatch, env, expected):
    monkeypatch.setenv("GATEWAY_CACHE_ENABLED", env)
    assert config._cache_section({"enabled": not expected})["enabled"] is expected


def test_env_overrides_local_only(monkeypatch):
    monkeypatch.setenv("GATEWAY_CACHE_LOCAL_ONLY", "false")
    cfg = CacheConfig.model_validate(config._cache_section({"local_only": True}))
    assert cfg.local_only is False
    assert cfg.enabled is True


def test_empty_env_keeps_file_value(monkeypatch):
    monkeypatch.setenv("GATEWAY_CACHE_ENABLED", "  ")
    assert config._cache_section({"enabled": False})["enabled"] is False


def test_invalid_env_is_an_error(monkeypatch):
    # 打ち間違いで黙ってキャッシュが有効・無効にならないよう、読めない値は起動時にエラーにする
    monkeypatch.setenv("GATEWAY_CACHE_LOCAL_ONLY", "maybe")
    with pytest.raises(ValueError, match="GATEWAY_CACHE_LOCAL_ONLY"):
        config._cache_section({})


@pytest.mark.parametrize(
    ("mode", "enabled", "local_only"),
    [("off", False, True), ("local_only", True, True)],
)
def test_legacy_mode_is_read(mode, enabled, local_only):
    cfg = CacheConfig.model_validate(config._cache_section({"mode": mode}))
    assert (cfg.enabled, cfg.local_only) == (enabled, local_only)


def test_explicit_switch_wins_over_legacy_mode():
    cfg = CacheConfig.model_validate(config._cache_section({"mode": "off", "enabled": True}))
    assert cfg.enabled is True


def test_missing_section_uses_defaults():
    cfg = CacheConfig.model_validate(config._cache_section(None))
    assert (cfg.enabled, cfg.local_only) == (True, True)


def test_bundled_config_yaml_defaults():
    # リポジトリの app/config.yaml は「使う・ローカルモデルの答えだけ」
    settings = config.load_settings()
    assert settings.cache.enabled is True
    assert settings.cache.local_only is True
