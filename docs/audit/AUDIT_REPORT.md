# AUDIT_REPORT.md — MedAgent Forensic Engineering Audit

Audit date: 2026-09-23. Audit-only; no files outside `docs/audit/` and
`artifacts/audit/` were modified; no git rebase/reset/checkout/commit commands
were run. Two file populations are used throughout — **WORKING TREE** (what is
physically on disk right now) and **GIT HISTORY (14a59b9)** (the last fully
committed state, read non-destructively via `git archive 14a59b9`). See
`INITIAL_STATE.md` §1 for why this distinction is necessary and how it was
established. Unless marked WORKING TREE, all code citations are to the
git-history snapshot.

---

## 1. EXECUTIVE AUDIT SUMMARY

MedAgent is a real, substantially-implemented LangGraph-based biomedical
research agent (6 real graph nodes, 3 real external API integrations, a
genuine hybrid FAISS+BM25+RRF+cross-encoder RAG pipeline, and an honest,
self-critical evaluation harness) — but the **working tree, as currently
checked out mid-interactive-rebase, contains zero Python source files** (only
compiled `__pycache__` bytecode); every code-level finding here had to be
traced through git history at commit `14a59b9`. Separately and more
importantly for the audit's stated purpose: **every one of the specific
headline metrics named in the task's target-claim list (96% task completion,
98% tool reliability, 5K+ workflows, 10K+ documents, Recall@10 ~0.92, nDCG@10
~0.88, hallucination ~5%, ~35% grounding improvement, citation faithfulness
~0.91) is either explicitly self-disclosed as fabricated by the project's own
`RESULTS.md`/`RESULTS_RAG_COMPARISON.md`, or unsupported/contradicted by the
project's own machine-generated evaluation artifacts.** The underlying
engineering, however, is largely real: a working 6-node agent graph with
genuine conditional self-reflection, three correctly-wired external APIs, a
measured (if modest) hybrid retrieval pipeline, and an evaluation team that
documented its own failures (a 90-minute hang, a Metal/MPS concurrency crash,
a hallucination-judge reliability collapse) in unusual, credible detail. See
`CLAIM_EVIDENCE_MATRIX.md` for the full claim-by-claim verdict table.

## 2. REPOSITORY STATE

See `INITIAL_STATE.md` in full. Summary: mid-interactive-rebase
(`onto 58a2b2f`, editing `b4af5c0`, 135 commands remaining), `HEAD` at an
**empty** commit, so the working tree currently has no tracked `.py` files at
all (only `__pycache__`). Untracked-but-present: 11 root narrative `.md`
files, `data/` (406MB), `logs/medagent.log` (19,159 lines), `.env` (keys:
`NVIDIA_API_KEY`, `LOG_LEVEL`, `LOG_FILE`), `venv/` (1.2GB, Python 3.12.7,
Darwin/arm64). Git history's last complete commit is `14a59b9`, read via
`git archive` (non-destructive).

## 3. REPOSITORY INVENTORY

See `REPOSITORY_INVENTORY.md` and `artifacts/audit/repository_manifest.json`
in full. Summary: 9,847 lines of core module Python across `agent/` (2,261),
`config/` (522), `tools/` (1,370), `retrieval/` (~1,946 incl. experimental
scripts), `evaluation/` (2,731), `utils/` (613), `main.py` (92). Plus 1,029
lines of tests, 10 aggregate + 8 incremental evaluation-result JSON artifacts,
19 retrieval eval-result JSON artifacts, and 11 root narrative docs.

## 4. DOCUMENTATION VS IMPLEMENTATION

The root narrative docs (`PHASE1/2/3_COMPLETE.md`, `EVAL_HANG_FIX_COMPLETE.md`,
`CHEMBL_BACKFILL_COMPLETE.md`, `CITATIONS_BUG_INVESTIGATION.md`,
`REPORT_TABLE_DETERMINISM_COMPLETE.md`) are unusual among "completion
narrative" docs in that they are largely **self-correcting**: `RESULTS.md` and
`RESULTS_RAG_COMPARISON.md` explicitly name and repudiate earlier fabricated
figures (96%/98%/5K+/35%) and replace them with measured numbers, including
numbers that make the project look worse (18-38% task success). This is the
opposite failure mode from typical doc drift — the risk here is not
over-claiming in the current docs, it's that **`AUDIT_CURRENT_STATE.md`** (a
prior audit, dated 2026-09-08) is now **stale**: it describes a pre-RAG,
2-broken-tools state that later commits fixed, and it remains in the repo
uncorrected. See `CLAIM_EVIDENCE_MATRIX.md` "Additional load-bearing claim."
Full claim table: `CLAIM_EVIDENCE_MATRIX.md`.

## 5. ACTUAL SYSTEM ARCHITECTURE

See `ACTUAL_ARCHITECTURE.md` in full. Summary: `main.py` CLI → `MedAgent`
(`agent/graph.py`) → compiled `langgraph.graph.StateGraph` with 6 nodes and one
conditional loop-back edge (`graph.py:100-129`) → `AgentState` TypedDict
(`state.py`, 15 fields) flows through all nodes.

## 6. ENTRY POINTS

`main.py` (git history) is the sole entry point: an `argparse` CLI
(`python main.py "query" [--trace] [--max-iterations N] [--temperature T]
[--no-rag]`), fails fast if `NVIDIA_API_KEY` is unset (main.py:49-58). No web
server, no API, no notebook entry point exists. `evaluation/evaluator.py`'s
`AgentEvaluator` is a secondary, batch-oriented entry point for running the
test suite (`evaluator.py:197-307`), invoked as a library, not via `main.py`
(no `--evaluate` flag was ever added — `PHASE3_STATUS.md`'s own "What Still
Needs Implementation" section lists "Main.py Integration: Add --evaluate flag"
as **not done**).

## 7. AGENT/GRAPH ARCHITECTURE

Genuinely a multi-node LangGraph `StateGraph`, not a thin wrapper — see
`ACTUAL_ARCHITECTURE.md` §2 for the full per-node breakdown (file, purpose,
prompt, model, tools, routing). The routing decision
(`should_continue_research`, `graph.py:26-59`) is a real conditional function
reading `state["needs_more_info"]`/`state["current_step"]`/
`state["max_iterations"]`, wired via `workflow.add_conditional_edges`
(`graph.py:122-129`) — this is LangGraph's actual conditional-routing
primitive, correctly used, not a fake/always-true branch.

## 8. STATE MODEL

`agent.state.AgentState` (`state.py:14-209`), a `TypedDict` with 15 declared
fields (query, research_plan, current_step, max_iterations, use_rag,
tools_to_call, tool_results, tool_call_history, intermediate_thoughts,
confidence_score, needs_more_info, final_report, citations, retrieved_context,
start_time, total_tokens_used, errors, messages). Notably, `use_rag` is
explicitly documented as declared-in-schema rather than an ad hoc key because
"LangGraph's StateGraph filters state to schema-declared keys only — confirmed
directly" (`state.py:75-84`) — a specific, verified detail about LangGraph's
runtime behavior, evidence of real hands-on debugging rather than copied
boilerplate.

## 9. PROMPTS

Six prompt templates in `agent/prompts.py` (445 lines), one per node:
`QUERY_ANALYSIS_PROMPT`, `PLANNING_PROMPT`, `TOOL_QUERY_GENERATION_PROMPT`,
`SYNTHESIS_PROMPT`, `VERIFICATION_PROMPT`, `REPORT_GENERATION_PROMPT`. All but
the last require strict JSON output (enforced by `_parse_llm_json`,
`nodes.py:95-120`, which also strips markdown code fences). All explicitly
instruct anti-hallucination/grounding behavior (e.g. `SYNTHESIS_PROMPT`:
"Ground everything in tool results and retrieved context ... Do NOT add
external knowledge", prompts.py:222; `REPORT_GENERATION_PROMPT`: "Do NOT add
information not found in the tool results or the RETRIEVED CONTEXT",
prompts.py:425). `PLANNING_PROMPT` was specifically tightened
(prompts.py:98-109) to enumerate the exact 3 valid tool names after
hallucinated tool names were observed in evaluation (`RESULTS.md` §3) — a
directly-evidenced case of prompt engineering responding to measured failure.
Every prompt is invoked from a live node call site (`nodes.py`) — none are
orphaned/unused.

## 10. MODELS

Single LLM provider throughout: **NVIDIA NIM**, model
`nvidia/nemotron-3-super-120b-a12b` (`llm_config.py:23`), via
`langchain_nvidia_ai_endpoints.ChatNVIDIA`. Temperatures are per-node and
intentional, not uniform: query_analysis 0.1 (extraction, low variance),
planning 0.3, tool query generation 0.2, synthesis 0.2, verification 0.3,
report generation 0.4 (nodes.py, per-node `get_llm(temperature=...)` calls).
`max_tokens` defaults to 2048 but is explicitly raised to 8192 for
synthesis/report generation nodes after truncation was observed to break JSON
parsing (`nodes.py:771,1041`, with inline rationale). API key configured via
`NVIDIA_API_KEY` env var name only (value not inspected). No structured-output
/ function-calling API is used — JSON is requested by prompt instruction and
parsed manually.

## 11. TOOLS

Three real tool classes, all subclassing `tools.base_tool.BaseTool`
(311 lines, abstract base with caching/retry/logging/standardized
`ToolResult`): `PubMedTool` (NCBI E-utilities, `esearch.fcgi`/`efetch.fcgi`,
XML parsing via `xml.etree.ElementTree`), `ClinicalTrialsTool`
(`clinicaltrials.gov/api/v2/studies`, with `VALID_STATUSES`/`VALID_PHASES`
enums), `ChEMBLTool` (EBI REST API, `target/search`, `molecule`,
`drug_indication` endpoints). No JSON-schema-typed tool definitions are passed
to the LLM (no `bind_tools`) — the LLM is told tool capabilities in prose
(`nodes.py:500-512`) and asked to emit JSON parameters
(`TOOL_QUERY_GENERATION_PROMPT`), which Python then validates by
`if/elif tool_name ==` dispatch (`nodes.py:651-680`). Unknown/hallucinated
tool names are explicitly caught and recorded as failures, not silently
dropped (`nodes.py:603-626`).

## 12. EXTERNAL KNOWLEDGE SOURCES

All three are **actually invoked in the live pipeline** — traced call sites:
`main.py` → `MedAgent.run` → graph → `tool_execution_node` → `tool_instances
= {"pubmed": PubMedTool(), "clinical_trials": ClinicalTrialsTool(), "chembl":
ChEMBLTool()}` (`nodes.py:588-592`) → real `.search_*()` calls
(`nodes.py:651-680`). Rate limiting: per-source, via `utils/rate_limiter.py`'s
token-bucket `@rate_limit` decorator, configured per-tool
(`settings.PUBMED_RATE_LIMIT=3`, `CLINICAL_TRIALS_RATE_LIMIT=10`,
`CHEMBL_RATE_LIMIT=10` req/s, `config/settings.py:31-42`). Retry: via
`utils/retry_handler.py`'s `RetrySession`, `MAX_RETRIES=3` with exponential
backoff (`settings.py:45-56`). Caching: per-tool in-memory dict keyed by
method+sorted-params, TTL-bound (`base_tool.py:84-133`, `CACHE_TTL=3600s`) —
process-local only, not persisted or shared across runs. Normalization/dedup:
ChEMBL results are deduplicated by `chembl_id`
(`_build_chembl_compound_table`, `nodes.py:251-265`); no cross-run dedup
exists for PubMed/ClinicalTrials results. ChEMBL name-backfill
(`_backfill_chembl_names`, `nodes.py:123-200`) is a real, documented data-gap
mitigation (a second API call to fill missing compound names), not
speculative.

## 13. DATA/CORPUS/INDEXES

`data/corpus/abstracts.jsonl`: **9,000** lines (`wc -l`, confirmed), one JSON
object per line with `pmid`/`title`/`abstract` fields (sampled and validated
directly). `data/corpus/abstracts_raw_all.jsonl`: 13,115 lines (pre-filter
pull, superset). `data/index/index_meta.json` (machine-generated):
`embedding_model: "all-MiniLM-L6-v2"`, `embedding_dim: 384`,
`index_type: "IndexFlatIP (cosine via L2-normalized vectors)"`,
`num_abstracts: 9000`, `num_chunks: 22674`, `chunk_size_words: 180`,
`chunk_overlap_words: 30`, `build_time_seconds: 87.4`. `data/index/chunks.jsonl`
independently confirmed at 22,674 lines — matches `index_meta.json` exactly,
and `Retriever.__init__` (`retriever.py:90-94`) asserts `index.ntotal ==
len(chunks)` at load time (a real internal consistency check, not just an
unverified metadata claim). Three additional index variants exist under
`data/index/variants/` (BGE-base embedding model; 256/50 and 384/64 chunk
sizes) — evidence of real hyperparameter experimentation, not a single
untested build. The index is **actually used at retrieval time**: traced from
`synthesis_node` (`nodes.py:794-799`) through `_retrieve_rag_context`
(`nodes.py:340-369`) to `retrieval.retriever.retrieve` (`retriever.py:448-463`),
gated on `state["use_rag"]` (default `True`).

## 14. RETRIEVAL ARCHITECTURE

Hybrid: dense (FAISS `IndexFlatIP` cosine similarity via
`sentence-transformers` encode + L2-normalize, `retriever.py:190-203`) +
sparse (BM25 via `rank_bm25`, `retriever.py:164-171`), fused by **Reciprocal
Rank Fusion** with the standard formula (`_rrf_fuse`, `retriever.py:205-232`,
`k=60`, optional per-list weights), then **cross-encoder reranked**
(`cross-encoder/ms-marco-MiniLM-L-6-v2`, `retriever.py:39,116-151`) over the
top ~30 RRF-fused candidates, then deduplicated by PMID
(`_dedup_rows_by_pmid`, `retriever.py:251-275`) down to k. Constants:
`DENSE_TOP_N=30`, `BM25_TOP_N=30`, `RRF_POOL_SIZE=30`
(`retriever.py:34-37`). `retrieve()`'s default is this full hybrid pipeline
(`retrieve_hybrid_reranked`), a documented, evidence-based decision reversing
an earlier dense-only default after measuring hybrid winning on 2 of 2 later
eval sets (`retriever.py:355-378`, cross-referenced against
`PHASE3_RETRIEVAL_QUALITY_COMPLETE.md`). No reranking threshold/cutoff score
is applied — always returns top-k regardless of absolute relevance.

## 15. HETEROGENEOUS-SOURCE HANDLING

Real, traced example: for a query about a drug target, `tool_execution_node`
can call ChEMBL (compounds), ClinicalTrials.gov (trials), and PubMed
(literature) in one run; `report_generation_node`'s
`_build_chembl_compound_table` (`nodes.py:225-315`) actively cross-references
ChEMBL compounds against ClinicalTrials.gov interventions by name-substring
match to populate a "Matched Trial" column — genuine multi-source synthesis,
not just concatenation. RAG-retrieved PubMed passages are a **fourth**,
distinct source, kept under a separate citation label ("PubMed RAG") from
live PubMed API results ("PubMed") specifically so provenance isn't conflated
(`nodes.py:993-1028`).

## 16. QUERY/NLU PIPELINE

`query_analysis_node` (`nodes.py:387-461`) extracts drug targets, diseases,
compounds, a 6-way query-type classification, and constraints, entirely via
LLM prompting with a low temperature (0.1) for consistency
(`QUERY_ANALYSIS_PROMPT`, `prompts.py:18-58`). No separate NER model, no
decomposition into sub-queries beyond this single-pass extraction, no query
rewriting beyond per-tool parameter generation
(`TOOL_QUERY_GENERATION_PROMPT`). This is "the LLM does it via a structured
prompt," a real but modest mechanism — not a dedicated NLU subsystem.

## 17. ANSWER GENERATION

`report_generation_node` (`nodes.py:956-1111`) assembles: (a) a citations list
built in Python from real tool/RAG data, (b) a deterministically-built ChEMBL
compound table (Python, not LLM), (c) an LLM call
(`REPORT_GENERATION_PROMPT`, temperature 0.4, `max_tokens=8192`) for narrative
sections. Context/token budgeting: `synthesis_node` truncates each tool's
results to the first 10 (`nodes.py:777-778`); `report_generation_node` passes
the full `tool_results` and `retrieved_context` (no truncation observed there
beyond citations capped at 20 per tool, `nodes.py:992`). No token-count-aware
dynamic truncation exists — truncation is fixed-size, not budget-computed.

## 18. CITATION/GROUNDING

Citations are assembled mechanically from real data
(PubMed: pmid/title/authors; ClinicalTrials: nct_id/title/status; ChEMBL:
chembl_id/name/max_phase; RAG: pmid/title/url — `nodes.py:987-1028`), not
LLM-invented. Grounding is enforced two ways: (1) prompt instruction (both
`SYNTHESIS_PROMPT` and `REPORT_GENERATION_PROMPT` explicitly forbid
non-grounded claims) and (2) removing LLM discretion entirely for the
compound table. **Citation hallucination can still happen** in narrative
prose: nothing checks that a specific inline citation marker actually
supports the sentence it's attached to — this is prompt-enforced only.
Citation-correctness evaluation exists only via the hallucination-judge
mechanism (§19/§26), which checks *claim* grounding against tool
results/retrieved context, not citation-to-claim linkage specifically. No
"citation faithfulness" metric of the kind implied by the ~0.91 target claim
exists (`CLAIM_EVIDENCE_MATRIX.md` #11).

## 19. VERIFICATION/REFINEMENT

`verification_node` (`nodes.py:852-949`) is model-based (LLM scores
query_coverage/evidence_quality/completeness/confidence per
`VERIFICATION_PROMPT`, `prompts.py:269-344`), not deterministic. It sets
`needs_more_info`, which — via `should_continue_research`
(`graph.py:26-59`) — is the sole determinant of whether the graph loops back
to `tool_execution` or proceeds to `report_generation`. Loop bound: hard-capped
at `state["max_iterations"]` (CLI default 10, `main.py:27-31`), with
`recursion_limit` sized explicitly at `max_iterations*3+10`
(`graph.py:244`) to avoid LangGraph's own default recursion ceiling being hit
first. There is no separate "Refiner" node — refinement is entirely this
loop-back, which re-executes `tool_execution → synthesis → verification`
using an updated `tools_to_call` if the verifier suggested new tools/queries
(`nodes.py:929-931`).

## 20. ERROR/RETRY/FALLBACK BEHAVIOR

Layered: (1) per-LLM-call retry with fresh-client construction on
timeout/429/503 inside `_RateLimitedChatNVIDIA.invoke`
(`llm_config.py:209-284`, up to 3 attempts, exponential backoff via
`utils/retry_handler.py::calculate_backoff`); (2) per-tool HTTP retry via
`RetrySession` (`base_tool.py:73-77`, `MAX_RETRIES=3`); (3) per-node
try/except in every one of the 6 graph nodes, each falling back to a degraded
default rather than crashing the whole run (e.g. `query_analysis_node` falls
back to a minimal `general_research` classification, `nodes.py:454-459`;
`report_generation_node` falls back to a minimal error report,
`nodes.py:1098-1109`); (4) `MedAgent.run`'s own outer try/except
(`graph.py:245-267`) as a last-resort catch-all that still returns a valid
(if error-flagged) state rather than raising to the caller; (5) a per-case
wall-clock cap in the evaluation harness (`CASE_WALL_CLOCK_TIMEOUT_SECONDS=1200`,
`evaluator.py:42`) as a final safety net above the per-call timeout, added
specifically after a real 90-minute hang incident
(`EVAL_HANG_FIX_COMPLETE.md`, cross-referenced in code comments,
`llm_config.py:37-44`). Documented real failure modes actually observed and
handled: 503, 429, 502 (ClinicalTrials.gov), LLM call timing out on all 3
attempts, synthesis-node JSON parse failure (`RESULTS.md` "Failure
characterization").

## 21. OBSERVABILITY

`utils/logger.py` (178 lines) provides structured JSON-line logging
(`log_tool_call` helper) and per-dispatch LLM timing logs added specifically
to diagnose the 429/concurrency incident (`llm_config.py:229-231,238-241,265`).
**However**, `logs/medagent.log` as it currently exists on disk (WORKING TREE,
19,159 lines) is dominated by synthetic unit-test log lines (e.g. `"Tool call
succeeded: nonexistent query xyz123"`, `"Tool call succeeded: test"`,
timestamped in a tight sub-millisecond cluster) — this is evidence of
`tests/test_pubmed.py`-style unit tests exercising `base_tool.py`'s logging
path, **not** a trace of real production agent runs against live APIs. No
end-to-end request tracing/correlation ID spans nodes; observability is
per-component (per-tool-call, per-LLM-call), not a unified trace per query.

## 22. PERFORMANCE

Measured, not estimated: average per-case latency 177.5s (fresh, Phase 2) /
209.4s (all 60) / ~198s (Phase 3, both arms) — `RESULTS.md` §4,
`RESULTS_RAG_COMPARISON.md` §3. RAG retrieval itself is fast (single-digit
seconds per the project's own timing notes, cross-referenced in
`nodes.py:72-75`) — the dominant cost is sequential LLM calls (7-15+ per run).
RAG adds ~35% more tokens but no measurable latency delta (198.1s vs 198.2s,
`RESULTS_RAG_COMPARISON.md` §3) since embedding/FAISS retrieval is local and
fast relative to LLM round-trips.

## 23. CONCURRENCY

Two real, independently-evidenced concurrency features: (1) case-level
parallelism in the evaluation harness via `ThreadPoolExecutor`
(`evaluator.py:340-393`, `concurrency` param), validated for thread-safety
(`PHASE3_CONCURRENCY_VALIDATION.md`) and shown to trigger a real Apple
Metal/MPS crash under concurrent `SentenceTransformer.encode()` calls, fixed
with an explicit `threading.Lock()` around the RAG retrieval call site
(`nodes.py:76,354`, not inside `retrieval/` itself — a call-site fix, not a
retrieval-quality change); (2) per-thread LLM-call-count attribution
(`llm_config.py:127-179`) to correctly measure per-case usage when multiple
cases run concurrently, with an automatic cross-check (global counter sum vs.
per-case sum, `evaluator.py:275-295`) that would flag a broken attribution
mechanism rather than silently trusting it. No async/await is used anywhere —
all concurrency is thread-based.

## 24. CACHING

Per-tool, in-memory, process-local only: `BaseTool._get_from_cache`/
`_save_to_cache` (`base_tool.py:100-133`), keyed by method+sorted-params,
TTL-bound (`CACHE_TTL=3600s`, `ENABLE_CACHE=True` by default,
`settings.py:78-86`). Not persisted to disk, not shared across processes/runs,
not applied to LLM calls or RAG retrieval (`retrieve()` re-runs FAISS/BM25 on
every call with no result cache).

## 25. TESTING

**Currently, zero tests are collectible** in the working tree
(`venv/bin/python -m pytest tests/ -q` → `"no tests ran in 0.00s"`, verified
directly — `tests/` contains only `__pycache__`, no `.py` files). From git
history: `tests/test_chembl.py` (315 lines), `test_clinical_trials.py` (307),
`test_nodes.py` (187), `test_pubmed.py` (220) — 1,029 lines of substantive
unit tests (not stubs — `.pyc` filenames confirm they compiled under
`pytest-7.4.3`, consistent with real execution history). `RESULTS.md` §6
self-reports "pytest tests/: 40/42 pass — same 2 pre-existing rate-limit-test
failures documented since PHASE1_COMPLETE.md," but this audit **could not
independently reproduce this number** — the working tree has no runnable
source, and re-executing against the git-history snapshot was outside this
audit's read-only, working-tree-only scope. Classified **UNVERIFIED BY THIS
AUDIT** (tier-4 evidence, self-reported, not independently confirmed here).

## 26. EVALUATION ARCHITECTURE

`evaluation/evaluator.py` (`AgentEvaluator`, 877 lines): runs `MedAgent` on
`evaluation/test_cases.py`'s 60 hardcoded test cases (836 lines,
`grep -c '"id":'` confirms 60), computes metrics via
`evaluation/metrics.py`'s `AgentMetrics` (470 lines, 8 static methods:
`task_success_rate`, `tool_precision`, `redundancy_rate`,
`self_correction_rate`, `citation_coverage`, `avg_latency`, `avg_confidence`,
`hallucination_rate`), runs a separate LLM-judge hallucination check
(`evaluation/hallucination_judge.py`, 301 lines), and persists results both
incrementally per-case (`experiments/results/incremental_*.jsonl`, resumable)
and as an aggregate JSON report (`experiments/results/evaluation_*.json`, 10
on disk). Ground truth: `test_cases.py`'s hand-authored `expected_tools`/
`expected_drugs`/`min_results` fields — author-curated, not externally sourced
or independently validated. Held-out vs. tuning-set status: not distinguished
anywhere — the same 60 cases appear to be used for both any informal tuning
during development and the reported results, a genuine methodological gap
(not flagged by the project's own docs).

## 27. CURRENT VERIFIED METRICS

| Metric | Value | Source (machine-generated) |
|---|---|---|
| Task success rate | 37.9% (fresh n=29) / 18.3% (all 60) | `experiments/results/evaluation_20260909_193811.json` via `RESULTS.md` §4 |
| Tool precision | 85.3% (fresh) / 76.8% (all 60) | same |
| Redundancy rate | 12.9% (fresh) / 18.2% (all 60) | same |
| Self-correction rate | 93.1% (fresh) / 91.7% (all 60) | same |
| Citation coverage | 77.1% (fresh) / 68.4% (all 60) | same |
| Avg confidence | 0.465 (fresh) / 0.225 (all 60) | same |
| Avg latency | 177.5s (fresh) / 209.4s (all 60) | same |
| Hallucination rate (Phase 2) | 42.9% (27/63 claims, n=6 judged/60) | same |
| Recall@10, hybrid, survey set | 0.4832 mean | `retrieval/eval_results_hybrid.json` |
| Recall@10, hybrid, strict set | 0.4016 mean | `PHASE3_RETRIEVAL_QUALITY_COMPLETE.md` §10.10, cross-checked against `retrieval/eval_results_strict_hybrid.json` |
| Recall@10, hybrid, grounding set | 0.6638 mean (oracle ceiling 0.9492) | `PHASE3_RETRIEVAL_QUALITY_COMPLETE.md` §11.5, cross-checked against `retrieval/eval_results_grounding_hybrid.json` |
| Task success, baseline vs RAG | 36.7% vs 63.3% (n=30 each) | `RESULTS_RAG_COMPARISON.md` §3 |
| Hallucination, baseline vs RAG | 18.4% (n=10 judged) vs 5.7% (n=2 judged, not defensible) | same |
| Indexed abstracts / chunks | 9,000 / 22,674 | `data/index/index_meta.json`, cross-checked `wc -l` |

## 28. UNVERIFIED OR CONTRADICTED CLAIMS

Full table: `CLAIM_EVIDENCE_MATRIX.md`. Every one of the 12 target claims is
CONTRADICTED or UNSUPPORTED except claim #2 (PubMed/ClinicalTrials/ChEMBL as
sources — VERIFIED) and claim #4 (FAISS retrieval — VERIFIED); claim #1
(6-node workflow) is PARTIALLY VERIFIED (real, but different node names/roles
than documented).

## 29. CURRENT PROJECT CLAIM MATRIX

| Claim source | Document | Actual (code/artifact) | Status |
|---|---|---|---|
| Resume-style bullets (96%/98%/5K+/0.92/0.88/~5%/35%/0.91) | implied by target list, contradicted in `RESULTS.md`/`RESULTS_RAG_COMPARISON.md` | See §27 | See `CLAIM_EVIDENCE_MATRIX.md` |
| "6-stage agentic workflow" | project narrative | `agent/graph.py` 6-node `StateGraph`, different names/roles | PARTIALLY VERIFIED |
| `AUDIT_CURRENT_STATE.md` ("no RAG exists", "2/3 tools broken") | prior self-audit, 2026-09-08 | Both fixed by `14a59b9`: real RAG pipeline, correct tool dispatch | STALE/CONTRADICTED by later commits |
| `PHASE3_STATUS.md` "hyperparameter tuner", "--evaluate flag" | phase status doc | Neither exists in `14a59b9` (`experiments/tuner.py` absent, `main.py` has no `--evaluate` flag) | UNBUILT, self-acknowledged in the same doc's "What Still Needs Implementation" section |

## 30. JD CAPABILITY MATRIX

Full table: `JD_CAPABILITY_MATRIX.md`. Summary: 7 DIRECTLY DEMONSTRATED, 10
PARTIALLY DEMONSTRATED, 0 NOT DEMONSTRATED, out of 19 assessed capabilities.

## 31. ENGINEERING MATURITY

| Dimension | Rating | Basis |
|---|---|---|
| Architecture | **ADEQUATE** | Real, correctly-used LangGraph state machine with genuine conditional routing (§7); no native tool-calling API, single-provider LLM lock-in. |
| Correctness | **WEAK** | Task success rate 18-38% measured; hallucinated tool selection persists after mitigation; no per-claim citation verification. |
| Reliability | **ADEQUATE** | Multiple layers of real, evidenced error handling (§20) and two real production-shaped incidents found and fixed (hang, Metal/MPS crash) — genuine reliability *engineering*, even though end-task reliability is weak. |
| Testability | **WEAK (currently), historically ADEQUATE** | Working tree currently has zero runnable tests (§25); git history shows 1,029 lines of real unit tests and a self-reported 40/42 pass rate this audit could not independently confirm. |
| Reproducibility | **WEAK** | No CI; single-machine, OS-specific bugs found (Metal/MPS); this audit could not re-run anything (§35). |
| Observability | **ADEQUATE** | Real structured logging and per-dispatch LLM timing (§21), but the present `logs/medagent.log` mostly reflects unit-test noise, not production traces. |
| Performance | **WEAK** | 177-210s average per-case latency; not viable for interactive use as shipped. |
| Security | **ADEQUATE** | See §33 — no obvious unsafe patterns found in the modules read; secrets handling via `.env`/env vars is conventional. |
| Evaluation rigor | **STRONG (methodology) / WEAK (statistical power)** | Genuinely rigorous, honestly-reported methodology (documented biases, sample-size caveats, judge-reliability caveats) but small sample sizes throughout (§26). |
| Documentation accuracy | **ADEQUATE, with one stale artifact** | Root docs are unusually self-correcting; `AUDIT_CURRENT_STATE.md` is stale (§4, §29). |

## 32. DEAD CODE/TECHNICAL DEBT

See `REPOSITORY_INVENTORY.md` §C for the full list. Summary: root-level
`test_phase1.py`/`test_phase2.py`/`examples/test_*.py` duplicate
`tests/test_*.py`; `retrieval/hyde.py`/`query_expansion.py`/
`experiment_grounding_optimization.py` are one-off experiments explicitly
**not** shipped in the production `retrieve()` path (`retriever.py:355-378`
confirms none beat the shipped baseline); `evaluation/reconstruct_from_logs.py`
is a one-time incident-recovery script; `retrieval/eval_set_strict_buggy_v1.json`
is a superseded, explicitly-named-buggy artifact kept for the record.
`tenacity`/`ratelimit` are pinned in `requirements.txt` but the actual
rate-limiting/retry logic is hand-rolled in `utils/`, suggesting these two
dependencies may be unused dead weight (not exhaustively verified against
every import in every file).

## 33. SECURITY/SECRET FINDINGS

`.env` (WORKING TREE) defines `NVIDIA_API_KEY`, `LOG_LEVEL`, `LOG_FILE` — key
**names only** inspected, values never read or printed, per instructions.
`.env.example` exists in git history as the documented template (standard
practice). No hardcoded API keys, tokens, or credentials were found in any
`.py` file read during this audit (`config/settings.py`,
`config/llm_config.py` both load via `os.getenv`/`pydantic_settings`
`env_file=".env"`, `settings.py:112`). No `eval()`/`exec()`/unsafe
`pickle.loads()` of untrusted external data was found in the modules read;
`retrieval/retriever.py` does `pickle.load()` on `bm25.pkl`
(`retriever.py:161`), which is a locally-generated build artifact, not
untrusted external input — low severity as used, but worth noting as a
pattern if `bm25.pkl` were ever sourced externally. No subprocess/shell
invocation was found in any module read. Severity assessment: **LOW** — no
credential leakage or unsafe deserialization-of-untrusted-input pattern found
in the code actually reviewed (not every line of all 9,847 LOC was read
character-by-character; this is a sampled, targeted review, not an exhaustive
static-analysis pass).

## 34. BIOMEDICAL-SAFETY BOUNDARY

No disclaimer text, medical-advice guardrail, or "not for clinical use"
boundary was found in any prompt (`agent/prompts.py`) or in `main.py`'s
output. The system positions itself (per `README.md`/`PROJECT_SUMMARY.md`
naming and prompt framing — "autonomous drug discovery research assistant,"
`prompts.py:18,65,134,206,269,351`) as a **research assistant**, and prompts
consistently instruct grounding in retrieved literature/trial/compound data
rather than general medical advice — but there is no explicit output-level
disclaimer or safety filter distinguishing "research summary" from "clinical
recommendation" for an end reader. This is a real gap for any claim of
"safe for clinical decision support" positioning (which the project does not
appear to claim, but also does not explicitly disclaim).

## 35. REPRODUCIBILITY

**Not reproduced by this audit.** Two independent blockers: (1) the working
tree currently has no runnable Python source at all (§1/§2) — nothing could
be executed as-is without first materializing source files outside the two
permitted audit directories, which this audit's scope disallows; (2) even
against the git-history snapshot, running a live evaluation would require a
working `NVIDIA_API_KEY` and would incur real, uncontrolled-cost API calls to
NVIDIA NIM (and PubMed/ClinicalTrials.gov/ChEMBL) — per instructions, this was
not attempted since the key's validity/cost exposure could not be safely
assessed without first using it. All metrics in this audit (§27) are traced
to already-existing, machine-generated result artifacts on disk, not
independently regenerated. `pytest` was attempted (safe, read-only) and
confirmed **0 tests collectible** in the current working tree (§25) — this
one result **was** independently reproduced, and it is a negative result.

## 36. PRESERVE CANDIDATES

| Component | Evidence for preserving |
|---|---|
| `agent/graph.py` + `agent/nodes.py` (6-node LangGraph orchestration) | Real, correctly-used conditional routing; genuine self-reflection loop; extensive inline rationale documenting real debugging (state-schema filtering, recursion limits). |
| `retrieval/retriever.py` (hybrid RAG pipeline) | Measured, iterated-on (3 index variants, HyDE/weighted-RRF experiments tried and honestly rejected), internally self-consistent (`index.ntotal == len(chunks)` assertion). |
| `tools/*.py` (PubMed/ClinicalTrials/ChEMBL connectors) | Correctly wired, real endpoints, real data-gap handling (ChEMBL name backfill), shared clean `BaseTool` abstraction. |
| `config/llm_config.py`'s `_RateLimitedChatNVIDIA` wrapper | Directly traceable to a real, well-documented production incident; genuinely more robust than a bare LLM client wrapper. |
| `evaluation/evaluator.py`'s incremental-persistence/resume mechanism | Directly traceable to the same incident; a real, non-trivial reliability feature (thread-safe append, resumable by run_id). |

## 37. REWRITE CANDIDATES

| Component | Evidence for rewriting |
|---|---|
| `evaluation/hallucination_judge.py` | Self-documented ~39% success rate across all validation attempts (max_tokens increase, model swap) — the current single-model, same-family-judge approach has been tried and shown not to work reliably; needs a different judge architecture (independent model, shorter/simpler extraction task, or removed as a headline metric until it does). |
| Tool dispatch mechanism (`nodes.py:651-680`'s `if/elif` + prose-described tool capabilities) | Root cause of the persistent hallucinated-tool-name problem (9 distinct hallucinated names, 12+ attempts even after prompt tightening); a schema-constrained/native tool-calling API would eliminate this class of failure structurally rather than by prompt-tightening. |
| Root-level narrative docs, specifically `AUDIT_CURRENT_STATE.md` | Stale relative to `14a59b9`; should be superseded/corrected rather than left as an uncorrected historical artifact readers might trust. |
| `main.py` (as a "production entry point") | Single synchronous CLI, no serving layer, no `--evaluate` integration despite being planned (`PHASE3_STATUS.md`) — fine as a dev tool, not a preserve-as-is production interface. |

## 38. UNDERSOLD CAPABILITIES

- The **honesty of the evaluation methodology itself** (documented biases,
  judge failure rates, sample-size caveats, a "Bug 2" measurement-artifact
  writeup that reversed an apparent RAG regression finding into a correct
  positive one, `RESULTS_RAG_COMPARISON.md` §2) is a genuinely strong,
  unusual engineering practice that none of the target claims (which focus on
  headline percentages) reflect or reward.
- The **cross-source compound/trial matching**
  (`_build_chembl_compound_table`, `nodes.py:225-315`) and the deliberate
  removal of LLM discretion over which compounds appear in the report is a
  real, well-reasoned grounding mechanism not captured by any of the
  evaluated headline metrics.
- Real, specific systems debugging (Apple Metal/MPS thread-safety,
  LangGraph's undeclared-state-key-filtering behavior, `ChatNVIDIA`'s
  `timeout` parameter not bounding a stalled connection) — this is senior-level
  troubleshooting evidence that a resume bullet list of percentages doesn't
  surface at all.

## 39. WHAT IS LEFT TO BUILD

- A working tree with source code restored (currently blocked mid-rebase —
  out of this audit's scope to fix, see `INITIAL_STATE.md`).
- A tool-calling mechanism resistant to hallucinated tool names (schema/
  function-calling based).
- A reliable hallucination/grounding judge (current one fails on the
  majority of real cases).
- Any deployment/serving layer (API, container, CI) — none exists.
- A retrieval-quality push toward the eval sets' own oracle ceilings (current
  hybrid Recall@10 0.66 vs. 0.95 ceiling on the grounding set) or an
  acknowledgment that 0.92 was never a realistic target for this corpus/eval
  design.
- Correction or removal of the stale `AUDIT_CURRENT_STATE.md`.
- An `--evaluate` CLI integration and hyperparameter tuner, both explicitly
  planned and explicitly not built (`PHASE3_STATUS.md`).

## 40. KEY LIMITATIONS

- This audit could not execute any code (working tree has none; live-API
  execution against history was out of safe scope) — all findings are static/
  artifact-based, not independently re-measured.
- Not every one of the 9,847 lines of core module code was read
  line-by-line; security/dead-code findings are from targeted sampling, not
  exhaustive static analysis.
- The self-reported 40/42 pytest pass rate and the specific mechanics of
  several one-off experimental scripts (`hyde.py`, `query_expansion.py`,
  `verify.py`) were not independently re-verified beyond confirming their
  existence and non-use in the production path.

## 41. HIGH-IMPACT QUESTIONS FOR THE NEXT DESIGN PHASE

1. Is the in-progress interactive rebase intended to be completed, and onto
   what final state — is `14a59b9`'s feature set (working RAG, fixed tool
   dispatch, 60-case eval) the intended baseline to rebuild the working tree
   from, or is some different history being constructed?
2. Should `hallucination_judge.py` be replaced with a structurally different
   approach (independent judge model, human spot-checks, or a narrower
   automatic check) given its ~39% measured reliability across all attempts
   so far?
3. Is native LLM tool-calling (function-calling / `bind_tools`) worth
   adopting to eliminate the hallucinated-tool-name failure class
   structurally, replacing the current JSON-emit/Python-dispatch pattern?
4. What is the real target Recall@10 for this corpus/eval-set design, given
   the grounding set's own oracle ceiling is 0.9492, not 1.0 — is "0.92" an
   achievable target at all with this indexing approach, or does it require a
   fundamentally different retrieval/eval-set design?
5. Should `AUDIT_CURRENT_STATE.md` and the resume-bullet language it was
   responding to be retired/corrected now that later commits fixed the two
   specific bugs it flagged, to avoid a future reader trusting stale
   conclusions?

## 42. AUDIT VERDICT

AUDIT COMPLETE - READY FOR DESIGN
