"""
Step 4: 評価データセットでベンチマーク → 合格なら Ollama にモデルをインポートする。

合格基準: ROUGE-L スコアが既存モデルより向上 (またはベースラインを超える)。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess

import httpx

logger = logging.getLogger(__name__)

EVAL_PATH = "/tmp/ft_eval.jsonl"
MODEL_DIR = "/tmp/ft_model"
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
MODEL_NAME = "ai-gateway-custom"
ROUGE_THRESHOLD = float(os.environ.get("FT_ROUGE_THRESHOLD", "0.3"))


def _rouge_l(reference: str, hypothesis: str) -> float:
    ref_tokens = reference.lower().split()
    hyp_tokens = hypothesis.lower().split()
    if not ref_tokens or not hyp_tokens:
        return 0.0

    m, n = len(ref_tokens), len(hyp_tokens)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if ref_tokens[i - 1] == hyp_tokens[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    lcs = dp[m][n]
    precision = lcs / n
    recall = lcs / m
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _ollama_chat(prompt: str) -> str:
    resp = httpx.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json={
            "model": MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def _import_to_ollama() -> None:
    gguf_files = [f for f in os.listdir(MODEL_DIR) if f.endswith(".gguf")]
    if not gguf_files:
        raise RuntimeError(f"No GGUF file found in {MODEL_DIR}")

    gguf_path = os.path.join(MODEL_DIR, gguf_files[0])
    modelfile = f"FROM {gguf_path}\n"
    modelfile_path = os.path.join(MODEL_DIR, "Modelfile")
    with open(modelfile_path, "w") as f:
        f.write(modelfile)

    subprocess.run(
        ["ollama", "create", MODEL_NAME, "-f", modelfile_path],
        check=True,
        capture_output=True,
    )
    logger.info("Imported model to Ollama as '%s'", MODEL_NAME)


def run() -> None:
    # Ollama に GGUF をインポート (評価前にロード)
    _import_to_ollama()

    with open(EVAL_PATH, encoding="utf-8") as f:
        samples = [json.loads(line) for line in f]

    scores = []
    for sample in samples[:50]:  # 最大 50 件で評価
        msgs = sample["messages"]
        user_msg = next(m["content"] for m in msgs if m["role"] == "user")
        ref = next(m["content"] for m in msgs if m["role"] == "assistant")
        try:
            hyp = _ollama_chat(user_msg)
            scores.append(_rouge_l(ref, hyp))
        except Exception as e:
            logger.warning("Evaluation sample failed: %s", e)

    if not scores:
        raise RuntimeError("No evaluation samples succeeded")

    avg_rouge = sum(scores) / len(scores)
    logger.info("ROUGE-L avg: %.4f (threshold=%.4f)", avg_rouge, ROUGE_THRESHOLD)

    if avg_rouge < ROUGE_THRESHOLD:
        raise RuntimeError(
            f"ROUGE-L {avg_rouge:.4f} is below threshold {ROUGE_THRESHOLD}"
        )

    logger.info("Model evaluation passed. Model '%s' is now active.", MODEL_NAME)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
