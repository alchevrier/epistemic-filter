# ADR-0013: Evaluation Benchmark

**Date:** 2026-06-15  
**Status:** Accepted

---

## Context

The fine-tuned model needs a termination condition and a falsifiable quality claim. Without a defined benchmark, "the model is better" is an opinion. With a benchmark, it is a measurement. The benchmark must test the specific capabilities the corpus was designed to produce — not general LLM capabilities, but domain-specific first-principles reasoning and wrong-claim recognition.

The benchmark also defines what "better than the base model" means operationally. This is the proof that the corpus pipeline works.

---

## Decision

The benchmark has three components, each testing a distinct capability the fine-tuning is designed to produce.

---

### Component 1 — Frame Identification (25 questions)

**Tests:** Can the model identify the limiting assumption of a claim and state what changes when the assumption is removed?

**Format:** Each question presents a domain claim and asks the model to:
1. Name the assumption the claim depends on
2. State what the conclusion becomes when the assumption is removed
3. Cite the mechanism that becomes redundant

**Example:**
> Q: "In concurrent systems, reads and writes to shared data must be protected by locks or atomic operations." What assumption does this claim depend on, and what changes when that assumption is removed?
> 
> Expected: The claim assumes execution windows are undeclared — multiple threads may access the same memory region simultaneously. When execution windows are declared at compile time and single-writer channel ownership is proved, no two circuits access the same region in overlapping windows. Locks and atomics become structurally redundant. The shared mutable state the claim describes does not exist when timing is declared.

**Scoring:** 0 (wrong assumption identified), 1 (assumption correct, consequence incomplete), 2 (assumption correct, consequence fully derived, mechanism named)

**Pass threshold:** ≥ 1.6 average (80% of full credit across 25 questions)

---

### Component 2 — Wrong-Claim Classification (17 questions, one per W-register entry)

**Tests:** Can the model classify the degree of a known-wrong claim and produce the correct contrastive response?

**Format:** Each question presents a claim from the W-register (without naming it as such) and asks:
1. What degree is this claim? (scoped / near-miss / misattributed / framing-trap / false)
2. What is the correct refutation at that degree?

**Example:**
> Q: "The JVM's bump pointer allocation is O(1) and highly efficient." What degree of wrongness is this claim, and what is the correct response?
>
> Expected: framing-trap. The allocation cost is O(1) but the claim presents a local measurement as a global property. The full cost per object includes GC tracing, compaction, pointer updating, write barrier maintenance, and card table overhead — O(live heap) in time, unpredictable in timing. The efficiency is real but the efficiency claim is an IOU deferred to the GC cycle.

**Scoring:** 0 (wrong degree), 1 (correct degree, incomplete refutation), 2 (correct degree, full refutation with mechanism)

**Pass threshold:** ≥ 1.6 average

---

### Component 3 — Cross-Domain Bridge (9 questions, one per cross-domain mapping in ADR-0010)

**Tests:** Can the model identify the structural isomorphism between a cross-domain document and the primary domain claim it reinforces?

**Format:** Each question presents a passage from a cross-domain domain (logistics, finance, biology, etc.) and asks the model to:
1. Identify the structural pattern it instantiates
2. Name the primary domain equivalent mechanism
3. State the bridge — why the two are structurally identical despite different vocabulary

**Example:**
> Q: "Toyota's kanban system eliminates buffer inventory by making parts arrive exactly when needed, making the buffer's existence pointless." What primary domain mechanism is this structurally identical to, and why?
>
> Expected: Lock-free channel declarations in clock-aware programming. Kanban declares arrival windows (parts arrive at declared times). Buffer inventory exists to compensate for undeclared arrival timing. When timing is declared, the buffer is redundant — not improved, eliminated. In the primary domain: declared execution windows eliminate locks. Lock is the buffer. Channel declaration is the kanban. The structural derivation is identical; only the vocabulary differs.

**Scoring:** 0 (no connection identified), 1 (connection identified, bridge incomplete), 2 (full bridge with structural derivation)

**Pass threshold:** ≥ 1.4 average (70% — cross-domain is harder, slightly lower bar)

---

### Baseline Comparison

Every benchmark question is run against:
1. **Base Phi-3 Mini** (before fine-tuning) — establishes the baseline
2. **Fine-tuned model** (after fine-tuning) — measures improvement
3. **Claude Sonnet** (frontier model) — establishes the ceiling

The fine-tuned model must exceed the base model on all three components. It does not need to exceed Claude Sonnet — but the gap should be small on Components 1 and 2 (domain-specific reasoning), and potentially inverted on Component 3 (cross-domain bridges that Claude has not seen explicitly).

---

### Benchmark Question Set

The benchmark question set is **fixed and held out** — it is never in the training corpus. 51 questions total (25 + 17 + 9). Written before the first training run and not modified afterwards. Modifications to the question set invalidate prior benchmark results.

The question set is stored at `benchmark/questions.json` in the repository.

---

## Pass Criteria for Model Graduation

The fine-tuned model graduates (is ready for use as the domain LLM) when:

1. Component 1 (Frame Identification): ≥ 1.6/2.0 average
2. Component 2 (Wrong-Claim Classification): ≥ 1.6/2.0 average  
3. Component 3 (Cross-Domain Bridge): ≥ 1.4/2.0 average
4. All three components exceed base Phi-3 Mini scores by ≥ 0.3 points average

If any component fails: diagnose which corpus tier is underrepresented (Component 1 → primary domain, Component 2 → contrastive training, Component 3 → cross-domain), add documents, retrain.

---

## Rationale

**Why not use existing benchmarks (MMLU, HellaSwag, etc.)?**

Existing benchmarks test general capabilities. The fine-tuned model is not trying to improve on general capabilities — it is trying to produce domain-specific first-principles reasoning that the base model does not have. Existing benchmarks will not measure this and will likely show regression (expected: fine-tuning on a narrow corpus degrades general performance slightly). That regression is acceptable and expected.

**Why 51 questions?**

Small enough to run in under an hour on CPU. Large enough to produce statistically meaningful averages per component. The benchmark is run after every training cycle — it must not be a bottleneck.

**Why is the question set fixed and held out?**

Benchmark validity requires that the questions were never seen during training. Modifying the question set after seeing training results introduces selection bias — questions are chosen because the model does well on them, not because they test the right capabilities. Fixed and held out from the start.

**Why include Claude Sonnet as a ceiling?**

To distinguish "the fine-tuned model is better than the base at this domain" from "the fine-tuned model has reached the ceiling of what any model can do with this domain." If the fine-tuned model exceeds Claude Sonnet on Component 3 (cross-domain bridges), that is a meaningful result — it means the bridge annotations in the corpus contain signal that the frontier model's training data does not.

---

## Consequences

- The benchmark question set must be written before the first training run. It is a prerequisite, not a post-hoc evaluation.
- Benchmark results are stored in `benchmark/results/` with model version, date, and per-question scores. Never overwritten — appended.
- The graduation criteria are a falsifiable claim: the corpus pipeline either produces a model that meets them or it does not. If it does not, the corpus needs diagnosis and improvement.
