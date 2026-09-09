# Phase 2 Evaluation Results

**Date:** 2026-09-09
**Run:** 60/60 test cases (`experiments/results/incremental_default.jsonl`, aggregate
report `experiments/results/evaluation_20260909_193811.json`)

This replaces the fabricated **"96% task completion, 98% tool-call reliability, 5K+
autonomous workflows"** resume claims with the actual measured numbers from a real,
committed evaluation run. Several of these numbers are meaningfully worse than the
fabricated figures — that is reported as-is, not softened.

## 1. Test set

**60 test cases** (`evaluation/test_cases.py`, up from an original 10), split:

| Difficulty | Count |
|---|---|
| Easy | 18 |
| Medium | 24 |
| Hard | 12 |
| Ambiguous | 6 |

Covers each tool individually (pure-PubMed, pure-ClinicalTrials, pure-ChEMBL cases),
two- and three-tool combinations across oncology/cardiology/autoimmune/infectious
disease/neurology/rare disease, and several deliberately broad or causally complex
queries intended to plausibly trigger the self-reflection loop.

## 2. How this run was actually produced (read before trusting the numbers below)

This run did not go smoothly, and that matters for interpreting the results honestly:

- **The first attempt at this batch hung for 90+ minutes on case 31** and had to be
  killed (`ChatNVIDIA`'s own `timeout=30` did not bound a connection that opened
  successfully and then stopped delivering data — full incident writeup and root
  cause evidence in `EVAL_HANG_FIX_COMPLETE.md`).
- The 31 cases that had already completed before the hang were **salvaged from
  structured logs** (`logs/medagent.log`), not re-run. This recovers real tool usage,
  result counts, citations, and derived metrics like `tool_precision` faithfully, but
  **cannot recover `confidence_score`, `task_completed`, hallucination-judge verdicts,
  token counts, or LLM call counts** for those 31 — none of those were ever captured
  by the structured logger for the killed process. Those fields are stored as `null`
  for these cases, not guessed, and they're tagged `"status":
  "completed_reconstructed"` everywhere so they're never silently confused with a
  fully-measured result.
- After fixing the hang (hard per-call timeout with fresh-client retry, a per-case
  wall-clock cap, incremental persistence, and resume support — see
  `EVAL_HANG_FIX_COMPLETE.md`), the batch was **resumed from case 32** and completed
  the remaining **29 cases fresh**, with full data including `task_completed`,
  `confidence_score`, tokens, and LLM call counts.
- **Consequence for coverage**: cases 1-31 happen to cover all 18 "easy" cases and 10
  of the 24 "medium" cases. The 29 freshly-run cases are 14 medium + all 10 hard + all
  5 ambiguous. **This run has zero measured `task_completed` data for the "easy"
  difficulty tier** — every easy case is in the reconstructed set. This is a real gap
  in this run's coverage, not a claim that easy queries perform some particular way.

Because of this, metrics below are reported two ways where it matters:
**"Fresh" (n=29)** = the freshly-run cases with complete data, and **"All 60"** = fresh
+ reconstructed combined, where the reconstructed cases' unmeasurable fields
(`task_completed=None`, `confidence=0`, etc.) are conservatively counted as failures/
zeros rather than excluded — which drags the "All 60" numbers down relative to "Fresh."
Report the "Fresh" numbers as the more meaningful ones for judging real current
performance; report "All 60" for an honest, unpadded view of what this actual run
as a whole can support.

## 3. Methodology notes

**Rate limiting** (`config/llm_config.py`): every LLM call is throttled to **35 RPM**
(NVIDIA NIM's free tier is 40 RPM; 35 leaves headroom for retries), applied globally
via a wrapper around `ChatNVIDIA.invoke()`.

**Hard timeout + fresh-client retry**: every LLM call is also bounded by a **90-second
hard timeout**, enforced independently of `ChatNVIDIA`'s own (evidently unreliable)
`timeout` parameter, via a daemon thread. Up to 3 attempts, each with a freshly
constructed client. **This fired live 21 times during this run's freshly-executed 29
cases** — 21 calls that would previously have had no enforced ceiling at all, each
successfully recovered instead of stalling. See `EVAL_HANG_FIX_COMPLETE.md` for full
detail and why a daemon thread was used instead of `ThreadPoolExecutor`.

**Tool-hallucination counting**: Nemotron occasionally invents a tool name that
doesn't exist (e.g. `pubchem`, `drugbank`, `fda_labels`, `kegg`, `europe_pmc`,
`cochrane`, `clinicaltrials.gov`, `literature`, `fda`). `PLANNING_PROMPT` was tightened
to explicitly enumerate the only 3 valid tool names, and — regardless of whether that
fully eliminates it — every hallucinated tool name is now recorded in
`tool_call_history` as a failed attempt, so `tool_precision` counts it as a miss
instead of the attempt silently vanishing. **This still happens often**: across all 60
cases, 9 distinct hallucinated tool names were attempted a combined 12+ times (see
`tool_usage` breakdown below) — the prompt tightening reduced but did not eliminate
this behavior.

**Hallucination-rate methodology** (`evaluation/hallucination_judge.py`): a *separate*
LLM call (its own prompt, temperature=0.0, no shared context with the report-writing
call) extracts factual claims from a completed run's report and checks each against
that same run's actual retrieved `tool_results`, counting unsupported claims as
hallucinated. **This is a real, defensible approach, but it is explicitly NOT the
rigor of human verification**: it measures whether the report stayed grounded in this
run's own retrieved data, not whether that data (or the report) is correct against
reality, and the judge is the same underlying model family grading a different task,
not an independent judge. See that module's docstring for the full list of limits.
**In this run, the judge itself failed on 23 of the 29 freshly-run cases** (an
unresolved, separate reliability issue documented in `EVAL_HANG_FIX_COMPLETE.md` —
even after raising `max_tokens` to 8192, some real reports still exhaust Nemotron's
internal reasoning budget before emitting the final JSON verdict). **The
hallucination-rate number below is therefore based on only 6 successfully-judged
cases out of 60** — a genuinely small sample, reported as such rather than presented
as if it covered the whole run.

## 4. Real numbers

| Metric | Fresh (n=29) | All 60 | What it means |
|---|---|---|---|
| **Task success rate** | **37.9%** (11/29) | **18.3%** (11/60) | % of runs that produced a report with confidence ≥ 0.5, met the minimum result count, and mentioned ≥50% of expected drugs. All 60's lower number reflects 31 reconstructed cases whose success genuinely couldn't be determined (counted as failures here, not excluded). |
| **Tool precision** | **85.3%** | **76.8%** | Of all tools *attempted* (including hallucinated ones), the fraction that were actually relevant to the query. This is the closest existing metric to the fabricated "98% tool-call reliability" claim — it measures *tool selection* correctness, not raw API call success rate (this evaluation doesn't separately track that as its own metric). |
| **Redundancy rate** | 12.9% | 18.2% | % of tool calls that repeated an identical (tool, query) pair the agent had already made. Lower is better. |
| **Self-correction rate** | 93.1% | 91.7% | % of runs where the self-reflection loop actually looped (>1 iteration). Healthy target band is 20-40% per the metric's own design intent — this run is far above that, meaning the agent almost always felt it needed more research, which given the 37.9% success rate suggests looping isn't reliably converging on success. |
| **Citation coverage** | 77.1% | 68.4% | Ratio of citation entries to total retrieved results. |
| **Avg. confidence** | 0.465 | 0.225 | Agent's own self-assessed confidence (0-1) at verification time. |
| **Avg. latency** | 177.5s | 209.4s | Wall-clock time per test case (agent run + hallucination judge). |
| **Hallucination rate** | **42.9%** (27/63 claims, from 6 successfully-judged cases) | same | See methodology caveat above — small sample, not comparable to a claim covering the full 60. |

**Failure characterization (fresh cases only, n=18 failed of 29)**: 11 of 18 failures
had no error at all — the agent completed cleanly but self-assessed confidence below
the 0.5 success threshold (dominant failure mode). The remaining 7 failed due to real
transient infrastructure issues: NVIDIA NIM `503 Service temporarily overloaded` (3
cases), a genuine `429 Too Many Requests` from NVIDIA (1 case, despite the 35 RPM
limiter — NVIDIA's actual enforcement can be burstier than a steady-state average),
a `502 Bad Gateway` from ClinicalTrials.gov (1 case), an LLM call that timed out on
all 3 attempts (1 case), and a synthesis-node JSON parse failure (1 case). **None of
these caused a lost test case** — every one was caught by existing per-node error
handling and the run continued; they just count as task failures, not batch failures.

## 5. Real usage totals — replacing "5K+ autonomous workflows"

- **Workflows actually run**: **60** end-to-end evaluation test cases (29 executed
  fresh in this session; 31 salvaged from an earlier interrupted run of the same
  batch — see §2). This is the honest scale actually tested. There is no basis for
  "5K+" anywhere in this codebase's history — no prior run logs, no results directory
  existed before this Phase 2 work.
- **Total LLM calls**: **356** (across the 29 freshly-run cases; the 31 reconstructed
  cases' call counts were never captured, so the true combined total is somewhat
  higher than 356, but honestly unknown for those 31).
- **Total tokens used**: **1,583,374** combined (1,540,990 agent-pipeline tokens +
  42,384 hallucination-judge tokens), again only from the 29 freshly-run cases.

## 6. Verification

- `pytest tests/`: **40/42 pass** — same 2 pre-existing rate-limit-test failures
  documented since `PHASE1_COMPLETE.md`, no new failures.
- `experiments/results/incremental_default.jsonl` contains all 60 test case IDs
  (1-60), no gaps, no `status: "timeout"` entries — no case was dropped or lost.
- 3 genuine NVIDIA NIM `429 Too Many Requests` responses occurred during the run
  (one caused a task failure, see §4); none corrupted or dropped a test case's data -
  each was caught by the same per-node error handling that already exists for other
  transient provider errors (matching the `503` handling documented since Phase 1).

## What this honestly does and doesn't show

This run demonstrates a working, instrumented, real evaluation pipeline producing
real numbers from real API calls — not a simulation. It does **not** show a
production-ready 96%-success agent: **task success is 37.9% on the cases with
complete data**, driven mostly by the agent's own confidence self-assessment landing
below 0.5 rather than outright crashes. Tool selection (85.3% precision) is
reasonably strong. Self-correction almost always triggers but doesn't reliably lead
to success. The hallucination-rate figure is not trustworthy at its current sample
size (6 judged cases) and needs the judge's reliability issue fixed before it means
much. None of this is disguised — it's the actual measured state of the system as of
this run.
