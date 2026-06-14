# ADR-0009: Source Context Classification

**Date:** 2026-06-15  
**Status:** Accepted

---

## Context

Every document is produced within a context that shapes its claims, its hedging, and its relationship to the existing consensus. A PhD thesis, a conference paper, an industry engineering blog post, a hardware datasheet, and a personal technical essay are not equivalent sources — not because of quality differences, but because their **production incentives** differ systematically. Those incentive differences predict which kinds of claims will be present, which will be absent, and which will be systematically biased.

Ignoring source context means treating a committee-reviewed PhD thesis the same as an independent first-principles derivation. They are not the same. The PhD thesis is optimised to satisfy reviewers who are themselves embedded in the consensus. A claim that challenges a foundational assumption will be softened, scoped, or removed before publication — not because the author is wrong, but because the production context rewards consensus alignment and penalises consensus challenge.

A fine-tuned model trained without source context awareness will inherit these biases. It will weight consensus-aligned claims more heavily (they appear in more documents) and first-principles challenges more lightly (they appear in fewer, smaller-circulation sources). This is the opposite of the desired prior.

---

## Decision

Every accepted document is tagged with a **source context** from the following classification:

| Context | Description | Incentive Structure | Claim Bias |
|---|---|---|---|
| `academic-thesis` | PhD or Master's thesis | Satisfy committee, demonstrate literature mastery | Conservative; consensus-aligned; hedged challenges |
| `academic-peer-reviewed` | Conference or journal paper | Pass peer review; incremental contribution | Incremental; scoped; avoids paradigm-level claims |
| `academic-workshop` | Workshop or position paper | Speculative; less review pressure | More willing to challenge; less rigorous |
| `industry-engineering` | Engineering blog, design doc, postmortem | Solve a real problem; ship it | Pragmatic; often contains undeclared timing insights without naming them |
| `standards-body` | RFC, IEEE standard, ISO spec | Consensus by committee | Conservative by construction; captures what is, not what should be |
| `hardware-documentation` | Datasheet, architecture manual, errata | Describe what the hardware does | Highly precise; no incentive to challenge the programming model |
| `independent` | Personal technical essay, independent research, preprint without institutional affiliation | No committee, no peer review | Most likely to contain first-principles challenges; least likely to be polished |
| `seed` | Documents in the seed corpus | Authored from consistent first principles | Foundational; treated as ground truth |

---

## How Source Context Affects Scoring

Source context does **not** change the quality gate thresholds (ADR-0001). A document either passes domain relevance and reasoning depth or it does not, regardless of where it came from.

Source context **does** affect interpretation during manual review and contrastive training:

**For `academic-thesis` and `academic-peer-reviewed`:**
- Hedged or scoped claims that would otherwise trigger a known-wrong flag (ADR-0008) are more likely to be `scoped` degree, not `false`. The author may know the claim is incomplete but cannot say so explicitly without failing review.
- A PhD thesis that gets 80% of the way to a first-principles conclusion and stops is a `near-miss` candidate. The committee stopped it, not the author's reasoning.
- These documents are valuable for what they contain *between* the consensus-aligned claims: the data, the measurements, the derivations in the body, even when the abstract and conclusion are forced to align with the consensus.

**For `industry-engineering`:**
- Often contains practical timing insights described in operational terms ("we had to pin this thread to avoid jitter") without recognising them as evidence for a first-principles claim. These are `misattributed` in the W-register sense: correct observation, undeclared explanation.
- High value as empirical evidence that the model's claims hold in production, even when the author does not have the vocabulary to state them as such.

**For `independent`:**
- Highest prior for first-principles challenges. Lowest prior for rigour and precision.
- Read the derivation chain carefully. If it holds, the source context should not discount it.
- The seed corpus itself (`clock-aware-programming`) is `independent`. This is not a coincidence.

**For `hardware-documentation`:**
- Highest factual precision. Zero incentive to challenge the programming model.
- Treat as ground truth for hardware behaviour claims. Do not expect first-principles insight into software model implications.
- The Cortex-A53 Software Optimization Guide is `hardware-documentation`. It tells you exact instruction latencies. It does not tell you that those latencies make a compiler-derived `budget_ticks` possible.

**For `standards-body`:**
- Consensus by construction. Every claim survived committee review, which means every challenging claim was removed.
- Valuable for understanding the current consensus precisely. Treat as a description of the existing model, not as evidence for or against the new one.

---

## Source Context in the Metadata Record

The metadata record (ADR-0006) is extended with a `source_context` field:

```json
{
  "id": "arxiv:2401.12345",
  "title": "...",
  "source_context": "academic-peer-reviewed",
  "source_venue": "OSDI 2024",
  "source_layer": 2,
  "domain_relevance_score": 0.88,
  "reasoning_depth_score": 0.82,
  "contradiction_flags": ["W-03"],
  "contradiction_degrees": ["scoped"],
  "decision": "accepted-with-annotation",
  "notes": "Scheduler necessity claim is scoped to POSIX model. Body contains precise dispatch latency measurements consistent with budget_ticks derivation.",
  "timestamp": "2026-06-15T..."
}
```

---

## Rationale

**Why not discount `academic-thesis` documents by default?**

The committee-alignment bias affects the abstract, introduction, and conclusion — the framing. The body — the measurements, the derivations, the implementation details — is often far less biased. A thesis that concludes "our scheduler reduces jitter by 40%" may contain the precise cycle-level data that proves cache miss costs are undeclared timing compensation. The conclusion is biased. The data is not. Discounting the whole document loses the data.

**Why is `independent` the highest prior for first-principles challenges?**

Because removing the committee removes the consensus filter. The author of an independent technical essay answers only to the logic. If the derivation is wrong, it is wrong on its own terms, not suppressed by review. The seed corpus is `independent` for exactly this reason. The absence of institutional validation is not a weakness — it is the condition under which paradigm-level claims can be made without being softened into incrementalism.

**Why record the source venue?**

OSDI, SOSP, and USENIX ATC have different acceptance cultures. OSDI tends toward systems with strong performance claims. SOSP tends toward foundational systems work. ArXiv preprints have no review at all. The venue is a second-order signal that refines the source context classification.

---

## Alternatives Rejected

### Treat all peer-reviewed sources as higher quality than non-peer-reviewed

**Rejected.** Peer review filters for consensus alignment, not for first-principles correctness. The most important claims in the seed corpus would not survive peer review as written — they challenge foundational assumptions that reviewers would require to be hedged or removed. Peer review is a quality signal within a paradigm. It is not a quality signal for paradigm-level claims.

### Weight source context in the quality score

**Rejected.** Source context affects interpretation, not the binary pass/fail decision. A document from an `independent` source that fails reasoning depth is still rejected. A document from a `academic-thesis` source that passes both axes is still accepted. The weight belongs in the contrastive training strategy, not the gate.

---

## Consequences

- Every accepted document carries a source context tag. The tag is assigned during the fetch step using heuristics (ArXiv affiliation field, venue name, URL pattern) and confirmed during manual review.
- The contrastive training pipeline must handle source context — a `scoped` claim from an `academic-thesis` is treated differently from the same claim in an `independent` document.
- The reflection window (ADR-0007) includes a source context distribution check: if > 80% of accepted documents are `academic-peer-reviewed`, the corpus may be systematically underweighting first-principles challenges. Add more `independent` and `industry-engineering` sources.
