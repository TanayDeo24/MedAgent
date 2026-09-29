# Phase 9 — Initial Audit: Reliability / Concurrency / Performance

Written BEFORE any Phase-9 implementation change, per the governing
directive's Step 2/3. Starting checkpoint: branch
`medagent-v2-phase9-reliability-performance`, HEAD
`29eb68393e037e1c6d968982179bd5cf948f4873` (== `origin/main`), working tree
otherwise clean (one stray untracked scratch file,
`phase9_skip_audit.txt`, not a tracked-file modification — noted, not
touched). Default suite: 507 passed, 0 failed, 7 skipped. Live-enabled
suite (`RUN_LIVE_CHEMBL_TESTS=1`): 514 passed, 0 failed, 0 skipped. Both
match the checkpoint's stated expectation exactly.

---

## 1. Exact Phase-9 objective

Verbatim from `docs/v2/V2_PHASE_GATES.md` (lines 294–331):

> **Purpose:** implement the fault-injection matrix and measure
> reliability (`EVALUATION_CONTRACT.md` §10) plus latency/cost
> instrumentation (§9) under realistic concurrent load.

## 2. Exact authoritative exit gates

- **Work to perform:** design and freeze the fault-injection matrix
  (timeouts, 429/503, malformed responses, empty/partial source outage,
  invalid structured output, retriever/reranker/verifier failure per
  source and per stage); implement injected-fault test scenarios; measure
  recovery vs. silent-failure rates; instrument per-stage latency;
  validate concurrency safety (confirm no regression of the real, already-
  fixed Metal/MPS concurrency crash — commit `01760fe` — and test at the
  concurrency level actually planned for production, not just the
  previously-validated worker count).
- **Expected artifacts:** benchmark G (versioned scenario definitions), a
  reliability report, a latency/cost report with P50/P95 per stage.
- **Measurements:** recovery rate, silent-failure rate, partial-answer
  quality, retry amplification, latency penalty (§10); full latency/cost
  table (§9).
- **Exit gate:** silent-failure rate at or near zero (every injected fault
  either recovers or is disclosed — never both hidden and wrong); latency
  figures reported with hardware/concurrency stated, compared against but
  not forced to beat the Phase 0 reference point (one real end-to-end run:
  461s, 26 LLM calls, 11 tool calls; historical batch average
  ~177–210s/case — reference only, not a V2 target).
- **Stop condition:** any fault scenario producing a confidently-wrong,
  undisclosed answer is a blocking defect — fix before proceeding,
  regardless of rarity.
- **What must not be claimed yet:** final held-out generalization numbers
  (Phase 10's territory).

`EVALUATION_CONTRACT.md` §9 (Latency/Cost/System Metrics) and §10
(Reliability Metrics) define the exact metric formulas — reproduced in
full in `docs/v2/PHASE9_RELIABILITY_PERFORMANCE_CONTRACT.md` (companion
document, this pass) rather than duplicated here. §9's explicit reporting
methodology requirement: "all latency/cost numbers must state hardware,
concurrency setting, and sample size... not a benchmark until run at n≥30
under fixed conditions... No arbitrary aggressive thresholds are set."

## 3. Current architecture relevant to each gate

### LangGraph execution
Two separate compiled graphs: `build_agent_graph()` (pre-Phase-8, legacy
confidence-threshold loop via `verification_node`) and
`build_research_loop_graph()` (Phase 8, gap-driven loop, additive, opt-in
via `MedAgent(research_loop=True)`). Each `MedAgent()` instantiation
compiles and owns its own graph object — `agent/graph.py`'s
`__init__` calls `build_research_loop_graph()`/`build_agent_graph()`
fresh every time, never a shared/cached compiled graph. Recursion limits
are computed explicitly, not left at LangGraph's default 25:
`(MAX_RESEARCH_ITERATIONS * 5) + 15 = 30` for the research-loop graph,
`(self.max_iterations * 3) + 10` for the legacy graph.

### LLM client wrappers
Two independent implementations, not unified:
1. `config/llm_config.py::get_llm()` — LangChain `ChatNVIDIA`, wrapped in
   `_RateLimitedChatNVIDIA`: real hard wall-clock timeout via a daemon
   thread (`LLM_CALL_TIMEOUT_SECONDS=90`, deliberately NOT relying on
   `ChatNVIDIA`'s own `timeout=` param, which was observed live not to
   bound a stuck-open connection — see `EVAL_HANG_FIX_COMPLETE.md`), 3
   attempts total, fresh-client-per-retry, substring-matched
   429/503-only retry classification, module-level rate limiter (35 RPM,
   capacity=1), global + thread-local call counters.
2. `orchestration/candidate_b_native_tools.py::call_cerebras_native_tools()`
   — raw `requests.post`, **deliberately no retry** (documented Phase-3
   design choice: "a Candidate-B measurement pass wants the model's real
   single-shot tool-selection behavior... a silent retry would both
   double real spend... and obscure a genuine no-tool-call outcome"), a
   single 60s `requests` timeout, errors returned in `.error` (never
   raised) so the caller degrades safely.
3. `grounding_eval/nvidia_judge.py` — a third, separate raw-`requests`
   implementation with its own bounded retry (default 2) and 90s timeout.

**Finding:** three independent provider-call implementations with three
different retry/timeout policies is a real inconsistency, not
necessarily a defect — (1) and (3) both retry safely; (2) never retries,
by original design, for a documented reason specific to Phase-3
measurement purity. Whether that Phase-3-specific rationale should still
apply to (2)'s use inside the live, opt-in `research_loop=True` product
path (as opposed to only the original Candidate-B benchmark harness) is
exactly the kind of question Phase 9 should evaluate with a measured
before/after experiment (Step 13 discipline), not decide from first
principles here.

### Rate limiting
`utils/rate_limiter.py::TokenBucket`/`RateLimiter` — thread-safe (each
bucket has its own `threading.Lock`), global singleton `_rate_limiter`,
keyed buckets per provider/purpose. `wait_for_token()` polls via
`time.sleep(0.1)` in a spin-wait loop — not injectable-clock-friendly,
noted for Step 10/24 (tests needing a fake clock, not real sleeps).
Current keys: `nvidia_nim_llm` (35 RPM), `cerebras_candidate_b_native_tools`
(5 RPM), plus per-source keys inside each `BaseTool` subclass (PubMed 3
RPS, ClinicalTrials 10 RPS, ChEMBL 10 RPS — `config/settings.py`).

### Retry/backoff (tool HTTP layer)
`utils/retry_handler.py::RetrySession` (subclasses `requests.Session`) —
real exponential-jitter backoff (`calculate_backoff`), `MAX_RETRIES=3`
(→ 4 total attempts, confirmed empirically in Phase-8 live fault
verification: exactly 4 attempts observed for injected 429/503/timeout),
`RETRY_BACKOFF_BASE=2s`, `RETRY_BACKOFF_MAX=60s`. Retryable status set:
{429, 500, 502, 503, 504}; non-retryable: {400, 401, 403, 404, 405, 422}.
`ConnectionError`/`Timeout` always retried.

### Tool HTTP clients
`tools/base_tool.py::BaseTool` — one `RetrySession` instance per tool
(constructed once, at module-import time, via `orchestration/registry.py`'s
module-level `DEFAULT_REGISTRY` singleton — `pubmed`/`clinical_trials`/
`chembl` `BaseTool` subclass instances are shared across every
`MedAgent()` instance and every concurrent thread/request in the current
process). Each instance also owns a plain, unlocked `self.cache: Dict[str,
tuple[float, Any]]` (in-memory TTL cache, `CACHE_TTL=3600s`,
`ENABLE_CACHE=True` by default).

### Retrieval
`retrieval/retriever.py::_get_retriever()` — lazy module-level singleton
(`global _retriever; if _retriever is None: _retriever = Retriever()`),
theoretically racy if called concurrently before first use, but
**practically eager**: `agent/nodes.py` calls `_get_retriever()` at its
own module-import time (single-threaded, before any request can run),
so the race window does not occur in this codebase's actual call pattern.
RAG retrieval itself is serialized process-wide by
`agent.nodes._rag_retrieval_lock` (a `threading.Lock`), a real fix for a
real, previously-crashing Metal/MPS concurrency bug (commit `01760fe`) —
confirmed still present (`grep` verified this session).

### Evidence normalization
`evidence_normalization_node` (frozen Phase 5) recomputes `state["evidence"]`
from scratch on every call from the full, ever-growing
`tool_results`/`tool_call_history`/`rag_documents` — no incremental/cached
computation, no shared mutable state across requests (operates purely on
the per-request `AgentState` dict). Cost scales with total accumulated
raw records, not just new ones — a legitimate Step 17 optimization
candidate (recomputing from scratch every research-loop iteration is
`O(n²)` in total raw record count across `MAX_RESEARCH_ITERATIONS`
rounds) worth measuring, not assuming.

### Research loop
`research/loop_control.py` — four independent hard ceilings:
`MAX_RESEARCH_ITERATIONS=3`, `MAX_TOOL_CALLS_TOTAL=8`,
`MAX_REPEATED_ACTION=1`, `MAX_CONSECUTIVE_TOOL_FAILURE_ROUNDS=2`. All
enforced in one function (`decide_stop_reason`), proven non-infinite by
`test_decide_stop_never_infinite_for_a_persistently_unresolved_gap`. This
session's own live-verification pass (Phase 8 local closure) independently
confirmed zero infinite loops across 11 real live runs.

### Synchronous vs. concurrent paths
The core `MedAgent.run()` pipeline is entirely synchronous (no `asyncio`
anywhere in the reviewed code paths). Concurrency, where it exists, is
applied EXTERNALLY at the case/request level via
`ThreadPoolExecutor` — `evaluation/evaluator.py::_run_concurrent` is the
only such call site found, and it already follows the correct pattern
(fresh `MedAgent()` per task, never a shared graph instance). No existing
API/server layer was found that would multiplex real concurrent user
requests onto shared `MedAgent` state — `main.py` constructs one
`MedAgent()` per CLI invocation (single process, single request).

### Shared mutable state (full inventory, classified)

| Object | Scope | Classification |
|---|---|---|
| `orchestration.registry.DEFAULT_REGISTRY` (and its 3 `BaseTool` instances) | module-level singleton, process-wide | shared, mostly thread-safe (each tool's `RetrySession`/rate limiter are safe for concurrent use), **except** its plain-dict cache (see below) |
| `BaseTool.cache` (per-instance dict) | shared across every concurrent request via the singleton tool instances | **shared, check-then-act race** — not corrupting (CPython dict ops are atomic under the GIL) but can cause redundant duplicate work ("thundering herd") under concurrent identical queries; not a correctness bug, a wasted-work risk |
| `BaseTool.session` (`RetrySession`) | shared, module-level | shared, believed thread-safe (`requests.Session` + urllib3 connection pooling are designed for concurrent use); not yet load-tested under this codebase's own concurrency in this pass |
| `utils.rate_limiter._rate_limiter` (global `RateLimiter`) | shared, module-level | shared, thread-safe by design (`threading.Lock` per bucket) |
| `config.llm_config._llm_call_count` / `_llm_call_lock` | shared, module-level | shared, thread-safe (explicit lock) |
| `config.llm_config._thread_local` | thread-local by design | request-local (correct, intentional) |
| `retrieval.retriever._retriever` (lazy singleton) | shared, module-level | shared; theoretically racy init, practically eager (see above); the underlying FAISS/BM25 index objects are read-only after construction — safe for concurrent reads once built |
| `agent.nodes._rag_retrieval_lock` | shared, module-level | shared, thread-safe (explicit lock; the whole point of its existence) |
| `agent.nodes._chembl_backfill_tool` (module-level `ChEMBLTool()`) | shared, module-level | shared; same classification as the registry's ChEMBL instance (own cache/session) |
| `AgentState` (the LangGraph state dict) | constructed fresh per `MedAgent().run()` call | request-local — not shared across concurrent requests (confirmed: `create_initial_state()` builds a new dict every call, and `evaluation/evaluator.py`'s own concurrency pattern gives each task a fresh `MedAgent()`) |
| Evidence/GroundedAnswer/citation objects | constructed fresh per request from `AgentState` | request-local |
| Logging (`utils/logger.py`) | not yet inspected line-by-line this pass | **unknown** — flagged for Step 9's deeper pass (Python's standard `logging` module is thread-safe by design, but any custom buffering/context here needs direct confirmation) |

### Caches
See "Tool HTTP clients" above. No other cache located in the reviewed
code paths (no LLM-response cache, no Evidence cache, no retrieval-result
cache beyond the FAISS index itself).

### Provider clients
NVIDIA (`ChatNVIDIA` via `config/llm_config.py`), Cerebras (raw
`requests` via `orchestration/candidate_b_native_tools.py` and
`nlu/extractor.py`), NVIDIA judge (raw `requests` via
`grounding_eval/nvidia_judge.py`) — three provider surfaces, as above.

### Timeout handling
Inconsistent across layers, but each individually bounded:
- Tool HTTP calls: `API_TIMEOUT=30s` (per attempt) × up to 4 attempts
  (`RetrySession`) = worst case ~30s×4 + backoff (up to ~4×60s max
  backoff, though real observed backoffs were single-digit seconds — see
  Phase-8 live fault-injection evidence).
- NVIDIA `ChatNVIDIA` calls: `LLM_CALL_TIMEOUT_SECONDS=90s` (real,
  enforced) × `LLM_CALL_MAX_ATTEMPTS=3` = worst case 270s + backoff.
- Cerebras tool-selection calls: 60s, single attempt, no retry = worst
  case 60s exactly.
- NVIDIA judge calls: 90s × up to 2 retries.
- No single "whole-request" timeout budget exists anywhere — a pathological
  worst case (every layer maxing out its own timeout across every research
  iteration) is not currently bounded by an outer deadline, only by the
  research loop's own iteration/call-count ceilings. Quantified precisely
  in Step 11 (this document does not attempt the full multiplication
  here).

### Fault handling
Already exercised for real in Phase-8 local verification (11 live runs,
including 3 explicitly fault-injected cases: timeout, 429, and simultaneous
5xx across all 3 biomedical sources) — every case terminated safely, zero
fabricated Evidence, zero infinite loops, `error_category` recorded at a
flat `tool_error`/`internal_error`/`registry_invalid` granularity (not
per-HTTP-status — a documented, disclosed limitation, not a defect,
per `PHASE8_LOCAL_VERIFICATION_AUDIT.md`'s CTL-017 section). Phase 9's own
mandate (per CTL-017's ledger text) is to build the broader,
system-wide fault-injection matrix this narrow Phase-8 pass didn't
attempt (concurrent faults, more fault classes, load-level testing).

### Logging/tracing
Standard Python `logging` via `utils/logger.py` (not yet read
line-by-line this pass — flagged above). `tool_call_history` and
`intermediate_thoughts` provide a structured per-request trace embedded in
`AgentState` itself (request-local, not a global/shared trace buffer) —
this is actually a good concurrency property already in place (no shared
trace-ID registry to leak across concurrent requests).

## 4. Existing reliability mechanisms
- Bounded, classified HTTP retry (`RetrySession`) with real exponential
  jitter backoff.
- Real, hard, enforced LLM call timeout (daemon-thread-based, specifically
  engineered around a previously-observed real hang incident).
- Bounded LLM retry on 429/503 with fresh-client reconstruction.
- Four independent, tested research-loop bounds, proven non-infinite.
- A real, previously-fixed concurrency crash (Metal/MPS) with a documented
  fix and its own verification test.
- Fail-safe (never fail-crash) degradation at every reviewed provider
  boundary: a failure becomes a recorded error + safe continuation, never
  an unhandled exception reaching the caller (confirmed both by code
  reading and by 11 real live runs in Phase-8 local verification).

## 5. Existing concurrency behavior
Request-level concurrency is NOT implemented inside `MedAgent`/the graph
itself — it is achieved externally by the caller constructing multiple
independent `MedAgent()` instances (the `evaluation/evaluator.py` pattern).
This is a good, low-risk design: most per-request state is naturally
isolated. The real shared-state surface is narrow: the singleton tool
registry (rate limiters + HTTP sessions + per-tool caches) and the RAG
retriever/lock. No test in the current 514-test suite exercises multiple
concurrent `MedAgent(research_loop=True).run()` calls against the real
shared singletons (the closest existing coverage is
`PHASE3_CONCURRENCY_VALIDATION.md`'s historical work and the Metal/MPS
fix's own "3x repeated 4-thread concurrent stress test" — both pre-Phase-8,
neither exercising the research-loop graph).

## 6. Existing retry/backoff behavior
See §3 above (three independent implementations). All three are
individually bounded (no unbounded retry anywhere found). None currently
account for the OTHER layers' retries when computing worst-case total
wait — i.e., there's no shared "total time/attempts budget" spanning
tool-HTTP-retry × LLM-retry × research-loop-iteration. Quantified in
Step 11 (worst-case call bounds), not assumed safe here.

## 7. Current performance bottlenecks (to be MEASURED, not assumed)
Candidates identified by code reading, each requiring actual profiling
before any change (Step 6/7 of this pass, not yet performed):
- LLM inference wall-clock (multiple sequential Cerebras/NVIDIA calls per
  request — query analysis, tool orchestration, synthesis, grounded
  generation, gap analysis's per-claim judge calls, report generation;
  Phase-8 live runs observed single LLM calls taking 8–90+ seconds under
  real provider load).
- Serial source retrieval: `tool_orchestration_node` issues tool calls
  from a single native-tool-calling round (parallel_tool_calls=True at
  the PROVIDER level, but `execute_validated_call` invocations in
  `agent/nodes.py`'s loop over `raw_tool_calls` are issued sequentially
  in Python, not concurrently) — a plausible, not yet confirmed,
  candidate for safe parallelization (Step 12).
- `evidence_normalization_node`'s from-scratch recomputation every
  research-loop iteration (see §3).
- RAG retrieval's forced serialization (`_rag_retrieval_lock`) — a real,
  accepted concurrency cost from the Metal/MPS fix, worth re-measuring
  under Phase-9's actual target concurrency level rather than assuming
  its Phase-3-era "small cost" characterization still holds.
- Provider-side rate-limit waiting (Cerebras 5 RPM for tool-selection
  calls, NVIDIA 35 RPM) — directly observable in Phase-8 live logs as
  real wait time, not yet isolated as its own measured line item.

## 8. What is missing
- No frozen, versioned fault-injection scenario matrix (Phase 9's own
  primary deliverable, per its exit gate — "benchmark G").
- No per-stage latency instrumentation output (stage boundaries exist
  functionally as separate graph nodes, but no structured latency capture
  keyed by stage name currently persists to an artifact).
- No concurrency test exercising the real shared singletons under the
  research-loop graph specifically.
- No worst-case call-bound calculation on record (Step 11).
- No injectable/fake-clock-based rate-limiter/retry unit tests (current
  tests, where they touch timing, appear to use real sleeps or mocks at
  the HTTP layer — needs a dedicated pass, Step 24).
- No unified retry/timeout policy across the three provider-call
  implementations (may be intentional per-purpose, or may be worth
  partial unification — a Step 13 experiment, not decided here).

## 9. What is already sufficient (not to be re-built)
- Tool-HTTP retry/backoff (`RetrySession`) — real, tested, exponential,
  jittered, correctly classified retryable vs. non-retryable.
- LLM hard-timeout enforcement — specifically engineered against a real
  past incident, already correct.
- Research-loop boundedness — four independent ceilings, already proven
  non-infinite by both unit tests and 11 real live runs.
- The Metal/MPS concurrency fix — already correct and already tested;
  Phase 9's job is to CONFIRM no regression, not redesign it.
- Fail-safe degradation at every provider boundary — already the
  consistent pattern everywhere reviewed.

## 10. What is explicitly out of scope for Phase 9
- Any change to gap taxonomy, research-action taxonomy, stop conditions,
  dedup logic, prompts, generation behavior, Evidence schemas, or the
  grounding evaluator, UNLESS Phase-9 testing exposes a genuine
  correctness defect (per the governing directive's own carve-out).
- Any Phase-10 held-out benchmark access, construction, or scoring.
- Retrieval quality tuning (owned by Phase 4, frozen).
- Grounding/citation quality tuning (owned by Phases 6/7, frozen).
- Final production deployment decisions (explicitly deferred in
  `RESUME_METRIC_CANDIDATES.md`'s Phase-2 framing note: "that question is
  out of Phase 2's scope and should be revisited (Phase 9 or a dedicated
  deployment decision)" — Phase 9 may inform this but does not decide it
  here).

## 11. What belongs to Phase 10 instead
Final held-out generalization numbers, and any claim that a Phase-9
measurement is "production-representative" without Phase-9's own larger-n
discipline first (mirrors CTL-019's exact caveat from Phase 8's local
closure — carried forward, not reset).

## 12. Metrics that must be measured before optimization
Full detail in the companion `docs/v2/PHASE9_RELIABILITY_PERFORMANCE_CONTRACT.md`
and `artifacts/v2/phase9_measurement_contract.json` (this pass, written
next, per Step 4). At minimum: per-stage latency (not just end-to-end),
LLM/tool call counts, retry counts by cause, rate-limit wait time,
research-loop iteration counts — every one of these already has a real
code-level hook (call counters, `tool_call_history`, research-loop state
fields) to read from, so instrumentation is mostly "capture and persist
what already exists," not "add new probes to uninstrumented code."

## 13. Remaining CTL debt relevant to Phase 9
Per `docs/v2/CLOUD_TO_LOCAL_GAP_CLOSURE.md` (re-read this session):
- **CTL-016** — PARTIALLY CLOSED. A real, live 2-round multi-iteration
  case is verified; no organic 3-round live case occurred in the Phase-8
  local-closure pass. Explicitly non-blocking for Phase 9's start.
  Phase 9's own broader load/concurrency testing may incidentally produce
  a 3-round case (a query that genuinely needs it under real conditions);
  if so, it should be recorded and CTL-016 re-assessed, but Phase 9 must
  NOT manufacture one artificially just to close this item — that would
  violate the same "no benchmark-chasing" principle this project has
  followed since Phase 8's DEV-D.
- **CTL-017** — CLOSED for its Phase-8-declared narrow scope (the research
  loop's own bounded response to 3 real, individually-injected fault
  classes). Phase 9 owns the system-wide fault-injection matrix explicitly
  named in `V2_PHASE_GATES.md`'s Phase-9 section and in CTL-017's own
  ledger text ("Phase 9 owns the SYSTEM-WIDE fault matrix"). This Phase-9
  pass's fault matrix (Step 8) is that broader work — not a re-verification
  of what CTL-017 already closed, but a genuine expansion (concurrent
  faults, more fault classes, per-stage/per-source breadth, load-level
  conditions).
- **CTL-019** — re-measured and disclosed in the Phase-8 local-closure
  pass (n=8 live cases); explicitly NOT yet production-representative
  ("not citable as production-representative until a larger-n sample
  exists (Phase 9/11)"). Phase 9's own larger-scale measurement work is
  a legitimate opportunity to grow this sample size honestly — but any
  Phase-9 metric must independently earn its own n-disclosure and
  resume-safe/not-yet-resume-safe classification (Step 27), not silently
  inherit CTL-019's closure status by association.

No other CTL item (013–015, 018, 020) has Phase-9-relevant remaining work
— all fully CLOSED per the Phase-8 local-closure pass, unrelated to
reliability/concurrency/performance scope.

## 14. Baseline default-vs-live test behavior
Recorded in full in this report's STEP 1 section (see the human-facing
report accompanying this document). Summary: default `pytest tests/ -q -rs`
→ 507 passed, 0 failed, 7 skipped (all 7 = live ChEMBL tests, opt-in via
`RUN_LIVE_CHEMBL_TESTS=1`); with that flag set → 514 passed, 0 failed, 0
skipped. Both exactly match the checkpoint's stated expectation — no
unexplained failure, no need to root-cause before starting Phase 9.
