#!/usr/bin/env python3
"""
discover_candidates.py — Feed the scorer with ArXiv candidates.

Two modes, combinable:

  search   — Query ArXiv across category + keyword combinations that overlap
             the domain defined by the seed centroid.

  expand   — Given ArXiv IDs of accepted papers, pull their reference lists
             via Semantic Scholar and add new IDs to the candidate queue.

Usage:
    python3 pipeline/discover_candidates.py [--search] [--expand] [--score] [--save] [--limit N]

    --search        Run ArXiv keyword search (default if no mode flag given)
    --expand        Run citation graph expansion from accepted corpus
    --score         Pipe each new candidate through score_candidate.py
    --save          Pass --save to score_candidate.py (only relevant with --score)
    --limit N       Cap number of new candidates to process (default: 50)
    --dry-run       Print candidate IDs without scoring

Output:
    List of candidate ArXiv IDs not yet scored (stdout), one per line.
    With --score: scoring results appear inline.

Sources:
    Axis 1 — ArXiv Atom API  (no key required)
    Axis 2 — Semantic Scholar API  (no key required, rate-limited to 1 req/s)

Deduplication:
    Any ID already present in corpus/accepted/ or corpus/rejected_metadata/
    is skipped silently. This makes the script safe to run repeatedly.
"""

import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

import requests

REPO_ROOT = Path(__file__).parent.parent
ACCEPTED_DIR = REPO_ROOT / "corpus" / "accepted"
REJECTED_DIR = REPO_ROOT / "corpus" / "rejected_metadata"

ARXIV_SEARCH = "http://export.arxiv.org/api/query?search_query={q}&start={start}&max_results={n}&sortBy=relevance"
S2_REFERENCES = "https://api.semanticscholar.org/graph/v1/paper/arXiv:{id}/references?fields=externalIds,title&limit=100"
S2_CITATIONS  = "https://api.semanticscholar.org/graph/v1/paper/arXiv:{id}/citations?fields=externalIds,title&limit=100"

# ---------------------------------------------------------------------------
# Domain search queries
# Each tuple is (categories, keyword_terms).
# ArXiv search syntax: cat:cs.OS AND all:"term"
# Multiple categories use OR: (cat:cs.OS OR cat:cs.PL)
# ---------------------------------------------------------------------------

SEARCH_QUERIES = [
    # Time-triggered architecture / TDMA formal (Kopetz TTA, FlexRay, TT-Ethernet)
    (
        "(cat:cs.OS OR cat:cs.AR OR cat:cs.NI)",
        '"time-triggered" AND ("formal" OR "deterministic" OR "verification" OR "scheduling")',
    ),
    # Temporal isolation / time protection (seL4, capability OS)
    (
        "(cat:cs.OS OR cat:cs.CR)",
        '("temporal isolation" OR "time protection" OR "determinism") AND ("kernel" OR "hypervisor" OR "verified")',
    ),
    # WCET static analysis — tighter focus than previous (abstract interpretation, ILP)
    (
        "(cat:cs.OS OR cat:cs.PL OR cat:cs.AR)",
        '"worst-case execution time" AND ("abstract interpretation" OR "implicit path" OR "integer linear")',
    ),
    # Time-sensitive networking / deterministic Ethernet (TSN, IEEE 802.1Qbv)
    (
        "(cat:cs.NI OR cat:cs.AR)",
        '("time-sensitive networking" OR "TSN" OR "802.1Qbv") AND ("formal" OR "scheduling" OR "deterministic")',
    ),
    # Partition scheduling / separation kernel (ARINC 653, MILS, LynxOS)
    (
        "(cat:cs.OS OR cat:cs.CR)",
        '("partition scheduling" OR "separation kernel" OR "ARINC 653") AND ("real-time" OR "formal" OR "isolation")',
    ),
    # Type-based resource bounds / compile-time cost (RAML, sized types)
    (
        "(cat:cs.PL OR cat:cs.LO)",
        '("resource-aware" OR "sized types" OR "amortized complexity") AND ("type system" OR "compile-time" OR "static")',
    ),
    # Unikernel verified OS (MirageOS, Unikraft, HaLVM, IncludeOS)
    (
        "(cat:cs.OS OR cat:cs.PL)",
        '("unikernel" OR "MirageOS" OR "Unikraft" OR "IncludeOS") AND ("verified" OR "formal" OR "deterministic" OR "safe")',
    ),
    # Static task scheduling / rate-monotonic proof
    (
        "(cat:cs.OS OR cat:cs.AR)",
        '("rate-monotonic" OR "EDF" OR "cyclic executive") AND ("formal" OR "proof" OR "verified" OR "schedulability")',
    ),
    # Ownership + real-time / Rust embedded systems formal
    (
        "(cat:cs.PL OR cat:cs.OS)",
        '("ownership" OR "borrow") AND ("real-time" OR "embedded" OR "deterministic") AND ("Rust" OR "linear type" OR "affine")',
    ),
    # Hardware time-partitioning / memory-mapped timing (FPGA, co-design)
    (
        "(cat:cs.AR OR cat:cs.OS)",
        '("time partition" OR "temporal partition") AND ("hardware" OR "FPGA" OR "co-design" OR "reconfigurable")',
    ),
    # Compile-time memory layout / static allocation formal
    (
        "(cat:cs.PL OR cat:cs.AR)",
        '("compile-time" OR "static allocation") AND ("memory layout" OR "stack bound" OR "region") AND ("formal" OR "proof" OR "verified")',
    ),
    # Deterministic replay / causal consistency compile-time
    (
        "(cat:cs.OS OR cat:cs.PL OR cat:cs.DC)",
        '("deterministic execution" OR "deterministic replay") AND ("compile-time" OR "static" OR "formal")',
    ),
    # Poll-mode / kernel-bypass with determinism guarantees
    (
        "(cat:cs.NI OR cat:cs.OS)",
        '("kernel bypass" OR "DPDK" OR "RDMA") AND ("deterministic" OR "bounded latency" OR "worst-case")',
    ),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_scored_ids() -> set[str]:
    """Return IDs already accepted or rejected (normalised, no version suffix)."""
    ids = set()
    for p in ACCEPTED_DIR.glob("*/"):
        ids.add(_normalise(p.name))
    for p in REJECTED_DIR.glob("*.json"):
        ids.add(_normalise(p.stem))
    return ids


def _normalise(arxiv_id: str) -> str:
    """Strip version suffix: '2301.12345v2' -> '2301.12345'."""
    return re.sub(r"v\d+$", "", arxiv_id.strip())


def search_arxiv(categories: str, terms: str, max_results: int = 25) -> list[tuple[str, str]]:
    """Return list of (arxiv_id, title) from an ArXiv search."""
    q = quote(f"{categories} AND all:{terms}")
    url = ARXIV_SEARCH.format(q=q, start=0, n=max_results)
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"  [search] ArXiv request failed: {e}", file=sys.stderr)
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(resp.text)
    results = []
    for entry in root.findall("atom:entry", ns):
        raw_id = entry.findtext("atom:id", "", ns).split("/")[-1]
        arxiv_id = _normalise(raw_id)
        title = entry.findtext("atom:title", "", ns).strip().replace("\n", " ")
        results.append((arxiv_id, title))
    return results


def expand_citations(arxiv_id: str, delay: float = 1.1) -> list[tuple[str, str]]:
    """
    Return (arxiv_id, title) pairs from the reference list of arxiv_id.
    Uses Semantic Scholar free tier — 1 req/s.
    """
    found = []
    for url_template in (S2_REFERENCES, S2_CITATIONS):
        url = url_template.format(id=arxiv_id)
        try:
            resp = requests.get(url, timeout=20, headers={"User-Agent": "epistemic-filter/1.0"})
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", [])
            for item in items:
                paper = item.get("citedPaper") or item.get("citingPaper") or {}
                ext = paper.get("externalIds") or {}
                aid = ext.get("ArXiv")
                if aid:
                    title = paper.get("title", "")
                    found.append((_normalise(aid), title))
            time.sleep(delay)
        except requests.exceptions.RequestException as e:
            print(f"  [expand] S2 request failed for {arxiv_id}: {e}", file=sys.stderr)
    return found


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]
    do_search = "--search" in args or "--expand" not in args  # default to search
    do_expand = "--expand" in args
    do_score  = "--score"   in args
    do_save   = "--save"    in args
    dry_run   = "--dry-run" in args
    limit = 50
    for i, a in enumerate(args):
        if a == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])

    scored = load_scored_ids()
    print(f"Already scored: {len(scored)} IDs", file=sys.stderr)

    candidates: dict[str, str] = {}  # id -> title

    # --- ArXiv search ---
    if do_search:
        print(f"\nRunning {len(SEARCH_QUERIES)} ArXiv search queries ...", file=sys.stderr)
        for cats, terms in SEARCH_QUERIES:
            short = terms[:60].replace("\n", " ")
            print(f"  {short} ...", end=" ", flush=True, file=sys.stderr)
            results = search_arxiv(cats, terms, max_results=20)
            new = [(aid, t) for aid, t in results if aid not in scored and aid not in candidates]
            for aid, title in new:
                candidates[aid] = title
            print(f"{len(new)} new", file=sys.stderr)
            time.sleep(0.4)  # polite ArXiv rate

    # --- Citation expansion ---
    if do_expand:
        accepted_ids = [p.name for p in ACCEPTED_DIR.glob("*/") if p.is_dir()]
        if not accepted_ids:
            print("\n[expand] No accepted papers yet — run --search and --score first.", file=sys.stderr)
        else:
            print(f"\nExpanding citations from {len(accepted_ids)} accepted papers ...", file=sys.stderr)
            for aid in accepted_ids:
                print(f"  {aid} ...", end=" ", flush=True, file=sys.stderr)
                refs = expand_citations(aid)
                new = [(r, t) for r, t in refs if r not in scored and r not in candidates]
                for r, title in new:
                    candidates[r] = title
                print(f"{len(new)} new", file=sys.stderr)

    # Deduplicate final list and apply limit
    queue = list(candidates.items())[:limit]

    print(f"\nCandidates to process: {len(queue)} (limit {limit})", file=sys.stderr)

    if not queue:
        print("No new candidates found.", file=sys.stderr)
        sys.exit(0)

    if dry_run:
        for aid, title in queue:
            print(f"{aid}\t{title}")
        sys.exit(0)

    if not do_score:
        # Just print IDs
        for aid, _title in queue:
            print(aid)
        sys.exit(0)

    # --- Score each candidate ---
    score_cmd = [
        sys.executable,
        str(Path(__file__).parent / "score_candidate.py"),
    ]
    if do_save:
        score_cmd.append("--save")

    print(file=sys.stderr)
    accepted_count = 0
    rejected_count = 0

    for i, (aid, title) in enumerate(queue, 1):
        print(f"[{i}/{len(queue)}] {aid}  {title[:60]}", file=sys.stderr)
        result = subprocess.run(
            score_cmd + [aid],
            capture_output=False,
        )
        if result.returncode != 0:
            print(f"  [error] scorer exited {result.returncode}", file=sys.stderr)
        print(file=sys.stderr)
        time.sleep(2)  # polite pause between candidates to avoid ArXiv 429

    print(
        f"Done. Processed {len(queue)} candidates.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
