# Phase 3: RAG/FAISS Retrieval Layer — Complete

Data pipeline for the RAG retrieval layer: corpus, embeddings, FAISS index,
and a `retrieve()` interface. Built and verified standalone — **not** wired
into `agent/nodes.py` (that's a later, separate pass). **Zero NVIDIA NIM /
ChatNVIDIA calls anywhere in this pass** — corpus acquisition used only
PubMed's REST API, embeddings run locally via `sentence-transformers`.

## 1. Corpus

- **Source**: `PubMedTool` (existing, REST-based `esearch`/`efetch`
  wrapper around NCBI E-utilities) — no LLM involved, and its existing
  3 req/s rate limiter was used as-is.
- **72 query terms** spanning the disease areas in
  `evaluation/test_cases.py`: oncology (18 terms), cardiology (9),
  autoimmune/inflammatory (11), infectious disease (9), neurology (11),
  rare disease (8), plus cross-cutting drug-class/mechanism terms (6).
  Terms were chosen to overlap directly with test-case vocabulary (EGFR/BTK/
  BRAF/PARP/JAK inhibitors, CAR-T, checkpoint inhibitors, CFTR modulators,
  etc.) so the corpus has real topical coverage for what the agent gets
  asked, plus broader disease-area terms for background coverage.
- Fetched with `years_back=15`, `max_results=200` per query — 13,115 unique
  abstracts came back after dedup (72 queries × ~200 each, ~50-95% new per
  query). That overshot the 8k-10k target, so the corpus was **deterministically
  subsampled to 9,000** (`random.seed(42)`, all 72 source queries still
  represented in the subsample). The full 13,115-abstract raw fetch is kept
  at `data/corpus/abstracts_raw_all.jsonl` for reference; the working corpus
  used for indexing is `data/corpus/abstracts.jsonl` (9,000 records).
- Each record: `pmid`, `title`, `abstract`, `journal`, `pub_date`, `year`,
  `doi`, `url`, `query` (which search term surfaced it). Abstracts with no
  text (`"No abstract available"`) were dropped at fetch time.
- Total fetch time: **134s** (~2.2 min) for the raw 13,115-abstract pull.

## 2. Chunking + embedding

- **Chunking**: fixed word-count windows, 180 words with 30-word overlap
  (implemented in `retrieval/chunking.py`). Rationale: PubMed abstracts come
  back as a single joined text block (`PubMedTool` concatenates structured
  Background/Methods/Results/Conclusion sections with spaces) — there's no
  real paragraph structure to split on. A fixed window also keeps chunks
  under `all-MiniLM-L6-v2`'s 256-token limit (180 words ≈ 235 tokens at
  ~1.3 tokens/word), so longer structured abstracts get split into
  multiple retrievable chunks instead of being silently truncated. Most
  abstracts (short, single-block) end up as one chunk; longer ones split
  into 2-4.
- Each chunk is embedded as `"Title: {title}\n\n{chunk text}"` so the
  title's topical signal carries into every chunk of a multi-chunk
  abstract, not just the first — but the raw `chunk_text` (no title
  prefix) is what's stored/returned for display and citation.
- **Embedding model**: `sentence-transformers/all-MiniLM-L6-v2`, 384-dim,
  runs entirely locally on CPU — no external API calls. Chosen for being
  fast, small, and a reasonable-quality general-purpose sentence encoder
  well suited to short scientific-abstract chunks at this corpus scale.
- 9,000 abstracts → **22,674 chunks** (2.52 chunks/abstract average).
  Embedding all 22,674 chunks took **~85s** on CPU (batch size 64).

## 3. FAISS index

- **Type**: `IndexFlatIP` (exact inner-product search over L2-normalized
  vectors, i.e. exact cosine similarity). Justified at this scale: 22,674
  vectors × 384 dims is small enough that brute-force exact search runs in
  single-digit-to-low-double-digit milliseconds per query (see latencies
  below) — there's no accuracy/latency tradeoff to make yet. HNSW/IVF only
  start earning their complexity (approximate recall, tunable
  ef/nlist parameters, more involved build/persist logic) at corpus sizes
  well beyond this one; premature here.
- Persisted to disk: `data/index/faiss.index` (34.8 MB) +
  `data/index/chunks.jsonl` (32.7 MB, parallel array of chunk metadata,
  one line per vector by index position) + `data/index/index_meta.json`
  (model name, dims, chunk params, build stats).
- Total index build time (chunk + embed + index): **87.4s**.

## 4. `retrieve()` interface

`retrieval/retriever.py` exposes:

```python
from retrieval.retriever import retrieve, Document

docs: list[Document] = retrieve(query: str, k: int = 5)
```

`Document` fields: `pmid`, `title`, `text` (the chunk's raw text),
`score` (cosine similarity), `journal`, `year`, `pub_date`, `doi`, `url`,
`chunk_index`, `num_chunks` — everything needed for citation later.

The embedding model and FAISS index are loaded lazily on first call and
cached at module scope (`_get_retriever()`), so repeated calls in the same
process only pay the ~2s load cost once. No network or LLM calls happen
inside `retrieve()` — embedding runs locally.

This is the only module intended for `agent/nodes.py` to import from in the
later wiring pass — it has no dependency on `agent/`, `evaluation/`, or
`config/llm_config.py`/`ChatNVIDIA`.

## 5. Standalone verification

Ran via `python -m retrieval.verify` — 7 queries spanning the disease areas
above, no agent involved. Full output is in the session log; two examples:

```
QUERY: What is the mechanism of action of metformin in type 2 diabetes?
latency: 54.0ms | 3 results

  [1] score=0.793 PMID:37317976 (2023) Polish archives of internal medicine
      Role of metformin in the management of type 2 diabetes: recent advances.
      chunk 3/3: as the first‑line therapy. The novel classes of antidiabetic
      medications have demonstrated significant positive effects on glycemia...

  [2] score=0.782 PMID:35067907 (2022) Pharmacological reports : PR
      An update on mode of action of metformin in modulation of
      meta-inflammation and inflammaging.
```

```
QUERY: CAR-T cell therapy for multiple myeloma targeting BCMA
latency: 133.7ms | 3 results

  [1] score=0.874 PMID:38777913 (2024) International journal of hematology
      Current progress of CAR-T-cell therapy for patients with multiple myeloma.
      chunk 3/3: strategies. In this article, we will review the current
      status of BCMA-targeting CAR-T-cell therapy...

  [2] score=0.865 PMID:38066841 (2023) Hematology. American Society of
      Hematology. Education Program
      Current use of CAR T cells to treat multiple myeloma.
```

All 7 test queries returned topically on-point top-3 results (cosine scores
0.65-0.87), including a mechanism-of-resistance query and a rare-disease
gene-therapy query, confirming the corpus's topical spread holds up at
retrieval time. Per-query latency after the one-time ~2s model/index load:
**11-140ms** (first query per cold process pays a small extra JIT-ish cost;
steady state is at the low end).

## 6. Build time summary

| Stage | Time |
|---|---|
| Corpus fetch (72 queries, 13,115 raw abstracts) | 134s |
| Chunk + embed + build index (9,000 abstracts → 22,674 chunks) | 87s |
| **Total pipeline build** | **~3.7 min** |

## Flags for the later agent-wiring pass

- **Per-query latency (11-140ms)** is negligible next to LLM call latency in
  the agent loop — retrieval won't be the bottleneck once wired in.
- **First call in a fresh process pays ~2s** to load the embedding model +
  FAISS index. If `retrieve()` gets called from a request-scoped process
  (rather than a long-lived one), that 2s will show up on every request —
  worth keeping the process long-lived, or warming the retriever at agent
  startup.
- **Index on disk is ~65 MB total** (`faiss.index` + `chunks.jsonl`) — small
  enough to ship/load without special handling, but `data/` is
  gitignored (pre-existing repo policy), so whatever deployment path is
  used for the agent will need to either rebuild the index or otherwise
  transport these files — they won't come along via `git`.
- **Corpus is a static snapshot** (fetched once, ~2 years to 15 years back
  depending on query, dated 2026-09-09) — no refresh mechanism exists yet.
  If the agent's evaluation surfaces stale-literature complaints, that's
  expected: this pipeline doesn't re-fetch or incrementally update.
- **Chunk-level citation**: `retrieve()` returns individual chunks, not
  whole abstracts — a single PMID can appear multiple times in one result
  set at different `chunk_index` values if several of its windows are all
  relevant. Downstream citation logic should probably dedupe/merge by PMID
  rather than treating each chunk as an independent source.
- The raw 13,115-abstract fetch (before the 9,000 subsample) is preserved
  at `data/corpus/abstracts_raw_all.jsonl` in case a future pass wants a
  larger corpus without re-hitting PubMed.
