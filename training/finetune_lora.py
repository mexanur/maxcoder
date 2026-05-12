"""
LoRA fine-tune Qwen2.5-Coder on MaxCoder agent format data.

Optimised for RTX 3050 Ti 4 GB VRAM:
  - 3B model  → fits comfortably, ~3.5 GB VRAM
  - 7B model  → fits with 4-bit quant + ctx=1024, ~3.9 GB VRAM (tight)

Usage:
    # Generate training data first:
    python training/generate_agent_data.py --out training/agent_data.jsonl

    # Fine-tune 3B (recommended for 4GB VRAM):
    python training/finetune_lora.py \
        --data  training/agent_data.jsonl \
        --base  unsloth/Qwen2.5-Coder-3B-Instruct-bnb-4bit \
        --out   training/maxcoder-agent-lora-3b

    # Fine-tune 7B (needs ctx=1024 on 4GB):
    python training/finetune_lora.py \
        --data  training/agent_data.jsonl \
        --base  unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit \
        --ctx   1024 \
        --out   training/maxcoder-agent-lora-7b

After training, merge + export to Ollama:
    python training/export_to_ollama.py --lora training/maxcoder-agent-lora-3b
"""
import argparse, pathlib


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data",   default="training/agent_data.jsonl")
    ap.add_argument("--base",   default="unsloth/Qwen2.5-Coder-3B-Instruct-bnb-4bit")
    ap.add_argument("--out",    default="training/maxcoder-agent-lora")
    ap.add_argument("--epochs", type=int,   default=3)
    ap.add_argument("--ctx",    type=int,   default=2048)
    ap.add_argument("--lr",     type=float, default=2e-4)
    ap.add_argument("--rank",   type=int,   default=16)
    args = ap.parse_args()

    print(f"Loading base model : {args.base}")
    print(f"Training data      : {args.data}")
    print(f"Output dir         : {args.out}")
    print(f"Context length     : {args.ctx}")
    print(f"LoRA rank          : {args.rank}")
    print(f"Epochs             : {args.epochs}")
    print()

    try:
        from unsloth import FastLanguageModel
    except ImportError:
        raise SystemExit(
            "unsloth not installed.\n"
            "Install: pip install unsloth torch --index-url https://download.pytorch.org/whl/cu121"
        )

    from trl import SFTTrainer
    from transformers import TrainingArguments
    from datasets import load_dataset

    model, tok = FastLanguageModel.from_pretrained(
        model_name=args.base,
        max_seq_length=args.ctx,
        load_in_4bit=True,
    )

    model = FastLanguageModel.get_peft_model(
        model,
        r=args.rank,
        lora_alpha=args.rank,
        lora_dropout=0,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
    )

    def fmt(ex):
        return {"text": (
            "<|im_start|>system\n"
            "You are MaxCoder Agent, an expert software engineer that reads "
            "and writes project files using @@CREATE / @@EDIT / @@DELETE / @@RUN commands."
            "<|im_end|>\n"
            "<|im_start|>user\n" + ex["instruction"] + "<|im_end|>\n"
            "<|im_start|>assistant\n" + ex["output"]  + "<|im_end|>"
        )}

    ds = load_dataset("json", data_files=args.data, split="train").map(fmt)
    print(f"Dataset size: {len(ds)} examples")

    # VRAM-safe settings for RTX 3050 Ti
    is_7b  = "7b" in args.base.lower() or "7B" in args.base
    ga     = 16 if is_7b else 8    # gradient accumulation
    ctx    = min(args.ctx, 1024 if is_7b else 2048)

    trainer = SFTTrainer(
        model=model,
        tokenizer=tok,
        train_dataset=ds,
        dataset_text_field="text",
        max_seq_length=ctx,
        args=TrainingArguments(
            per_device_train_batch_size=1,
            gradient_accumulation_steps=ga,
            num_train_epochs=args.epochs,
            learning_rate=args.lr,
            warmup_ratio=0.1,
            logging_steps=5,
            output_dir=args.out,
            fp16=True,
            optim="adamw_8bit",
            save_strategy="epoch",
            save_total_limit=2,
            dataloader_num_workers=0,   # Windows-safe
            report_to="none",
        ),
    )

    print("\nTraining…")
    trainer.train()

    out = pathlib.Path(args.out)
    model.save_pretrained(out)
    tok.save_pretrained(out)
    print(f"\n✅  LoRA adapter saved to {out}")

    # Write a ready-to-use Modelfile for ollama
    model_tag = "maxcoder-agent-3b" if not is_7b else "maxcoder-agent-7b"
    modelfile_path = out.parent / f"Modelfile.{model_tag}"
    modelfile_path.write_text(f"""FROM {args.base}
ADAPTER {out}

PARAMETER num_ctx {ctx}
PARAMETER temperature 0.2
PARAMETER top_p 0.9
PARAMETER repeat_penalty 1.1
PARAMETER num_gpu 99

SYSTEM \"\"\"
You are MaxCoder Agent, an expert software engineer that reads and writes
project files using @@CREATE / @@EDIT / @@DELETE / @@RUN commands.
Always output the COMPLETE file content in each block.
\"\"\"
""", encoding="utf-8")

    print(f"📄  Modelfile written to {modelfile_path}")
    print(f"\nNext: register with Ollama:")
    print(f"  ollama create {model_tag} -f {modelfile_path}")
    print(f"  ollama run {model_tag}")


if __name__ == "__main__":
    main()
