# ADR-0012: Fine-Tuning Strategy

**Date:** 2026-06-15  
**Status:** Accepted

---

## Context

The corpus pipeline (ADR-0001 through ADR-0010) produces a curated text corpus. This ADR defines how that corpus is used to produce a fine-tuned local LLM — which base model, which training method, how the primary and cross-domain tiers are mixed, and how contrastive training on annotated contradictions is implemented.

The constraints are: i5-12400 CPU, 32 GB RAM, no GPU, 70 GB free NVMe. Fine-tuning must be feasible within these constraints without cloud compute.

---

## Decision

### Base Model

**Phi-3 Mini (3.8B parameters, Q4_K_M quantisation, ~2.2 GB)**

Rationale:
- Fits in RAM with headroom for training overhead
- Trained on "textbook quality" filtered data (Microsoft Research) — the closest existing base to the epistemic filter's corpus philosophy
- Strong reasoning benchmark performance at 3.8B, outperforms larger models trained on web crawl data on multi-step reasoning tasks
- `aarch64` and `x86_64` support; runs on CPU via `llama.cpp`

Alternative considered: Gemma 3 1B (faster, smaller) — rejected because 1B parameters is insufficient for the multi-step reasoning chains in the primary domain corpus. Phi-3 Mini at Q4 is the minimum viable parameter count for this domain.

### Training Method

**QLoRA (Quantised Low-Rank Adaptation)**

- Base model loaded in 4-bit quantisation (NF4)
- LoRA adapters trained in fp16/bf16
- Rank: r=16, alpha=32 (standard starting point, tune during calibration)
- Target modules: `q_proj`, `v_proj`, `k_proj`, `o_proj` (attention layers)
- Memory footprint during training: ~8–12 GB RAM (base model + gradients + optimizer state for adapter weights only)
- Tooling: `unsloth` (CPU-compatible QLoRA, 2× faster than naive implementation)

Full fine-tuning rejected: requires 4× model size in optimizer state — 8.8 GB for Phi-3 Mini at fp32. Exceeds safe RAM budget when combined with corpus and tooling overhead.

### Training Data Mix

Documents fed to the trainer in the following ratio per epoch:

| Tier | Ratio | Notes |
|---|---|---|
| Primary domain — accepted | 60% | Standard next-token prediction |
| Cross-domain — accepted with bridge annotation | 15% | Bridge annotation prepended as context |
| Accepted-with-annotation (contradiction flagged) | 15% | Contrastive format (see below) |
| Seed corpus (clock-aware-programming) | 10% | Repeated every epoch — anchor the prior |

The seed corpus is repeated every epoch to prevent catastrophic forgetting of the founding prior. It is the anchor — if the model drifts from it, all other corpus decisions are invalidated.

### Contrastive Training Format

Documents accepted-with-annotation (ADR-0008) are formatted as contrastive pairs during training:

```
[CONTEXT] {document excerpt containing the flagged claim}
[CLAIM] {verbatim flagged sentence}
[DEGREE] {scoped | near-miss | misattributed | framing-trap | false}
[REFUTATION] {seed section reference + canonical refutation from W-register}
[BRIDGE] {explicit derivation of why the claim is wrong at this degree}
```

The model is trained to produce the REFUTATION and BRIDGE given the CONTEXT, CLAIM, and DEGREE. This trains the model to engage with the specific structure of the wrong claim, not just produce the correct answer.

### Training Schedule

- **Epoch 1–3**: full corpus mix, learning rate 2e-4, warmup 100 steps
- **Epoch 4–6**: reduce learning rate to 5e-5, increase seed corpus ratio to 20% (prevent drift)
- **Evaluation**: run benchmark (ADR-0013) after epoch 3 and epoch 6. Stop if benchmark plateaus or degrades.
- **Checkpoint**: save adapter weights after each epoch. Total checkpoint storage: ~3 × (r=16 adapter size) ≈ 150 MB.

### Estimated Training Time (CPU, i5-12400)

- Corpus size target: 500 documents × ~4K tokens average = ~2M tokens
- Phi-3 Mini at Q4 on CPU: ~100–150 tokens/second
- Tokens per epoch: 2M
- Time per epoch: ~4–6 hours
- 6 epochs: ~24–36 hours total

Acceptable. Run overnight across 3 nights. No cloud compute required.

---

## Rationale

**Why Phi-3 Mini over Gemma 3 1B?**

The corpus trains a reasoning model, not a retrieval model. Reasoning chains in the primary domain require holding multiple intermediate conclusions simultaneously while deriving the next step. At 1B parameters, this collapses — the model pattern-matches to the nearest training example rather than deriving. Phi-3 Mini at 3.8B is the minimum for reliable multi-step derivation on domain-specific content.

**Why QLoRA over full fine-tuning?**

Full fine-tuning changes all weights — it is expensive and risks catastrophic forgetting of the base model's reasoning capabilities. QLoRA trains only the low-rank adapters (~1% of parameters), preserving the base model's generalisation while injecting domain-specific knowledge. For a corpus of ~500 documents, QLoRA is sufficient and CPU-feasible.

**Why repeat the seed corpus every epoch?**

The seed is the ground truth. As new documents enter the corpus, the model's distribution shifts. Repeating the seed every epoch is the training-time equivalent of the centroid drift check in the reflection window — it keeps the prior anchored to the founding documents while still absorbing new signal.

**Why the contrastive training format?**

A model that learns only the correct claims is fragile in deployment. Users will ask questions that contain W-register claims ("but don't we need locks?"). The model needs to recognise the claim, classify its degree, and produce the specific refutation — not just state the correct answer and ignore the question's frame. Contrastive training produces this capability.

---

## Alternatives Rejected

### Cloud fine-tuning (Replicate, Modal, RunPod)

**Rejected for first cycle.** The first fine-tuning run is a calibration — we don't yet know if the corpus is good enough to produce a useful model. Running calibration on cloud compute at non-trivial cost before validating the corpus is premature. CPU fine-tuning is slow but zero marginal cost. Move to cloud for second cycle if first cycle validates the approach.

### LoRA without quantisation

**Rejected.** Phi-3 Mini in fp16 requires ~7.6 GB RAM. With LoRA adapter gradients and optimizer state, total RAM during training reaches ~18–20 GB. Leaves insufficient headroom on 32 GB for OS and tooling. Q4 quantisation brings the base model to ~2.2 GB, making training comfortable within the RAM budget.

### Instruction tuning format (prompt-response pairs)

**Considered but not primary.** The corpus is document-level text, not prompt-response pairs. Training primarily on next-token prediction over documents teaches the model the domain's reasoning structure. Instruction tuning format is used only for the contrastive training examples where a specific input-output mapping is needed. Mixing both formats in the ratio described above.

---

## Consequences

- `unsloth` must be installed and tested for CPU compatibility before training begins
- Adapter checkpoints (~50 MB each) stored alongside corpus; total storage impact negligible
- The contrastive training format requires the W-register to be machine-readable (standalone JSON — ADR not yet written, dependency)
- Training time is 24–36 hours spread across multiple sessions; requires a resumable checkpoint strategy
- The M5 Max (when available) reduces training time by ~10–20× via GPU acceleration; the same QLoRA approach applies without modification
