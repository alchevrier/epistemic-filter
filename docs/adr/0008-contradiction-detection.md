# ADR-0008: Contradiction Detection and Known-Wrong Claims

**Date:** 2026-06-15  
**Status:** Accepted

---

## Context

The two-axis quality gate (ADR-0001) admits documents that are domain-relevant and reason from first principles. It does not check whether those documents are *correct* relative to the seed corpus's foundational claims. A rigorous, domain-relevant paper that gets a key concept wrong is the most dangerous kind of false positive: the fine-tuned model will learn the wrong claim with high confidence, precisely because the surrounding reasoning is coherent and well-structured. Noise averages out across the corpus. A coherent wrong claim reinforces itself.

**A claim is limiting if treating it as true requires multiple independent compensation mechanisms.** This is the operational definition used throughout the pipeline. The threshold is ≥ 3 compensation mechanisms — a count that is observable from inside any frame, without requiring the evaluator to already know the claim is wrong. (See ADR-0016 for the full definition and examples.)

The known-wrong claims register (W-register) is the pipeline's record of limiting beliefs at different stages of structural failure. Detecting them in incoming documents before training is the function of this ADR.

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
| `framing-trap` | Locally correct, technically rigorous, but presents a compensation as a solution — actively training engineers away from questioning the underlying assumption | Train the model to step back and ask "what assumption makes this mechanism necessary?" |
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
| W-09 | `scoped` | "std::atomic / the C++ memory model is the correct abstraction for concurrent hardware access" | Correct within the assumption that timing is undeclared. `std::atomic` compensates for the compiler not knowing which threads access which memory and when. When execution windows are declared at compile time and the channel model enforces single-writer ownership, atomic operations are structurally redundant — no two circuits access the same memory region in overlapping windows. C++ accretes compensating mechanisms (`std::atomic`, `std::jthread`, `std::pmr`) because each wrong foundation is still present; the language is a committee product that can add but never remove. | Paper I — The Root Observation; Paper III — Memory section; ADR-0007 (clock-aware) |
| W-10 | `misattributed` | "Managed runtimes (JVM, GC) are a necessary productivity trade-off for safe concurrent programming" | The observation (programmer productivity matters) is correct. The explanation (JVM/GC is the necessary cost of that productivity) is wrong. JVM and GC compensate for undeclared memory lifetimes and undeclared execution windows — the same missing declarations that make locks necessary. The productivity cost is not GC vs no-GC; it is "declare your timing" vs "don't declare it and pay at runtime." With AI-assisted authorship and a four-rule language, declaring timing is not a productivity cost at all. LMAX Disruptor is the empirical proof: a JVM system engineered to avoid GC pauses in the hot path — meaning the engineers spent enormous effort un-doing what the JVM does by default to recover the latency properties that declared timing would have given for free. | Paper II — The Language; Paper III — Memory section; README — no reboot section |
| W-11 | `framing-trap` | "RCU (read-copy-update) is the correct solution to the concurrent read performance problem" | The observation (concurrent reads are performance-critical) is correct. RCU is not a solution — it is a compensation for undeclared read access patterns. When which circuit reads which memory region and when is declared at compile time, the read is a single-writer channel subscription. No reader contention exists by construction. No grace period required. No generation counter. RCU is technically impressive and locally correct; it trains engineers to master the compensation rather than question the assumption that made the compensation necessary. Documents presenting RCU as a general solution are framing traps: they obscure the OS and scheduler assumptions that create the concurrent read problem in the first place, and mislead engineers into investing expertise in compensating mechanisms rather than in the missing model. | Paper I — The Root Observation; ADR-0003 (clock-aware) — RCU elimination |
| W-12 | `framing-trap` | "Dynamic memory allocation is necessary because application memory requirements cannot be known in advance" | Every production low-latency system contradicts this claim in its own codebase: object pools, arena allocators, slab allocators, pre-allocated ring buffers — all are runtime reimplementations of what the clock-aware channel declaration does at compile time. The engineer who writes an object pool is implicitly declaring that allocations are bounded and predictable, while explicitly refusing to say so at the language level. Memory is finite. Applications are bounded. The bounds are knowable — they follow from the circuit's declared channels, their tiers, and their sizes. `malloc` exists to compensate for the absence of that declaration. The dynamic allocator is not a solution to unbounded memory requirements; it is a runtime mechanism for managing declared-but-undeclared bounds at unpredictable cost. GC pause, heap fragmentation, and allocator lock contention are not properties of memory — they are properties of not having declared the memory layout at compile time. | Paper II — The Language (channel declarations); Paper III — Memory section; ADR-0008 (clock-aware) — memory management |
| W-13 | `framing-trap` | "The JVM is efficient at memory allocation — bump pointer allocation is O(1)" | Correct in isolation. The IOU is not. Bump pointer allocation is fast because it defers 100% of the reclamation cost to the garbage collector, which must then: trace the entire live object graph, identify unreachable objects, compact or sweep fragmented heap regions, update every pointer that moved during compaction, and pause or interleave all of this with application threads under stop-the-world or concurrent marking protocols. The allocation appears O(1) and cheap; the GC cycle that follows is O(live heap) in time, O(heap size) in memory bandwidth, and unpredictable in timing. The JVM's allocation efficiency is a local measurement that obscures the global cost. Every byte allocated cheaply is a byte the GC must account for later — with interest. The total cost per object over its lifetime is not the allocation cost; it is the allocation cost plus the GC cost plus the write barrier cost plus the card table maintenance cost. Measured that way, bump pointer allocation is not efficient. It is an efficient way of making the cost invisible until it is too late to avoid it. | Paper III — Memory section; W-10 (JVM productivity); W-12 (dynamic allocation) |
| W-14 | `false` | "C++ is close to the hardware" | False on two counts simultaneously, neither of which is scoped. First: the hardware is not imperative. An OOO processor has no concept of sequential statement ordering — it has data dependencies, pipeline stages, and execution ports. C++ source is a sequential narrative that the compiler backend and the OOO engine spend enormous effort translating into something the hardware can exploit. The abstraction gap is not thin; it is the entire compiler backend plus the OOO engine plus the branch predictor plus the memory subsystem. Second: the claim is self-refuting in practice. When producing predictable code generation requires knowledge of aliasing rules, `restrict`, `__builtin_expect`, `__attribute__((packed))`, `volatile` semantics, `std::launder`, `std::atomic` memory ordering, and architecture-specific intrinsics — the abstraction is not close to the hardware, it is failing to abstract it, and deep specialist knowledge is required to negotiate the failure. The channel declaration model is closer to the hardware than C++: a declared channel with a declared tier and a declared access pattern maps directly to a physical memory region at a known address with a known latency. No negotiation. No escape hatches. No compiler archaeology. | Paper II — The Language; Paper IV — Hardware Architecture; README benchmark section |
| W-15 | `misattributed` | "Language X is the right tool for domain Y because it is inherently suited to it" | The observation (certain languages dominate certain domains) is correct. The causal explanation (technical fitness) is wrong — the causation runs in reverse. Python dominates ML not because it is efficient at tensor operations (NumPy is C under a Python interface) but because the first ML frameworks were written in Python, which attracted ML researchers, which produced more Python ML libraries, which attracted more ML researchers. Java dominates enterprise not because it is safe or productive for large teams but because Sun's 1990s marketing, university adoption, and the resulting talent pool made Java the path of least hiring resistance. C++ dominates HFT not because it is close to the hardware (W-14) but because the first HFT systems were written by engineers who came from C, and institutional knowledge, interview pipelines, and library ecosystems calcified around it. In every case: the language that arrived first with sufficient institutional backing became the hiring signal, which became the talent pool, which became the library ecosystem, which became "the right tool." Technical fitness is reverse-engineered after the fact to justify a social reality. The actual determinant of language dominance is: which libraries exist, which jobs are advertised, and which profile of engineer is being hired — none of which are properties of the language's technical merits. | Paper II — The Language (four rules, designed from declarations down, not from a syntax up) |
| W-16 | `misattributed` | "Domain expertise and role specialisation produce the innovations that change a field" | The observation (experts advance fields incrementally) is correct within a paradigm. The explanation (role specialisation produces paradigm shifts) is wrong — the causation runs in the opposite direction. Every paradigm shift in computing was made by someone who did not fit the existing role: Thompson and Ritchie were building an OS and needed a language that didn't exist — the "C programmer" role came after the work. Torvalds was a student who found the existing OS unsatisfying and wrote his own — not a kernel engineer by training. McCarthy was an AI researcher who needed a notation for symbolic computation and invented Lisp as a side effect — not a language designer. Knuth was a mathematician who found typesetting tools wrong and built TeX — not a typographer. In every case: the person who created the paradigm was not optimised for the existing paradigm. They were optimised for a problem the existing paradigm could not solve. The institutional hiring process selects for fit with the current paradigm — which is precisely why it excludes the people most likely to replace it. You cannot write a job description for a role that does not yet exist. The profile of a clock-aware systems engineer has no job posting. That is not a weakness of the idea; it is evidence that the idea is genuinely outside the existing framing. | ADR-0009 (epistemic-filter) — source context; seed corpus authorship context |
| W-17 | `misattributed` | "Deep domain specialisation produces the broadest and most general insights" | The observation (specialists produce deep insights within their domain) is correct. The explanation (depth within one domain generalises) is wrong. Deep specialisation produces local optimisation within a frame, not challenge to the frame. A world-class Linux kernel engineer has extraordinary mastery of scheduling, locking, and memory management — all within the assumption that timing is undeclared. That mastery makes the assumption invisible: it is the water they swim in, their professional identity, their peer vocabulary. They can optimise within the frame to an extraordinary degree and cannot see the frame at all. Intel's chip design process illustrates the institutional version: cross-domain workload analysis (HPC, ML, database, networking) is applied at the feature level — wider SIMD for ML, larger cache for database, lower latency for networking. The synthesis happens inside the wrong frame (OOO + undeclared timing) and produces a chip that serves all workloads adequately and none optimally. The general insight — "declare timing, eliminate compensation" — is not available to any domain specialist working alone. It requires seeing the structural pattern across domains simultaneously. That is only possible for someone who is not fully captured by any one domain's frame. The cross-domain view is not a luxury; it is the precondition for seeing what the specialists cannot. | ADR-0010 (epistemic-filter) — cross-domain reinforcement; W-16 |

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
