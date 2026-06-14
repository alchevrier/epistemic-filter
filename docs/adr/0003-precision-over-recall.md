# ADR-0003: Precision Over Recall

**Date:** 2026-06-15  
**Status:** Accepted

---

## Context

Any classification system trades off precision (fraction of accepted documents that are genuinely high quality) against recall (fraction of genuinely high quality documents that are accepted). The choice of which error to tolerate defines the character of the resulting corpus.

This decision records the explicit choice and its rationale.

---

## Decision

**Precision is the primary objective. Recall is acceptable collateral damage.**

When in doubt, reject. A document that passes one axis but is near the threshold on the other is rejected, not admitted with reduced confidence. There is no "probably good enough" tier.

---

## Rationale

**False positives compound; false negatives do not.**

A false positive — a low-quality document admitted to the corpus — enters the fine-tuning data and shifts the model's prior. The shift is small for any single document but accumulates across the corpus. Once the model is fine-tuned on a corrupted corpus, the corruption is embedded in the weights. Correcting it requires either retraining from scratch or targeted negative fine-tuning, both expensive.

A false negative — a high-quality document rejected — is simply absent from the corpus. The model does not learn from it. This is a missed opportunity, not active damage. The prior is not degraded. The document can be reconsidered later (lower the threshold, re-run, re-evaluate). The error is reversible.

**The corpus is intentionally small.**

This is not a general-purpose web crawl. The goal is a dense, coherent corpus of a few hundred to a few thousand documents — enough to produce a tight prior in one domain. At that scale, each document's influence on the final prior is measurable. A 5% false positive rate in a 10,000-document corpus is manageable noise. A 5% false positive rate in a 200-document corpus is 10 corrupting documents — significant.

**Quality over volume is the founding principle.**

100K quality tokens outperform 1 trillion noisy tokens for domain-specific fine-tuning (ref: Phi-1, Microsoft Research, 2023). This only holds if "quality" is enforced strictly. Relaxing the quality gate to increase recall undermines the entire thesis.

**Expert behaviour is high-precision by nature.**

A domain expert reading a stack of papers discards most of them after the abstract. They are running a high-precision filter — they would rather miss a good paper than spend time on a bad one, because their time (the fine-tuning compute budget, in this analogy) is the scarce resource. The classifier should behave like the expert, not like a literature review assistant trying to be comprehensive.

---

## Alternatives Rejected

### Balanced precision/recall (F1 optimisation)

**Rejected.** F1 treats false positives and false negatives as equally costly. They are not. False positives actively degrade the model. False negatives are missed opportunities. Optimising F1 produces a corpus that is larger but less reliable — the opposite of the goal.

### High recall, post-hoc cleaning

**Rejected.** Admit everything above a low threshold, then manually remove bad documents after inspection. This defers the quality decision to a manual step that does not scale. The pipeline is designed to reduce human labour, not to create it downstream.

### Tiered admission (high-confidence, medium-confidence, low-confidence pools)

**Rejected.** Adds complexity without a clear payoff. The medium-confidence pool requires a separate training strategy and a decision about how to weight it. The two-axis gate with a binary pass/fail is simpler, auditable, and sufficient for the corpus size targeted.

---

## Consequences

- The corpus will be smaller than a recall-optimised pipeline would produce. This is correct — the corpus should be small and dense.
- Some genuinely high-quality documents will be rejected. This is acceptable.
- Threshold calibration (ADR-0001) is important because setting thresholds too high reduces the corpus to the point of being non-representative. The goal is strict, not pathological.
- The rejection rate is itself a signal: if 95% of candidate ArXiv papers are rejected, either the thresholds are miscalibrated or the domain filter (source selection) is too broad. Both are fixable upstream.
