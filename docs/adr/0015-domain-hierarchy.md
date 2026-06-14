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

### Fine-Tuning per Node

Each node produces a separate fine-tuned model:
- Root model: trained on full primary corpus + cross-domain corpus
- Branch models: trained on branch corpus + 20% root corpus
- Leaf models: trained on leaf corpus + 20% branch corpus + 10% root corpus

Branch and leaf models are fine-tuned from the parent model (not from the base Phi-3 Mini), paying for the common prior once. A leaf model is the parent model with a delta fine-tuning — estimated training time per leaf: 4–8 hours CPU.

### Routing

At inference time, the user's query is embedded and compared against all node centroids. The node with the highest cosine similarity routes the query to the corresponding model. If no node exceeds 0.70 similarity, the root model handles the query.

---

## Rationale

**Why three levels (root → branch → leaf)?**

Root captures the founding insight. Branch captures hardware vs software split — these are genuinely different vocabularies and reasoning styles. Leaf captures specific sub-domain expertise. Four levels would over-specify at current corpus size; two levels would under-differentiate the branches.

**Why inherit parent seed into child seed?**

Without inheritance, a leaf model trained only on FPGA papers would lose the connection to the root insight. It would become a domain expert that knows FPGA deeply but cannot relate FPGA timing constraints to the clock-aware programming model. Inheritance keeps the connection alive.

**Why fine-tune leaf models from parent models?**

Training each leaf from the base model independently is 6× the training cost. Training from the parent model (which already carries the branch prior) means the leaf fine-tuning only needs to learn the leaf-specific delta. This is the same efficiency argument as QLoRA: pay for the common prior once.

**Why routing by centroid similarity at inference time?**

The routing decision must be fast and interpretable. Centroid similarity is computed in milliseconds and the routing decision is auditable — you can see which centroid won and by how much. A learned router (classification head) would be faster but less transparent and requires additional training.

---

## Consequences

- The hierarchy is the long-term target. The first implementation builds only the root model and validates the pipeline end-to-end before branching.
- Branch and leaf models are second-cycle work — after the root model passes the benchmark (ADR-0013).
- The `hierarchy/` directory structure must be initialised before branch-level scoring begins.
- The routing system is third-cycle work — implemented after at least two branch models exist.
- Each new leaf requires a seed corpus definition, a centroid derivation run, and a benchmark variant (ADR-0013 questions adapted for the leaf domain). This is documented in the leaf's own ADR when it is created.
