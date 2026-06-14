# ADR-0014: Corpus Reproducibility

**Date:** 2026-06-15  
**Status:** Accepted

---

## Context

The corpus is the foundation of the fine-tuned model. If the corpus cannot be reproduced, the model cannot be reproduced, and the pipeline's claims cannot be independently verified. Reproducibility requires that every acceptance decision is recorded with enough information to replay it: which document, which thresholds were active at the time, what the centroid was, and what the human review concluded.

Without this, the corpus is an opaque artifact — useful locally but not auditable, not transferable, and not improvable by others.

---

## Decision

Every document processed by the pipeline — accepted or rejected — produces a **document record** stored in `corpus/records/`. Records are append-only (never modified after creation) and are version-controlled.

### Document Record Schema

```json
{
  "record_version": "1.0",
  "id": "arxiv:2401.12345",
  "title": "Exokernel: An Operating System Architecture for Application-Level Resource Management",
  "authors": ["Engler, D.R.", "Kaashoek, M.F.", "O'Toole Jr., J."],
  "url": "https://arxiv.org/abs/cs/9412223",
  "fetch_timestamp": "2026-06-15T14:23:11Z",
  "source_layer": 1,
  "source_context": "academic-peer-reviewed",
  "source_venue": "SOSP 1995",
  "corpus_tier": "primary",
  "abstract_relevance_score": 0.81,
  "domain_relevance_score": 0.87,
  "reasoning_depth_scores": {
    "premise_declaration": 0.5,
    "derivation_chain": 1.0,
    "frame_exposure": 0.5,
    "assumption_challenge": 1.0,
    "conclusion_specificity": 1.0,
    "frame_trap_absence": 0.5,
    "weighted_total": 0.75
  },
  "contradiction_flags": ["W-08"],
  "contradiction_degrees": ["near-miss"],
  "decision": "accepted-with-annotation",
  "centroid_at_acceptance": "corpus/centroids/cycle_002.npy",
  "thresholds_at_acceptance": {
    "domain_relevance": 0.85,
    "reasoning_depth": 0.80
  },
  "cycle": 2,
  "human_review_notes": "Right diagnosis (OS abstraction overhead), stops at relocation not elimination. Body contains precise latency measurements useful as empirical evidence. W-08 near-miss annotation added.",
  "bridge_annotation": null,
  "text_hash": "sha256:a3f2c1...",
  "text_path": "corpus/texts/arxiv_cs_9412223.txt",
  "nearest_seed_sections": [
    "docs/papers/03-os-and-runtime/02-the-os.md#kernel-circuit-updates",
    "docs/papers/03-os-and-runtime/01-starting-point.md#runtime-is-bitstream-loader"
  ]
}
```

### Centroid Snapshots

At the end of each reflection window cycle, the current embedding centroid is saved as a numpy array:

```
corpus/centroids/cycle_000.npy   ← initial (seed corpus only)
corpus/centroids/cycle_001.npy   ← after cycle 1
corpus/centroids/cycle_002.npy   ← after cycle 2
...
```

Each document record references the centroid active at the time of its acceptance. This allows replay: given the centroid snapshot and the thresholds, the domain relevance score can be recomputed from the stored text and verified.

### Cycle Summary Log

```
corpus/cycles/cycle_001.json
corpus/cycles/cycle_002.json
...
```

Each cycle summary (ADR-0007 format) is stored alongside the records.

### Text Storage

Accepted document texts stored at `corpus/texts/{id_normalised}.txt`. Rejected document texts not stored (ADR-0004). Document record stored regardless of decision (rejected records have `text_path: null`).

### Reproducibility Guarantee

Given the `epistemic-filter` repository at a specific git commit, the following can be reproduced by any third party:

1. The seed corpus (git submodule pointer to `clock-aware-programming` at a specific commit)
2. The embedding model (`nomic-embed-text` version pinned in `config/models.json`)
3. The thresholds active at each cycle (stored in each document record)
4. The centroid at each cycle (stored as numpy arrays, committed to git or stored in LFS)
5. The reasoning depth feature scores for each document (stored in document record)
6. The human review notes for each manually reviewed document (stored in document record)

Items 1–5 are fully automated reproductions. Item 6 (human review notes) documents the human judgment — it cannot be automated but it is recorded, so a third party can read the notes and evaluate whether they agree with the decision.

### Verification Script

A `verify_corpus.py` script (to be implemented) accepts a document record and:
1. Re-fetches the document from its URL
2. Re-embeds it with the pinned embedding model
3. Re-computes domain relevance against the centroid snapshot referenced in the record
4. Re-computes reasoning depth feature scores using the rubric (ADR-0011)
5. Checks that the recomputed scores match the stored scores within tolerance (±0.02)
6. Reports pass/fail

This script is the reproducibility proof.

---

## Rationale

**Why store records for rejected documents?**

Rejected documents are the calibration data. If the thresholds are recalibrated (ADR-0006), rejected documents near the old threshold may be reconsidered. Without stored records, recalibration requires re-fetching and re-scoring all previously rejected documents. With stored records, recalibration is a filter over existing metadata.

**Why reference the centroid by file path rather than embedding it in the record?**

The centroid vector is 768 floats (3 KB at float32). Embedding it in every document record that shares that centroid would be redundant. The centroid file is shared by all documents accepted in the same cycle. Referencing it by path is both more compact and more auditable — the centroid file itself is version-controlled.

**Why store the text hash?**

To detect if the source document was modified after acceptance (e.g., ArXiv paper updated with a new version). If the hash of the re-fetched text differs from the stored hash, the document should be re-scored against the new version.

**Why are document records append-only?**

To preserve the audit trail. If a document is re-scored (due to threshold recalibration or W-register update), a new record is created with a new timestamp referencing the original record's ID. The original record is never modified. This makes the full decision history visible in the record sequence.

---

## Consequences

- The `corpus/` directory structure must be initialised before the first document is processed
- Centroid numpy arrays may be large enough to warrant git-lfs for the repository — evaluate after cycle 3 when size is known
- The `verify_corpus.py` script is a prerequisite for claiming reproducibility publicly — must be implemented before the repository is open-sourced
- Human review notes are free-form text — they are not machine-parseable but they are the only record of the human judgment that cannot be automated
