# ADR-0005: Embedding Model — nomic-embed-text via Ollama

**Date:** 2026-06-15  
**Status:** Accepted

---

## Context

The domain relevance axis (ADR-0001) requires embedding both the seed corpus documents and candidate documents into a shared vector space, then computing cosine similarity. The choice of embedding model determines the quality of the similarity signal, the disk footprint, the inference speed on CPU, and the reproducibility of the pipeline.

The development machine is an i5-12400 with 32 GB RAM and no discrete GPU. The model must run locally — no API calls for scoring, which would introduce cost, latency, and an external dependency in the hot path of the pipeline.

---

## Decision

**`nomic-embed-text`** via Ollama.

- Model size: ~270 MB
- Context window: 8192 tokens
- Inference: CPU-only, no GPU required
- Deployment: `ollama pull nomic-embed-text`, then local HTTP API at `localhost:11434`
- Licence: Apache 2.0 — no restrictions on use

---

## Rationale

**Performance on retrieval benchmarks.**

`nomic-embed-text` achieves competitive performance on MTEB (Massive Text Embedding Benchmark) retrieval tasks at a fraction of the size of larger models. For domain-specific similarity — where the query and corpus share vocabulary and reasoning style — a smaller well-trained embedding model often outperforms larger general models because the similarity signal is less diluted by out-of-domain training data.

**270 MB fits comfortably in the disk and RAM budget.**

The model loads once, stays resident in memory during a pipeline run (~500 MB RAM footprint), and is fast enough on the i5-12400 to embed a 20-page paper in under 2 seconds. The entire seed corpus (all clock-aware-programming markdown files) embeds in under a minute.

**Ollama provides a stable, version-pinned local API.**

Running the embedding model through Ollama means the pipeline calls a local HTTP endpoint — the same interface it would use for any other locally-hosted model. Model versioning, updates, and swaps are handled by Ollama without changing pipeline code. If a better embedding model becomes available, the swap is one `ollama pull` command and one configuration line change.

**8192 token context window covers all target documents.**

A 20-page academic paper is approximately 5,000–8,000 tokens. The 8192 token window means full-document embedding is possible without chunking for most papers. Chunking introduces averaging artefacts that can misrepresent papers where the high-quality reasoning appears only in specific sections.

**CPU-only inference removes the GPU dependency.**

The pipeline must be reproducible on the development machine and on any contributor's machine without requiring a GPU. `nomic-embed-text` via Ollama meets this requirement. GPU inference would be faster but is not a hard requirement for a pipeline that processes one document at a time.

---

## Alternatives Rejected

### OpenAI `text-embedding-3-small` or `text-embedding-3-large` (API)

**Rejected.** External API dependency in the scoring pipeline. Every document embedding requires a network call and incurs per-token cost. The pipeline is designed to run offline and at zero marginal cost per document. API embedding breaks both properties.

### `sentence-transformers/all-MiniLM-L6-v2`

**Rejected.** 384-dimensional embeddings versus `nomic-embed-text`'s 768 dimensions. The lower dimensionality reduces the precision of cosine similarity comparisons in a domain-specific setting where fine-grained semantic distinctions matter. Also requires direct Python dependency on `sentence-transformers` and its transitive dependencies, adding installation complexity.

### `BAAI/bge-large-en-v1.5`

**Rejected.** Higher quality on general benchmarks but 1.3 GB model size and significantly slower CPU inference. The marginal quality improvement over `nomic-embed-text` does not justify the 5× size increase for this use case.

### Chunked embedding with averaging

**Rejected as default.** Chunking a 20-page paper into 512-token chunks and averaging the chunk embeddings loses the document-level coherence signal. A paper that reasons from first principles over 20 pages has a different global embedding than one that states conclusions in the first page and fills the rest with citations. Full-document embedding preserves this signal. Chunking is available as a fallback for documents exceeding 8192 tokens.

---

## Consequences

- `ollama` must be installed on the development machine. This is a one-time setup step.
- The pipeline has a local service dependency (`ollama serve` must be running). This is documented in the setup instructions.
- Embedding consistency: all documents in the corpus must be embedded with the same model version. Model upgrades require re-embedding the full corpus — acceptable given the corpus size target.
- The 8192-token limit means documents longer than approximately 30 pages may require chunking. This edge case is handled by the pipeline but is not the common case for academic papers.
