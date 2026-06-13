"""Initial schema: cache_entries and knowledge_entries with pgvector

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute("""
        CREATE TABLE IF NOT EXISTS cache_entries (
            id          UUID        PRIMARY KEY,
            query_text  TEXT        NOT NULL,
            query_vec   vector(768),
            response    JSONB       NOT NULL,
            source      TEXT        NOT NULL DEFAULT 'external',
            app         TEXT        NOT NULL DEFAULT '',
            tenant      TEXT        NOT NULL DEFAULT '',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            hit_count   INTEGER     NOT NULL DEFAULT 0,
            ttl_expires TIMESTAMPTZ
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS cache_entries_vec_idx
        ON cache_entries USING ivfflat (query_vec vector_cosine_ops)
        WITH (lists = 100)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_entries (
            id            UUID        PRIMARY KEY,
            query_text    TEXT        NOT NULL,
            response_text TEXT        NOT NULL,
            provider      TEXT        NOT NULL DEFAULT 'external',
            quality_score FLOAT,
            domain_tags   TEXT[]      NOT NULL DEFAULT '{}',
            app           TEXT        NOT NULL DEFAULT '',
            tenant        TEXT        NOT NULL DEFAULT '',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            used_in_ft    BOOLEAN     NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS knowledge_entries_domain_idx
        ON knowledge_entries USING gin (domain_tags)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS knowledge_entries_ft_idx
        ON knowledge_entries (used_in_ft, quality_score)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_entries")
    op.execute("DROP TABLE IF EXISTS cache_entries")
