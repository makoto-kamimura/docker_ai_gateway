from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from gateway.auth import verify_token
from gateway.cache.embedder import embed

router = APIRouter()


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str = "nomic-embed-text"


@router.post("/v1/embeddings")
async def create_embeddings(
    req: EmbeddingRequest,
    _: str = Depends(verify_token),
):
    inputs = [req.input] if isinstance(req.input, str) else req.input
    data = []
    for i, text in enumerate(inputs):
        vec = await embed(text)
        data.append({"object": "embedding", "index": i, "embedding": vec})
    return {
        "object": "list",
        "model": req.model,
        "data": data,
    }
