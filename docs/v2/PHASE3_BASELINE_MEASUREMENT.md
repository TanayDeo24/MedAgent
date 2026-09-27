# Phase 3 Step 17 — Candidate A (Legacy) Baseline Measurement

This document records the methodology and headline results of the Phase-3
BEFORE measurement: the CURRENT/legacy `planning_node` + `tool_execution_node`
pipeline (`agent/nodes.py`), driven for real against the 59
`development`+`validation` cases of
`artifacts/v2/phase3_benchmark_manifest.json` (`benchmark_version 1.0.0`).
Per the governing directive, `phase3_heldout` (15 cases) was **not touched**.

Full per-case results and the complete aggregate-metrics object are in
`artifacts/v2/phase3_baseline_results.json`. **No existing source file was
modified** to produce this measurement — see Section 5.

---

## 1. Methodology

For each of the 59 cases:

1. Built a `ResearchQuery` (`nlu/schemas.py`) from the case's hand-authored
   `research_query_input` dict.
2. Converted it via the real `nlu.to_legacy_research_plan()` adapter
   (`nlu/__init__.py:80-127`) — the actual conversion path documented in
   `PHASE3_INITIAL_ORCHESTRATION_AUDIT.md` Section A.
3. Built a minimal `AgentState` via `agent.state.create_initial_state(query=original_query, max_iterations=10)`
   and set `state["research_plan"] = json.dumps(legacy_plan)`.
4. Called the REAL `agent.nodes.planning_node(state)`, then the REAL
   `agent.nodes.tool_execution_node(state)` — no mocking of the LLM
   (NVIDIA NIM, per `config/llm_config.py`) or of the PubMed/ClinicalTrials.gov/
   ChEMBL HTTP calls. Real rate limiters and retry handling (`utils/rate_limiter.py`,
   `utils/retry_handler.py`) were exercised unmodified; a handful of real
   transient `503 Service temporarily overloaded` provider errors were
   observed and recovered by the existing retry logic during the run.
5. Recorded `tools_to_call`, `tool_call_history`, latencies, token usage, and
   errors, then compared against each case's `gold` block and — retrospectively
   — against `orchestration/models.py`'s typed argument schemas (the legacy
   pipeline itself does not validate against them; this is purely a
   measurement-time check to get a real schema-valid rate for the legacy
   system, as the task required).

**Max iterations / verification loop**: only `planning_node` +
`tool_execution_node` were driven (one pass each), not the
`verification_node` continue-loop — this matches the task's stated scope
("planning_node ... then tool_execution_node") and Candidate A's definition
in `PHASE3_GATE_PLAN.md` Section 1, which is scoped to exactly these two
nodes.

### Assumption / documented adaptation

8 of the 59 cases (`MS-001, MS-002, MS-004, MS-005, MS-012, MS-013, MS-014,
MS-015`) hand-author `research_query_input.requested_evidence_types` using
`"clinical_trials"` (with underscore), which does not validate against the
frozen `EvidenceSourceType` enum in `nlu/taxonomy.py` (which uses
`"clinicaltrials"`, no underscore) — a benchmark-manifest/schema naming
drift, not a code defect. Per the audit (Section A), `requested_evidence_types`
is **provably never read** by `to_legacy_research_plan()` (grep confirms only
`nlu/schemas.py`/`nlu/extractor.py` touch it — it is computed by the NLU
stage and dropped on the floor before `planning_node` ever runs). The
harness therefore normalizes only this one field's string values
(`clinical_trials` → `clinicaltrials`) before constructing the `ResearchQuery`
object, purely to allow schema construction to succeed; no field that
actually reaches `planning_node`/`tool_execution_node` was touched. This is
recorded per-case in `phase3_baseline_results.json`'s `assumptions` field.
Without this normalization, these 8 cases (all `multi_source`) would have
had to be skipped entirely; the fix is confirmed inert on system behavior
and is disclosed here rather than silently applied.

**No other case was skipped.** `cases_scored: 59`, `cases_skipped: 0`.

---

## 2. Headline results

| Metric | Value |
|---|---|
| Cases run | **59 / 59** (44 development + 15 validation) |
| Source-routing F1 (mean) | **0.759** |
| Source-routing precision (mean) | 0.709 |
| Source-routing recall (mean) | 0.983 |
| Exact source-set match rate | **0.576** (34/59) |
| Unnecessary-source call rate (cases) | 0.424 |
| Required-source miss rate — pubmed | 0.0 (0/24) |
| Required-source miss rate — clinical_trials | 0.0 (0/24) |
| Required-source miss rate — chembl | **0.053** (1/19) |
| Valid-registered-tool rate | 1.0 (107/107 selected names) |
| Unregistered/hallucinated tool names generated | 0 |
| Operation accuracy (right tool, right operation) | 0.939 (62/66 — see structural limitation below) |
| Parameter schema-valid rate (vs. `orchestration/models.py`, retrospective) | **0.738** (79/107) |
| Schema-invalid calls that reached the real executor | **28 / 107** |
| Unregistered tool execution count | **0** |
| Multi-source all-required-sources-success rate | 1.0 (10/10 multi-source gold cases) |
| Model (LLM) calls per case | mean 2.81, P50 3, max 4, min 2 |
| Total tokens per case | mean 5228, P50 5251, P95 8910 |
| Total tool-orchestration latency per case | mean 23.4s, P50 20.0s, P95 42.0s, max 62.0s |
| Abstention-expected cases that actually abstained | **0 / 6** |

---

## 3. Hard safety gates (`PHASE3_GATE_PLAN.md` Section 3) — Candidate A results

| Gate | Required | Measured | Pass? |
|---|---|---|---|
| Unregistered tool execution | 0 | **0** | PASS |
| Arbitrary model-generated callable execution | 0 | 0 (static audit + no code path found; not independently re-verified beyond audit) | PASS (by audit) |
| Arbitrary model-generated URL execution | 0 | 0 (all three tools use fixed hardcoded base URLs; not independently re-verified beyond audit) | PASS (by audit) |
| Schema-invalid call reaching executor | 0 | **28** | **FAIL** |
| Secret or auth header in trace | 0 | 0 (manually inspected all recorded fields) | PASS |
| Call without a traceable call_id | 0 | **107 (all of them)** | **FAIL** |
| Unknown-tool silent fallback | 0 | **0** (verified empirically: every invalid name recorded as a failed history entry, never substituted) | PASS |

**Candidate A fails 2 of the 7 hard safety gates, by construction** — not
due to any per-case anomaly in this run, but because the legacy pipeline has
no parameter-schema validation boundary (audit Section C) and no `call_id`
concept anywhere in `AgentState`/`tool_call_history` (audit Section G). This
is exactly the kind of defect Phase 3's `orchestration/` layer (Candidates B
and C) is meant to fix, and is why Candidate A is measured here as a
baseline, not a contender for selection.

---

## 4. Named limitations found (not silently absorbed)

1. **No abstention concept.** Confirmed empirically: 0 of 6
   `abstention_expected=true` cases in development+validation (5
   `ambiguous_abstain` + `FL-004`) resulted in the legacy pipeline abstaining
   — every one produced a non-empty `tools_to_call` and attempted real tool
   execution. `planning_node`'s exception-fallback is
   `["pubmed","clinical_trials","chembl"]` (all three), never `[]`; there is
   no `PlanStatus.NO_EXECUTION_NEEDS_CLARIFICATION` equivalent anywhere in
   `agent/nodes.py`/`agent/state.py`.
2. **`ChEMBLTool.get_drug_info` is structurally unreachable** from
   `tool_execution_node`'s LLM-driven dispatch — only `search_by_target`/
   `search_by_indication` are selectable (the chembl `if/elif`'s nested
   `query_type` dispatch never considers `get_drug_info`; it is only called
   internally by `_backfill_chembl_names`). The 4 benchmark cases whose gold
   operation is `chembl`/`get_drug_info` (`CH-013`, `CH-014`, `MS-009`,
   `MS-012`) are therefore operation-accuracy failures by architecture, not
   by model error.
3. **No parameter-schema validation gate before execution** — 28 of 107
   real tool-call parameter sets generated by the query-generation LLM call
   failed retrospective validation against `orchestration/models.py`'s typed
   argument schemas, yet all 28 were executed against the real tool method
   anyway (this is the Section-3 hard-gate failure above).
4. **No call-level correlation ID anywhere** in `AgentState`/
   `tool_call_history` — 107/107 real tool calls in this run lacked a
   traceable `call_id` by construction.
5. **Per-tool-call latency is not recorded** in `tool_call_history` (only a
   completion timestamp, no start time or `latency_ms` copy from
   `ToolResult.metadata`) — see Section 6, `NOT MEASURED` items.

---

## 5. What was NOT measured, and why (no fabricated numbers)

The following predeclared metrics (`PHASE3_GATE_PLAN.md` Section 2) are
recorded as `NOT MEASURED` in `phase3_baseline_results.json`, with the
specific reason inline at each field, rather than estimated:

- **Semantically-invalid-parameter rate** — requires a semantic judge
  (LLM-as-judge or manual annotation); out of scope for a deterministic
  reproduction run.
- **Retry count / recovered-failures-via-retry** — `tool_call_history` does
  not record retry counts; retries happen transparently inside
  `utils/retry_handler.py`'s `RetrySession`, invisible at the orchestration
  layer (confirms audit Section G).
- **Per-tool-call latency breakdown** — `tool_call_history` records only a
  completion timestamp, not a start time or `latency_ms`; reconstructing it
  would require patching production code, which this task explicitly avoided.
  The measured `tool_execution_stage_total_per_case` (mean 14.4s, P50 11.2s)
  is the real, whole-stage total instead.
- **Input/output token breakdown** — `_accumulate_tokens` only sums
  `total_tokens`; the per-call input/output split is never persisted to
  `AgentState`.
- **$/query** — no per-token pricing configuration exists anywhere in this
  codebase for the NVIDIA NIM key used; not estimated from an external price
  this run did not verify against actual billing.
- **Timeout/rate-limit/HTTP-error rates** are reported only as a
  **string-matched heuristic** over the free-text `error` field (legacy has
  no typed `ToolErrorCategory`), explicitly labeled heuristic, not exact.
- **`error_category_completeness`** is structurally 0.0 against the typed
  `ToolErrorCategory` enum, since legacy errors are untyped strings.

---

## 6. Source files touched by this measurement

None. Only new files were added:

- `artifacts/v2/phase3_baseline_results.json` (per-case results + aggregate metrics)
- `docs/v2/PHASE3_BASELINE_MEASUREMENT.md` (this file)

`agent/nodes.py`, `agent/state.py`, `nlu/__init__.py`, `orchestration/models.py`,
and every other existing file were read only, never edited. The
`requested_evidence_types` normalization described in Section 1 happens
entirely inside the throwaway measurement harness (not committed to the
repo as a project file), never in any file under `agent/`, `nlu/`, or
`orchestration/`.
