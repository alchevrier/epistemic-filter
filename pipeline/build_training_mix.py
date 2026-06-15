#!/usr/bin/env python3
"""
build_training_mix.py — Assemble the QLoRA training dataset from the curated corpus.

Reads:
    corpus/accepted/*/             — accepted documents (text.txt + record.json)
    corpus/seed/                   — seed corpus (clock-aware-programming docs)
    corpus/known-wrong-claims.json — W-register for contrastive examples

Writes:
    corpus/training/mix.jsonl      — full training dataset, JSONL format
    corpus/training/manifest.json  — stats and split summary

Format of each JSONL line:
    {"text": "...", "tier": "primary|cross_domain|contrastive|seed", "source": "..."}

Tier ratios (ADR-0012):
    primary      60%  — accepted corpus, next-token prediction
    cross_domain 15%  — accepted corpus docs tagged as cross-domain, with bridge annotation
    contrastive  15%  — W-register contrastive pairs (CONTEXT / CLAIM / DEGREE / REFUTATION / BRIDGE)
    seed         10%  — seed corpus repeated to anchor the prior every epoch

Usage:
    python3 pipeline/build_training_mix.py [--seed-dir PATH] [--out-dir PATH] [--epoch-tokens N]

    --seed-dir PATH     Path to seed corpus directory (default: ../clock-aware-programming/docs)
    --out-dir PATH      Output directory (default: corpus/training)
    --epoch-tokens N    Target epoch token count for ratio replication (default: 1_000_000)
    --no-shuffle        Preserve tier order in output (for inspection)

Output format is compatible with the HuggingFace `datasets` / `trl` SFT trainer:
    Each line is {"text": "<full document text>"} with optional metadata fields.
    The 'text' field is the full training string — no prompt/response split for
    primary/seed tiers (continuation/next-token prediction).
    Contrastive examples use the structured format from ADR-0012.
"""

import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_SEED_DIR = Path("/home/alchevrier/Repositories/clock-aware-programming/docs")
DEFAULT_OUT_DIR  = REPO_ROOT / "corpus" / "training"

ACCEPTED_DIR     = REPO_ROOT / "corpus" / "accepted"
WRONG_CLAIMS_PATH = REPO_ROOT / "corpus" / "known-wrong-claims.json"

# ADR-0012 tier ratios
TIER_RATIOS = {
    "primary":      0.60,
    "cross_domain": 0.15,
    "contrastive":  0.15,
    "seed":         0.10,
}

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

# ---------------------------------------------------------------------------
# Contrastive format (ADR-0012)
# ---------------------------------------------------------------------------

CONTRASTIVE_TEMPLATE = """\
[CONTEXT] The following claim appears in systems and concurrency literature. \
It is partially or wholly incorrect within the clock-aware-programming frame. \
The degree of incorrectness is annotated.
[CLAIM] {claim}
[DEGREE] {degree}
[REFUTATION] {refutation}
[BRIDGE] The claim rests on the assumption that execution timing is undeclared. \
When timing is declared at compile time — via channel ownership, budget_ticks, \
and the dispatch table — the mechanism the claim treats as necessary becomes \
structurally redundant. The claim is correct within the frame it assumes; \
it fails when that frame is replaced by compile-time declarations.\
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_seed_docs(seed_dir: Path) -> list[dict]:
    """Load all .md files from the seed corpus directory."""
    docs = []
    for f in sorted(seed_dir.rglob("*.md")):
        if f.name in ("index.md",):
            continue
        text = f.read_text(encoding="utf-8").strip()
        if len(text.split()) < 50:  # skip stubs
            continue
        docs.append({
            "text": text,
            "tier": "seed",
            "source": str(f.relative_to(seed_dir.parent)),
            "word_count": len(text.split()),
        })
    return docs


def load_accepted_docs() -> tuple[list[dict], list[dict]]:
    """
    Load accepted corpus documents.
    Returns (primary_docs, cross_domain_docs).
    A document is cross-domain if its title/abstract contains cross-domain keywords.
    """
    primary, cross_domain = [], []
    if not ACCEPTED_DIR.exists():
        return primary, cross_domain

    for doc_dir in sorted(ACCEPTED_DIR.iterdir()):
        text_path   = doc_dir / "text.txt"
        record_path = doc_dir / "record.json"
        if not text_path.exists():
            continue

        text = text_path.read_text(encoding="utf-8").strip()
        record = {}
        if record_path.exists():
            record = json.loads(record_path.read_text(encoding="utf-8"))

        meta = record.get("metadata", {})
        title    = meta.get("title", "").lower()
        abstract = meta.get("abstract", "").lower()
        haystack = title + " " + abstract

        is_cross = any(kw in haystack for kw in CROSS_DOMAIN_KEYWORDS)
        entry = {
            "text": text,
            "tier": "cross_domain" if is_cross else "primary",
            "source": f"corpus/accepted/{doc_dir.name}",
            "arxiv_id": record.get("arxiv_id", doc_dir.name),
            "word_count": len(text.split()),
        }
        if is_cross:
            entry["text"] = _prepend_bridge(text, meta)
            cross_domain.append(entry)
        else:
            primary.append(entry)

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
    """Build contrastive training examples from the W-register."""
    if not WRONG_CLAIMS_PATH.exists():
        return []
    claims = json.loads(WRONG_CLAIMS_PATH.read_text(encoding="utf-8"))
    examples = []
    for entry in claims:
        text = CONTRASTIVE_TEMPLATE.format(
            claim=entry["claim"],
            degree=entry["degree"],
            refutation=entry["refutation"],
        )
        examples.append({
            "text": text,
            "tier": "contrastive",
            "source": f"corpus/known-wrong-claims.json#{entry['id']}",
            "wrong_claim_id": entry["id"],
            "degree": entry["degree"],
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
    epoch_tokens = 1_000_000

    for i, a in enumerate(args):
        if a == "--seed-dir" and i + 1 < len(args):
            seed_dir = Path(args[i + 1])
        elif a == "--out-dir" and i + 1 < len(args):
            out_dir = Path(args[i + 1])
        elif a == "--epoch-tokens" and i + 1 < len(args):
            epoch_tokens = int(args[i + 1])

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

    total_base = len(seed_docs) + len(primary_docs) + len(cross_docs) + len(contrastive_docs)
    if total_base == 0:
        print("\nERROR: No documents found in any tier.")
        print("  Run pipeline/discover_candidates.py --search --score --save first.")
        sys.exit(1)

    print()

    # --- Determine counts for each tier ---
    # Strategy: use natural count for whichever tier has data, then replicate
    # others to match the ADR-0012 ratios. The controlling tier is whichever
    # is largest relative to its ratio — we don't over-replicate that one.
    #
    # If accepted corpus is empty (early pipeline), scale from seed docs.
    if primary_docs:
        # Primary is the natural anchor at 60%
        primary_count = len(primary_docs)
        total_target  = int(primary_count / TIER_RATIOS["primary"])
    else:
        # No accepted docs yet — scale from seed at 10%, contrastive at 15%
        seed_count    = len(seed_docs)
        total_target  = int(seed_count / TIER_RATIOS["seed"])
        primary_count = 0
        print("NOTE: No accepted documents yet. Building mix from seed + contrastive only.")
        print("      Run discovery pipeline to populate corpus/accepted/ before fine-tuning.")
        print()

    counts = {
        "primary":      primary_count,
        "cross_domain": max(1, int(total_target * TIER_RATIOS["cross_domain"])) if cross_docs else 0,
        "contrastive":  max(1, int(total_target * TIER_RATIOS["contrastive"])) if contrastive_docs else 0,
        "seed":         max(1, int(total_target * TIER_RATIOS["seed"])),
    }

    print("Target tier counts:")
    for tier, count in counts.items():
        print(f"  {tier:<14} {count:>5}  ({TIER_RATIOS[tier]*100:.0f}%)")
    print()

    # --- Replicate tiers to target counts ---
    batches = {
        "primary":      replicate_to_target(primary_docs,     counts["primary"]),
        "cross_domain": replicate_to_target(cross_docs,       counts["cross_domain"]),
        "contrastive":  replicate_to_target(contrastive_docs, counts["contrastive"]),
        "seed":         replicate_to_target(seed_docs,        counts["seed"]),
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

    word_total = 0
    tier_stats: dict[str, dict] = {t: {"count": 0, "words": 0} for t in TIER_RATIOS}

    with mix_path.open("w", encoding="utf-8") as fh:
        for doc in all_docs:
            # Write only 'text' + light metadata to keep the file trainer-friendly
            line = {"text": doc["text"]}
            # Include metadata as passthrough fields (ignored by most trainers)
            for k in ("tier", "source", "arxiv_id", "wrong_claim_id", "degree"):
                if k in doc:
                    line[k] = doc[k]
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")

            tier = doc["tier"]
            wc   = doc.get("word_count", len(doc["text"].split()))
            tier_stats[tier]["count"] += 1
            tier_stats[tier]["words"] += wc
            word_total += wc

    # Estimate token count (≈ words × 1.33 for English technical text)
    token_estimate = int(word_total * 1.33)

    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "mix_path": str(mix_path.relative_to(REPO_ROOT)),
        "total_documents": len(all_docs),
        "total_words": word_total,
        "estimated_tokens": token_estimate,
        "epoch_token_target": epoch_tokens,
        "epochs_to_cover_target": round(epoch_tokens / max(token_estimate, 1), 2),
        "tier_stats": tier_stats,
        "tier_ratios_actual": {
            t: round(tier_stats[t]["count"] / max(len(all_docs), 1), 3)
            for t in TIER_RATIOS
        },
        "adr": "ADR-0012",
        "seed_dir": str(seed_dir),
        "shuffle": shuffle,
    }

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # --- Print summary ---
    print(f"Written: {mix_path.relative_to(REPO_ROOT)}")
    print(f"  Total documents : {len(all_docs):,}")
    print(f"  Total words     : {word_total:,}")
    print(f"  Estimated tokens: {token_estimate:,}")
    print()
    print("Tier breakdown:")
    for tier, stats in tier_stats.items():
        actual_pct = stats["count"] / max(len(all_docs), 1) * 100
        print(f"  {tier:<14} {stats['count']:>5} docs  {actual_pct:5.1f}%  {stats['words']:>8,} words")
    print()
    print(f"Manifest: {manifest_path.relative_to(REPO_ROOT)}")

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
