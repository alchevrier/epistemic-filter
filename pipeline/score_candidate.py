#!/usr/bin/env python3
"""
score_candidate.py — Fetch an ArXiv paper and score it on both quality axes.

Usage:
    python3 pipeline/score_candidate.py <arxiv_id> [--save]

    arxiv_id: e.g. 2301.12345 or https://arxiv.org/abs/2301.12345
    --save: if both axes pass, save accepted document to corpus/accepted/

Output (stdout):
    Domain relevance score  (cosine similarity to seed_v1 centroid)
    Reasoning depth score   (weighted average of 6 structural features)
    Pass / Fail decision

Requires:
    - .venv with numpy and requests
    - Ollama running with nomic-embed-text pulled
    - corpus/centroids/seed_v1.npy computed by compute_seed_centroid.py

Thresholds:
    Domain relevance >= 0.85  (ADR-0001 — fixed)
    Reasoning depth  >= 0.20  (Phase 1 heuristic — calibrated to seed doc baseline)
                     >= 0.80  (Phase 2 fine-tuned classifier — ADR-0001 target)

Note on reasoning depth scoring:
    Phase 1 uses heuristic pattern matching for the 6 structural features
    defined in ADR-0011. The 0.80 ADR-0001 threshold is the Phase 2 fine-tuned
    model target. Phase 1 threshold (0.20) is calibrated against seed documents:
    seed mean score ~0.20, best ~0.36. A paper scoring < 0.20 on Phase 1
    heuristics is rejected. The fine-tuned model in Phase 2 applies the 0.80
    threshold with learned rather than hand-crafted features.
"""

import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
CENTROID_PATH = REPO_ROOT / "corpus" / "centroids" / "seed_v1.npy"
ACCEPTED_DIR = REPO_ROOT / "corpus" / "accepted"
REJECTED_DIR = REPO_ROOT / "corpus" / "rejected_metadata"

OLLAMA_EMBED_URL = "http://localhost:11434/api/embed"
EMBED_MODEL = "nomic-embed-text"

DOMAIN_RELEVANCE_THRESHOLD = 0.85   # ADR-0001 — fixed
REASONING_DEPTH_THRESHOLD = 0.20    # Phase 1 heuristic baseline (ADR-0001 Phase 2 target: 0.80)

# ADR-0011 feature weights
FEATURE_WEIGHTS = {
    "premise_declaration": 0.25,
    "derivation_chain": 0.30,
    "frame_exposure": 0.20,
    "assumption_challenge": 0.10,
    "conclusion_specificity": 0.10,
    "frame_trap_absence": 0.05,
}

# ---------------------------------------------------------------------------
# ArXiv fetching
# ---------------------------------------------------------------------------

ARXIV_API = "http://export.arxiv.org/api/query?id_list={id}"
ARXIV_HTML = "https://arxiv.org/html/{id}"
ARXIV_ABS  = "https://arxiv.org/abs/{id}"


def parse_arxiv_id(raw: str) -> str:
    """Accept bare ID or full URL, return bare ID like '2301.12345'."""
    raw = raw.strip().rstrip("/")
    if raw.startswith("http"):
        path = urlparse(raw).path
        return path.split("/")[-1]
    return raw


def fetch_metadata(arxiv_id: str) -> dict:
    """Fetch title, abstract, authors via ArXiv Atom API."""
    url = ARXIV_API.format(id=arxiv_id)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    root = ET.fromstring(resp.text)
    entry = root.find("atom:entry", ns)
    if entry is None:
        raise ValueError(f"ArXiv ID '{arxiv_id}' not found")

    title = entry.findtext("atom:title", "", ns).strip().replace("\n", " ")
    abstract = entry.findtext("atom:summary", "", ns).strip().replace("\n", " ")
    authors = [
        a.findtext("atom:name", "", ns)
        for a in entry.findall("atom:author", ns)
    ]
    published = entry.findtext("atom:published", "", ns)[:10]

    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "published": published,
        "arxiv_url": ARXIV_ABS.format(id=arxiv_id),
    }


def fetch_full_text(arxiv_id: str) -> str | None:
    """
    Attempt to fetch the HTML version of the paper (ADR-0004: prefer HTML).
    Returns cleaned plain text, or None if unavailable.
    """
    url = ARXIV_HTML.format(id=arxiv_id)
    try:
        resp = requests.get(url, timeout=60, headers={"User-Agent": "epistemic-filter/1.0"})
        if resp.status_code != 200:
            return None
        # Strip HTML tags naively — good enough for embedding
        text = re.sub(r"<[^>]+>", " ", resp.text)
        text = re.sub(r"&[a-z]+;", " ", text)    # HTML entities
        text = re.sub(r"\s+", " ", text).strip()
        # Drop navigation boilerplate at start/end (heuristic: first 500 chars)
        if len(text) > 1000:
            text = text[500:]
        return text
    except requests.exceptions.RequestException:
        return None


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed_text(text: str) -> np.ndarray:
    """Embed text, chunking if necessary. Returns normalised float32 vector."""
    chunks = _chunk(text, max_chars=8000)
    vecs = []
    for chunk in chunks:
        resp = requests.post(
            OLLAMA_EMBED_URL,
            json={"model": EMBED_MODEL, "input": chunk},
            timeout=120,
        )
        resp.raise_for_status()
        vecs.append(np.array(resp.json()["embeddings"][0], dtype=np.float32))
    if len(vecs) == 1:
        v = vecs[0]
    else:
        v = np.mean(vecs, axis=0).astype(np.float32)
    return v / np.linalg.norm(v)


def _chunk(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    paragraphs = text.split("\n\n")
    chunks, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) + 2 > max_chars:
            if current:
                chunks.append(current.strip())
            current = para
        else:
            current = current + "\n\n" + para if current else para
    if current:
        chunks.append(current.strip())
    return chunks or [text[:max_chars]]


# ---------------------------------------------------------------------------
# Domain relevance (Axis 1)
# ---------------------------------------------------------------------------

def score_domain_relevance(embedding: np.ndarray, centroid: np.ndarray) -> float:
    return float(np.dot(embedding, centroid))


# ---------------------------------------------------------------------------
# Reasoning depth (Axis 2) — heuristic Phase 1 classifier
# ---------------------------------------------------------------------------

# ADR-0011 Feature 1 — Explicit Premise Declaration
_PREMISE_POS = re.compile(
    r"\b(we assume|given that|under the (assumption|constraint|model) that"
    r"|starting from|we define|let us define|let [A-Z]\b|precondition"
    r"|we take as given|our model assumes|formally[,:]"
    r"|definition[:\s]|lemma[:\s]|theorem[:\s])\b",
    re.IGNORECASE,
)
_PREMISE_NEG = re.compile(
    r"\b(as is (well known|standard practice|commonly accepted)"
    r"|it is (obvious|clear|trivial) that|everyone knows"
    r"|of course[,\s]|naturally[,\s])\b",
    re.IGNORECASE,
)

# ADR-0011 Feature 2 — Derivation Chain Visibility
_DERIVATION_POS = re.compile(
    r"\b(therefore|it follows (that)?|this implies|hence|thus"
    r"|because [a-z]|since [a-z]|consequently|this means that"
    r"|we (can |now )?conclude|this (shows|demonstrates|proves)"
    r"|from (this|the above)|by (substitution|induction|contradiction)"
    r"|observe that|note that|we note|it can be derived"
    r"|by construction|which (means|implies|shows)|this gives us"
    r"|it is (then|now) (clear|straightforward) that)\b",
    re.IGNORECASE,
)
_DERIVATION_NEG = re.compile(
    r"\b(obviously|clearly[,\s]|trivially|it is easy to see"
    r"|one can show|it can be shown)\b",
    re.IGNORECASE,
)

# ADR-0011 Feature 3 — Frame Exposure
_FRAME_POS = re.compile(
    r"\b(within (the|our|this) (model|framework|assumption|context|system)"
    r"|under (the )?(POSIX|Linux|x86|ARM|shared memory|preemptive|assumption)"
    r"|this (result|conclusion|claim|property) (holds|applies|is valid) (when|if|only if)"
    r"|if (instead|we|one) (assume|assumes|consider|drop|relax)"
    r"|this depends on|conditional on|in contrast to|unlike (prior|previous|existing)"
    r"|where (prior|previous|existing) work (assumes?|takes|treats)"
    r"|under the (standard|conventional|traditional) (assumption|model|approach)"
    r"|assuming (only|that|no|bounded|unbounded)"
    r"|if we (remove|relax|drop|lift) (the|this) assumption"
    r"|this (claim|result|argument) assumes"
    r"|the (limit|boundary|scope) of (this|our) (model|approach|analysis)"
    r"|beyond (this|our) (model|scope|framework))\b",
    re.IGNORECASE,
)
_FRAME_NEG = re.compile(
    r"\b(always|never|universally|in all cases|by definition impossible"
    r"|fundamental(ly)? (requires?|needs?|demands?))\b",
    re.IGNORECASE,
)

# ADR-0011 Feature 4 — Assumption Challenge
_ASSUMPTION_CHALLENGE = re.compile(
    r"\b(we (question|challenge|re-examine|reconsider|ask whether)"
    r"|is (it )?(really |actually )?(necessary|required|unavoidable)"
    r"|(do|does) (we|one) (really |actually )?need"
    r"|the (standard|common|conventional|dominant) (assumption|approach|view)"
    r"|(what|but what) if (instead|we|the)"
    r"|we show that .{0,60} (is not|are not|need not) (required|necessary)"
    r"|contrary to (common belief|the standard|conventional wisdom))\b",
    re.IGNORECASE,
)

# ADR-0011 Feature 5 — Conclusion Specificity
_CONCLUSION_SPECIFIC = re.compile(
    r"(\b\d+[\.,]\d+\s*(%|ns|ms|us|cycles?|bytes?|GB|MB|KB|tokens?|x|×)"
    r"|\breduces? .{0,40} by \d"
    r"|\beliminates? .{0,40} entirely"
    r"|\bprovably\b|\bformal(ly)?\b"
    r"|\bif and only if\b"
    r"|\bO\([0-9n\s\+\*logk]+\)\b"  # big-O notation
    r"|\biff\b)",
    re.IGNORECASE,
)
_CONCLUSION_VAGUE = re.compile(
    r"\b(may (improve|help|reduce|increase)"
    r"|could (potentially|possibly)"
    r"|in some cases|sometimes|often|generally"
    r"|we believe|we think|we hope|we expect"
    r"|likely to|tends? to)\b",
    re.IGNORECASE,
)

# ADR-0011 Feature 6 — Frame Trap Absence (inverse score — penalise trap language)
_FRAME_TRAP = re.compile(
    r"\b(the (correct|right|best|optimal|proper) (solution|approach|way)"
    r"|solves? the (problem of|issue of|challenge of)"
    r"|is the answer to"
    r"|eliminates? the need for .{0,30} entirely"  # only if compensation framing
    r"|the (industry|community|standard) (solution|approach))\b",
    re.IGNORECASE,
)


def _density(matches: list, word_count: int) -> float:
    """Normalise match count to [0, 1] based on rate per 100 words.

    Saturates at 0.3 matches per 100 words (≈ 66 matches in a 22k-word paper).
    Calibrated against seed document scores: best seed ~0.36, mean ~0.22.
    """
    if word_count == 0:
        return 0.0
    rate = len(matches) / max(word_count / 100, 1)  # per 100 words
    return min(1.0, rate / 0.3)  # saturates at 0.3 matches per 100 words


def score_reasoning_depth(text: str) -> dict:
    """
    Score all 6 ADR-0011 features. Returns feature scores and weighted total.
    Phase 1: heuristic pattern matching. Calibrated conservatively.
    """
    words = text.split()
    wc = max(len(words), 1)

    # Feature 1 — Premise Declaration
    pos1 = _PREMISE_POS.findall(text)
    neg1 = _PREMISE_NEG.findall(text)
    f1 = max(0.0, min(1.0, _density(pos1, wc) * 2.0 - _density(neg1, wc) * 1.5))

    # Feature 2 — Derivation Chain
    pos2 = _DERIVATION_POS.findall(text)
    neg2 = _DERIVATION_NEG.findall(text)
    f2 = max(0.0, min(1.0, _density(pos2, wc) * 2.0 - _density(neg2, wc) * 2.0))

    # Feature 3 — Frame Exposure
    pos3 = _FRAME_POS.findall(text)
    neg3 = _FRAME_NEG.findall(text)
    f3 = max(0.0, min(1.0, _density(pos3, wc) * 2.5 - _density(neg3, wc) * 1.0))

    # Feature 4 — Assumption Challenge
    pos4 = _ASSUMPTION_CHALLENGE.findall(text)
    f4 = min(1.0, _density(pos4, wc) * 4.0)  # rarer signal, amplify

    # Feature 5 — Conclusion Specificity
    pos5 = _CONCLUSION_SPECIFIC.findall(text)
    neg5 = _CONCLUSION_VAGUE.findall(text)
    f5 = max(0.0, min(1.0, _density(pos5, wc) * 2.0 - _density(neg5, wc) * 0.5))

    # Feature 6 — Frame Trap Absence (1.0 = no traps, 0.0 = many traps)
    trap6 = _FRAME_TRAP.findall(text)
    f6 = max(0.0, 1.0 - _density(trap6, wc) * 3.0)

    features = {
        "premise_declaration": round(f1, 3),
        "derivation_chain": round(f2, 3),
        "frame_exposure": round(f3, 3),
        "assumption_challenge": round(f4, 3),
        "conclusion_specificity": round(f5, 3),
        "frame_trap_absence": round(f6, 3),
    }

    weighted = sum(features[k] * FEATURE_WEIGHTS[k] for k in FEATURE_WEIGHTS)

    return {"features": features, "score": round(weighted, 4)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]
    if not args:
        print("Usage: score_candidate.py <arxiv_id> [--save]")
        sys.exit(1)

    save = "--save" in args
    raw_id = next(a for a in args if not a.startswith("--"))
    arxiv_id = parse_arxiv_id(raw_id)

    # Load centroid
    if not CENTROID_PATH.exists():
        print(f"ERROR: centroid not found at {CENTROID_PATH}")
        print("Run pipeline/compute_seed_centroid.py first.")
        sys.exit(1)
    centroid = np.load(CENTROID_PATH)

    print(f"Scoring: {arxiv_id}")
    print(f"  https://arxiv.org/abs/{arxiv_id}")
    print()

    # Fetch metadata
    print("Fetching metadata ...", end=" ", flush=True)
    try:
        meta = fetch_metadata(arxiv_id)
    except Exception as e:
        print(f"FAILED: {e}")
        sys.exit(1)
    print("done")
    print(f"  Title    : {meta['title']}")
    print(f"  Authors  : {', '.join(meta['authors'][:3])}" +
          (f" +{len(meta['authors'])-3} more" if len(meta['authors']) > 3 else ""))
    print(f"  Published: {meta['published']}")
    print()

    # Fetch full text
    print("Fetching full text (HTML) ...", end=" ", flush=True)
    full_text = fetch_full_text(arxiv_id)
    if full_text:
        approx_tokens = len(full_text.split()) * 4 // 3
        print(f"done (~{approx_tokens:,} tokens)")
        score_text = full_text
        text_source = "full_text_html"
    else:
        print("unavailable — scoring on abstract only")
        score_text = meta["title"] + "\n\n" + meta["abstract"]
        text_source = "abstract_only"
    print()

    # Embed
    print("Embedding ...", end=" ", flush=True)
    embedding = embed_text(score_text)
    print("done")

    # Axis 1 — Domain relevance
    relevance = score_domain_relevance(embedding, centroid)
    relevance_pass = relevance >= DOMAIN_RELEVANCE_THRESHOLD

    # Axis 2 — Reasoning depth
    depth_result = score_reasoning_depth(score_text)
    depth = depth_result["score"]
    depth_pass = depth >= REASONING_DEPTH_THRESHOLD

    # Decision
    decision = "ACCEPT" if (relevance_pass and depth_pass) else "REJECT"
    if relevance_pass and not depth_pass:
        reason = "fails reasoning depth"
    elif depth_pass and not relevance_pass:
        reason = "fails domain relevance"
    elif not relevance_pass and not depth_pass:
        reason = "fails both axes"
    else:
        reason = "passes both axes"

    # Output
    print()
    print("=" * 60)
    print(f"  DECISION : {decision}  ({reason})")
    print("=" * 60)
    print()
    print(f"  Axis 1 — Domain Relevance : {relevance:.4f}  "
          f"(threshold {DOMAIN_RELEVANCE_THRESHOLD})  "
          f"{'✓' if relevance_pass else '✗'}")
    print()
    print(f"  Axis 2 — Reasoning Depth  : {depth:.4f}  "
          f"(threshold {REASONING_DEPTH_THRESHOLD})  "
          f"{'✓' if depth_pass else '✗'}")
    print()
    print("  Feature breakdown:")
    for feat, score in depth_result["features"].items():
        weight = FEATURE_WEIGHTS[feat]
        contrib = score * weight
        bar = "█" * int(score * 20)
        print(f"    {feat:<26} {score:.3f} × {weight:.2f} = {contrib:.3f}  {bar}")
    print()
    print(f"  Text source: {text_source}")
    print()

    # Save result
    record = {
        "arxiv_id": arxiv_id,
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "reason": reason,
        "text_source": text_source,
        "axis1_domain_relevance": round(relevance, 4),
        "axis1_pass": relevance_pass,
        "axis2_reasoning_depth": round(depth, 4),
        "axis2_pass": depth_pass,
        "reasoning_depth_features": depth_result["features"],
        "metadata": meta,
    }

    if decision == "ACCEPT" and save:
        ACCEPTED_DIR.mkdir(parents=True, exist_ok=True)
        doc_dir = ACCEPTED_DIR / arxiv_id
        doc_dir.mkdir(exist_ok=True)
        (doc_dir / "text.txt").write_text(score_text, encoding="utf-8")
        (doc_dir / "record.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )
        print(f"  Saved to: corpus/accepted/{arxiv_id}/")
    elif decision == "REJECT":
        REJECTED_DIR.mkdir(parents=True, exist_ok=True)
        (REJECTED_DIR / f"{arxiv_id}.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )
        print(f"  Rejection metadata saved to: corpus/rejected_metadata/{arxiv_id}.json")

    if decision == "ACCEPT" and not save:
        print("  (Run with --save to persist accepted document to corpus)")


if __name__ == "__main__":
    main()
