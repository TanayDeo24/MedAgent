# Phase 4 LangGraph Integration Verification

Steps 27–30 of the Phase 4 gate plan: verify (not just assert) that the
frozen Phase 4 retrieval architecture (`artifacts/v2/phase4_frozen_config.json`,
config_version 2 — PubMed local RAG, ClinicalTrials fixed phase filter,
ChEMBL's new `resolve_compound_name`) is actually wired into the live
`agent/nodes.py` / `agent/graph.py` pipeline, with no dead/ambiguous paths
left behind, and that it works end-to-end against the real graph.

**Verdict: no integration code changes were needed.** The hypothesis in
the governing task — that Phase 4's capabilities were already fully
reachable through Phase 3's existing generic orchestration boundary and
synthesis_node's existing RAG call — held up under both code reading and
live testing. Nothing in this repo was modified as part of this
verification pass (see `git status --short` at the end of this document).

---

## Step 27: Integration verification (Task A)

### A.1 — synthesis_node really does call `retrieve()` as the PubMed RAG mechanism

`agent/nodes.py::synthesis_node` (line ~876) calls
`_retrieve_rag_context(query)` — a thin wrapper around
`retrieval.retriever.retrieve()` (imported at the top of `nodes.py` as
`retrieve_passages`) — gated on `state.get("use_rag", True)`:

```python
if state.get("use_rag", True):
    state["retrieved_context"] = _retrieve_rag_context(query)
else:
    state["retrieved_context"] = []
```

`use_rag` is set on `AgentState` by `MedAgent.__init__`'s `use_rag` param
(default `True`) via `agent/graph.py::MedAgent.run()`. So by default every
real run retrieves RAG passages unconditionally; the flag exists only for
the deliberate baseline-vs-RAG comparison (`RESULTS_RAG_COMPARISON.md`),
not as a gate anyone would accidentally leave off. `retrieve()` itself
(`retrieval/retriever.py`) is the frozen hybrid pipeline (FAISS dense +
BM25 sparse → RRF fusion → cross-encoder rerank) — nothing downstream
re-implements or bypasses it.

Confirmed live in all 4 end-to-end runs (Step 29 below):
`retrieved_context_count == 10` (`RAG_RETRIEVAL_K`) in every run,
regardless of which tools the model also selected via tool orchestration —
i.e. RAG and Phase-3 live-tool orchestration both fire independently and
unconditionally per query, exactly as designed (PubMed has two distinct,
intentionally separate provenance paths — "PubMed" from the live tool call
vs. "PubMed RAG" from the local index — see `report_generation_node`'s
citation-building comment at `agent/nodes.py` line ~1097).

### A.2 — tool_orchestration_node's dispatch is genuinely operation-agnostic

Read `agent/nodes.py::tool_orchestration_node` in full (lines 527–816) and
`orchestration/candidate_b_native_tools.py` in full (439 lines). Confirmed:

- `DECLARED_TOOLS` (`candidate_b_native_tools.py` line 112) is a static
  tuple of exactly 6 `(function_name, ToolName, operation, argument_schema,
  call_cls)` entries — `chembl_resolve_compound_name` is simply the 6th
  entry, declared identically to the other 5, sharing the exact same
  `build_tool_declarations()` → `parse_and_validate_tool_call()` →
  `execute_validated_call()` pipeline. Nothing branches on the tool or
  operation name anywhere in this module.
- `parse_and_validate_tool_call()` looks up the model's returned function
  name in `DECLARED_TOOLS_BY_NAME` (a plain dict `.get()`, never a dynamic
  `eval`/`getattr` by model-produced string), builds the typed `ToolCall`
  pydantic subclass, and validates it against
  `orchestration.registry.DEFAULT_REGISTRY` — again with no per-operation
  special-casing.
- `tool_orchestration_node` itself iterates `raw_tool_calls` and, for each,
  calls the same two functions regardless of which tool/operation was
  selected (lines 645–797). The only operation-specific branch anywhere in
  the node is the ChEMBL name-backfill block (lines 735–750), and that
  branch explicitly checks `outcome.operation in ("search_by_target",
  "search_by_indication")` — i.e. it explicitly does NOT apply to
  `resolve_compound_name` (which doesn't need backfill; it already returns
  a matched name or `None`), so there was nothing to add there.

Confirmed live: query 3 ("What is the ChEMBL ID for semaglutide?", a
non-ID phrasing) caused the Cerebras model to select
`chembl_resolve_compound_name` (visible in `tool_call_history`'s
`operation` field) with zero code changes — the operation was reachable
through the existing generic path on the first live attempt.

### A.3 — the single-dict merge logic handles `resolve_compound_name`'s result shape correctly

`tools/chembl_tool.py::resolve_compound_name()` (lines 472–693) returns a
`ToolResult` whose `.data` is **one dict** (not a list) — same shape
convention as `get_drug_info()`, documented explicitly in its docstring:
`keys: input_name, normalized_name, matched_name, chembl_id,
preferred_name, match_type, candidates`.

`agent/nodes.py` line 758's merge logic:

```python
items = data if isinstance(data, list) else [data]
```

is purely `isinstance`-based, not name/operation-based, so it wraps
`resolve_compound_name`'s single dict into a 1-item list exactly the same
way it already did for `get_drug_info` — no new branch was needed, and
none was added.

Confirmed live: `tool_results["chembl"]` after both `resolve_compound_name`
runs (queries 3 and 4) was a proper Python list containing exactly one
dict each, with the real `chembl_id` intact (`CHEMBL2108724` for
semaglutide, `CHEMBL3353410` for osimertinib) — see Step 29 below for the
raw values.

### Minor observation (not a defect, not fixed — documented per instructions)

`report_generation_node`'s citation builder (`agent/nodes.py` ~line
1089–1095) and `_build_chembl_compound_table()` (~line 275) both read a
ChEMBL entry's compound name via `result.get("name") or
result.get("drug_name")` — the field names `search_by_target` /
`search_by_indication` / `get_drug_info` results use.
`resolve_compound_name`'s result dict uses `matched_name` /
`preferred_name` instead (a deliberately different, richer field set — see
its docstring), so a `resolve_compound_name` entry's citation shows
`"name": "N/A"` and it is excluded from the deterministic compound table
(`_build_chembl_compound_table` skips entries with no resolved `name`).

This does **not** cause any crash, data corruption, or fabricated
identifier — the real `chembl_id` is still present in `tool_results` and
in the raw JSON handed to the report-writing LLM prompt (confirmed live:
both `resolve_compound_name` reports correctly quote the real ChEMBL ID in
prose, e.g. "The ChEMBL database assigns semaglutide the identifier
**CHEMBL2108724**"). It only means a `resolve_compound_name`-only citation
row and the deterministic compound table undercount that entry's name/
phase columns. Per the governing directive ("Do not modify any file unless
integration work is genuinely found to be needed... minimal necessary
change"), this is a report-formatting nuance, not an integration defect —
the pipeline works correctly end-to-end without it — so it was left
unmodified and is recorded here for visibility rather than patched.

---

## Step 28: Dead-path check (Task B)

- **Other ChEMBL name-lookup implementations**: `grep -rln "chembl"
  --include="*.py"` across the repo shows exactly one resolution
  implementation (`tools/chembl_tool.py::resolve_compound_name`), one
  registry registration (`orchestration/registry.py` line 256), and one
  declared-tool entry (`orchestration/candidate_b_native_tools.py` line
  134). No superseded/legacy name-lookup path exists anywhere.
- **`PUBMED_DEFAULT_DATE_RANGE`**: still defined in `config/settings.py`
  (the field itself is kept, per the original fix's design, so removing it
  isn't required), but every non-comment code reference to it was already
  removed. The only remaining occurrences repo-wide are: (a) explanatory
  comments in `tools/pubmed_tool.py` documenting why it is deliberately
  *not* read, and (b) `tests/test_pubmed.py`'s regression guard, which
  greps the tool's own source for exactly this pattern and fails the test
  suite if a live reference reappears. Re-confirmed after all of this
  session's other changes (Steps A/B/C/D) — still clean.
- **`filter.phase`**: same pattern — the only occurrences are the
  explanatory comment in `tools/clinical_trials_tool.py` (documenting that
  the v2 API rejects this parameter with HTTP 400, and why `AREA[Phase]`
  inside `query.term` is used instead) and `tests/test_clinical_trials.py`'s
  three regression-guard assertions (`assert "filter.phase" not in
  called_params`). Re-confirmed clean.

**No ambiguous or dead retrieval path was found in production code.**
Nothing required a legacy-marking comment.

---

## Step 29: Bounded live end-to-end integration (Task C)

Ran the real `agent.graph.MedAgent(max_iterations=1, use_rag=True).run(query)`
— real Cerebras (tool orchestration) + real NVIDIA NIM (`nemotron-3-super-120b-a12b`,
query analysis/synthesis/verification/report generation) + real
PubMed/ClinicalTrials.gov/ChEMBL API calls, no mocking — for the 4 required
queries, then re-ran 2 of them once more after hitting transient upstream
LLM-provider errors (see below).

### Query 1 — PubMed-focused
*"What does recent literature say about EGFR inhibitor resistance
mechanisms in lung cancer?"*

- Tool orchestration selected `pubmed/search_pubmed` **3 times** in one
  round (real PMIDs returned, e.g. `40133478`, `39614090`, `40673977`).
- RAG (`synthesis_node` → `retrieve_passages`) independently retrieved 10
  passages (different PMIDs from the live-tool set, as expected — separate
  provenance, e.g. `26852079`, `40505315`).
- **Both mechanisms fired**, confirming A.1's live-tool-orchestration-plus-RAG
  design works as documented.
- `tool_call_history` entries all carried non-null `call_id`s
  (`step0-0`, `step0-1`, `step0-2`).
- First attempt: `report_generation_node` hit a transient NVIDIA API `404
  Not Found` (caught by the node's own try/except, producing the existing
  fallback "Report generation encountered an error" report rather than
  crashing the graph — no data corruption, pipeline completed). **Re-ran
  once**: completed cleanly, real 15,312-character report, no fallback,
  citations and RAG passages both present.
- No fabricated/malformed source IDs observed in either attempt.

### Query 2 — ClinicalTrials-focused with explicit phase constraint
*"What phase 3 clinical trials are studying pembrolizumab for melanoma?"*

- Tool orchestration selected `clinical_trials/search_trials` once; real
  NCT IDs returned (`NCT05549297`, `NCT06264180`, `NCT03755739`,
  `NCT06697301`, `NCT06488482`) — confirms the fixed `AREA[Phase]3` query
  construction works through the real graph end-to-end (no HTTP 400, no
  empty/garbage result set).
- First attempt: `report_generation_node` hit a transient NVIDIA `503
  Service temporarily overloaded`, caught gracefully, fallback report
  produced, no crash. **Re-ran once**: completed cleanly (this time
  `verification_node` itself hit one transient 503, also caught
  gracefully, `needs_more_info` defaulted to stop-and-report as designed),
  real 8,113-character report generated with no fallback text, correctly
  discussing multiple named phase 3 trials.
- No fabricated/malformed NCT IDs observed.

### Query 3 — ChEMBL compound-name resolution (the new operation)
*"What is the ChEMBL ID for semaglutide?"*

- The model **actually selected `chembl_resolve_compound_name`** (not
  `get_drug_info` or a 404) — confirmed via `tool_call_history`'s
  `operation` field.
- Result: `{"input_name": "semaglutide", "matched_name": "SEMAGLUTIDE",
  "chembl_id": "CHEMBL2108724", "match_type": "exact_preferred_name",
  "candidates": []}` — a real, correct ChEMBL ID, resolved via the exact
  preferred-name tier (no fuzzy fallback needed for this well-known drug
  name).
- Flowed correctly into `state["tool_results"]["chembl"]` as a 1-item
  list (confirming A.3's merge-logic claim) and into the final report:
  *"The ChEMBL database assigns semaglutide the identifier
  **CHEMBL2108724**"* — the correct real ID appears verbatim in the
  generated report's executive summary. Full report generated
  successfully first try (6,771 characters, no fallback), 11 citations.
- **This is the single clearest confirmation that no integration code was
  needed**: the new operation was reachable, selectable, executable, and
  correctly reflected in the final report through entirely pre-existing
  Phase 3 generic-dispatch + Phase 4 single-dict-merge code paths.

### Query 4 — Multi-source (ChEMBL name-resolution + ClinicalTrials)
*"Find ChEMBL compound info for osimertinib and any related phase 2
clinical trials for lung cancer."*

- Tool orchestration selected **both** `chembl/resolve_compound_name`
  (osimertinib → real, correct `CHEMBL3353410`, `match_type:
  exact_preferred_name`) **and** `clinical_trials/search_trials` (real NCT
  IDs: `NCT06868485`, `NCT06363734`, `NCT05498428`, `NCT05528458`,
  `NCT07535437`) in the same orchestration round.
- Both calls carried distinct `call_id`s (`step0-0`, `step0-1`).
- Report generated successfully first try (12,371 characters, no
  fallback), 31 citations, correctly cross-referencing osimertinib
  (ChEMBL; PubMed RAG) against the trial data in the executive summary.
- Confirms a real multi-source run with a ChEMBL name-resolution leg
  completes end-to-end, sources correctly attributed, no ID corruption.

### Cross-cutting checks (all 4 + 2 retries)

- **No fabricated/corrupted source IDs**: every PMID, NCT ID, and ChEMBL
  ID observed across all 6 runs (4 original + 2 retries) is a real,
  correctly-formatted identifier consistent with what the underlying APIs
  actually returned — none were inspected as literally fabricated, and the
  frozen ChEMBL config's structural guarantee (`resolve_compound_name`
  never returns a `chembl_id` not present in a real upstream response)
  held in every run.
- **`call_id` present on every `tool_call_history` entry**: confirmed
  (`call_ids_present: true` in every run's summary).
- **No secrets leaked**: inspected the full error traces from the two
  transient NVIDIA failures (404, 503) — they contain HTTP response
  headers, request URLs, and provider error bodies, but no API key or
  other secret in any field. `CEREBRAS_API_KEY`/`NVIDIA_API_KEY` are read
  only at header-construction time in `candidate_b_native_tools.py` /
  `config/llm_config.py` and never logged.
- **Report generated in every run**: all 6 runs (4 original + 2 retries)
  produced a non-empty `final_report` — the 2 original transient-error
  cases produced the existing graceful fallback report (not a crash); the
  2 retries and 2 clean-first-try runs produced full LLM-written reports.
  The pipeline never raised an uncaught exception out of `graph.invoke()`
  in any of the 6 runs.
- **Retrieval candidates matched expectations**: RAG returned exactly
  `RAG_RETRIEVAL_K` (10) passages in every run regardless of query type;
  ChEMBL resolution results were present and correctly shaped whenever the
  model selected that operation.

### Note on the two transient failures

Both transient errors (a `404 Not Found` from
`integrate.api.nvidia.com` and a `503 Service temporarily overloaded`)
occurred only in `report_generation_node`/`verification_node`'s NVIDIA NIM
calls — never in Cerebras tool orchestration, never in the
PubMed/ClinicalTrials/ChEMBL tool calls themselves, and never in RAG
retrieval. Both queries completed cleanly on a single retry with the exact
same code, confirming these were transient upstream provider issues
(observed 404 response carried a `Deprecation: 2026-10-03T09:00:00Z`
header on the `nemotron-3-super-120b-a12b` endpoint, suggesting the
provider is mid-migration on that model as of this session's run date;
this is an operational/vendor concern for a future session to track, not a
Phase 4 retrieval-architecture defect, and is explicitly out of this
verification's scope). `report_generation_node`'s pre-existing try/except
fallback (not something this session added) already handles this
gracefully — this is exactly the kind of resilience the existing code was
designed for, and it worked as intended both times.

---

## Step 30: Full test suite (Task D)

```
venv/bin/python -m pytest tests/ -q
```

**Result: 267 passed, 7 skipped, 0 failed** (41.50s) — identical counts to
the documented pre-task baseline (267 passed, 7 skipped). No regressions;
no code was modified in this session, so no change was expected.

---

## Summary

| Task | Outcome |
|---|---|
| A (integration verification) | No code changes needed. All 3 sub-claims (RAG call site, generic dispatch, dict-merge shape handling) verified true both by reading and by live testing. |
| B (dead-path check) | Clean. No superseded ChEMBL lookup path; `PUBMED_DEFAULT_DATE_RANGE` and `filter.phase` appear only in explanatory comments and regression-guard tests, re-confirmed after this session's changes (of which there were none to production code). |
| C (live e2e) | All 4 required queries + 2 confirmatory retries completed end-to-end with real APIs, no mocking. `resolve_compound_name` was correctly selected and executed for both the compound-name query and the multi-source query, with real ChEMBL IDs flowing correctly into `tool_results` and the final report. Two transient NVIDIA NIM provider errors (404, 503) were observed and resolved on retry — confirmed as upstream/transient, not a Phase 4 defect. No fabricated/corrupted IDs, no missing `call_id`s, no secret leakage. |
| D (test suite) | 267 passed, 7 skipped, 0 failed — unchanged from baseline. |

No files in this repository were modified as part of this verification
pass (see `git status --short` below).
