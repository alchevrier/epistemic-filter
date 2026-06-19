#!/usr/bin/env python3
"""
compute_seed_centroid.py — Embed seed documents and compute the root centroid.

Usage:
    python3 pipeline/compute_seed_centroid.py

Requirements:
    - Ollama running locally with nomic-embed-text pulled
    - .venv with numpy and requests installed

Output:
    corpus/centroids/seed_v1.npy   — centroid vector (float32, shape [768])
    corpus/centroids/seed_v1.json  — metadata: per-document similarity to centroid,
                                     document paths, token counts, timestamp
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
SEED_DIR = Path("/home/alchevrier/Repositories/clock-aware-programming/docs")
CENTROID_DIR = REPO_ROOT / "corpus" / "centroids"
OLLAMA_URL = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"

# ADR-0016: exclude index/README files — they are navigation, not derivation
EXCLUDE_FILENAMES = {"index.md", "README.md"}

# ADR-0016: target internal similarity range 0.75-0.92 for multi-author seeds.
# Single-author seeds (all documents from one consistent prior) will naturally
# cluster tighter -- values up to 0.98 are expected and correct.
# The HIGH warning is informational only for single-author seeds.
SIMILARITY_WARN_LOW = 0.75
SIMILARITY_WARN_HIGH = 0.92

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def collect_seed_files(seed_dir: Path) -> list[Path]:
    """Collect all .md files from the seed directory, excluding nav files."""
    files = sorted(
        f for f in seed_dir.rglob("*.md")
        if f.name not in EXCLUDE_FILENAMES
    )
    return files


def embed(text: str) -> np.ndarray:
    """Embed text via Ollama nomic-embed-text. Returns float32 vector."""
    resp = requests.post(
        "http://localhost:11434/api/embed",
        json={"model": EMBED_MODEL, "input": text},
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    # /api/embed returns {"embeddings": [[...]]}
    vec = np.array(data["embeddings"][0], dtype=np.float32)
    return vec


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def chunk_text(text: str, max_tokens: int = 2000) -> list[str]:
    """
    nomic-embed-text supports 8192 tokens. Split on paragraph boundaries
    to stay safely below the limit. For seed documents this is rarely needed
    but handled defensively.
    Approximation: 1 token ≈ 4 chars.
    """
    max_chars = max_tokens * 4
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
    return chunks


def embed_document(path: Path) -> tuple[np.ndarray, int]:
    """
    Embed a document, averaging chunk embeddings if the document is long.
    Returns (embedding vector, approximate token count).
    """
    text = path.read_text(encoding="utf-8")
    approx_tokens = len(text) // 4
    chunks = chunk_text(text)
    if len(chunks) == 1:
        return embed(chunks[0]), approx_tokens
    chunk_vecs = [embed(c) for c in chunks]
    avg = np.mean(chunk_vecs, axis=0).astype(np.float32)
    avg = avg / np.linalg.norm(avg)  # re-normalise after averaging
    return avg, approx_tokens


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # Check Ollama is reachable
    try:
        requests.get("http://localhost:11434", timeout=5)
    except requests.exceptions.ConnectionError:
        print("ERROR: Ollama is not running. Start it with: ollama serve")
        sys.exit(1)

    print(f"Embedding model : {EMBED_MODEL}")
    print(f"Seed directory  : {SEED_DIR}")
    print()

    seed_files = collect_seed_files(SEED_DIR)
    if len(seed_files) < 5:
        print(f"WARNING: only {len(seed_files)} seed files found. "
              "ADR-0016 minimum is 5. Check SEED_DIR.")

    print(f"Found {len(seed_files)} seed documents:")
    for f in seed_files:
        print(f"  {f.relative_to(SEED_DIR.parent)}")
    print()

    # Embed all documents
    embeddings = []
    records = []
    for path in seed_files:
        print(f"Embedding: {path.name} ...", end=" ", flush=True)
        vec, tokens = embed_document(path)
        embeddings.append(vec)
        records.append({
            "path": str(path),
            "relative_path": str(path.relative_to(SEED_DIR.parent)),
            "approx_tokens": tokens,
        })
        print(f"done ({tokens:,} tokens approx)")

    # Compute centroid
    matrix = np.stack(embeddings, axis=0)  # shape [N, D]
    centroid = matrix.mean(axis=0).astype(np.float32)
    centroid = centroid / np.linalg.norm(centroid)  # normalise

    # Pairwise similarities to centroid
    print()
    print("Cosine similarity to centroid:")
    print(f"  {'Document':<55} {'Similarity':>10}")
    print(f"  {'-'*55} {'-'*10}")
    similarities = []
    for i, (path, rec) in enumerate(zip(seed_files, records)):
        sim = cosine_similarity(embeddings[i], centroid)
        similarities.append(sim)
        rec["centroid_similarity"] = round(sim, 4)
        flag = ""
        if sim < SIMILARITY_WARN_LOW:
            flag = "  ← LOW (consider removing)"
        elif sim > SIMILARITY_WARN_HIGH:
            flag = "  ← HIGH (seed may be too narrow)"
        label = path.relative_to(SEED_DIR.parent)
        print(f"  {str(label):<55} {sim:.4f}{flag}")

    sim_array = np.array(similarities)
    print()
    print(f"  Min similarity : {sim_array.min():.4f}")
    print(f"  Max similarity : {sim_array.max():.4f}")
    print(f"  Mean similarity: {sim_array.mean():.4f}")
    print(f"  Std similarity : {sim_array.std():.4f}")
    print()

    # ADR-0016 range check
    in_range = (sim_array >= SIMILARITY_WARN_LOW) & (sim_array <= SIMILARITY_WARN_HIGH)
    out_of_range = (~in_range).sum()
    if out_of_range == 0:
        print(f"✓ All documents within target similarity range "
              f"[{SIMILARITY_WARN_LOW}, {SIMILARITY_WARN_HIGH}]")
    else:
        print(f"⚠ {out_of_range} document(s) outside target range "
              f"[{SIMILARITY_WARN_LOW}, {SIMILARITY_WARN_HIGH}] — review before locking seed")

    # Save centroid
    CENTROID_DIR.mkdir(parents=True, exist_ok=True)
    centroid_path = CENTROID_DIR / "seed_v1.npy"
    np.save(centroid_path, centroid)
    print(f"\nCentroid saved : {centroid_path}")
    print(f"  Shape  : {centroid.shape}")
    print(f"  Dtype  : {centroid.dtype}")
    print(f"  Norm   : {np.linalg.norm(centroid):.6f} (should be 1.0)")

    # Save metadata
    metadata = {
        "version": "seed_v1",
        "created": datetime.now(timezone.utc).isoformat(),
        "embed_model": EMBED_MODEL,
        "seed_dir": str(SEED_DIR),
        "document_count": len(seed_files),
        "centroid_shape": list(centroid.shape),
        "similarity_stats": {
            "min": round(float(sim_array.min()), 4),
            "max": round(float(sim_array.max()), 4),
            "mean": round(float(sim_array.mean()), 4),
            "std": round(float(sim_array.std()), 4),
        },
        "target_range": [SIMILARITY_WARN_LOW, SIMILARITY_WARN_HIGH],
        "documents": records,
    }
    meta_path = CENTROID_DIR / "seed_v1.json"
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Metadata saved : {meta_path}")

    print()
    print("Next step: run pipeline/score_candidate.py <arxiv_id> to score a candidate document.")


if __name__ == "__main__":
    main()
