"""セマンティックキャッシュを使うかどうかの判定（設定の cache.enabled / cache.local_only）。

判定だけをここに集め、completions（検索）と semantic（保存）の両方から同じ規則で呼ぶ。
"""
from __future__ import annotations

from typing import Optional

from gateway.config import CacheConfig

LOCAL_PROVIDER = "ollama"


def _scoped(app: str, tenant: str, request_opt_out: bool) -> bool:
    # 利用者ごとに内容が違う答えを使い回さないよう、アプリとテナントが分かる要求だけにする
    return bool(app) and bool(tenant) and not request_opt_out


def lookup_allowed(
    cfg: CacheConfig,
    provider_name: str,
    app: str,
    tenant: str,
    request_opt_out: bool = False,
) -> bool:
    """要求の前に、キャッシュを探すか。local_only のときは、ローカルモデルが答える要求だけ。"""
    if not cfg.enabled or not _scoped(app, tenant, request_opt_out):
        return False
    return provider_name == LOCAL_PROVIDER or not cfg.local_only


def store_allowed(
    cfg: CacheConfig,
    source: str,
    app: str,
    tenant: str,
    request_opt_out: bool = False,
) -> bool:
    """答えをキャッシュに残すか。source は答えた側（local / external）。外部へ振り替えた答えも、local_only なら残さない。"""
    if not cfg.enabled or not _scoped(app, tenant, request_opt_out):
        return False
    return source == "local" or not cfg.local_only


def request_opt_out(metadata: Optional[dict]) -> bool:
    """要求の metadata に "cache": false があれば、その要求ではキャッシュを使わない。"""
    if not metadata:
        return False
    value = metadata.get("cache")
    return value is False or (isinstance(value, str) and value.strip().lower() in ("false", "0", "off", "no"))
