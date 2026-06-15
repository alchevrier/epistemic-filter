# Seed Prior Statement — Root Domain

**Version:** 1.0  
**Date:** 2026-06-15  
**Curator:** Alex Chevrier  
**Seed source:** [`clock-aware-programming`](https://github.com/alchevrier/clock-aware-programming)

---

## 1. The Founding Claim

**Execution windows can be declared at compile time.**

When every circuit declares when it runs, for how long, and which memory regions it reads and writes, the compiler can prove the entire execution schedule before the first instruction executes. This is not a performance optimisation. It is a structural property: the proof exists or the program does not compile.

---

## 2. The Assumption This Rejects

The dominant paradigm of systems software rests on a single invisible assumption:

**Execution timing is undeclared — the system cannot know in advance when things will run, for how long, or what they will access.**

This assumption is never stated. It is background. It is what makes the scheduler, the mutex, the memory barrier, the garbage collector, and the interrupt handler feel like necessary inventions rather than compensations for a missing declaration. Each of these mechanisms exists for one reason: to manage, at runtime, consequences of a timing relationship that was not declared at compile time.

The founding claim does not say the assumption is wrong in all contexts. It says: **the assumption is not universal, and treating it as universal produces systems whose complexity is proportional to what was not declared.**

---

## 3. The Derivation Chain

From the founding claim, the following consequences derive in order. Each step follows from the previous without additional assumptions.

**Step 1 — Channel as the unit of communication.**  
If a circuit declares what it writes and what it reads, communication between circuits is a named, typed, bounded region in memory with a single declared writer. That region is a channel. Channels replace shared mutable state because shared mutable state is what you have when writer identity and timing are undeclared.

**Step 2 — Budget_ticks as the unit of time.**  
If a circuit declares when it runs and for how long, the compiler can verify that declaration against the hardware latency table. The declared duration is budget_ticks — derived from the sum of instruction latencies for the circuit's critical path. Budget_ticks is not an estimate. It is a compile-time proof obligation.

**Step 3 — The dispatch table replaces the scheduler.**  
If every circuit has a declared window (start time, budget_ticks, core affinity) and the admission test proves no two circuits' windows overlap on the same core, the dispatch table is a compile-time theorem. The runtime scheduler has no decisions to make. It is redundant.

**Step 4 — Lock-freedom is a proof, not a technique.**  
If no two circuits access the same memory region in overlapping windows — proved by the channel ownership declarations and the dispatch table — no lock is needed. Lock-freedom is not achieved by using compare-and-swap instead of mutexes. It is proved by the channel model. There is nothing to protect.

**Step 5 — Memory ordering elimination.**  
If the compiler knows which circuit accesses which channel and when, it can generate load/store sequences without conservative barriers. The memory barrier exists to prevent reordering across boundaries where a concurrent writer might exist; the channel model proves no such writer exists.

**Step 6 — Prefetch precision.**  
If the dispatch table is known before execution, the compiler knows which addresses each circuit will access and at which window boundary. PRFM becomes exact — not a hint, not a heuristic — because the access pattern is declared.

**Step 7 — No reboot.**  
If the OS is a set of kernel circuits in the same dispatch table as application circuits, a kernel update is a circuit swap — the new circuit is proved compatible before the swap, the old circuit is removed. No reboot is required because there is no moment of inconsistency: the proof precedes the transition.

---

## 4. What the Derivation Chain Eliminates

At each step, a mechanism that the dominant paradigm considers necessary becomes structurally redundant — not optimised, not avoided, but made inapplicable:

| Eliminated | Made redundant by |
|---|---|
| Runtime scheduler | Dispatch table (Step 3) |
| Mutex / lock | Channel ownership proof (Step 4) |
| Memory barrier / fence | Non-overlapping window proof (Step 5) |
| Garbage collector | Declared channel tiers (lifetime = tier) |
| PRFM as hint | PRFM as exact compile-time instruction (Step 6) |
| Interrupt handler (for known-rate events) | Declared poll window |
| Reboot | Proved circuit swap (Step 7) |
| Virtual dispatch (vtable) | Declared channel type |
| Context switch | Non-overlapping windows by construction |

Each of these is a compensation for undeclared timing. Declaring timing makes each one inapplicable — not unnecessary in the sense of being skipped, but structurally irrelevant in the sense of solving a problem that does not arise.

---

## 5. The Boundary Statement

The following types of first-principles documents would be expected to **fail domain relevance** (cosine similarity < 0.85 against the seed centroid), even if they reason from stated premises with full derivation chains:

- **Byzantine fault tolerance / distributed consensus** — correct first-principles reasoning about agreement under partial failure. The centroid is in declared-timing single-machine systems, not distributed agreement protocols. Would pass reasoning depth; fail domain relevance.

- **Formal verification of concurrent programs (TLA+, separation logic)** — correct derivation-based work. But the frame accepts concurrent access as a given and proves properties about it. The seed frame eliminates concurrent access by construction. Adjacent; not the same frame.

- **RTOS design and implementation** — the RTOS is the closest prior art, and documents about it will score moderately on domain relevance. They fail because RTOS approximates declared timing at runtime; the seed frame proves it at compile time. Score expected: 0.70–0.82 (below threshold).

- **High-performance networking (DPDK, RDMA)** — relevant vocabulary, but the frame is about throughput and latency optimisation within the undeclared-timing assumption. Zero-copy, lock-free rings, busy-polling — all are compensations. Expected score: 0.65–0.80.

- **Rust memory safety (borrow checker, ownership)** — the borrow checker is the closest existing approximation of channel ownership in a real language. Documents about Rust will score 0.75–0.88 — borderline. Those that focus on ownership as a compile-time proof mechanism (close to the seed frame) may pass. Those that focus on Rust as a systems language (performance, safety without GC) will score lower.

Documents that fall below 0.85 are not wrong. They are not in the domain. The boundary is not a quality judgment. It is a centroid position.

---

## 6. Why This Seed Is Valid

- Every claim in the seed documents is derived from the founding claim or from a previous derivation step
- The curator (Alex Chevrier) authored the seed documents and can derive every claim from the founding claim in a live session
- No claim in the seed is accepted on the authority of another person or prior work — where prior work is referenced (exokernel, LMAX Disruptor, RCU), it is as evidence or contrast, not as foundation
- The seed is internally consistent: all documents share the same foundational assumption (execution windows can be declared) and derive from it in the same direction
- The W-register (17 entries, `corpus/known-wrong-claims.json`) was built by auditing what the dominant paradigm believes that the seed refutes — it came from this prior statement, not from a general survey of common mistakes
