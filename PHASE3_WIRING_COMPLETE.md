# Phase 3: RAG Retrieval Layer Wired into the Agent Pipeline

## 0. Branch/setup note (read first — the task's premise didn't hold)

The task described `retrieval/` and the built index/corpus in `data/` as
"already merged into this branch." That was not true when work started:

- `retrieval/` (the locked hybrid dense+BM25+RRF+rerank pipeline) lived only
  on a separate, diverged branch (`phase3-rag`, checked out in a sibling
  worktree at `/Users/tanaydeo/Documents/medagent-rag`). It had never been
  merged into `main`. `main` had moved on since the two branches' common
  ancestor with its own eval-infra fixes (concurrency, 429/503 retry, the
  hallucination judge fix) that `phase3-rag` didn't have.
- `data/` (the built FAISS index + BM25 pickle + corpus, ~406MB) is
  `.gitignore`d, so it was never going to arrive via any git merge — it only
  ever existed on disk in the `phase3-rag` worktree.

Resolved by: merging `phase3-rag` into `main` in this worktree (clean merge,
no conflicts — `phase3-rag` had no changes under `agent/`), then copying
`data/` from the sibling worktree unmodified. `retrieval/retriever.py`
resolves its paths relative to its own file location
(`Path(__file__).resolve().parent.parent / "data"`), so no path/config
changes were needed for the copy to work. Confirmed at
`main` HEAD = `60e8c58` (merge commit) before this pass's own commits.

None of `retrieval/`'s code, its locked configuration, or any retrieval
measurement was touched — per the task's scope, all wiring work stayed in
`agent/nodes.py`, `agent/prompts.py`, and `agent/state.py`.

## 1. What was wired

**`agent/state.py`**: added `retrieved_context: List[Dict[str, Any]]` to
`AgentState` (and to `create_initial_state`'s defaults). Holds the
RAG-retrieved passages (pmid/title/text/url/score) for the current run,
populated once in `synthesis_node` and reused by `report_generation_node` —
one `retrieve()` call per run, not one per node.

**`agent/nodes.py`**:
- `from retrieval.retriever import retrieve as retrieve_passages, _get_retriever`,
  plus a module-import-time call to `_get_retriever()` (wrapped in
  try/except so a missing/unbuilt index doesn't crash import — degrades
  gracefully instead, same as every other optional-enrichment failure mode
  already in this file).
- `_dedupe_retrieved_by_pmid()`: defensive per-PMID dedup at the call site
  (same pattern as `_build_chembl_compound_table`'s `chembl_id` dedup).
  Note: `retrieve()`'s own hybrid pipeline already dedupes by PMID
  internally (`Retriever._dedup_rows_by_pmid`), so this is belt-and-suspenders,
  not covering an actual observed bug — kept anyway since it was explicitly
  asked for and costs nothing.
- `_retrieve_rag_context(query)`: calls `retrieve_passages(query, k=10)`,
  dedupes, converts `Document` objects to plain dicts, and never raises —
  returns `[]` on any failure.
- `_format_retrieved_context(...)`: renders the retrieved passages as
  `[PMID ...] Title\ntext` blocks for prompt insertion.
- `synthesis_node`: calls `_retrieve_rag_context(query)` once, stores the
  result in `state["retrieved_context"]`, and passes the formatted context
  into `SYNTHESIS_PROMPT`.
- `report_generation_node`: reuses `state["retrieved_context"]` (no second
  `retrieve()` call for the same query — verified safe since `synthesis`
  always precedes `report_generation` in `agent/graph.py`'s graph, on every
  path including the loop-back-for-more-research path), passes it into
  `REPORT_GENERATION_PROMPT`, and appends one citation per retrieved passage
  with `"source": "PubMed RAG"` — kept structurally distinct from the
  existing `"source": "PubMed"` citations, which come from a live
  `PubMedTool` API call, not this local index.

**`agent/prompts.py`**:
- `SYNTHESIS_PROMPT`: added a `RETRIEVED CONTEXT` section and two new
  synthesis rules instructing the model to ground claims in it and use it
  to fill gaps where `tool_results` are thin, consistent with the existing
  anti-hallucination instructions.
- `REPORT_GENERATION_PROMPT`: added a `RETRIEVED CONTEXT` section, and
  extended the "ground everything" and "cite all claims" critical
  requirements to cover it, including the `"(PubMed RAG)"` inline-citation
  convention.

## 2. Real example of retrieved context appearing in a report

Two end-to-end runs via `python main.py --trace`, both against real NVIDIA
NIM calls and the real corpus/index (no mocking):

**Query 1**: "What EGFR inhibitors are used for non-small cell lung cancer?"
(`--max-iterations 1`)
- `[SYNTHESIS] Retrieved 10 RAG passages` logged.
- Final report: 50 citations total, 9 of them `"PubMed RAG"` (PMIDs
  26268739, 28138934, 28699260, 29766737, 34217707, 27912836, 40372786,
  25382203, 26781399, 31558282).
- Concretely grounded claims that came *only* from RAG, not from the live
  PubMed tool call (which returned 0 results for this run — MeSH query
  mismatch): lazertinib as a third-generation EGFR TKI targeting T790M
  (PMID 40372786), XHL11 as a novel selective EGFR inhibitor overcoming
  EGFR-mediated resistance (PMID 34217707), and the general resistance
  narrative motivating next-generation TKIs (PMID 27912836). Report text:
  > "Lazertinib and XHL11 are described in PubMed as third-generation and
  > selective EGFR inhibitors, respectively, with activity against T790M
  > and other resistant mutants【PubMed RAG】."

**Query 2**: "What is pembrolizumab used for?" (from `evaluation/test_cases.py`,
reused for comparability with earlier phases, `--max-iterations 1`)
- `[SYNTHESIS] Retrieved 10 RAG passages` logged.
- Final report: 30 citations total, 17 `"PubMed RAG"` mentions covering
  distinct indications (NSCLC first-line, gastroesophageal cancer, melanoma,
  TNBC combination therapy, TMB-based histology-agnostic approval, Merkel
  cell carcinoma case reports) each tied to a specific PMID (e.g. PMID
  38537779 for TMB companion-diagnostic approval, PMID 32919526 for the
  KEYNOTE-158 biomarker analysis). ChEMBL returned no pembrolizumab-specific
  data for this run (it's a biologic, not a small molecule in that
  database), so RAG was the dominant grounding source for the entire
  clinical-indications section of this report — a real case where the
  RAG layer materially changed report content vs. what tool_results alone
  would have supported.

Both runs' citations correctly separate `"PubMed"` (live API, tool_results)
from `"PubMed RAG"` (this pass's retrieval index) — never conflated in
either report.

## 3. One-time-load behavior confirmed

Measured directly (not inferred):

- `import agent.nodes` (which triggers the module-level `_get_retriever()`
  warm-load: SentenceTransformer embedding model + FAISS index + chunk
  metadata) took **4.34s**, with a single `[RAG] Retriever ... loaded at
  module import` log line.
- First `retrieve()` call after that: **2.11s** — this is BM25 and the
  cross-encoder loading lazily on first real use (by `retrieval/retriever.py`'s
  own existing lazy-load design for those two components specifically,
  unchanged by this pass).
- Second `retrieve()` call, different query: **0.25s** — no reload,
  confirms the singleton cache (`retrieval.retriever._get_retriever`'s
  module-global `_retriever`) is doing its job.
- Across both full end-to-end runs above (query 1 then query 2, same
  process would show this if run back-to-back — these were run as separate
  processes, so each shows its own single `[RAG] Retriever ... loaded at
  module import` line, exactly once per process, never once per node call
  within a run). Within each single run, `synthesis_node` calls
  `retrieve_passages()` exactly once (not once per node), confirmed by
  exactly one `[SYNTHESIS] Retrieved N RAG passages` log line per run and
  zero additional retrieval calls from `report_generation_node` (it reads
  `state["retrieved_context"]` instead).

## 4. Verification

- `pytest tests/` (via the venv at `/Users/tanaydeo/Documents/medagent-rag/venv`,
  since `retrieval/`'s dependencies — sentence-transformers, faiss-cpu,
  langchain-nvidia-ai-endpoints — aren't in the system Python): **40/42
  passing**, the same 2 pre-existing failures as before this pass
  (`test_chembl.py::TestChEMBLRateLimiting::test_rate_limit_applied`,
  `test_pubmed.py::TestPubMedRateLimiting::test_rate_limit_applied`) —
  confirmed unchanged by diffing against a `git stash` run of the same
  suite pre-edit.
- No file under `retrieval/` was modified. No retrieval measurement was
  re-run. `data/` was copied, not regenerated.

## 5. Flags for the upcoming baseline-vs-RAG comparison run (next step, not done here)

- **Environment**: this repo's own Python environment is missing
  `langchain-nvidia-ai-endpoints` (and likely the other RAG-side deps) —
  the comparison run will need the same venv used for this verification
  (`/Users/tanaydeo/Documents/medagent-rag/venv`) or an equivalent one with
  both sets of dependencies installed. Worth resolving/documenting properly
  before that run rather than working around it ad hoc again.
- **RAG isn't always the dominant signal**: query 1 shows RAG passages
  citing findings the live PubMed tool call completely missed (0 results
  that run) — a baseline-vs-RAG comparison run may show a larger uplift
  than expected specifically when the live PubMed query the LLM generates
  is a poor match (MeSH term mismatch, as happened here), since RAG doesn't
  depend on that generated query being good.
- **RAG can also be the majority grounding source even when tool calls
  succeed**: query 2 shows ChEMBL legitimately returning no
  pembrolizumab-specific data (it's a biologic) while RAG carried nearly
  the entire clinical-indications section — this is a case where "RAG vs.
  baseline" isn't just incremental grounding, it changes what the report
  can say at all for certain query types (biologics, antibodies) that
  ChEMBL structurally can't help with.
- **`data/` is not committed** — anyone else running this branch (a fresh
  clone, CI, another comparison run) needs the same manual `data/` copy (or
  a documented `retrieval.build_corpus` + `retrieval.build_index` +
  `retrieval.build_bm25` rebuild) done here; this is not something git
  alone will ever hand them.
- Both verification runs used `--max-iterations 1` to keep the check fast;
  the comparison run should presumably use whatever `max_iterations` the
  original 60-case Phase 2 batch used, for a fair comparison against those
  numbers.
