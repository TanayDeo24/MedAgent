# Phase 4 — Initial Retrieval Audit

Read-only audit of what retrieval capability exists in this repo *today*,
verified against actual code and files (not the historical description
handed down from "old/pre-V2 MedAgent"). Every claim below is backed by a
file:line citation or a concrete command output. Where something could not
be verified, that is stated explicitly rather than assumed.

**Headline finding: the historical description is essentially accurate and
the retrieval layer it describes is real, present, and live-wired into the
current agent graph** — it is not orphaned legacy code left over from a
prior architecture. It was built and wired in *after* Phase 3's tool
orchestration work (see git log in Section F), as a separate enrichment
path alongside (not inside) `tool_orchestration_node`.

---

## A. PubMed — live API vs. local corpus/index

Both exist, and both are live.

**1. Live API path (Phase 3, typed tool orchestration)**
- `tools/pubmed_tool.py` — `PubMedTool` wraps NCBI E-utilities
  (`esearch.fcgi` / `efetch.fcgi`), live HTTP only, no local data
  (`tools/pubmed_tool.py:1-32,55-107`).
- Called from `agent/nodes.py`'s `tool_orchestration_node`
  (`agent/nodes.py:527-560`) via
  `orchestration/candidate_b_native_tools.py`'s `execute_validated_call()`,
  which is the registry-bound path to the real tool client method
  (`agent/nodes.py:544-552`). Results land in `state["tool_results"]["pubmed"]`.

**2. Local corpus + FAISS + BM25 + cross-encoder RAG path (also live, separate node)**
This is the "old MedAgent" description, and it checks out almost exactly:

- Corpus: `data/corpus/abstracts.jsonl` — **9,000 lines** (`wc -l` = 9000),
  25 MB, built from a raw fetch of 13,115 unique abstracts preserved at
  `data/corpus/abstracts_raw_all.jsonl` (13,115 lines), per
  `retrieval/README.md`'s "Known gap" section (subsampled to 9,000 via
  `random.seed(42)`, no committed subsample script — see below).
- Chunks: `data/index/chunks.jsonl` — **22,674 lines**, matching
  `data/index/index_meta.json`'s `"num_chunks": 22674`.
- Index metadata (`data/index/index_meta.json`):
  ```
  "embedding_model": "all-MiniLM-L6-v2"
  "embedding_dim": 384
  "index_type": "IndexFlatIP (cosine via L2-normalized vectors)"
  "num_abstracts": 9000
  "num_chunks": 22674
  "chunk_size_words": 180
  "chunk_overlap_words": 30
  ```
  i.e. exactly the historical description's numbers (9,000 abstracts,
  22,674 chunks, IndexFlatIP, all-MiniLM-L6-v2).
- Index files present on disk: `data/index/faiss.index` (34.8 MB),
  `data/index/bm25.pkl` (26.1 MB, `rank_bm25`-based), both `mtime` Sep 11
  (this environment's system clock reads 2026, so treat this only as
  "same build batch as the corpus/chunks files," not a calendar claim).
- BM25 metadata (`data/index/bm25_meta.json`): `"num_docs": 22674`,
  tokenizer = "lowercase alphanumeric regex, title + chunk_text".
- Chunking code: `retrieval/chunking.py` (180-word chunks / 30-word overlap,
  matches `index_meta.json`).
- Index-build code: `retrieval/build_index.py` (FAISS `IndexFlatIP` build),
  `retrieval/build_bm25.py` (BM25 build + `tokenize()`, imported by
  `retrieval/retriever.py:25`).
- Corpus-build code: `retrieval/build_corpus.py` — fetches via
  `PubMedTool.search_pubmed()` over 72 hardcoded query terms
  (`retrieval/README.md`'s Step 1 description); this is the one script in
  the whole layer that is *not* reproducible byte-for-byte today — seeSection F/staleness notes below.
- Retriever/query-time code: `retrieval/retriever.py`:
  - `Retriever` class loads `SentenceTransformer(all-MiniLM-L6-v2)` +
    `faiss.read_index()` + lazy BM25 + lazy `CrossEncoder` at
    `retrieval/retriever.py:60-119`.
  - Cross-encoder model: `"cross-encoder/ms-marco-MiniLM-L-6-v2"`
    (`retrieval/retriever.py:39`), used in `_rerank()`
    (`retrieval/retriever.py:121-150`) over the RRF-fused candidate pool.
  - RRF fusion: `_rrf_fuse()` with `RRF_K = 60`
    (`retrieval/retriever.py:36,206-...`) — matches the historical "k=60"
    claim exactly.
  - Default production pipeline is `retrieve_hybrid_reranked()` (dense +
    BM25 → RRF fuse → cross-encoder rerank), confirmed by
    `retrieval/retriever.py:448-453` (`retrieve()` calls
    `_get_retriever().retrieve(...)`, and `retrieve_hybrid_reranked()`'s
    docstring at `retrieval/retriever.py:477-486` states "This is what
    `retrieve()` calls by default"), and by git commit `f80e92f "Lock final
    config: retrieve() now defaults to the hybrid pipeline"`.
- **Is this code invoked from the current production path?** Yes, but
  *not* through `tool_orchestration_node`/`orchestration/`. It is imported
  and called directly in `agent/nodes.py`:
  - Import: `agent/nodes.py:37` —
    `from retrieval.retriever import retrieve as retrieve_passages, _get_retriever`.
  - Warm-loaded at module import time: `agent/nodes.py:62-70`.
  - Invoked inside `synthesis_node` via `_retrieve_rag_context()`
    (`agent/nodes.py:354-383`, called at `agent/nodes.py:877`), gated on
    `state.get("use_rag", True)` (`agent/nodes.py:876-881`). Result is
    stored in `state["retrieved_context"]` and formatted into both the
    `SYNTHESIS_PROMPT` (`agent/nodes.py:884-888`) and the
    `REPORT_GENERATION_PROMPT` (`agent/nodes.py:1103-1131`), and surfaced
    as `"PubMed RAG"`-labeled citations distinct from live-API `"PubMed"`
    citations (`agent/nodes.py:1098-1109`, comment explicitly distinguishes
    the two provenances).
  - `RAG_RETRIEVAL_K = 10` (`agent/nodes.py:52`); results deduped by PMID
    before use (`_dedupe_retrieved_by_pmid`, `agent/nodes.py:333-351,369`).
  - A thread lock (`_rag_retrieval_lock`, `agent/nodes.py:90`) serializes
    concurrent `retrieve()` calls — added in commit `01760fe "Fix a real
    Metal/MPS crash on concurrent RAG retrieval calls"`, i.e. this path has
    been run under real concurrency load, not just unit-tested.
  - `report_generation_node` also consumes `state["retrieved_context"]`
    (`agent/nodes.py:1103-1131`) but does **not** call `retrieve()` again —
    it reuses what `synthesis_node` already fetched (comment at
    `agent/nodes.py:862-866` explains why: one retrieval per query, shared
    by both nodes).
  - This RAG path is entirely separate from `orchestration/`'s typed tool
    orchestration: it is not one of the three `ToolName` values
    (`orchestration/models.py`), is not in `orchestration/registry.py`'s
    `DEFAULT_REGISTRY`, and `tool_orchestration_node` never touches
    `retrieve_passages`/`retrieved_context` (confirmed: no `retriev`/`rag`
    hits inside `tool_orchestration_node`'s body,
    `agent/nodes.py:527-~820`).

**Additional index variants present (experimentation artifacts, not
production):** `data/index/variants/{bge_base_180_30,chunk_256_50,chunk_384_64}/`
each contain their own `faiss.index`/`bm25.pkl`/`chunks.jsonl`/
`index_meta.json`, corresponding to embedding-model and chunk-size
experiments run via `retrieval/experiment_grounding_optimization.py` and
recorded in the many `retrieval/eval_results_*.json` files (see Section E).
None of these are referenced by `agent/nodes.py` or any production path —
only `data/index/{faiss.index,bm25.pkl,chunks.jsonl,index_meta.json}`
(no variant subdirectory) is loaded by `retrieval/retriever.py`'s default
`INDEX_PATH`/`CHUNKS_PATH`/`BM25_PATH` constants
(`retrieval/retriever.py:27-31`).

---

## B. ClinicalTrials.gov — live-API-only, no local index

Confirmed. `tools/clinical_trials_tool.py:1-13` wraps the
ClinicalTrials.gov REST API (`clinicaltrials.gov/api/gui`) via `BaseTool`
+ `requests` session, no local file/index loading anywhere in the file.
`orchestration/models.py:140-155`'s `ClinicalTrialsSearchArgs` is a typed
pydantic schema mirroring `ClinicalTrialsTool.search_trials()`'s live-call
signature (`condition, intervention, status, phase, max_results, sponsor,
country`) — it validates arguments for the live call, it does not describe
or gate any local corpus.

Repo-wide search for a hidden local trials corpus:
```
grep -rn "clinical_trials\|ClinicalTrials" retrieval/ data/  →  no matches
find . -iname "*trial*" -not -path "*/venv/*"  →  only tools/clinical_trials_tool.py and orchestration references
```
No local ClinicalTrials.gov corpus, index, or cache file exists anywhere
in the repo.

---

## C. ChEMBL — live-API-only, no local index

Confirmed. `tools/chembl_tool.py:1-13` wraps the ChEMBL web services API
(`chembl.gitbook.io`) via `BaseTool` + `requests`, no local file/index
loading in the file. `agent/nodes.py:50`'s module-level `_chembl_backfill_tool
= ChEMBLTool()` instance is explicitly documented as used only for
name-backfill on already-fetched results (`agent/nodes.py:43-50`), not as
a local corpus.

Repo-wide search: `grep -rn "chembl\|ChEMBL" retrieval/ data/` → no
matches. No local ChEMBL corpus or index exists anywhere in the repo.

---

## D. Cross-source fusion / ranking

There is **no cross-source ranking or fusion code**. `state["tool_results"]`
stays a dict keyed per source (`pubmed` / `clinical_trials` / `chembl`),
each a separate list, all the way through:

- `tool_orchestration_node` merges each call's data into
  `state["tool_results"]` keyed by tool name (`agent/nodes.py:754-767`) —
  no interleaving or cross-tool score across sources at this point.
- `synthesis_node` (`agent/nodes.py:823-...`) truncates each source's list
  independently to its first 10 entries (`formatted_results[tool_name] =
  results[:10]`, `agent/nodes.py:857-860`) and hands the whole
  per-source-keyed dict to the LLM as JSON; any "connections between
  results from different tools" (per the node's own docstring,
  `agent/nodes.py:828-833`) is produced by the LLM's free-text synthesis,
  not by any ranking/fusion function in code.
- `report_generation_node` similarly iterates `tool_results.items()` and
  truncates each source's list to 20 for citations
  (`agent/nodes.py:1069-1071`, `results[:20]`) — again per-source, no
  cross-source score comparison.
- The only real fusion/dedup logic in the codebase is *within* the RAG
  path only: `_rrf_fuse()` fuses dense+BM25 candidates *within* the PubMed
  local-index retriever (`retrieval/retriever.py:206-...`), and
  `_dedupe_retrieved_by_pmid()` dedupes RAG passages by PMID
  (`agent/nodes.py:333-351`). Neither touches `tool_results` or crosses
  the PubMed/ClinicalTrials/ChEMBL boundary.
- No top-k selection across sources, no cross-source deduplication (e.g. a
  drug appearing in both a PubMed abstract and a ChEMBL record is never
  merged/deduped), and no cross-source relevance ranking exists anywhere
  in `agent/nodes.py` or `orchestration/`.

---

## E. Tests / eval artifacts

**Tests:** No retrieval-specific tests exist in `tests/`.
```
find tests -iname "*retriev*" -o -iname "*rag*" -o -iname "*faiss*" \
  -o -iname "*bm25*" -o -iname "*chunk*" -o -iname "*rerank*"   → no results
grep -rln "faiss|FAISS|bm25|BM25|CrossEncoder|retrieve(" tests/  → no results
grep -n "rag|RAG|retrieve" tests/test_nodes.py                  → no results
```
`tests/test_nodes.py` (which exercises `agent/nodes.py`) does not test
`_retrieve_rag_context`, `_dedupe_retrieved_by_pmid`, or
`_format_retrieved_context` at all, despite these being live, wired-in
functions. This is a real, current test gap, not a legacy-code question.
`tests/` covers `test_pubmed.py`, `test_clinical_trials.py`,
`test_chembl.py` (live-API tool wrappers), `test_candidate_b_native_tools.py`,
`test_orchestration_models.py`, `test_orchestration_registry.py`,
`test_query_compilers.py` (Phase 3 orchestration), `test_nlu.py` (Phase 2),
and `test_nodes.py`, `test_rate_limiter.py`, `test_settings_security.py` —
none touch `retrieval/`.

**Retrieval evaluation scripts (present, and actively used — not stale
artifacts from a prior era):** `retrieval/measure_recall.py`,
`retrieval/build_eval_set.py`, `retrieval/build_eval_set_strict.py`,
`retrieval/build_eval_set_grounding.py`,
`retrieval/experiment_grounding_optimization.py`,
`retrieval/query_expansion.py`, `retrieval/hyde.py`, `retrieval/verify.py`.

**Eval result artifacts:** a large number of
`retrieval/eval_results_*.json` files (baseline, hybrid, dense,
`bge_base_dense`/`bge_base_hybrid`, `chunk_256_50_*`, `chunk_384_64_*`,
`expansion_hybrid`, grounding-set variants including
`bm25_weight_2x`/`bm25_weight_3x`, HyDE variants) plus
`retrieval/eval_set.json`, `retrieval/eval_set_grounding.json`,
`retrieval/eval_set_strict.json`, `retrieval/eval_set_strict_buggy_v1.json`,
`retrieval/hyde_cache_grounding.json`. These clearly correspond to a
Recall@10-driven experiment series (git log below), not to nDCG/MRR — no
nDCG or MRR references were found anywhere in `retrieval/`:
```
grep -rln "recall@\|nDCG\|MRR" retrieval/  →  only measure_recall.py and the eval_results_*.json / eval_set_*.json files (Recall@10 only)
```
Per governing instructions, these numbers are reported as historical
context only and are **not** treated as current baselines by this audit —
Phase 4 should re-run `retrieval/measure_recall.py` itself if it wants a
trustworthy current number, rather than reading these files as ground
truth. Git log (`git log --oneline -- retrieval/`) shows this entire
experiment series (BM25 add, RRF fusion, cross-encoder rerank, chunk-size
sweeps, embedding-model sweep, query expansion, HyDE, BM25-reweighting) is
one continuous, connected commit sequence ending in `f80e92f "Lock final
config: retrieve() now defaults to the hybrid pipeline"`, immediately
followed by `e0a56f4 "Wire RAG retrieval into synthesis/report generation
nodes"` — i.e. the wiring into `agent/nodes.py` happened right after, and
because of, this experimentation, not as a leftover from a different
project.

**Other artifacts referencing this history at the repo root (not under
`docs/v2/`, so easy to miss):** `PHASE3_RETRIEVAL_LAYER_COMPLETE.md`,
`PHASE3_WIRING_COMPLETE.md`, `RESULTS_RAG_COMPARISON.md`,
`retrieval/README.md`. These are the primary source docs for the build
history and rebuild instructions and were used as corroborating evidence
above; they are current/accurate against the code as far as this audit
checked (corpus size, chunk count, RRF k=60, chunking params, default
pipeline all cross-checked independently against `data/index/index_meta.json`
and `retrieval/retriever.py`, and matched).

**One genuine staleness/reproducibility gap**, per `retrieval/README.md`
itself: the production 9,000-abstract corpus was subsampled from the raw
13,115-abstract fetch via an "ad hoc, uncommitted script" (`random.seed(42)`)
that is not reproducible from anything currently checked in —
`retrieval/build_corpus.py` as it exists today writes all fetched records
straight through with no subsampling step. This means the exact corpus
cannot be rebuilt from scratch from committed code alone; the *built*
`data/` artifacts (which are `.gitignore`d, per `retrieval/README.md`'s
opening line) are what's actually running, not something CI/a fresh clone
regenerates automatically.

---

## F. Dependencies

`requirements.txt` (repo root) explicitly lists, under a `# RAG /
retrieval layer (Phase 3)` header:
```
sentence-transformers==6.0.1
faiss-cpu==1.15.0
rank_bm25==0.2.2
numpy<2  # pinned for sentence-transformers/scipy/scikit-learn ABI compat with pandas 2.1.4
```
No `pyproject.toml` exists in the repo (only `requirements.txt`).

All three retrieval libraries are demonstrably reachable from the current
production path, not just declared-but-unused:
- `faiss` — imported and used in `retrieval/retriever.py:21,81`
  (`faiss.read_index`), reached via `agent/nodes.py:37,62-70,369`.
- `sentence-transformers` — `SentenceTransformer` and `CrossEncoder`
  imported at `retrieval/retriever.py:23`, used at
  `retrieval/retriever.py:80,118`, reached via the same import chain.
- `rank_bm25`-based BM25 — built by `retrieval/build_bm25.py`, loaded
  lazily by `Retriever._load_cross_encoder`'s sibling BM25 loader in
  `retrieval/retriever.py` (`self._bm25`, `retrieval/retriever.py:109-110`),
  reached the same way.

Note the header comment mislabels this as "(Phase 3)" even though Phase 3
(per `docs/v2/PHASE3_TOOL_ORCHESTRATION.md` etc.) was frozen as the typed
tool-orchestration work — the git log timestamps/commit sequence
(Section E above) show the RAG layer was actually built and wired in as
its own, later, separate body of work, using "Phase 3" only as a loose
label in that one comment. This is worth flagging as a naming
inconsistency for whoever scopes Phase 4, since it could cause someone to
assume Phase 3's frozen scope already covers this and skip auditing it —
which is exactly the mistake this document exists to prevent.

---

## Summary: what retrieval infrastructure actually exists and is LIVE today

- **PubMed live API tool** (`tools/pubmed_tool.py`) called through Phase 3
  typed orchestration (`agent/nodes.py`'s `tool_orchestration_node` →
  `orchestration/`) — populates `state["tool_results"]["pubmed"]`.
- **PubMed local RAG layer** — a real, working, hybrid retrieval pipeline:
  9,000-abstract corpus, 22,674 chunks, FAISS `IndexFlatIP` dense index
  (`all-MiniLM-L6-v2`, 384-dim), `rank_bm25` sparse index, RRF fusion
  (k=60), `cross-encoder/ms-marco-MiniLM-L-6-v2` reranking. Wired directly
  into `agent/nodes.py`'s `synthesis_node` (and consumed by
  `report_generation_node`) as `state["retrieved_context"]`, independent
  of and in addition to the live PubMed API tool call. Gated by a
  `use_rag` flag (default `True`). This is genuinely live in the current
  production graph, not dead code.
- **ClinicalTrials.gov** — live-API-only (`tools/clinical_trials_tool.py`),
  no local index of any kind, confirmed by repo-wide search.
- **ChEMBL** — live-API-only (`tools/chembl_tool.py`), no local index of
  any kind, confirmed by repo-wide search.
- **Dependencies** `faiss-cpu`, `sentence-transformers`, `rank_bm25` are
  all declared in `requirements.txt` and all actually reachable from the
  live `agent/nodes.py` → `retrieval/retriever.py` import chain.

## Summary: what is legacy / stale / disconnected

- **Three experimental index variants** under `data/index/variants/`
  (`bge_base_180_30`, `chunk_256_50`, `chunk_384_64`) are on disk but not
  referenced by any production code path — only the top-level
  `data/index/{faiss.index,bm25.pkl,chunks.jsonl,index_meta.json}` is
  loaded by default. These are experimentation-only artifacts.
- **The corpus-subsampling step** (13,115 → 9,000 abstracts,
  `random.seed(42)`) has no committed/reproducible script — the currently
  running `data/corpus/abstracts.jsonl` cannot be regenerated from
  `retrieval/build_corpus.py` alone today. The *artifact* is live; the
  *build process that produced it* is partially undocumented/lost.
- **No test coverage** exists for any part of the RAG retrieval layer
  (`retrieval/` or the `agent/nodes.py` RAG glue) — `tests/test_nodes.py`
  does not exercise `_retrieve_rag_context`/`_dedupe_retrieved_by_pmid`/
  `_format_retrieved_context` at all. Functionally live, but untested at
  the level the rest of this codebase's `tests/` directory otherwise holds
  itself to.
- **Cross-source fusion/ranking does not exist anywhere** (Section D) —
  `tool_results` from PubMed/ClinicalTrials/ChEMBL are combined only via
  free-text LLM synthesis, never via code-level ranking, deduplication, or
  top-k selection across sources. If Phase 4's brief includes
  "heterogeneous retrieval... across PubMed, ClinicalTrials.gov, and
  ChEMBL," this cross-source layer is the one piece that is genuinely
  **greenfield** — nothing to revive here, because nothing was ever built.
- The many `retrieval/eval_results_*.json` / `eval_set*.json` files are
  historical experiment records (Recall@10-driven only; no nDCG/MRR found)
  from the retrieval layer's own tuning process — useful as context for
  *how* the current hybrid config was chosen, but per the governing
  directive, not to be treated as current baselines by Phase 4 without
  independently re-running `retrieval/measure_recall.py`.
