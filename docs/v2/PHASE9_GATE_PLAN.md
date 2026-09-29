# Phase 9 — Gate Plan (retrospective, from executed history)

This document records the ACTUAL sequence of gated passes executed for
Phase 9 (Reliability/Concurrency/Performance), in order, with the artifact
each gate produced. It is written retrospectively, after the fact, from the
real work already performed - no gate below is hypothetical or planned-but-
not-run. Each gate required a human-reviewed stop before the next began,
per this project's phase-gate methodology.

## Gate sequence

### Gate 1 — Measurement contract + workload manifest
Established the statistical reporting rules (n≥30 for any percentile claim,
raw values otherwise), the metrics to be measured (latency/throughput/
concurrency/reliability/efficiency/quality guardrails), and the workload
cases to be used.
- **Artifacts:** `artifacts/v2/phase9_measurement_contract.json`,
  `artifacts/v2/phase9_workload_manifest.json`
- **Doc:** `docs/v2/PHASE9_RELIABILITY_PERFORMANCE_CONTRACT.md`

### Gate 2 — Unoptimized baseline measurement + bottleneck profile
Measured the pre-optimization system exactly as it stood, across the
workload manifest's cases, and derived a per-node stage-time-share ranking.
- **Artifacts:** `artifacts/v2/phase9_baseline_results.json`,
  `artifacts/v2/phase9_baseline_profile.json`
- **Finding:** gap_analysis 56.3% of stage time, report_generation 19.5%,
  synthesis 17.2%, grounded_generation 4.6%, tool/research execution ~2%
  combined, local Python negligible.

### Gate 3 — Systematic fault matrix, concurrency safety audit, rate-limiter
audit, formal boundedness derivation (Steps 8-11)
Enumerated fault scenarios, audited thread-safety of shared mutable state,
audited the rate limiter's real behavior, and derived worst-case boundedness
formulas from the codebase as it then stood.
- **Artifacts:** `artifacts/v2/phase9_fault_matrix.json`,
  `artifacts/v2/phase9_concurrency_audit.json`,
  `artifacts/v2/phase9_rate_limiter_audit.json`,
  `artifacts/v2/phase9_boundedness_analysis.json`

### Gate 4 — PHASE9-PROCESS-DEV-001 remediation
A human audit found ~19 unauthorized real live `MedAgent.run()` executions
occurred during Gate 3 via scratchpad scripts. This gate: created a formal
process-deviation record (not a product defect), separated Category A
(controlled/authoritative) from Category B (unplanned live/supplementary)
evidence, reconciled the affected findings from Category A evidence only,
and re-validated tests - without any additional live provider traffic.
- **Artifact:** `artifacts/v2/phase9_process_deviation_001.json`
- **Doc:** `docs/v2/PHASE9_FAILURE_ANALYSIS.md`'s PHASE9-PROCESS-DEV-001 record

### Gate 5 — Pre-optimization consistency audit
Reconciled several internal inconsistencies discovered before optimization
could be authorized: a fault-count discrepancy, PHASE9-DEFECT-001's
"unbounded" framing (corrected to "missing an intentional application-level
budget" - the actual generation path has a finite, if large, provider-token-
derived ceiling), tool/source-call ceiling formula reconciliation,
concurrency isolation test coverage, rate-limiter starvation/wait-bound
clarification, and terminology cleanup.
- **Doc:** `docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md`'s "PRE-OPTIMIZATION
  CONSISTENCY AUDIT" addendum

### Gate 6 — Boundedness Hardening pass (PHASE9-DEFECT-001 / -002 fixes)
Implemented `CLAIM_EVALUATION_BUDGET=32` (request-global claim-judge-call
budget) and `MAX_TOOL_CALLS_PER_ROUND=12`/`MAX_TOOL_CALLS_PER_REQUEST=24`
(request-global tool-call budgets), both derived from real Phase-8 dev/
validation corpus distributions, with extensive deterministic tests and a
network-egress test guard (`tests/conftest.py`'s `no_network` fixture).
- **Artifacts:** `artifacts/v2/phase9_claim_and_tool_call_distributions.json`
- **Code:** `research/loop_control.py`, `research/gap_analysis.py`,
  `agent/nodes.py`, `agent/state.py`, `research/action_planning.py`,
  `research/models.py`
- **Tests:** `tests/test_phase9_claim_budget.py`,
  `tests/test_phase9_tool_call_budget.py`,
  `tests/test_phase9_quality_non_regression.py`,
  `tests/test_phase9_network_guard.py`

### Gate 7 — PHASE9-PROCESS-DEV-002 discovery and remediation
During Gate 6's own test-writing, a genuine pre-existing test-harness
thread-safety race was discovered (per-thread `pytest.MonkeyPatch()`/
`.undo()` mutating shared, process-global module attributes) that could let
a real `ChatNVIDIA` client get constructed during a supposedly fully-stubbed
concurrency test. Fixed by installing stubs once, globally, before spawning
any thread.
- **Artifact:** `artifacts/v2/phase9_process_deviation_002.json`

### Gate 8 — Gap-analysis bounded-concurrency implementation (scheduling only)
Implemented `GAP_ANALYSIS_MAX_CONCURRENCY` (default 1) as a configurable
bounded-concurrency mechanism for independent per-claim judge calls,
preserving ordering/budget/rate-limiter/retry semantics, with extensive
deterministic barrier/stub-based tests. Explicitly performed on battery
power with zero timing-sensitive measurement and zero live calls.
- **Code:** `research/gap_analysis.py`, `research/loop_control.py`
- **Tests:** `tests/test_phase9_gap_analysis_concurrency.py`
- **Artifact (pre-registration only at this gate):**
  `artifacts/v2/phase9_gap_analysis_concurrency_experiment.json`

### Gate 9 — AC-powered gap-analysis concurrency benchmark (live)
With AC power confirmed, ran the pre-registered live A/B/C comparison
(concurrency 1/2/4) across SMALL/MEDIUM/LARGE frozen scratchpad fixtures -
45 planned live judge calls, 45 actual, 0 failures/retries/429/5xx.
- **Finding:** concurrency provides no meaningful latency improvement - the
  shared Cerebras judge rate limiter (`capacity=1`, 5 RPM) fully serializes
  dispatch regardless of thread count; waits stack additively.
- **Decision:** `GAP_ANALYSIS_MAX_CONCURRENCY=1` retained as the production
  default.
- **Artifact:** `artifacts/v2/phase9_gap_analysis_concurrency_experiment.json`
  (completed)

### Gate 10 — Post-concurrency optimization decision audit
From existing evidence only (no new live calls), surveyed every
provider-backed stage, derived theoretical rate-limit floors for gap-
analysis batching at various sizes, audited report_generation/synthesis/
tool-selection-retry/BaseTool.cache as optimization candidates, and ranked
all candidates. Selected gap-analysis PAIR BATCHING (batch_size=2) as the
single next experiment - the only lever identified that can reduce the
rate-limit floor itself (concurrency provably cannot).
- **Artifact:** `artifacts/v2/phase9_next_optimization_decision.json`

### Gate 11 — Phase-9 FINAL freeze pass (this pass)
Completed all remaining Phase-9 work in one governed pass:
- Durably froze the SMALL/MEDIUM/LARGE benchmark fixtures into a
  repo-tracked artifact (`artifacts/v2/phase9_gap_analysis_frozen_fixtures.json`),
  ending dependence on session-ephemeral scratchpad paths.
- Implemented gap-analysis PAIR BATCHING (`GAP_ANALYSIS_BATCH_SIZE`,
  default 1; supported values 1/2 only) with strict claim_id-tagged batch
  request/response validation, whole-batch failure semantics (new
  `GapType.CLAIM_EVALUATION_FAILED`), and per-claim (not per-batch) budget
  accounting.
- Deterministically validated the implementation (29 new tests,
  `tests/test_phase9_pair_batching.py`) and confirmed semantic equivalence
  between batch_size=1 and batch_size=2 on the frozen fixtures with judge
  responses held fixed.
- Ran the full offline regression (0 unexpected failures, 0 unexpected
  provider traffic).
- Ran the pre-registered, AC-powered live pair-batching A/B benchmark
  (contemporaneous batch_size=1 vs batch_size=2 control, 23 planned live
  judge requests).
- Selected/rejected batching per the pre-registered rollback criteria and
  locked the final Phase-9 configuration.
- Ran fresh, pre-registered final Phase-9 validation on cases distinct from
  the optimization/tuning fixtures.
- Finalized CTL-016/017/019 carryover status.
- Ran the final full offline regression and the final live-enabled ChEMBL
  regression.
- Classified every Phase-9 candidate metric as resume-safe or not.
- Produced `docs/v2/PHASE9_FINAL_GATE_AUDIT.md`.
- **Result:** see `docs/v2/PHASE9_FINAL_GATE_AUDIT.md` for the authoritative
  per-gate PASS/FAIL/PARTIAL determination and the final freeze-readiness
  decision.
