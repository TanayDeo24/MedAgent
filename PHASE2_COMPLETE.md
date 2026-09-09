# Phase 2 Complete: Real Evaluation Replacing Fabricated Numbers

**Date:** 2026-09-09
**Scope:** Build a real evaluation of the MedAgent pipeline and replace the
fabricated 96% task-completion / 98% tool-call-reliability / "5K+ workflows"
resume numbers with actual measured ones. No RAG/FAISS, GraphQL, frontend, or
concurrency work (concurrency explicitly deferred to Phase 3).

## What was built

**1. Rate limiting** (`config/llm_config.py`, `utils/rate_limiter.py`) — every
LLM call throttled to 35 RPM (NVIDIA NIM's free tier is 40), applied globally
via a wrapper around `ChatNVIDIA.invoke()`. Fixed a latent bug in the existing
token-bucket rate limiter: a sub-1-per-second rate could never accumulate
enough tokens to satisfy a single call, causing an infinite wait — fixed by
adding an explicit `capacity` parameter.

**2. Token usage tracking** (`agent/nodes.py`) — `AgentState.total_tokens_used`
was declared but never populated by any node. Added `_accumulate_tokens()`,
called after every one of the 6 nodes' LLM calls (including per-tool calls in
`tool_execution_node`'s loop), using ChatNVIDIA's standard `usage_metadata`.

**3. Tool-hallucination handling, both halves** (`agent/prompts.py`,
`agent/nodes.py`) — tightened `PLANNING_PROMPT` to explicitly enumerate the
only 3 valid tool names, *and* made hallucinated tool names show up as a real
`tool_precision` miss (previously only a warning log line, invisible to
metrics) regardless of whether the prompt fix fully works. It doesn't fully
eliminate the behavior — see `RESULTS.md` for how often it still occurs.

**4. Expanded test set** (`evaluation/test_cases.py`) — 10 → 60 cases (18
easy, 24 medium, 12 hard, 6 ambiguous), covering each tool individually,
multi-tool combinations, and queries designed to plausibly trigger the
self-reflection loop.

**5. Hallucination-rate methodology** (`evaluation/hallucination_judge.py`) —
an LLM-judge approach (separate call, no shared context with the agent's own
report-writing), since manual human labeling of 60+ cases wasn't practical.
Documented honestly as measuring internal grounding, not verified
real-world correctness, and explicitly not the rigor of human review.

**6. Ran the real evaluation** — and hit a real incident along the way: the
first attempt hung 90+ minutes on case 31 (`ChatNVIDIA`'s own `timeout=30`
did not bound a connection that opened successfully and then stopped
delivering data). This became its own fix pass
(`EVAL_HANG_FIX_COMPLETE.md`): a real hard timeout with fresh-client retry
(daemon-thread based, deliberately not `ThreadPoolExecutor` — that would have
reproduced the hang at process-exit time via its atexit thread-join), a
20-minute per-case wall-clock cap, incremental persistence (previously
results were only written once, at the very end of a full run — exactly why
the hang risked losing all 31 already-completed cases), and resume support.
31 completed cases were salvaged from structured logs rather than re-run
(zero cases lost), and the batch resumed cleanly from case 32 through
completion.

**7. Computed and reported real numbers** — `RESULTS.md`.

## The real numbers (see RESULTS.md for full detail and caveats)

| Metric | Value | vs. fabricated claim |
|---|---|---|
| Task success rate | 37.9% (fresh, n=29) / 18.3% (all 60) | vs. fabricated 96% |
| Tool precision (closest to "tool-call reliability") | 85.3% (fresh) / 76.8% (all 60) | vs. fabricated 98% |
| Workflows actually run | 60 (29 fresh + 31 salvaged) | vs. fabricated "5K+" |
| Total LLM calls (fresh cases) | 356 | previously untracked |
| Total tokens used (fresh cases) | 1,583,374 | previously untracked |
| Hallucination rate | 42.9%, but from only 6 successfully-judged cases | new metric, no prior claim |

These are meaningfully worse than the resume figures in several places, and
`RESULTS.md` reports that plainly rather than softening it. The dominant
real failure mode (11 of 18 failed fresh cases) is the agent completing
cleanly but self-assessing confidence below the 0.5 success threshold — not
crashes or infrastructure failures.

## Verification

- `pytest tests/`: 40/42 pass throughout every commit in this phase, same 2
  pre-existing rate-limit-test failures, no new failures introduced.
- `experiments/results/incremental_default.jsonl`: all 60 test case IDs
  present, no gaps, zero `status: "timeout"` entries.
- The hard-timeout fix was verified twice: once with a deliberately simulated
  300-second hang (confirmed caught, retried with a fresh client, and the
  process exited cleanly despite an abandoned daemon thread still "hanging"
  in the background), and once live in production — it fired 21 times during
  the real resumed batch, each time recovering instead of stalling.

## Found along the way, out of scope for this phase

- **The hallucination judge still fails on most real reports** even after
  raising `max_tokens` to 8192 (23 of 29 freshly-judged cases failed with an
  empty-response symptom). A synthetic large-prompt reproduction did not
  reproduce it, so the exact trigger for real reports isn't identified.
  Diagnostic logging was added; root cause not chased further here. This is
  the single most important open item for Phase 3 if hallucination-rate
  numbers are to be trusted at full sample size.
- **Zero "easy"-difficulty coverage with complete data in this run** — all 18
  easy test cases happened to fall in the salvaged (reconstructed-from-log)
  portion of the batch, which lacks `task_completed`/`confidence_score`. A
  future run isn't affected by this (it was a one-time consequence of exactly
  where the hang occurred), but it means this run's numbers say nothing
  concrete about easy-query performance specifically.
- **A genuine NVIDIA NIM 429 (Too Many Requests) occurred 3 times** despite
  the 35 RPM limiter — NVIDIA's real enforcement can apparently be burstier
  than a smoothed steady-state average suggests. Didn't cause any lost data
  (existing per-node error handling caught it, same as the already-documented
  503 handling), but worth knowing if RPM is ever pushed closer to the 40
  limit.
- **The tool-call-reliability concept isn't separately tracked** — this
  evaluation's `tool_precision` metric measures whether the *right* tools
  were selected, not the raw success/failure rate of individual API calls
  once selected. A dedicated "tool call success rate" metric (successful
  calls / attempted calls, independent of relevance) would be a reasonable
  Phase 3 addition if that's the more literal claim to substantiate.
- **No caching/deduplication of ChEMBL `get_drug_info()` calls across
  iterations** (flagged since `CHEMBL_BACKFILL_COMPLETE.md`) — still
  unaddressed, and now more visible given real per-case LLM-call counts are
  tracked (up to 356 calls across 29 cases).
- Concurrency (running test cases in parallel) was explicitly out of scope
  for this phase per the task's own instructions - the rate limiter's single
  global bucket would need no changes to support it (concurrent callers
  already correctly share one token bucket), but the evaluator's sequential
  loop, wall-clock cap, and incremental-write logic would need review before
  parallelizing safely.
