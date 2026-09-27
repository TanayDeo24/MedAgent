# Phase 1 Complete: Bug Fixes + LLM Provider Migration

**Date:** 2026-09-08
**Scope:** Fix broken tool dispatch in the LangGraph agent pipeline, migrate the LLM
provider from Google Gemini to NVIDIA NIM (Nemotron), and get the whole thing running
end-to-end from a CLI. FAISS/RAG, GraphQL, a frontend, native `bind_tools()` tool-calling,
and the evaluation-metrics framework were explicitly out of scope and were not touched.

## What was fixed

### 1. LLM provider migration: Google Gemini → NVIDIA NIM
- `config/llm_config.py`: `ChatGoogleGenerativeAI` replaced with `ChatNVIDIA`
  (`langchain_nvidia_ai_endpoints`), model `nvidia/nemotron-3-super-120b-a12b`, reading
  `NVIDIA_API_KEY` instead of `GOOGLE_API_KEY`.
- `config/settings.py`: the pydantic-settings field is now `NVIDIA_API_KEY`.
- `.env.example`, `README.md`, `docs/architecture.md`, `docs/phase1_architecture.md`,
  `docs/phase2_architecture.md`, `PROJECT_SUMMARY.md`, `test_phase1.py`, `test_phase2.py`,
  `agent/state.py`: every Gemini/Google reference updated to NVIDIA/Nemotron. A full
  repo grep for `gemini|GOOGLE_API_KEY|ChatGoogleGenerativeAI|google-generativeai` now
  returns zero matches outside `AUDIT_CURRENT_STATE.md`, which is left untouched
  deliberately — it's a dated snapshot of the pre-migration state, not living
  documentation, and this file supersedes it going forward.
- `requirements.txt`: dropped `langchain-google-genai`/`google-generativeai`, added
  `langchain-nvidia-ai-endpoints==0.3.19`. That package requires
  `langchain-core>=0.3.51,<0.4`, so `langchain-core` was bumped from `0.3.0` to `0.3.51`
  (still satisfies `langchain==0.3.0`'s own `>=0.3.0,<0.4.0` constraint and
  `langgraph==0.2.28`'s `>=0.2.39,<0.4`, so nothing else needed to move). Confirmed via
  `pip check` — no conflicts, and this dependency set no longer pulls in `grpcio` at all
  (that was a Google-generativeai transitive dependency), so the cosmetic
  `grpcio ... is not supported on this platform` `pip check` warning seen under the old
  Gemini stack is gone too.

### 2. Tool-dispatch bugs in `agent/nodes.py::tool_execution_node`
`tool_execution_node` was calling `ChEMBLTool.search_compounds()` (doesn't exist) and
`ClinicalTrialsTool.search_trials(query=...)` (no such parameter) — both would raise on
every real invocation, silently caught by the node's own try/except and logged as an
"error" in the trace. Only PubMed's call was ever correctly wired. Fixed by:
- Dispatching ChEMBL calls to `search_by_target()` or `search_by_indication()` based on
  the LLM-selected `query_type`.
- Passing `condition=`/`intervention=`/`status=`/`phase=` to `ClinicalTrialsTool.search_trials()`,
  matching its real signature.
- Updating `TOOL_QUERY_GENERATION_PROMPT` (`agent/prompts.py`) so the LLM is told to
  produce parameters that match these real signatures instead of an imagined generic
  interface.

### 3. PubMed empty-results crash
`PubMedTool.parse_results()` crashed with `TypeError: a bytes-like object is required,
not 'list'` whenever a search found zero PMIDs, because `search_pubmed()` short-circuits
to `[]` in that case but `parse_results()` unconditionally tried `ET.fromstring()` on
whatever it was handed. `parse_results()` now returns a list input as-is.

### 4. Two new reliability bugs found only after switching to Nemotron
These did not reproduce under Gemini and were only caught once real end-to-end runs
against NVIDIA NIM were attempted:
- **JSON truncation**: `synthesis_node`'s structured JSON output was getting cut off
  mid-string at the default 2048-token completion limit on Nemotron, making
  `_parse_llm_json()` fail on almost every real run (5 of 7 synthesis attempts failed in
  the first real end-to-end test). Fixed by raising `max_tokens` to 8192 for
  `synthesis_node` and `report_generation_node` specifically (the two nodes with the
  largest expected output) rather than changing the global default.
- **Recursion-limit mismatch**: LangGraph's default `recursion_limit` (25) counts every
  node visit, not research iterations. Each self-reflection loop
  (`tool_execution -> synthesis -> verification`) costs 3 node visits, so anything past
  ~7-8 loop iterations hit `GraphRecursionError` before `max_iterations`'s own stop
  condition could ever fire — meaning any query needing more than ~7 iterations could
  never produce a final report, regardless of confidence. `agent/graph.py::MedAgent.run()`
  now passes an explicit `recursion_limit` sized from `max_iterations` (`max_iterations * 3 + 10`)
  instead of relying on the library default.

### 5. Trivial test-assertion fixes
`test_timeout_error` in all three tool test files asserted the substring `"timeout"`,
but `BaseTool.handle_errors()` produces `"API request timed out. Please try again."`
("timed out", two words — the more correct phrasing). Updated the three assertions to
match rather than degrading the error message.

### 6. `main.py` CLI entrypoint (new)
There was previously no way to run the agent outside of importing `MedAgent` in a
script or the interactive `examples/demo_agent.py` menu. `main.py` now supports
`python main.py "query" [--trace] [--max-iterations N] [--temperature T]`, fails fast
with a clear message and non-zero exit if `NVIDIA_API_KEY` is missing, and `--trace`
prints the full tool-call history and reasoning trace.

### 7. Git history
This repo had no `.git` directory at all before this phase. Initialized git, committed
the pre-fix baseline as a root commit, then four logically separated commits for the
work above (migration, tool-dispatch + reliability fixes, test-assertion fixes,
`main.py`). `.gitignore` already correctly excluded `.env`, `venv/`, `__pycache__/`,
and `logs/*.log` — no changes needed there.

## Verification run results

### 1. `pip install -r requirements.txt` (clean venv)
Succeeds with exit code 0, no `ResolutionImpossible` error, `pip check` reports
"No broken requirements found."

### 2. `pytest tests/ -v`
**38/40 pass.** The 2 remaining failures are **pre-existing and out of scope** (see
below) — not something introduced by this phase's changes, and not part of the 3
timeout-assertion fixes this phase was scoped to.

### 3. `python main.py "..." --trace` end-to-end runs
Two real queries were run against the live NVIDIA NIM API and live PubMed/ClinicalTrials/ChEMBL
APIs (no mocking):

- **"Find EGFR inhibitors for lung cancer and their clinical trial status"** (10
  iterations) — completed with **zero errors**, produced a full markdown report with a
  compound table and 12 numbered citations. ChEMBL and ClinicalTrials both returned real,
  non-empty results on every one of the ~9-10 tool calls made across the run's
  iterations (PubMed was not selected by the planner in this particular run — an LLM
  planning choice, not a bug).
- **"What is the mechanism of action of pembrolizumab, what PD-1 targeting compounds
  exist, and what published literature and clinical trials support its use in
  melanoma?"** (3 iterations, to specifically confirm PubMed) — completed with **zero
  errors**. Confirmed from the trace: PubMed returned 25 results, then 0, then 5
  (varying by iteration's search terms — all successful, non-error calls); ChEMBL
  returned 20, 50, and 20 results; ClinicalTrials returned 20 and 20 results. **All
  three tools confirmed firing with real, non-error results in this run.**

Both runs are reproducible by anyone with an `NVIDIA_API_KEY` in `.env`.

### 4. JSON-parsing reliability across nodes
Across the two verification runs above plus the two earlier runs that surfaced and then
confirmed the fix for the truncation bug (4 full runs, ~30+ individual node-level LLM
calls across query_analysis, planning, tool_execution's query-generation step,
synthesis, verification, and report_generation), **zero `_parse_llm_json()` failures
occurred after the `max_tokens` fix was applied.** Before the fix, `synthesis_node`
failed on 5 of 7 attempts in a single run. **Prompt/config adjustment required for
Nemotron**: only the `max_tokens` bump described above — the JSON *structure* Nemotron
produces (formatting, key names, nesting) matched the original Gemini-era prompts
without any wording changes; the only failure mode was truncation, not malformed JSON
shape.

### 5. `git log --oneline`
```
2797b1f Add main.py CLI entrypoint
0e8b777 Fix timeout error-message assertion mismatch in tool tests
d53d241 Fix broken tool dispatch and pipeline reliability bugs in the agent graph
6cf331a Migrate LLM provider from Google Gemini to NVIDIA NIM (Nemotron)
b4af5c0 Initial commit: MedAgent baseline state (Day 1-3 / Phase 1-3 work)
```

## Out of scope but worth knowing about for later phases

- **The 2 remaining rate-limit test failures are a pre-existing test-design flaw, not a
  product bug.** `TestPubMedRateLimiting::test_rate_limit_applied` and
  `TestChEMBLRateLimiting::test_rate_limit_applied` mock out `_search_ids`/`_fetch_details`
  (the exact methods carrying the `@rate_limit` decorator), which replaces the decorated
  method entirely — the decorator never runs, so the test's own timing assertion can
  never hold given how it mocks. Fixing this properly would mean patching at the HTTP
  layer (e.g. `self.session.get`) instead of the rate-limited method itself. This
  existed before the NVIDIA migration and is unrelated to any of the fixes above; not
  fixed here since it wasn't in this phase's scope.
- **Nemotron sometimes hallucinates tool names that don't exist.** In one run it emitted
  `pubchem` as a tool to call (there is no such tool — only `pubmed`, `clinical_trials`,
  `chembl` exist). `tool_execution_node` already handles this gracefully (`if tool_name
  not in tool_instances: logger.warning(...); continue`), so it's not a crash, just a
  wasted planning cycle. Worth tightening the `PLANNING_PROMPT`'s tool list constraint
  if this recurs often once evaluation metrics are being tracked for real.
- **ChEMBL's `search_by_target()` frequently returns compounds with `pref_name: null`,
  `development_phase: "Unknown"`, and no mechanism-of-action data.** This is the real
  ChEMBL API's behavior for many entries (not a parsing bug on our end — verified
  directly against the live API), but it means reports built purely from `search_by_target`
  results often can't name the actual drug, which visibly limited the quality of the
  first verification run's report ("Compound names are largely missing (null)"). If RAG
  or a richer ChEMBL query strategy (e.g., following up unnamed hits with
  `get_drug_info()`) becomes a later-phase goal, this is the gap to close.
  Not fixed here — it's a data/strategy limitation, not the dispatch bug this phase
  targeted.
- **No cost/rate-limit guardrails around the new NVIDIA NIM usage.** Each verification
  run made 15-30+ LLM calls (6 nodes x up to `max_iterations` loops). There's no
  token/request budget tracking anywhere in the codebase (the `total_tokens_used` field
  in `AgentState` is declared but never actually populated by any node). Worth
  addressing before running this against a real evaluation suite at any scale.
- **`AUDIT_CURRENT_STATE.md` is now stale** on every claim about the LLM provider,
  the tool-dispatch bug, the PubMed crash, the missing `main.py`, the missing git
  history, and the `requirements.txt` conflict — all of those are fixed as of this
  file. It was deliberately left unedited as a historical record rather than rewritten;
  treat this file (`PHASE1_COMPLETE.md`) as the current source of truth on those points
  going forward.
- **`evaluation/`, FAISS/RAG, GraphQL, a frontend, and native `bind_tools()` tool-calling
  remain entirely unbuilt**, exactly as documented in `AUDIT_CURRENT_STATE.md` — nothing
  in this phase touched them, per scope.
