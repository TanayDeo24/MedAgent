# Phase 9 — Reliability / Performance: Steps 8-11 (Fault Matrix, Concurrency, Rate Limiter, Formal Boundedness)

This document covers ONLY Steps 8-11 of the Phase 9 governing directive:
the systematic fault-injection matrix, the concurrency safety audit, the
rate-limiter audit, and the formal worst-case boundedness derivation.
Steps 1-7 (initial audit, measurement contract, workload manifest,
baseline measurement/profiling) are covered in their own existing
documents (`PHASE9_INITIAL_AUDIT.md`, `PHASE9_RELIABILITY_PERFORMANCE_CONTRACT.md`,
`artifacts/v2/phase9_workload_manifest.json`,
`artifacts/v2/phase9_baseline_results.json`/`phase9_baseline_profile.json`)
and are not repeated or redone here. No optimization, provider/model
change, caching, or gap_analysis parallelization was performed — this is
audit-only, per the governing directive's explicit scope limits.

**Process-deviation notice:** during execution of this pass, a human audit
found that ~19 real live end-to-end `MedAgent.run()` calls were made via
scratchpad scripts (`live_runner.py`, `smoke_test.py`, `fault_injection.py`)
that left Cerebras/NVIDIA fully live — unauthorized for this pass. Full
detail, root cause, and remediation: `PHASE9_FAILURE_ANALYSIS.md`'s
`PHASE9-PROCESS-DEV-001`. Every formal conclusion in this document was
re-verified to depend only on Category A (controlled) evidence — see the
classification immediately below.

---

## Evidence classification (added during PHASE9-PROCESS-DEV-001 remediation)

Every claim in this document is one of:

- **Category A — Controlled / Authoritative.** Deterministic pytest,
  injected transport (`unittest.mock`/`monkeypatch`), fake provider
  response, fake clock, barrier-based concurrency test, or
  static/code-derived analysis (reading constants, grepping for schema
  limits, etc.). **This is the only category that supports a formal
  Phase-9 gate claim.**
- **Category B — Supplementary unplanned live observation.** Evidence
  from the 19 unauthorized `live_runner.py`/`smoke_test.py`/`fault_injection.py`
  runs described in `PHASE9-PROCESS-DEV-001`. Preserved for reference,
  **never used to support a formal gate claim**, and never combined with
  Category A into one aggregate pass rate.

Unless marked otherwise, every result in Steps 8-11 below is **Category
A**. The one exception is the "Supplementary Live Observations" subsection
at the end of the Step 8 section, which is explicitly Category B.

---

## Step 8 — Systematic Fault Matrix

### Method

Every scenario is exercised via `unittest.mock.patch`/`monkeypatch` at the
transport boundary (`requests.post`, `ChatNVIDIA.invoke`,
`RetrySession.request`, orchestration execution functions) or via direct
unit-level construction of the deciding function
(`research.loop_control.decide_stop_reason`,
`research.action_planning.plan_actions`). **No real network call** against
Cerebras/NVIDIA/PubMed/ClinicalTrials/ChEMBL was made anywhere in this
step, per the governing directive's explicit "do not abuse live public
services" instruction. Full scenario-by-scenario detail lives in
`artifacts/v2/phase9_fault_matrix.json`; the executable proof is
`tests/test_phase9_fault_matrix.py` (37 tests, all PASS).

### Results summary

| Section | Scenarios | Pass | Fail |
|---|---|---|---|
| A — Cerebras tool-selection path | 11 | 11 | 0 |
| B — Three LLM clients (separately) | 8 | 8 | 0 |
| C — Per-source tool faults | 6 | 6 | 0 |
| D — Research-loop injection (6 points) | 6 | 6 | 0 |
| E — State/graph edge cases | 7 | 7 | 0 |
| **Total** | **37** (1 reconciliation test is counted separately below) | **37** | **0** |

Note: `TestCerebras503Reconciliation` (1 additional test) is not counted
in the 37 fault-scenario total above — it is a distinct, dedicated
reconciliation check, described in its own section below.

**Defects found in Step 8:** none. Every injected fault in every one of
the 37 scenarios was handled correctly — no fabricated Evidence IDs, no
invalid Evidence IDs, no uncaught exception, no infinite loop, no silent
failure, and no false `sufficient_evidence` stop. (Step 11 below finds one
genuine boundedness defect, `PHASE9-DEFECT-001`, but it is a call-COUNT
formal-guarantee gap, not a fault-injection-handling failure — it does not
belong to the Step 8 fault matrix's own PASS/FAIL accounting.)

### Per-implementation retry policy (reported separately, as required)

| Implementation | File | Retry policy | Timeout | Confirmed by |
|---|---|---|---|---|
| Cerebras tool-selection | `orchestration/candidate_b_native_tools.py::call_cerebras_native_tools` | **Zero retry** (deliberate design) | 60s, single attempt | Section A tests + structural source proof (exactly one `requests.post(` call site) |
| NVIDIA NIM (`ChatNVIDIA`) | `config/llm_config.py::_RateLimitedChatNVIDIA` | Up to `LLM_CALL_MAX_ATTEMPTS=3`, fresh client per retry, 429/503-substring-classified | 90s hard daemon-thread timeout per attempt | Section B1 tests |
| NVIDIA/Cerebras judge | `grounding_eval/judge.py::_invoke_judge` | Bounded retry, exactly 2 attempts | 60s per attempt | Section B3 tests |
| Cerebras claim generator | `generation/generator.py::_invoke_cerebras_claims` | Bounded retry, exactly 2 attempts | 60s per attempt | (Same code pattern as B3; not separately re-tested — frozen Phase-6 code, read-only confirmation) |
| Cerebras NLU extractor | `nlu/extractor.py::_invoke_cerebras_json` | Bounded retry, exactly 2 attempts | 60s per attempt | (Same code pattern as B3; read-only confirmation, out of Phase-9's node-level scope) |
| Biomedical source tools | `utils/retry_handler.py::RetrySession` | `MAX_RETRIES=3` → 4 total attempts, exponential jittered backoff | 30s per attempt (`API_TIMEOUT`) | Section C tests |

### Cerebras 503 reconciliation (required deliverable)

**Claim under investigation:** a real Cerebras 503 was observed once
during the Phase-9 Step 6/7 baseline run and reportedly "absorbed
transparently" — does this contradict `candidate_b_native_tools.py`'s
documented zero-retry design?

**Evidence examined:**
- `artifacts/v2/phase9_baseline_results.json`'s 12 baseline cases' `errors`
  fields contain **no** Cerebras-tool-selection-shaped error string
  (`candidate_b_native_tools.py`'s own error format is exactly
  `f"HTTP {status}: {text}"`); none match a 503 in that shape.
- `logs/medagent.log` lines 3423-3819+ (session
  `2026-09-25T00:41:43Z`-`00:46:17Z`) show every 503 in that session logged
  by `logger="config.llm_config"`, with message text
  `[LLM DISPATCH RESULT] ... error=Exception: [###] {'message': 'Service temporarily overloaded', 'type': 'Service Unavailable', 'code': 503}`,
  immediately followed by
  `[LLM RETRY] Call failed with a retryable provider error (attempt N/3): ... discarding client and retrying with a fresh connection`.
- The `[###] {...}` message shape is `langchain_nvidia_ai_endpoints`'s own
  internal error-string format (documented in `config/llm_config.py`'s
  `_RETRYABLE_ERROR_MARKERS` comment) — **not**
  `candidate_b_native_tools.py`'s format.
- No log line anywhere in the session matches
  `candidate_b_native_tools.py`'s own error string format with a 503
  status.

**Conclusion:**

- **Exact call that got the 503:** an NVIDIA NIM `ChatNVIDIA.invoke()` call
  (via `config/llm_config.py::get_llm()`), **not** a
  `call_cerebras_native_tools()` tool-selection call.
- **Exact function/class handling it:**
  `config/llm_config.py::_RateLimitedChatNVIDIA.invoke()` — its
  `_is_retryable_llm_error()` substring match classified it retryable, then
  it discarded the client, constructed a fresh `ChatNVIDIA`, slept a
  calculated backoff, and retried (up to `LLM_CALL_MAX_ATTEMPTS=3` total).
- **Tool-selection or another path:** another path — implementation #1
  (NVIDIA NIM client), not implementation #2 (Cerebras tool-selection).
- **Did HTTP transport retry it?** No.
- **Did application code retry it?** Yes — `_RateLimitedChatNVIDIA`'s own
  bounded retry-with-fresh-client logic.
- **Did a LangGraph node-level fallback absorb it?** No — it never reached
  node level; it was fully absorbed inside the LLM client wrapper before
  any node-level try/except was needed.
- **Is "zero retry" still an accurate characterization?** **Yes**, for
  `call_cerebras_native_tools()` specifically. The observed
  absorbed-503 was on a different implementation (NVIDIA NIM), which was
  always designed to retry 429/503-classified errors — this is that
  mechanism working exactly as documented, not a contradiction of the
  Cerebras tool-selection path's deliberate zero-retry design. The
  governing directive's context note ("A real Cerebras 503 was observed")
  is a provider mischaracterization, corrected here by direct log
  evidence; the underlying reliability behavior (a transient 503 absorbed
  without user-visible failure) is real, and is correctly attributed to
  implementation #1's retry policy.

Full structured detail (including the executable test,
`TestCerebras503Reconciliation::test_nvidia_client_503_is_retried_cerebras_tool_selection_503_is_not`)
is in `artifacts/v2/phase9_fault_matrix.json`'s `cerebras_503_reconciliation` key.

This reconciliation is entirely **Category A** — it relies only on the
pre-existing 2026-09-25 baseline-run log lines and static code reading, not
on any of the `PHASE9-PROCESS-DEV-001` live runs. A human audit
independently re-derived the same conclusion directly from
`logs/medagent.log` and confirms it: **"zero retry" remains accurate for
`call_cerebras_native_tools()`; the absorbed 503 belonged to the NVIDIA NIM
client path (`config.llm_config._RateLimitedChatNVIDIA`), which retries by
design.** No correction to this finding was needed.

### Supplementary Live Observations (Category B — not used as gate evidence)

During this pass, ~19 real live end-to-end runs were made via scratchpad
scripts outside the authorized stub-based method — see
`PHASE9_FAILURE_ANALYSIS.md`'s `PHASE9-PROCESS-DEV-001` for the full
process-deviation record. Summary, disclosed here for completeness only:

- **Count:** 19 (2 via `smoke_test.py`, 8 via `live_runner.py`, 9 via three
  runs of `fault_injection.py`).
- **Purpose (as executed, not as authorized):** ad hoc smoke-testing of the
  instrumentation approach, and reproduction of Phase-8's `LOCAL-01..08`
  and `CTL017-fault-{timeout,429,5xx}` cases against live infrastructure.
- **Providers actually contacted:** Cerebras (native tool-selection +
  claim generation) and NVIDIA NIM, live, in all 19 runs;
  PubMed/ClinicalTrials/ChEMBL live in 10 of the 19 (`smoke_test.py` +
  `live_runner.py`), stubbed in the other 9 (`fault_injection.py`).
- **Findings:** consistent with the Category A results — no fabricated or
  invalid Evidence IDs observed, no uncaught exception, correct terminal
  stop reasons (`sufficient_evidence`/`safe_abstention`/`no_productive_action`/`budget_exhausted`
  all observed appropriately). Two real Cerebras `429` responses
  (`"code":"queue_exceeded"`, provider-side queue pressure) and 27 real
  NVIDIA `503` responses were encountered and handled by existing retry
  logic without a user-visible failure, matching the Category A retry-policy
  findings above.
- **Explicitly unplanned:** none of these 19 runs were pre-registered in
  `artifacts/v2/phase9_workload_manifest.json` for this pass, and none were
  authorized by the governing directive's Step 8 instructions.
- **Explicitly not primary gate evidence:** the Step 8 PASS/FAIL table
  above (37/37) and the Cerebras-503 reconciliation depend on none of this;
  it is retained only as a supplementary real-world echo of the same
  conclusions, not as their basis.

---

## Step 9 — Concurrency Safety Audit

Full detail: `artifacts/v2/phase9_concurrency_audit.json`. Executable
proof: `tests/test_phase9_concurrency_audit.py` (5 tests, all PASS).

### Shared mutable state inventory (summary — full table in the JSON artifact)

| Object | Classification |
|---|---|
| `orchestration.registry.DEFAULT_REGISTRY` | shared-thread-safe |
| `BaseTool.cache` (per-tool-instance dict) | **shared-with-benign-duplicate-work-race** (empirically confirmed this pass) |
| `BaseTool.session` (`RetrySession`) | shared-thread-safe |
| `utils.rate_limiter._rate_limiter` | shared-thread-safe |
| `config.llm_config._llm_call_count`/`_llm_call_lock` | shared-thread-safe |
| `config.llm_config._thread_local` | request-local (correct, intentional) |
| `retrieval.retriever._retriever` | shared-thread-safe (practically eager init) |
| `agent.nodes._rag_retrieval_lock` | shared-thread-safe (the Metal/MPS fix — untouched) |
| `agent.nodes._chembl_backfill_tool` | shared-with-benign-duplicate-work-race (same cache property) |
| `AgentState` | request-local |
| Evidence/GroundedAnswer/citation objects | request-local |
| `logging` (stdlib) | shared-thread-safe |
| `research/loop_control.py` constants | immutable |

### Empirical `BaseTool.cache` race result

Using a `threading.Barrier(2)` placed inside a stubbed upstream call —
AFTER the cache-miss check and BEFORE either thread's write — two
concurrent identical-key requests produced **2 real upstream executions**
for what is logically 1 cacheable request. Both threads obtained the
identical correct data; the final cache entry was valid and correct (plain
dict assignment is atomic under the GIL, so no torn/partial write is ever
observable). **Classification: inefficiency-only (wasted redundant work /
thundering herd), not a data-correctness defect.** Per the governing
directive's explicit instruction, this race is audited here, **not
fixed**.

### Concurrency=2 / concurrency=4 results

Both levels: all tasks completed without an uncaught exception, no
query/stop-reason/iteration-count leakage between concurrent tasks
observed, and the shared rate-limiter singleton survived 4×20=80
concurrent calls with zero exceptions. Full detail in the JSON artifact.

---

## Step 10 — Rate Limiter Audit

Full detail: `artifacts/v2/phase9_rate_limiter_audit.json`. Executable
proof: `tests/test_phase9_rate_limiter_audit.py` (15 tests, all PASS,
using an injectable fake clock — no real sleeps).

**Correctness verdict: no defects found.** Configured provider rates (35
RPM NVIDIA, 5 RPM Cerebras, 3 RPS PubMed, 10 RPS ClinicalTrials, 10 RPS
ChEMBL) each have their own independent, correctly-isolated `TokenBucket`.
First calls never wait; subsequent calls after exhausting capacity wait
the exact minimum spacing implied by the configured rate (confirmed via
fake clock, e.g. ~1.714s for 35 RPM, ~12.0s for 5 RPM). `TokenBucket.consume()`'s
internal lock prevents double-spending the same token under concurrent
contention (10 racing threads against a 1-token bucket produced exactly 1
success, never 0 or >1) — **no burst above the configured rate was
observed under any tested condition.**

**Retry interaction (confirmed):** `wait_for_rate_limit()` is called
BEFORE every attempt at every real call site, with no visibility into
whether that attempt ultimately succeeds — **every retry attempt consumes
its own token**, including failed ones. This is already accounted for in
`config/llm_config.py`'s own documented rationale for capping NVIDIA at 35
(not the true 40) RPM.

**Fairness:** not guaranteed by design (`wait_for_token()` is an unordered
spin-wait with no FIFO queue) — documented as an inherent property, not
asserted as a bug, since nothing in this codebase's actual usage pattern
(single process, a handful of concurrent tasks) depends on strict
ordering.

**Inefficiencies noted, not defects:** the 0.1s spin-wait poll interval
adds a small avoidable latency tail versus an event-driven wake mechanism
— explicitly not fixed, per the no-optimization scope of this pass.

---

## Step 11 — Formal Worst-Case Boundedness

Full detail: `artifacts/v2/phase9_boundedness_analysis.json`. Constants
were read directly from source (`research/loop_control.py`,
`config/llm_config.py`, `orchestration/candidate_b_native_tools.py`,
`grounding_eval/judge.py`, `generation/generator.py`, `nlu/extractor.py`,
`utils/retry_handler.py`, `config/settings.py`), never invented.

### Call graph model (research-loop product path)

- **R = 1 + MAX_RESEARCH_ITERATIONS = 1 + 3 = 4** total tool-orchestration
  rounds (1 initial + up to 3 follow-up iterations via
  `research_execution_node` re-invoking `tool_orchestration_node`).
- **G = R = 4** grounded-generation/gap-analysis cycles (the follow-up loop
  bypasses `synthesis_node`, going `research_execution → evidence_merge →
  grounded_generation` directly — confirmed from `build_research_loop_graph`'s
  own edges).
- `synthesis_node`, `query_analysis_node`, and `report_generation_node`
  each run **exactly once** per request (never revisited by the loop).

### The 7 required formulas (with real constants substituted)

1. **Max LLM calls/request:**
   `11 + Σ_{g=1}^{4} C_g` where `C_g` = factual-claim count in generation
   cycle `g`. The `11` = 1 (NLU) + 4 (Cerebras tool-selection, 1/round) + 1
   (synthesis) + 4 (grounded generation, 1/cycle) + 1 (report generation).
   **The `C_g` term is UNBOUNDED** (see Claim-Count Boundedness below).

2. **Max biomedical-source calls/request:**
   `R × |DECLARED_TOOLS| = 4 × 6 = 24` — a **soft** bound (the 6 declared
   tool functions are the practical ceiling; nothing in code hard-caps how
   many distinct tool calls one Cerebras response may return).

3. **Max retry-amplified source calls:**
   `24 × (MAX_RETRIES + 1) = 24 × 4 = 96` total HTTP attempts, worst case.

4. **Max research rounds:**
   `R = 1 + MAX_RESEARCH_ITERATIONS = 4`, hard-enforced by
   `decide_stop_reason`'s `BUDGET_EXHAUSTED` check.

5. **Max gap-analysis judge calls:**
   `Σ_{g=1}^{4} C_g` — **UNBOUNDED**, the same term as formula 1's
   variable part (this is `PHASE9-DEFECT-001`).

6. **Max total external calls:**
   `116 + 2 × Σ_{g=1}^{4} C_g` — bounded part = 2 (NLU) + 4 (tool-select) +
   3 (synthesis) + 96 (source HTTP) + 8 (grounded gen) + 3 (report) = 116;
   unbounded part is the judge-call term (each judge call up to 2
   attempts).

7. **Max timeout-driven wall-clock time:**
   `~4612 seconds (~77 minutes) + Σ_{g=1}^{4} C_g × ~144 seconds` — the
   bounded part is a pathological (every individual call maxing out
   simultaneously) worst case, far above real observed Phase-9 baseline
   cases (58s-603s, see `artifacts/v2/phase9_baseline_results.json`); the
   unbounded part is, again, the claim-count term.

### Claim-count boundedness (critical finding)

**No cap exists at any of the 4 layers checked:**

| Layer | File | Finding |
|---|---|---|
| Schema (pydantic) | `generation/models.py:119` | `claims: List[GroundedClaim]` — plain `List[...]`, no `max_length`. Grep for `max_length`/`max_items` in the file: zero matches. |
| Generation JSON schema | `generation/generator.py:86-102` | `_CLAIMS_JSON_SCHEMA`'s `"claims"` array has no `"maxItems"`. Grep: zero matches. |
| Parser | `generation/generator.py` (`_invoke_cerebras_claims`/`generate_grounded_answer`) | Only checks `isinstance(claims_raw, list)` — no length check. |
| Validation | `generation/validation.py::validate_claims` | Checks evidence-ID validity, factual-claim support, claim-ID uniqueness, no bare-source-ID citation — **no `len(claims)` check anywhere in the function.** |
| Runtime consumer | `research/gap_analysis.py:84` | `for claim in grounded_answer.claims:` — no slicing, no cap, no sampling. |

A soft, **indirect** mitigating factor exists (`max_completion_tokens=4096`
on the Cerebras claim-generation call caps total OUTPUT size), but this is
not a claim-COUNT cap — a model could produce many short claims within
that token budget, and nothing validates or rejects an unusually large
claims array.

**Conclusion:** the formal maximum judge-call count (and therefore total
call count and wall-clock time) is **unbounded as a function of the
model's own output length/structure**, not fixed by any code-level
constant. This is a genuine **boundedness defect**, assigned
**`PHASE9-DEFECT-001`** (continuing numbering from
`PHASE8-DEFECT-002`, the last previously-assigned ID). It is classified as
a formal-guarantee gap, **not** a correctness/fabrication defect — no
fabricated or invalid Evidence ID, and no silent failure, was found
anywhere in this pass's fault matrix (Step 8). Per the governing
directive, **it is not fixed in this pass** — see
`artifacts/v2/phase9_boundedness_analysis.json`'s `candidate_remedies_analyzed_not_implemented`
for the full analysis of 6 candidate remedies (hard claim cap, total
evaluation budget, batch judging, bounded concurrency, bounded truncation
with disclosure, whole-answer gap analysis), each scored for safety,
semantic effect, compatibility with frozen Phase 6/7 behavior, grounding
quality impact, latency impact, silent-drop risk, and user-visible
behavior change. None is chosen or implemented here.

### Time-bound analysis (precise statement)

Every **individual** external call, retry attempt, backoff sleep, and
rate-limit wait in the system is finitely bounded — confirmed by direct
reading of every relevant timeout/retry-count/backoff-max/rate-limit
constant. Research-loop **iterations** are also hard-bounded
(`MAX_RESEARCH_ITERATIONS=3`). **However, the total NUMBER of
gap-analysis judge calls issued within those bounded iterations is not
bounded**, because it is driven by `GroundedAnswer.claims`' length, which
has no cap anywhere in the code. **Therefore: the system does not
currently have a finite, code-enforced wall-clock upper bound on a single
request — not because any individual wait/call path is unbounded, but
because the total NUMBER of otherwise-individually-bounded calls is
unbounded.** No "max request duration" deadline of any kind exists in the
code (confirmed by grep across `agent/graph.py`/`agent/nodes.py`/`research/*.py`
for any wrapping timeout around `graph.invoke()` or the research loop as a
whole) — none is invented or assumed here. This is stated precisely as a
call-COUNT boundedness gap, not a per-call timeout gap.

---

## CTL-017 reassessment

**Is the Phase-9-owned broader portion of CTL-017 now satisfied?** Yes,
for this pass's own scope. Phase 8's CTL-017 closure was narrow (3
individually-injected fault classes on the research loop only). This
pass's Step 8 fault matrix covers, additionally: all 3 independent LLM
client implementations tested separately with distinct retry policies
confirmed; per-source tool fault injection beyond the single
"simultaneous 5xx" case (single-source failure, one-fails-others-succeed,
retry exhaustion, empty result, malformed payload); 6 distinct
research-loop injection points instead of 3; state/graph edge cases; and
the Cerebras-503-vs-zero-retry discrepancy explicitly reconciled with
direct log evidence. 37 scenarios across 5 lettered categories, all PASS,
zero fault-handling-correctness defects found. This is not claimed as
exhaustive coverage of every conceivable fault permutation (e.g. real
concurrent faults across multiple sources under real network conditions
remain a candidate for a future pass if a specific gap is identified), but
it substantively satisfies CTL-017's own pre-registered "Phase 9 owns the
system-wide fault matrix" language.

**CTL-016 and CTL-019:** left **unchanged**. This pass's concurrency tests
used mocked/stubbed dependencies by design (no real network calls, per
scope), producing no new organic live 3-round case (CTL-016's specific
criterion) and no new live-run samples toward CTL-019's n-disclosure bar.
Per the governing directive's own instruction ("if in doubt, leave
unchanged and say why"), both are left exactly as Phase 8's local closure
left them.

---

## PRE-OPTIMIZATION CONSISTENCY AUDIT (addendum)

A human audit of the Steps 8-11 report found several internal
inconsistencies and imprecise claims before optimization could be
authorized. Corrections below; full machine-readable detail is in
`artifacts/v2/phase9_boundedness_analysis.json`'s
`pre_optimization_consistency_audit_corrections` key and
`artifacts/v2/phase9_fault_matrix.json`'s top-level `scenario_count`/
`test_function_count` fields (both updated by this audit). No production
code was changed; two pre-existing **test-only** methodology bugs were
fixed (see "Test-only fixes" below).

### 1. Fault-matrix count reconciliation

Two different, both-legitimate counts were being conflated:
- **38** distinct documented fault CONDITIONS (JSON scenario rows,
  A=11+B=8+C=6+D=6+E=7).
- **37** pytest TEST FUNCTIONS (confirmed via `pytest --collect-only -q`):
  A contributes only 9 functions for its 11 conditions, because
  `test_schema_invalid_tool_call_args_never_reaches_execution` is ONE
  function asserting THREE conditions (A9 unregistered_tool, A10
  arguments_json_invalid, A11 schema_invalid) in sequence.

The original report's top-level `scenario_count: 37` silently equaled the
test-function count while its own per-section table summed to 38 — an
internal inconsistency, not a fabrication. Both numbers are now stated
explicitly, separately, and are never conflated again in this artifact.

### 2. PHASE9-DEFECT-001 claim-count boundedness — corrected

See `PHASE9_FAILURE_ANALYSIS.md`'s `PHASE9-DEFECT-001` entry for the full
correction. Summary: the original "unbounded" claim did not check whether
`generation/generator.py::_invoke_cerebras_claims`'s executed
`max_completion_tokens=4096` ceiling already provides a finite (if very
large, order ~100-150 claims/cycle) bound. Corrected answer: **finite only
because of this external/provider limit, not because of any deliberate
application-level budget** — reframed as an APPLICATION-LEVEL BOUNDEDNESS
DEFECT, not a literal-infinity claim. Severity is not eliminated: a ~600
theoretical judge-call ceiling and a ~25-hour theoretical wall-clock
ceiling provide no meaningful reliability guarantee even though they are
not mathematically infinite.

### 3. Tool/source-call ceiling reconciliation

`DECLARED_TOOLS_COUNT=6` (number of distinct tool function schemas offered
to Cerebras per round) and `MAX_TOOL_CALLS_TOTAL=8` (a hard counter of
`research_execution_node` ROUND invocations, not individual tool calls)
operate at different layers and were conflated in the original `R × 6 =
24` / `24 × 4 = 96` formulas, which implied `6` was a hard per-round cap
when it is not (code does not limit `len(raw_tool_calls)`). Corrected: R=4
(hard) is the binding round constraint (`MAX_TOOL_CALLS_TOTAL=8` never
binds tighter and plays no further role); the true per-round tool-call
ceiling is soft and provider-token-budget-derived
(`max_completion_tokens=1024` on the Cerebras tool-selection call, order-of-
magnitude ~20-30 valid tool_calls/round) — giving a **soft,
input/output-dependent** estimate of roughly 80-120 logical biomedical
calls/request, not the previously-stated hard-looking 24. Full detail in
the JSON's `tool_vs_source_call_reconciliation` key.

### 4. Concurrency isolation coverage gap — closed

Added `TestConcurrentRichStateIsolation` to
`tests/test_phase9_concurrency_audit.py`: concurrent requests now receive
real, distinct, marker-tagged (`REQUEST_A_ONLY_0`, `REQUEST_B_ONLY_1`, ...)
Evidence IDs, source IDs, claims, citations, `used_evidence_ids`, and
`Evidence.provenance.call_id`, at concurrency=2 and concurrency=4, all
stubbed (no live calls). Result: **zero cross-request contamination** in
either field's own-marker-only content, at both concurrency levels.
`AgentState` has **no separate global trace/request-ID field** (confirmed
by reading `agent/state.py` in full) — `tool_call_history`'s per-entry
`call_id` and `Evidence.provenance.call_id` are the closest analogues, both
request-local by construction; `tool_call_history` is legitimately empty
in this stub path (zero tools selected by design) and is disclosed as such
rather than asserted against.

### 5. Rate-limiter starvation / wait-bound — clarified

The original report's blanket "rate-limit wait is finite" claim (used
inside Formula 7) is accurate **only under a closed-workload model**
(Model A: a fixed, small, known set of concurrent callers — this
codebase's actual current usage pattern, confirmed via
`evaluation/evaluator.py`'s fresh-instance-per-task design). Under an
arbitrary-sustained-arrivals model (Model B), `wait_for_token()`'s
unordered spin-wait (no FIFO queue, confirmed via source reading) means a
specific waiting caller **can** be starved indefinitely by continuously
arriving new callers, and no universal finite per-request wait bound can
be claimed without an additional arrival-rate assumption. **Classification:
a documented scheduling property under Model A (this codebase's real
usage) — not a defect requiring Phase-9 remediation now**; it would become
a genuine reliability/boundedness gap only under a hypothetical future
Model-B (multi-tenant/arbitrary-arrival) deployment this project does not
currently have. Full detail in the JSON's `rate_limiter_starvation_analysis`
key.

### 6. Provider/path terminology cleanup

The original report's "NVIDIA-backed paths (3 distinct clients)" heading
incorrectly grouped a Cerebras-backed judge under an NVIDIA label. Verified
by reading `grounding_eval/judge.py` directly: `CEREBRAS_API_URL =
"https://api.cerebras.ai/v1/chat/completions"` — genuinely Cerebras-backed,
not configurable, and sharing the `cerebras_free_trial` 5 RPM bucket with
the claim generator and NLU extractor. Corrected: **5 distinct LLM call
sites**, 4 Cerebras-backed (3 sharing one 5 RPM bucket) and 1
NVIDIA-NIM-backed. Full per-path table (function/class, actual provider,
purpose, attempts, timeout, limiter, retry policy) in the JSON's
`provider_path_terminology_cleanup` key.

### 7. Recomputed formal bounds

See `artifacts/v2/phase9_boundedness_analysis.json` (updated) and
`PHASE9_FAILURE_ANALYSIS.md`'s corrected `PHASE9-DEFECT-001` entry for
every formula, now explicitly categorized as HARD APPLICATION CONSTANT
(R=4, research rounds), PROVIDER-CONFIG-DEPENDENT BOUND (rate-limiter
spacing), INPUT/OUTPUT-DEPENDENT BOUND (claim count, tool-call count, and
everything derived from them), or NO UNIVERSAL BOUND UNDER STATED MODEL
(rate-limit wait under Model B only). Logical calls and retry-amplified
attempts are kept as explicitly separate figures throughout, never mixed
into one number.

### 8. PHASE9-DEFECT-001 final decision

**Final wording:** "Missing intentional application-level claim-evaluation
budget for gap-analysis judge calls" (see corrected entry in
`PHASE9_FAILURE_ANALYSIS.md`). **Severity:** downgraded from an implied
"literally infinite" framing to a bounded-but-pathologically-large
(order ~600 judge calls / ~25h wall-clock worst case) application-level
gap — still real, still worth fixing, not a false alarm. **Why it
matters:** the existing "bound" is accidental (a token-length setting
chosen for unrelated reasons), not a deliberate reliability guarantee —
functionally equivalent to having no guarantee for planning/timeout-budget
purposes. **Must it be fixed before Phase-9 freeze?** Not decided in this
pass — that decision is explicitly deferred to the human reviewer, per the
same phase-gate discipline that already deferred the fix's selection.
Candidate remedies (ranked by semantic safety, not speed, full detail
already in `phase9_boundedness_analysis.json`'s
`claim_count_boundedness.candidate_remedies_analyzed_not_implemented`):
1. **B — total gap-analysis evaluation budget** (safest: no generation-side
   change, Phase-8-owned files only, needs an explicit "not evaluated"
   state).
2. **E — bounded truncation with explicit disclosure** (safe by
   construction since disclosure is built in, but touches frozen Phase-6
   generation code).
3. **A — hard max claims per answer** (same generation-code touch as E,
   without E's built-in disclosure requirement — higher silent-drop risk).
4. **C — batch claim judging** (unverified grounding-quality effect, needs
   its own re-validation pass against the frozen Phase-7 judge contract).
5. **D — bounded concurrency** (reduces wall-clock only, does NOT fix the
   call-count-unboundedness formula; also explicitly out of scope this
   pass regardless).
6. **F — whole-answer gap analysis** (strongest latency fix, but the most
   invasive relative to frozen Phase 7/8 per-claim attribution — highest
   semantic risk). None implemented.

### Test-only fixes (no production code changed)

Two **pre-existing** thread-safety bugs in the test suite itself (not
production code) were found and fixed while building item 4's isolation
coverage: `TestConcurrentMedAgentExecutions` (already existing) and the
first draft of the new `TestConcurrentRichStateIsolation` both used a
per-thread `pytest.MonkeyPatch()` + `.undo()` around shared, process-global
module attributes (`agent.nodes.get_llm`, etc.) — a genuine race, since one
thread's `.undo()` can restore the REAL implementation while another thread
is still mid-flight. This was **observed empirically**: it let a real
`ChatNVIDIA` client get constructed (and make a real live call to NVIDIA's
model-listing endpoint) during a supposedly fully-stubbed concurrency test
run. Fixed by installing every stub exactly once, globally, before
spawning any thread, with per-request behavior derived from `state["query"]`
(thread-local by construction) instead of from a per-thread closure. Fix
verified via 3 repeated full-file runs with zero recurrence of the
live-call warning, then confirmed clean across the full `pytest tests/`
suite.

---

## BOUNDEDNESS HARDENING (production-code pass, following the audit-only passes above)

This section documents the first Phase-9 pass that changes PRODUCTION code
(everything above this section was audit-only). It implements fixes for
PHASE9-DEFECT-001 and the newly-discovered PHASE9-DEFECT-002 - see
`docs/v2/PHASE9_FAILURE_ANALYSIS.md` for the full defect records and
`artifacts/v2/phase9_boundedness_analysis.json`'s new `formulas_post_fix`/
`claim_budget_design`/`tool_call_budget_design` keys for the machine-readable
version of everything below (existing keys in that file are untouched).

### Distributions extracted (Steps 4 and 6)

Full raw data in `artifacts/v2/phase9_claim_and_tool_call_distributions.json`.

**Claim count (n_factual_claims), primary corpus** - every value from
`artifacts/v2/phase8_dev_benchmark_results.json` +
`phase8_validation_results.json` + `phase8_validation_run2_results.json`,
at the (case, round) granularity those files actually record:

- n = 45, min = 0, median = 3, **max = 8**.
- Raw sorted values: `[0,0,0,0,0,0,0,0, 1,1,1, 2,2,2,2,2, 3,3,3,3,3,3,3,3, 4,4,4,4,4,4,4, 5,5,5, 6,6,6,6, 7, 8,8,8,8,8,8]`
- **Cumulative per-multi-round-case totals** (the figure most comparable to
  a REQUEST-GLOBAL budget): max observed = **16** (case
  `VAL-F-tool-failure-safe-termination`, 8+8 across its 2 real rounds). No
  case in this corpus exercised more than 2 real rounds (the hard bound
  allows up to 4).
- Broader corpus (adding 9 Phase-6 single-shot-generation values, which
  never went through the research-loop's gap-analysis judge-call loop at
  all): n = 54, max still = 8 - confirms 8 is not an artifact of only
  checking 3 files.
- **Excluded as not comparable:** `artifacts/v2/phase7_*.json`'s `n_claims`
  field (values up to 32) is an AGGREGATE across many test cases in one
  evaluation batch, not a per-answer/per-cycle count - verified by direct
  inspection of `phase7_candidate_b_fresh_supplement_results.json` and
  excluded from the distribution above (documented, not silently dropped).
- **"Required judging" count:** the data only ever recorded
  `n_factual_claims` (factual claims with `>=1 evidence_ids`, which is
  exactly `analyze_gaps`'s own judging-eligibility filter) - it does not
  separately break out a narrower "actually required judging" subset, so
  `n_factual_claims` **is** that count already; stated precisely rather
  than assumed.

**Tool-call count** - `artifacts/v2/phase9_baseline_results.json`'s 12 real
baseline cases' `n_tool_calls` (AGGREGATE per whole request, all rounds
combined - not a per-round breakdown):

- n = 12, min = 1, median = 3.5, **max = 12** (case
  `F5-research-loop-one-followup`).
- **No repo artifact records a PER-ROUND model-emitted `raw_tool_calls[]`
  array length anywhere** - grep-confirmed against every
  `artifacts/v2/phase8_*.json` file for `tool_calls_per_round`/
  `n_tool_calls`/`tools_called` patterns. Stated explicitly per the
  governing directive's instruction, rather than guessed.
- Secondary, code-level basis (from the PRE-OPTIMIZATION CONSISTENCY
  AUDIT's `tool_vs_source_call_reconciliation`, in
  `artifacts/v2/phase9_boundedness_analysis.json`):
  `DECLARED_TOOLS_COUNT=6`, and a soft, provider-token-budget-derived
  per-round ceiling on the order of **~20-30 valid tool_calls/round**
  (from `call_cerebras_native_tools`'s `max_completion_tokens=1024`
  default).

### CLAIM_EVALUATION_BUDGET design decision (Step 4)

**Scope: REQUEST-GLOBAL (across all G<=4 generation cycles), not
per-cycle.** Reasoning: (1) it directly bounds the actual reliability
concern - total judge-call count / wall-clock cost for the WHOLE request -
with one clean number; (2) it matches the existing request-global-budget
naming convention already established by `MAX_TOOL_CALLS_TOTAL` in the same
module; (3) a per-cycle-only budget would still need to be multiplied by
the hard cycle count to produce a request-level guarantee, so request-global
is the more direct, not more complex, choice.

**Value: `CLAIM_EVALUATION_BUDGET = 32`.** Derivation: (observed single-
round max claims in the primary corpus, **8**) x (hard
`MAX_RESEARCH_ITERATIONS`-derived cycle count, **G=4**) = **32** - exactly
what a request would need to sustain the corpus's own worst observed
single-round rate across every one of its hard-bounded cycles. This is
already 2x the highest actually-observed CUMULATIVE multi-round total in
that same corpus (16), and roughly two orders of magnitude below the
incidental `max_completion_tokens=4096`-derived ceiling (~400-600
claims/request) that PHASE9-DEFECT-001 originally flagged as providing no
meaningful reliability guarantee - so this is a genuine application-level
tightening, not a restatement of the incidental provider-token ceiling.

### MAX_TOOL_CALLS_PER_ROUND / MAX_TOOL_CALLS_PER_REQUEST design decision (Step 6)

**Values: `MAX_TOOL_CALLS_PER_ROUND = 12`, `MAX_TOOL_CALLS_PER_REQUEST = 24`.**

- `12` = 2x `DECLARED_TOOLS_COUNT=6` - enough headroom for the model to
  legitimately call the same tool twice with different arguments in one
  round (e.g. ChEMBL search-by-target AND search-by-indication), and
  coincidentally already covers the single highest REAL aggregate-per-
  request `n_tool_calls` value observed (12) even under the pessimistic
  assumption that it all concentrated in one round. Well below the soft
  ~20-30 order-of-magnitude token-derived ceiling, so this is a genuine
  tightening, not a restatement.
- `24` = 2x that same observed real max (12); confirmed
  `MAX_TOOL_CALLS_PER_REQUEST (24) <= MAX_TOOL_CALLS_PER_ROUND * R (12*4=48)`
  - the per-request figure is the tighter, binding constraint in practice.

**Design decision - invalid (registry-rejected) calls DO consume budget
slots**, counted the moment they appear in `raw_tool_calls[]`, before
`parse_and_validate_tool_call` ever runs on them. Chosen over the
alternative (only registry-valid calls consume budget) because that
alternative would let a response padded with many registry-invalid junk
entries bypass the budget's actual purpose: bounding total processing
effort spent on a round's raw model output, not just how many calls reach
the HTTP boundary. This is the more conservative, smallest-blast-radius
choice and is proven implemented by
`tests/test_phase9_tool_call_budget.py::TestInvalidCallsConsumeBudget`.

**No new stop reason invented.** Once the request-global tool-call budget
is exhausted, the next round necessarily executes 0 tool calls, which the
PRE-EXISTING `research_execution_node` productivity check already turns
into `EXECUTED_UNPRODUCTIVE` -> `research_consecutive_failure_rounds`
increments -> the PRE-EXISTING `TOOL_FAILURE_LIMIT` stop reason fires after
`MAX_CONSECUTIVE_TOOL_FAILURE_ROUNDS=2` such rounds. Verified this is
sufficient (no case where the loop would otherwise spin without ever
reaching a terminal stop reason, since `MAX_RESEARCH_ITERATIONS=3` hard-caps
total rounds regardless).

### Overflow / budget-exhaustion semantics implemented (Step 5's 9 requirements)

| # | Requirement | How satisfied |
|---|---|---|
| 1 | At most `CLAIM_EVALUATION_BUDGET` judge evaluations per request | `research/gap_analysis.py::analyze_gaps` tracks a request-global counter (`state["claim_judge_calls_used"]`) and stops issuing real `judge_claim_semantic()` calls once exhausted. Proven by `tests/test_phase9_claim_budget.py`'s exact-call-count assertions. |
| 2 | Never mark an unevaluated claim "supported" | A distinct `GapType.EVALUATION_BUDGET_EXHAUSTED` gap is created instead - never silence, never a fabricated SUPPORTED judgment. |
| 3 | Never drop an unevaluated claim from the answer | `analyze_gaps` never touches `grounded_answer.claims`; the claim remains in `claims`/`rendered_text` untouched. |
| 4 | Explicit unresolved/unevaluated state, reusing `EvidenceGap`'s shape | One new `GapType` enum value added (smallest additive schema change); no parallel mechanism built. |
| 5 | Reuse `finalize_research_answer_node`'s qualifier machinery | `_UNRESOLVED_CLAIM_GAP_TYPES` extended with `"evaluation_budget_exhausted"`, with its own honest qualifier wording. |
| 6 | Already-judged claims before exhaustion unchanged | `analyze_gaps` only ever appends new gaps / advances a local counter - it never revisits or mutates a `ClaimGroundingJudgment` already produced earlier in the same call. Proven by `tests/test_phase9_claim_budget.py::TestClaimBudgetPreservesAlreadyJudgedClaims`. |
| 7 | Zero fabricated Evidence IDs | The budget-exhaustion gap cites only `claim.claim_id`, never an `evidence_id` field. Proven explicitly by test assertion. |
| 8 | No false `sufficient_evidence` while a budget-exhausted gap is open | `decide_stop_reason`'s pre-existing `if not gaps: return SUFFICIENT_EVIDENCE` is untouched; a budget-exhausted gap keeps `gaps` non-empty. `plan_actions` additionally excludes this gap type from candidate selection so it can never be "resolved" by a futile tool call. |
| 9 (PHASE8-DEFECT-001/002 non-regression) | Pre-existing fixes remain intact | `tests/test_research_finalize_answer_defect_fix.py` + `tests/test_research_integration.py` re-run in full after the change: **21 passed, 0 failed** (unchanged from before - these test files were not modified by this pass). |

### Recomputed worst-case bounds (Step 8) - PRE-FIX vs POST-FIX

All PRE-FIX figures below are quoted verbatim from
`artifacts/v2/phase9_boundedness_analysis.json`'s original `formulas` key
(unchanged, still present in that file) - shown here strictly for
side-by-side comparison, never deleted.

| Formula | PRE-FIX | POST-FIX | Status change |
|---|---|---|---|
| 1. Max LLM logical calls/request | `11 + sum(C_g)`, finite but input/output-dependent, order-of-magnitude `~611` | `11 + CLAIM_EVALUATION_BUDGET = 11 + 32 = **43**` | input/output-dependent -> **HARD APPLICATION CONSTANT** |
| 2. Max logical biomedical/tool calls per request | `R * DECLARED_TOOLS_COUNT = 24`, but flagged SOFT (DECLARED_TOOLS_COUNT is a schema count, not an enforced cap) | `MAX_TOOL_CALLS_PER_REQUEST = **24**` (same number, now genuinely hard-enforced) | soft/mischaracterized -> **HARD APPLICATION CONSTANT** |
| 3. Max retry-amplified biomedical HTTP attempts | `24 * (TOOL_MAX_RETRIES+1) = 96`, soft (inherits #2's soft status) | `MAX_TOOL_CALLS_PER_REQUEST * 4 = 24 * 4 = **96**` (same number, now hard) | soft -> **HARD APPLICATION CONSTANT** |
| 4. Max research rounds | `R = 1 + MAX_RESEARCH_ITERATIONS = 4`, already hard | **`4`**, unchanged | already hard, unchanged |
| 5. Max gap-analysis judge calls/request | `sum(C_g)`, finite but input/output-dependent, order-of-magnitude `~600` | `CLAIM_EVALUATION_BUDGET = **32**` | input/output-dependent -> **HARD APPLICATION CONSTANT** |
| 6. Max total external calls/request | `116 + 2*sum(C_g)`, order-of-magnitude `~1316` | `116 + (CLAIM_EVALUATION_BUDGET * CEREBRAS_JUDGE_MAX_ATTEMPTS) = 116 + (32*2) = 116 + 64 = **180**` | input/output-dependent -> **HARD APPLICATION CONSTANT** |
| 7. Max timeout-driven wall-clock time | `~4612s + sum(C_g)*~144s`, order-of-magnitude `~91,000s (~25h)`, "practically unbounded for planning purposes" | `~4612s + (CLAIM_EVALUATION_BUDGET * ~144s) = 4612 + (32*144) = 4612 + 4608 = **~9220s (~2.56h)`** | input/output-dependent, planning-unusable -> **HARD, DEFENSIBLE NUMBER** (first time this phase a real, non-order-of-magnitude figure exists) |

Supplementary breakdowns (all now hard, given both new budgets):

- **Max LLM provider attempts/request** (Cerebras+NVIDIA only, excluding
  biomedical tool HTTP): NLU (<=2) + tool-selection (4) +
  synthesis (<=3) + grounded-generation (<=8) + report-generation (<=3) +
  judge (`32*2`=64) = **84**.
- **Max biomedical HTTP attempts/request:** `MAX_TOOL_CALLS_PER_REQUEST *
  (TOOL_MAX_RETRIES+1) = 24*4 = **96**`.
- **Max total external attempts/request:** `84 + 96 = **180**` (matches
  formula 6 above).

**Wall-clock derivation note:** the `~4612s` bounded component is UNCHANGED
from the pre-fix derivation (none of its individual per-call
timeout/backoff/rate-limit constants changed) - what changed is that its
own `biomedical_source_http` sub-term already assumed 24 logical calls,
which is now an accurate, hard-enforced figure (`MAX_TOOL_CALLS_PER_REQUEST`)
instead of an unjustified placeholder. Per the governing directive's
explicit instruction, no new concurrent-contention wall-clock bound beyond
the existing rate-limiter Model A (closed/fixed-N workload) assumption is
attempted here - Model A/Model B remain exactly as characterized in the
PRE-OPTIMIZATION CONSISTENCY AUDIT's `rate_limiter_starvation_analysis`.

### Quality non-regression (Step 11)

A normal workload well under both budgets (1 tool call selected, 1 factual
claim, 1 judge call) was run through the FULL stubbed `MedAgent(research_loop=True).run()`
graph (`tests/test_phase9_quality_non_regression.py::TestNormalWorkloadUnaffectedByNewBudgets`).
Result: `research_stop_reason="sufficient_evidence"`,
`research_iteration=0`, the claim's `qualifier` stays `None` (never
caveated), `claim_judge_calls_used=1` (far below 32),
`tool_calls_used_this_request=0`, zero `tool_call_budget_exhausted` history
entries, zero `evaluation_budget_exhausted` gaps - i.e. every new
budget-tracking field/branch this pass added is reachable and exercised by
the real code path, but never trips, for an ordinary request. A second,
direct code-level angle
(`TestGuardBranchesProvablyNeverEnteredUnderBudget`) constructs claims/tool-
calls just UNDER each threshold and asserts, via real mock call counts (not
just returned state), that every claim/tool-call is processed with zero
budget-exhaustion branches entered - demonstrating the new guard conditions
are provable no-ops by construction below threshold, backed by a passing
test rather than only a code-reading argument.

### GAP-ANALYSIS JUDGE-CALL CONCURRENCY (scheduling-only follow-up pass)

This is a SCHEDULING change only - not a performance-tuning pass. It adds
the CAPABILITY to run `research/gap_analysis.py::analyze_gaps`'s per-claim
`judge_claim_semantic()` calls with bounded worker concurrency, but does not
change the frozen judge itself (`grounding_eval/judge.py` - prompt, schema,
classification logic, retry logic, and the shared `utils/rate_limiter.py`
TokenBucket are all completely untouched), and does not change the
mechanism's default runtime behavior. No live Cerebras/NVIDIA/PubMed/
ClinicalTrials/ChEMBL call, no live `MedAgent.run()`, and no timing/
throughput measurement of any kind was performed during this pass - see
`artifacts/v2/phase9_gap_analysis_concurrency_experiment.json` for the
pre-registered, still-empty future benchmark contract.

**Mechanism.** `analyze_gaps` now processes its claim-support detector in
three sequential-then-concurrent-then-sequential phases:

1. **Step A (sequential, no I/O)** walks `grounded_answer.claims` in its own
   order and, for each factual claim with resolvable cited Evidence,
   reserves one `CLAIM_EVALUATION_BUDGET` slot (decrementing an in-scope
   `budget_remaining` counter) BEFORE any worker thread exists, or assigns
   it an `EVALUATION_BUDGET_EXHAUSTED` gap if no slot remains. Because this
   reservation happens in plain single-threaded code ahead of any
   concurrent dispatch, it is race-free by construction - no two workers can
   ever observe a stale `budget_remaining > 0` and both proceed on the same
   last slot.
2. **Step B (concurrent I/O)** dispatches exactly the pre-approved,
   budget-reserved claims to `grounding_eval.judge.judge_claim_semantic` via
   a `concurrent.futures.ThreadPoolExecutor(max_workers=GAP_ANALYSIS_MAX_CONCURRENCY)`
   used as a context manager (guarantees `shutdown(wait=True)` on exit - no
   dangling worker threads survive `analyze_gaps`'s return). Every worker
   calls the exact same shared, thread-safe rate limiter the sequential code
   already used (audited thread-safe in the immediately-prior pass) - no
   second limiter is constructed, no call bypasses it. A worker's exception
   is caught per-future and stored as a distinct failure sentinel, never
   allowed to propagate out of `analyze_gaps` and never able to corrupt or
   erase another worker's independent result.
3. **Step C (sequential, no I/O)** rebuilds the returned `gaps` list by
   walking `grounded_answer.claims` in ITS OWN order again and looking up
   each claim's outcome (by `claim_id`) from Step B's results dict - never
   from completion order. This is what guarantees the output is ordered
   identically to the pre-concurrency sequential version regardless of which
   worker happens to finish first, and that a claim can never receive a
   different claim's judgment.

**Configurability.** `research/loop_control.py`'s new
`GAP_ANALYSIS_MAX_CONCURRENCY` constant (same file/style as
`CLAIM_EVALUATION_BUDGET`/`MAX_TOOL_CALLS_PER_ROUND`) sets the worker-pool
size. Default is `1`, which reproduces today's exact sequential call order
byte-for-byte - this pass adds the capability to raise it, it does not
change default production behavior. Raising the default is deliberately
left as a decision for a later, AC-powered pass once real timing evidence
against the live rate limiter exists (see the deferred-experiment artifact).

**Deterministic validation.** `tests/test_phase9_gap_analysis_concurrency.py`
(18 new tests, all using the `no_network` fixture, zero real network calls)
covers: per-level peak-concurrency bounds at 1/2/4 (using a lock-guarded
peak tracker and, for 2 and 4, a `threading.Barrier` that forces genuine
simultaneous overlap rather than merely failing to observe a violation);
output ordering under adversarially-scrambled completion order (a
per-claim `threading.Event` release chain driven by a background controller
thread); claim-association / no-cross-claim-contamination; budget
preservation under concurrency including the adversarial "4-way pool, 2
slots remaining, 10 claims wanting judgment -> exactly 2 real calls, never
more" case; single/multiple/all-worker failure isolation with no fabricated
gaps and no exception escaping; confirmation the scheduling layer does not
itself double-count a claim regardless of the judge's own internal retries;
confirmation every dispatched call still passes through the real, shared
`wait_for_rate_limit` (a spy wraps the real function rather than replacing
it, mocking only `requests.post` and the API key so no real HTTP occurs);
a hang/deadlock-and-thread-cleanup check (explicitly documented in the
test file as a correctness check, not a timing benchmark); and a
scheduling-equivalence proof that concurrency 1/2/4 produce byte-identical
gap lists, gap ordering, and `claim_judge_calls_used` values on a frozen
fixed-response fixture. All 18 pass; the two pre-existing gap-analysis test
files (`tests/test_phase9_claim_budget.py`'s 23 tests and
`tests/test_research_models_and_gap_analysis.py`'s pre-existing tests) were
re-run afterward with zero regressions.

---

## AC-Powered Gap-Analysis Concurrency Benchmark (live measurement, results)

Full raw data, provenance, and every field below: `artifacts/v2/phase9_gap_analysis_concurrency_experiment.json`.

**Environment:** AC Power confirmed via `pmset -g batt` immediately before
this pass began. macOS 15.7.4, Python 3.12.7, Apple M3, 8 logical cores,
16 GB RAM.

**Fixture provenance (disclosed):** no repo-tracked `artifacts/v2/*.json`
file stores full serialized `GroundedAnswer`+`Evidence` objects (only
summary counts) — confirmed by exhaustive search. Per explicit human
authorization, this benchmark reused the real, already-acquired
`LOCAL-06`/`LOCAL-04`/`LOCAL-02` scratchpad outputs (originally produced
during the already-recorded `PHASE9-PROCESS-DEV-001` unauthorized-traffic
incident) purely as frozen INPUT data — no additional `MedAgent.run()` or
biomedical-source call was made to obtain them. Fixtures: SMALL (4
judge-eligible claims, nearest available to the target 3), MEDIUM (5,
exact match), LARGE (6, nearest available to the target 8 — no scratchpad
case reaches 8).

**Method:** benchmarked `research/gap_analysis.py::analyze_gaps` directly
(not `MedAgent.run()`), with `GAP_ANALYSIS_MAX_CONCURRENCY` overridden
per-run via monkeypatch and restored to the production default (1) after
every run. Pre-registered execution order (rotated to avoid confounding
concurrency level with time-of-day/provider drift): SMALL→[1,2,4],
MEDIUM→[2,4,1], LARGE→[4,1,2]. Expected live logical judge calls: 45
(4+5+6 per fixture × 3 concurrency levels). **Actual: 45 — exact match.**
0 failures, 0 retries, 0 real 429s, 0 real 5xxs across all 45 calls.

**Raw results (n=1 per cell — no P95/P99 reported, per the measurement
contract's n≥30 rule):**

| Fixture | Concurrency=1 | Concurrency=2 | Concurrency=4 |
|---|---|---|---|
| SMALL (4 claims) | 36.419s | 48.186s (+32.3%) | 48.229s (+32.4%) |
| MEDIUM (5 claims) | 60.054s | 60.023s (−0.1%) | 60.387s (+0.6%) |
| LARGE (6 claims) | 72.170s | 72.296s (+0.2%) | 72.543s (+0.5%) |

**Rate-limiter finding (the key result):** per-call `rate_limit_wait_ms`
telemetry shows waits **stack additively** under concurrency — e.g. SMALL
at concurrency=4, the 4 calls' waits are ≈12s/24s/36s/48s, identical total
serialization time to the fully-sequential case. This is because
`utils.rate_limiter.TokenBucket`'s Cerebras bucket has `capacity=1`: only
one token is ever available, so the limiter fully serializes real provider
dispatch **regardless of how many threads are waiting**. Bounded
concurrency at the scheduling layer cannot reduce wall-clock time when the
binding constraint is a capacity=1 rate limiter — it only changes *which*
thread waits, never *how long* the total wait is. No burst above the
configured 5 RPM allowance was observed at any concurrency level (zero
evidence the limiter was bypassed).

SMALL's apparent 32% regression under concurrency=2/4 is **not** attributed
to a genuine concurrency-caused slowdown — it is plausibly confounded by
the shared, process-wide rate-limiter bucket's carryover state between
sequential benchmark runs (the concurrency=1 run happened to run first
against a still-full bucket; the concurrency=2/4 runs' first calls already
show ~11.7s waits against an already-partially-depleted bucket). With n=1
per condition, this cannot be statistically distinguished from a real
effect, and is disclosed as such rather than asserted either way. MEDIUM
and LARGE's null results (<1% difference) are unaffected by this
particular confound and are sufficient on their own to support the
conclusion below.

**Semantic check:** zero evidence of scheduler corruption at any
concurrency level — no missing claim, no duplicated claim, no wrong
claim-ID association, no ordering corrupted by completion order, no budget
mismatch. LARGE's single real gap (tied to claim `c-0`) appeared
identically at all 3 concurrency levels; SMALL/MEDIUM produced zero gaps
at all 3 levels. Any variation that did exist is attributable to provider
nondeterminism (if any), never to the scheduler.

**Candidate selection: KEEP 1.** No candidate (2 or 4) demonstrated a
meaningful, defensible latency improvement — MEDIUM and LARGE show the
mechanism is fully rate-limiter-bound (capacity=1), not scheduling-bound,
so there is structurally no wall-clock benefit available to capture under
the current 5 RPM/capacity=1 configuration. Per the governing directive's
own instruction ("if neither 2 nor 4 demonstrates a meaningful defensible
improvement, keep 1"), the default is unchanged. All 8 selection criteria
(zero scheduler defect, zero budget violation, zero claim loss, zero
cross-claim association, rate limiter respected, retry behavior preserved,
zero reliability regression) passed at every concurrency level — this is
not a rejection of the implementation's correctness, only a finding that
it provides no benefit under the current rate-limit configuration.

**E2E confirmation: deliberately not run.** Since the selected candidate
(1) equals the baseline (1), a live end-to-end comparison would measure
`GAP_ANALYSIS_MAX_CONCURRENCY=1` against itself — zero additional
information at the cost of additional live provider traffic. Documented as
a deliberate decision, not an omission, consistent with the governing
directive's "keep total live traffic bounded" and "no hidden exploratory
live runs" rules.

**Production default: unchanged.** OLD=1, NEW=1. The bounded-concurrency
mechanism remains implemented and fully tested (not removed) for a future
pass if the Cerebras rate-limit configuration is ever revisited —
changing that limiter is explicitly out of this pass's scope.

**Quality non-regression:** `CLAIM_EVALUATION_BUDGET=32`,
`MAX_TOOL_CALLS_PER_ROUND=12`, `MAX_TOOL_CALLS_PER_REQUEST=24` all
confirmed unchanged in `research/loop_control.py`. No production code was
modified this pass (measurement-only) — the deterministic regression
(`614 passed, 0 failed, 7 skipped`) is byte-identical to the pre-pass
baseline, confirming no side effect from the live benchmark.
