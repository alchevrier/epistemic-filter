# ADR-0010: Cross-Domain Reinforcement Layer

**Date:** 2026-06-15  
**Status:** Accepted

---

## Context

A model trained exclusively on systems papers knows the core insight — "declare when something happens, and the compensation for not knowing becomes unnecessary" — within one domain and one vocabulary. It associates the insight with locks, schedulers, GC, and channels. It cannot recognise the same insight when it appears in logistics, finance, biology, or physics under completely different notation.

This is a generalisation failure. The insight is structural, not domain-specific. It recurs wherever timing is undeclared and systems must compensate at runtime for the missing declaration. A model that knows only the systems manifestation will correctly answer systems questions but will fail to:

1. Recognise when a cross-domain analogy strengthens the primary domain's claim
2. Apply the insight to novel domains where the vocabulary is unfamiliar
3. Understand the insight as a general principle rather than a domain-specific technique

The cross-domain reinforcement layer addresses this by adding a second corpus tier — documents from domains outside systems engineering where the same structural pattern appears. This is analogous to how a neural network generalises: not by memorising more examples within one distribution, but by finding the shared structure across different input distributions. The cross-domain layer is the mechanism by which the model learns the invariant, not just the instances.

---

## Decision

A second corpus tier — **cross-domain reinforcement** — is added alongside the primary domain corpus. Cross-domain documents are scored, tagged, and included with a **structural bridge annotation** that explicitly identifies which primary domain claim the cross-domain document reinforces and why the structural pattern is isomorphic.

Cross-domain documents are not expected to pass the primary domain relevance threshold (0.85 cosine similarity against the systems seed centroid). They are scored against a **secondary centroid** derived from the structural pattern itself — the abstract claim "declare timing, eliminate compensation" — not against domain vocabulary.

Cross-domain documents must pass:
1. **Reasoning depth** ≥ 0.80 (same threshold, same definition — premises explicit and examinable)
2. **Structural isomorphism score** ≥ 0.75 — does the document's core argument instantiate the abstract pattern, even in different vocabulary?

The structural isomorphism score is assigned during manual review. It cannot be automated in the first cycle — it requires a human to read the document and identify the mapping between the cross-domain mechanism and the primary domain claim.

---

## Cross-Domain Map (initial)

| Domain | Mechanism | Primary Domain Isomorph | Structural Pattern |
|---|---|---|---|
| **Logistics** | Toyota Production System / Just-In-Time manufacturing | Lock-free channels, compile-time memory layout | Declare arrival windows → eliminate buffer inventory. Buffer = compensation for undeclared timing. |
| **Logistics** | Theory of Constraints (Goldratt) | Admission test / dispatch table | Identify the bottleneck (the constraining circuit), subordinate everything else to it. Throughput = bottleneck throughput. Slack elsewhere is declared, not managed. |
| **Finance** | Scheduled auction markets (call auctions) vs continuous trading | Dispatch table vs preemptive scheduler | Declare when matching occurs → pricing complexity collapses. Continuous markets require real-time hedging because timing is undeclared. |
| **Finance** | Options pricing / Greeks as runtime compensation | Budget_ticks derivation | Delta, gamma, vega are runtime compensations for not knowing when the underlying moves. A declared-timing derivative has no Greeks — the timing is the contract. |
| **Biology** | Circadian rhythms / ultradian cycles | ClockCircuit / dispatch table | Organism pre-loads resources before the window opens. Immune response is compensation for undeclared pathogen timing. Vaccine = declared timing for immune system. |
| **Biology** | Synaptic pruning during sleep | Reflection window / corpus recalibration | Brain removes low-weight connections on a declared cycle. Undeclared removal = fragmentation (equivalent to heap fragmentation). |
| **Physics** | Classical limit of quantum mechanics | Compile-time proof vs runtime measurement | Quantum uncertainty collapses when measurement timing is declared relative to system evolution. Uncertainty = compensation for undeclared observation timing. |
| **Operations research** | Queuing theory / Little's Law | Budget_ticks + admission test | L = λW. Throughput and latency are functions of declared arrival and service rates. Variance = undeclared timing. |
| **Neuroscience** | Expert pattern recognition / chunking | Seed corpus prior / domain centroid | Expert skims because domain prior is pre-loaded — same as runtime PRFM prefetch from manifest. Novice reads everything because no prior exists to discriminate signal from noise. |

---

## Scoring and Tagging

Cross-domain documents are tagged with:
- `corpus_tier: cross_domain`
- `primary_claim_reinforced: [W-XX or seed section reference]`
- `structural_pattern: declare_timing_eliminate_compensation` (or other identified pattern)
- `isomorphism_score: 0.00–1.00` (manual assignment)
- `bridge_annotation: [explicit description of the mapping]`

The bridge annotation is the most important field. It is the training signal — it teaches the model not just that the cross-domain document is relevant, but *why* and *where* the structural connection lies.

Example bridge annotation for a JIT manufacturing paper:

> "Buffer inventory in JIT manufacturing is structurally identical to a lock in concurrent systems programming. Both exist because timing is undeclared. JIT eliminates buffer by declaring arrival windows (kanban = channel declaration). Lock-free channels eliminate the lock by declaring execution windows (budget_ticks = arrival window). The compensation (buffer / lock) is redundant in both cases once timing is declared. The domain vocabulary differs; the structural derivation is identical."

---

## Why This Is the Most Important Layer

A model trained on the primary domain corpus learns the insight within one frame. It can answer systems questions correctly. It cannot generalise.

A model that also knows the cross-domain corpus has learned that the insight recurs — in different notation, in different centuries, in different fields — whenever the same structural condition (undeclared timing) is present. That recurrence is the evidence that the insight is fundamental, not accidental.

The cross-domain layer is the mechanism by which the model learns to abstract. Without it, the model is a domain expert. With it, the model is a first-principles reasoner who happens to be fluent in the systems domain. The difference is: the domain expert answers systems questions. The first-principles reasoner answers any question that instantiates the same structural pattern, including questions in domains the training corpus never explicitly covered.

This is the bridge to general reasoning capability — not by training on more data, but by training on the right structural invariant across the minimum necessary domains.

---

## Alternatives Rejected

### Primary domain corpus only

**Rejected.** Produces a domain expert, not a first-principles reasoner. The model will correctly solve known problems and fail to recognise novel instantiations of the same insight.

### General cross-domain training (broad web crawl across many domains)

**Rejected.** Dilutes the prior. The cross-domain layer must be curated for structural isomorphism, not broad coverage. A logistics paper that does not instantiate the declare-timing-eliminate-compensation pattern is noise, regardless of how well-written it is.

### Automated structural isomorphism scoring

**Rejected for the first cycle.** The isomorphism score requires a human to identify the mapping between cross-domain vocabulary and primary domain claims. This cannot be automated before the base model exists. Once the primary domain model is trained, it can be used to score cross-domain candidates automatically — producing the isomorphism score from the model's own embedding space. This is a second-cycle capability.

---

## Consequences

- The corpus now has two tiers: primary domain (systems engineering, hardware, compilers) and cross-domain reinforcement (logistics, finance, biology, physics, operations research, neuroscience).
- Cross-domain documents are always minority — target ratio: 80% primary, 20% cross-domain. Enough to establish the structural invariant without diluting domain fluency.
- Every cross-domain document requires a manually written bridge annotation. This is the highest-effort step in the pipeline. It is also the highest-value step — the annotation is the generalisation signal.
- The reflection window (ADR-0007) includes a cross-domain distribution check: if cross-domain documents cluster around one secondary domain (e.g., all logistics), the structural invariant is being reinforced from only one angle. Add documents from other secondary domains to triangulate.
