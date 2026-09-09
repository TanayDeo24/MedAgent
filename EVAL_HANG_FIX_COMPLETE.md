# Evaluation Hang: Root Cause, Salvage, and Fix

**Date:** 2026-09-09
**Scope:** The 60-case evaluation batch (started as part of Phase 2, see
`RESULTS.md`/`PHASE2_COMPLETE.md`) hung for 90+ minutes on case 31 and had to
be killed. This document covers: what caused it, what was salvaged from the
30 cases that had already completed, and the fix (hard per-call timeout with
fresh-connection retry, a per-case wall-clock cap, and incremental
persistence + resume) so this class of failure can't lose completed work
again. Touched `config/llm_config.py`, `evaluation/evaluator.py`,
`evaluation/metrics.py`, `evaluation/hallucination_judge.py` (diagnostics
only), a new `evaluation/reconstruct_from_logs.py` salvage tool, and
`.gitignore` (to allow committing `experiments/results/`). No RAG/FAISS,
GraphQL, frontend, or concurrency work.

## 1. Root cause (evidence-based, not a guess)

**`ChatNVIDIA`'s own `timeout=30` parameter does not bound an already-open
connection that stops sending data.**

Evidence, gathered while the process was still hung (not after the fact):

- The process (`agent.nodes`) logged `Agent run complete. Steps: 2, Thoughts:
  12` for case 31 at 15:46:13, meaning the agent's own 6-node pipeline
  finished successfully and the process moved on to the post-hoc
  hallucination-judge call. No further log line ever appeared.
- `lsof -p <pid>` repeatedly showed **one stable `ESTABLISHED` TCP connection**
  to NVIDIA's endpoint (via `awsglobalaccelerator.com`) that never closed,
  alongside 8 stale `CLOSE_WAIT` sockets from earlier, already-completed
  calls in the same process.
- CPU time for the process was frozen at exactly `0:33.61` across multiple
  checks spanning over an hour - zero CPU activity, not merely slow.
- The connection state, CPU time, and log file were all **byte-for-byte
  identical** checked 44 minutes apart and again 86 minutes apart. Nothing
  was progressing at any rate; this was not "very slow," it was stopped.
- `ChatNVIDIA(..., timeout=30)` was passed at construction. A real,
  enforced 30-second timeout would have raised an exception (which the
  hallucination judge's own `try/except` already catches and logs) long
  before the 44-90+ minute window observed. It did not fire.

**Conclusion:** the `timeout` parameter passed to `ChatNVIDIA` bounds request
setup / initial response but not a connection that opens successfully and
then stops delivering data mid-response - exactly the shape of a stalled
server-side stream or a network-level black hole. Since it isn't enforced
where it matters, nothing in the code was actually protecting against this
before this fix.

## 2. Salvage: what happened to the 30 (actually 31) completed cases

**Killed the process** with `SIGTERM` (confirmed sufficient - no `SIGKILL`
needed, process exited within seconds, which also confirms this was a
genuine I/O-level stall rather than something holding a lock or ignoring
signals).

**What was NOT lost:** `experiments/results/` was empty for this batch (only
written once, at the very end of a full run - the root design flaw items 4-6
below fix). But `logs/medagent.log` is structured JSON, flushed continuously
and independent of the killed process's own in-memory state. It contains
every node-level log line from every run today, so isolating this batch
required filtering by the exact process's timestamp window
(2026-09-09T16:52:00 to T19:47:00 UTC, from `ps`'s reported start time and
the log's last line).

Wrote `evaluation/reconstruct_from_logs.py` (a reusable tool now, not a
one-off script) to parse that window, split it into per-case blocks at each
`"Starting agent run: <query>"` boundary, and reconstruct each case's
`tools_used`, per-tool success/failure (including hallucinated tool names
like `pubchem`/`drugbank`/`fda_labels`), result counts, citations/compound
counts, iteration count, and errors - using the exact same
`AgentMetrics.tool_precision`/`redundancy_rate` logic the real evaluator
uses, not an approximation.

**Result: all 31 case blocks in the window were found and matched to their
`TEST_CASES` entries by exact query text** (cases 1-31; case 31's own agent
pipeline had, in fact, completed - see the log evidence above - only the
post-hoc hallucination judge call for it hung). **Zero cases were fully lost.**

**What is honestly NOT recoverable for any of the 31**, and is stored as
`null` rather than guessed:
- `confidence_score` - computed by `verification_node` but only ever pushed
  into `state["intermediate_thoughts"]` text, never passed to `logger.info()`.
- `task_completed` - `_check_task_success()` needs the actual `final_report`
  text (for `expected_drugs` substring matching) and `confidence_score`;
  neither exists in any log.
- `hallucination_judge` results - `judge_report_hallucinations()` only logs
  on failure, never logs its verdict on success.
- `tokens_used` / `llm_calls` - tracked in-memory only, never logged.
- `latency_seconds` for case 31 specifically - its "Completed in Xs" line
  (only ever printed by the CLI wrapper, not the structured logger) never
  printed, since the process was killed before reaching it.

Every reconstructed record carries `"reconstructed_from_logs": true` and a
`reconstruction_note` explaining exactly what's missing and why, so nothing
downstream (or in `RESULTS.md`) can mistake it for a fully-measured result.
Saved to `experiments/results/reconstructed_cases_1-31_from_hang.json`, and
seeded into `experiments/results/incremental_default.jsonl` (tagged
`"status": "completed_reconstructed"`) so the fixed evaluator's resume logic
picks up cleanly at case 32 instead of re-running 1-31 from scratch.

## 3. Fix: real hard timeout with fresh-connection retry

`config/llm_config.py`'s `_RateLimitedChatNVIDIA.invoke()` now wraps every
call in `_invoke_with_hard_timeout()`, which runs `llm.invoke()` on a
**daemon `threading.Thread`** and waits up to `LLM_CALL_TIMEOUT_SECONDS`
(**90s**) via `thread.join(timeout=...)`.

**Why a daemon `threading.Thread` and not `concurrent.futures.ThreadPoolExecutor`**
(which is what was originally suggested): `ThreadPoolExecutor` registers an
`atexit` handler that joins every worker thread from every pool ever created
before the interpreter can exit. If the underlying call truly never returns
(exactly what was observed here), that worker thread would still be stuck
when the process tries to exit, and `_python_exit()`'s join would hang
**forever at process-exit time** - silently reproducing this exact hang, just
moved to a different, harder-to-diagnose moment. A daemon thread carries no
such join-at-exit obligation: Python cannot forcibly kill a thread, but a
daemon thread is simply abandoned and reclaimed by the OS when the process
ends, with no interpreter-level wait. **Verified live**: a script that
triggers a real timeout, with the "hung" call still sleeping 300s in the
background, exits cleanly with code 0 in 1.4 seconds.

On timeout: the stale `ChatNVIDIA` client is **discarded and a fresh one
constructed** (`self._llm = ChatNVIDIA(**self._construct_kwargs)`) before
retrying - the 8 stale `CLOSE_WAIT` sockets observed during the incident
suggest connection/session reuse may itself have been part of what went
stale, not just one unlucky request. Up to `LLM_CALL_MAX_ATTEMPTS` (**3**:
1 initial + 2 retries) are made, with exponential backoff
(`utils/retry_handler.py`'s existing `calculate_backoff()`, which generalizes
cleanly here since it's pure math, not tied to `requests`) between attempts.
If all attempts time out, a new `LLMCallTimeoutError` is raised - the calling
node's existing `try/except` (already present in every one of the 6 nodes)
handles it exactly like any other LLM error, no new failure path needed
there.

**Why 90 seconds**: this same incident's own logs show legitimate,
successfully-completed calls (including large synthesis/report/hallucination
-judge prompts) taking 15-55 seconds under normal conditions. 90s leaves
comfortable headroom above that without waiting anywhere near as long as the
observed 44+ minute stall before concluding something is actually wrong.

## 4. Fix: per-case wall-clock cap

`evaluation/evaluator.py` now wraps `self.agent.run(query)` itself (not just
each LLM call) in the same daemon-thread timeout pattern, capped at
`CASE_WALL_CLOCK_TIMEOUT_SECONDS`.

**Deliberately NOT the 3-5 minutes originally suggested for this constant.**
This same incident's own reconstructed data shows plenty of legitimate,
successfully-completed cases taking longer than that under real conditions
(ChEMBL/NVIDIA transient errors triggering the existing retry/backoff logic
in the tools and, now, in the LLM layer too): case 2 took 820s (13.7 min),
case 4 took 663s, case 24 took 334s. A 3-5 minute cap would have
misclassified all of those as timeouts. Set to **1200s (20 minutes)**
instead - comfortably above the highest observed legitimate latency, while
still catching the genuinely pathological case where multiple calls in the
same test case each exhaust their own 3-attempt timeout budget (worst case
per call: 3 x 90s + backoff ≈ 5 minutes; a case with several such calls
stacking up is the scenario this cap exists for).

A case that exceeds this cap gets `"status": "timeout"` in its result (not
silently dropped, not crashing the batch) and the loop moves on immediately.

## 5. Fix: incremental persistence (replacing batch-at-the-end)

Confirmed by reading `evaluation/evaluator.py` before this fix: results were
only ever written to disk once, via `_save_report()`, called at the very end
of `run_evaluation()` after every test case had been processed - exactly why
killing the hung process risked losing all 30 (in fact 31) already-completed
cases' data.

Now, `run_evaluation()` calls `_append_incremental_result()` immediately
after every single case (success, failure, or timeout), writing one JSON
line to `experiments/results/incremental_<run_id>.jsonl`. A slimmed copy of
`state` is stored (confidence_score/current_step/errors only, same reduction
`_save_report()` already applied at the end) so the file doesn't balloon
across a 60+ case run; the full state is only ever needed in-memory, by this
same process's own aggregate metrics.

## 6. Fix: resume support

`run_evaluation(test_cases=None, verbose=True, run_id="default")` now loads
`incremental_<run_id>.jsonl` on startup via `_load_incremental_results()`,
builds the set of already-completed `test_case_id`s, and starts from the
first test case not in that set - printing `RESUMING run_id='default': N
cases already completed, M remaining`. Calling it again with a new `run_id`
starts a genuinely fresh batch instead.

**A real correctness gap this exposed and had to be fixed too:**
`AgentMetrics.calculate_all_metrics()` recomputes `tool_precision`,
`redundancy_rate`, and `citation_coverage` from each result's full
`state["tool_call_history"]` / `state["citations"]` / `state["tool_results"]`.
That's fine for results computed fresh in the same process, but silently
wrong for results loaded back from the incremental file (slimmed state, no
`tool_call_history`) or from the log-reconstructed cases (no real state at
all) - it would have quietly returned near-0.0 values for every resumed or
reconstructed case, corrupting the aggregate. Fixed by having
`_generate_evaluation_report()` average each result's own **already-computed**
`tool_precision`/`redundancy_rate`/`citation_coverage` fields instead of
re-deriving them from `state` - correct for every result regardless of when
or how it was computed. Also fixed `AgentMetrics.avg_confidence()` and
`avg_latency()` to treat an explicit `None` value (not just a missing key) as
0, since reconstructed/timeout results store those as real `None`s for
fields that were genuinely never measured.

## 7. Verification

- **Timeout fix, live-tested with a real simulated hang**: patched
  `ChatNVIDIA` with a fake client that sleeps 300s on every `invoke()` call
  (temporarily shrinking `LLM_CALL_TIMEOUT_SECONDS`/`LLM_CALL_MAX_ATTEMPTS`
  for a fast test). Confirmed: caught after 2 attempts in 4.8s, a fresh
  client instance was constructed for the retry (verified via a call
  counter), and `LLMCallTimeoutError` was raised cleanly - never hung.
  Separately confirmed process exit is clean (0.33s, exit code 0) even with
  an abandoned "still sleeping" daemon thread left behind, validating the
  daemon-thread-over-ThreadPoolExecutor choice.
- **Salvage confirmed**: `evaluation/reconstruct_from_logs.py` re-run
  produces identical output to the original one-off version; all 31 cases
  matched to real `TEST_CASES` entries with plausible, spot-checked data
  (e.g. case 2's reconstructed 820.0s latency verified directly against the
  raw stdout capture's `"Completed in 820.0s"` line).
  `experiments/results/reconstructed_cases_1-31_from_hang.json` and the
  seeded `incremental_default.jsonl` are both present and valid.
- **Resume + incremental persistence, live-tested against the real batch**:
  restarted `run_evaluation(run_id="default")` against all 60 `TEST_CASES`.
  Console output confirmed: `RESUMING run_id='default': 31 cases already
  completed, 29 remaining`, and it started at `[32/60]` with case 32's real
  query text - not case 1. Watched `incremental_default.jsonl` grow from 31
  to 35 lines as cases 32-35 completed in real time, each with correct,
  distinct `tool_precision`/`llm_calls`/`tokens_used` values written
  immediately (confirmed by inspecting the newly-appended lines directly,
  not just trusting the count). This batch continues running in the
  background past this document's writing - see `RESULTS.md` for whatever
  scale it reaches by the time that document is finalized.
- `pytest tests/`: **40/42 pass**, same two pre-existing rate-limit-test
  failures as every prior pass, no new failures.

## Found but out of scope for this pass

- **The hallucination judge is still failing on real (not synthetic) large
  reports**, even after the earlier `max_tokens=8192` fix, with the same
  `Expecting value: line 1 column 1 (char 0)` empty-content symptom -
  observed on cases 32, 33, and 34 in the resumed batch (all
  `"judge_failed": true`, `0/0` claims). A synthetic large-prompt
  reproduction with similar token counts did NOT reproduce it, so the exact
  trigger for real reports isn't yet identified. Added a diagnostic log line
  (`evaluation/hallucination_judge.py`) that captures `usage`/`finish_reason`
  the next time this happens, but did not chase the root cause further here
  since it's a separate reliability concern from the hang this document
  covers, and doesn't block resume/incremental persistence (both confirmed
  working above independent of the judge's own success rate). This means
  `RESULTS.md`'s hallucination-rate numbers may be based on a smaller
  successfully-judged sample than the full case count - `RESULTS.md` reports
  `hallucination_judge_failures`/`hallucination_judge_missing` explicitly so
  this is visible, not hidden.
- **The `.gitignore` fix for `experiments/results/`** was actually a
  stranded piece of the original Phase 2 plan (written but never committed
  before the hang), applied here since it was needed to commit this fix's
  own salvaged data.
- `evaluation/hallucination_judge.py` itself was also a stranded, uncommitted
  Phase 2 deliverable (written before the hang, never committed) - committed
  here as its own commit since the resume/incremental work depends on it.
