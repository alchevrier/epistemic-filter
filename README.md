# Epistemic Filter
#### Alex Chevrier — chevrier.alex@gmail.com

> A two-axis data quality filter for bootstrapping domain-specific LLMs: domain relevance scored against a seed corpus, reasoning depth scored by structural first-principles analysis. Precision over recall. Quality over volume.

---

*The thinking in this project is mine. The writing was produced with AI assistance (GitHub Copilot / Claude).*

---

**Started: 2026-06-15.**

---

## The Problem

Training a domain-specific LLM requires a high-quality corpus. Finding one is the hard part. Web crawls are noisy. Academic databases are large but undifferentiated — a survey paper and a first-principles derivation paper look similar to a keyword filter, but only one of them trains a model that can reason rather than pattern-match.

The bottleneck is not data volume. It is **epistemic quality** — the fraction of the corpus that contains genuine derivation chains, not just domain vocabulary.

A human expert solves this by skimming. They discard most papers after the abstract because their domain prior tells them immediately whether a document contains new derivation or familiar conclusions restated. The expert is running a high-precision filter. This project builds that filter.

---

## Two Axes, Both Required

Every candidate document must pass two independent quality criteria:

**Axis 1 — Domain relevance**
Cosine similarity of the document's embedding against the seed corpus centroid. Measures whether the document belongs in the target domain. Threshold: ≥ 0.85.

**Axis 2 — Reasoning depth**
Structural classifier score measuring whether the document derives conclusions from stated premises (first-principles reasoning) rather than asserting them. Threshold: ≥ 0.80.

A document that passes one axis but fails the other is rejected. There is no weighted average, no partial admission, no override. The gate is an intersection, not a union.

---

## The Seed Corpus

The positive class is defined by the [`clock-aware-programming`](https://github.com/alchevrier/clock-aware-programming) repository — a body of papers and ADRs reasoning from first principles about a new programming model. The seed is:

- Authored by one person from a consistent set of foundations
- First-principles throughout: every claim derived from the level below it
- Version-controlled: the reasoning is visible and traceable in commit history
- Public: the quality definition is auditable by anyone

The seed corpus centroid defines what "domain relevant" means. The seed's structural patterns define what "first-principles reasoning" looks like. Both definitions are inspectable, not statistical abstractions.

---

## Pipeline

```
seed corpus
    ↓
embed (nomic-embed-text, local, CPU)
    ↓
centroid → domain relevance scorer
    ↓
ArXiv candidate (fetch on demand)
    ↓ 
extract text → discard PDF
    ↓
score: domain relevance × reasoning depth
    ↓
pass both? → store text + metadata
fail either? → discard, log metadata only
```

**Disk strategy:** fetch → extract → discard PDF. Accepted documents stored as plain text only (~50 KB per paper vs ~2 MB PDF). Full corpus target: under 500 MB on disk.

---

## Hierarchical Extension

The filter supports a domain hierarchy — each level fine-tuned from its parent:

```
System Engineering
    ├── Hardware (FPGA, silicon, timing constraints)
    └── Software (OS, Compiler, C++, PLs)
```

The same two-axis gate applies at each level, with a level-specific seed centroid. The base prior is trained once; each branch is a targeted delta on top.

---

## Bootstrap Loop

Once the initial corpus passes the static filter, a small local LLM (Phi-3 mini, Gemma 3 1B) is fine-tuned on it. That fine-tuned model then acts as a second-pass reasoning depth classifier — disagreements with a frontier cloud model (Claude, GPT-4) on new documents are hand-labelled and fed back. The local model converges toward the cloud model's judgment on this specific domain. Cloud API calls drop toward zero as the local model improves.

---

## What Is Open-Sourced

Not model weights. The **method**:

- The relevance scorer (embedding pipeline + threshold configuration)
- The reasoning depth classifier (structural feature definitions + training data)
- The seed corpus pointer (`clock-aware-programming` repository)
- The hierarchy definition (domain tree + per-level centroid)
- The fetch-extract-discard pipeline code

Anyone with a coherent authored seed corpus in their domain can reproduce the method. The seed is the only domain-specific input. The rest is domain-agnostic infrastructure.

---

## Architecture Decision Records

| # | Title | Status |
|---|---|---|
| [0001](docs/adr/0001-two-axis-quality-gate.md) | Two-axis quality gate | Accepted |
| [0002](docs/adr/0002-seed-corpus-as-positive-class.md) | Seed corpus as positive class definition | Accepted |
| [0003](docs/adr/0003-precision-over-recall.md) | Precision over recall | Accepted |
| [0004](docs/adr/0004-fetch-extract-discard.md) | Fetch-extract-discard pipeline | Accepted |
| [0005](docs/adr/0005-embedding-model.md) | Embedding model — nomic-embed-text via Ollama | Accepted |
