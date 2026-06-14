# ADR-0006: Candidate Discovery and Relevance Feedback

**Date:** 2026-06-15  
**Status:** Accepted

---

## Context

The pipeline needs a supply of candidate documents to score. Fetching randomly from a large academic database produces a high rejection rate and wastes the fetch budget. Fetching too narrowly risks missing genuinely relevant documents that use different vocabulary. Additionally, every rejection carries information: a document that was fetched but failed one or both axes tells us something about either the source selection or the threshold calibration. That information must be captured and acted on.

This ADR defines: (1) how candidates are discovered, (2) the fetch priority ordering, and (3) how rejections feed back into the system.

---

## Decision

### Part 1 — Discovery Strategy (layered, priority-ordered)

Candidates are discovered in three layers, attempted in priority order:

**Layer 1 — Seed citation graph (highest precision)**
Extract references from every seed corpus document. Each cited paper is a candidate. Papers cited by seed documents are likely to be high-quality signal — they are the sources the seed author found worth citing, which is a strong prior for domain relevance and reasoning depth. Fetch and score these first.

**Layer 2 — ArXiv category search (medium precision)**
Query the ArXiv API for papers in targeted categories: `cs.OS`, `cs.AR`, `cs.PL`, `cs.DC`, `cs.ET`. Filter by date (last 5 years default, configurable). Sort by citation count descending — highly-cited papers in the target categories have been vetted by the domain community. Embed the abstract first; if the abstract cosine similarity is below 0.70, skip the full fetch. The abstract pre-filter eliminates the bulk of irrelevant papers before a full fetch is attempted.

**Layer 3 — Recursive expansion (lowest precision, used sparingly)**
For every accepted document, extract its references as new candidates (same as Layer 1 applied to the growing corpus). This expands the corpus along the citation graph of accepted documents. Rate-limited to avoid runaway expansion: at most 5 new candidates per accepted document.

### Part 2 — Relevance Feedback on Rejection

Every rejected document generates a metadata record:

```json
{
  "id": "arxiv:2401.12345",
  "title": "...",
  "source_layer": 1,
  "domain_relevance_score": 0.72,
  "reasoning_depth_score": 0.91,
  "decision": "rejected",
  "failed_axis": "domain_relevance",
  "nearest_seed_sections": ["paper-02-language.md#channel-definition", "..."],
  "timestamp": "2026-06-15T..."
}
```

Rejections are analysed in batches of 20. The analysis asks three questions:

1. **Did it fail domain relevance?** Inspect the nearest seed sections it landed near. If the seed sections are genuinely adjacent in topic (the document uses different vocabulary for the same concepts), lower the domain relevance threshold by 0.02 and re-score. If the seed sections are genuinely different in topic, the rejection was correct — the source (Layer 2 category) may be too broad.

2. **Did it fail reasoning depth?** Read the document. If it contains genuine derivation chains that the classifier missed, the classifier has a false negative — add the document to the negative class training set for the *opposite* failure pattern (documents that look shallow to the classifier but are not). Retrain the classifier.

3. **Did it fail both?** The source is too noisy. If multiple consecutive rejections come from the same ArXiv category or citation cluster, flag that source as low-yield and deprioritise it in future fetches.

### Part 3 — Threshold Recalibration Protocol

After every 50 documents scored (accepted or rejected), run the recalibration check:

- If acceptance rate > 40%: thresholds may be too loose. Spot-check 5 accepted documents manually. If any are questionable, raise the lower-scoring axis threshold by 0.02.
- If acceptance rate < 5%: thresholds may be too tight or sources are too broad. Inspect the 5 highest-scoring rejected documents. If any are clearly high quality, lower the failing axis threshold by 0.02 and re-score the full rejected batch.
- If acceptance rate is 5–40%: no recalibration needed. Continue.

Target acceptance rate: **10–20%**. This reflects the expert's natural rejection rate when skimming a stack of papers in a familiar domain.

---

## Rationale

**Why start with the seed citation graph?**

The seed author already ran a high-precision filter when writing the papers — they cited only what they found worth citing. The citation graph is a curated list of high-prior candidates, available for free with no fetching or scoring needed to identify them. Layer 1 should produce the highest acceptance rate of any discovery source.

**Why use abstract pre-filtering before full fetch?**

Fetching a full PDF costs time and temporary disk space. An abstract is available from the ArXiv API response without a separate fetch. A 0.70 cosine similarity threshold on the abstract is loose enough to avoid false negatives (a paper with a technical abstract that uses different vocabulary than the seed) while eliminating the clear misses. The threshold is intentionally lower than the full-document threshold (0.85) because abstracts are shorter and less representative of the full document's embedding.

**Why record nearest seed sections for every rejection?**

The nearest seed sections tell you *what* the classifier thought the document was about — which section of the seed it most resembled in embedding space. For a false negative (good document wrongly rejected), this is the diagnostic: the document landed near a seed section that is adjacent but not identical in topic. That diagnosis directly guides the fix — either adjust the threshold or add a corrective training example near that seed section's embedding.

**Why target 10–20% acceptance rate?**

Too high (> 40%): the filter is not doing its job. The corpus will contain noise.
Too low (< 5%): either the sources are wrong or the thresholds are miscalibrated. Both are fixable, but a near-zero acceptance rate means no corpus is being built.
10–20% matches the expert's intuitive rejection rate and produces a corpus growth rate that can be sustained without running out of candidate sources.

---

## Alternatives Rejected

### No feedback loop — static thresholds forever

**Rejected.** The first 50 documents are calibration data. Thresholds set before seeing any real candidates are guesses. Without a feedback loop, miscalibration is permanent and undetectable until the fine-tuned model underperforms.

### Fully automatic threshold adjustment (gradient descent on acceptance rate)

**Rejected.** Automatic adjustment without human inspection can drift the thresholds away from their epistemic meaning. A threshold is a quality commitment, not a knob to tune for throughput. Adjustments are allowed but must be validated by manual spot-check.

### Scrape all ArXiv categories and filter post-hoc

**Rejected.** Generates enormous fetch volume before any filtering occurs. The abstract pre-filter (Layer 2) achieves the same result with 10–20× less fetch volume.

---

## Consequences

- Every fetch produces a metadata record, regardless of pass/fail. The metadata log is the audit trail for threshold decisions.
- Recalibration is a manual step triggered by the acceptance rate check, not an automatic process.
- The citation graph expansion (Layer 3) must be rate-limited to prevent the candidate queue from growing faster than the pipeline can score.
- The discovery strategy is biased toward the seed citation graph. If the seed author has a narrow reading history, Layer 1 will have a corresponding blind spot. Layer 2 (category search) compensates for this.
