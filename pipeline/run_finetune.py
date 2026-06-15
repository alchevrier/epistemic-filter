#!/usr/bin/env python3
"""
run_finetune.py — QLoRA fine-tuning of Phi-3 Mini on the curated training mix.

Prerequisites (install once):
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
    pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
    pip install --no-deps trl peft accelerate bitsandbytes

    Or run with --install to attempt auto-install (requires network + ~8GB disk).

Usage:
    python3 pipeline/run_finetune.py [--dry-run] [--install] [--epochs N] [--mix PATH]

    --dry-run    Validate environment, load model, check VRAM, exit without training.
    --install    Install missing Python dependencies before running.
    --epochs N   Override epoch count (default: 6, per ADR-0012 schedule).
    --mix PATH   Path to training mix JSONL (default: corpus/training/mix.jsonl).
    --output DIR Output directory for adapter checkpoints (default: corpus/adapters).
    --resume DIR Resume training from a checkpoint directory.

Training schedule (ADR-0012):
    Epochs 1-3:  lr = 2e-4, seed_ratio = 10%  (standard mix)
    Epochs 4-6:  lr = 5e-5, seed_ratio = 20%  (consolidation, drift prevention)
    Checkpoint saved after each epoch (~50MB LoRA adapter weights).
    Benchmark eval recommended after epoch 3 and epoch 6.

Model:
    Base:    microsoft/Phi-3-mini-4k-instruct (3.8B, ~2.2GB at Q4)
    Method:  QLoRA — 4-bit NF4 base, fp16/bf16 LoRA adapters
    LoRA:    r=16, alpha=32, target modules: q_proj v_proj k_proj o_proj
    VRAM:    ~4-5GB during training (RTX 4060 8GB: comfortable)
"""

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_MIX_PATH    = REPO_ROOT / "corpus" / "training" / "mix.jsonl"
DEFAULT_ADAPTER_DIR = REPO_ROOT / "corpus" / "adapters"

BASE_MODEL = "microsoft/Phi-3-mini-4k-instruct"

LORA_CONFIG = dict(
    r=16,
    lora_alpha=32,
    target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
)

TRAINING_SCHEDULE = [
    # (epoch_range_inclusive, lr, seed_weight_boost)
    ((1, 3), 2e-4, 1.0),
    ((4, 6), 5e-5, 2.0),   # double seed weight in consolidation phase
]

MAX_SEQ_LENGTH = 2048     # Phi-3 Mini context window (4k, use half for safety)
TRAIN_BATCH    = 2        # per-device batch size (RTX 4060 8GB)
GRAD_ACCUM     = 4        # effective batch = 8
WARMUP_STEPS   = 100

# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------

def check_deps() -> tuple[bool, list[str]]:
    """Return (all_ok, missing_packages)."""
    missing = []
    for pkg, import_name in [
        ("torch",         "torch"),
        ("transformers",  "transformers"),
        ("peft",          "peft"),
        ("trl",           "trl"),
        ("bitsandbytes",  "bitsandbytes"),
        ("datasets",      "datasets"),
        ("accelerate",    "accelerate"),
    ]:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)
    return len(missing) == 0, missing


def check_unsloth() -> bool:
    try:
        __import__("unsloth")
        return True
    except ImportError:
        return False


def install_deps() -> None:
    import subprocess
    print("Installing PyTorch (CUDA 12.1) ...")
    subprocess.run([
        sys.executable, "-m", "pip", "install",
        "torch", "torchvision", "torchaudio",
        "--index-url", "https://download.pytorch.org/whl/cu121",
        "--quiet",
    ], check=True)

    print("Installing training libraries ...")
    subprocess.run([
        sys.executable, "-m", "pip", "install",
        "trl", "peft", "accelerate", "bitsandbytes", "datasets",
        "--quiet",
    ], check=True)

    print("Installing unsloth ...")
    subprocess.run([
        sys.executable, "-m", "pip", "install",
        "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git",
        "--no-deps", "--quiet",
    ], check=True)
    print("Dependencies installed.")


# ---------------------------------------------------------------------------
# Dry-run: validate environment, load model, check VRAM
# ---------------------------------------------------------------------------

def dry_run(mix_path: Path) -> None:
    print("=== DRY RUN ===")
    print()

    # 1. Python deps
    ok, missing = check_deps()
    unsloth_ok = check_unsloth()
    if ok:
        print("  [✓] Core training libraries present")
    else:
        print(f"  [✗] Missing libraries: {', '.join(missing)}")
        print("      Run: python3 pipeline/run_finetune.py --install")
    if unsloth_ok:
        print("  [✓] unsloth present")
    else:
        print("  [!] unsloth not installed (optional but strongly recommended for speed)")

    # 2. CUDA
    try:
        import torch
        cuda_ok = torch.cuda.is_available()
        if cuda_ok:
            gpu = torch.cuda.get_device_name(0)
            total_mb = torch.cuda.get_device_properties(0).total_memory // (1024 ** 2)
            free_mb  = (torch.cuda.get_device_properties(0).total_memory
                        - torch.cuda.memory_allocated(0)) // (1024 ** 2)
            print(f"  [✓] CUDA available: {gpu} ({total_mb} MB total, {free_mb} MB free)")
            if total_mb < 7000:
                print("  [!] Less than 7GB VRAM — may need to reduce batch size")
        else:
            print("  [✗] CUDA not available — training will fall back to CPU (very slow)")
    except ImportError:
        print("  [!] torch not installed — cannot check CUDA")
        cuda_ok = False

    # 3. Training mix
    if mix_path.exists():
        with mix_path.open() as f:
            lines = f.readlines()
        tier_counts: dict[str, int] = {}
        total_words = 0
        for line in lines:
            d = json.loads(line)
            tier = d.get("tier", "unknown")
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
            total_words += len(d["text"].split())
        token_est = int(total_words * 1.33)
        print(f"  [✓] Training mix: {len(lines)} documents, ~{token_est:,} tokens")
        for tier, count in sorted(tier_counts.items()):
            pct = count / len(lines) * 100
            print(f"        {tier:<14} {count:>4} docs  ({pct:.0f}%)")
        if token_est < 50_000:
            print("  [!] < 50K tokens — corpus too small for meaningful fine-tuning")
            print("      Run: .venv/bin/python3 pipeline/discover_candidates.py --search --score --save")
    else:
        print(f"  [✗] Training mix not found: {mix_path}")
        print("      Run: python3 pipeline/build_training_mix.py")

    # 4. Model load check (only if deps present)
    if ok:
        print()
        print("Loading model for VRAM check (this downloads ~2.2GB on first run) ...")
        try:
            import torch
            from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig

            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
            )

            tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=False)

            device_map = "cuda" if cuda_ok else "cpu"
            model = AutoModelForCausalLM.from_pretrained(
                BASE_MODEL,
                quantization_config=bnb_config if cuda_ok else None,
                device_map=device_map,
                trust_remote_code=False,
                attn_implementation="eager",
            )

            params = sum(p.numel() for p in model.parameters())
            print(f"  [✓] Model loaded: {params/1e9:.2f}B parameters")

            if cuda_ok:
                allocated_mb = torch.cuda.memory_allocated(0) // (1024 ** 2)
                free_mb      = (torch.cuda.get_device_properties(0).total_memory
                                - torch.cuda.memory_allocated(0)) // (1024 ** 2)
                print(f"  [✓] VRAM after model load: {allocated_mb} MB used, {free_mb} MB free")
                if free_mb < 2000:
                    print("  [!] Less than 2GB VRAM free after model load — training may OOM")
                else:
                    print("  [✓] VRAM headroom sufficient for QLoRA (r=16) training")

            # Test tokenizer on a sample
            sample = "Execution windows can be declared at compile time."
            ids = tokenizer(sample, return_tensors="pt")
            print(f"  [✓] Tokenizer: '{sample}' → {ids['input_ids'].shape[1]} tokens")

            del model
            if cuda_ok:
                torch.cuda.empty_cache()

        except Exception as e:
            print(f"  [✗] Model load failed: {e}")

    print()
    print("=== DRY RUN COMPLETE ===")
    print()
    if ok and mix_path.exists():
        print("Ready to train. Run:")
        print("  python3 pipeline/run_finetune.py")
    else:
        if not ok:
            print("Fix missing dependencies first:")
            print("  python3 pipeline/run_finetune.py --install")
        if not mix_path.exists():
            print("Build training mix first:")
            print("  python3 pipeline/build_training_mix.py")


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def run_training(
    mix_path: Path,
    adapter_dir: Path,
    total_epochs: int = 6,
    resume_from: str | None = None,
) -> None:
    import torch

    # Import training stack
    try:
        from unsloth import FastLanguageModel
        use_unsloth = True
        print("Using unsloth fast path.")
    except ImportError:
        use_unsloth = False
        print("unsloth not available — using standard HuggingFace path (slower).")

    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        TrainingArguments,
    )
    from trl import SFTTrainer
    from datasets import Dataset

    adapter_dir.mkdir(parents=True, exist_ok=True)

    # --- Load dataset ---
    print(f"\nLoading training mix: {mix_path}")
    with mix_path.open() as f:
        records = [json.loads(line) for line in f]
    dataset = Dataset.from_list(records)
    print(f"  {len(dataset)} examples loaded")

    # --- Load model ---
    print(f"\nLoading base model: {BASE_MODEL}")
    cuda_ok = torch.cuda.is_available()

    if use_unsloth:
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=BASE_MODEL,
            max_seq_length=MAX_SEQ_LENGTH,
            dtype=torch.bfloat16,
            load_in_4bit=True,
        )
        model = FastLanguageModel.get_peft_model(
            model,
            r=LORA_CONFIG["r"],
            lora_alpha=LORA_CONFIG["lora_alpha"],
            target_modules=LORA_CONFIG["target_modules"],
            lora_dropout=LORA_CONFIG["lora_dropout"],
            bias=LORA_CONFIG["bias"],
            use_gradient_checkpointing="unsloth",
            random_state=42,
        )
    else:
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
        ) if cuda_ok else None

        tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=False)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        model = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL,
            quantization_config=bnb_config,
            device_map="auto" if cuda_ok else "cpu",
            trust_remote_code=False,
            attn_implementation="eager",
        )
        model = prepare_model_for_kbit_training(model)

        lora_cfg = LoraConfig(**LORA_CONFIG)
        model = get_peft_model(model, lora_cfg)

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total     = sum(p.numel() for p in model.parameters())
    print(f"  Trainable: {trainable:,} / {total:,} parameters ({trainable/total*100:.2f}%)")

    # --- Training schedule: two phases ---
    for phase_idx, (epoch_range, lr, seed_boost) in enumerate(TRAINING_SCHEDULE):
        start_epoch, end_epoch = epoch_range
        phase_epochs = end_epoch - start_epoch + 1

        if phase_idx == 1 and seed_boost > 1.0:
            # Consolidation phase: duplicate seed examples to boost their weight
            seed_records   = [r for r in records if r.get("tier") == "seed"]
            other_records  = [r for r in records if r.get("tier") != "seed"]
            extra_seed     = seed_records * (int(seed_boost) - 1)
            phase_records  = other_records + seed_records + extra_seed
            import random
            random.shuffle(phase_records)
            phase_dataset  = Dataset.from_list(phase_records)
            print(f"\nPhase 2 consolidation dataset: {len(phase_dataset)} examples "
                  f"({len(seed_records) * int(seed_boost)} seed, {len(other_records)} other)")
        else:
            phase_dataset = dataset

        checkpoint_dir = adapter_dir / f"phase{phase_idx + 1}"
        checkpoint_dir.mkdir(exist_ok=True)

        print(f"\n--- Phase {phase_idx + 1}: epochs {start_epoch}-{end_epoch}, lr={lr} ---")

        args = TrainingArguments(
            output_dir=str(checkpoint_dir),
            num_train_epochs=phase_epochs,
            per_device_train_batch_size=TRAIN_BATCH,
            gradient_accumulation_steps=GRAD_ACCUM,
            learning_rate=lr,
            warmup_steps=WARMUP_STEPS if phase_idx == 0 else 0,
            lr_scheduler_type="cosine",
            fp16=not torch.cuda.is_bf16_supported() if cuda_ok else False,
            bf16=torch.cuda.is_bf16_supported() if cuda_ok else False,
            logging_steps=10,
            save_strategy="epoch",
            save_total_limit=3,
            report_to="none",
            optim="paged_adamw_8bit" if cuda_ok else "adamw_torch",
            seed=42,
            dataloader_num_workers=0,
        )

        trainer = SFTTrainer(
            model=model,
            tokenizer=tokenizer,
            train_dataset=phase_dataset,
            dataset_text_field="text",
            max_seq_length=MAX_SEQ_LENGTH,
            args=args,
            packing=True,   # pack multiple short examples into one sequence
        )

        print(f"Starting training phase {phase_idx + 1} ...")
        trainer.train(resume_from_checkpoint=resume_from if phase_idx == 0 else None)

        # Save adapter after this phase
        phase_adapter = adapter_dir / f"adapter_phase{phase_idx + 1}"
        model.save_pretrained(str(phase_adapter))
        tokenizer.save_pretrained(str(phase_adapter))
        print(f"Adapter saved: {phase_adapter.relative_to(REPO_ROOT)}")

        # Save training metadata
        meta = {
            "phase": phase_idx + 1,
            "epoch_range": list(epoch_range),
            "lr": lr,
            "base_model": BASE_MODEL,
            "lora_config": LORA_CONFIG,
            "examples": len(phase_dataset),
            "mix_path": str(mix_path),
        }
        (phase_adapter / "training_meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )

        print(f"\nPhase {phase_idx + 1} complete.")
        print("Next: run benchmark evaluation:")
        print(f"  python3 pipeline/evaluate_benchmark.py --adapter {phase_adapter.relative_to(REPO_ROOT)}")

    # Final merged adapter
    final_adapter = adapter_dir / "adapter_final"
    model.save_pretrained(str(final_adapter))
    tokenizer.save_pretrained(str(final_adapter))
    print(f"\nFinal adapter saved: {final_adapter.relative_to(REPO_ROOT)}")
    print("\nTraining complete.")
    print("Run full benchmark evaluation:")
    print(f"  python3 pipeline/evaluate_benchmark.py --adapter {final_adapter.relative_to(REPO_ROOT)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]

    if "--install" in args:
        install_deps()
        if "--dry-run" not in args and len(args) == 1:
            return

    mix_path    = DEFAULT_MIX_PATH
    adapter_dir = DEFAULT_ADAPTER_DIR
    total_epochs = 6
    resume_from = None
    dry = "--dry-run" in args

    for i, a in enumerate(args):
        if a == "--mix"     and i + 1 < len(args): mix_path     = Path(args[i + 1])
        if a == "--output"  and i + 1 < len(args): adapter_dir  = Path(args[i + 1])
        if a == "--epochs"  and i + 1 < len(args): total_epochs = int(args[i + 1])
        if a == "--resume"  and i + 1 < len(args): resume_from  = args[i + 1]

    if dry:
        dry_run(mix_path)
        return

    # Pre-flight checks
    ok, missing = check_deps()
    if not ok:
        print(f"ERROR: Missing libraries: {', '.join(missing)}")
        print("Run: python3 pipeline/run_finetune.py --install")
        sys.exit(1)

    if not mix_path.exists():
        print(f"ERROR: Training mix not found: {mix_path}")
        print("Run: python3 pipeline/build_training_mix.py")
        sys.exit(1)

    with mix_path.open() as f:
        count = sum(1 for _ in f)
    if count < 10:
        print(f"ERROR: Training mix has only {count} examples — too few to train.")
        sys.exit(1)

    print(f"Training mix: {mix_path} ({count} examples)")
    print(f"Adapter output: {adapter_dir}")
    print(f"Epochs: {total_epochs}")
    print()

    run_training(mix_path, adapter_dir, total_epochs, resume_from)


if __name__ == "__main__":
    main()
