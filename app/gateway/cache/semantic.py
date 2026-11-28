from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from gateway.cache import policy
from gateway.config import settings
from gateway.db import get_pool


async def search(
    query_vec: list[float],
    app: str,
    tenant: str,
) -> Optional[dict]:
    """類似度が閾値を超えるキャッシュエントリを返す。なければ None。
    app と tenant が両方とも一致するものだけを探す（ほかのアプリ・テナントの答えを返さない）。"""
    if not app or not tenant:
        return None
    pool = await get_pool()
    threshold = settings.cache.similarity_threshold
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, response, 1 - (query_vec <=> $1::vector) AS similarity
            FROM cache_entries
            WHERE app = $2 AND tenant = $3
              AND (ttl_expires IS NULL OR ttl_expires > NOW())
              AND 1 - (query_vec <=> $1::vector) > $4
            ORDER BY query_vec <=> $1::vector
            LIMIT 1
            """,
            query_vec,
            app,
            tenant,
            threshold,
        )
        if row is None:
            return None

        await conn.execute(
            "UPDATE cache_entries SET hit_count = hit_count + 1 WHERE id = $1",
            row["id"],
        )
        return json.loads(row["response"])


async def store(
    query_text: str,
    query_vec: list[float],
    response: dict,
    source: str,
    app: str = "",
    tenant: str = "",
) -> None:
    # 設定で許した答え（既定はローカルモデルの答え）で、アプリとテナントが分かるものだけを保存する
    if not policy.store_allowed(settings.cache, source, app, tenant):
        return
    pool = await get_pool()
    ttl_hours = settings.cache.default_ttl_hours
    ttl_expires = None
    if ttl_hours is not None:
        from datetime import timedelta
        ttl_expires = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO cache_entries
              (id, query_text, query_vec, response, source, app, tenant, created_at, ttl_expires)
            VALUES ($1, $2, $3::vector, $4, $5, $6, $7, NOW(), $8)
            ON CONFLICT DO NOTHING
            """,
            uuid.uuid4(),
            query_text,
            query_vec,
            json.dumps(response, ensure_ascii=False),
            source,
            app,
            tenant,
            ttl_expires,
        )


async def get_stats() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM cache_entries")
        hits = await conn.fetchval("SELECT COALESCE(SUM(hit_count), 0) FROM cache_entries")
    return {"total_entries": total, "total_hits": hits}


async def clear_all() -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM cache_entries")
    return int(result.split()[-1])
