#!/usr/bin/env python3
"""
evaluate_benchmark.py — Run the 51 held-out questions against a model and score results.

Supports two model backends:
  Ollama  — any model served by Ollama (no Python ML deps required)
  Adapter — HuggingFace base + LoRA adapter from run_finetune.py (requires torch etc.)

Usage:
    # Score base model via Ollama (quick baseline, no deps beyond requests)
    python3 pipeline/evaluate_benchmark.py --ollama --model phi3:mini

    # Score fine-tuned adapter
    python3 pipeline/evaluate_benchmark.py --adapter corpus/adapters/adapter_final

    # Compare base vs fine-tuned (runs both, writes comparison report)
    python3 pipeline/evaluate_benchmark.py --ollama --model phi3:mini \\
        --adapter corpus/adapters/adapter_final --compare

    # Score from pre-generated answers file (re-score without re-running model)
    python3 pipeline/evaluate_benchmark.py --answers benchmark/answers_phi3_base.json

Options:
    --questions PATH    Benchmark file (default: benchmark/questions.json)
    --out DIR          Output directory (default: benchmark/results/)
    --limit N          Score only first N questions (for quick check)
    --max-tokens N     Max tokens per answer (default: 512)
    --temperature F    Sampling temperature (default: 0.1 — near-deterministic)
    --no-auto-score    Skip heuristic scoring; write raw answers only for manual review
    --verbose          Print each question, answer, and score as they run

Scoring (ADR-0017):
    Each question scored 0 / 1 / 2.
    0→1 discriminator: specific concept must appear in answer.
    1→2 discriminator: specific derivation or mechanism must appear in answer.
    Auto-scoring uses keyword matching against discriminator criteria.
    Auto-scores are approximate — manual review of borderline answers recommended.

Pass thresholds (ADR-0013):
    C1 (Frame Identification)     mean >= 1.6 / 2.0  (25 questions)
    C2 (Wrong-Claim Classification) mean >= 1.6 / 2.0  (17 questions)
    C3 (Cross-Domain Bridge)      mean >= 1.4 / 2.0   (9 questions)
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO_ROOT       = Path(__file__).parent.parent
QUESTIONS_PATH  = REPO_ROOT / "benchmark" / "questions.json"
RESULTS_DIR     = REPO_ROOT / "benchmark" / "results"

OLLAMA_GENERATE = "http://localhost:11434/api/generate"

PASS_THRESHOLDS = {"C1": 1.6, "C2": 1.6, "C3": 1.4}

# System prompt anchors the model in the domain frame
SYSTEM_PROMPT = """\
You reason within the clock-aware-programming frame. In this frame:
- Execution windows can be declared at compile time.
- Circuits declare when they run, for how long, and which memory regions they access.
- The compiler proves the schedule before execution begins.
- Mechanisms like schedulers, mutexes, memory barriers, and garbage collectors exist
  as compensations for undeclared timing. When timing is declared, they become redundant.
- A claim is 'scoped' if it is locally correct but presents a conditional truth as universal.
- A claim is 'misattributed' if the observation is correct but the causal explanation is wrong.
- A claim is a 'near-miss' if the diagnosis is right but the remedy relocates rather than
  eliminates the underlying cause.
- A claim is a 'framing-trap' if it is locally correct but frames a compensation as a solution.
Answer clearly and directly. Name the assumption, state what changes when it is removed,
and name the mechanism that becomes redundant or inapplicable.\
"""

# ---------------------------------------------------------------------------
# Auto-scorer
# ---------------------------------------------------------------------------

def _keywords(text: str) -> set[str]:
    """Meaningful lowercase word set (common stop words removed)."""
    stops = {"a", "an", "the", "is", "it", "in", "of", "to", "or", "and",
             "not", "for", "at", "as", "by", "be", "on", "but", "must",
             "that", "this", "with", "from", "are", "was", "has", "its"}
    return {w for w in re.findall(r"[a-z][a-z0-9'-]*", text.lower()) if w not in stops}


def _concept_present(answer: str, concept: str, threshold: float = 0.5) -> bool:
    """
    Return True if the meaningful words of 'concept' appear sufficiently
    in 'answer'. Keyword-level matching handles synonyms and reorderings.
    """
    concept_kw = _keywords(concept)
    if not concept_kw:
        return True
    answer_kw = _keywords(answer)
    hit = concept_kw & answer_kw
    return len(hit) / len(concept_kw) >= threshold


def _extract_positive_concepts(text: str) -> list[str]:
    """
    Extract the positive key concept(s) from a discriminator sentence.
    Strips negative qualifications ('not X', 'rather than X') before searching.

    Rules (applied in order):
    1. First quoted phrase before any negative clause.
    2. Clause after action verb (name/explain/identify/…) before negation.
    3. Full text as fallback.
    """
    # Strip from the first negative clause onward
    text_pos = re.split(r"(?:,?\s+not\s+'|\. Must not\b)", text)[0]
    # Rule 1: quoted phrase
    quoted = re.findall(r"'([^']+)'", text_pos)
    if quoted:
        return quoted
    # Rule 2: after action verb
    m = re.search(
        r"must (?:name|identify|explain|state|introduce|derive|give|"
        r"characterise|trace|make|mention|show|use|describe)\s+(?:that\s+|the\s+)?(.+)",
        text_pos, re.IGNORECASE
    )
    if m:
        raw = re.split(r"\s+(?:and|—|-|rather|not|instead)\b|[.;]", m.group(1))[0]
        return [raw.strip()]
    return [text_pos]



def auto_score(answer: str, discriminator: dict) -> int:
    """
    Score an answer 0/1/2 using the discriminator criteria.

    discriminator keys: '0_to_1' and '1_to_2'
    Positive key concepts extracted (negative clauses stripped first).
    Keyword-coverage matching (≥50%) handles synonyms and reorderings.

    Conservative: uncertain cases score 0 or 1 rather than 2.
    """
    if not answer or len(answer.split()) < 10:
        return 0

    d01 = discriminator.get("0_to_1", "")
    d12 = discriminator.get("1_to_2", "")

    c01 = _extract_positive_concepts(d01)
    c12 = _extract_positive_concepts(d12)

    # Score 0→1
    passes_01 = all(_concept_present(answer, c) for c in c01 if c)
    if not passes_01:
        return 0

    # Score 1→2
    passes_12 = all(_concept_present(answer, c) for c in c12 if c)
    if not passes_12:
        return 1

    return 2


# ---------------------------------------------------------------------------
# Model backends
# ---------------------------------------------------------------------------

def generate_ollama(
    question: str,
    model: str,
    max_tokens: int = 512,
    temperature: float = 0.1,
) -> str:
    """Generate an answer via Ollama."""
    payload = {
        "model": model,
        "prompt": f"{SYSTEM_PROMPT}\n\n{question}",
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": temperature,
        },
    }
    resp = requests.post(OLLAMA_GENERATE, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()["response"].strip()


def generate_adapter(
    question: str,
    model,
    tokenizer,
    max_tokens: int = 512,
    temperature: float = 0.1,
    device: str = "cuda",
) -> str:
    """Generate an answer using a loaded HuggingFace model+adapter."""
    import torch

    prompt = f"{SYSTEM_PROMPT}\n\n{question}"
    inputs = tokenizer(prompt, return_tensors="pt").to(device)

    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=max_tokens,
            temperature=temperature,
            do_sample=temperature > 0,
            pad_token_id=tokenizer.eos_token_id,
        )

    generated = out[0][inputs["input_ids"].shape[1]:]
    return tokenizer.decode(generated, skip_special_tokens=True).strip()


def load_adapter_model(adapter_path: Path):
    """Load base model + LoRA adapter. Returns (model, tokenizer, device)."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel

    from run_finetune import BASE_MODEL

    cuda_ok = torch.cuda.is_available()
    device = "cuda" if cuda_ok else "cpu"

    print(f"Loading base model: {BASE_MODEL}")
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    ) if cuda_ok else None

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        quantization_config=bnb_config,
        device_map="auto" if cuda_ok else "cpu",
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
    )

    print(f"Loading adapter: {adapter_path}")
    model = PeftModel.from_pretrained(model, str(adapter_path))
    model.eval()

    return model, tokenizer, device


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def compute_report(results: list[dict], label: str) -> dict:
    """Compute C1/C2/C3 scores and overall summary."""
    by_component: dict[str, list[int]] = {"C1": [], "C2": [], "C3": []}
    for r in results:
        comp = r.get("component")
        score = r.get("auto_score")
        if comp in by_component and score is not None:
            by_component[comp].append(score)

    component_stats = {}
    for comp, scores in by_component.items():
        if not scores:
            continue
        mean = sum(scores) / len(scores)
        threshold = PASS_THRESHOLDS[comp]
        component_stats[comp] = {
            "n": len(scores),
            "mean": round(mean, 3),
            "threshold": threshold,
            "pass": mean >= threshold,
            "score_distribution": {
                "0": scores.count(0),
                "1": scores.count(1),
                "2": scores.count(2),
            },
        }

    all_scores = [r["auto_score"] for r in results if r.get("auto_score") is not None]
    overall_mean = sum(all_scores) / len(all_scores) if all_scores else 0

    return {
        "label": label,
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "total_questions": len(results),
        "overall_mean": round(overall_mean, 3),
        "components": component_stats,
        "all_pass": all(s["pass"] for s in component_stats.values()),
    }


def print_report(report: dict) -> None:
    print()
    print("=" * 60)
    print(f"  BENCHMARK RESULTS — {report['label']}")
    print("=" * 60)
    print(f"  Overall mean: {report['overall_mean']:.3f} / 2.000")
    print(f"  Questions scored: {report['total_questions']}")
    print()
    for comp, stats in report["components"].items():
        status = "PASS" if stats["pass"] else "FAIL"
        dist = stats["score_distribution"]
        bar = "█" * dist["2"] + "▓" * dist["1"] + "░" * dist["0"]
        print(f"  {comp}  mean={stats['mean']:.3f}  threshold={stats['threshold']}  "
              f"[{status}]  {bar}")
        print(f"      0:{dist['0']}  1:{dist['1']}  2:{dist['2']}  (n={stats['n']})")
    print()
    overall = "ALL PASS" if report.get("all_pass") else "NOT YET PASSING"
    print(f"  → {overall}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]

    use_ollama   = "--ollama"   in args
    use_adapter  = "--adapter"  in args
    compare_mode = "--compare"  in args
    no_score     = "--no-auto-score" in args
    verbose      = "--verbose"  in args

    questions_path = QUESTIONS_PATH
    out_dir        = RESULTS_DIR
    max_tokens     = 512
    temperature    = 0.1
    limit          = None
    ollama_model   = "phi3:mini"
    adapter_path   = None
    answers_file   = None

    for i, a in enumerate(args):
        if a == "--questions" and i + 1 < len(args): questions_path = Path(args[i + 1])
        if a == "--out"       and i + 1 < len(args): out_dir        = Path(args[i + 1])
        if a == "--max-tokens"and i + 1 < len(args): max_tokens     = int(args[i + 1])
        if a == "--temperature"and i+1 < len(args):  temperature    = float(args[i + 1])
        if a == "--limit"     and i + 1 < len(args): limit          = int(args[i + 1])
        if a == "--model"     and i + 1 < len(args): ollama_model   = args[i + 1]
        if a == "--adapter"   and i + 1 < len(args): adapter_path   = Path(args[i + 1])
        if a == "--answers"   and i + 1 < len(args): answers_file   = Path(args[i + 1])

    if not use_ollama and not use_adapter and not answers_file:
        # Default: use Ollama if running, adapter if present, error otherwise
        use_ollama = True

    # --- Load questions ---
    if not questions_path.exists():
        print(f"ERROR: Benchmark file not found: {questions_path}")
        sys.exit(1)

    with questions_path.open() as f:
        bench = json.load(f)

    questions = bench["questions"]
    if limit:
        questions = questions[:limit]

    print(f"Benchmark: {len(questions)} questions")
    print(f"Components: {bench.get('total_questions', '?')} total, "
          f"using {len(questions)}{' (limited)' if limit else ''}")
    print()

    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

    # --- If re-scoring from existing answers file ---
    if answers_file:
        with answers_file.open() as f:
            prior_results = json.load(f)["results"]
        results = prior_results
        label = answers_file.stem
        if not no_score:
            for r in results:
                q = next((q for q in bench["questions"] if q["id"] == r["id"]), None)
                if q:
                    r["auto_score"] = auto_score(r["answer"], q["discriminator"])
        report = compute_report(results, label)
        print_report(report)
        out_path = out_dir / f"rescore_{label}_{timestamp}.json"
        out_path.write_text(json.dumps({"report": report, "results": results}, indent=2))
        print(f"\nSaved: {out_path.relative_to(REPO_ROOT)}")
        return

    # --- Generate answers ---
    runs: list[tuple[str, callable]] = []  # (label, generate_fn)

    if use_ollama:
        # Verify Ollama is reachable
        try:
            r = requests.get("http://localhost:11434/api/tags", timeout=5)
            r.raise_for_status()
            print(f"Ollama: {ollama_model}")
        except Exception as e:
            print(f"ERROR: Ollama not reachable: {e}")
            print("Start Ollama and ensure the model is pulled:")
            print(f"  ollama pull {ollama_model}")
            sys.exit(1)

        def gen_ollama(q: str) -> str:
            return generate_ollama(q, ollama_model, max_tokens, temperature)

        runs.append((f"ollama_{ollama_model.replace(':', '_')}", gen_ollama))

    if use_adapter and adapter_path:
        if not adapter_path.exists():
            print(f"ERROR: Adapter not found: {adapter_path}")
            sys.exit(1)
        try:
            model, tokenizer, device = load_adapter_model(adapter_path)
        except ImportError as e:
            print(f"ERROR: Missing dep for adapter mode: {e}")
            print("Run: python3 pipeline/run_finetune.py --install")
            sys.exit(1)

        def gen_adapter(q: str) -> str:
            return generate_adapter(q, model, tokenizer, max_tokens, temperature, device)

        runs.append((adapter_path.name, gen_adapter))

    if not runs:
        print("No model backend specified. Use --ollama or --adapter.")
        sys.exit(1)

    all_reports = []

    for label, gen_fn in runs:
        print(f"\nRunning: {label}")
        print("-" * 50)
        results = []

        for i, q in enumerate(questions, 1):
            qid  = q["id"]
            comp = q["component"]
            text = q["question"]

            if verbose:
                print(f"\n[{i}/{len(questions)}] {qid} ({comp})")
                print(f"Q: {text[:120]}{'...' if len(text) > 120 else ''}")
            else:
                print(f"  [{i:2d}/{len(questions)}] {qid} ...", end=" ", flush=True)

            t0 = time.time()
            try:
                answer = gen_fn(text)
                elapsed = time.time() - t0

                score = auto_score(answer, q["discriminator"]) if not no_score else None

                if verbose:
                    print(f"A: {answer[:300]}{'...' if len(answer) > 300 else ''}")
                    print(f"Score: {score}  ({elapsed:.1f}s)")
                else:
                    score_str = str(score) if score is not None else "?"
                    print(f"score={score_str}  ({elapsed:.1f}s)")

            except Exception as e:
                print(f"ERROR: {e}")
                answer = ""
                score = 0
                elapsed = 0

            results.append({
                "id": qid,
                "component": comp,
                "question": text,
                "expected_answer": q["expected_answer"],
                "discriminator": q["discriminator"],
                "answer": answer,
                "auto_score": score,
                "elapsed_s": round(elapsed, 2),
            })

        # Score and report
        report = compute_report(results, label)
        print_report(report)
        all_reports.append(report)

        # Save per-run results
        out_path = out_dir / f"{label}_{timestamp}.json"
        out_path.write_text(json.dumps(
            {"report": report, "results": results}, indent=2, ensure_ascii=False
        ))
        print(f"Saved: {out_path.relative_to(REPO_ROOT)}")

    # --- Comparison report (if --compare with multiple runs) ---
    if compare_mode and len(all_reports) > 1:
        print("\n" + "=" * 60)
        print("  COMPARISON")
        print("=" * 60)
        for comp in ("C1", "C2", "C3"):
            print(f"\n  {comp}:")
            for r in all_reports:
                stats = r["components"].get(comp, {})
                if stats:
                    status = "PASS" if stats["pass"] else "FAIL"
                    print(f"    {r['label']:<40} {stats['mean']:.3f}  [{status}]")

        comp_path = out_dir / f"comparison_{timestamp}.json"
        comp_path.write_text(json.dumps(all_reports, indent=2))
        print(f"\nComparison saved: {comp_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
