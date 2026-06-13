from __future__ import annotations

import asyncio
import uuid
from typing import Optional

from gateway.db import get_pool
from gateway.metrics import knowledge_entries_total


_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "inventory": ["在庫", "inventory", "stock", "warehouse", "倉庫"],
    "hr": ["人事", "hr", "employee", "社員", "休暇", "給与"],
    "general": [],
}


def _classify_domain(text: str) -> list[str]:
    lower = text.lower()
    tags = [
        domain
        for domain, keywords in _DOMAIN_KEYWORDS.items()
        if keywords and any(kw in lower for kw in keywords)
    ]
    return tags or ["general"]


async def save(
    query_text: str,
    response_text: str,
    provider: str,
    app: str = "",
    tenant: str = "",
    quality_score: Optional[float] = None,
) -> None:
    domain_tags = _classify_domain(query_text)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO knowledge_entries
              (id, query_text, response_text, provider, quality_score, domain_tags, app, tenant, created_at, used_in_ft)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), FALSE)
            """,
            uuid.uuid4(),
            query_text,
            response_text,
            provider,
            quality_score,
            domain_tags,
            app,
            tenant,
        )
    # 非同期でカウントを更新
    asyncio.create_task(_update_metric())


async def _update_metric() -> None:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM knowledge_entries")
        knowledge_entries_total.set(count)
    except Exception:
        pass


async def get_domain_stats() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT tag, COUNT(*) AS count
            FROM knowledge_entries, UNNEST(domain_tags) AS tag
            GROUP BY tag
            ORDER BY count DESC
            """
        )
    return [{"domain": r["tag"], "count": int(r["count"])} for r in rows]


async def get_stats() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM knowledge_entries")
        avg_score = await conn.fetchval(
            "SELECT AVG(quality_score) FROM knowledge_entries WHERE quality_score IS NOT NULL"
        )
        pending_ft = await conn.fetchval(
            "SELECT COUNT(*) FROM knowledge_entries WHERE used_in_ft = FALSE AND quality_score >= 0.8"
        )
    return {
        "total_entries": total,
        "avg_quality_score": round(float(avg_score), 3) if avg_score else None,
        "pending_finetuning": pending_ft,
    }


async def export_for_finetuning(
    quality_threshold: float = 0.8,
    limit: int = 10000,
) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT query_text, response_text, provider, domain_tags, quality_score
            FROM knowledge_entries
            WHERE used_in_ft = FALSE
              AND quality_score >= $1
            ORDER BY quality_score DESC
            LIMIT $2
            """,
            quality_threshold,
            limit,
        )
    return [dict(r) for r in rows]
