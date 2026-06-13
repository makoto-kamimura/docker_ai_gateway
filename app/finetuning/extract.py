"""
Step 1: Knowledge Store から未使用・高品質 Q&A データを抽出して
        /tmp/ft_raw.jsonl に保存する。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

import asyncpg
from pgvector.asyncpg import register_vector

logger = logging.getLogger(__name__)

DB_URL = os.environ.get(
    "ALEMBIC_DATABASE_URL",
    "postgresql://gateway:gateway@postgres:5432/ai_gateway",
)
QUALITY_THRESHOLD = float(os.environ.get("FT_QUALITY_THRESHOLD", "0.8"))
MIN_SAMPLES = int(os.environ.get("FT_MIN_SAMPLES", "500"))
OUTPUT_PATH = "/tmp/ft_raw.jsonl"


async def _extract() -> int:
    conn = await asyncpg.connect(DB_URL, init=register_vector)
    try:
        rows = await conn.fetch(
            """
            SELECT query_text, response_text, provider, domain_tags, quality_score
            FROM knowledge_entries
            WHERE used_in_ft = FALSE
              AND quality_score >= $1
            ORDER BY quality_score DESC
            """,
            QUALITY_THRESHOLD,
        )
    finally:
        await conn.close()

    if len(rows) < MIN_SAMPLES:
        raise RuntimeError(
            f"Not enough samples: {len(rows)} < {MIN_SAMPLES}"
        )

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(dict(row), ensure_ascii=False, default=str) + "\n")

    logger.info("Extracted %d samples to %s", len(rows), OUTPUT_PATH)
    return len(rows)


def run() -> None:
    asyncio.run(_extract())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
