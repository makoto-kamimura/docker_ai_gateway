"""
Step 3: Unsloth + LoRA でファインチューニングを実行し、
        GGUF 形式で /tmp/ft_model/ に保存する。

NOTE: GPU 環境 (NVIDIA) + unsloth パッケージが必要。
      requirements.txt には含めていないため、GPU 利用時に別途インストール:
        pip install unsloth
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

BASE_MODEL = os.environ.get("FT_BASE_MODEL", "unsloth/llama-3-8b-Instruct-bnb-4bit")
LORA_RANK = int(os.environ.get("FT_LORA_RANK", "16"))
TRAIN_PATH = "/tmp/ft_train.jsonl"
OUTPUT_DIR = "/tmp/ft_model"


def run() -> None:
    try:
        from unsloth import FastLanguageModel
        from trl import SFTTrainer
        from transformers import TrainingArguments
        from datasets import load_dataset
    except ImportError as e:
        raise RuntimeError(
            "unsloth / trl / datasets not installed. "
            "Run: pip install unsloth trl datasets"
        ) from e

    logger.info("Loading base model: %s", BASE_MODEL)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL,
        max_seq_length=2048,
        load_in_4bit=True,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=LORA_RANK,
        lora_alpha=LORA_RANK * 2,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        bias="none",
        use_gradient_checkpointing=True,
    )

    dataset = load_dataset("json", data_files={"train": TRAIN_PATH}, split="train")

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="messages",
        max_seq_length=2048,
        args=TrainingArguments(
            output_dir=OUTPUT_DIR,
            num_train_epochs=1,
            per_device_train_batch_size=2,
            gradient_accumulation_steps=4,
            warmup_steps=10,
            logging_steps=10,
            save_strategy="epoch",
            fp16=True,
            report_to="none",
        ),
    )

    logger.info("Starting training...")
    trainer.train()

    logger.info("Saving GGUF model to %s", OUTPUT_DIR)
    model.save_pretrained_gguf(OUTPUT_DIR, tokenizer, quantization_method="q4_k_m")
    logger.info("Training complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
