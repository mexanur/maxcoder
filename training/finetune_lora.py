"""
LoRA fine-tune Qwen2.5-Coder on your own (instruction, output) JSONL.
Best run on 8GB+ VRAM. On 4GB (3050 Ti) use the 1.5B model.

Usage:
    python training/finetune_lora.py \
        --data training/sample_data.jsonl \
        --base unsloth/Qwen2.5-Coder-1.5B-Instruct-bnb-4bit \
        --out  training/maxcoder-lora
"""
import argparse

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data",   default="training/sample_data.jsonl")
    ap.add_argument("--base",   default="unsloth/Qwen2.5-Coder-1.5B-Instruct-bnb-4bit")
    ap.add_argument("--out",    default="training/maxcoder-lora")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--ctx",    type=int, default=2048)
    args = ap.parse_args()

    from unsloth import FastLanguageModel
    from trl import SFTTrainer
    from transformers import TrainingArguments
    from datasets import load_dataset

    print(f"Loading base model: {args.base}")
    model, tok = FastLanguageModel.from_pretrained(
        model_name=args.base, max_seq_length=args.ctx, load_in_4bit=True)

    model = FastLanguageModel.get_peft_model(
        model, r=16, lora_alpha=16, lora_dropout=0,
        target_modules=["q_proj","k_proj","v_proj","o_proj",
                        "gate_proj","up_proj","down_proj"])

    def fmt(ex):
        return {"text": (
            "<|im_start|>user\n" + ex["instruction"] + "<|im_end|>\n"
            "<|im_start|>assistant\n" + ex["output"]  + "<|im_end|>"
        )}

    ds = load_dataset("json", data_files=args.data, split="train").map(fmt)

    trainer = SFTTrainer(
        model=model, tokenizer=tok,
        train_dataset=ds, dataset_text_field="text",
        max_seq_length=args.ctx,
        args=TrainingArguments(
            per_device_train_batch_size=1,
            gradient_accumulation_steps=8,
            num_train_epochs=args.epochs,
            learning_rate=2e-4,
            warmup_steps=10,
            logging_steps=5,
            output_dir=args.out,
            fp16=True,
            optim="adamw_8bit",
            save_strategy="epoch",
        ),
    )

    print("Training...")
    trainer.train()
    model.save_pretrained(args.out)
    tok.save_pretrained(args.out)
    print(f"\n✅ LoRA saved to {args.out}")
    print("Next: merge to GGUF → ollama create (see README for steps).")

if __name__ == "__main__":
    main()
