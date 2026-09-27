# Phase 3 Gate Plan

Predeclared, BEFORE any candidate benchmarking happens, per the governing
Phase 3 directive Steps 9-12. Thresholds and candidate architectures are
fixed here and must not be adjusted after seeing results.

---

## 1. The three candidates (Step 9)

### Candidate A — Legacy baseline

The current `planning_node` + `tool_execution_node` pipeline in
`agent/nodes.py`, exactly as documented in
`docs/v2/PHASE3_INITIAL_ORCHESTRATION_AUDIT.md`: a second free-text LLM
call for source/tool selection (ignoring `ResearchQuery.requested_evidence_types`),
a third free-text LLM call per tool for parameter generation, hardcoded
`if/elif` dispatch, dict-membership allowlist check only at execution time.

Measured honestly, not intentionally degraded and not intentionally
improved beyond its current real behavior. The only adaptation permitted:
feeding it the real frozen Phase-2 `ResearchQuery`/`original_query` as
input (since that's the actual current call site), not a hypothetically
worse input. This is the Phase-3 BEFORE system (Step 17).

### Candidate B — Provider-native tool calling

**Availability confirmed** (checked live against current Cerebras docs,
2026-09-24): Cerebras' Chat Completions API supports OpenAI-style `tools`/
`tool_choice`/`parallel_tool_calls`, and `qwen-3.8-27b`'s own model page
explicitly lists "Tool Calling" and "Parallel Tool Calling" among its
capabilities (sources: `https://inference-docs.cerebras.ai/api-reference/chat-completions`,
`https://inference-docs.cerebras.ai/models/qwen-3.8-27b`). Candidate B is
therefore **AVAILABLE**, not marked UNAVAILABLE.

Architecture: `ResearchQuery` (or minimally its `original_query` +
structured fields as needed) is given to `qwen-3.8-27b` with the three real
tools declared via the `tools` parameter (JSON-Schema argument specs
matching `orchestration/models.py`'s per-tool argument schemas exactly —
`PubMedSearchArgs`, `ClinicalTrialsSearchArgs`, three ChEMBL operations).
The model's returned `tool_calls` are parsed and **must still pass through
our own `orchestration/registry.py` `validate_call` boundary** before
execution — provider-native tool calling is explicitly not permission to
skip our allowlist/schema validation (contract Section 5, directive Step
21). If the model names a tool/operation outside our registry, or emits an
argument shape that fails our schema, that is a Candidate-B failure to
record, not a crash and not a silent pass-through.

### Candidate C — ResearchQuery-driven hybrid

`ResearchQuery` -> `orchestration/source_selection.py::select_sources`
(deterministic, from `requested_evidence_types`) -> a source-specific typed
query compiler per selected source (deterministic field mapping from
`ResearchQuery.constraints`/`entities` where possible; constrained-model
assistance only for genuinely free-text fields, e.g. PubMed's `query`
string) -> `orchestration/models.py` typed `ToolCall` -> `orchestration/registry.py`
validation -> execution. This is the architecture the `orchestration/`
package (Steps 5-8) was built to support. Not assumed to win — measured
like the other two.

---

## 2. Predeclared evaluation metrics (Step 10)

**Source routing:** Precision, Recall, F1 against gold required-source set;
exact source-set match rate; required-source miss rate; unnecessary-source
call rate.

**Tool selection:** valid-registered-tool rate; nonexistent/unregistered-
tool generation rate; operation accuracy (right tool, right operation).

**Parameter quality:** schema-valid rate; required-field accuracy; per-field
accuracy; canonicalization correctness (e.g. trial status/phase matching
`VALID_TRIAL_STATUSES`/`VALID_TRIAL_PHASES`); semantically-invalid-parameter
rate.

**Execution safety (must be 0 — see Section 3):** unregistered calls
reaching the executor; malformed calls reaching the executor; arbitrary
URL/callable execution; unsafe-dispatch incidents.

**Execution reliability:** successful executions; transient failures;
recovered failures (via retry); unrecovered failures; retry count; timeout
rate; upstream-error rate.

**Result utility (deterministic only, no Phase-4 relevance semantics):**
nonempty-result-when-expected rate; empty-result rate.

**Multi-source:** all-required-sources-success rate; partial-success rate;
missed-source rate; unnecessary-source rate; parallel-execution success
(where implemented).

**Performance:** planning/source-selection latency, parameter-generation
latency, orchestration overhead, external API/network latency, and total
tool-stage latency — each reported as mean/P50/P90/P95/max, separately.

**Cost:** model calls per orchestration; input/output tokens; $/query where
applicable (measured, not projected, unless explicitly labeled a
projection — same discipline as the Phase-2 ledger).

**Traceability:** valid call-ID rate; execution-result-linked-to-call rate;
error-category completeness; sanitized-trace completeness (no secrets).

Explicitly NOT included: semantic relevance of retrieved evidence (Phase 4
territory).

---

## 3. Hard safety gates (Step 11) — frozen, non-negotiable, all must equal 0

| Gate | Required value |
|---|---|
| Unregistered tool execution | 0 |
| Arbitrary model-generated callable execution | 0 |
| Arbitrary model-generated URL execution | 0 |
| Schema-invalid call reaching executor | 0 |
| Secret or auth header in trace | 0 |
| Call without a traceable call_id | 0 |
| Unknown-tool silent fallback | 0 |

Any candidate violating any one of these is disqualified outright,
regardless of how strong its other metrics are. These gates are not
weakened after seeing candidate results.

---

## 4. Predeclared quality gates (Step 12)

Thresholds set from: the product contract, the Candidate-A baseline
measured in Step 17 (not yet measured at the time this document is
written — thresholds below are stated as *relative-to-baseline*
requirements, not absolute numbers invented in advance of ever seeing real
baseline data, since inventing an absolute number now risks exactly the
kind of unfounded target the governing methodology prohibits), and Phase-3
risk level (this layer gates every downstream retrieval call — a
correctness regression here silently corrupts all later phases).

A winning candidate must, on the frozen Phase-3 validation split:

1. **Source-set exact-match rate** ≥ Candidate-A's measured rate (no
   regression) — the *point* of Phase 3 is not to make source selection
   worse while making dispatch safer.
2. **Required-source miss rate** — per-source, not just in aggregate. A
   candidate with excellent aggregate F1 but systematically missing one
   entire source (e.g. perfect PubMed + poor ClinicalTrials) FAILS this
   gate even if its aggregate routing F1 looks acceptable — directive Step
   12 names this exact failure mode explicitly and it is treated as
   disqualifying, not averaged away.
3. **Parameter schema-valid rate** = 100% for any candidate whose
   architecture routes ToolCalls through `orchestration/registry.py`
   (Candidates B and C) — a schema-invalid call must never reach execution
   by construction (this is a Section-3 hard gate restated as a quality
   requirement so it is checked at the per-candidate level, not only in
   aggregate).
4. **No unrecovered failure category regression** vs. Candidate A on the
   same validation cases (a candidate must not turn a Candidate-A recoverable
   failure into an unrecovered one).
5. **Multi-source correctness**: for validation cases with 2+ gold required
   sources, all-required-sources-success rate must not regress vs.
   Candidate A.

Any candidate failing gate 1 is disqualified. **Any candidate failing gate 2
on a per-source basis is disqualified**, independent of aggregate score —
this is the specific protection against a high-composite-score candidate
hiding a systematic per-source defect (directive Step 12's own example).

If no candidate passes every hard safety gate (Section 3) and every quality
gate above: **Phase 3 remains OPEN.** No "least bad" selection.

---

## 5. Traceability of this document

- Candidate B availability finding: live Cerebras docs, verified
  2026-09-24, cited above.
- Candidate architectures grounded in `docs/v2/PHASE3_INITIAL_ORCHESTRATION_AUDIT.md`
  (Candidate A) and `orchestration/models.py`, `orchestration/registry.py`,
  `orchestration/source_selection.py` (Candidate C's typed layer, already
  implemented and independently test-verified: 174/174 tests passing at
  time of writing, HEAD `14a59b9e4c514714883245e8ac1e95a2f1457775`
  unchanged).
- Quality gate thresholds are stated relative to Candidate A's own measured
  baseline (not yet measured) rather than as invented absolute numbers, to
  avoid setting an unfounded target before real data exists — consistent
  with the project's standing anti-fabrication rule.
