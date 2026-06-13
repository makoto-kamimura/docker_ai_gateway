from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from gateway.auth import verify_token
from gateway.cache import semantic
from gateway.knowledge import store

router = APIRouter(prefix="/v1/admin", dependencies=[Depends(verify_token)])

# Fine-tuning ジョブの状態管理 (インメモリ: 本番は Redis 等に移行)
_ft_status: dict = {"status": "idle", "progress": None, "started_at": None, "error": None}


@router.get("/cache/stats")
async def cache_stats():
    return await semantic.get_stats()


@router.delete("/cache")
async def cache_clear():
    deleted = await semantic.clear_all()
    return {"deleted": deleted}


@router.get("/knowledge/stats")
async def knowledge_stats():
    return await store.get_stats()


@router.post("/knowledge/export")
async def knowledge_export(quality_threshold: float = 0.8, limit: int = 1000):
    rows = await store.export_for_finetuning(quality_threshold=quality_threshold, limit=limit)
    return {"count": len(rows), "data": rows}


@router.post("/finetuning/trigger")
async def finetuning_trigger():
    if _ft_status["status"] == "running":
        return {"message": "already running", "status": _ft_status}
    asyncio.create_task(_run_finetuning())
    return {"message": "triggered"}


@router.get("/finetuning/status")
async def finetuning_status():
    return _ft_status


async def _run_finetuning():
    import importlib
    from datetime import datetime, timezone

    _ft_status.update({"status": "running", "progress": "0/4", "started_at": str(datetime.now(timezone.utc)), "error": None})
    try:
        for step, name in enumerate(["extract", "prepare", "train", "evaluate"], 1):
            _ft_status["progress"] = f"{step}/4 ({name})"
            mod = importlib.import_module(f"finetuning.{name}")
            await asyncio.to_thread(mod.run)
        _ft_status.update({"status": "success", "progress": "4/4"})
    except Exception as e:
        _ft_status.update({"status": "failed", "error": str(e)})
