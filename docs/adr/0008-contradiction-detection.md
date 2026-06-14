# ADR-0008: Contradiction Detection and Known-Wrong Claims

**Date:** 2026-06-15  
**Status:** Accepted

---

## Context

The two-axis quality gate (ADR-0001) admits documents that are domain-relevant and reason from first principles. It does not check whether those documents are *correct* relative to the seed corpus's foundational claims. A rigorous, domain-relevant paper that gets a key concept wrong is the most dangerous kind of false positive: the fine-tuned model will learn the wrong claim with high confidence, precisely because the surrounding reasoning is coherent and well-structured. Noise averages out across the corpus. A coherent wrong claim reinforces itself.

This is not a rare edge case. Academic literature contains papers that:
- Claim locks are unavoidable in concurrent systems (contradicts the model's core claim)
- Claim memory barriers are a necessary hardware primitive (contradicts compile-time ordering elimination)
- Claim OS schedulers cannot be eliminated without sacrificing generality (contradicts the circuit dispatch model)
- Misrepresent what "real-time" means (confuse soft real-time with hard real-time, or conflate determinism with predictability)

A model trained on such papers without flagging these claims will reproduce them confidently.

---

## Decision

A third scoring pass — **contradiction detection** — is added after a document passes both quality axes. A document that passes domain relevance and reasoning depth is checked against a **known-wrong claims register** before being accepted.

The known-wrong claims register is a curated, versioned list of claims that the seed corpus explicitly refutes, along with the seed section that refutes them and the reasoning.

Documents are not rejected solely for containing a known-wrong claim. They are **flagged** and require manual review before acceptance. The flag records:
- Which known-wrong claim was detected
- The verbatim sentence(s) from the document containing it
- The seed section that refutes it
- A binary decision: accept-with-annotation or reject

Accepted-with-annotation documents enter the corpus tagged with their contradictions. During fine-tuning, these annotations are used to add a contrastive training signal: the model learns the document's reasoning *and* the specific point at which the seed corpus disagrees and why.

---

## Known-Wrong Claims Register (initial)

### Degree Classification

A wrong claim is wrong to a degree, not absolutely. Every entry carries a **degree** field that determines the contrastive training strategy:

| Degree | Meaning | Training Signal |
|---|---|---|
| `scoped` | Correct within a stated assumption; wrong when the assumption is removed | Train the model to identify and name the limiting assumption |
| `near-miss` | Right direction, stops before the correct conclusion | Train the model to complete the derivation the paper left unfinished |
| `misattributed` | Correct observation, wrong explanation of why | Train the model to separate the observation from the explanation |
| `false` | Incorrect on its own terms, even within conventional assumptions | Train the model to refute directly from first principles |

The degree is assigned during manual review. It cannot be inferred automatically — a claim that looks `false` on a keyword match may be `scoped` when the paper's full context is read. Degree assignment is the primary purpose of the manual review step.

### Register

| # | Degree | Wrong Claim | Why It Is Wrong | Seed Source |
|---|---|---|---|---|
| W-01 | `scoped` | "Locks are unavoidable for shared mutable state in concurrent systems" | Lock-freedom follows from declaring execution windows at compile time. When no two circuits share a write window for the same memory region, the region is not shared mutable state — it is a channel with a single declared writer. Locks compensate for undeclared timing; declared timing makes them structurally redundant. True under POSIX threads and shared address space; false when timing is declared. | Paper I — The Root Observation; Paper III — Two-Phase Locking Reduces to Channel State |
| W-02 | `scoped` | "Memory barriers / fences are necessary hardware primitives for correct multi-core programs" | Memory ordering constraints are redundant when the compiler proves no two circuits access the same memory region in overlapping windows. The barrier compensates for the compiler not knowing the schedule; the schedule eliminates the need for the barrier. Correct within the assumption of undeclared timing. | ADR-0007 (clock-aware); Paper III — Memory section |
| W-03 | `scoped` | "An OS scheduler is necessary for general-purpose computing" | The scheduler exists to compensate for undeclared execution windows. When every circuit declares its window and the admission test passes, the dispatch table is a compile-time theorem. A runtime scheduler is redundant. "General-purpose" is not a property of the scheduler; it is a property of the set of circuits that can be declared. | Paper III — Runtime Is the Kernel |
| W-04 | `misattributed` | "Real-time systems require dedicated RTOS or special hardware" | The observation (real-time requires determinism) is correct. The explanation (determinism requires RTOS) is wrong. Determinism requires declared windows, which the RTOS approximates badly at runtime and the compiler proves exactly at compile time. The RTOS is a runtime compensation for a missing compile-time proof. | Paper I; Paper III — Execution section |
| W-05 | `scoped` | "Cache misses are irreducible runtime variance" | Irreducible only when access patterns are undeclared. When channel tiers are declared and the dispatch table is known before execution, the runtime issues precise prefetch instructions (PRFM) for exactly the addresses each circuit will access. The miss becomes a prefetch hit scheduled at a declared window boundary. | Paper III — Memory section; README benchmark section |
| W-06 | `scoped` | "Garbage collection is necessary for memory safety without unsafe code" | Memory safety without GC follows from declared channel lifetimes. Each channel has a declared tier (ephemeral, task, session, permanent). The compiler proves no circuit reads a channel after its declared lifetime. No runtime collector is needed because there is no undeclared allocation to collect. | Paper II — The Language; Paper III — Memory section |
| W-07 | `scoped` | "Pointer indirection is necessary for dynamic data structures" | Pointer indirection exists to compensate for not knowing the size and location of data at compile time. When channel size and tier are declared, the compiler resolves the physical address at compile time. Dynamic data structures are channels with declared access patterns (W[i] = i for arrays; hash(key) & mask for maps). No indirection required. | Paper II — Every data structure is a channel |
| W-08 | `near-miss` | "Exokernels solve the OS abstraction problem by pushing resource management to applications" | The exokernel diagnoses the right problem (OS abstractions impose unnecessary overhead) but stops at the wrong solution (relocate resource management to the application). Relocation preserves the total complexity — the application still needs a scheduler, a memory manager, a page table. The clock-aware model eliminates runtime resource management entirely by making it a compile-time proof. The exokernel is the closest prior art; the divergence point is "relocate" vs "eliminate". | Paper III — Runtime Is the Kernel; ADR-0002 (clock-aware) |

---

## Rationale

**Why flag rather than auto-reject?**

A paper that contains W-01 ("locks are unavoidable") may be making a *scoped* claim — "in the context of POSIX threads and shared address space, locks are unavoidable." That scoped claim is correct. The paper is not wrong; it is describing a different model. Auto-rejection would discard a potentially valuable document because of an accurate statement about a different paradigm. Manual review distinguishes the scoped claim (acceptable, annotate the scope) from the absolute claim (contradicts the seed, flag for contrastive training).

**Why use contrastive training for accepted-with-annotation documents?**

A model that learns domain-relevant reasoning but never encounters the wrong claims it will face in deployment is fragile. When a user asks "but don't we need locks for concurrent access?", the model needs to know not just the correct answer but the specific structure of the wrong claim it is being asked about. Contrastive training on annotated contradictions produces a model that can engage with the wrong claim directly, not just state the correct answer in isolation.

**Why maintain the register as a versioned file?**

The register is a commitment. Every entry is a claim the project asserts is wrong, with a named source that refutes it. If a future paper or implementation reveals that W-03 ("scheduler is unnecessary") is wrong in some important case, the register must be updated — and the update is visible in git history with a recorded reason. The register cannot drift silently.

---

## Alternatives Rejected

### No contradiction detection (rely on domain relevance + reasoning depth)

**Rejected.** A coherent wrong claim in a domain-relevant document is the highest-risk failure mode. Passing the two-axis gate is necessary but not sufficient for corpus safety.

### Auto-reject any document containing a known-wrong claim

**Rejected.** Scoped correct claims that superficially match a known-wrong pattern would be wrongly rejected. Manual review at the flagging stage preserves the distinction.

### LLM-based contradiction detection (ask a model whether the document contradicts the seed)

**Considered but deferred.** An LLM-based contradiction detector would be powerful but introduces a dependency on the very kind of model we are trying to build. Bootstrapping contradiction detection from the register (keyword + semantic similarity match against known-wrong claim embeddings) is simpler, interpretable, and does not require a fine-tuned model to already exist. LLM-based detection can be added in a later cycle once the base model is available.

---

## Consequences

- The pipeline now has three passes: domain relevance → reasoning depth → contradiction check.
- The known-wrong claims register is a maintained artefact. It grows as the seed corpus grows and as new contradictions are identified in candidate documents.
- Accepted-with-annotation documents require special handling during fine-tuning. The fine-tuning pipeline must support contrastive training on annotated passages.
- The register is a public statement of what the project considers foundational and wrong. It is auditable and challengeable.
