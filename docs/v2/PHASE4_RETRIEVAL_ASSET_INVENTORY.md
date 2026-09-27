# Phase 4 — Retrieval Asset Inventory

Read-only inventory (Phase 4 Step 4) of every retrieval-related asset in the
repo, classified as **CURRENT** / **LEGACY** / **STALE** / **UNKNOWN** against
the live production path confirmed by
[`docs/v2/PHASE4_INITIAL_RETRIEVAL_AUDIT.md`](./PHASE4_INITIAL_RETRIEVAL_AUDIT.md).
Full machine-readable version: `artifacts/v2/phase4_retrieval_inventory.json`.

**Classification key**
- **CURRENT** — actively used by the live production path (`retrieval/retriever.py`'s
  default `retrieve()` → `retrieve_hybrid_reranked()`, wired into `agent/nodes.py`'s
  `synthesis_node`).
- **LEGACY** — superseded but kept for reference/reproducibility/history.
- **STALE** — present but not known to be used, possibly outdated vs. CURRENT.
- **UNKNOWN** — cannot be determined from available evidence; stated explicitly.

Root-level `PHASE3_*.md` docs, `RESULTS_RAG_COMPARISON.md`, etc. predate this
project's current V2 phase-gate numbering — their "Phase 3" label is **not**
this project's (already-complete, unrelated) V2 Phase 3. Their build/experiment
history is used as factual context below; every metric number sourced from them
is marked **HISTORICAL/UNVERIFIED**, per the governing Phase 4 directive.

---

## 1. Corpus assets (`data/corpus/`, gitignored)

| Asset | Records | Size | Classification | Why |
|---|---|---|---|---|
| `abstracts.jsonl` | 9,000 | 25.0 MB | **CURRENT** | What `data/index/` was built from; `index_meta.json` confirms `num_abstracts: 9000` matches exactly. |
| `abstracts_raw_all.jsonl` | 13,115 | 36.5 MB | **LEGACY** | Pre-subsample raw fetch, kept for reference; not loaded by any build/production path directly. |

## 2. Index assets (`data/index/`, gitignored)

### Main index — **CURRENT**

`retrieval/retriever.py`'s default `INDEX_PATH`/`CHUNKS_PATH`/`BM25_PATH` point
here with no variant subdirectory; this is what `synthesis_node` retrieves
against.

| File | Size | Detail |
|---|---|---|
| `faiss.index` | 34.8 MB | `IndexFlatIP`, `all-MiniLM-L6-v2`, 384-dim, 22,674 vectors |
| `bm25.pkl` | 26.1 MB | `rank_bm25.BM25Okapi`, 22,674 docs |
| `chunks.jsonl` | 32.7 MB (22,674 lines) | Parallel metadata array |
| `index_meta.json` | — | `chunk_size_words: 180`, `chunk_overlap_words: 30`, `build_time_seconds: 87.4` |
| `bm25_meta.json` | — | tokenizer: lowercase alphanumeric regex, title + chunk_text |

### Variants (`data/index/variants/*/`) — all **STALE**

Not referenced by any production path; each corresponds to a swept
configuration whose eval result measured worse than the CURRENT config.

| Variant | Embed model | Chunk size | Chunks | Corresponding eval results | Classification |
|---|---|---|---|---|---|
| `bge_base_180_30` | BAAI/bge-base-en-v1.5 (768-dim) | 180/30 | 22,674 | `eval_results_bge_base_{dense,hybrid}.json` (0.4173 / 0.4675) | STALE |
| `chunk_256_50` | all-MiniLM-L6-v2 (384-dim) | 256/50 | 17,146 | `eval_results_chunk_256_50_{dense,hybrid}.json` (0.5541 / 0.4792) | STALE |
| `chunk_384_64` | all-MiniLM-L6-v2 (384-dim) | 384/64 | 11,957 | `eval_results_chunk_384_64_{dense,hybrid}.json` (0.567 / 0.4689) | STALE |

(All recall numbers HISTORICAL/UNVERIFIED.)

## 3. Eval-set assets (`retrieval/eval_set*.json`, git-tracked)

Three (four, counting the superseded buggy attempt) distinct eval-set
builders, distinguished by **relevance definition** and **query type**:

| File | Builder | Queries | Definition | Notes |
|---|---|---|---|---|
| `eval_set.json` | `build_eval_set.py` | 19 | LOOSE (general topical relevance) | Survey queries ("what is the evidence for X"); schema v2 |
| `eval_set_strict_buggy_v1.json` | `build_eval_set_strict.py` (attempt 1) | 18 | STRICT | Buggy: model converged on one best match instead of judging each candidate independently — **LEGACY**, superseded |
| `eval_set_strict.json` | `build_eval_set_strict.py` (attempt 2b, fixed) | 18 | STRICT | Corrected per-candidate independent verdicts, batched in groups of 8; schema v5 |
| `eval_set_grounding.json` | `build_eval_set_grounding.py` | 29 (28 written) | STRICT (reused) | Citation-grounding / specific-claim queries, written before consulting corpus content; **the eval set behind the final locked hybrid config** |

STRICT = "a chunk is relevant only if it directly states a fact/finding/
mechanism supporting a specific claim" (vs. LOOSE's general topical match).
All labeling is LLM-assisted (`nvidia/nemotron-3-super-120b-a12b`), explicitly
**not human-verified**.

## 4. Eval-result assets (`retrieval/eval_results_*.json`, git-tracked)

19 files total. Grouped by which eval set they were run against:

**Against `eval_set.json` (loose, survey queries):** `baseline` (dense,
0.5711), `hybrid` (0.4832), `bge_base_dense`/`bge_base_hybrid`,
`chunk_256_50_dense`/`_hybrid`, `chunk_384_64_dense`/`_hybrid`,
`expansion_hybrid` (0.3807) — all **LEGACY**.

**Against `eval_set_strict.json` (strict, survey queries):** `strict_dense`
(0.3408), `strict_hybrid` (0.4016, hybrid first starts winning here) — **LEGACY**.

**Against `eval_set_grounding.json` (strict, grounding queries) — the
decisive round:** `grounding_dense` (0.4761), **`grounding_hybrid` (0.6638,
the best-measured result in the whole series — corresponds to the config
`retrieve()` defaults to today, classified CURRENT)**, `grounding_bge_dense`
(0.5363), `grounding_bge_hybrid` (0.6325), `grounding_bm25_weight_2x`/`_3x`
(0.6549 each), `grounding_hyde_dense_only` (0.4223), `grounding_hyde_hybrid`
(0.6437) — all **LEGACY** except `grounding_hybrid`.

Six of the `grounding_*` files have `mode`/`variant`/`expand` recorded as
`null` in their own JSON — the technique they represent had to be inferred
from filename + git log, not read from structured fields (flagged as an
integrity issue, see below).

All numbers above are **HISTORICAL/UNVERIFIED**. Full detail with per-file
classification/rationale is in the JSON inventory.

## 5. Build & tooling scripts (`retrieval/*.py`)

| Script | Role | Classification |
|---|---|---|
| `build_corpus.py` | Fetches raw corpus via PubMed API, 72 query terms | CURRENT for the raw fetch; **cannot reproduce the shipped 9,000-record subsample** (see integrity issue #1) |
| `build_index.py` | Chunk + embed + build FAISS index (also drives variant builds) | CURRENT |
| `build_bm25.py` | Build BM25 sparse index from chunks | CURRENT |
| `chunking.py` | Fixed word-window chunking (180/30 default) | CURRENT |
| `retriever.py` | `Retriever` class + `retrieve()`/`retrieve_dense()`/`retrieve_hybrid_reranked()`; production entry point | CURRENT |
| `verify.py` | Manual smoke-test of `retrieve()` | CURRENT (utility) |
| `measure_recall.py` | Shared Recall@10 scoring harness behind every `eval_results_*.json` | CURRENT (utility — Phase 4 should re-run this for a trustworthy current number) |
| `build_eval_set.py` | Builds loose survey eval set | LEGACY (produces LEGACY eval set) |
| `build_eval_set_strict.py` | Re-labels pools under strict definition | LEGACY (produces LEGACY eval sets) |
| `build_eval_set_grounding.py` | Builds grounding/citation eval set | CURRENT (produces the eval set behind the current locked config) |
| `experiment_grounding_optimization.py` | Runs HyDE/BM25-reweight/combo experiments against the locked grounding set | LEGACY (experiment driver; no output beat the adopted config) |
| `hyde.py` | HyDE hypothetical-document embedding technique | LEGACY (opt-in, not in default pipeline) |
| `query_expansion.py` | LLM-based query reformulation + RRF fuse | LEGACY (opt-in, not in default pipeline, measured worse) |
| `README.md` | Rebuild instructions, documents the subsampling gap itself | CURRENT (authoritative, cross-checked accurate) |

## 6. Other artifacts

- `retrieval/hyde_cache_grounding.json` — cache of 24 HyDE-generated passages. **LEGACY** (supports a non-adopted technique).
- `RESULTS_RAG_COMPARISON.md` (root, git-tracked) — one-time 30-case `use_rag=True` vs `False` comparison. **LEGACY/HISTORICAL**, numbers unverified.

## 7. Root-level historical docs

| Doc | Retrieval-scoped? | Flag |
|---|---|---|
| `PHASE3_RETRIEVAL_LAYER_COMPLETE.md` | Yes | HISTORICAL/UNVERIFIED — factual build history corroborated accurate by the audit |
| `PHASE3_RETRIEVAL_QUALITY_COMPLETE.md` | Yes | HISTORICAL/UNVERIFIED — **headline conclusion ("defaults to dense") is now stale**; superseded by the later grounding-set result that locked hybrid instead (commit `f80e92f`). Experiment mechanics remain accurate history. |
| `PHASE3_WIRING_COMPLETE.md` | Yes | HISTORICAL/UNVERIFIED — corroborated accurate |
| `PHASE3_CONCURRENCY_VALIDATION.md` | No (explicitly out of scope) | Not a retrieval asset |
| `REPORT_TABLE_DETERMINISM_COMPLETE.md` | No (explicitly out of scope) | Not a retrieval asset |
| `CITATIONS_BUG_INVESTIGATION.md` | No (ChEMBL, not RAG) | Not a retrieval asset |
| `EVAL_HANG_FIX_COMPLETE.md` | No (explicitly out of scope) | Not a retrieval asset |
| `CHEMBL_BACKFILL_COMPLETE.md` | No (explicitly out of scope) | Not a retrieval asset |

## 8. Dependencies (`requirements.txt`)

| Package | Pinned version | Reachable from production? |
|---|---|---|
| `sentence-transformers` | `6.0.1` | Yes — dense embedding model + cross-encoder reranker |
| `faiss-cpu` | `1.15.0` | Yes — `IndexFlatIP` |
| `rank_bm25` | `0.2.2` | Yes — BM25 sparse index |
| `numpy` | `<2` | Yes (ABI compat pin) |

Cross-encoder model `cross-encoder/ms-marco-MiniLM-L-6-v2` is a runtime
HuggingFace model id (no separate pip pin). The `requirements.txt` section
header mislabels this block `"# RAG / retrieval layer (Phase 3)"` — a naming
collision with this project's actual (unrelated, already-complete) V2 Phase 3;
flagged as integrity issue #6 below.

---

## Integrity / reproducibility issues found

1. **[HIGH] Corpus-subsampling reproducibility gap** — the live 9,000-abstract
   corpus was deterministically subsampled (`random.seed(42)`) from a raw
   13,115-abstract fetch, but that subsampling step has **no committed
   script**. `build_corpus.py` as committed today writes every fetched record
   straight through with no subsampling logic, and `git log --follow` shows
   only one commit ever touched that file. **A fresh clone cannot regenerate
   the exact production corpus from committed code alone.** This is the named
   issue called out by the governing Phase 4 directive's Step 28
   ("Index builds must be reproducible... do not rely on opaque manually
   generated index files").
2. **[MEDIUM]** All of `data/` (~406 MB: corpus + index + variants) is
   `.gitignore`d — nothing under it arrives via `git clone`/`git merge`; it was
   manually copied in from a prior build (per `PHASE3_WIRING_COMPLETE.md`).
3. **[MEDIUM]** Zero automated test coverage exists for the RAG retrieval
   layer or its `agent/nodes.py` glue (`_retrieve_rag_context`,
   `_dedupe_retrieved_by_pmid`, `_format_retrieved_context`).
4. **[LOW-MEDIUM]** All `eval_results_*.json`/`eval_set*.json` Recall@10
   numbers are LLM-judge-labeled and explicitly self-described as "not
   human-verified" — treat as historical context only; re-run
   `retrieval/measure_recall.py` for a trustworthy current number.
5. **[LOW]** Six `eval_results_grounding_*.json` files have `null`
   `mode`/`variant`/`expand` fields — technique must be inferred from filename
   + git log rather than read from the file's own structured data.
6. **[LOW]** `requirements.txt`'s retrieval dependency block is labeled
   `"(Phase 3)"`, colliding with this project's actual, unrelated, already-
   complete V2 Phase 3 — a naming hazard that could cause a future Phase 4
   scoping pass to wrongly assume the retrieval layer is already covered.
