# ADR-0001: Two-Axis Quality Gate

**Date:** 2026-06-15  
**Status:** Accepted

---

## Context

The goal is to build a high-quality domain-specific corpus for fine-tuning local LLMs. The primary risk is noise in the training data — noisy documents degrade the prior permanently and are difficult to remove after fine-tuning has occurred. A single quality score is insufficient because a document can be domain-relevant without reasoning from first principles, or can reason rigorously from first principles in the wrong domain. Both cases produce a corrupted prior for different reasons.

---

## Decision

Every candidate document must pass **two independent axes**, both required:

1. **Domain relevance** — cosine similarity of the document's embedding against the seed corpus centroid. Threshold: ≥ 0.85.
2. **Reasoning depth** — structural classifier score measuring whether the document derives conclusions from stated premises (first-principles reasoning) rather than asserting them. Threshold: ≥ 0.80.

**Reasoning depth is not mathematical density.** A document dense with proofs and formalism scores high on mathematical rigour, not necessarily on reasoning depth. The distinction is whether the **premises are made explicit and examinable**. A document that states its assumptions, shows why each step follows from the previous one, and makes the frame of the argument visible — even in plain prose — scores high on reasoning depth. A document that works out the maths of a mechanism while leaving the assumption that makes the mechanism necessary unstated scores low, because the reader cannot evaluate the frame, only the derivation within it.

An expert does not need the full maths of RCU to evaluate it. They need two things: what problem it claims to solve, and why that problem exists. Those two facts allow the expert to evaluate whether the problem is real or whether it is a compensation for a missing model. The maths are irrelevant to that judgment — they are only relevant if the frame has already been accepted. Reasoning depth measures whether the document exposes the frame, not whether it executes within it rigorously.

A document that passes one axis but fails the other is rejected. There is no weighted average, no partial admission, no override.

---

## Rationale

**Why two axes, not one?**

A domain-relevant document that asserts conclusions trains the model to pattern-match, not to reason. A rigorous reasoning document in the wrong domain trains the model to derive wrong conclusions. The failure modes are different but equally damaging. A single score cannot distinguish them.

**Why are the thresholds asymmetric (0.85 vs 0.80)?**

Domain relevance is measured by cosine similarity against an embedding centroid — a continuous geometric measure that is sensitive to vocabulary overlap. Setting it too high (≥ 0.90) risks discarding genuine domain documents that use different vocabulary for the same concepts. 0.85 eliminates the bulk of noise while preserving terminological diversity.

Reasoning depth is a structural classifier score — harder to fake than domain vocabulary. A document either shows its derivation steps or it does not. The threshold can be slightly lower because the feature is more binary in practice.

**Why intersection, not union?**

The union gate (pass either axis) would admit domain-relevant noise and off-domain rigorous documents. Both corrupt the prior. The intersection gate (pass both axes) is strict but that is the intent — the corpus is small by design and every document must earn its place.

---

## Alternatives Rejected

### Single composite score (weighted average of both axes)

**Rejected.** A composite score allows a very high domain relevance to compensate for low reasoning depth. This admits well-written domain summaries that assert without deriving — exactly the failure mode the classifier is designed to prevent.

### Domain relevance only

**Rejected.** This is standard RAG filtering. It produces a domain-coherent corpus but not a reasoning-coherent one. The fine-tuned model learns what the domain talks about, not how the domain thinks. The result is confident pattern-matching rather than derivation.

### Reasoning depth only

**Rejected.** Rigorous reasoning from first principles in an unrelated domain trains the model to reason well but in the wrong direction. A philosophy of mathematics paper may score 0.95 on reasoning depth and 0.20 on domain relevance. It does not belong in the corpus.

---

## Consequences

- Some high-quality documents will be rejected for failing one axis. This is acceptable — the corpus is intentionally small and dense, not large and broad.
- Threshold calibration is required: run the first 50 candidate documents through both scorers, spot-check near-threshold cases manually, adjust if necessary.
- False positives (noise admitted) are more damaging than false negatives (good documents discarded). When in doubt, reject.
