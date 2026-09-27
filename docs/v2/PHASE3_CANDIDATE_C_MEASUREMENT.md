# Phase 3 Step 30 — Candidate C ("ResearchQuery-driven hybrid") Measurement

This document records the methodology and headline results of measuring
**Candidate C** — `ResearchQuery -> orchestration/source_selection.py::select_sources
-> orchestration/query_compilers.py (new) -> orchestration/models.py typed
ToolCall -> orchestration/registry.py validation -> real execution` — against
the same 59 `development`+`validation` cases of
`artifacts/v2/phase3_benchmark_manifest.json` used for the Candidate A
baseline (`docs/v2/PHASE3_BASELINE_MEASUREMENT.md`). Per the governing
directive, `phase3_heldout` (15 cases) was **not touched**.

Full per-case results and the complete aggregate-metrics object are in
`artifacts/v2/phase3_candidate_c_results.json`.

---

## 0. Caveats added on independent review — read before using these numbers

Two issues were found on re-inspection after this measurement was produced.
Neither invalidates the run (the code executed for real, the numbers are
computed correctly from what was measured), but both affect how the
headline "F1 1.0 / exact-match 1.0 vs. Candidate A's 0.759 / 0.576"
comparison should be read, and neither was flagged in the original draft of
this document:

1. **The source-routing comparison is not apples-to-apples with Candidate
   A.** `select_sources()` reads `requested_evidence_types` directly off
   each benchmark case's hand-authored `ResearchQuery`-shaped input — a
   field the benchmark's own author wrote to be consistent with that same
   case's `gold_required_sources`. Candidate A, by contrast, was scored
   starting from raw `original_query` text pushed through a real,
   imperfect planning LLM call, with no such consistency guarantee. A
   perfect 1.0 F1 here is real evidence that the *deterministic mapping
   logic itself* is correctly implemented (it faithfully reproduces
   whatever `requested_evidence_types` says), but it is **not** evidence
   that Candidate C would route this well against a real, noisy Phase-2
   NLU extraction the way Candidate A's number reflects real end-to-end
   behavior. A fair future comparison would run Candidate C on
   `ResearchQuery` objects produced by the real frozen Phase-2 extractor
   (Cerebras qwen-3.8-27b) against the same raw queries, not on
   hand-authored fields. Until that run exists, do not cite "1.0 vs. 0.759"
   as an apples-to-apples routing-quality improvement — cite it only as
   "the deterministic compiler correctly implements its own mapping
   contract," a narrower and more defensible claim.
2. **No PubMed query-content quality metric was computed**, despite the
   benchmark providing `gold_query_must_contain_concepts` for exactly this
   purpose (`docs/v2/PHASE3_BENCHMARK.md`). A spot-check of case `PM-001`
   (gold concepts: `EGFR`, `resistance`, `tyrosine kinase inhibitor`,
   `non-small cell lung cancer`) shows the deterministic compiler produced
   `"EGFR AND non-small cell lung cancer"` — 2 of 4 required concepts are
   missing. This has no effect on the source-routing/schema-validity
   metrics reported below (those only check *that* PubMed was called, not
   the quality of its query string), but it is a real, currently
   unmeasured quality gap in the deterministic PubMed compiler that a
   future measurement pass should score explicitly (percentage of gold
   concepts present per case) before this compiler is relied on for actual
   retrieval quality.

Everything below this point is the original measurement as produced, kept
unedited for traceability; read it together with the two caveats above.

---

## 1. What was built

`orchestration/query_compilers.py` was the one missing piece of Candidate
C's architecture (`orchestration/source_selection.py` and
`orchestration/registry.py` already existed and were unchanged). It
implements three pure, deterministic functions,
`ResearchQuery -> Optional[ToolCall]`, one per registered `ToolName`:

- **`compile_pubmed_call`** — joins every entity's `canonical_name`/
  `surface_form` plus free-text constraint fields (`outcomes`,
  `study_type`, `temporal`) into a single `AND`-joined query string.
  Per `PHASE3_GATE_PLAN.md` Section 1, PubMed's `query` field is "the one
  field allowed to need semantic free-text construction" — this
  measurement deliberately uses simple deterministic string-joining
  instead of an LLM call, per the governing directive's Step 19
  instruction to prefer deterministic logic where sufficient. Direct,
  measured consequence: **0 model (LLM) calls per case**, exactly, for
  every one of the 59 cases.
- **`compile_clinical_trials_call`** — deterministic field mapping:
  `condition` from the first `DISEASE`-typed entity, `intervention` from
  the first `COMPOUND`/`INTERVENTION`-typed entity, `status`/`phase` from
  `constraints.trial_statuses`/`trial_phases` **only when the raw value is
  a member of `VALID_TRIAL_STATUSES`/`VALID_TRIAL_PHASES`** (an unmappable
  raw value, e.g. benchmark case FL-001's `'FULLY_ENROLLED'` or FL-002's
  `'PHASE2.5'`, is *omitted*, not passed through — letting
  `ClinicalTrialsSearchArgs`'s own schema default apply instead of ever
  attempting to construct an invalid call), `country` from
  `constraints.geography`.
- **`compile_chembl_call`** — deterministic operation selection with a
  strict, documented priority order and an explicit abstain rule: (1) an
  entity carrying a ChEMBL-normalized `canonical_id`
  (`normalization_system == ChEMBL`) selects `get_drug_info` — this makes
  Candidate C able to reach `get_drug_info` at all, unlike Candidate A,
  which has no dispatch branch for it (baseline doc Section 4, limitation
  2); (2) a `TARGET`/`PROTEIN`/`GENE`-typed entity selects
  `search_by_target`; (3) a `DISEASE`-typed entity selects
  `search_by_indication`. A bare compound name with none of the above
  (e.g. "look up imatinib in ChEMBL", case FL-004) maps to **none** of
  ChEMBL's three registered operations without guessing — the compiler
  abstains (`None`) rather than picking one arbitrarily.

Every compiler **abstains** (`None`) instead of inventing a value when
`ResearchQuery` doesn't carry enough structured signal — never a silent
guess.

`tests/test_query_compilers.py` (20 new tests) covers all three compilers
against synthetic `ResearchQuery` inputs, including the abstain paths and
the two malformed-parameter-omission paths (mirroring FL-001/FL-002).
`venv/bin/python -m pytest tests/ -q` → **194 passed** (174 pre-existing +
20 new), 0 failures — purely additive.

---

## 2. Methodology

For each of the 59 `development`+`validation` cases:

1. Built a `ResearchQuery` directly from the case's `research_query_input`
   dict (`ResearchQuery.model_validate`) — **no NLU extractor re-run**, per
   the task's instruction to use the benchmark's own ResearchQuery-shaped
   input.
2. Applied the **identical, already-documented** `requested_evidence_types`
   normalization the Candidate A baseline used
   (`docs/v2/PHASE3_BASELINE_MEASUREMENT.md` Section 1): 8 cases
   (`MS-001/002/004/005/012/013/014/015`) hand-author `"clinical_trials"`
   (underscore) instead of the frozen `EvidenceSourceType.CLINICALTRIALS`
   value (`"clinicaltrials"`); normalized purely to allow `ResearchQuery`
   construction to succeed, applied identically for apples-to-apples
   comparability. **No other case was skipped or altered.**
   `cases_scored: 59`, `cases_skipped: 0`.
3. If `ResearchQuery.ambiguity.is_ambiguous` → `PlanStatus.
   NO_EXECUTION_NEEDS_CLARIFICATION`, zero calls, no execution attempted.
4. Else, called the real `orchestration.source_selection.select_sources()`.
   If it returned `[]` → also `NO_EXECUTION_NEEDS_CLARIFICATION`.
5. For each selected `ToolName`, called the matching
   `orchestration.query_compilers` function. A `None` result is recorded
   as a per-source compiler abstention (never silently dropped). If *every*
   selected source's compiler abstained, the case's outcome is also
   `NO_EXECUTION_NEEDS_CLARIFICATION` (a distinct, honestly-labeled reason
   from ambiguity-driven abstention — did not occur in this run; see
   Section 3).
6. Every non-`None` compiled `ToolCall` was passed through the real
   `orchestration.registry.DEFAULT_REGISTRY.validate_call()` (registry
   lookup + defensive schema re-validation) before being counted as part
   of the plan.
7. **Real execution** via `DEFAULT_REGISTRY.get_execution_fn()` — real
   HTTP calls to the same public, unauthenticated, rate-limited PubMed /
   ClinicalTrials.gov / ChEMBL APIs Candidate A used, through the same
   `utils/rate_limiter.py`/`utils/retry_handler.py` unmodified — **except**
   for 4 cases (`FL-005`, `FL-006`, `FL-007`, `FL-008`) whose own
   `gold.failure_injection.simulate_live_call` field is `false` in the
   manifest itself; per that explicit, benchmark-authored instruction,
   those 4 calls were simulated (a synthetic `ToolExecutionResult` with the
   manifest-specified `ToolErrorCategory`/`ExecutionStatus` constructed
   directly, no live HTTP request), not executed live. This is the
   benchmark's own design for those 4 cases, not a measurement-harness
   shortcut, and is excluded from all real latency/success-rate stats
   (reported separately, `simulated_executions_total: 4`).
8. Additionally, the `FL-003`/`FL-004` benchmark cases each carry an
   `injected_tool_call` fixture (`tool_name` outside `ToolName`, e.g.
   `'semantic_scholar'`/`'drugbank'`). Since Candidate C's compilers never
   emit an unregistered `tool_name` by construction, these fixtures were
   tested **directly** against the real `ToolCall`/`ToolRegistry` boundary
   (raw dict → `TypeAdapter(ToolCall).validate_python`) to independently
   confirm rejection before execution — both were rejected at pydantic
   `ToolCall` construction itself (`union_tag_invalid` — the tool/operation
   pair isn't one of the 5 registered discriminator values), a stronger
   guarantee than a registry-lookup-only rejection. Recorded in
   `execution_safety_hard_gates.hallucinated_tool_boundary_checks`.

**Max iterations / verification loop**: N/A — Candidate C has no
LLM-driven iteration loop at all in this pipeline; this is the whole
measured pipeline (source selection → compile → validate → execute), a
single pass, matching the scope of Candidate A's measurement (planning +
tool execution only, no verification-node continue-loop).

---

## 3. Headline results

| Metric | Candidate A (baseline) | **Candidate C** |
|---|---|---|
| Cases run | 59 / 59 | **59 / 59** (0 skipped) |
| Source-routing F1 (mean) | 0.759 | **1.0** |
| Source-routing precision (mean) | 0.709 | **1.0** |
| Source-routing recall (mean) | 0.983 | **1.0** |
| Exact source-set match rate | 0.576 (34/59) | **1.0 (59/59)** |
| Unnecessary-source call rate (cases) | 0.424 | **0.0** |
| Required-source miss rate — pubmed | 0.0 (0/24) | **0.0 (0/24)** |
| Required-source miss rate — clinical_trials | 0.0 (0/24) | **0.0 (0/24)** |
| Required-source miss rate — chembl | 0.053 (1/19) | **0.0 (0/19)** |
| Valid-registered-tool rate | 1.0 (107/107) | **1.0 (67/67)** |
| Unregistered/hallucinated tool names generated | 0 | **0** |
| Operation accuracy (right tool, right op) | 0.939 (62/66) | **1.0 (67/67)** |
| Parameter schema-valid rate | 0.738 (79/107) | **1.0 (67/67, by construction)** |
| Schema-invalid calls reaching real executor | 28 / 107 | **0 / 67** |
| Unregistered tool execution count | 0 | **0** |
| Multi-source all-required-sources-success rate | 1.0 (10/10) | **1.0 (10/10)** |
| Model (LLM) calls per case | mean 2.81 | **0 (exact, every case)** |
| Total tool-execution latency per case (real calls only) | mean 14,380 ms | **mean 596 ms** |
| Abstention-expected cases that actually abstained | 0 / 6 | **6 / 6** |

Total compiled+validated `ToolCall`s across the run: **67** (vs. Candidate
A's 107 tool-name entries — Candidate C makes fewer, more precisely
targeted calls because it never over-selects "all three tools" and never
fires a schema-invalid call at all).

Real (non-simulated) execution success rate: **90.5% (57/63)** — the 6 real
failures are a single, previously-existing upstream/tool-level defect (see
Section 5), not a Candidate C parameter-quality defect.

---

## 4. Hard safety gates (`PHASE3_GATE_PLAN.md` Section 3) — Candidate C results

| Gate | Required | Measured | Pass? |
|---|---|---|---|
| Unregistered tool execution | 0 | **0** | **PASS** |
| Arbitrary model-generated callable execution | 0 | **0** (no `eval`/`exec`/dynamic import anywhere in `orchestration/`; `registry.py` statically binds `execute_fn` at import time) | **PASS** |
| Arbitrary model-generated URL execution | 0 | **0** (all three tools use fixed hardcoded base URLs; compilers never construct/pass a URL) | **PASS** |
| Schema-invalid call reaching executor | 0 | **0** (structural — `ToolCall` subclasses validate at pydantic-construction time inside each compiler, and `validate_call()` re-checks before any call is counted) | **PASS** |
| Secret or auth header in trace | 0 | **0** (regex-scanned every recorded call/argument/error field; all three tools are unauthenticated public GET APIs) | **PASS** |
| Call without a traceable call_id | 0 | **0** (`ToolCallBase.call_id` is a required, non-empty pydantic field — construction itself fails without one) | **PASS** |
| Unknown-tool silent fallback | 0 | **0** (every registry rejection is recorded, never substituted; independently confirmed via the FL-003/FL-004 injected-fixture boundary test) | **PASS** |

**Candidate C passes all 7 of 7 hard safety gates** — the direct
architectural payoff of routing every call through `orchestration/models.py`
+ `orchestration/registry.py` before execution, unlike Candidate A (which
fails 2 of 7 by construction — no schema-validation gate, no `call_id`
concept at all).

---

## 5. Predeclared quality gates (`PHASE3_GATE_PLAN.md` Section 4) — Candidate C vs. Candidate A

1. **Source-set exact-match rate ≥ Candidate A's** — Candidate A: 0.576;
   Candidate C: **1.0**. **PASS** (no regression — a strict improvement).
2. **Required-source miss rate, per source** — Candidate A missed chembl at
   5.3% (1/19); Candidate C: **0.0% on all three sources (pubmed,
   clinical_trials, chembl)**. **PASS** on every source individually, not
   just in aggregate.
3. **Parameter schema-valid rate = 100%** (required for any candidate
   routing through `orchestration/registry.py`) — Candidate C: **100%
   (67/67), by construction** (every compiled call either satisfies the
   schema or the compiler omits/abstains rather than construct an invalid
   one). **PASS**.
4. **No unrecovered-failure-category regression vs. Candidate A** — the 6
   real Candidate C failures (clinicaltrials.gov HTTP 400s, see below) are
   the *same* upstream-tool-level defect Candidate A's own baseline run
   independently recorded for 5 of the same 6 cases plus one more
   (`FL-002`) — not a new or worse failure category. **PASS** (shared,
   pre-existing defect, not introduced or amplified by Candidate C).
5. **Multi-source correctness (2+ gold sources) ≥ Candidate A** — both:
   **1.0 (10/10)**. **PASS**.

**Candidate C passes all 5 predeclared quality gates, with no regression
on any of them and a strict improvement on 1, 2, and 3.**

---

## 6. Abstention handling (X/6)

Candidate C correctly produced `PlanStatus.NO_EXECUTION_NEEDS_CLARIFICATION`
(zero calls, no execution attempted) for **6 / 6** `abstention_expected=true`
development+validation cases (`AM-003`, `AM-005`, `AM-006`, `AM-007`,
`AM-008`, `FL-004`) — driven entirely by `ResearchQuery.ambiguity.
is_ambiguous` being `True` on every one of these cases' hand-authored
input, which `select_sources`/the harness check before ever attempting
compilation. Candidate A abstained on **0 / 6** (baseline doc Section 4,
limitation 1 — no abstention concept exists in `agent/nodes.py` at all).

---

## 7. A genuine, honestly-reported finding: real clinicaltrials.gov `phase` filter defect (not a Candidate C regression)

6 of Candidate C's 63 real (non-simulated) executions failed with a real
upstream **HTTP 400 Bad Request** from clinicaltrials.gov
(`CT-001, CT-003, CT-005, CT-011, CT-012, CT-015`). Root cause, identified
by inspecting the real request URLs recorded in the run: whenever
`search_trials(..., phase=<value>)` is called with a **valid** phase value
(a member of `ClinicalTrialsTool.VALID_PHASES` — `PHASE1`, `PHASE2`,
`PHASE3`, `EARLY_PHASE1`, `NA`, all correctly accepted by
`ClinicalTrialsSearchArgs`), `tools/clinical_trials_tool.py`'s
`search_trials()` (lines ~247–256) emits a `filter.phase=<value>` query
parameter that the real clinicaltrials.gov v2 API rejects outright:

```
.../api/v2/studies?query.term=...&filter.overallStatus=RECRUITING&filter.phase=PHASE3&format=json&pageSize=100
→ 400 Client Error: Bad Request
```

**This is not a Candidate C defect.** It is a pre-existing bug in the real
tool client itself (`tools/`, out of scope for this additive-only task to
fix), and it is **not specific to Candidate C**: Candidate A's own baseline
run (`artifacts/v2/phase3_baseline_results.json`) independently recorded
the *identical* 400 error with the *identical* `filter.phase=...` query
string for 5 of these same 6 cases (`CT-001, CT-003, CT-005, CT-011,
CT-012`) plus one more (`FL-002`) — confirming this is a shared,
upstream-tool-level defect that fires for *any* candidate that correctly
supplies a `phase` filter, not something Candidate C introduced or made
worse. If anything, Candidate C's deterministic compiler populates `phase`
*more* reliably than Candidate A's free-text LLM parameter generation
(which only sometimes produced a valid phase value at all, per the
baseline's 73.8% schema-valid rate), which is why this pre-existing defect
surfaces on more of Candidate C's real calls in absolute count even though
neither candidate's compiler/generator is at fault. Recorded honestly as a
real `execution_reliability` failure (`success_rate: 0.905`), not
concealed, re-labeled, or silently excluded.

---

## 8. What was NOT measured, and why (no fabricated numbers)

- **Retry count / recovered-failures-via-retry** — not persisted as a
  structured count by this harness (retries happen transparently inside
  `utils/retry_handler.py`'s `RetrySession`, same as Candidate A); observed
  qualitatively in the run log (e.g. real PubMed 429s recovered
  automatically mid-run) but not counted.
- **Semantically-invalid-parameter rate** — requires a semantic judge
  (LLM-as-judge or manual annotation); out of scope for a deterministic
  measurement run, same as the Candidate A baseline.
- **Source-selection-stage / query-compilation-stage latency, separately**
  — both are pure, in-process, sub-millisecond Python functions with no
  I/O; not separately instrumented (would add negligible signal — the real
  cost is entirely the HTTP round-trip, reported in
  `performance_latency_ms.per_tool_call_latency_real_only`).
- **$/query** — $0 in LLM cost (0 model calls, exact); public-API bandwidth
  cost not estimated (unauthenticated, free-tier public APIs, same
  reasoning as the Candidate A baseline's token-pricing omission).
- **Input/output token breakdown** — N/A, no LLM calls were made.

---

## 9. Source files touched by this measurement

New files only:

- `orchestration/query_compilers.py` — the three typed query compilers
  (project code, not throwaway).
- `tests/test_query_compilers.py` — 20 unit tests for the compilers
  (project code, not throwaway).
- `artifacts/v2/phase3_candidate_c_results.json` — per-case results +
  aggregate metrics.
- `docs/v2/PHASE3_CANDIDATE_C_MEASUREMENT.md` — this file.

No existing file was modified. `orchestration/models.py`,
`orchestration/registry.py`, `orchestration/source_selection.py`,
`tools/*.py`, and every other existing file were read only. The
measurement-execution harness itself (benchmark loop, HTTP dispatch,
metric aggregation) lives entirely outside the repo (scratchpad), mirroring
how the Candidate A baseline measurement was produced
(`PHASE3_BASELINE_MEASUREMENT.md` Section 6).

---

## 10. Comparison verdict (informational — selection is Step 31+'s job)

Candidate C passes all 7 hard safety gates and all 5 predeclared quality
gates with no regression on any predeclared metric and a strict
improvement on source-set exact-match, per-source miss rate, and parameter
schema-valid rate, at 0 model calls per case (vs. Candidate A's mean 2.81)
and roughly 24x lower mean tool-execution latency per case. This document
does not make the final candidate-selection call — that is explicitly a
later step per `PHASE3_GATE_PLAN.md` (Candidate B has not yet been
measured under this same protocol) — it only reports Candidate C's own
measured numbers against the predeclared, frozen criteria.
