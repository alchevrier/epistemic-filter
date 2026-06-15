# ADR-0016: Seed Construction Methodology

**Date:** 2026-06-15  
**Status:** Accepted

---

## Context

The seed corpus is the positive class definition — it determines what "domain relevant" means, what "first-principles reasoning" looks like, and what the centroid the pipeline filters against actually represents. Everything downstream (corpus acceptance, model training, benchmark construction) depends on the seed being correct.

The current implementation uses a single specific seed: the `clock-aware-programming` repository. For the pipeline to be reproducible by other practitioners in other domains, the methodology for constructing a seed must be explicit — not just the instance.

The core problem is circular: to build a seed, you need to know what good reasoning in your domain looks like. To know that, you need domain expertise. The pipeline cannot bootstrap that expertise. It can only scale it.

This ADR defines the methodology a domain expert follows to construct a valid seed corpus for their domain.

---

## Decision

### What a Seed Is

A seed corpus is a **minimal, internally consistent, first-principles body of writing** that defines the positive class for the domain. It is the embodiment of the epistemic standard the pipeline enforces — the centroid the similarity gate measures against, and the reasoning pattern the depth classifier is calibrated to.

A seed is not:
- A curated reading list of the best papers in the field
- A survey of the state of the art
- An anthology of authoritative voices

A seed is:
- Writing that derives conclusions from stated premises at every step
- Writing from a consistent epistemic position — not a collection of perspectives
- Writing where you, the curator, can defend every claim from first principles

**If you cannot defend a claim in your seed from first principles, remove it.** It will anchor the centroid in the wrong place and calibrate the depth classifier to a lower standard.

---

### Minimum Seed Requirements

| Property | Minimum | Notes |
|---|---|---|
| Document count | 5 | Below 5, the centroid is too sensitive to individual documents |
| Token count | ~50,000 tokens | Enough for a stable embedding centroid |
| Internal consistency | Required | All documents share the same foundational assumptions |
| First-principles density | High throughout | Primarily derivation, not assertion or survey |
| Your authorship or deep familiarity | Required | You must be able to challenge any claim in the seed |

---

### Step 1 — Identify Your Prior

Before collecting any documents, write a one-page statement of your domain prior:

1. **What is the founding claim of your domain?** The single statement that, if true, changes what follows. In clock-aware programming: "Execution windows can be declared at compile time." In LLVM: "A program's semantics can be represented as a graph of typed values without temporal commitment."

2. **What assumption does most work in your field implicitly accept that your founding claim rejects or refines?** This is the W-register seed. In clock-aware programming: "Execution timing is necessarily undeclared." In LLVM: "The IR is a convenient intermediate; the real semantics live in the source or the binary."

3. **What is the derivation chain from founding claim to your most specific current work?** Each step is a potential seed document. If you cannot state the chain, the seed is not ready.

Write this statement. It is the ground truth against which you evaluate every seed document. If a document does not follow from this statement — even if it is excellent writing in your field — it does not belong in the seed.

---

### Step 2 — Select Seed Documents

Seed documents must satisfy all of the following:

**Criterion A — Premises explicit.** Every major claim in the document is derived from a stated premise. The reader can identify where the derivation begins and follow each step. Documents that assert conclusions from authority or consensus fail this criterion.

**Criterion B — Assumptions examinable.** The document names or implies assumptions that can be contested. Assumptions invisible to the document (treated as universal background) are framing traps. A document that cannot be contested has assumptions so embedded the author cannot see them — and neither will the model trained on it.

**Criterion C — Consistent foundational position.** The document shares the epistemic position in your prior statement. A document that is excellent first-principles reasoning but from a different founding claim will pull the centroid sideways.

**Criterion D — You can defend it.** You have read it, you understand every step, and you could reproduce the key derivations in a whiteboard session. Documents you accept on trust from authority do not qualify.

---

### Step 3 — Audit the Seed for Framing Traps

This is the step most practitioners skip and the one that most determines output quality.

For each claim in each seed document, ask:

1. **Is this claim correct only within an assumption I have not stated?** If yes, state the assumption explicitly or remove the claim.
2. **Does this claim present a compensation mechanism as a solution?** (e.g., "RCU is the correct solution for concurrent reads" — correct locally, but presents compensation as solution.) If yes, this is a framing-trap candidate for the W-register, not seed material.
3. **Could someone who accepted the dominant paradigm of this field read this document and find it unremarkable?** If yes, the document is likely inside the existing frame, not outside it. Seed documents should be mildly or strongly counterintuitive to a practitioner who has not questioned the dominant paradigm.

The output of this step is a draft W-register: claims you found in your own candidate seed material that are scoped, near-miss, misattributed, framing-trap, or false. These do not go into the seed. They go into `corpus/known-wrong-claims.json`.

---

### Step 4 — Compute and Inspect the Centroid

Once seed documents are selected:

1. Embed each document with nomic-embed-text
2. Compute the centroid (mean of all document embeddings)
3. Rank all seed documents by cosine similarity to the centroid
4. Inspect the bottom 2–3 documents

**If the lowest-similarity seed document has cosine similarity < 0.70 against the centroid:** the seed is not internally consistent. The low-similarity document is pulling the centroid away from the core prior. Either remove it or identify why it belongs — if you cannot articulate why, remove it.

**If all seed documents have cosine similarity > 0.95:** the seed may be too narrow. A seed that is perfectly self-similar produces a centroid that rejects adjacent first-principles work in the same domain. Consider whether you are defining a document style rather than a domain prior.

The target internal similarity range is **0.75–0.92** across seed documents. Enough coherence to define a direction; enough spread to cover the domain's legitimate variation.

---

### Step 5 — Name the Boundary

Write a one-paragraph boundary statement: what types of first-principles documents in your domain would you expect to *fail* the domain relevance gate, and why. This tests whether the centroid is in the right place.

Example for clock-aware programming: "A first-principles paper on Byzantine fault tolerance, even if it reasons from stated premises with full derivation chains, would fail domain relevance — the centroid is in declared-timing systems, not distributed consensus. It would pass reasoning depth and fail domain relevance. That is the correct outcome."

If you cannot write this statement — if you cannot name what the centroid should reject — the centroid is not well-defined. Iterate on seed selection until you can name the boundary.

---

### Step 6 — Lock the Seed

Once the centroid is stable and the boundary is named:

- Commit the seed documents to `corpus/seed/`
- Commit the centroid vector to `corpus/centroids/seed_v1.json`
- Commit the prior statement and boundary statement to `corpus/seed/prior.md`
- Tag the commit: `seed-v1`

**The seed is now locked.** Do not modify seed documents after the first corpus acceptance cycle begins. Changes to the seed invalidate all prior acceptance decisions — the cosine similarity of every previously accepted document against the new centroid must be recomputed.

If you discover a seed document contains a framing trap after locking: move it to the W-register, recompute the centroid, tag as `seed-v2`, and note which documents require re-scoring.

---

## Rationale

**Why must the curator be able to defend every seed claim?**

The pipeline scales the seed. If the seed contains a claim the curator accepted on authority — plausible, well-sourced, but not personally derived — and that claim is subtly wrong, the model will reproduce it at scale with high confidence. The curator's personal derivability is the only quality gate that catches this. No automated tool can substitute for it.

**Why is internal consistency required rather than coverage?**

A seed that covers the domain broadly but inconsistently produces a centroid that points in no particular direction — it accepts documents that superficially match the domain vocabulary rather than documents that reason from the domain's founding claim. Breadth without a consistent prior produces a general domain corpus, not an epistemically filtered one. Narrow, deep, consistent beats broad, shallow, representative.

**Why does the W-register come from the seed audit?**

The framing traps most likely to appear in accepted corpus documents are the ones that look like seed material but aren't. They come from the same body of work, the same community, the same vocabulary. The seed audit is where you encounter them in their most convincing form — embedded in otherwise excellent writing. The W-register built from the seed audit is higher quality than one built from general field knowledge because it captures the specific compensation mechanisms that are invisible from inside the domain frame.

---

## Failure Modes

| Failure | Symptom | Recovery |
|---|---|---|
| Seed contains authority-accepted claim the curator hasn't derived | Model confidently wrong in a specific way that matches a field consensus | Identify which seed claim is the source; move to W-register; recompute centroid |
| Seed too narrow | Centroid rejects valid adjacent first-principles work | Add 2–3 seed documents from the adjacent area; recompute |
| Seed too broad | Centroid accepts domain vocabulary without reasoning depth | Tighten to documents the curator authored or deeply understands; remove survey material |
| Prior statement cannot be written | Curator does not have a clear founding claim | Do not proceed. The pipeline cannot manufacture a prior that does not exist. |
| Boundary cannot be named | Centroid is undefined relative to adjacent domains | Add negative examples: 3–5 documents the curator is certain should be rejected, embed them, verify they fall below 0.85 threshold |

---

## Consequences

- Seed construction is a prerequisite to running the pipeline. It cannot be parallelised with pipeline setup.
- Minimum time to construct a valid seed: several days of careful reading and the prior statement writing. It cannot be done in an afternoon.
- The seed is a statement of the curator's epistemic position. It is personal, not neutral. This is by design, not a limitation to be engineered away.
- A practitioner who has not questioned the dominant paradigm of their field cannot construct a valid seed for this pipeline. They can construct a seed that scales the dominant paradigm. That is a different tool.

---

## Variant B — Founding-Claim-First (Non-Expert Path)

### What a Core Belief Actually Is

A core belief is not wrong from the start. It is **load-bearing** — it sustains your entire mental model, your tooling choices, your professional practice. It works. It is what you build on. The word "limiting" is only visible in retrospect, after the crisis.

The belief that "execution timing is undeclared" sustained decades of OS design, compiler development, and concurrency research. It was not a mistake — it was the correct founding assumption for the hardware and problems of its era. It became limiting only when the compensation load it required — scheduler, mutex, barrier, GC, RCU, thread pool, context switch, interrupt handler — grew large enough to be visible as a pattern rather than as isolated engineering decisions.

This is the critical distinction: a core belief sustains you until it doesn't. The transition is not a correction of an error. It is a structural failure under increasing load — the belief can no longer carry what has been built on top of it without requiring more compensation than the original problem justified.

**Implications for the W-register:** the degree classification (scoped / near-miss / misattributed / framing-trap / false) maps to where the belief is in its lifecycle. A scoped belief is still sustaining within its boundary — it has not failed, it has only been bounded. A framing-trap is sustaining while preventing you from seeing the load it is accumulating. A false belief never had a valid sustaining phase. The W-register is not a list of mistakes — it is a record of beliefs at different stages of structural failure.

**Implications for the crisis:** the crisis is not an intellectual event. It is the moment the sustaining function fails. You cannot force it. You can only count the load and wait for the structure to become visible as load rather than as normal engineering.

Variant B is for that case. It does not require an expert seed as input. It uses a **founding question** as the minimal starting condition and treats the seed as an emergent output of the iteration, not a prerequisite to it.

### The Improvement Cycle

Whether expert or non-expert, the cognitive process of improvement follows the same structure:

1. **Identify** — find a belief whose compensation load is ≥ 3
2. **Abandon** — give it up, not just weaken it. Partial abandonment preserves the frame.
3. **Adopt** — derive a new mental model from first principles that requires 0 compensations for the same problem
4. **Iterate** — repeat on the next belief
5. **Force iteration until stable** — stop condition: `len(limiting_beliefs_with_count ≥ 3) == 0` within scope

Step 2 is the hard one. A belief that has been load-bearing for years feels like knowledge, not a belief. Weakening it ("maybe GC isn't always necessary") preserves the frame. Abandoning it ("execution timing can be declared; GC compensates for not declaring it") exits the frame. The difference is whether the new position requires the old compensation mechanisms or not. If you weaken a belief and still need GC, you have not abandoned the belief — you have qualified it.

### You Always Skim

Every document encounter begins with a skim. This is not a shortcut — it is the primary cognitive operation. What changes between novice and expert is not whether they skim, but **what the skim is guided by**.

| Stage | Skim is guided by | What gets flagged |
|---|---|---|
| Novice, no prior | Nothing — everything looks equally important | Random; high noise |
| Variant B — compensation counting | Compensation load signal | "Does this add or reduce compensation on a belief I hold?" |
| Variant A — seed centroid | Pattern match against pre-loaded prior | "Does this look like my seed?" |
| Expert + fine-tuned model | Centroid + reasoning depth simultaneously | "Domain match AND derives from premises?" |

The two-axis gate in this pipeline is the expert skim made explicit and automated. Domain relevance = centroid match = first-pass pattern recognition. Reasoning depth = structural derivation present = second-pass confirmation. The gate encodes what an expert does in 30 seconds of skimming.

For Variant B practitioners, the skim during naive exposure is guided by compensation counting rather than centroid similarity. The question is not "does this look like my seed?" (no seed exists yet) but "does this document add new compensation mechanisms to a belief I currently hold, or does it show the same problem handled with fewer?" That question is answerable from inside the frame, before the crisis, without a pre-existing prior.

The skim is also the mechanism by which the filter spots what is missing. A document that neither adds compensations nor reduces them on any current belief is outside the current scope. A document that reveals a compensation the curator had not counted is a gap discovery — it expands the W-register. A document that shows the same problem with 0 compensations is the anomaly that triggers the crisis.

Learning does not begin with a seed. It begins with naive exposure — encountering domain material without a coherent prior, accumulating beliefs incrementally within the available frame. Beliefs accumulate until a specific failure mode appears: a belief begins to require multiple compensation mechanisms to defend. At that point — and not before — the belief becomes visible as limiting. The frame shatters. A new one is built from the rubble. This is a Kuhnian paradigm shift at the individual level: normal science (accumulation within frame) → anomaly accumulation (compensation load increases) → crisis (belief becomes indefensible) → new frame.

The seed, in this model, is not the starting point. It is what you have after the first shattering. It is the output of the process.

### The Compensation Load Signal

The key insight is that **compensation load is measurable before the shattering occurs**. You do not need to have already escaped the frame to detect that a belief is limiting. You only need to count:

> How many independent mechanisms exist whose sole purpose is to compensate for this belief being treated as true?

- "Dynamic allocation is necessary" → GC, object pools, arena allocators, slab allocators, bump pointer, finaliser chain, write barriers, card tables → 8+ compensation mechanisms → limiting belief
- "Execution timing is undeclared" → scheduler, mutex, atomic, memory barrier, RCU, thread pool, interrupt handler, context switch → 8+ compensation mechanisms → limiting belief
- "Static allocation is sufficient" → 0 compensation mechanisms → non-limiting

A practitioner who cannot yet identify what is wrong with a belief can still count its compensation mechanisms. The count is observable from inside the frame. The wrongness is not.

This is the accessible entry point: **you do not need to know the right answer. You only need to count the cost of the current answer.**

### Variant B Process

**Step 0 — Choose a founding question.** Not a claim — a question. A claim assumes an answer; a question does not. The founding question should be the most basic thing you are uncertain about in your domain.

Examples:
- "What is the minimum that must be true for deterministic execution to be possible?"
- "What would memory management look like if allocation bounds were always known?"
- "What would a compiler know if it knew when every instruction would execute?"

The founding question does not need to be answerable yet. It needs to be genuine — something you actually want to know, not something you already know the answer to.

**Step 1 — Naive exposure with compensation counting.** Read broadly in the domain. For each significant claim you encounter, count its compensation mechanisms. Do not evaluate correctness — only count compensations. Record:

```
claim: "X is necessary"
compensations: [list of mechanisms that exist because X is treated as true]
count: N
```

Claims with count ≥ 3 are limiting belief candidates. Do not yet abandon them — accumulate them.

**Step 2 — Wait for the crisis.** A limiting belief candidate becomes a crisis when:
- Its compensation count keeps growing as you read more (new compensations keep appearing)
- The compensations have their own compensations (second-order compensation)
- You encounter material that handles the same problem with 0 or 1 compensations (anomaly)

The anomaly is the trigger. It does not need to be from a paper or an authority. It can be a single sentence in a blog post, a comment in source code, or a design decision in a codebase that handles the same problem differently. When you see it, you will recognise it: "why don't they need the thing everyone else needs?"

**Step 3 — Shatter and rebuild.** When the crisis is clear:
1. State the limiting belief explicitly
2. State what you are abandoning (the belief, not the domain)
3. State the new founding claim that makes the compensations unnecessary
4. Derive the first consequences of the new claim

The derivation in Step 4 is the first seed document. It is yours — it comes from your own reasoning, not from a paper. It will be short, rough, and probably incomplete. That is correct. It is the founding document.

**Step 4 — Iterate.** Now the founding-claim-first path merges with Variant A. You have a founding claim and one seed document. Apply Variant A Steps 2–6: select additional documents against the four criteria, audit for framing traps, compute the centroid, name the boundary, lock the seed.

The difference: in Variant A, the seed is expert-constructed before iteration. In Variant B, one seed document exists after the first shattering, and the remainder of the seed is built by applying Variant A criteria from that new position.

**Stop condition:** `len(limiting_beliefs_with_count ≥ 3) == 0` within your current domain scope. You are not looking for global completeness — only stability within the scope you have defined. The scope will expand as the coordinator agent develops.

### What Changes in the Pipeline

Nothing structural changes. The seed produced by Variant B feeds into the same pipeline as Variant A — embed, centroid, two-axis gate, reflection window, training. The difference is entirely in how the seed is constructed.

The W-register entries from Variant B are the limiting beliefs identified in Step 1. They are already in the right format: claim, compensation count, degree (the degree is determinable after the shattering — before it, you only have the count, not the classification).

### The Accessibility Gain

Variant A requires escaping the frame before starting. Variant B requires only the ability to count compensations — a skill that can be taught and practiced without prior domain expertise. The compensation count is observable from inside the frame; the limiting belief is not.

This is the key difference: Variant A is for practitioners who have already questioned the dominant paradigm. Variant B is for practitioners who are willing to count and wait for the crisis. The pipeline is the same. The entry requirement is different.

The honest caveat: Variant B takes longer. The founding question to first shattering may take weeks or months of reading. The process cannot be rushed — the crisis must be genuine, not performed. A performed shattering (abandoning a belief you have not actually tested) produces a false new frame that will also require compensations. Count those too.
