# Phase 3 Step 34 — Tool Orchestration Integration

This document records what changed when the frozen, validated Phase 3
winning architecture (Candidate B — Cerebras `qwen-3.8-27b` native tool
calling, validated through `orchestration/registry.py`; see
`docs/v2/PHASE3_WINNER_SELECTION.md`) was wired into the real LangGraph
pipeline (`agent/graph.py`, `agent/nodes.py`), replacing the fragile legacy
free-text dispatch described in
`docs/v2/PHASE3_INITIAL_ORCHESTRATION_AUDIT.md`.

This is Step 34 only. It does not attempt Step 35 (broader legacy
compatibility audit) or Step 36 (final gate audit), and it does not start
any Phase 4 work.

---

## 1. What was replaced

- `planning_node` (old `agent/nodes.py:488-576`) — a free-text LLM call
  (`get_llm(temperature=0.3)`) given a hand-written tool catalog, asked to
  return JSON `tools_to_use: [{tool, priority}, ...]`, with no
  schema/enum validation of the returned tool names and no connection to
  the frozen Phase 2 `ResearchQuery.requested_evidence_types` prediction.
  On any failure, it unconditionally fell back to calling all three tools.
- `tool_execution_node` (old `agent/nodes.py:583-754`) — hardcoded
  `if tool_name == "pubmed": ... elif ... : ...` dispatch, plus a THIRD
  free-text LLM call per tool (`TOOL_QUERY_GENERATION_PROMPT`) to generate
  that tool's call parameters as an untyped dict. The only allowlist
  enforcement anywhere in the old pipeline was an ad hoc
  `if tool_name not in tool_instances` dict-membership check done at
  execution time, not at the point of selection.

**Both are now fully removed** — not kept side-by-side as a dead/legacy
branch. No concrete reason was found to keep the old path; per directive
Step 35's framing ("do not keep an unsafe old path merely to preserve
backward compatibility"), and because the old path's only distinguishing
property (looser validation) is exactly the defect being fixed, there is
no argument for retaining it.

## 2. What replaced it

**One new node, `tool_orchestration_node`** (`agent/nodes.py`), which:

1. Calls `orchestration.candidate_b_native_tools.call_cerebras_native_tools(state["query"])`
   — one real Cerebras Chat Completions request with the three real tools
   declared via `build_tool_declarations()` (JSON Schemas generated
   directly from `orchestration/models.py`'s pydantic argument schemas, so
   the declared schema and the validation schema can never drift).
2. For each raw `tool_calls[i]` the model returns, calls
   `orchestration.candidate_b_native_tools.parse_and_validate_tool_call()`
   — the sole path from a raw provider tool call to something this node
   will execute: recognized-function-name check against a static
   allowlist → JSON-arguments parse → typed `ToolCall` (pydantic)
   construction → `orchestration.registry.DEFAULT_REGISTRY.validate_call()`.
   A call that fails any step is recorded in `tool_call_history` (with a
   `call_id` and a typed `failure_category`) and never reaches execution.
3. For each call that passes validation, calls
   `orchestration.candidate_b_native_tools.execute_validated_call()` — the
   real `tools/pubmed_tool.py` / `tools/clinical_trials_tool.py` /
   `tools/chembl_tool.py` client method via the registry's bound execution
   function, with the same HTTP session, retry policy, and rate limiter
   those clients already use internally (unchanged).
4. Merges each successful call's `ToolResult.data` into
   `state["tool_results"]`, keyed by tool name, in the same
   list-of-parsed-dicts shape the old dispatch produced.

### Design decision: one combined node, not two

`planning_node` + `tool_execution_node` are collapsed into this single
node rather than kept as two nodes with new internals, because the frozen
architecture itself is **one** Cerebras round trip that both selects tools
and generates their typed arguments in the same response. There is no
intermediate "plan" object to hand from a first node to a second — the
only way to split this into two nodes would be either (a) calling Cerebras
twice for the same decision (which the measured/frozen architecture never
does, and would silently change what "Candidate B" means versus what was
benchmarked), or (b) an empty first node, which is not a real two-node
structure. `agent/graph.py`'s `StateGraph` edges were updated accordingly:

```
Old: query_analysis -> planning -> tool_execution -> synthesis -> verification -> [continue: tool_execution | report] -> report_generation -> END
New: query_analysis -> tool_orchestration -> synthesis -> verification -> [continue: tool_orchestration | report] -> report_generation -> END
```

The graph still has the same conditional self-reflection loop shape
(`should_continue_research`, unchanged); only the two nodes it used to
loop through are now one.

## 3. `AgentState` field changes

No fields were added to or removed from `agent/state.py` — the existing
`tools_to_call`, `tool_results`, `tool_call_history`, `errors`,
`intermediate_thoughts`, `total_tokens_used`, `current_step`,
`research_plan` are all reused with their existing declared types.
What changed is **what populates them and what each `tool_call_history`
entry contains**:

- Every `tool_call_history` entry now has a `call_id` field (e.g.
  `"step0-0"`), correlating it to the specific Cerebras tool-call response
  entry it came from. This did not exist before (Candidate A's
  disqualification for the missing-`call_id` hard-gate failure — see
  `docs/v2/PHASE3_WINNER_SELECTION.md` Section 1 — is exactly the defect
  this closes at the integration level, not just in `orchestration/`
  measurement code).
- Each entry also now carries an `operation` field (e.g.
  `"search_by_target"`) and an `error_category` field (one of
  `orchestration/models.py`'s `ParsedToolCallOutcome.failure_category`
  values — `unregistered_tool`, `arguments_json_invalid`,
  `schema_invalid`, `registry_error` — or `"tool_error"`/`"internal_error"`
  for a real execution-time failure, or `None` on success). The old shape
  only had `tool`/`query`/`params`/`success`/`results_count`/`error`/
  `timestamp` with no typed failure taxonomy.
- `tool_results[tool_key]` for ChEMBL can now also be populated by the
  `chembl_get_drug_info` operation (previously unreachable from
  `agent/nodes.py`, which only ever called `search_by_target`/
  `search_by_indication`). That operation's `ToolResult.data` is a single
  compound dict, not a list — `tool_orchestration_node` normalizes it to a
  one-item list before merging, so `tool_results[tool_key]` is always
  list-shaped, exactly as `synthesis_node`, `verification_node`, and
  `report_generation_node`'s `_build_chembl_compound_table`/citation
  builder already assume. This is what keeps those three nodes fully
  unchanged by this integration.
- `research_plan` (a JSON string) gains a new top-level `"orchestration"`
  key written by `tool_orchestration_node` (either
  `{"status": "no_execution_needs_clarification", "model_message": ...}`
  or `{"status": "executed", "calls": [...]}`), alongside the pre-existing
  `"research_plan"` (from the now-removed `planning_node` — no longer
  written) and `"synthesis"` (from `synthesis_node`, unchanged) keys.
  Nothing downstream reads the old `"research_plan"` sub-key by name
  (verified: `synthesis_node`/`verification_node`/`report_generation_node`
  only ever read `"synthesis"` out of this dict), so its absence is not a
  breaking read, only a leftover no-op possibility if some future code
  went looking for it.

## 4. The `NO_EXECUTION_NEEDS_CLARIFICATION` outcome

If Cerebras returns zero tool calls for a query (the model judged the
query ambiguous or not actionable, and chose not to guess), this is
`orchestration/models.py`'s `PlanStatus.NO_EXECUTION_NEEDS_CLARIFICATION`
— a valid, non-error outcome, not a best-guess fallback. Previously, the
equivalent failure path (`planning_node`'s JSON-parse/LLM error handler)
did the OPPOSITE — it silently called *all three* tools
(`state["tools_to_call"] = ["pubmed", "clinical_trials", "chembl"]`),
which is exactly the "guess instead of abstaining" behavior the frozen
architecture is designed to avoid.

In the new pipeline: `tools_to_call` is left `[]`, `tool_results` stays
`{}` (no key is ever set for any tool — not even to `None` — since no tool
was called), and `research_plan`'s `"orchestration"` block records the
abstention explicitly along with the model's raw message content (if any),
for debugging/audit purposes. `synthesis_node` and `verification_node`
were confirmed (by reading their existing code, unchanged by this
integration) to already handle empty/missing `tool_results` keys
gracefully — they never treat an absent tool_results key as "the tool ran
and found nothing," and the LLM prompts in both nodes are given the
(correctly empty) formatted-results dict, so a downstream report cannot
misrepresent an abstention as "no data was found by a real search."

## 5. Error handling / secret handling

- `state["errors"]` accumulation semantics are preserved: a Cerebras
  HTTP/config failure, a per-call validation failure, and a per-call
  execution failure are each still appended to `state["errors"]` as a
  human-readable string, exactly as before, just sourced from the new
  typed `ToolExecutionResult`/`ParsedToolCallOutcome`/`RegistryError`
  shapes instead of untyped exception text.
- `settings.CEREBRAS_API_KEY` is read the same way
  `orchestration/candidate_b_native_tools.py::call_cerebras_native_tools`
  already reads it — a `pydantic.SecretStr`, unwrapped via
  `.get_secret_value()` only at the HTTP `Authorization` header
  construction point, never logged/printed. `agent/nodes.py` does not
  touch `config/settings.py` or the key at all; it only calls the existing
  `call_cerebras_native_tools()` function, so this integration adds no new
  secret-handling code path. If the key is unset,
  `call_cerebras_native_tools()` raises `RuntimeError("CEREBRAS_API_KEY is
  not configured")`, which `tool_orchestration_node` catches and records
  in `state["errors"]` (instead of crashing `graph.invoke()`), with
  `tools_to_call` left empty for that run.
- No retry, rate-limit, or timeout policy was changed. The Cerebras call
  keeps its existing no-retry-on-purpose contract (single-shot tool
  selection measurement basis, see
  `orchestration/candidate_b_native_tools.py`'s module docstring) and its
  existing `wait_for_rate_limit` throttle; tool execution keeps the
  existing `tools/*.py` HTTP session/retry/rate-limit stack unchanged
  (execution goes through the same bound client methods the old dispatch
  called directly, just now via the registry's `execute_validated_call`
  wrapper instead of an `if/elif`).

## 6. Consumers that need to adapt

- **`MedAgent.run()` / the compiled graph** (`agent/graph.py`): no change
  to its public interface — `MedAgent(...).run(query)` still returns the
  same `AgentState` shape. A caller reading `final_state["tool_results"]`,
  `["citations"]`, `["final_report"]` is unaffected.
- **A caller reading `tool_call_history` entries and assuming the OLD
  fixed key set** (`tool`/`query`/`params`/`success`/`results_count`/
  `error`/`timestamp`) will still find all of those keys present
  (unchanged), plus the new `call_id`/`operation`/`error_category` keys.
  This is additive, not a removal, so existing consumers that only read
  the old keys (confirmed: `evaluation/metrics.py`'s
  `AgentMetrics.tool_precision`/`redundancy_rate`, which read `call["tool"]`
  /`call["params"]`) are unaffected.
- **`tests/test_nodes.py::test_hallucinated_tool_name_recorded_as_precision_miss`**
  was rewritten (not just updated) — see Section 7.
- **`test_phase2.py`** (a standalone root-level manual verification script,
  not under `tests/`, not part of the pytest suite run by this task or by
  CI) directly imports and calls `planning_node`/`tool_execution_node`,
  which no longer exist. This script is now stale. It is explicitly out of
  scope for this Step (only `tests/test_nodes.py` was in scope per the
  directive), and is called out here rather than silently left broken with
  no record of why.
- **`orchestration/source_selection.py`**'s module docstring references
  `agent/nodes.py`'s old `planning_node` by name in a few sentences of
  prose describing the historical defect it was written to compare
  against. Left unchanged — it is describing history (the old, now-removed
  behavior it was benchmarked against), not current code, and rewriting it
  is outside this Step's scope.

## 7. Test changes (`tests/test_nodes.py`)

- **`test_hallucinated_tool_name_recorded_as_precision_miss` — rewritten,
  not just adapted.** The old version injected a hallucinated tool name
  directly into `state["tools_to_call"]` and called the now-removed
  `tool_execution_node` — this only ever exercised the ad hoc
  dict-membership guard at execution time, never real tool *selection*
  (see `docs/v2/PHASE3_INITIAL_ORCHESTRATION_AUDIT.md` Section B, which
  states this explicitly about the old test). The new version mocks
  `agent.nodes.call_cerebras_native_tools` (same mocking boundary style
  `tests/test_candidate_b_native_tools.py` already uses — no real network
  call) to return a `CerebrasNativeToolsResult` containing one tool call
  with a hallucinated function name (`"pubchem_search"`), then calls the
  real `tool_orchestration_node`. This exercises the actual
  `parse_and_validate_tool_call()` → registry boundary for real, and
  asserts: the call is recorded in `tool_call_history` with a `call_id`
  and `error_category == "unregistered_tool"`, `tool_results` stays empty
  (nothing executed), and `tools_to_call` stays empty (the hallucinated
  name is never treated as a real selection). The test's original intent
  (hallucinated tool names must not vanish and must not reach execution)
  is fully preserved; only the code path under test changed from a bypass
  to the real pipeline.
- **`test_chembl_citations_use_parsed_field_names`,
  `test_chembl_citation_id_never_na_when_chembl_id_present`** — unchanged
  (only the module-level import line was updated). Both test
  `report_generation_node` directly against a hand-constructed
  `tool_results` dict; `report_generation_node` itself was not touched by
  this integration (it already only reads `state["tool_results"]`/
  `state["research_plan"]`, both of which keep the same shape it expects),
  so these tests' setup and assertions remain fully valid.
- **`test_token_usage_accumulates_across_calls`** — unchanged.
  `query_analysis_node` and `_accumulate_tokens` (the two things this test
  exercises) were not touched by this integration.

Test count: **206 passed before, 206 passed after** (`venv/bin/python -m
pytest tests/ -q`). No test was added or deleted net; one test
(`test_hallucinated_tool_name_recorded_as_precision_miss`) was rewritten
in place against the new pipeline, as described above.

## 8. Live integration check (Step 29 style)

Three small, stable, real queries were run end-to-end through the actual
compiled graph (`MedAgent().run(query)`, i.e. `agent/graph.py`'s real
`build_agent_graph()` + `agent/nodes.py`'s real nodes, no mocking), making
real Cerebras + PubMed/ClinicalTrials.gov/ChEMBL HTTP calls. See the
session's live run output for exact per-query tool selections, result
counts, and any errors encountered — this section is a pointer to that
run, not a restatement of benchmark numbers already established in
`docs/v2/PHASE3_HELDOUT_SUPPLEMENT_RESULTS.md`. The purpose of this check
is solely to confirm the new orchestration works *inside the full
LangGraph pipeline* (state flowing correctly into `synthesis_node`/
`verification_node`/`report_generation_node`, no crash, a real
`final_report` produced), not to re-measure routing quality.
