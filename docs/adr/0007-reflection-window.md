# ADR-0007: Mandatory Reflection Window

**Date:** 2026-06-15  
**Status:** Accepted

---

## Context

A continuous pipeline that fetches, scores, and accepts documents without pause will drift. The first 20 accepted documents shape the embedding centroid more than documents 200–220 do. Early miscalibration compounds silently — the corpus drifts in a direction the acceptance rate metric cannot detect, because the metric measures throughput, not coherence. By the time the fine-tuned model underperforms, the root cause is buried in early decisions that were never reviewed.

Additionally, the human operator's understanding of what constitutes quality evolves as the corpus grows. A document that seemed borderline at acceptance time may be clearly wrong in retrospect — or clearly right. That reassessment is only possible with a pause.

---

## Decision

The pipeline runs in **cycles of 50 documents scored**. At the end of each cycle, the pipeline stops and a reflection window opens before the next cycle begins.

The reflection window has four mandatory steps:

**Step 1 — Corpus coherence review**
Re-embed the full accepted corpus and recompute the centroid. Compare the new centroid to the previous cycle's centroid (cosine similarity between centroids). If the centroid has moved more than 0.05 from the previous cycle: the corpus is drifting. Review the documents accepted in this cycle — one of them is an outlier pulling the centroid. Identify and consider removing it.

**Step 2 — Worst accepted document**
Rank accepted documents by their combined score (domain relevance × reasoning depth). Read the bottom 3. Ask: would you accept these today, knowing what you know now? If no: remove them from the corpus and add them to the negative training set for the reasoning depth classifier. If yes: the thresholds are well-calibrated.

**Step 3 — Best rejected document**
From the rejection metadata log, identify the 3 highest-scoring rejected documents (the ones closest to the threshold). Read them. Ask: was the rejection correct? If no: lower the relevant axis threshold by 0.02 and re-score the rejected batch. If yes: the thresholds are correctly strict.

**Step 4 — Source yield review**
Compute acceptance rate per discovery source (Layer 1 citation graph vs Layer 2 ArXiv category vs Layer 3 recursive expansion). If any source has < 3% acceptance rate over the last 50 documents: deprioritise it for the next cycle. If Layer 1 (citation graph) is exhausted: move to Layer 2 as primary.

After all four steps are complete, record a cycle summary and resume.

---

## Rationale

**Why 50 documents per cycle?**

50 is enough to compute a stable acceptance rate (ADR-0006 recalibration protocol) and enough to make centroid drift visible. It is small enough that a full reflection window review (reading 6 documents, computing metrics) takes under an hour. Longer cycles mean drift goes undetected longer. Shorter cycles make the reflection overhead dominate the pipeline time.

**Why recompute the centroid every cycle?**

The centroid is the definition of domain relevance. If it drifts, the definition drifts. Catching drift at cycle boundaries means at most 50 documents of contamination before correction. Catching it only at fine-tuning time means the entire corpus is potentially contaminated.

**Why read the worst accepted and best rejected documents manually?**

Metrics cannot catch all failure modes. A document that scores 0.86 domain relevance and 0.81 reasoning depth passes both thresholds — but if a human reads it and finds it asserts conclusions in domain vocabulary without derivation, the classifier has a systematic blind spot. That blind spot is only visible through human inspection of near-threshold cases. The reflection window is the scheduled opportunity for that inspection.

**Why review source yield per layer?**

Discovery sources degrade over time. The seed citation graph (Layer 1) is finite — it will be exhausted after the first few cycles. ArXiv category search (Layer 2) has variable yield depending on how targeted the categories are. Recursive expansion (Layer 3) can produce diminishing returns if the accepted corpus converges on a narrow citation cluster. Tracking yield per source makes the degradation visible and actionable before it affects the pipeline throughput.

**Why is the reflection window mandatory, not optional?**

Because the temptation when the pipeline is running well is to skip it. The reflection window catches problems that only appear in retrospect. Making it mandatory means the corpus quality is reviewed even when everything seems fine — which is exactly when silent drift is most likely to be occurring.

---

## Alternatives Rejected

### Continuous pipeline with no pause

**Rejected.** Silent drift is undetectable until fine-tuning underperforms. By then the corpus may need to be rebuilt from scratch.

### Reflection triggered by metric threshold (e.g., acceptance rate drops below 5%)

**Rejected.** Metric-triggered reflection only catches detectable failure modes. The failure modes that matter most — centroid drift, classifier blind spots, source yield degradation — are not reliably detected by the acceptance rate metric alone. A scheduled reflection catches what metrics miss.

### Human review of every accepted document

**Rejected.** Defeats the purpose of automation. The reflection window reviews only the boundary cases (worst accepted, best rejected) — the documents where the classifier's judgment is most likely to be wrong. Documents far from the threshold are trusted to the classifier.

---

## Cycle Summary Format

At the end of each reflection window, record:

```json
{
  "cycle": 3,
  "documents_scored": 50,
  "documents_accepted": 8,
  "acceptance_rate": 0.16,
  "centroid_drift": 0.021,
  "threshold_changes": [],
  "documents_removed": [],
  "documents_reconsidered": [],
  "source_yield": {
    "layer_1_citation": 0.31,
    "layer_2_arxiv": 0.12,
    "layer_3_recursive": 0.07
  },
  "notes": "Layer 1 citation graph nearly exhausted. Transition to Layer 2 primary next cycle."
}
```

The cycle log is the audit trail for the corpus. It records every human judgment made during the reflection window and why.

---

## Consequences

- The pipeline is not continuous. It pauses every 50 documents for human review.
- The reflection window adds time overhead — approximately 1–2 hours per cycle for the manual reading steps.
- The cycle summary log is a permanent record of corpus curation decisions. It is version-controlled alongside the corpus.
- Centroid drift detection requires storing the centroid vector from each previous cycle. Storage cost is negligible (768-dimensional float32 vector = ~3 KB per cycle).
