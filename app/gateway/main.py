from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from gateway.api import admin, completions, embeddings, public
from gateway.config import settings
from gateway.db import close_pool, get_pool

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AI Gateway (provider=%s)", settings.llm.default_provider)
    await get_pool()
    _start_scheduler()
    yield
    await close_pool()
    logger.info("AI Gateway stopped")


def _start_scheduler() -> None:
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from gateway.api.admin import _run_finetuning

        cfg = settings.finetuning
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            _run_finetuning,
            "cron",
            **_parse_cron(cfg.schedule),
            id="finetuning",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("Scheduler started (cron=%s)", cfg.schedule)
    except Exception as e:
        logger.warning("Scheduler not started: %s", e)


def _parse_cron(expr: str) -> dict:
    minute, hour, day, month, day_of_week = expr.split()
    return {
        "minute": minute,
        "hour": hour,
        "day": day,
        "month": month,
        "day_of_week": day_of_week,
    }


app = FastAPI(title="AI Gateway", version="0.1.0", lifespan=lifespan)

# Prometheus メトリクスエンドポイント
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# ルーター登録
app.include_router(public.router)       # 認証不要: GET / と GET /stats
app.include_router(completions.router)
app.include_router(embeddings.router)
app.include_router(admin.router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/v1/models")
async def models():
    providers = list(settings.llm.providers.keys())
    return {
        "object": "list",
        "data": [
            {"id": p, "object": "model", "owned_by": "ai-gateway"}
            for p in ["auto"] + providers
        ],
    }
