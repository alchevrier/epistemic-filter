# ADR-0002: Seed Corpus as Positive Class Definition

**Date:** 2026-06-15  
**Status:** Accepted

---

## Context

The classifier needs a definition of "high quality" before it can score any candidate document. That definition must be both precise and human-verifiable — it cannot be a statistical abstraction over a scraped corpus, because a scraped corpus averages over noise and makes the quality criterion opaque.

The question is: what is the positive class, and where does it come from?

---

## Decision

The positive class is defined by an **authored seed corpus** — a body of documents written by one author from a consistent set of first principles. The initial seed is the `clock-aware-programming` repository (`https://github.com/alchevrier/clock-aware-programming`).

The seed corpus is:
- Treated as ground truth for domain relevance (its centroid defines the embedding target)
- Treated as ground truth for reasoning depth (its structural patterns define what first-principles derivation looks like in this domain)
- Version-controlled and public — the definition of quality is auditable by anyone

---

## Rationale

**Why an authored corpus rather than a curated subset of existing literature?**

An authored corpus has three properties that curated literature lacks:

1. **Consistency of reasoning style.** A single author reasoning from the same foundations throughout produces a tight embedding cluster. The centroid of that cluster is a precise quality target. A curated multi-author corpus has reasoning style variance that widens the cluster and weakens the similarity signal.

2. **Interpretability of failures.** When the classifier makes a wrong call, the seed corpus is the reference. Because the author knows what every section means and why it was written, misclassifications can be diagnosed by reading the candidate document alongside the nearest seed sections. The fix is targeted and traceable.

3. **No bootstrap problem.** Curating a high-quality subset of existing literature requires already knowing what high quality looks like — which is the problem the classifier is supposed to solve. An authored corpus breaks the circularity: the author's judgment is the definition, not a derived approximation of it.

**Why `clock-aware-programming` specifically?**

- First-principles reasoning throughout: every claim is derived from the level below it (`budget_ticks` from the instruction graph, the dispatch table from `budget_ticks`, the no-reboot property from the dispatch table)
- Domain-consistent from Paper I through Paper IV: language → OS → hardware, same model all the way down
- Version-controlled commit history: the reasoning developed in sequence is visible and traceable
- Already public: the seed is reproducible by anyone

**Why is the seed corpus treated as ground truth rather than a starting point to be refined?**

Because the classifier's job is to find more documents like it, not to redefine what it is. If the seed is wrong, the correct fix is to improve the seed — not to let the classifier drift away from it through iterative refinement on unannotated data. The seed is the anchor.

---

## Alternatives Rejected

### Curated subset of ArXiv papers as positive class

**Rejected.** Requires hand-labelling before any classifier exists — the bootstrap problem. Also produces a multi-author corpus with reasoning style variance, weakening the embedding signal.

### Synthetic positive class (LLM-generated examples of first-principles reasoning)

**Rejected.** LLM-generated text optimises for the appearance of first-principles reasoning, not the substance. A classifier trained on synthetic positives learns to recognise stylistic markers of rigour rather than actual derivation structure. This produces a classifier that is fooled by well-written but shallow documents.

### Wikipedia or textbook excerpts as positive class

**Rejected.** Textbooks assert and explain; they rarely derive from foundations visible to the reader. Wikipedia summaries are explicitly written to avoid showing derivation chains. Both fail the reasoning depth criterion that the classifier is supposed to enforce.

---

## Consequences

- The classifier quality is bounded by the seed corpus quality. If the seed contains shallow reasoning, the classifier learns to accept shallow reasoning. The seed must be maintained and improved as the project evolves.
- New seed documents (future papers, ADRs, implementation notes) strengthen the positive class as they are added.
- The seed corpus is a public commitment: anyone can inspect the definition of quality and challenge it.
