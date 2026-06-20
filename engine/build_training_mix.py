#!/usr/bin/env python3
"""
build_training_mix.py — Assemble the QLoRA training dataset from the curated corpus.

Reads:
    corpus/accepted/*/             — accepted documents (text.txt + record.json)
    corpus/seed/                   — seed corpus (clock-aware-programming docs)
    corpus/known-wrong-claims.json — W-register for contrastive examples
    corpus/analogy-examples.json   — C3 cross-domain analogy Q&A pairs
    corpus/c4-coding-examples.json — C4 generative coding Q&A pairs

Writes:
    corpus/training/mix.jsonl      — full training dataset, JSONL format
    corpus/training/manifest.json  — stats and split summary

Format of each JSONL line:
    {"text": "<Phi-3 chat-template string>", "tier": "...", "source": "..."}

All training examples are formatted using the Phi-3-mini-instruct chat template:
    <|system|>\n{system}<|end|>\n<|user|>\n{user}<|end|>\n<|assistant|>\n{asst}<|end|>\n

Tier strategy (natural counts, minimal replication):
    primary      — accepted corpus, 1x (natural count, no replication)
    cross_domain — accepted cross-domain docs, 1x
    seed         — seed corpus, 1x (covers vocabulary and frame)
    contrastive  — W-register claims, 2x (covers all 5 degree labels multiple times)
    analogy      — C3 cross-domain Q&A pairs, 2x (covers mechanism mapping)

Usage:
    python3 pipeline/build_training_mix.py [--seed-dir PATH] [--out-dir PATH]
    --no-shuffle        Preserve tier order in output (for inspection)
"""

import json
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

import sys
DOMAIN_ROOT = REPO_ROOT / "domains" / "cap"
for i, arg in enumerate(sys.argv):
    if arg == "--domain" and i + 1 < len(sys.argv):
        DOMAIN_ROOT = Path(sys.argv[i + 1])

DEFAULT_SEED_DIR = Path("/home/alchevrier/Repositories/clock-aware-programming/docs")
DEFAULT_OUT_DIR  = DOMAIN_ROOT / "corpus" / "training"

ACCEPTED_DIR      = DOMAIN_ROOT / "corpus" / "accepted"
WRONG_CLAIMS_PATH = DOMAIN_ROOT / "corpus" / "known-wrong-claims.json"
ANALOGY_PATH      = DOMAIN_ROOT / "corpus" / "analogy-examples.json"
C1_PATH           = DOMAIN_ROOT / "corpus" / "c1-examples.json"
C4_CODING_PATH    = DOMAIN_ROOT / "corpus" / "c4-coding-examples.json"

NOISY_ACCEPTED_MARKERS = [
    "report github issue",
    "submit in github",
    "why html?",
    "initializereadingpreferences",
    "localstorage.getitem",
    "instructions for reporting errors",
    "experimental support, please view the build logs for errors",
]

# Tier ratios (for reporting only — actual counts use natural strategy below)
TIER_RATIOS = {
    "primary":      0.60,
    "cross_domain": 0.15,
    "contrastive":  0.15,
    "seed":         0.10,
    "analogy":      0.00,  # additive, not ratio-controlled
    "c1":           0.00,  # additive, not ratio-controlled
    "c4_coding":    0.00,  # additive, not ratio-controlled
}

# ---------------------------------------------------------------------------
# Phi-3-mini-instruct chat template
# Format: <|system|>\n{s}<|end|>\n<|user|>\n{u}<|end|>\n<|assistant|>\n{a}<|end|>\n
# ---------------------------------------------------------------------------

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
and name the mechanism that becomes redundant or inapplicable."""


def phi3_chat(system: str, user: str, asst: str) -> str:
    """Format a single training example as a Phi-3-mini-instruct chat turn."""
    return (
        f"<|system|>\n{system}<|end|>\n"
        f"<|user|>\n{user}<|end|>\n"
        f"<|assistant|>\n{asst}<|end|>\n"
    )

# Cross-domain: accepted papers whose record lists these topic keywords in title/abstract
CROSS_DOMAIN_KEYWORDS = [
    "ownership", "borrow", "linear type", "session type",
    "process algebra", "csp", "channel calculus",
    "region-based", "memory region",
    "formal verification", "model checking",
    "reactive", "synchronous language", "lustre", "esterel",
    "unikernel", "library os", "exokernel",
    "dpdk", "poll mode", "kernel bypass",
    "wcet", "worst-case execution",
]

# User prompt template for C2 contrastive examples
CONTRASTIVE_USER = """\
Classify the following systems claim as: scoped / misattributed / near-miss / false / framing-trap.
Name the assumption the claim depends on, then provide the clock-aware-programming refutation.

CLAIM: {claim}"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_seed_docs(seed_dir: Path) -> list[dict]:
    """Load all .md files from the seed corpus directory as chat-format continuations."""
    docs = []
    for f in sorted(seed_dir.rglob("*.md")):
        if f.name in ("index.md",):
            continue
        text = f.read_text(encoding="utf-8").strip()
        words = text.split()
        if len(words) < 50:  # skip stubs
            continue
        # Document continuation: first 150 words as user context, rest as assistant
        split = min(150, len(words) // 3)
        user_ctx  = " ".join(words[:split])
        asst_body = " ".join(words[split:split + 500])
        user_msg  = f"Continue the following clock-aware programming text:\n\n{user_ctx}"
        formatted = phi3_chat(SYSTEM_PROMPT, user_msg, asst_body)
        docs.append({
            "text": formatted,
            "tier": "seed",
            "source": str(f.relative_to(seed_dir.parent)),
            "word_count": len(words),
        })
    return docs


def load_accepted_docs() -> tuple[list[dict], list[dict]]:
    """
    Load accepted corpus documents.
    Returns (primary_docs, cross_domain_docs).
    A document is cross-domain if its title/abstract contains cross-domain keywords.
    """
    primary, cross_domain = [], []
    skipped_noisy = 0
    if not ACCEPTED_DIR.exists():
        return primary, cross_domain

    def clean_accepted_text(raw_text: str) -> str | None:
        text = re.sub(r"\s+", " ", raw_text).strip()
        lower = text.lower()

        abstract_idx = lower.find(" abstract ")
        if abstract_idx > 0:
            for marker in NOISY_ACCEPTED_MARKERS:
                marker_idx = lower.find(marker)
                if marker_idx != -1 and marker_idx < abstract_idx:
                    text = text[max(0, abstract_idx - 200):]
                    lower = text.lower()
                    break

        for footer in [
            " instructions for reporting errors ",
            " experimental support, please view the build logs for errors ",
            " report github issue ",
        ]:
            idx = lower.find(footer)
            if idx != -1:
                text = text[:idx]
                lower = text.lower()

        marker_hits = sum(1 for m in NOISY_ACCEPTED_MARKERS if m in lower)
        noisy_prefix = (
            "localstorage" in lower[:600]
            or "document.documentelement.setattribute" in lower[:1000]
            or "report github issue" in lower[:1200]
        )
        if marker_hits >= 2 and noisy_prefix:
            return None

        # Keep only substantial documents in accepted tier.
        if len(text.split()) < 400:
            return None

        return text

    for doc_dir in sorted(ACCEPTED_DIR.iterdir()):
        text_path   = doc_dir / "text.txt"
        record_path = doc_dir / "record.json"
        if not text_path.exists():
            continue

        raw_text = text_path.read_text(encoding="utf-8").strip()
        text = clean_accepted_text(raw_text)
        if text is None:
            skipped_noisy += 1
            continue
        record = {}
        if record_path.exists():
            record = json.loads(record_path.read_text(encoding="utf-8"))

        meta = record.get("metadata", {})
        title    = meta.get("title", "").lower()
        abstract = meta.get("abstract", "").lower()
        haystack = title + " " + abstract

        is_cross = any(kw in haystack for kw in CROSS_DOMAIN_KEYWORDS)
        words = text.split()
        split = min(150, len(words) // 3)
        user_ctx  = " ".join(words[:split])
        asst_body = " ".join(words[split:split + 500])
        prefix = "Continue the following clock-aware programming text"
        if is_cross:
            prefix = "Continue the following cross-domain reinforcement text (bridge: formal reasoning structures compatible with clock-aware programming)"
        user_msg  = f"{prefix}:\n\n{user_ctx}"
        formatted = phi3_chat(SYSTEM_PROMPT, user_msg, asst_body)
        entry = {
            "text": formatted,
            "tier": "cross_domain" if is_cross else "primary",
            "source": f"corpus/accepted/{doc_dir.name}",
            "arxiv_id": record.get("arxiv_id", doc_dir.name),
            "word_count": len(words),
        }
        if is_cross:
            cross_domain.append(entry)
        else:
            primary.append(entry)

    if skipped_noisy:
        print(f"  [cleaning] skipped {skipped_noisy} noisy/insufficient accepted documents")

    return primary, cross_domain


def _prepend_bridge(text: str, meta: dict) -> str:
    """Prepend cross-domain bridge annotation (ADR-0010 context signal)."""
    title = meta.get("title", "")
    bridge = (
        f"[BRIDGE CONTEXT] This document is included as cross-domain reinforcement. "
        f"It develops reasoning structures compatible with the clock-aware-programming "
        f"frame but from a different starting domain. Bridge signals: formal derivation, "
        f"frame-bounded conclusions, assumption exposure. "
        f"Source: {title}\n\n"
    )
    return bridge + text


def load_contrastive_examples() -> list[dict]:
    """Build contrastive Q&A training examples from the W-register (chat format)."""
    if not WRONG_CLAIMS_PATH.exists():
        return []
    claims = json.loads(WRONG_CLAIMS_PATH.read_text(encoding="utf-8"))
    examples = []
    for entry in claims:
        user_msg = CONTRASTIVE_USER.format(claim=entry["claim"])
        degree = entry.get('degree', 'false')
        if 'refutation' in entry:
            refutation = entry['refutation']
        else:
            reason = entry.get('reason', 'This violates the domain rules.')
            refutation = f"Degree: {degree}. The claim is incorrect in this architecture. {reason}"
        
        asst_msg = f"DEGREE: {degree}\n\n{refutation}"
        text = phi3_chat(SYSTEM_PROMPT, user_msg, asst_msg)
        examples.append({
            "text": text,
            "tier": "contrastive",
            "source": f"corpus/known-wrong-claims.json#{entry.get('id', f'AUTO-{len(examples)}')}",
            "wrong_claim_id": entry.get("id", f"AUTO-{len(examples)}"),
            "degree": degree,
            "word_count": len(text.split()),
        })
    return examples


def load_analogy_examples() -> list[dict]:
    """Load C3 cross-domain analogy Q&A training examples (chat format)."""
    if not ANALOGY_PATH.exists():
        return []
    entries = json.loads(ANALOGY_PATH.read_text(encoding="utf-8"))
    examples = []
    for entry in entries:
        text = phi3_chat(SYSTEM_PROMPT, entry["question"], entry["answer"])
        examples.append({
            "text": text,
            "tier": "analogy",
            "source": f"corpus/analogy-examples.json#{entry['id']}",
            "analogy_id": entry["id"],
            "domain": entry.get("domain", ""),
            "word_count": len(text.split()),
        })
    return examples


def load_c1_examples() -> list[dict]:
    """Load C1 frame-identification Q&A training examples (chat format)."""
    if not C1_PATH.exists():
        return []
    entries = json.loads(C1_PATH.read_text(encoding="utf-8"))
    examples = []
    for entry in entries:
        text = phi3_chat(SYSTEM_PROMPT, entry["question"], entry["answer"])
        examples.append({
            "text": text,
            "tier": "c1",
            "source": f"corpus/c1-examples.json#{entry['id']}",
            "c1_id": entry["id"],
            "word_count": len(text.split()),
        })
    return examples


def load_c4_coding_examples() -> list[dict]:
    """Load C4 generative coding Q&A training examples (chat format)."""
    if not C4_CODING_PATH.exists():
        return []
    entries = json.loads(C4_CODING_PATH.read_text(encoding="utf-8"))
    examples = []
    for entry in entries:
        text = phi3_chat(SYSTEM_PROMPT, entry["question"], entry["answer"])
        examples.append({
            "text": text,
            "tier": "c4_coding",
            "source": f"corpus/c4-coding-examples.json#{entry['id']}",
            "c4_id": entry["id"],
            "word_count": len(text.split()),
        })
    return examples


def replicate_to_target(docs: list[dict], target_count: int) -> list[dict]:
    """
    Replicate a list of documents (with shuffling) to reach approximately
    target_count entries. Used to enforce tier ratios by count.
    """
    if not docs:
        return []
    result = []
    while len(result) < target_count:
        batch = docs[:]
        random.shuffle(batch)
        result.extend(batch)
    return result[:target_count]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]
    shuffle = "--no-shuffle" not in args

    seed_dir = DEFAULT_SEED_DIR
    out_dir  = DEFAULT_OUT_DIR

    for i, a in enumerate(args):
        if a == "--seed-dir" and i + 1 < len(args):
            seed_dir = Path(args[i + 1])
        elif a == "--out-dir" and i + 1 < len(args):
            out_dir = Path(args[i + 1])

    # --- Load all tiers ---
    print("Loading seed corpus ...")
    seed_docs = load_seed_docs(seed_dir)
    print(f"  {len(seed_docs)} seed documents")

    print("Loading accepted corpus ...")
    primary_docs, cross_docs = load_accepted_docs()
    print(f"  {len(primary_docs)} primary, {len(cross_docs)} cross-domain")

    print("Loading W-register contrastive examples ...")
    contrastive_docs = load_contrastive_examples()
    print(f"  {len(contrastive_docs)} contrastive examples")

    print("Loading analogy examples ...")
    analogy_docs = load_analogy_examples()
    print(f"  {len(analogy_docs)} analogy examples")

    print("Loading C1 frame-identification examples ...")
    c1_docs = load_c1_examples()
    print(f"  {len(c1_docs)} C1 examples")

    print("Loading C4 generative coding examples ...")
    c4_coding_docs = load_c4_coding_examples()
    print(f"  {len(c4_coding_docs)} C4 coding examples")

    total_base = len(seed_docs) + len(primary_docs) + len(cross_docs) + len(contrastive_docs)
    if total_base == 0:
        print("\nERROR: No documents found in any tier.")
        print("  Run pipeline/discover_candidates.py --search --score --save first.")
        sys.exit(1)

    print()

    # --- Determine counts for each tier ---
    # Natural count strategy: avoid over-replication which causes overfitting and
    # format degradation. Replicate only short-form tiers (contrastive, analogy)
    # to ensure label/mechanism coverage.
    CONTRASTIVE_REPS = 2  # 2x ensures each degree label seen multiple times per epoch
    ANALOGY_REPS     = 2  # 2x ensures each mechanism mapping seen multiple times per epoch
    C1_REPS          = 2  # 2x ensures each assumption-removal pattern seen multiple times
    C4_CODING_REPS   = 5  # 5x reinforces implementation-level CAP phrasing heavily since we have very few examples representing this task.

    if primary_docs:
        counts = {
            "primary":      len(primary_docs),                           # 1x, no replication
            "cross_domain": len(cross_docs),                             # 1x, no replication
            "seed":         len(seed_docs),                              # 1x, full vocabulary
            "contrastive":  len(contrastive_docs) * CONTRASTIVE_REPS,   # 2x, degree taxonomy
            "analogy":      len(analogy_docs) * ANALOGY_REPS,           # 2x, mechanism mapping
            "c1":           len(c1_docs) * C1_REPS,                     # 2x, assumption-removal
            "c4_coding":    len(c4_coding_docs) * C4_CODING_REPS,       # 2x, CAP coding responses
        }
    else:
        # No accepted docs yet — seed + contrastive only
        print("NOTE: No accepted documents yet. Building mix from seed + contrastive only.")
        print("      Run discovery pipeline to populate corpus/accepted/ before fine-tuning.")
        print()
        counts = {
            "primary":      0,
            "cross_domain": 0,
            "seed":         len(seed_docs),
            "contrastive":  len(contrastive_docs) * CONTRASTIVE_REPS,
            "analogy":      len(analogy_docs) * ANALOGY_REPS,
            "c1":           len(c1_docs) * C1_REPS,
            "c4_coding":    len(c4_coding_docs) * C4_CODING_REPS,
        }

    print("Tier counts:")
    for tier, count in counts.items():
        if count > 0:
            print(f"  {tier:<14} {count:>5}")
    print()

    # --- Replicate tiers to target counts ---
    batches = {
        "primary":      replicate_to_target(primary_docs,     counts["primary"]),
        "cross_domain": replicate_to_target(cross_docs,       counts["cross_domain"]),
        "seed":         replicate_to_target(seed_docs,        counts["seed"]),
        "contrastive":  replicate_to_target(contrastive_docs, counts["contrastive"]),
        "analogy":      replicate_to_target(analogy_docs,     counts["analogy"]),
        "c1":           replicate_to_target(c1_docs,          counts["c1"]),
        "c4_coding":    replicate_to_target(c4_coding_docs,   counts["c4_coding"]),
    }

    # --- Merge and shuffle ---
    all_docs = []
    for tier_docs in batches.values():
        all_docs.extend(tier_docs)

    if shuffle:
        random.shuffle(all_docs)

    # --- Write JSONL ---
    out_dir.mkdir(parents=True, exist_ok=True)
    mix_path = out_dir / "mix.jsonl"
    manifest_path = out_dir / "manifest.json"

    all_tiers = list(counts.keys())
    word_total = 0
    tier_stats: dict[str, dict] = {t: {"count": 0, "words": 0} for t in all_tiers}

    with mix_path.open("w", encoding="utf-8") as fh:
        for doc in all_docs:
            line = {"text": doc["text"]}
            for k in (
                "tier", "source", "arxiv_id", "wrong_claim_id", "degree",
                "analogy_id", "domain", "c1_id", "c4_id"
            ):
                if k in doc:
                    line[k] = doc[k]
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")

            tier = doc.get("tier", "unknown")
            wc   = doc.get("word_count", len(doc["text"].split()))
            if tier in tier_stats:
                tier_stats[tier]["count"] += 1
                tier_stats[tier]["words"] += wc
            word_total += wc

    # Estimate token count (≈ words × 1.33 for English technical text)
    token_estimate = int(word_total * 1.33)

    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "mix_path": str(str(mix_path)),
        "total_documents": len(all_docs),
        "total_words": word_total,
        "estimated_tokens": token_estimate,
        "tier_stats": tier_stats,
        "seed_dir": str(seed_dir),
        "shuffle": shuffle,
    }

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # --- Print summary ---
    print(f"Written: {str(mix_path)}")
    print(f"  Total documents : {len(all_docs):,}")
    print(f"  Total words     : {word_total:,}")
    print(f"  Estimated tokens: {token_estimate:,}")
    print()
    print("Tier breakdown:")
    for tier, stats in tier_stats.items():
        if stats["count"] > 0:
            actual_pct = stats["count"] / max(len(all_docs), 1) * 100
            print(f"  {tier:<14} {stats['count']:>5} docs  {actual_pct:5.1f}%  {stats['words']:>8,} words")
    print()
    print(f"Manifest: {str(manifest_path)}")

    # --- Warnings ---
    if len(primary_docs) == 0:
        print()
        print("WARNING: primary tier is empty. The training mix is seed+contrastive only.")
        print("         This is sufficient for a dry run but not for domain fine-tuning.")
        print("         Run: .venv/bin/python3 pipeline/discover_candidates.py --search --score --save")

    if counts["cross_domain"] == 0:
        print()
        print("NOTE: No cross-domain documents in accepted corpus yet.")
        print("      Cross-domain tier will be omitted from training mix.")

    if token_estimate < 50_000:
        print()
        print(f"WARNING: Only {token_estimate:,} tokens in training mix.")
        print("         Fine-tuning on fewer than 50K tokens will not produce meaningful adaptation.")
        print("         Expand the corpus before running QLoRA training.")

    print()
    print("Next step:")
    print("  .venv/bin/python3 pipeline/run_finetune.py")


if __name__ == "__main__":
    main()
