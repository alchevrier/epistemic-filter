# ADR-0004: Fetch-Extract-Discard Pipeline

**Date:** 2026-06-15  
**Status:** Accepted

---

## Context

The development machine has approximately 70GB of free NVMe storage. Academic papers in PDF format average 1–3 MB each. A bulk download of even a targeted ArXiv subset (cs.OS + cs.AR + cs.PL, last 5 years) would consume tens of gigabytes before any quality filtering. Storing the full PDF corpus is not feasible within the disk budget.

Additionally, the classifier operates on text, not on PDFs. PDF storage is only useful for human inspection of near-threshold cases — a secondary need, not a primary one.

---

## Decision

Documents are processed using a **fetch-extract-discard** pipeline:

1. **Fetch** — download the PDF (or HTML where available) of a candidate document on demand
2. **Extract** — convert to plain text, stripping layout, figures, and references
3. **Score** — run both quality axes against the extracted text
4. **Decision** — if both axes pass: store the extracted text, discard the PDF. If either axis fails: discard both PDF and text.
5. **Archive** — the accepted corpus consists only of extracted plain text files

PDFs are never retained after scoring. The disk footprint of an accepted document is the plain text only: a 20-page paper is approximately 40–80 KB as plain text versus 1–3 MB as PDF — a 20–40× reduction.

---

## Rationale

**Plain text is all the pipeline needs.**

The embedding model (ADR-0005) and the reasoning depth classifier both operate on tokenised text. PDF layout, figures, equations rendered as images, and reference lists add no signal and complicate extraction. Discarding the PDF after text extraction loses nothing the pipeline can use.

**The disk budget is a hard constraint, not a preference.**

70GB free sounds generous but fills quickly if PDFs accumulate. A corpus of 5,000 accepted documents at 2 MB average PDF size is 10 GB — before model checkpoints, embeddings, and tooling. Keeping only plain text keeps the accepted corpus under 500 MB regardless of document count.

**On-demand fetching avoids bulk download problems.**

Bulk downloading large ArXiv subsets violates ArXiv's bulk access policy unless done via their S3 mirror with proper rate limiting. On-demand fetching via the ArXiv API (one paper at a time, with rate limiting) is within policy, produces no upfront disk cost, and naturally integrates with the scoring pipeline — a paper is fetched only when the pipeline is ready to score it.

**Near-threshold cases requiring human inspection are handled separately.**

If a document near the threshold needs human review, it can be re-fetched on demand. The original URL is stored in the document metadata regardless of the pass/fail decision. Re-fetching a 2 MB PDF takes seconds on a broadband connection. The cost of re-fetching the rare near-threshold case is negligible; the cost of storing all PDFs speculatively is not.

---

## Alternatives Rejected

### Store all PDFs, extract text as a separate step

**Rejected.** Retains 20–40× the disk footprint for no pipeline benefit. The PDF is not used after text extraction.

### Bulk download via ArXiv S3 mirror

**Rejected.** Produces immediate multi-GB disk pressure before any quality filtering has occurred. Also requires compliance with ArXiv's bulk access terms, which restrict commercial use and require coordination. The on-demand API approach is simpler, within policy, and produces no upfront disk cost.

### HTML-only sources (skip PDF entirely)

**Partially adopted.** ArXiv provides HTML versions for papers submitted in LaTeX (most CS papers). Where HTML is available, prefer it over PDF — the extraction is cleaner and requires no PDF parsing library. The pipeline should attempt HTML first and fall back to PDF only when HTML is unavailable.

---

## Consequences

- The accepted corpus is plain text only. No PDF is retained after scoring.
- Document metadata (title, authors, ArXiv ID, URL, both axis scores, accept/reject decision, timestamp) is stored as a small JSON record per document regardless of pass/fail. This enables re-fetching, threshold recalibration, and audit.
- The disk budget for the pipeline (models + corpus + embeddings + tooling) is projected at under 10 GB total.
- Near-threshold documents can be re-fetched and re-inspected at any time using the stored ArXiv ID.
