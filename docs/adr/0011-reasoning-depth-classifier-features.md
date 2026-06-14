# ADR-0011: Reasoning Depth Classifier — Structural Features

**Date:** 2026-06-15  
**Status:** Accepted

---

## Context

ADR-0001 defines reasoning depth as: *premises made explicit and examinable; conclusions derived from those premises; frame of the argument visible*. It explicitly excludes mathematical density as a proxy. This ADR defines the concrete structural features the classifier uses to produce a score between 0 and 1.

Without a precise feature definition, the classifier cannot be trained, cannot be audited, and cannot be improved systematically when it fails.

---

## Decision

The reasoning depth classifier scores documents on **six structural features**. Each feature is scored 0–1 and the final score is the weighted average defined below.

---

### Feature 1 — Explicit Premise Declaration (weight: 0.25)

**What it measures:** Does the document state its starting assumptions before deriving from them?

**Positive signals:**
- "We assume...", "Given that...", "Under the constraint that...", "Starting from the observation that..."
- A section explicitly labelled "Assumptions", "Model", "Preconditions", or "Foundations"
- The document names what it takes as given vs what it derives

**Negative signals:**
- Claims presented as universal without a stated scope ("locks are necessary")
- Consensus cited as justification ("as is standard practice...", "as is well known...")
- No distinction between assumed and derived claims anywhere in the document

**Scoring heuristic:** 1.0 if premises are named and scoped. 0.5 if some premises are implicit but the derivation chain is otherwise visible. 0.0 if the document reasons entirely from unstated assumptions.

---

### Feature 2 — Derivation Chain Visibility (weight: 0.30)

**What it measures:** Can the reader follow each step from premise to conclusion without filling in gaps from prior knowledge?

**Positive signals:**
- Each claim cites or re-states the claim it follows from
- "Because X, therefore Y" structure, explicit or paraphraseable
- Intermediate conclusions are stated before being used as premises
- The author anticipates objections and derives why they fail

**Negative signals:**
- "Obviously...", "Clearly...", "It follows that..." without showing the following
- Jumps from observation to conclusion skipping intermediate steps
- Maths present but the reasoning that motivated the maths is absent
- Results stated in abstract then "proved" in appendix with no connection to the argument

**Scoring heuristic:** 1.0 if every step is shown. 0.5 if most steps are shown but some require domain knowledge to bridge. 0.0 if conclusions are asserted and derivations are absent or purely formal with no conceptual grounding.

---

### Feature 3 — Frame Exposure (weight: 0.20)

**What it measures:** Does the document make its frame of reference visible — i.e., does it say what model of the world it operates within, and what would have to be different for its conclusions to change?

**Positive signals:**
- "Within the X model...", "Assuming shared address space...", "Under the POSIX threading model..."
- The document states the conditions under which its conclusions hold
- The document identifies related work that reaches different conclusions and explains why the frames differ
- "This result depends on...", "If instead we assumed Y, the conclusion would be..."

**Negative signals:**
- Claims presented as universally applicable without scope
- Related work dismissed without identifying the frame difference ("approach X is inferior")
- No acknowledgement that the conclusions are conditional on the model

**Scoring heuristic:** 1.0 if the frame is named, scoped, and contrasted with alternatives. 0.5 if the frame is implicit but consistent and recoverable. 0.0 if the document treats its frame as reality.

---

### Feature 4 — Assumption Challenge (weight: 0.10)

**What it measures:** Does the document question at least one assumption that is typically taken for granted in the domain?

**Positive signals:**
- "The standard approach assumes X — we ask whether X is necessary"
- "Previous work takes Y as given — we show Y is not required when..."
- The document removes an assumption and derives what changes

**Negative signals:**
- All assumptions are inherited from prior work without comment
- The document works within the consensus frame entirely
- Related work is framed as "building on" rather than "questioning"

**Scoring heuristic:** 1.0 if at least one foundational assumption is explicitly questioned and an alternative is derived. 0.5 if the document implicitly operates with a non-standard assumption without naming it. 0.0 if all assumptions are inherited and unchallenged.

---

### Feature 5 — Conclusion Specificity (weight: 0.10)

**What it measures:** Are the conclusions specific and falsifiable, or vague and hedged into unfalsifiability?

**Positive signals:**
- Quantified claims ("reduces latency by X cycles", "eliminates Y under condition Z")
- Claims that name the conditions under which they would be false
- Conclusions that make a prediction that could be tested

**Negative signals:**
- "May improve...", "could potentially...", "in some cases..."
- Conclusions that are true by definition or unfalsifiable by construction
- Results that depend on so many qualifications that no specific prediction follows

**Scoring heuristic:** 1.0 if conclusions are specific, quantified, or explicitly falsifiable. 0.5 if conclusions are directionally clear but not precisely bounded. 0.0 if conclusions are hedged into vagueness.

---

### Feature 6 — Frame Trap Absence (weight: 0.05)

**What it measures:** Does the document avoid presenting a compensation mechanism as a solution without naming the assumption that makes the compensation necessary? (Inverse of the `framing-trap` W-register degree.)

**Positive signals:**
- Compensation mechanisms are named as such ("this is necessary because the scheduler does not know...")
- The document says what problem would disappear if the underlying assumption changed
- The mechanism's existence is explained by the missing model, not just described

**Negative signals:**
- Compensation presented as a solution with no mention of what it compensates for
- The mechanism is described in detail but the assumption that makes it necessary is absent
- "The correct way to handle X is Y" without "X exists because of assumption Z"

**Scoring heuristic:** 1.0 if no framing traps are present or existing ones are named explicitly. 0.5 if one framing trap is present but the document otherwise exposes its frame. 0.0 if the document is built on an unexposed framing trap.

---

## Final Score Computation

```
reasoning_depth = (
    0.25 * premise_declaration +
    0.30 * derivation_chain +
    0.20 * frame_exposure +
    0.10 * assumption_challenge +
    0.10 * conclusion_specificity +
    0.05 * frame_trap_absence
)
```

Threshold for acceptance: ≥ 0.80 (ADR-0001).

---

## Classifier Implementation

**First cycle (bootstrap):** Human scoring using the feature rubric above. Each feature scored 0, 0.5, or 1.0. Weighted sum computed. First 50 documents scored by human; used as training data for the automated classifier.

**Second cycle (automated):** Fine-tune a small classification head on top of `nomic-embed-text` embeddings, trained on the human-scored documents. The classifier predicts the weighted feature scores from the document embedding. Validated against a held-out set of human-scored documents before deployment.

**Known failure mode — mathematical density:** A document with dense proofs and formalism will produce high embedding similarity to rigorous academic work. The classifier must not use mathematical symbol density as a proxy for derivation chain visibility. Mathematical formalism without conceptual grounding scores low on Feature 2 (derivation chain visibility) and high on nothing else. The rubric is the safeguard.

---

## Rationale

**Why six features rather than one?**

A single score conflates distinct properties. A document can score high on premise declaration and low on frame exposure (states its assumptions but doesn't say when they stop holding). A document can score high on conclusion specificity and low on derivation chain (makes a precise claim but doesn't show why it follows). Each failure mode produces a different kind of corrupted prior. The feature breakdown makes the failure mode diagnosable.

**Why is derivation chain visibility weighted highest (0.30)?**

It is the core property that distinguishes a document that trains reasoning from a document that trains pattern-matching. Explicit premises and specific conclusions are necessary but not sufficient — without the visible derivation chain, the model learns that "X implies Y" without learning why, which is pattern-matching.

**Why is frame trap absence weighted lowest (0.05)?**

It is a negative signal — its absence is penalising, not its presence rewarding. Most documents score 1.0 on this feature simply by not containing a framing trap. The weight is low because it is a floor check, not a discriminator.

---

## Consequences

- Human scoring of the first 50 documents takes approximately 30–60 minutes per document batch (6 features × 3-point scale × reading time).
- The feature rubric is the ground truth for classifier training. If the rubric is wrong, the classifier is wrong. Rubric updates require re-scoring affected training documents.
- Feature scores are stored in the metadata record alongside the final weighted score, enabling per-feature analysis of classifier failures.
