#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path
import json

def init_domain(domain_path):
    dp = Path(domain_path)
    dp.mkdir(parents=True, exist_ok=True)
    (dp / "corpus" / "seed").mkdir(parents=True, exist_ok=True)
    (dp / "benchmark" / "results").mkdir(parents=True, exist_ok=True)
    
    # Provide a self-documenting JSON structure so users know exactly the format expected
    example_benchmark = {
        "version": "1.0",
        "total_questions": 1,
        "components": {
            "C1": {
                "name": "Custom Domain Rule Check",
                "question_count": 1,
                "description": "Checks if the model understands the core constraint of this domain."
            }
        },
        "questions": [
            {
                "id": "Q-001",
                "component": "C1",
                "question": "What happens if we violate the core constraint?",
                "expected_answer": "The system fails mathematically because...",
                "discriminator": {
                    "0_to_1": "Must mention the mathematical failure.",
                    "1_to_2": "Must explain the precise mechanism of the failure."
                }
            }
        ]
    }
    
    with open(dp / "benchmark" / "questions.json", "w") as f:
        json.dump(example_benchmark, f, indent=2)
        
    with open(dp / "corpus" / "seed" / "rules.md", "w") as f:
        f.write("# Domain Rules\n\n1. Define your core constraints here.\n2. E.g., 'Never use std::mutex'.\n3. The `generate` command will read this file to build training data.")
        
    print(f"Initialized new domain at {domain_path}")

def run_script(script_path, args):
    cmd = [sys.executable, str(Path("engine") / script_path)] + args
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

def main():
    parser = argparse.ArgumentParser(description="Epistemic Fine-Tuning Engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Init
    init_parser = subparsers.add_parser("init", help="Initialize a new domain")
    init_parser.add_argument("domain", help="Path to new domain (e.g. domains/secure-rust)")

    # Generate / Build Mix
    gen_parser = subparsers.add_parser("generate", help="Generate the dataset and build the mix")
    gen_parser.add_argument("--domain", required=True, help="Path to domain")

    # Train
    train_parser = subparsers.add_parser("train", help="Run the QLoRA finetuning")
    train_parser.add_argument("--domain", required=True, help="Path to domain")
    train_parser.add_argument("--base-model", default="microsoft/Phi-3-mini-4k-instruct", help="HF model name")
    train_parser.add_argument("--epochs", default="6", help="Epochs to train")

    # Evaluate
    eval_parser = subparsers.add_parser("evaluate", help="Prove the model correctness")
    eval_parser.add_argument("--domain", required=True, help="Path to domain")
    eval_parser.add_argument("--adapter", required=True, help="Path to compiled adapter")

    # Uncover
    uncover_parser = subparsers.add_parser("uncover", help="Dynamically uncover a codebase's constraints into a new domain")
    uncover_parser.add_argument("--repo", required=True, help="Path to the repository to mine")
    uncover_parser.add_argument("--domain", required=True, help="Path to the newly uncovered domain")
    uncover_parser.add_argument("--provider", default="ollama", choices=["ollama", "openai", "anthropic", "copilot", "gemini"], help="LLM provider (default: ollama)")
    uncover_parser.add_argument("--model", help="Model name (e.g. gpt-4o, claude-3-5-sonnet, gemini-1.5-pro)")
    uncover_parser.add_argument("--api-key", help="API key or GitHub Token for Copilot")

    args, extra = parser.parse_known_args()

    if args.command == "init":
        init_domain(args.domain)
    elif args.command == "generate":
        run_script("build_training_mix.py", ["--domain", args.domain] + extra)
    elif args.command == "train":
        run_script("run_finetune.py", ["--domain", args.domain, "--epochs", args.epochs] + extra)
    elif args.command == "evaluate":
        run_script("evaluate_benchmark.py", ["--domain", args.domain, "--adapter", args.adapter] + extra)
    elif args.command == "uncover":
        cmd_args = ["--repo", args.repo, "--domain", args.domain, "--provider", args.provider]
        if args.model: cmd_args.extend(["--model", args.model])
        if args.api_key: cmd_args.extend(["--api-key", args.api_key])
        run_script("uncover_domain.py", cmd_args + extra)

if __name__ == "__main__":
    main()
