"""
Step 2: ft_raw.jsonl を ChatML 形式の JSON Lines (train/eval 8:2) に変換する。
"""
from __future__ import annotations

import json
import logging
import random

logger = logging.getLogger(__name__)

INPUT_PATH = "/tmp/ft_raw.jsonl"
TRAIN_PATH = "/tmp/ft_train.jsonl"
EVAL_PATH = "/tmp/ft_eval.jsonl"
EVAL_RATIO = 0.2


def _to_chatml(row: dict) -> dict:
    return {
        "messages": [
            {"role": "user", "content": row["query_text"]},
            {"role": "assistant", "content": row["response_text"]},
        ]
    }


def run() -> None:
    with open(INPUT_PATH, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]

    random.shuffle(rows)
    split = int(len(rows) * (1 - EVAL_RATIO))
    train_rows = rows[:split]
    eval_rows = rows[split:]

    with open(TRAIN_PATH, "w", encoding="utf-8") as f:
        for row in train_rows:
            f.write(json.dumps(_to_chatml(row), ensure_ascii=False) + "\n")

    with open(EVAL_PATH, "w", encoding="utf-8") as f:
        for row in eval_rows:
            f.write(json.dumps(_to_chatml(row), ensure_ascii=False) + "\n")

    logger.info(
        "Prepared %d train / %d eval samples", len(train_rows), len(eval_rows)
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
