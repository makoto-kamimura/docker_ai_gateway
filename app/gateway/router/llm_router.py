from __future__ import annotations

from gateway.config import settings
from gateway.db import get_pool


async def _local_accuracy(domain_tags: list[str]) -> float:
    """ドメインタグに対するローカル LLM の過去精度を DB から取得する。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if domain_tags:
            score = await conn.fetchval(
                """
                SELECT AVG(quality_score)
                FROM knowledge_entries
                WHERE quality_score IS NOT NULL
                  AND used_in_ft = TRUE
                  AND domain_tags && $1
                """,
                domain_tags,
            )
        else:
            score = await conn.fetchval(
                "SELECT AVG(quality_score) FROM knowledge_entries WHERE used_in_ft = TRUE"
            )
    return float(score) if score else 0.0


async def decide(
    cache_similarity: float,
    domain_tags: list[str] | None = None,
) -> str:
    """
    戻り値: 'local' | 'external'
    信頼スコア = キャッシュ類似度 × 0.6 + ローカルモデル精度 × 0.4
    """
    tags = domain_tags or []
    local_acc = await _local_accuracy(tags)
    confidence = cache_similarity * 0.6 + local_acc * 0.4

    threshold = settings.router.local_confidence_threshold
    if confidence >= threshold:
        return "local"
    return "external"
