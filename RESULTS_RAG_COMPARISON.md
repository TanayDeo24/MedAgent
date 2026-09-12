# Baseline vs. RAG Comparison — Phase 3 Final Deliverable

**Date:** 2026-09-11/12
**Purpose:** Replace the fabricated resume claim **"improving evidence-grounded
response accuracy by 35%"** with a real, measured number from a real, controlled
comparison run.

## 1. Methodology (decided before running, not adjusted after seeing results)

**Parameters:** `max_iterations=2, temperature=0.3` — the exact values used in
Phase 2's 60-case batch (`experiments/results/evaluation_20260909_193811.json`'s
`agent_config`). Any other value would make this an invalid comparison against
project convention.

**Test cases:** the first 30 test cases by `id` (1–30) from
`evaluation/test_cases.py`, in file order — deterministic and reproducible.
Difficulty spread: 18 easy, 9 medium, 2 hard, 1 ambiguous. Both arms ran the
**exact same 30 cases, same order**.

**Concurrency:** `concurrency=4` for both arms (the worker count validated for
thread-safety and real wall-clock improvement in `PHASE3_CONCURRENCY_VALIDATION.md`
— reused rather than re-validated, since re-validating concurrency wasn't in
scope for this pass).

**Arms:**
- **Arm A (baseline):** `MedAgent(max_iterations=2, temperature=0.3, use_rag=False)`
- **Arm B (RAG):** `MedAgent(max_iterations=2, temperature=0.3, use_rag=True)`

The `use_rag` toggle (`agent/graph.py`) skips `synthesis_node`'s RAG retrieval
call entirely when `False` — everything else (tools, prompts minus the RAG
section, non-RAG citations) is identical between arms.

**Metric definitions, stated up front:**
- **Primary metric: hallucination rate** (LLM-judge, lower = more grounded) —
  the metric that most directly measures unsupported claims, which is what
  "evidence-grounded accuracy" actually means.
- **Secondary metric: citation coverage**, broken out by source (live tool
  calls vs. "PubMed RAG") — more real citations, more visibly RAG-attributable,
  supports the primary metric's story but does not override it if they disagree.
- Task success rate, confidence, latency, and token/call counts are reported
  for completeness but are not the basis for the "grounding" claim.

This framing was fixed before either arm ran and is not adjusted below based on
what the numbers turned out to show.

## 2. Two real bugs found and fixed during this run (read before trusting the numbers)

This comparison did not go cleanly, and both problems are documented here in
full rather than quietly patched over.

**Bug 1 — a real crash, not a flaky retry.** Arm B (RAG-enabled, concurrency=4)
crashed the whole process within its first minute:
`failed assertion _status < MTLCommandBufferStatusCommitted ... in
-[IOGPUMetalCommandBuffer setCurrentCommandEncoder:]`. Two concurrent worker
threads both called the RAG retriever's embedding model
(`SentenceTransformer.encode()`, a Metal/MPS GPU forward pass on this machine)
at the same moment — Apple's Metal backend isn't safe for concurrent
command-buffer submission without external synchronization. Fixed with a
`threading.Lock()` around the `retrieve()` call site in `agent/nodes.py`
(not inside `retrieval/`, which stays untouched) — serializes RAG calls
across concurrent cases. Verified with a 3x repeated 4-thread concurrent
stress test against the exact crashing code path before resuming the run.
The crashed run had already persisted 3/30 cases cleanly; the evaluator's
resume-by-run-id picked up from case 4 rather than losing that work.

**Bug 2 — a real measurement artifact, not a real RAG regression.** On the
first full run of both arms, the raw hallucination rates were: baseline
20.0% (42/210 claims, 12/30 judged), RAG **73.6%** (240/326 claims, 10/30
judged) — RAG looked dramatically *worse*. Investigation found the cause:
`judge_report_hallucinations()` only ever received `state["tool_results"]`,
never `state["retrieved_context"]`. Every claim in a RAG-enabled report that
was correctly grounded in a retrieved RAG passage (not in `tool_results`) was
being counted as hallucinated purely because the judge was never shown the
data that supported it — not because those reports were actually less
accurate. Fixed by adding `retrieved_context` to the judge's prompt as a
second, equally-valid source of truth (`evaluation/hallucination_judge.py`),
and re-judging both arms' already-completed cases against the fix — using the
full `final_report`/`tool_results`/`retrieved_context` `evaluator.py` now
persists per case, so this did **not** require re-running either arm's agent
pipeline, only re-scoring already-captured data.

Both fixes are committed separately from this results commit, with full
detail in their own commit messages.

## 3. Per-arm results (corrected, post-fix)

| Metric | Baseline (n=30) | RAG (n=30) | Note |
|---|---|---|---|
| **Hallucination rate (primary)** | **18.4%** (35/190 claims, **n=10 judged**) | **5.7%** (3/53 claims, **n=2 judged**) | See §4 — the RAG figure is not statistically meaningful at n=2 |
| Task success rate | 36.7% (11/30) | 63.3% (19/30) | Secondary/contextual, not the grounding metric |
| Citation coverage (avg) | 84.7% | 90.2% | Secondary metric |
| — of which "PubMed RAG" | 0 citations | 300 citations (of 1,057 total) | Confirms RAG citations only appear when `use_rag=True`, as designed |
| — ChEMBL / ClinicalTrials.gov / PubMed (live) | 380 / 223 / 151 | 380 / 191 / 186 | Live-tool citation volume is comparable across arms |
| Avg confidence | 0.379 | 0.571 | |
| Avg latency | 198.2s | 198.1s | Essentially identical — see §5 |
| Total tokens (combined) | 1,328,725 | 1,789,879 | RAG arm used ~35% more tokens (larger prompts from retrieved passages + more successful reports to generate) |
| Total LLM calls | 403 | 399 | Comparable — RAG retrieval itself is a local embedding call, not an LLM call, so it doesn't add to this count |
| Wall-clock (this batch) | ~51 min | ~51 min (across 2 runs, due to the mid-run crash/resume) | |

## 4. The real delta, and why it can't be reported as a clean win

**Raw numbers say hallucination rate dropped from 18.4% to 5.7%** — a
**~69% relative reduction** if taken at face value. This is **not** reported
as the headline finding, because it isn't a defensible one: the RAG arm's
judge succeeded on only **2 of 30 cases**. A rate computed from 2 data points
is not a real sample — it is barely more informative than reporting one or two
anecdotes. The judge's own reliability got *worse* on the RAG arm specifically
(2/30 vs. baseline's 10/30, both far off this project's earlier ~39% overall
estimate), almost certainly because `retrieved_context` adds up to another
15,000 characters to the judge's own prompt (see §2's fix) — a longer prompt
plausibly extends Nemotron's internal reasoning chain further past the 90s
timeout, the same failure mode documented at length in
`evaluation/hallucination_judge.py` and `RESULTS.md`.

**The honest conclusion**: this run does not produce a defensible
hallucination-rate delta between baseline and RAG. The baseline arm's 18.4%
(n=10) is itself a small sample; the RAG arm's 5.7% (n=2) is too small to
support any percentage claim at all, whether "35%," "69%," or otherwise. Both
numbers point in the same direction (RAG associated with a lower rate), and
that directional signal is worth stating — but it is a *hint*, not a
measurement precise enough to replace one fabricated number with another
overconfident one.

**What this run does support, defensibly:**
- RAG citations only appear when `use_rag=True` (0 vs. 300) — the toggle
  works exactly as designed and doesn't leak into the baseline arm.
- Task success rate improved substantially with RAG (63.3% vs. 36.7%,
  n=30 each, not judge-limited) — this is the secondary/contextual metric,
  not the primary grounding claim, but it is a real, well-sampled result
  worth reporting alongside the primary metric's inconclusive one.
- RAG did not meaningfully change agent latency (198.1s vs. 198.2s) — local
  embedding + FAISS retrieval is fast enough (single-digit seconds, see
  `PHASE3_WIRING_COMPLETE.md`) relative to the LLM calls surrounding it that
  it doesn't show up in the aggregate latency figure at this sample size.
  RAG did increase total token usage by ~35% (larger prompts from retrieved
  passages, plus more reports actually being generated to completion).

## 5. What would be needed for a real answer

The judge's reliability (now confirmed to degrade further under RAG's larger
prompts) is the actual bottleneck, not this comparison's design. A trustworthy
hallucination-rate delta would need either: a judge that reliably succeeds on
enough of both arms' cases to support real percentages (the three attempts at
this so far — `max_tokens` increases, a lighter model, and this pass's
context fix — have each fixed a real problem without reaching that bar), or a
substantially larger case count per arm to compensate for the judge's ~10-40%
success rate with brute sample size, which was outside this pass's one-day
time budget.

## 6. Honesty summary

- Hallucination rate: **directionally lower with RAG, but not measurable with
  confidence at this judge success rate** (n=10 baseline, n=2 RAG) — reported
  as such, not rounded up to a clean percentage.
- Task success rate: **meaningfully higher with RAG** (63.3% vs. 36.7%,
  full n=30 both arms) — a real, secondary finding.
- Citation coverage: **higher with RAG** (90.2% vs. 84.7%), with the increase
  visibly and entirely attributable to "PubMed RAG" sources (300 citations,
  zero in baseline) — confirms the toggle and citation labeling both work.
- Latency: **no meaningful difference** (198.1s vs. 198.2s).
- Tokens: **~35% higher with RAG** (1.79M vs. 1.33M combined) — a real cost,
  reported plainly.
- No metric got worse with RAG in this run. If one had, it would be reported
  here the same way.
