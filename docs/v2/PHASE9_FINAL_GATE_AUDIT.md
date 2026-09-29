# Phase 9 — Final Gate Audit

Every gate below cites the artifact/evidence it rests on. No gate is marked
PASS on prose assertion alone. See `docs/v2/PHASE9_GATE_PLAN.md` for the
full chronological history that produced this evidence.

| # | Gate | Evidence / Artifact | Result | PASS/FAIL/PARTIAL | Caveat |
|---|---|---|---|---|---|
| 1 | Measurement contract established before any measurement | `artifacts/v2/phase9_measurement_contract.json`, `docs/v2/PHASE9_RELIABILITY_PERFORMANCE_CONTRACT.md` | Statistical rules (n>=30 for percentiles), metrics, workload frozen before Step 6 | **PASS** | — |
| 2 | Unoptimized baseline measured | `artifacts/v2/phase9_baseline_results.json`, `artifacts/v2/phase9_baseline_profile.json` | gap_analysis 56.3% dominant bottleneck identified | **PASS** | — |
| 3 | Systematic fault matrix | `artifacts/v2/phase9_fault_matrix.json` | All planned fault classes exercised, safe termination in every case | **PASS** | Also closes CTL-017's system-wide scope |
| 4 | Concurrency safety audit | `artifacts/v2/phase9_concurrency_audit.json` | Shared mutable state audited; `BaseTool.cache` race confirmed inefficiency-only (2 duplicate executions under a FORCED barrier test, never naturally observed) | **PASS** | Cache race classified LOW PRIORITY, not fixed - documented, not blocking |
| 5 | Rate-limiter audit | `artifacts/v2/phase9_rate_limiter_audit.json` | `TokenBucket` thread-safety confirmed; capacity=1 behavior documented | **PASS** | — |
| 6 | Formal worst-case boundedness derivation | `artifacts/v2/phase9_boundedness_analysis.json`, PRE-OPTIMIZATION CONSISTENCY AUDIT corrections | Recomputed post-fix bounds: max 32 claim-judge calls/request, max 24 logical tool calls/request | **PASS** | Historical isolated-request wall-clock estimate valid only under documented closed-workload assumptions (limiter not FIFO/fair under sustained contention) |
| 7 | PHASE9-PROCESS-DEV-001 remediation | `artifacts/v2/phase9_process_deviation_001.json` | Unauthorized live traffic separated into Category A/B evidence, reconciled, re-validated | **PASS** | Process deviation, not a product defect |
| 8 | PHASE9-DEFECT-001 fix (claim-evaluation budget) | `research/loop_control.py`, `research/gap_analysis.py`, `tests/test_phase9_claim_budget.py` (11 tests) | `CLAIM_EVALUATION_BUDGET=32`, request-global, deterministically tested, live-confirmed never exceeded in final validation | **PASS** | — |
| 9 | PHASE9-DEFECT-002 fix (tool-call budget) | `research/loop_control.py`, `agent/nodes.py`, `tests/test_phase9_tool_call_budget.py` (11 tests) | `MAX_TOOL_CALLS_PER_ROUND=12`/`MAX_TOOL_CALLS_PER_REQUEST=24`, deterministically tested, live-confirmed never exceeded | **PASS** | — |
| 10 | PHASE9-PROCESS-DEV-002 remediation | `artifacts/v2/phase9_process_deviation_002.json` | Test-harness monkeypatch race root-caused and fixed | **PASS** | Process deviation, not a product defect |
| 11 | Gap-analysis bounded-concurrency implementation | `research/gap_analysis.py`, `tests/test_phase9_gap_analysis_concurrency.py` (18 tests) | Scheduling-layer mechanism implemented, race-free, order-preserving, deterministically validated | **PASS** | — |
| 12 | AC-powered concurrency benchmark | `artifacts/v2/phase9_gap_analysis_concurrency_experiment.json` | 45/45 planned/actual live calls, 0 failures; no meaningful latency improvement at concurrency 2/4 | **PASS** | n=1/cell - raw values only, no percentile claim; decision is KEEP 1 (a genuine negative result, not an omission) |
| 13 | Post-concurrency optimization decision audit | `artifacts/v2/phase9_next_optimization_decision.json` | Pair batching selected as the sole next candidate from ranked evidence | **PASS** | — |
| 14 | Durable benchmark fixtures frozen | `artifacts/v2/phase9_gap_analysis_frozen_fixtures.json` | SMALL/MEDIUM/LARGE fixtures repo-tracked with checksums, provenance disclosed | **PASS** | — |
| 15 | Pair-batching implementation | `grounding_eval/judge.py::judge_claims_batch`, `research/gap_analysis.py`, `research/models.py::CLAIM_EVALUATION_FAILED` | Strict claim_id validation, whole-batch failure semantics, per-claim budget accounting | **PASS** | — |
| 16 | Pair-batching deterministic validation | `tests/test_phase9_pair_batching.py` (29 tests), incl. semantic equivalence on frozen fixtures | All pass; batch1 vs batch2 equivalence proven with judge responses held fixed | **PASS** | — |
| 17 | AC-powered pair-batching benchmark | `artifacts/v2/phase9_pair_batching_experiment.json` | 23/23 planned/actual live calls, 0 failures/retries; SMALL -34.1%, MEDIUM -40.4%, LARGE -50.1%; zero contamination/false-support | **PASS** | n=1/cell - raw values only |
| 18 | Candidate selection | `artifacts/v2/phase9_pair_batching_experiment.json::candidate_selection` | All 8 pre-registered criteria passed; SELECT batch_size=2 | **PASS** | — |
| 19 | PHASE9-PROCESS-DEV-003 discovery and remediation | `artifacts/v2/phase9_process_deviation_003.json`, `docs/v2/PHASE9_FAILURE_ANALYSIS.md` | Suspected (unconfirmed) live-traffic risk from stale tests after the default flip; 3 files remediated (network guards + batch-size pins); static audit found no other exposed file | **PASS** | Suspected, not confirmed - explicitly disclosed as such; no new live call made to verify |
| 20 | Final configuration lock | `artifacts/v2/phase9_frozen_config.json` | All 9 constants recorded with decision provenance | **PASS** | No further optimization tuning authorized past this point |
| 21 | Fresh final validation pre-registration | `artifacts/v2/phase9_final_validation_manifest.json` | 5 cases, frozen config recorded, written before execution | **PASS** | — |
| 22 | Fresh final validation execution | `/private/tmp/.../scratchpad/final_validation/results.json` (raw), summarized in `docs/v2/PHASE_METRICS_LEDGER.md` | 5/5 cases reached explicit terminal states; 0 infinite loops; 0 fabricated Evidence IDs accepted; budgets respected; PHASE8-DEFECT-001 caveat mechanism confirmed live | **PASS** | 2/5 cases hit a pre-existing Phase-6/7 generation-layer hard-gate rejection (safety mechanism working as designed) - disclosed, not a Phase-9 defect |
| 23 | CTL-016 carryover | `docs/v2/CLOUD_TO_LOCAL_GAP_CLOSURE.md` | Unchanged - no organic 3-round live `MedAgent.run()` case added this phase | **PARTIAL** (unchanged) | Non-blocking; remaining requirement: one organic 3-round live case; owner phase 8/13 |
| 24 | CTL-017 carryover | `docs/v2/CLOUD_TO_LOCAL_GAP_CLOSURE.md` | Both narrow scope (Phase-8 pass) and Phase 9's own system-wide fault matrix complete | **PASS (CLOSED)** | — |
| 25 | CTL-019 carryover | `docs/v2/CLOUD_TO_LOCAL_GAP_CLOSURE.md` | Unchanged - Phase 9's live measurements were gap-analysis-specific, not a larger-n Phase-8 DEV/Validation re-measurement | **PARTIAL** (unchanged, citation-time gate) | Non-blocking for Phase 9/10; deferred to Phase 11 |
| 26 | Final deterministic regression | This pass, captured output | 643 passed, 0 failed, 7 skipped | **PASS** | Confirmed identical before and after live validation |
| 27 | Final live-enabled ChEMBL regression | This pass, captured output | 650 passed, 0 failed, 0 skipped (`RUN_LIVE_CHEMBL_TESTS=1`) | **PASS** | — |
| 28 | No unexpected provider traffic from deterministic tests | `logs/medagent.log` inspected after both final regression runs | Only the pre-existing 2026-09-25 historical entry present; 0 new hits | **PASS** | `grounding_eval/judge.py`'s call site never logs through this pipeline, disclosed as a known blind spot, not treated as proof of absence for THAT call site specifically - relevant only to DEV-003's suspicion, which remains explicitly unconfirmed |
| 29 | PHASE8-DEFECT-001 remains fixed | Final validation case VAL9-4 | Caveat mechanism fired correctly on a real, live `weakly_supported_fact` gap | **PASS** | — |
| 30 | PHASE8-DEFECT-002 remains fixed | Final validation - every case returned a non-None, correct `research_stop_reason` | All 5 cases returned an explicit, correct terminal `research_stop_reason` | **PASS** | — |
| 31 | Phase-10 protection | `git status`/`git diff` scope, no file under any Phase-10 path touched | Zero Phase-10 files read, constructed, or modified this entire Phase-9 effort | **PASS** | — |
| 32 | No commit/push | `git status --short` | Nothing staged or committed at any point in this pass | **PASS** | — |

## Overall Phase-9 freeze-readiness decision

**Phase 9 is genuinely ready to freeze**, with two explicitly non-blocking,
carried-forward items (CTL-016, CTL-019) that were already non-blocking
before this phase began and remain so - neither is a Phase-9 responsibility
to close, and neither blocks Phase 10. No genuine, unresolved product
defect was found at any point in this phase. Three process deviations were
found, documented, and remediated; none altered any formal conclusion.
