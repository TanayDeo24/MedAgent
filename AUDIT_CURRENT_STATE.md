# Audit: Current State of "MedAgent" / "Multi-Agent Drug Discovery Gen AI Platform" / "TraceGuard"

**Audit date:** 2026-09-08
**Auditor note:** This directory is **not a git repository** (`git status` fails — no `.git`). There is no commit history available at all, so all statements about "history" below are inferred from file content (READMEs, status docs) rather than `git log`. The project internally calls itself **MedAgent**; no file in the repo contains the strings "TraceGuard", "GraphQL", "React", "FAISS", or "hallucination rate" as a measured/produced artifact (see grep results in §4/§5).

---

## 1. Repo Overview

### Directory tree (full, minus `.pytest_cache`/`venv`)

```
.
├── .env.example
├── .gitignore
├── PHASE3_STATUS.md
├── PROJECT_SUMMARY.md
├── README.md
├── agent/
│   ├── __init__.py
│   ├── graph.py            # LangGraph StateGraph wiring (6 nodes)
│   ├── nodes.py            # The 6 node implementations
│   ├── prompts.py          # Prompt templates for each node
│   └── state.py            # AgentState TypedDict + factory
├── assets/
│   └── sys_architecture.png
├── config/
│   ├── __init__.py
│   ├── llm_config.py       # Gemini LLM factory (get_llm)
│   └── settings.py         # pydantic-settings config
├── docs/
│   ├── api_documentation.md
│   ├── architecture.md
│   ├── phase1_architecture.md
│   ├── phase2_architecture.md
│   └── tool_specifications.md
├── evaluation/
│   ├── __init__.py
│   ├── evaluator.py        # AgentEvaluator — runs agent on test cases
│   ├── metrics.py          # AgentMetrics — 8 static metric functions
│   └── test_cases.py       # 10 hardcoded test cases
├── examples/
│   ├── demo_agent.py
│   ├── test_chembl.py
│   ├── test_clinical_trials.py
│   └── test_pubmed.py
├── logs/
│   └── medagent.log        # JSON-line log, only contains this session's local pytest run
├── requirements.txt
├── setup.py
├── setup.sh
├── test_phase1.py
├── test_phase2.py
├── tests/
│   ├── __init__.py
│   ├── test_chembl.py
│   ├── test_clinical_trials.py
│   └── test_pubmed.py
├── tools/
│   ├── __init__.py
│   ├── base_tool.py        # Abstract BaseTool + ToolResult dataclass
│   ├── chembl_tool.py       # ChEMBL REST wrapper
│   ├── clinical_trials_tool.py  # ClinicalTrials.gov REST wrapper
│   └── pubmed_tool.py       # PubMed E-utilities wrapper
├── utils/
│   ├── __init__.py
│   ├── logger.py
│   ├── rate_limiter.py
│   └── retry_handler.py
└── validate.py
```

**No** `frontend/`, `client/`, `web/`, `ui/`, `graphql/`, `api/` (GraphQL-server sense), `faiss/`, `vectorstore/`, `rag/`, `embeddings/`, `experiments/` (referenced in docs but **does not exist on disk**), or `.github/` (no CI) directories exist anywhere in the repo.

### Git log summary
**NOT AVAILABLE.** `Is a git repository: false`. There is no `.git` directory, so there is no commit count, first/last commit date, or commit frequency to report. All chronology below is reconstructed from the prose in `README.md`, `PROJECT_SUMMARY.md`, and `PHASE3_STATUS.md`, which describe the project in three self-declared phases ("Day 1", "Day 2"/"Phase 2", "Phase 3"), last dated "November 21, 2024" in `PROJECT_SUMMARY.md`.

### README content
Full text preserved as-is in the repo at `README.md`. Summary of key claims (verified against code below):
- Positions the project as "Day 1: API Tool Wrappers" complete, with a roadmap: Day 2 = agent orchestration (LangGraph), Day 3 = "Web interface (Streamlit/Gradio)" + evaluation.
- Note: the README's own roadmap for the frontend is **Streamlit/Gradio**, not React/TypeScript/GraphQL — the resume's frontend claim does not match even the project's own aspirational roadmap.
- Lists 3 tools (PubMed, ClinicalTrials, ChEMBL) — all three exist and are implemented (see §3/§4 tool inventory).

### Other docs
- `PROJECT_SUMMARY.md`: Declares "Day 1" 100% complete, gives file/line counts, and lists Day 2/Day 3 as future work ("Integrate Google Gemini", "Build LangGraph agent workflow" — i.e., **not yet done as of this document**, even though `agent/graph.py` and `agent/nodes.py` elsewhere in the repo indicate this work was subsequently completed). This document is stale relative to the current code.
- `PHASE3_STATUS.md`: Explicitly says **"Phase 3 is 40% complete."** Lists what's built (test cases, metrics, evaluator, hyperparameter config dataclass) vs. what's missing (grid-search tuner, CLI `--evaluate`/`--tune` flags, human-eval interface, validation script, results visualization, docs). Notably references `experiments/hyperparams.py` and `experiments/results/` — **the `experiments/` directory does not exist in the current repo**, so even the "40% complete" claim can no longer be verified from present code; the referenced files are missing entirely.
- `docs/architecture.md`, `docs/phase1_architecture.md`, `docs/phase2_architecture.md`, `docs/tool_specifications.md`, `docs/api_documentation.md`: Design-note style docs describing the tool layer (Phase 1) and the 6-node LangGraph agent (Phase 2) as built. `docs/phase2_architecture.md` contains an ASCII architecture diagram of the 6-node loop that matches `agent/graph.py` reasonably closely (see §3).
- No ADRs, no `CHANGELOG.md`.

---

## 2. Stack & Dependencies

### `requirements.txt` (full contents)
```
langchain==0.3.0
langchain-google-genai==2.0.0
langgraph==0.2.28
google-generativeai==0.8.0
langsmith==0.1.129
langchain-core==0.3.0
requests==2.31.0
python-dotenv==1.0.0
pydantic==2.9.0
pydantic-settings==2.1.0
pytest==7.4.3
aiohttp==3.9.1
tenacity==8.2.3
ratelimit==2.2.1
pandas==2.1.4
tabulate==0.9.0
```

**Finding:** These pins are currently **not co-installable**. Running `pip install -r requirements.txt` fails with:
```
ERROR: Cannot install -r requirements.txt (line 2) and google-generativeai==0.8.0 because these package versions have conflicting dependencies.
ERROR: ResolutionImpossible
```
i.e. `langchain-google-genai==2.0.0` and `google-generativeai==0.8.0` have an unresolvable dependency conflict as pinned. **As shipped, `pip install -r requirements.txt` does not succeed on a clean environment.** No `pyproject.toml`, `Pipfile`, or lockfile exists to pin a known-good resolution. `setup.py` exists but only wraps the same requirements list for packaging; it does not fix the conflict.

No `package.json` (no JS/TS project at all), no `go.mod`, no `pyproject.toml`.

### Docker / compose
**NOT IMPLEMENTED.** No `Dockerfile`, `docker-compose.yml`, or any container config exists anywhere in the repo.

### CI
**NOT IMPLEMENTED.** No `.github/workflows`, no `.gitlab-ci.yml`, no other CI config.

### Env / config
`.env.example` (full contents):
```
# Google Gemini API Key (Required for Day 2)
GOOGLE_API_KEY=your_api_key_here

# Logging Configuration
LOG_LEVEL=INFO
LOG_FILE=logs/medagent.log

# API Configuration (Optional - defaults are set in config/settings.py)
# PUBMED_RATE_LIMIT=3
# CLINICAL_TRIALS_RATE_LIMIT=10
# CHEMBL_RATE_LIMIT=10
# API_TIMEOUT=30
# MAX_RETRIES=3
```
Only one required secret: `GOOGLE_API_KEY` (Gemini). All other vars are optional overrides of hardcoded defaults in `config/settings.py` (`PUBMED_BASE_URL`, `CLINICAL_TRIALS_BASE_URL`, `CHEMBL_BASE_URL`, rate limits, retry/backoff, timeouts, log level/file/format, cache TTL). No database, no vector store, no frontend-related env vars exist because none of those subsystems exist.

---

## 3. Multi-Agent Pipeline (LangChain/LangGraph)

**Verdict: LangChain and LangGraph are genuinely imported and used, not just listed in dependencies.** This is the most substantiated part of the resume claims, with one significant integration bug (below).

### Is it really 6 distinct stages?
**Yes — 6 nodes are implemented and wired into a real LangGraph `StateGraph`.** File: `agent/graph.py`, function `build_agent_graph()`.

| # | Node (function, `agent/nodes.py`) | What it does | LLM call | Tools it touches |
|---|---|---|---|---|
| 1 | `query_analysis_node` | Extracts drug targets, diseases, compounds, query type, constraints from the raw query via an LLM prompt (`QUERY_ANALYSIS_PROMPT`), parses JSON | Gemini via `get_llm(temperature=0.1)` | none directly |
| 2 | `planning_node` | Given the query analysis, LLM selects 1–3 tools and an execution order (`PLANNING_PROMPT`) | `get_llm(temperature=0.3)` | none directly (selects tool names) |
| 3 | `tool_execution_node` | For each selected tool, LLM generates tool-specific query params (`TOOL_QUERY_GENERATION_PROMPT`), then actually calls `PubMedTool`, `ClinicalTrialsTool`, `ChEMBLTool` | `get_llm(temperature=0.2)`, once per tool for query generation | PubMed, ClinicalTrials, ChEMBL (see bug below) |
| 4 | `synthesis_node` | LLM cross-references/synthesizes findings across tool outputs (`SYNTHESIS_PROMPT`), grounded-generation instructions in the prompt | `get_llm(temperature=0.2)` | none directly |
| 5 | `verification_node` | LLM self-assesses coverage/confidence/completeness and decides `needs_more_research` (`VERIFICATION_PROMPT`) — this drives the conditional edge back to node 3 | `get_llm(temperature=0.3)` | none directly |
| 6 | `report_generation_node` | LLM writes the final markdown report with citations built from `tool_results` (`REPORT_GENERATION_PROMPT`) | `get_llm(temperature=0.4)` | none directly (reads accumulated `tool_results`) |

LLM used throughout: **Google Gemini** via `langchain_google_genai.ChatGoogleGenerativeAI`, model string `"gemini-flash-latest"` (`config/llm_config.py`), **not** any Anthropic/OpenAI model. Temperature varies per node (0.1–0.4), each hardcoded per call site — see §4 for whether this constitutes "temperature-aware generation" (it is static per-node config, not dynamically computed from a signal).

### Orchestration graph: real or fake?
**Real `langgraph.graph.StateGraph`, not a linear script pretending to be one.** `agent/graph.py`:
- `workflow = StateGraph(AgentState)`
- 6 nodes added via `add_node`
- Linear edges: `query_analysis → planning → tool_execution → synthesis → verification`
- **A genuine conditional edge** at `verification`: `add_conditional_edges("verification", should_continue_research, {"continue": "tool_execution", "report": "report_generation"})` — this creates an actual loop (verification → tool_execution → synthesis → verification → ...) bounded by `max_iterations`, which is a legitimate agentic/self-reflective control flow, not just a straight pipeline.
- Compiled via `workflow.compile()`.

This part of the resume's claim ("6-stage LangGraph multi-agent pipeline with... prompt engineering") is **substantially true as code**, assuming it runs (see bug below).

### Critical bug: tool-execution wiring is broken for 2 of 3 tools
In `agent/nodes.py::tool_execution_node`, the code calls:
```python
elif tool_name == "clinical_trials":
    result = tool.search_trials(
        query=search_query,
        max_results=params.get("max_results", 20),
        status=params.get("status")
    )
elif tool_name == "chembl":
    result = tool.search_compounds(
        query=search_query,
        query_type=params.get("query_type", "target"),
        max_results=params.get("max_results", 20)
    )
```
Verified against the actual tool implementations:
- `ClinicalTrialsTool.search_trials(self, condition=None, intervention=None, status="RECRUITING", phase=None, max_results=None, sponsor=None, country=None)` — **there is no `query` parameter.** Calling it with `query=search_query` raises `TypeError: search_trials() got an unexpected keyword argument 'query'`.
- `ChEMBLTool` has **no `search_compounds` method at all** — only `search_by_target`, `get_drug_info`, `search_by_indication`. Calling `tool.search_compounds(...)` raises `AttributeError: 'ChEMBLTool' object has no attribute 'search_compounds'`.

I verified both directly:
```
chembl has search_compounds: False
search_trials params: ['condition', 'intervention', 'status', 'phase', 'max_results', 'sponsor', 'country']
```
**Impact:** any real end-to-end run of the agent that selects `clinical_trials` or `chembl` (which the planning prompt explicitly encourages for most query types) will throw inside `tool_execution_node`. The node's own `try/except` swallows the exception and logs it as an error/`intermediate_thought`, so the agent doesn't crash outright — but it silently fails to retrieve any ClinicalTrials or ChEMBL data on every single call. Only the `pubmed` path (`tool.search_pubmed(query=..., max_results=..., years_back=...)`) is correctly wired, because `PubMedTool.search_pubmed` does accept those exact kwargs. **This means the 3-tool multi-agent research loop the resume describes has, at most, 1 of 3 tools actually functional in its current wired state**, despite all 3 tools being independently well-implemented and independently tested.

### Tool-calling: full tool inventory
| Tool | File | Method(s) actually callable | Signature |
|---|---|---|---|
| PubMed | `tools/pubmed_tool.py` | `search_pubmed` | `search_pubmed(self, query: str, max_results: int = None, years_back: Optional[int] = None, date_from=None, date_to=None) -> ToolResult` |
| PubMed | same | `get_paper_details` | `get_paper_details(self, pmid: str) -> ToolResult` |
| ClinicalTrials | `tools/clinical_trials_tool.py` | `search_trials` | `search_trials(self, condition=None, intervention=None, status="RECRUITING", phase=None, max_results=None, sponsor=None, country=None) -> ToolResult` |
| ClinicalTrials | same | `get_trial_details` | `get_trial_details(self, nct_id: str) -> ToolResult` |
| ChEMBL | `tools/chembl_tool.py` | `search_by_target` | `search_by_target(self, target_name: str, max_results: int = 10) -> ToolResult` |
| ChEMBL | same | `get_drug_info` | `get_drug_info(self, chembl_id: str) -> ToolResult` |
| ChEMBL | same | `search_by_indication` | `search_by_indication(self, disease: str, max_results: int = 20) -> ToolResult` |

These are conventional Python method wrappers around REST calls (`requests` via a custom `RetrySession`), **not** LangChain `@tool`-decorated functions or Pydantic-schema tool definitions bindable to an LLM's native tool-calling API. The "tool calling" in this codebase is **manually orchestrated**: the LLM is prompted to emit JSON describing which tool + params to use (`TOOL_QUERY_GENERATION_PROMPT`), and the Python code parses that JSON and calls the corresponding Python function itself. This is a legitimate agentic pattern, but it is **not** LangChain/LangGraph native tool-calling (no `bind_tools`, no `ToolNode`, no OpenAI/Gemini function-calling schema declared anywhere in the code). If the resume's "LLM tool-calling" bullet implies native function-calling APIs, that is **not what's implemented** — it's LLM-generates-JSON-then-Python-dispatches, which is functionally similar but architecturally different and less reliable (it depends on `_parse_llm_json` succeeding, which itself has no retry/repair logic beyond a bare `try/except` raising `ValueError`).

### "96% task completion", "98% tool-call reliability", "5K+ autonomous workflows" — substantiated?
- **Evaluation code exists** (`evaluation/evaluator.py`, `evaluation/metrics.py`, `evaluation/test_cases.py`) that *could* produce a task-success-rate number: `AgentMetrics.task_success_rate()` computes `successful / len(results)` from a list of evaluation results, and `AgentEvaluator._check_task_success()` defines success criteria (report generated, confidence ≥ 0.5, results ≥ min_results, ≥50% of expected drugs found in report text). `evaluation/test_cases.py` defines exactly **10 test cases** total (3 easy, 4 medium, 2 hard, 1 ambiguous) — nowhere close to a scale that would produce a statistically meaningful "96%" or imply "5K+ workflows".
- **No saved evaluation results exist anywhere in the repo.** `evaluator.py` writes JSON reports to `experiments/results/`, but that directory does not exist on disk — meaning **the evaluator has apparently never been run to completion and persisted**, or any prior output was deleted/never committed (recall: no git history to check).
- `PHASE3_STATUS.md` itself states the evaluation framework was built but a working end-to-end run was not part of "what still needs implementation" (`experiments/tuner.py`, `main.py --evaluate` CLI integration are listed as **missing**) — there is **no `main.py` in the repo at all**, so there is no documented way to even invoke the evaluator from a CLI entrypoint today.
- Given the wiring bug above (ChEMBL/ClinicalTrials calls fail on every attempt), any evaluation run today would show most multi-tool test cases failing, since 2 of 3 tools are non-functional in the orchestration path.
- **"Tool-call reliability 98%" and "5K+ autonomous workflows" have zero supporting artifacts** — no run logs (the only log file present is from this audit's own local pytest run, not agent runs), no results JSON, no dashboard, no counter of any kind tracking workflow executions.

**Conclusion: 96% task completion, 98% tool-call reliability, and 5K+ autonomous workflows are currently unsubstantiated numbers with no data, logs, or saved evaluation output to back them, and are contradicted by an active, unfixed bug that breaks 2 of the 3 tool integrations.**

---

## 4. RAG / FAISS Pipeline

**NOT IMPLEMENTED.** Exhaustive search confirms zero references anywhere in the codebase:
```
grep -ril "faiss|react|graphql|typescript|vector|embedding|rag\b" .
→ (no matches)
```
- No FAISS index build script exists.
- No embedding model is referenced or used anywhere (no `sentence-transformers`, no OpenAI/Gemini embeddings call, no `text-embedding-*` usage).
- No document corpus exists on disk — real, scraped, or synthetic. The "10K+ biomedical documents" claim has no corresponding data files, ingestion script, or document count anywhere in the repo.
- "Temperature-aware generation": the only "temperature" concept in the codebase is the static, hardcoded `temperature=` kwarg passed per LLM call in `agent/nodes.py` (0.1 for query analysis, 0.3 for planning/verification, 0.2 for tool-query-gen/synthesis, 0.4 for report generation) and the `MedAgent.__init__(temperature=0.3)` constructor default. This is **static per-call-site configuration chosen by the developer**, not a mechanism that dynamically adjusts temperature based on any runtime signal (confidence, retrieval score, uncertainty, etc.). There is no code path where temperature is computed from a variable at runtime.
- No retrieval evaluation code (Recall@10) exists — `evaluation/metrics.py`'s 8 metrics (`task_success_rate`, `tool_precision`, `redundancy_rate`, `self_correction_rate`, `citation_coverage`, `avg_latency`, `avg_confidence`, `hallucination_rate`) are **agent-behavior metrics**, not retrieval metrics; none compute Recall@k or any IR-standard metric. `hallucination_rate()` exists as a function signature, but per its own docstring it "requires manual human verification" and takes a `manual_check` dict of `{total_claims, hallucinated_claims}` that must be supplied externally — there is no automated hallucination detector, and no record anywhere that this function has ever been invoked with real data (no saved results, per §3).
- Chunking strategy, vector dimensions, index type: **N/A — none of this exists.**

**Conclusion: RAG bullet #2 in its entirety (FAISS, 10K+ docs, temperature-aware generation, 3% hallucination rate, 0.92 Recall@10, 35% improvement) has no corresponding code, data, or artifacts anywhere in this repository. This is not a partially-built RAG system — there is no RAG system.**

---

## 5. Frontend / API Layer

**NOT IMPLEMENTED.** No frontend code, no GraphQL server, in any form.
- No `package.json`, no `node_modules` reference, no `.tsx`/`.jsx`/`.ts` files, no `vite.config`, no `webpack.config`, no `next.config` — nothing indicating a JS/TS project was ever scaffolded in this repo.
- No GraphQL schema file (`.graphql`, `.gql`), no `graphene`/`ariadne`/`strawberry` (Python GraphQL libs) or `apollo-server`/`graphql-yoga` (JS GraphQL libs) in dependencies or code.
- No REST/HTTP server of any kind either — no `fastapi`, `flask`, `django` in `requirements.txt`, and no `app.py`/`server.py`/`main.py` exposing an HTTP endpoint. The only "interface" to the agent is direct Python import (`from agent.graph import MedAgent; agent = MedAgent(); agent.run(query)`), invoked from `examples/demo_agent.py`, `test_phase1.py`, `test_phase2.py`, or interactively.
- "Agent state exposed live," "output guardrails," "live tool-call traces": there is no server process to expose state over a network at all, live or otherwise. What exists instead:
  - **State visibility**: `AgentState` (`agent/state.py`) is a `TypedDict` passed through the LangGraph in-process; `MedAgent.get_reasoning_trace()`, `.print_reasoning_trace()`, `.get_tool_usage_stats()` are convenience methods to inspect it **after a synchronous `.run()` call returns** — this is post-hoc introspection of an in-memory Python object, not a live stream, websocket, or subscription of any kind.
  - **"Guardrails"**: no dedicated guardrail module exists. The closest analogues are (a) prompt-level instructions telling the LLM not to hallucinate ("CRITICAL: Do not hallucinate... Only synthesize what's in the tool results" in `SYNTHESIS_PROMPT`/`REPORT_GENERATION_PROMPT`) — these are prompt engineering, not enforced guardrails/validation code — and (b) `_parse_llm_json()` in `agent/nodes.py`, which does basic JSON-parse error handling (strips markdown fences, raises `ValueError` on malformed JSON) but performs no schema validation, no content filtering, and no refusal handling.
  - **"Live tool-call traces"**: `state["tool_call_history"]` and `state["intermediate_thoughts"]` are populated during a run and can be printed via `print_reasoning_trace()` or logged via `utils/logger.py`'s structured JSON logging (`logs/medagent.log`). This is legitimate trace **capture**, but there is no display layer, dashboard, or live streaming UI — it is console output / log-file lines only.
- "40% reduction in query-to-insight time": no benchmark harness, no before/after timing comparison, no baseline measurement of any kind exists in the repo. `evaluation/metrics.py::avg_latency()` computes average agent latency but has no "manual research baseline" comparison logic and, per §3, has never been run with saved results.

**Conclusion: Bullet #3 in its entirety (React+TypeScript frontend, GraphQL API, live agent-state exposure, output guardrails, live tool-call traces, 40% query-to-insight improvement) has no corresponding code or artifacts anywhere in this repository.**

---

## 6. Tests & CI

### Test files and what they cover
| File | Covers | Method |
|---|---|---|
| `tests/test_pubmed.py` | `PubMedTool`: init, search success/no-results/invalid-query, XML parsing (basic/malformed/empty), rate limiting, connection/timeout error handling, caching | Mocked HTTP via `unittest.mock.patch` on internal `_search_ids`/`_fetch_details` |
| `tests/test_clinical_trials.py` | `ClinicalTrialsTool`: analogous coverage to PubMed tests | Mocked |
| `tests/test_chembl.py` | `ChEMBLTool`: analogous coverage | Mocked |
| `examples/test_pubmed.py`, `examples/test_clinical_trials.py`, `examples/test_chembl.py` | Example scripts, not pytest suites — designed to hit **live** external APIs for demo purposes, not CI-safe | Live network calls |
| `test_phase1.py`, `test_phase2.py` (repo root) | Not inspected in full here, named to align with the "Phase 1/2" self-declared milestones; not part of the `tests/` package and not covered by the `pytest tests/` command the README documents | — |

None of the `tests/` files test `agent/graph.py`, `agent/nodes.py`, or the LangGraph orchestration end-to-end — **there is no test coverage at all for the 6-node agent pipeline itself**, which is the component with the actual wiring bug identified in §3. Coverage is limited to the three low-level API-wrapper tools.

### Do they pass right now?
I ran the actual suite in a clean virtualenv (`requirements.txt` doesn't fully install — see §2 — so I installed the non-conflicting subset needed for these tests: pytest, requests, pydantic, pydantic-settings, python-dotenv, tenacity, ratelimit, pandas, tabulate, aiohttp):

```
$ pytest tests/ -v
...
FAILED tests/test_chembl.py::TestChEMBLErrorHandling::test_timeout_error
FAILED tests/test_chembl.py::TestChEMBLRateLimiting::test_rate_limit_applied
FAILED tests/test_clinical_trials.py::TestClinicalTrialsErrorHandling::test_timeout_error
FAILED tests/test_pubmed.py::TestPubMedToolBasic::test_search_pubmed_no_results
FAILED tests/test_pubmed.py::TestPubMedRateLimiting::test_rate_limit_applied
FAILED tests/test_pubmed.py::TestPubMedErrorHandling::test_timeout_error
=================== 6 failed, 34 passed, 2 warnings in 0.60s ===================
```
**34/40 pass, 6 fail as of this audit.** Failure causes observed:
- `test_timeout_error` (×3, one per tool): test asserts the substring `"timeout"` appears in the error message, but `BaseTool.handle_errors()` produces `"API request timed out. Please try again."` — capitalized `"Timed"`, lowercased assertion looks for `"timeout"` (one word) which never appears; the message says "timed out" (two words). Simple test/implementation string mismatch, not a functional bug.
- `test_rate_limit_applied` (×2): asserts 4 rapid calls take ≥0.3s due to rate limiting, but because `_search_ids`/`_fetch_details` are mocked out, the `@rate_limit` decorator (applied to the mocked-over methods) never actually throttles — the real rate limiter is bypassed by the mock, so the test's premise doesn't hold against its own mocking strategy.
- `test_search_pubmed_no_results`: when `_search_ids` returns `[]`, `search_pubmed`'s inner `_execute()` returns `[]` (a list) instead of an XML string, then unconditionally calls `self.parse_results([])`, which does `ET.fromstring([])` → `TypeError: a bytes-like object is required, not 'list'`. This is a **real code bug** (missing empty-list short-circuit was written in the docstring's example flow but not actually implemented as unconditionally as assumed) — the "no results" path is broken, not just a bad test assertion.

This confirms: the tool layer is mostly solid (34/40, and the 3 timeout failures are trivial string-matching issues), but there is at least one genuine unhandled-edge-case bug (empty PubMed search results crash instead of returning `[]`), on top of the more serious ChEMBL/ClinicalTrials wiring bug in the agent layer found in §3.

### CI
**NOT IMPLEMENTED.** No GitHub Actions, no other CI config anywhere in the repo.

---

## 7. Gap Summary (resume claim → current reality)

| Claim | Status | What exists | What's missing |
|---|---|---|---|
| **1. 6-stage LangChain+LangGraph multi-agent pipeline, tool-calling, prompt engineering — 96% task completion, 98% tool-call reliability, 5K+ workflows** | **Partially true** | A real 6-node LangGraph `StateGraph` with a genuine conditional self-reflection loop (`agent/graph.py`, `agent/nodes.py`); 6 well-engineered prompts (`agent/prompts.py`); 3 independently working, well-tested API tools (PubMed/ClinicalTrials/ChEMBL). An evaluation framework (metrics + 10 test cases + evaluator) exists in code. | The tool-execution node calls `ChEMBLTool.search_compounds()` (doesn't exist) and `ClinicalTrialsTool.search_trials(query=...)` (wrong signature) — **2 of 3 tools fail on every real invocation**. No native LLM tool-calling API used (it's LLM-emits-JSON, Python-dispatches). Zero saved evaluation runs, zero logs of real usage, no `experiments/` results directory, no `main.py` CLI entrypoint to even run it end-to-end. The 96%/98%/5K+ numbers have no supporting data anywhere. |
| **2. FAISS RAG pipeline over 10K+ biomedical docs, temperature-aware generation — 3% hallucination, 0.92 Recall@10, 35% improvement** | **Not built** | Nothing. Zero FAISS, embedding, vector-store, or document-corpus code/data anywhere in the repo. "Temperature" only exists as static hardcoded per-call-site config values. | Everything: index build script, embedding model choice, document corpus/ingestion, chunking strategy, retrieval evaluation code, and all 3 cited metrics. |
| **3. React+TypeScript frontend, GraphQL API, agent-state exposure, output guardrails, live tool-call traces — 40% query-to-insight reduction** | **Not built** | Nothing. No frontend project, no GraphQL/REST server, no network-exposed interface of any kind. Trace *capture* exists in-process (`intermediate_thoughts`, `tool_call_history`, structured JSON logging) but with no display/streaming layer. | Everything: the entire frontend app, the entire API layer (GraphQL or otherwise), any live/websocket state exposure, real guardrail/validation logic beyond prompt instructions, and the 40% benchmark. |

---

## 8. Honest Recommendation

Roughly 60–70% of resume bullet #1 is real, working engineering — the 6-node LangGraph state machine with a genuine self-reflective loop, well-written prompts that explicitly instruct grounding/anti-hallucination behavior, and three solidly-tested (34/40 passing) external API integrations is a legitimate foundation and shouldn't be rewritten. The fastest path to making bullet #1 fully true is: (1) fix the two tool-dispatch bugs in `tool_execution_node` (change the ChEMBL branch to call `search_by_target`/`search_by_indication` based on `query_type`, and fix the ClinicalTrials branch to pass `condition=`/`intervention=` instead of `query=`) — this is a same-day fix; (2) fix the empty-results crash in `PubMedTool.parse_results`; (3) actually run `evaluation/evaluator.py` against the 10 existing test cases (ideally expanded well beyond 10 to make any percentage claim meaningful) with a real `GOOGLE_API_KEY`, and save/commit the resulting JSON reports as evidence — only then do "task completion" and "tool-call reliability" numbers mean anything, and only at the actual measured value, not fabricated 96%/98% figures. "5K+ autonomous workflows" would require either genuinely running the agent that many times (impractical/costly) or rewriting the claim to match reality (e.g., "10 curated evaluation scenarios" or however many are actually run).

Bullets #2 and #3 are not partially-built — they are **entirely absent**, and treating them as "mostly there, needs polish" would be dishonest. RAG/FAISS would need to be built from scratch: pick a real corpus (e.g., a PubMed abstract dump or ChEMBL bioactivity dataset, which the existing tools already have API access to — that's a genuine synergy to exploit), embed and index it, wire retrieval into the existing `synthesis_node`/`report_generation_node` prompts (which already emphasize grounding, a good foundation to extend), and only then measure Recall@10/hallucination rate for real. The frontend/GraphQL bullet needs an entire application layer built from zero — a GraphQL server (e.g., Strawberry/Ariadne on top of the existing `MedAgent` class) exposing queries/subscriptions for run state and trace, plus a new React+TypeScript client. Given the current single-person, no-git-history, "Day 1/2/3" scope of this project, I'd treat bullets #2 and #3 as multi-week net-new builds, not touch-ups — and would recommend either building them for real or rewriting the resume to describe only what bullet #1 (once the two bugs above are fixed and evaluation is actually run) can honestly support.
