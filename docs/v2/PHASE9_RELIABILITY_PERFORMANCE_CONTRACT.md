# Phase 9 — Reliability / Performance Measurement Contract

Written BEFORE any baseline measurement or optimization, per the governing
directive's Step 4. Authoritative for what gets measured and how
statistics may be reported in this phase. Machine-readable mirror:
`artifacts/v2/phase9_measurement_contract.json`. Metric names/formulas
below are drawn directly from `docs/v2/EVALUATION_CONTRACT.md` §9/§10/§11
where those sections already define a metric — this document does not
invent competing definitions, it operationalizes them plus the additional
concurrency/efficiency metrics `V2_PHASE_GATES.md`'s Phase-9 section
requires that §9/§10/§11 don't individually name.

---

## 0. Statistical reporting rules (apply to every metric below)

1. **State n every time.** No metric is reported without its sample size
   next to it.
2. **P95/P99 require n ≥ 30 under fixed conditions** (verbatim from
   `EVALUATION_CONTRACT.md` §9: "not a benchmark until run at n≥30 under
   fixed conditions"). Below that, report the **raw per-run distribution**
   (every individual value) instead of a percentile claim.
3. **Mean/median/min/max/std dev may be reported at any n**, but n < 5
   should be labeled "illustrative only" (matching this project's own
   established convention for small dev samples, e.g. Phase 8's n=4 DEV
   set).
4. **State hardware, concurrency setting, AC/battery power state, and
   live-network status** alongside every latency/throughput number
   (`EVALUATION_CONTRACT.md` §9's explicit reporting methodology
   requirement, plus this session's own AC-power discipline).
5. **Never compare a battery-power run against an AC-power run as a
   before/after performance delta.** Battery-collected numbers (if any
   exist from earlier in this session) are disclosed as environment
   context only, never as a baseline for an optimization comparison.
6. **Preserve raw per-run timings**, not just aggregates — every baseline
   artifact stores the full list of per-run stage timings, not only
   summary statistics.
7. **No number is called "production-representative"** unless it clears
   this same n≥30 bar AND is disclosed as running on a single developer
   laptop, not production infrastructure (this project's standing
   caveat, carried from CTL-019).

---

## 1. LATENCY

All wall-clock, all in milliseconds unless noted, all captured via
`time.perf_counter()` (monotonic, immune to system clock adjustments).

| Metric | Definition | Where captured |
|---|---|---|
| End-to-end latency | full `MedAgent(...).run(query)` wall-clock, start to returned state | wraps the top-level `.run()` call |
| Query-understanding (NLU) latency | `query_analysis_node` wall-clock | node entry/exit timestamps |
| Tool-orchestration latency | `tool_orchestration_node` wall-clock (includes the Cerebras tool-selection call + all executed tool calls) | node entry/exit timestamps |
| Provider inference latency (per call) | wall-clock of each individual LLM call (Cerebras tool-selection, Cerebras/NVIDIA generation, NVIDIA judge) | already logged per-call by `config/llm_config.py`'s `[LLM DISPATCH]`/`[LLM DISPATCH RESULT]` lines and `orchestration/candidate_b_native_tools.py`'s own `latency_ms` return field — this phase adds structured capture of those existing values into an artifact, not new instrumentation |
| Rate-limit wait time (per call) | time spent inside `wait_for_rate_limit`/`TokenBucket.wait_for_token` before a call is allowed to proceed | measured by timing the call to `wait_for_rate_limit` itself, separately from the call it gates |
| Source-call latency (per source, PubMed/ClinicalTrials/ChEMBL) | each `BaseTool`-derived HTTP call's wall-clock, reported separately per source (per `EVALUATION_CONTRACT.md` §9: "genuinely different latency profiles") | `ToolResult.metadata["latency_ms"]`, already populated by `base_tool.py::_execute_with_monitoring` |
| Retrieval latency | `_retrieve_rag_context` wall-clock (includes the `_rag_retrieval_lock` wait, reported separately from the retrieval work itself) | wraps the call site in `synthesis_node` |
| Evidence normalization latency | `evidence_normalization_node` wall-clock | node entry/exit timestamps |
| Generation latency | `grounded_generation_node` wall-clock (the `generate_grounded_answer` call) | node entry/exit timestamps |
| Grounding-evaluation latency | per-claim `judge_claim_semantic` call wall-clock, summed and per-call, when the research loop's gap analysis runs it | wraps each judge call inside `research/gap_analysis.py` |
| Research-loop iteration latency | one full continue-branch cycle (`research_action_planning` → `research_execution` → `evidence_merge` → `grounded_generation` → `gap_analysis`) wall-clock | wraps the loop-body node sequence per iteration |
| Report-generation latency | `report_generation_node` wall-clock (legacy path) | node entry/exit timestamps |
| Local Python processing (derived) | end-to-end latency minus the sum of every above external-call/lock-wait component | computed, not directly measured — the residual after all known external waits are subtracted |

## 2. THROUGHPUT

| Metric | Definition |
|---|---|
| Completed queries/minute | successful `.run()` completions / wall-clock minutes, at a stated concurrency level |
| Concurrent request throughput | completions/minute at concurrency N, for each tested N (Step 19) |
| Provider call throughput | LLM calls completed/minute, aggregate across all provider surfaces |
| Tool-call throughput | biomedical tool calls completed/minute |

## 3. CONCURRENCY

| Metric | Definition |
|---|---|
| Successful concurrent executions | count of `.run()` calls that completed without an uncaught exception, out of N launched concurrently |
| State isolation | boolean per concurrent pair: no query/Evidence/citation/trace/stop-reason cross-contamination between two concurrently-run requests (verified by assertion, not sampled) |
| Race conditions observed | count of any assertion failure attributable to a race (cache corruption, duplicate IDs from a race, corrupted shared state) |
| Shared-client safety | boolean: the singleton tool-registry's `RetrySession`/rate-limiter/cache behave correctly under concurrent access (see Step 9's dedicated audit) |
| Duplicate execution | count of any tool/LLM call issued redundantly solely because of a race (not legitimate research-loop re-querying) |

## 4. RELIABILITY

Formulas are `EVALUATION_CONTRACT.md` §10's, applied to Phase 9's own
(broader than Phase 8's) fault matrix:

| Metric | Formula |
|---|---|
| Recovery rate | fault scenarios producing a correct disclosed-partial or full answer / total injected fault scenarios |
| Silent-failure rate | fault scenarios producing an answer with no disclosure of the failure / total injected fault scenarios |
| Partial-answer quality | Answer-Quality metrics (§6) on disclosed-partial answers |
| Retry amplification | mean additional latency/calls caused by retry logic, per fault event |
| Latency penalty | added wall-clock from fault handling vs. the clean-path baseline, same query |
| Timeout handling correctness | boolean per case: no indefinite block, bounded total wait |
| 429 handling correctness | boolean per case: retried within policy, never exceeds provider limit |
| 5xx handling correctness | boolean per case: retried within policy, safe terminal state if exhausted |
| Connection-error handling correctness | boolean per case |
| Malformed-response handling correctness | boolean per case: no crash, no fabricated Evidence |
| Retry exhaustion behavior | boolean per case: explicit failure state, never silent |
| Uncaught exception rate | uncaught exceptions / total requests (target: 0, per every reviewed code path's existing fail-safe design) |
| Fabricated Evidence IDs | count (target: 0, carried forward as an absolute invariant from every prior phase) |
| Invalid Evidence IDs | count (target: 0) |

## 5. EFFICIENCY

| Metric | Definition |
|---|---|
| LLM calls/query | count, already tracked via `get_llm_call_count()`/`get_thread_llm_call_count()` plus Cerebras's own per-call count |
| Tool calls/query | count, from `tool_call_history` length |
| Retrieval calls/query | count of `_retrieve_rag_context` invocations |
| Tokens/query | prompt + completion, combined and by stage, from each call's returned usage |
| Rate-limit wait/query | sum of §1's rate-limit-wait-time metric across the whole request |
| Retries/query | count, by cause (timeout/429/503/other), summed across all three provider-call implementations and the tool-HTTP layer |
| Redundant calls | tool/LLM calls that duplicate a call already made with identical arguments this request, excluding legitimate research-loop re-attempts after a genuine gap |
| Duplicate Evidence work | `evidence_duplicate_count` (already a first-class Phase-8 state field) |
| Wasted research iterations | iterations whose `ResearchActionStatus` is `executed_unproductive`/`executed_duplicate_only` / total iterations |

## 6. QUALITY GUARDRAILS (must not regress from any Phase-9 change)

| Metric | Source |
|---|---|
| Claim Support Precision | frozen Candidate B judge, §5 |
| Completeness | §6 |
| Citation precision / coverage | §7 |
| Fully grounded answer rate | §7 |
| Fabricated/invalid Evidence IDs | 0, absolute |
| Abstention correctness | human/judge-reviewed, matches Phase 8's own criterion |
| Research-loop correctness | stop-reason validity, per §11's "loop termination correctness" |
| Provenance integrity | `evidence_seen_ids`/`ResearchAction.new_evidence_ids` consistency, unchanged mechanism |

---

## 7. The three flagged findings — what will be MEASURED, not assumed

Per explicit instruction, none of the three findings from
`PHASE9_INITIAL_AUDIT.md` are acted on before measurement:

1. **Cerebras tool-selection zero-retry.** Measured via the fault matrix
   (Step 8): actual observed failure rate of `call_cerebras_native_tools`
   under real conditions, and — separately, safely, via network-boundary
   fault injection (the same safe method used in Phase 8's CTL-017 pass,
   never abusive real-world traffic) — what a bounded retry would have
   changed, BEFORE deciding whether to add one.
2. **`BaseTool.cache` unlocked dict.** Measured via the concurrency audit
   (Step 9): does concurrent access under this project's actual tested
   concurrency levels produce observable duplicate work or any race-
   attributable failure? A theoretical race is not the same as a measured
   one.
3. **No unified timeout budget.** Derived mathematically (Step 11) from
   already-declared constants (`MAX_RESEARCH_ITERATIONS`,
   `MAX_TOOL_CALLS_TOTAL`, `LLM_CALL_MAX_ATTEMPTS`,
   `LLM_CALL_TIMEOUT_SECONDS`, `MAX_RETRIES`, `RETRY_BACKOFF_MAX`, tool
   `API_TIMEOUT`) before any timeout-budget change is even considered.
