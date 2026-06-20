# Epistemic Filter
#### Alex Chevrier — chevrier.alex@gmail.com

> A two-axis data quality filter for bootstrapping domain-specific LLMs: domain relevance scored against a seed corpus, reasoning depth scored by structural first-principles analysis. Precision over recall. Quality over volume.

---

*The thinking in this project is mine. The writing was produced with AI assistance (GitHub Copilot / Claude).*

---

**Started: 2026-06-15.**

---

## The Prerequisite Nobody States

**This pipeline is a force multiplier on the curator's knowledge. It is not a substitute for it.**

The filter accepts documents that look like your seed and reason like your seed. If your seed embodies a framing trap — a locally correct belief that prevents you from questioning the assumption beneath it — the pipeline will scale that trap into a training corpus and the model will defend it fluently.

The W-register (the known-wrong claims register) was traditionally only as complete as the curator's self-awareness. If you had not personally escaped a framing trap, it wouldn't appear in your W-register, and the model would learn to defend it.

**Dynamic Discovery (`--uncover`) changes this.** By pointing a frontier model at a mature repository's ADRs and source code, the LLM acts as an architectural mirror. It automatically extracts not just the explicit rules, but the *Negative Space*—the standard, baseline paradigms that are forbidden by the new architecture. 

This offloads the burden of flawless self-awareness. It catches framing traps programmatically before they bake into the weights. The pipeline still reproduces a prior at scale, but "the prior" no longer relies exclusively on human memory—it is mathematically mined from the ground truth of the code and documentation.

**What this means in practice:**

- Do not run this pipeline on a seed you haven't read critically
- Do not define a W-register from a list of common mistakes — define it from claims you personally held and later recognised as wrong
- Do not graduate a model until a benchmark question set written before training exposes the blind spots you were aware of at construction time
- Expect iteration: the first training run will reveal corpus gaps you did not know existed

This is a tool for someone who knows their domain well enough to recognise first-principles reasoning when they encounter it. If you are still inside the dominant paradigm of your field, this pipeline will produce a model that is fluent in that paradigm. That may be useful. It is not the same thing as a model that can question it.

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

## The Epistemic Engine CLI

The core architecture has been decoupled from specific domain payloads into a scalable, generic product. This allows any team to define their proprietary constraints and synthesize an aligned dataset for local fine-tuning without polluting the core execution pipeline.

### 1. Initialize a New Domain
Start by scaffolding an empty domain. This creates the required folder structure, a blank benchmark template, and a seed rule file.
```bash
./epistemic.py init domains/my-custom-domain
```
*What you do next:* Edit `domains/my-custom-domain/corpus/seed/rules.md` with your strict paradigm constraints, and define your evaluation tracks (e.g., C1-C4) in `benchmark/questions.json`.

### 2. Auto-Uncover a Domain (Dynamic Discovery)
Instead of writing your paradigm rules manually, you can point the engine at an existing, mature repository. The engine will read your architectural documents (ADRs, READMEs) and source code, and use an LLM (local or cloud) to automatically extract your axioms and forbidden anti-patterns.
```bash
# Local execution (requires ~16GB+ VRAM for a strong 70B model)
./epistemic.py uncover --repo ../my-mature-project --domain domains/my-custom-domain --provider ollama --model llama3:70b

# Cloud execution (Flawless extraction, circumvents context limits)
export GITHUB_TOKEN="ghp_xxx"
./epistemic.py uncover --repo ../my-mature-project --domain domains/my-custom-domain --provider copilot --model gpt-4o
```
*What you do next:* Verify the generated `corpus/seed/rules.md` and `corpus/known-wrong-claims.json`, then proceed to generation.

### 3. Generate the Synthesized Curriculum
Once your seed rules and benchmarks are defined (manually or via `uncover`), the engine expands these into a massive, diverse training mix by crossing your rules with different structural tracks (contrastive examples, analogies, generative cases).
```bash
./epistemic.py generate --domain domains/my-custom-domain
```

### 4. Train the Local Expert Model
Train your local small LLM (e.g., Phi-3 Mini) using QLoRA against the synthesized curriculum, destroying its base-model biases and enforcing your strict constraints.
```bash
./epistemic.py train --domain domains/my-custom-domain --epochs 3 --base-model microsoft/Phi-3-mini-4k-instruct
```

### 5. Evaluate the Paradigm Shift
Validate that your new model passes the rigorous evaluation tracks and refuses to fall back into standard, unconstrained paradigms.
```bash
./epistemic.py evaluate --domain domains/my-custom-domain --adapter domains/my-custom-domain/corpus/adapters/adapter_final
```

---

## Architecture Decision Records

| # | Title | Status |
|---|---|---|
| [0001](docs/adr/0001-two-axis-quality-gate.md) | Two-axis quality gate | Accepted |
| [0002](docs/adr/0002-seed-corpus-as-positive-class.md) | Seed corpus as positive class definition | Accepted |
| [0003](docs/adr/0003-precision-over-recall.md) | Precision over recall | Accepted |
| [0004](docs/adr/0004-fetch-extract-discard.md) | Fetch-extract-discard pipeline | Accepted |
| [0005](docs/adr/0005-embedding-model.md) | Embedding model — nomic-embed-text via Ollama | Accepted |
| [0006](docs/adr/0006-candidate-discovery-and-feedback.md) | Candidate discovery and relevance feedback | Accepted |
| [0007](docs/adr/0007-reflection-window.md) | Mandatory reflection window (every 50 documents) | Accepted |
| [0008](docs/adr/0008-contradiction-detection.md) | Contradiction detection and known-wrong claims register | Accepted |
| [0009](docs/adr/0009-source-context-classification.md) | Source context classification (academic, industry, independent, hardware) | Accepted |
| [0010](docs/adr/0010-cross-domain-reinforcement.md) | Cross-domain reinforcement layer | Accepted |
| [0011](docs/adr/0011-reasoning-depth-classifier-features.md) | Reasoning depth classifier — structural features | Accepted |
| [0012](docs/adr/0012-fine-tuning-strategy.md) | Fine-tuning strategy (Phi-3 Mini, QLoRA, contrastive training) | Accepted |
| [0013](docs/adr/0013-evaluation-benchmark.md) | Evaluation benchmark (51 questions, 3 components, graduation criteria) | Accepted |
| [0014](docs/adr/0014-corpus-reproducibility.md) | Corpus reproducibility (document records, centroid snapshots, verify script) | Accepted |
| [0015](docs/adr/0015-domain-hierarchy.md) | Domain hierarchy definition (root → branch → leaf, centroid inheritance) | Accepted |
| [0016](docs/adr/0016-seed-construction-methodology.md) | Seed construction methodology — how to define your positive class | Accepted |
| [0017](docs/adr/0017-benchmark-construction-methodology.md) | Benchmark construction methodology — how to write your evaluation questions | Accepted |
