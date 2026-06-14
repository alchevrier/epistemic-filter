# ADR-0017: Benchmark Construction Methodology

**Date:** 2026-06-15  
**Status:** Accepted

---

## Context

The benchmark is the only falsifiable quality claim the pipeline makes. Without it, "the model is better" is an opinion. With it, improvement is a measurement. But the benchmark questions must be constructed by a domain expert from their own knowledge — they cannot be generated automatically or crowdsourced from people who have not questioned the domain's framing.

The current benchmark (`benchmark/questions.json`) contains 51 questions specific to the clock-aware-programming domain. For the pipeline to be reproducible in other domains, the methodology for constructing a benchmark must be transferable — a practitioner in another field should be able to follow these steps and produce an equivalent benchmark for their domain.

This ADR defines that methodology.

---

## Decision

The benchmark has three components, each testing a distinct capability. The construction methodology for each is different because each component requires accessing different parts of the curator's knowledge.

**The benchmark must be written before the first training run and never modified afterwards.** This is not a procedural nicety — it is the falsifiability condition. A benchmark written after training, or modified to match what the model does well, is not a benchmark. It is a description of the model's behaviour.

---

### Component 1 — Frame Identification Questions (target: ~25)

**What it tests:** Can the model identify the limiting assumption of a domain claim and derive what changes when the assumption is removed?

**How to construct them:**

**Step 1 — Collect standard field claims.** Go through your domain's canonical textbooks, introductory papers, and conference tutorial slides. Collect 30–40 claims that practitioners in your field would consider obviously correct — not controversial, not advanced, but foundational. These are the claims that appear in textbook introductions and are never questioned in practice.

Examples of the form to look for:
- "X is necessary because Y"
- "Without X, you cannot achieve Y"
- "X is the correct approach to Y"
- "X is unavoidable in any system that does Z"

**Step 2 — Identify the assumption.** For each claim, ask: what must be true about the world for this claim to hold? The assumption is usually implicit — that is what makes it a frame. It is stated as background, not as a premise. Write it out explicitly.

**Step 3 — Derive the removal.** Ask: what changes if the assumption is removed? Two outcomes are possible:
- The claim becomes false (the mechanism it describes is redundant)
- The claim becomes a special case (true under the assumption, not universally)

If you cannot derive what changes, the assumption you identified is not the right one. Dig further.

**Step 4 — Write the question.** Present the claim verbatim or in close paraphrase. Ask: "What assumption does this claim depend on, and what changes when that assumption is removed?"

**Step 5 — Write the expected answer.** The expected answer must:
1. Name the assumption precisely (not the domain, not the technique — the specific hidden premise)
2. Derive the consequence of removing it (what mechanism becomes redundant or what conclusion changes)
3. Name the mechanism that becomes redundant — the specific tool, protocol, or pattern that exists only to compensate for the assumption

**Step 6 — Write the discriminator.** Define what separates score 0 from score 1, and score 1 from score 2. The discriminator is what makes scoring reproducible. Without it, two scorers will disagree.

**Quality check:** if a well-trained practitioner in your field, reading the question cold, would say "this seems like a trick question — the claim is obviously correct", you have a good C1 question. The assumption is genuinely invisible from inside the frame. If they immediately say "well of course it depends on X", the assumption is already visible and the question is too easy.

---

### Component 2 — Wrong-Claim Classification Questions (one per W-register entry)

**What it tests:** Can the model classify the degree of wrongness of a known-problematic claim and produce the correct refutation at that degree?

**How to construct them:**

**Step 1 — Build the W-register first.** C2 questions are derived from W-register entries. You cannot write C2 questions before you have a W-register. The W-register comes from the seed audit (ADR-0016 Step 3).

**Step 2 — For each W-register entry, find the most convincing formulation of the claim.** Do not use a strawman. Find the version of the claim that a competent, thoughtful practitioner in your field would actually make — the version that sounds most correct, that has the most supporting evidence, that is hardest to dismiss. This is the question.

Why the most convincing formulation? Because the model will encounter this claim in its most persuasive form in the real world. Training it to recognise a weakened version produces a model that fails on the real thing.

**Step 3 — Present the claim without identification.** Do not say "this is a framing trap" or "this claim is wrong". Present it as a sincere assertion. Ask: "What degree of wrongness is this claim, and what is the correct response?"

**Step 4 — Write the expected answer.** The expected answer must:
1. Name the degree precisely (scoped / near-miss / misattributed / framing-trap / false)
2. State the boundary condition: where the claim is true, where it fails, what changes the outcome
3. Name the refutation mechanism: the specific reason the claim fails at that degree, not just the correct answer

**Degree definitions to apply consistently:**
- **scoped**: locally correct within a stated assumption; wrong when presented as universal
- **near-miss**: correct diagnosis, wrong remedy — relocates rather than eliminates the problem
- **misattributed**: correct observation, wrong causal explanation
- **framing-trap**: locally correct, presents compensation as solution, trains away from questioning the assumption
- **false**: wrong on its own stated terms — not merely scoped, not merely misattributed

**Step 5 — Write the discriminator.** Define what separates score 0 from score 1 specifically. For C2 questions, the most common failure is: model names the wrong degree. The discriminator should specify which alternative degree is the most tempting wrong answer and why it is wrong.

**Quality check:** if you initially classified a W-register entry as one degree and then changed it — that is a good question. The degree boundary is where the question's discriminative power lives.

---

### Component 3 — Cross-Domain Bridge Questions (one per cross-domain mapping)

**What it tests:** Can the model identify the structural isomorphism between a cross-domain passage and the primary domain mechanism it reinforces?

**How to construct them:**

**Step 1 — Build the cross-domain map first** (ADR-0010). C3 questions are one per mapping. You cannot write C3 questions before you have identified the cross-domain mappings.

**Step 2 — Find a real passage from the cross-domain field.** Do not fabricate the passage. Find an actual text — paper, textbook, blog post — from the cross-domain field that describes the mechanism. Quote it or closely paraphrase it, preserving the domain vocabulary. The passage should be self-contained: a reader unfamiliar with your primary domain should understand what the passage is saying about its own field.

Why a real passage? Because the model will encounter real passages. A constructed passage may inadvertently use primary domain vocabulary as a hint. Real passages use the cross-domain vocabulary without hints.

**Step 3 — Write the question.** Present the passage. Ask: "What primary domain mechanism is this structurally identical to, and why?"

**Step 4 — Write the expected answer.** The expected answer must:
1. Name the structural pattern explicitly (not "this is similar to X" — name the pattern: "declare arrival windows to eliminate compensation for unknown timing")
2. Name the primary domain equivalent mechanism specifically (not "the language runtime" — the specific mechanism: "lock-free channel declarations", "budget_ticks derivation", "admission test")
3. Derive the bridge: show why both are structurally identical by tracing the derivation in both domains with parallel steps

**The bridge is the highest-value element.** A model that says "this is like the scheduler" has pattern-matched on surface features. A model that shows the parallel derivation in both domains has understood the structural isomorphism.

**Step 5 — Write the discriminator.** Define what separates score 1 from score 2. For C3 questions, the most common failure is: model identifies a plausible connection but does not derive it — asserts the bridge instead of showing it.

**Quality check:** if you can write the bridge annotation for ADR-0010 and the C3 question's expected answer at the same time, without effort, the cross-domain mapping is real. If you struggle to write the expected answer, the mapping may be surface-level rather than structural — reconsider whether it belongs in ADR-0010.

---

### Scoring Calibration

Before fixing the question set, run a calibration pass:

1. Answer each question yourself as if you were a well-trained domain expert
2. Score your own answer against the expected answer using the discriminator
3. If you consistently score yourself 1.5–2.0, the discriminators are too lenient — tighten them
4. If you consistently score yourself 0.5–1.0, the expected answers are too demanding — the graduation threshold is the issue, not the questions

The benchmark should produce:
- Base model (untrained): 0.3–0.8 average across all components
- Expert human: 1.7–2.0 average across all components
- Target fine-tuned model: > 1.6 for C1 and C2, > 1.4 for C3

If your expected answers are so demanding that a domain expert cannot score 1.8+, the benchmark is testing something other than what the training produces. Adjust the discriminators.

---

### Question Set Size Guidance

| Component | Minimum | Target | Maximum useful |
|---|---|---|---|
| C1 (Frame Identification) | 10 | 25 | 40 |
| C2 (Wrong-Claim Classification) | All W-register entries | All W-register entries | All W-register entries |
| C3 (Cross-Domain Bridge) | All ADR-0010 mappings | All ADR-0010 mappings | All ADR-0010 mappings |

C1 minimum is 10 because below that, the average score is too sensitive to individual question difficulty variance. C1 maximum useful is ~40 because the W-register and cross-domain maps tend to grow faster than C1 questions and the evaluation time grows linearly.

C2 and C3 are bounded by the W-register and cross-domain map sizes respectively — one question per entry is the correct density. Adding more C2 questions per W-entry does not add information; it adds noise from question phrasing variation.

---

### What to Do When the Model Fails a Question

If the fine-tuned model consistently fails a specific question:

1. **Check whether the training corpus covers the assumption.** A C1 question about mechanism X requires training documents that expose X's assumption. If no training document does, the model has nothing to learn from.

2. **Check whether the W-register entry has a contrastive training example.** A C2 question about W-entry N requires a contrastive training pair (ADR-0012 format) that presents the claim, the degree, and the refutation. If the pair is absent or weak, the model has no training signal for that question.

3. **Check whether the cross-domain bridge annotation is complete.** A C3 question requires the bridge annotation from ADR-0010 to appear in training with the structural derivation explicit. If the annotation only asserts the connection without deriving it, the model learns the assertion, not the derivation.

The benchmark reveals corpus gaps. That is its function. A model that fails C1 questions needs more primary domain documents that expose assumptions. A model that fails C2 questions needs better contrastive training pairs. A model that fails C3 questions needs richer bridge annotations.

**Do not modify the questions to match the model's capabilities.** Add training data to match the benchmark. The benchmark is fixed; the corpus is not.

---

## Rationale

**Why must benchmark questions be written before training?**

Post-hoc benchmarks measure what the model does well, not whether the model meets the capability specification. Any benchmark written after observing training outputs is guaranteed to correlate with those outputs — even with good intentions, the question author's knowledge of what the model does well influences question construction. The benchmark written before training is the only honest measurement.

**Why is the most convincing formulation required for C2?**

The framing traps the model will encounter in deployment are convincing. A model trained to recognise strawman versions of wrong claims will fail on the real versions. The conviction of the formulation is a feature of C2 questions, not a flaw.

**Why must the bridge derivation be shown, not asserted, in C3?**

A model that asserts structural connections has pattern-matched on vocabulary — it has learned to say "this is like X" when the passage contains certain keywords. A model that derives the connection has understood the structural invariant. The derivation is the signal; the assertion is the noise. The discriminator between score 1 and score 2 on C3 questions specifically targets this distinction.

**Why is question authorship constrained to the curator?**

Crowdsourced questions reflect the crowd's frame. Questions written by practitioners inside the dominant paradigm will not probe the assumptions of the dominant paradigm — those assumptions are invisible to them. The curator, who has identified the framing traps through the seed audit, is the only person positioned to write questions that expose those specific traps. The benchmark is a product of the curator's epistemic position, not a neutral evaluation instrument.

---

## Consequences

- Benchmark construction requires completing the seed audit (ADR-0016 Step 3) and the cross-domain map (ADR-0010) before it can begin
- Minimum time to construct a valid benchmark: several days, concurrent with W-register and cross-domain map construction
- The benchmark is a commitment: once fixed, it is the graduation criterion. If the benchmark is wrong, the graduation criterion is wrong. Invest in getting it right before locking it
- A practitioner who cannot write the expected answers for their own C1 questions does not yet understand their domain's framing assumptions well enough to run this pipeline
