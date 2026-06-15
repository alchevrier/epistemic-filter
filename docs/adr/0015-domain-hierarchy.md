# ADR-0015: Domain Hierarchy Definition

**Date:** 2026-06-15  
**Status:** Accepted

---

## Context

Multiple ADRs reference a domain hierarchy without formally defining it. The hierarchy determines: which centroid a document is scored against, which base model is used for each branch, and how training data is mixed across levels. Without a formal definition, the hierarchy is an aspiration, not an implementable structure.

---

## Decision

The domain hierarchy is a tree. Each node has:
- A **name** and **description**
- A **seed corpus** (documents that define the positive class for that node)
- A **centroid** derived from embedding the seed corpus
- A **parent node** (except the root)
- A **level** (0 = root, 1 = branch, 2 = leaf)

### The Tree

```
Level 0 — Root
└── SystemEngineering
    Seed: clock-aware-programming (all papers + ADRs)
    Centroid: derived from full seed corpus
    Description: Systems that declare resource usage at compile time
                 to eliminate runtime compensation mechanisms

Level 1 — Branches
├── Hardware
│   Seed: clock-aware Paper IV + ARM/RISC-V architecture manuals
│         + selected FPGA synthesis papers
│   Centroid: derived from hardware seed
│   Description: Silicon design, timing constraints, instruction pipelines,
│                memory hierarchies, clock domains
│
└── Software
    Seed: clock-aware Papers I–III + selected compiler/OS papers
    Centroid: derived from software seed
    Description: Programming models, operating systems, compilers,
                 runtime systems, language design

Level 2 — Leaves
├── Hardware
│   ├── FPGA
│   │   Seed: FPGA synthesis papers, constraint files, HLS documentation
│   │   Description: Reconfigurable logic, clock domain crossing,
│   │                LUT utilisation, timing closure
│   │
│   └── ProcessorDesign
│       Seed: CPU architecture papers, microarchitecture documentation,
│             pipeline design, cache hierarchy
│       Description: In-order vs OOO, execution ports, branch prediction,
│                    memory subsystem design
│
└── Software
    ├── OperatingSystems
    │   Seed: clock-aware Paper III + selected OS papers
    │         (exokernel, capability systems, real-time OS)
    │   Description: Scheduling, memory management, device drivers,
    │                IPC, security models
    │
    ├── Compilers
    │   Seed: LLVM documentation, compiler construction papers,
    │         instruction selection, register allocation
    │   Description: IR design, code generation, optimisation passes,
    │                static analysis, type systems
    │
    └── SystemsProgramming
        Seed: clock-aware Paper II + Rust reference,
              selected C++ standards papers, POSIX specifications
        Description: Language design for systems, memory models,
                     concurrency primitives, ABI, linking
```

### Centroid Derivation

For each node, the centroid is computed by:
1. Embedding all documents in the node's seed corpus using `nomic-embed-text`
2. Computing the arithmetic mean of all embeddings
3. L2-normalising the result
4. Storing as `hierarchy/{node_name}/centroid.npy`

A document scored against a specific node uses that node's centroid for the domain relevance score. A document may be scored against multiple nodes — it is admitted to the highest-scoring node that passes both thresholds.

### Inheritance

Each node inherits its parent's seed corpus as a minority component of its own seed:
- Root seed: 100% SystemEngineering documents
- Branch seed: 70% branch-specific + 30% root seed
- Leaf seed: 60% leaf-specific + 25% parent branch + 15% root seed

This ensures that a Compilers-level document retains awareness of the root insight ("declare timing, eliminate compensation") even as it specialises. Without inheritance, the leaf models diverge from the founding principle.

### Single Aggregate Model

The hierarchy does not produce separate models per node. It produces **one model** trained on the aggregate of all domain seeds, with domain boundaries maintained by the training mix and the cross-domain bridge annotations.

- Root seed contributes the founding prior — present in every training epoch
- Branch seeds add domain-specific vocabulary and reasoning patterns
- Leaf seeds add sub-domain depth
- Cross-domain bridges (ADR-0010) are the mechanism that prevents any single domain's frame from dominating
- Contrastive training pairs (W-register, ADR-0008) are the mechanism that makes contradictions across domains explicit during training

The model internalises domain boundaries through training, not through separate model files. The contradiction between a RCU expert's seed and the clock-aware seed is resolved during training via the contrastive pairs — not at inference time by routing between separate models.

Training schedule: root seed first (establishes founding prior), branch seeds added in subsequent cycles, leaf seeds added last. Each cycle fine-tunes from the previous checkpoint — the common prior is paid once, domain deltas are incremental.

### Routing

At inference time, the user's query is embedded and compared against all node centroids. The centroid with the highest cosine similarity identifies the domain context — the model uses this as a prompt prefix or system instruction to activate the relevant domain prior within the single model. If no node exceeds 0.70 similarity, the root prior is used.

There is no external dispatcher and no per-domain model file to load. The routing is a context signal to one model, not a selection between multiple models.

---

## Rationale

**Why three levels (root → branch → leaf)?**

Root captures the founding insight. Branch captures hardware vs software split — these are genuinely different vocabularies and reasoning styles. Leaf captures specific sub-domain expertise. Four levels would over-specify at current corpus size; two levels would under-differentiate the branches.

**Why inherit parent seed into child seed?**

Without inheritance, a leaf model trained only on FPGA papers would lose the connection to the root insight. It would become a domain expert that knows FPGA deeply but cannot relate FPGA timing constraints to the clock-aware programming model. Inheritance keeps the connection alive.

**Why a single aggregate model rather than separate models per node?**

Separate models per node requires loading a different model file per query — incompatible with the goal of multiple agents simultaneously resident in memory. A single model with all domain priors baked in is always loaded, always available, and routes by context signal rather than by model swap. The contradiction between domains (e.g., RCU literature vs clock-aware literature) is resolved during training via contrastive pairs — producing a model that holds both and can reason about the difference — not by isolating them into separate models that never interact.

**Why routing by centroid similarity at inference time?**

The routing decision must be fast and interpretable. Centroid similarity is computed in milliseconds and the routing decision is auditable — you can see which centroid won and by how much. The winning centroid's domain identity is passed as context to the single model, activating the relevant prior without loading a different model.

---

## Consequences

- The first training cycle builds the root-only model and validates the pipeline end-to-end before adding branch or leaf seeds.
- Branch seeds are second-cycle work — after the root model passes the benchmark (ADR-0013).
- The `hierarchy/` directory structure must be initialised before branch-level scoring begins.
- The routing context signal is second-cycle work — implemented once a second domain seed exists to differentiate from.
- Each new leaf requires a seed corpus definition (ADR-0016), a centroid derivation run, a benchmark variant (ADR-0013 questions adapted for the leaf domain), and a W-register extension for the leaf's domain framing traps. This is documented in the leaf's own ADR when it is created.
- One model file. All domains. Domain context passed at inference time, not at load time.
