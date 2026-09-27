# ACTUAL_ARCHITECTURE.md

All citations are to the git-history snapshot at commit `14a59b9` (see
`INITIAL_STATE.md` §1) unless marked WORKING TREE.

## 1. Documented architecture (per root docs / *_COMPLETE.md narrative)

The `*_COMPLETE.md`/`RESULTS*.md`/`docs/architecture.md` files describe a
"six-stage agentic workflow" — Planner, Retriever, Tool Executor, Reasoner,
Verifier, Refiner (in resume-bullet phrasing) — over PubMed/ClinicalTrials.gov/
ChEMBL, with a FAISS-backed RAG layer, hybrid retrieval, and an evaluation
harness reporting task-completion/tool-reliability/hallucination/Recall/nDCG/
citation-faithfulness numbers.

## 2. Actual architecture (from code)

**Entry point**: `main.py` — an `argparse` CLI (`python main.py "query" [--trace]
[--max-iterations N] [--temperature T] [--no-rag]`). Checks
`settings.NVIDIA_API_KEY` is set before doing anything else (main.py:49-58),
then imports and drives `agent.graph.MedAgent`.

**Orchestration**: `agent/graph.py`'s `build_agent_graph()` builds a real
`langgraph.graph.StateGraph(AgentState)` with **six actual `add_node` calls**
(graph.py:100-105):

```
query_analysis -> planning -> tool_execution -> synthesis -> verification
                                    ^                              |
                                    |__________ continue __________|
                                                      \_ report -> report_generation -> END
```

This is a genuine conditional-routing state machine, not a thin linear wrapper:
`workflow.add_conditional_edges("verification", should_continue_research, {...})`
(graph.py:122-129) loops `verification -> tool_execution` while
`needs_more_info and current_step < max_iterations` (graph.py:48-59), and
`recursion_limit` is explicitly sized as `max_iterations*3 + 10` to accommodate
the loop (graph.py:244).

**State**: `agent.state.AgentState` (`TypedDict`, state.py:14-209) — 15 declared
fields across INPUT/PLANNING/TOOL USAGE/REASONING/OUTPUT/METADATA/LangChain-
compatibility groups, including `use_rag: bool` (state.py:75-84, deliberately
declared in the schema rather than left as an ad hoc key, with an inline note
explaining that LangGraph silently drops undeclared state keys — a real,
non-decorative design detail).

**Nodes** (`agent/nodes.py`, 1,111 lines) — six functions, each: builds a
prompt from `agent/prompts.py`, calls `config.llm_config.get_llm(...)`, parses
JSON via `_parse_llm_json` (nodes.py:95-120), updates `state`, and appends to
`state["intermediate_thoughts"]`/`state["errors"]` on failure (every node has a
try/except with a graceful degraded fallback, not a bare crash):
1. `query_analysis_node` (nodes.py:387-461) — extracts drug targets/diseases/
   compounds/query_type/constraints via `QUERY_ANALYSIS_PROMPT`.
2. `planning_node` (nodes.py:468-556) — selects/orders `tools_to_call` from
   {pubmed, clinical_trials, chembl} via `PLANNING_PROMPT`.
3. `tool_execution_node` (nodes.py:563-734) — for each planned tool, an LLM
   call generates tool-specific parameters (`TOOL_QUERY_GENERATION_PROMPT`),
   then **dispatches to the real tool method** (`tool.search_pubmed(...)`,
   `tool.search_trials(condition=..., intervention=..., status=..., phase=...)`,
   `tool.search_by_target(...)`/`tool.search_by_indication(...)`) — nodes.py:651-680.
   Also handles Nemotron hallucinating a nonexistent tool name (nodes.py:603-626,
   explicitly recorded as a failed `tool_call_history` entry rather than silently
   dropped) and backfills missing ChEMBL compound names via a second API call
   (`_backfill_chembl_names`, nodes.py:123-200).
4. `synthesis_node` (nodes.py:741-845) — cross-references `tool_results` across
   tools **and** RAG-retrieved passages (`_retrieve_rag_context`, nodes.py:340-369,
   gated on `state["use_rag"]`) via `SYNTHESIS_PROMPT`.
5. `verification_node` (nodes.py:852-949) — self-reflection: LLM scores query
   coverage / evidence quality / completeness / confidence and returns
   `needs_more_research` (bool), which drives the conditional edge above. This
   is the actual mechanism behind any "autonomous"/"self-correcting" claim.
6. `report_generation_node` (nodes.py:956-1111) — builds a citations list from
   both live tool results and RAG-retrieved passages (kept under distinct
   labels `"PubMed"` vs `"PubMed RAG"`, nodes.py:993-1028), deterministically
   builds the ChEMBL compound table in Python — **not** left to the LLM
   (`_build_chembl_compound_table`, nodes.py:225-315, with an explicit
   docstring rationale: "which compounds appear in the final report is
   decided by real tool data, not by the report-writing LLM's own
   (unverifiable) selection") — then calls the LLM for narrative prose and
   splices the deterministic table into a `<<COMPOUND_TABLE>>` placeholder
   (nodes.py:1064-1078).

**`MedAgent` class** (`agent/graph.py:142-429`) is the public interface:
`run(query)` builds initial state, invokes the compiled graph, catches any
exception and returns a degraded state with the error recorded rather than
raising (graph.py:245-267). Also exposes `get_reasoning_trace`,
`get_tool_usage_stats`, `print_reasoning_trace`, `save_report`, `get_citations`.

## 3. LLM layer

`config/llm_config.py` wraps `langchain_nvidia_ai_endpoints.ChatNVIDIA`
(`nvidia/nemotron-3-super-120b-a12b`, llm_config.py:23) in a custom
`_RateLimitedChatNVIDIA` class (llm_config.py:181-287) that on every `.invoke()`:
throttles to 35 RPM via a token bucket (`utils/rate_limiter.py`), enforces a
**hard 90-second wall-clock timeout** on a daemon thread (not
`ThreadPoolExecutor`, with an explicit rationale about atexit thread-joins —
llm_config.py:79-123), retries up to 3 attempts with a **freshly-constructed
client** on timeout or a detected 429/503 (matched by substring against the
exception text, since the underlying library has no typed exception for this
— llm_config.py:61-71), and tracks both a global and a thread-local call
counter (llm_config.py:124-179) used by the evaluation harness for accurate
per-case LLM-call attribution under concurrency. This is materially more
engineering than a bare `llm.invoke()` wrapper and is traceable to a specific,
documented incident (`EVAL_HANG_FIX_COMPLETE.md`, cross-referenced directly in
code comments at llm_config.py:37-44).

## 4. Documented vs. actual — key deltas

| Documented claim | Actual, from code/artifacts |
|---|---|
| "Planner, Retriever, Tool Executor, Reasoner, Verifier, Refiner" (6 named roles) | Actual node names are `query_analysis, planning, tool_execution, synthesis, verification, report_generation` — 6 nodes, real, but the RAG *retriever* is not a graph node; it's a function call (`_retrieve_rag_context`) invoked from inside `synthesis_node`, and there is no distinct "Refiner" node — refinement is the `verification -> tool_execution` loop-back, not a separate stage. |
| "GraphQL"/"React" frontend (per `AUDIT_CURRENT_STATE.md`'s own audit of a still-earlier repo state) | No web/GraphQL/React code exists anywhere in git history at `14a59b9`; `main.py` is the only entry point, a synchronous CLI. |
| Tool-calling via native LLM function-calling API | Not used. The LLM emits JSON (`TOOL_QUERY_GENERATION_PROMPT`, prompts.py:134-199) which Python then parses and dispatches by `if/elif tool_name ==` (nodes.py:651-680) — an LLM-emits-JSON-then-Python-dispatches pattern, not `bind_tools`/function-calling. |

## 5. Data flow for one query (traced from code)

`main.py` → `MedAgent.run(query)` → `create_initial_state` → graph.invoke:
1. `query_analysis` (1 LLM call) sets `research_plan` (query analysis JSON).
2. `planning` (1 LLM call) sets `tools_to_call`.
3. `tool_execution` (1 LLM call per planned tool + 1 real HTTP call per tool
   [+ 0-N extra ChEMBL backfill HTTP calls]) sets `tool_results`,
   `tool_call_history`.
4. `synthesis` (1 LLM call + 1 local embedding/FAISS/BM25/cross-encoder call
   if `use_rag`) sets `retrieved_context`, updates `research_plan` with a
   `synthesis` sub-object.
5. `verification` (1 LLM call) sets `needs_more_info`; if true and iterations
   remain, loop to step 3; else continue.
6. `report_generation` (1 LLM call) builds `citations`, deterministic compound
   table, and `final_report` (Markdown).

A single simple query with `use_rag=True` and no self-reflection loop is
therefore **≥5 LLM calls + ≥1-3 real external HTTP calls + 1 local
embedding/retrieval call**, matching the `RESULTS.md`-reported observation of
"7-15+ sequential LLM calls" per run (`config/llm_config.py:26-27` comment) and
the measured **356 total LLM calls across 29 fresh Phase-2 eval cases** (~12
calls/case average, `RESULTS.md` §5).

## 6. Dependencies (`requirements.txt`, git history)

```
langchain==0.3.0, langchain-nvidia-ai-endpoints==0.3.19, langgraph==0.2.28,
langsmith==0.1.129, langchain-core==0.3.51, requests==2.31.0,
python-dotenv==1.0.0, pydantic==2.9.0, pydantic-settings==2.1.0,
pytest==7.4.3, aiohttp==3.9.1, tenacity==8.2.3, ratelimit==2.2.1,
pandas==2.1.4, tabulate==0.9.0
sentence-transformers==6.0.1, faiss-cpu==1.15.0, rank_bm25==0.2.2, numpy<2
```
All versions pinned. `aiohttp`/`tenacity`/`ratelimit` are declared but the
actual rate-limiting/retry implementations in `utils/rate_limiter.py` and
`utils/retry_handler.py` are hand-rolled (token bucket, custom backoff), not
built on `tenacity`/`ratelimit` — these two dependencies appear to be unused
by the modules actually imported at runtime (not independently verified
against every file; flagged as a likely-dead-dependency candidate in
`AUDIT_REPORT.md` §32). **This `requirements.txt` is not present in the
current working tree at all** (WORKING TREE has zero requirements files) —
see `INITIAL_STATE.md` §3.
