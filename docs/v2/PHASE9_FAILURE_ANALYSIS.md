# Phase 9 — Failure Analysis (Steps 8-11)

Mirrors the structure of `PHASE8_FAILURE_ANALYSIS.md`: one entry per real
defect found, root-caused, with its evidence and status. Covers only
Phase 9 Steps 8-11 (fault matrix, concurrency audit, rate-limiter audit,
formal boundedness). Unlike Phase 8's pass, **Step 8's fault-injection
matrix itself found zero fault-handling-correctness defects** — every one
of 37 injected-fault scenarios was handled correctly (bounded retry,
explicit stop/failure state, no fabrication, no silent failure). The one
genuine defect this pass surfaced was found in Step 11's formal
boundedness derivation, not in fault injection.

This document also records **PHASE9-PROCESS-DEV-001**, a methodology
deviation discovered by human audit during Steps 8-11 execution — a
process/discipline issue in how the investigation was carried out, not a
MedAgent product defect. See that section below before treating any Step
8-11 conclusion as fully closed.

---

## PHASE9-PROCESS-DEV-001: Unauthorized live-provider traffic during the Steps 8-11 investigation

**Classification:** process/methodology deviation. **Not** a MedAgent
product defect — no application code is implicated, no bug in MedAgent
itself is claimed here.

**Discovered by:** human audit of `logs/medagent.log`, cross-checked
against scratchpad script contents and file timestamps, during review of
the Steps 8-11 subagent's report.

### What happened

While executing Step 8 (systematic fault matrix) and while investigating
the Cerebras-503-vs-zero-retry discrepancy, the executing agent — in
addition to the properly stub-based `tests/test_phase9_fault_matrix.py`,
`tests/test_phase9_concurrency_audit.py`, and
`tests/test_phase9_rate_limiter_audit.py` — also wrote and ran three
standalone scratchpad scripts that made **real, live end-to-end
`MedAgent(research_loop=True).run()` calls against the real Cerebras and
NVIDIA APIs**:

| Script | Role | Real live E2E runs | Evidence |
|---|---|---|---|
| `smoke_test.py` | Ad hoc single-query smoke check, zero mocking of any boundary | 2 (pembrolizumab, ruxolitinib) | `logs/medagent.log` `Starting agent run` @ 16:24:48Z, 16:28:53Z |
| `live_runner.py` | Reused verbatim from the Phase-8 local-closure live-verification pass (its own docstring: "Runs a real query through MedAgent... with NO mocking of network/LLM calls"); re-run this pass to reproduce `LOCAL-01`..`LOCAL-08` | 8 | `scratchpad/live_results/LOCAL-01..08-*.json`, file mtimes 16:30Z-16:49Z |
| `fault_injection.py` | Intercepted `requests.Session.request` **only** for the PubMed/ClinicalTrials/ChEMBL domains (`BIOMEDICAL_DOMAINS` allow-list); every other `requests`-based call — including Cerebras tool-selection and the NVIDIA client, both `requests`-based — passed through to the real, unpatched method | 9 (3 fault kinds × 3 separate script runs — `fault_injection.log`, `fault_injection2.log`, `fault_injection_postfix.log`) | `scratchpad/live_results/CTL017-fault-{timeout,429,5xx}.json`, `scratchpad/fault_injection*.log` |

**Total: 19 real, live end-to-end runs** between approximately
2026-09-28T16:24Z and 2026-09-28T16:51Z (the human audit's initial estimate
of "approximately 18" is confirmed correct within rounding — the exact
count from script/log cross-referencing is 19).

### Which boundaries were intercepted vs. left live

- **Intercepted (fake/stubbed):** PubMed, ClinicalTrials, ChEMBL HTTP
  transport — but only inside `fault_injection.py`'s 9 runs. `smoke_test.py`
  and `live_runner.py`'s 10 runs intercepted **nothing at all**.
- **Left live in all 19 runs:** Cerebras native tool-selection
  (`orchestration/candidate_b_native_tools.py::call_cerebras_native_tools`),
  Cerebras claim generation (`generation/generator.py`), and every NVIDIA
  NIM `ChatNVIDIA` call (query understanding, synthesis, report generation,
  grounding judge) via `config/llm_config.py::get_llm()`.

### Why these runs were unnecessary for the authorized Step-8 audit

The governing directive for this pass was explicit: *"Use dependency
injection / transport stubs / controlled fault boundaries wherever
possible. Do NOT abuse live public services."* Every fault class the
directive asked for (timeout, connection failure, 429, 5xx, malformed
JSON, schema-invalid response, retry exhaustion) is fully reproducible via
`unittest.mock.patch`/`monkeypatch` at the transport or client-method
boundary — and `tests/test_phase9_fault_matrix.py` proves this: it
independently covers the same fault classes, purely via mocks, with **zero
real network calls**, and is what the formal `phase9_fault_matrix.json`
(37/37 PASS) is actually built from (confirmed by direct inspection: the
artifact's `cerebras_503_reconciliation` and all 37 scenario rows cite only
`unittest.mock`/pre-existing Sept-25 log evidence, never the scratchpad
live-run outputs). The live scripts were not needed to reach any of the
formal conclusions — they were exploratory/confirmatory work that exceeded
the pass's authorized scope.

### Whether provider rate limits were actually exceeded

From `logs/medagent.log` alone (no new requests made to check this):

- **Cerebras** (configured 5 RPM = 1 call/12s): 54 real
  `call_cerebras_native_tools()` invocations logged in the 16:24Z-16:50Z
  window. Inter-call spacing in dense clusters is consistently ~12-24s,
  consistent with `utils/rate_limiter.py`'s own token bucket throttling
  these calls correctly even under this unplanned load — i.e., **MedAgent's
  own rate limiter appears to have prevented a self-inflicted RPM
  violation**. Two real (non-injected) Cerebras `429` responses were
  received (`"code":"queue_exceeded"`, real Cerebras response body, at
  16:34:51Z-16:34:52Z) — this is the provider's own server-side queue
  pressure, not evidence that MedAgent exceeded its configured 5 RPM cap.
  **No explicit rate-limit-violation log line (`utils.rate_limiter`
  warning/error) appears in the window.**
- **NVIDIA NIM**: 53 real `[LLM DISPATCH]` calls logged in the window; 27
  received a real `503 Service temporarily overloaded` at some point (all
  absorbed by `_RateLimitedChatNVIDIA`'s existing bounded retry, matching
  its documented design — see the Cerebras-503 reconciliation below, which
  this same mechanism explains); 24 dispatch results logged
  `status=success` directly. No 429 from NVIDIA was observed in the window.

**Conclusion: unauthorized traffic occurred; a confirmed rate-limit
*violation* by MedAgent itself did not.** The two real Cerebras 429s and
the NVIDIA 503s observed are ordinary transient provider-side conditions,
already covered by existing retry/backoff mechanisms and consistent with
what the Step 8 fault matrix already models via stubs — they do not
represent new information not already captured formally, only unnecessary
real-world cost to obtain a live echo of it.

### Which artifacts/claims were influenced by the runs

**None of the formal Step 8-11 written conclusions depend on this
evidence.** Verified by direct inspection:

- `artifacts/v2/phase9_fault_matrix.json` — self-contained; its own
  `"method"` field states "No real network call against
  Cerebras/NVIDIA/PubMed/ClinicalTrials/ChEMBL was made anywhere in this
  artifact," and its `cerebras_503_reconciliation` section cites only the
  pre-existing 2026-09-25 baseline-run log lines (Category A) and
  `phase9_baseline_results.json`, never the scratchpad live-run outputs.
- `artifacts/v2/phase9_concurrency_audit.json` — self-contained; its
  `"purpose"` field states concurrency tests used "stubbed LLM/tool
  boundaries (no real network calls)."
- `artifacts/v2/phase9_rate_limiter_audit.json`,
  `artifacts/v2/phase9_boundedness_analysis.json` — no reference to the
  scratchpad live-run outputs anywhere in either file (grep-confirmed).

The 19 live runs therefore contributed **no primary evidence** to any
formal Phase-9 gate claim. They stand only as unplanned supplementary
observations (see "Category A vs. B" classification in
`PHASE9_RELIABILITY_PERFORMANCE.md`).

### Root cause

The executing agent reused two pre-existing scripts from the Phase-8
local-closure pass (`live_runner.py`, and a fault-injection pattern
resembling the CTL-017 methodology) without re-deriving whether Phase-9's
own, stricter "stubs wherever possible, do not abuse live services"
instruction — different from Phase-8's own live-verification mandate,
where real end-to-end calls were the explicit point — still applied. The
reused scripts' docstrings correctly self-describe as doing real,
unmocked calls; the deviation was in applying a Phase-8-appropriate tool
under a Phase-9 constraint that forbade it, not in the tool's own
documentation being wrong or hidden.

### Remediation

1. This record (`PHASE9-PROCESS-DEV-001`) created; not hidden, not
   deleted.
2. Formal Steps 8-11 evidence re-audited and confirmed independent of the
   unauthorized runs (see above) — **no formal conclusion changes**.
3. `docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md` amended with an explicit
   "Supplementary Live Observations" section separating this evidence from
   the controlled/authoritative findings (never combined into one pass
   rate).
4. Scratchpad live-run outputs and scripts preserved as-is (not deleted;
   see "Scratchpad disposition" below) — they remain outside the git
   working tree (`/private/tmp/.../scratchpad/`, never staged) and require
   no repository action.
5. No additional live provider calls were made during this remediation.
6. **Going forward**, any live/E2E script reused across phases must be
   re-checked against the *current* phase's own stated scope before
   execution, not assumed compatible because it worked in a prior phase.

**Was any formal Phase-9 conclusion changed by this deviation?** **No.**
Every Category-A (controlled) result stands unchanged. The deviation is a
process-integrity finding about *how* the investigation was conducted, not
a correction to *what* it found.

---

## PHASE9-PROCESS-DEV-002: Per-thread monkeypatch race in a concurrency test, causing one accidental real NVIDIA model-listing call

**Classification:** methodology/process deviation (TEST HARNESS bug).
**Not** a MedAgent product defect - no application code is implicated.
Kept as an INDEPENDENT record from PHASE9-PROCESS-DEV-001 above (see that
section's own summary for the unrelated deviation it documents) - same
category, different root cause, different discovery mechanism, not merged.
Full machine-readable record: `artifacts/v2/phase9_process_deviation_002.json`.

**Discovered by:** self-discovered while authoring
`tests/test_phase9_concurrency_audit.py`'s `TestConcurrentRichStateIsolation`
coverage, during the PRE-OPTIMIZATION CONSISTENCY AUDIT pass that preceded
this BOUNDEDNESS HARDENING pass.

**What happened:** an earlier, per-thread version of that test's stub-
installation helper created and tore down (`.undo()`) a fresh
`pytest.MonkeyPatch()` instance INSIDE each worker thread's own task
function, patching PROCESS-GLOBAL module attributes
(`agent.nodes.get_llm`, `agent.nodes.call_cerebras_native_tools`, etc.).
Because `monkeypatch.setattr`/`.undo()` mutate the one shared module
namespace regardless of which thread calls them, one thread's `.undo()`
could restore the REAL `agent.nodes.get_llm` while another thread's
`MedAgent(research_loop=True).run()` call was still mid-flight - observed
empirically as a real `langchain_nvidia_ai_endpoints.ChatNVIDIA` client
being constructed, which itself makes a real HTTP call to NVIDIA's
model-listing/auth-validation endpoint as part of its own `__init__`
(library behavior, not something MedAgent's application code triggers
deliberately). No biomedical/query/Evidence data was ever sent in this
call - it was a client-initialization call, not a chat-completions request.

**Root cause:** a per-thread `pytest.MonkeyPatch()` install/undo cycle
racing on a shared, process-global module attribute, in a multi-threaded
test. See `_marker_from_query`'s docstring in
`tests/test_phase9_concurrency_audit.py` for the in-repo, code-adjacent
explanation this record cross-references rather than duplicates.

**Impact:** none on any formal Phase-9 conclusion. This is a bug in how a
TEST stubbed its own dependencies, not a finding about MedAgent's actual
concurrency-safety behavior (which the CORRECTED version of this same test
class continues to cover, with zero data-correctness defects found -
see the "Concurrency and rate-limiter audits" section below). The racy
version was caught and fixed during authoring, before being left in the
repository in that form.

**Remediation:** install every monkeypatch ONCE, globally, on the main
thread, before any worker thread is spawned; derive all per-task stub
behavior from data already present in each task's own `state` argument
(thread-local by construction) rather than from a per-thread patch/undo
cycle. Implemented in
`tests/test_phase9_concurrency_audit.py::_install_rich_state_stubs_once` /
`_marker_from_query`. Documented as a going-forward rule for any future
multi-threaded test needing per-task stubbed behavior.

**Was any formal Phase-9 conclusion changed by this deviation?** **No.**
Confirmed explicitly in `artifacts/v2/phase9_process_deviation_002.json`.

---

## PHASE9-PROCESS-DEV-003: Suspected unauthorized live-provider traffic caused by stale deterministic tests after GAP_ANALYSIS_BATCH_SIZE changed from 1 to 2

**Classification:** methodology/process deviation (TEST HARNESS gap) -
**suspected**, not confirmed. **Not** a MedAgent product defect - no
application code is implicated. Kept as an INDEPENDENT record from
PHASE9-PROCESS-DEV-001/002 above - same category, different root cause,
different discovery mechanism, not merged.

**Discovered by:** self-discovered during the Phase-9 FINAL freeze pass,
immediately after flipping the production default
`GAP_ANALYSIS_BATCH_SIZE` from 1 to 2 (following the live pair-batching
benchmark's accepted result) and launching the full deterministic
regression suite to confirm the flip was safe.

**What happened:** the full suite (`pytest tests/ -q -rs`) stalled for
~12 minutes of wall-clock time while consuming only ~13 seconds of CPU
time - a signature consistent with the process blocking on I/O (real
rate-limiter sleeps and/or a real socket wait) rather than doing
computational work. The run was interrupted (`SIGQUIT`, then later
`SIGKILL`) rather than left to continue indefinitely, per this project's
"stop rather than push through unexplained hangs/unexpected traffic" rule.
Its captured progress showed approximately 8 failures appearing around the
55-66% mark of the suite.

**Affected file / missing network isolation:**
`tests/test_phase9_claim_budget.py` - every one of its 11 tests mocks
*only* the single-claim `judge_claim_semantic` (never
`judge_claims_batch`), constructs between 27 and 320 factual claims per
test (to exercise `CLAIM_EVALUATION_BUDGET`), and used **zero** `no_network`
protection anywhere in the file (relying solely on the single-claim mock,
which was sufficient before batching existed). A second, narrower instance
was also present in one test of `tests/test_phase9_quality_non_regression.py`
(`test_claim_budget_guard_branch_never_entered_when_under_budget`,
constructing `CLAIM_EVALUATION_BUDGET-1` = 31 claims, same missing-guard
pattern).

**Why the default flip exposed the stale mock:** `research/gap_analysis.py`
now groups scheduled claims into pairs when `GAP_ANALYSIS_BATCH_SIZE=2` and
dispatches each pair via `grounding_eval.judge.judge_claims_batch` (a
function that did not exist, and therefore could not have been mocked,
when these tests were originally written). With that function left
unmocked, and with `settings.CEREBRAS_API_KEY` genuinely configured in
this development environment (confirmed via direct inspection), the code
does **not** take the "API key not configured" fast-fail path - it
proceeds into the real `utils.rate_limiter.wait_for_rate_limit()` call
(genuine synchronous waits, unmocked) and then attempts a real
`requests.post()` to `https://api.cerebras.ai/v1/chat/completions`, with
nothing in this file positioned to intercept it.

**Evidence supporting suspicion (not proof):**
1. `settings.CEREBRAS_API_KEY` is confirmed configured (real key present)
   in this environment - the "not configured" fast-fail did not apply.
2. `tests/test_phase9_claim_budget.py` has zero `no_network` usage across
   all 11 tests - nothing local would have blocked an outbound call.
3. The observed near-zero-CPU/long-wall-clock signature is consistent with
   genuine blocking I/O (real rate-limiter sleeps and/or real network
   round-trips), not a deadlock or infinite loop in application code.
4. This file's position in pytest's default collection order (file-index
   21 of ~40+ test files) is consistent, by cumulative test-count
   weighting, with the 55-66% progress mark at which the interrupted run's
   failures appeared.
5. The observed failures are fully explained by REAL provider responses
   not matching what each test's fake single-claim judge was rigged to
   return - a real Cerebras response for a batch of fabricated
   placeholder claim text (e.g. `"Factual claim c0."`) would legitimately
   cause exactly this kind of assertion mismatch.

**Inability to confirm provider-side receipt from local logs:**
`logs/medagent.log` shows zero hits for `cerebras.ai` in the relevant time
window - but this is **not exculpatory**. Independently confirmed earlier
in this same Phase-9 effort (during the fully-authorized, 23-call live
pair-batching benchmark): `grounding_eval/judge.py`'s `requests.post()`
call site does not route through `agent.nodes`'/the application's logging
pipeline at all, so that benchmark's own real, confirmed live calls also
produced zero `medagent.log` hits. The log's silence therefore says
nothing either way about whether a real request left this machine during
the interrupted run. No provider-side (billing/usage dashboard)
confirmation was sought, and **no new live call was made to verify this
suspicion** - per the explicit instruction not to generate any new live
traffic to investigate it.

**Remediation:**
- `tests/test_phase9_claim_budget.py`: added an autouse fixture pinning
  `GAP_ANALYSIS_BATCH_SIZE=1` (this file tests the claim budget, not
  batching - holding batching at its pre-batching value is correct test
  isolation, not a weakening) **and** a second autouse fixture that forces
  the pre-existing opt-in `no_network` guard (`tests/conftest.py`) active
  for every test in the module, regardless of each test's own signature -
  so any future change that again routes a claim group through a real,
  unmocked call fails loudly and immediately instead of silently
  attempting one.
- `tests/test_phase9_quality_non_regression.py`: identical two-fixture
  remediation (batch-size pin + forced `no_network`).
- `tests/test_phase9_gap_analysis_concurrency.py`: already carried
  `no_network` on every one of its 18 tests (so no real traffic could have
  escaped from this file regardless of the default flip - its symptom was
  a genuine but harmless hang from real, unmocked rate-limiter waits before
  the blocked call raised, not a network escape) - received only the
  batch-size pin, for the same test-isolation reason as above.
- `tests/test_research_models_and_gap_analysis.py`: a precautionary pin
  was added here during initial triage, then REMOVED after a full static
  audit proved every test in this file schedules at most one
  judge-eligible factual claim (a second, non-factual `ClaimType.INFERENCE`
  claim in one test is filtered out before any grouping/dispatch occurs) -
  this file was never actually exposed to the batching code path at any
  `GAP_ANALYSIS_BATCH_SIZE` value, so no fix was needed here.
- No other file in the deterministic suite was found, via full static
  audit, to construct 2+ judge-eligible claims while mocking only the
  single-claim judge function without either `no_network` protection or
  being otherwise unreachable (e.g. `gap_analysis_node` itself stubbed
  out, as in `tests/test_phase9_concurrency_audit.py`).

**No product defect found.** Every failure/hang traces to test-harness
staleness (a new function, `judge_claims_batch`, introduced by the
pair-batching implementation, not yet known to tests written before it
existed) or a missing test-level network guard - never to incorrect
behavior in `research/gap_analysis.py`, `grounding_eval/judge.py`, or the
pair-batching implementation itself. The 29 tests in
`tests/test_phase9_pair_batching.py` (which mock both judge functions and
use `no_network` throughout by design) were not implicated and remain the
authoritative deterministic evidence for the batching implementation's
correctness.

**Was any formal Phase-9 conclusion changed by this deviation?** **No.**
The live pair-batching benchmark result (batch_size=2 selected) is
unaffected - this deviation concerns only test-harness exposure discovered
*after* that benchmark, during the subsequent regression-safety check of
the default-flip decision, not the benchmark itself.

---

## PHASE9-DEFECT-001: Missing intentional application-level claim-evaluation budget (reframed by the PRE-OPTIMIZATION CONSISTENCY AUDIT — see below before reading the rest of this entry)

**PRE-OPTIMIZATION CONSISTENCY AUDIT CORRECTION (supersedes this entry's
original title/wording below):** the original title and several statements
below said the judge-call count and wall-clock time were "unbounded"
without checking whether an *executed* provider-side output-token limit
already provides a finite (if very large) ceiling. Rechecked:
`generation/generator.py::_invoke_cerebras_claims` sends
`max_completion_tokens=4096` (its own hard-coded default, confirmed via its
single call site — no override anywhere in the executed path) inside the
real Cerebras request body, in strict JSON-schema mode. Standard
OpenAI-compatible completions-API behavior (which Cerebras implements)
hard-truncates generation at that token count — a genuine, executed,
provider-enforced ceiling, not an invented one. **The corrected, strongest
defensible statement is: finite only because of this external/provider
output-token limit, NOT because of any deliberate application-level claims
budget** (full derivation, including an order-of-magnitude estimate of the
resulting ceiling — roughly ~100-150 claims/cycle, ~400-600 across all 4
generation cycles — in `artifacts/v2/phase9_boundedness_analysis.json`'s
`claim_count_boundedness.answers` field). The system is **not**
mathematically unbounded; it **is** missing any *intentional,
semantically-meaningful* claim-evaluation budget — the only ceiling that
exists is an accidental byproduct of a token-length setting chosen for
unrelated cost/latency reasons, and its real value is large enough to
provide no meaningful reliability guarantee. The defect is therefore
**renamed and reclassified** below; the root-cause code citations (schema/
generation-schema/parser/validation/runtime layers all lacking a claim-COUNT
cap) remain accurate and unchanged — only the "unbounded" framing and
severity are corrected.

**Corrected title:** Missing intentional application-level claim-evaluation
budget for gap-analysis judge calls — the only existing ceiling
(`max_completion_tokens=4096` on the Cerebras claim-generation call) is an
incidental, very large, provider-token-budget side effect, not a
deliberate reliability safeguard.

**Classification:** APPLICATION-LEVEL BOUNDEDNESS DEFECT (reframed from
"unbounded call-count" per the consistency audit) — still a genuine,
real Phase-9 finding, not a literal-infinity overclaim; not a
correctness/fabrication defect.

**Discovered during:** Step 11 (formal worst-case boundedness derivation),
specifically the claim-count boundedness sub-task.

**Symptom:** There is no fixed upper bound on `GroundedAnswer.claims`'
length anywhere in the code, which means `research/gap_analysis.py::analyze_gaps`'s
`for claim in grounded_answer.claims:` loop (line 84) can issue an
unbounded number of `judge_claim_semantic()` calls per gap-analysis pass —
and since this pass runs once per generation cycle (up to 4 times per
request: 1 initial + up to 3 research-loop follow-ups), the system's
total external-call count and total wall-clock time have no formal upper
bound, as a function of the model's own claim-generation output length.

**Root cause (exact code citations):**

1. **Schema layer** — `generation/models.py:119`:
   ```python
   claims: List[GroundedClaim]
   ```
   A plain `List[...]` annotation with no `Field(max_length=...)` or any
   other pydantic length constraint. Confirmed absent by direct reading;
   grep for `max_length`/`max_items` anywhere in `generation/models.py`
   returns zero matches.

2. **Generation JSON-schema layer** — `generation/generator.py:86-102`
   (`_CLAIMS_JSON_SCHEMA`):
   ```python
   "claims": {
       "type": "array",
       "items": {...},
   }
   ```
   No `"maxItems"` key. Grep for `maxItems` anywhere in
   `generation/generator.py` returns zero matches.

3. **Parser layer** — `generate_grounded_answer`/`_invoke_cerebras_claims`
   in `generation/generator.py` check only `isinstance(claims_raw, list)`
   before constructing `GroundedClaim` objects — no length check before or
   after parsing.

4. **Validation layer** — `generation/validation.py::validate_claims`
   checks: (a) every `evidence_ids` reference is a known Evidence ID, (b)
   every FACTUAL claim has ≥1 `evidence_ids`, (c) `claim_id` uniqueness,
   (d) no bare source-native ID citation. It performs **no check on
   `len(claims)`** anywhere in the function body — confirmed by direct
   reading of the complete function.

5. **Runtime consumer layer** — `research/gap_analysis.py:84`:
   ```python
   for claim in grounded_answer.claims:
       if claim.claim_type.value != "factual" or not claim.evidence_ids:
           continue
       ...
       judgment = judge_claim_semantic(claim.claim_id, claim.text, list(cited.keys()), cited)
   ```
   No slicing, no early-exit cap, no sampling — every factual claim with
   `evidence_ids` triggers one judge call.

**Soft mitigating factor, not a cap:** `generation/generator.py`'s
`_invoke_cerebras_claims` uses `max_completion_tokens=4096` for the
Cerebras claim-generation call, which places an indirect, token-budget-derived
ceiling on total OUTPUT size — but this is not a deterministic claim-COUNT
cap: a model could produce many short claims (each citing one
`evidence_id`) within that token budget, and nothing validates or rejects
an unusually large claims array as a distinct failure mode.

**Formal impact — CORRECTED by the consistency audit** (see
`docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md`'s Step 11 section and
`artifacts/v2/phase9_boundedness_analysis.json` for full derivations).
`C_g` is not literally unbounded — each generation cycle's
`max_completion_tokens=4096` ceiling caps it at an order-of-magnitude
estimate of **~100-150 claims/cycle** (not an exact enforced count).
Formulas below are therefore **INPUT/OUTPUT-DEPENDENT BOUNDS** (finite, but
not a fixed application constant and not tightly characterized), not
literally unbounded:
- Formula 1 (max LLM calls/request): `11 + Σ C_g` — finite, ≈ `11 + 4×150 ≈ 611` order-of-magnitude worst case.
- Formula 5 (max gap-analysis judge calls): `Σ C_g` — finite, ≈ `600` order-of-magnitude worst case.
- Formula 6 (max total external calls): `116 + 2·Σ C_g` — finite, ≈ `1316` order-of-magnitude worst case.
- Formula 7 (max wall-clock time): `~4612s + Σ C_g × ~144s` — finite, ≈ `~91,000s (~25h)` order-of-magnitude worst case; still practically unbounded FOR PLANNING PURPOSES even though it is not mathematically infinite.

**Was this ever observed to cause a real user-visible problem?** Not
directly observed as a runaway case in this pass's baseline data
(`artifacts/v2/phase9_baseline_results.json`'s 12 cases all completed with
claim counts small enough not to dominate latency) — this is a **formal
worst-case gap**, proactively derived from code reading per the governing
directive's explicit instruction to derive real formulas rather than
assume safety, not a defect discovered via a failing test or a bad live
run. `research/gap_analysis.py`'s own baseline-profile finding (56.3% of
all stage time in `gap_analysis`, per `artifacts/v2/phase9_baseline_profile.json`)
is consistent with claim count already being a meaningful cost driver
today, even without a pathological case having occurred yet.

**Was it fixed in this pass?** **No** — per the governing directive's
explicit instruction ("do NOT choose or implement a fix... analyze
candidate remedies... do not implement"). Continuing this audit did not
require a fix (the audit's own conclusions do not depend on the defect
being absent — they document its presence).

**Candidate remedies analyzed (not implemented; full detail in
`artifacts/v2/phase9_boundedness_analysis.json`):**

| ID | Remedy | Net verdict (summary) |
|---|---|---|
| A | Hard max factual claims per answer | Simple, but silent-drop risk is HIGH unless paired with explicit disclosure; touches frozen Phase-6 code. |
| B | Total gap-analysis evaluation budget (not per-answer) | Most surgical for latency; needs an explicit "not evaluated" state to avoid looking like a false pass; Phase-8-owned files only, no Phase-6/7 touch. |
| C | Batch claim judging (one call, many claims) | Reduces call count but trades it for prompt-size risk; touches frozen Phase-7 judge contract, needs its own re-validation pass. |
| D | Bounded concurrency for judge calls | Reduces wall-clock for a fixed claim count, does NOT fix the call-count-unboundedness formula; **explicitly out of scope this pass regardless** (governing directive forbids parallelizing gap_analysis). |
| E | Bounded truncation with explicit disclosure | Same mechanism as A but disclosure-first by construction — lowest silent-drop risk among the generation-side options. |
| F | Whole-answer gap analysis (1 call, not 1/claim) | Strongest latency fix (hard-bounds at G=4), but loses per-claim attribution that `research/action_planning.py`'s gap→claim→follow-up mechanism depends on — the most invasive relative to frozen Phase 7/8 behavior. |

**Status (original, as of the boundedness-derivation pass):** OPEN.
Documented and formally derived; no remedy selected or implemented. Left
for a future phase's explicit decision, consistent with this project's
phase-gate discipline (a Phase-9-discovered defect in a Phase-6/7/8-owned
file requires its own gate review before modification, per the governing
directive's carve-out language).

### 2026-09-28 UPDATE - FIXED in the Phase-9 "BOUNDEDNESS HARDENING" pass

**Status: FIXED.** (This sub-section is additive - every line above this
one is preserved unchanged as the historical record of the analysis that
led here; nothing above was deleted or rewritten.)

Remedy **B** ("Total gap-analysis evaluation BUDGET - cap total judge
calls across the whole request, not per-answer") from the candidate table
above was selected and implemented, exactly as that table's own analysis
anticipated: request-global scope, `research/gap_analysis.py` +
`research/loop_control.py` only (no `generation/` file touched, Phase-6/7
frozen code untouched), paired with an explicit "not evaluated" state
(remedy B's own stated requirement) rather than a silent skip.

- **New constant:** `research/loop_control.py::CLAIM_EVALUATION_BUDGET = 32`
  (request-global, not per-cycle). Derivation: the highest single-round
  `n_factual_claims` value observed anywhere in the Phase-8 dev/validation
  corpus (`artifacts/v2/phase8_dev_benchmark_results.json` +
  `phase8_validation_results.json` + `phase8_validation_run2_results.json`,
  n=45 round-level values) is 8, and `MAX_RESEARCH_ITERATIONS` hard-bounds
  any request to at most G=4 generation cycles - `8 x 4 = 32` is exactly
  what a request would need to sustain the corpus's own worst observed
  single-round rate across every one of its hard-bounded cycles, and is
  already 2x the highest actually-observed CUMULATIVE multi-round total in
  that same corpus (16, case VAL-F-tool-failure-safe-termination). Full
  distribution in `artifacts/v2/phase9_claim_and_tool_call_distributions.json`.
- **New gap type:** `research/models.py::GapType.EVALUATION_BUDGET_EXHAUSTED`
  - a claim whose judge call was skipped due to budget exhaustion gets this
  EXPLICIT gap, distinct from both "supported" (no gap) and "weak/
  contradicted" (the two pre-existing judge-driven gap types). Never
  fabricates an Evidence ID; only ever names the claim's own `claim_id`.
- **Scope decision (request-global, not per-cycle):** justified in
  `docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md`'s "BOUNDEDNESS HARDENING"
  section - request-global directly bounds the actual reliability concern
  (total judge-call count / wall-clock cost for the WHOLE request) with one
  clean number, matches the existing `MAX_TOOL_CALLS_TOTAL`
  request-global-budget naming convention already established in the same
  module, and is simpler to reason about than tracking G=4 separate
  per-cycle sub-budgets that would still need to sum to a request-level
  guarantee anyway.
- **Claims are NEVER dropped, NEVER marked supported:** the claim stays in
  `grounded_answer.claims`/`rendered_text` exactly as generated; only its
  gap-analysis judgment is skipped.
- **Caveat propagation:** `agent/nodes.py::finalize_research_answer_node`'s
  pre-existing PHASE8-DEFECT-001 qualifier machinery was extended
  (`_UNRESOLVED_CLAIM_GAP_TYPES` now includes
  `"evaluation_budget_exhausted"`, with its own distinct, honest qualifier
  wording: `"not evaluated by the grounding judge (request evaluation
  budget exhausted)"` rather than the pre-existing "not fully confirmed by
  follow-up research" wording, since the claim was never evaluated at all)
  - reused verbatim, no second/parallel caveat mechanism built.
  `render_answer_text` re-render is unchanged (still the frozen Phase-6
  compiler).
- **Never falsely resolved:** `research/action_planning.py::plan_actions`
  now excludes `EVALUATION_BUDGET_EXHAUSTED` gaps from candidate selection
  (no tool call can ever resolve "this claim's own already-cited evidence
  was never judged") - and
  `research/loop_control.py::decide_stop_reason`'s pre-existing `if not
  gaps: return SUFFICIENT_EVIDENCE` check is untouched, so a
  budget-exhausted gap (which is never empty-listed) can never produce a
  false `sufficient_evidence` stop. The natural consequence - zero
  productive actions remaining while a budget-exhausted gap persists -
  reaches `NO_PRODUCTIVE_ACTION` via the EXISTING stop-reason mechanism,
  with no new stop reason invented.
- **Tests:** `tests/test_phase9_claim_budget.py` (11 tests - below/at/over/
  massively-over budget, cross-round request-global accounting,
  already-judged-claims-preserved, no-false-sufficient-evidence, no-action-
  planned-for-this-gap-type, deterministic ordering, dormant-below-
  threshold non-regression). All 11 pass.
- **Regression check on PHASE8-DEFECT-001/002 (the pre-existing fixes this
  new code sits directly next to):** `tests/test_research_finalize_answer_defect_fix.py`
  + `tests/test_research_integration.py` re-run in full after this change:
  **21 passed, 0 failed** (identical to their pre-change pass count - these
  test files were not modified).
- **Full formula recomputation:** see
  `docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md`'s "BOUNDEDNESS HARDENING"
  section (PRE-FIX vs POST-FIX, side by side) and
  `artifacts/v2/phase9_boundedness_analysis.json`'s new
  `formulas_post_fix`/`claim_budget_design` keys (existing keys left
  intact, nothing deleted).

---

## PHASE9-DEFECT-002: Missing intentional application-level tool-call budget for model-emitted tool calls

**Classification:** APPLICATION-LEVEL BOUNDEDNESS DEFECT (same framing as
the corrected PHASE9-DEFECT-001 above - a real, finite-but-not-meaningfully-
bounded call-count gap, never a literal-infinity overclaim; not a
correctness/fabrication defect).

**Discovered during:** this pass's own Step 6 distribution-extraction +
code-reread, following directly from the PRE-OPTIMIZATION CONSISTENCY
AUDIT's `tool_vs_source_call_reconciliation` finding (see
`artifacts/v2/phase9_boundedness_analysis.json`'s
`pre_optimization_consistency_audit_corrections` key) that `DECLARED_TOOLS_COUNT=6`
had been incorrectly treated as an enforced per-round cap on model-emitted
`tool_calls[]` entries in the original boundedness derivation, when it is
actually only the count of distinct declared FUNCTION SCHEMAS offered to
Cerebras - nothing structurally prevents the model from returning many more
`tool_calls[]` entries (duplicates of the same function, or simply a long
array) in a single response.

**Symptom (verified against the actual, pre-fix code this pass started
from):** `agent/nodes.py::tool_orchestration_node`'s
`for i, raw_call in enumerate(raw_tool_calls):` loop (originally at
approximately line 699, before this pass's edits) iterated the ENTIRE
`raw_tool_calls` array returned by `call_cerebras_native_tools()` with no
length check, no slicing, no early-exit cap. `research/loop_control.py`'s
existing `MAX_TOOL_CALLS_TOTAL=8` does **not** solve this: it counts
`research_execution_node` ROUND INVOCATIONS (incremented exactly once per
follow-up round at `agent/nodes.py:1625`,
`state["research_tool_calls_used"] += 1`), never individual
`raw_tool_calls[]` entries within a single round's response - a single
round could therefore process an arbitrarily model-output-dependent number
of tool calls while `research_tool_calls_used` increments by exactly 1
regardless.

**Root cause (exact code citations, as found before this pass's fix):**

1. `agent/nodes.py::tool_orchestration_node` - `for i, raw_call in
   enumerate(raw_tool_calls):` with no length cap, confirmed by direct
   reading.
2. `orchestration/candidate_b_native_tools.py::DECLARED_TOOLS` (6 entries)
   is a schema-declaration count only - never consulted as a runtime cap
   anywhere in `tool_orchestration_node` or
   `parse_and_validate_tool_call`.
3. `research/loop_control.py::MAX_TOOL_CALLS_TOTAL=8` operates at the
   ROUND layer (see `pre_optimization_consistency_audit_corrections` in
   `artifacts/v2/phase9_boundedness_analysis.json` for the full
   layer-conflation writeup) and never binds tighter than
   `MAX_RESEARCH_ITERATIONS`-derived `R=4` under the current loop
   structure - it does not participate in bounding per-round tool-call
   count at all.

**The provider-output-dependent practical bound that DOES exist (soft,
not a deliberate application safeguard):**
`orchestration/candidate_b_native_tools.py::call_cerebras_native_tools`
sends `max_completion_tokens=1024` (its own hard-coded default, confirmed
no override at its single call site, `agent/nodes.py`'s
`call_cerebras_native_tools(query)` invocation) inside the real Cerebras
tool-selection request. Using the same order-of-magnitude token-cost-per-
entry reasoning the (corrected) PHASE9-DEFECT-001 analysis used for claim
counts, this yields a soft ceiling on the order of **~20-30 valid
tool_calls per round** - finite (so, per the same "do NOT call it
infinite" framing already established for PHASE9-DEFECT-001, this is never
described as unbounded), but an accidental byproduct of a token-length
setting chosen for unrelated cost/latency reasons, not a deliberate
reliability safeguard - exactly the same character of gap as
PHASE9-DEFECT-001.

**Reliability impact:** A single pathological or adversarial Cerebras
response returning many `tool_calls[]` entries in one round would have
caused `tool_orchestration_node` to attempt registry validation and (for
every registry-valid entry) real biomedical HTTP execution for all of
them, with no per-round ceiling - directly inflating both wall-clock time
and worst-case biomedical-source HTTP call count for that single round,
independent of `MAX_RESEARCH_ITERATIONS`/`MAX_TOOL_CALLS_TOTAL`, neither of
which would have caught it before real HTTP calls were already made.

**Worst-case HTTP-retry amplification (pre-fix):** each registry-valid
call that reaches `execute_validated_call` can itself retry up to
`utils/retry_handler.py::RetrySession.MAX_RETRIES=3` (4 total HTTP
attempts) - so an unbounded number of logical tool calls in one round
implies an unbounded number of HTTP attempts too, amplified 4x per call.

**Proposed remediation (implemented THIS pass - see the "FIXED" sub-section
below; not left open, unlike PHASE9-DEFECT-001's original single-pass
scope):** two new, named, request-global/per-round hard constants in
`research/loop_control.py` (`MAX_TOOL_CALLS_PER_ROUND`,
`MAX_TOOL_CALLS_PER_REQUEST`), enforced in
`agent/nodes.py::tool_orchestration_node` by truncating `raw_tool_calls`
to the allowed prefix (deterministic order preserved) BEFORE any
parsing/validation/execution of the overflow entries.

### FIXED in the Phase-9 "BOUNDEDNESS HARDENING" pass (same pass this
defect was discovered in - no separate future-phase deferral was needed,
unlike PHASE9-DEFECT-001's original single-pass scope, since this defect
was found early enough in the same pass to fix directly)

- **New constants:** `research/loop_control.py::MAX_TOOL_CALLS_PER_ROUND = 12`,
  `MAX_TOOL_CALLS_PER_REQUEST = 24`. Full derivation (observed real
  aggregate-per-request `n_tool_calls` data from
  `artifacts/v2/phase9_baseline_results.json`'s 12 real baseline cases,
  max=12; `DECLARED_TOOLS_COUNT=6` headroom reasoning) in
  `docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md`'s "BOUNDEDNESS HARDENING"
  section and `artifacts/v2/phase9_claim_and_tool_call_distributions.json`.
  Confirmed `MAX_TOOL_CALLS_PER_REQUEST (24) <= MAX_TOOL_CALLS_PER_ROUND * R
  (12*4=48)`.
- **Design decision - invalid calls DO consume budget slots:** documented
  explicitly in `agent/nodes.py::tool_orchestration_node` and
  `research/loop_control.py` - the budget counts every `raw_tool_calls[]`
  entry the model emitted, VALID OR INVALID (registry-rejected entries
  included), truncating the array BEFORE `parse_and_validate_tool_call`
  ever runs on the overflow entries. Chosen over the alternative
  (counting only registry-valid calls) because the latter would let a
  response padded with many registry-invalid junk entries bypass the
  budget's real purpose - bounding total processing effort spent on a
  round's raw model output, not just how many calls reach the HTTP
  boundary. Proven by `tests/test_phase9_tool_call_budget.py`'s
  `TestInvalidCallsConsumeBudget` class.
- **Overflow semantics:** overflow entries are NEVER parsed, NEVER
  validated, NEVER executed, and NEVER given a fabricated `ToolResult`;
  truncation preserves Cerebras's own returned order exactly (no
  reordering/prioritization); a synthetic `tool_call_history` entry
  (`error_category="tool_call_budget_exhausted"`) records exactly how many
  calls were truncated, for observability, without inventing a new
  AgentState field beyond the two counters already needed for the budget
  itself.
- **No new stop reason invented:** when the request-global budget is fully
  exhausted, a subsequent round executes 0 tool calls -> the existing
  `research_execution_node` productivity check
  (`tool_results_after == tool_results_before`) marks the action
  `EXECUTED_UNPRODUCTIVE` -> `research_consecutive_failure_rounds`
  increments -> `research/loop_control.py::decide_stop_reason`'s
  pre-existing `TOOL_FAILURE_LIMIT` path fires after
  `MAX_CONSECUTIVE_TOOL_FAILURE_ROUNDS=2` such rounds, exactly per the
  governing directive's instruction to prefer an existing stop-reason path
  over inventing a new one.
- **Tests:** `tests/test_phase9_tool_call_budget.py` (11 tests - below/at/
  over/huge-array-truncated per-round budget, cross-round request-global
  accounting, invalid-calls-consume-budget, retries-not-miscounted-as-new-
  logical-calls, evidence-preserved, no-false-sufficient-evidence,
  deterministic execution ordering). All 11 pass.

---

## Fault-injection matrix: zero correctness defects found

For completeness (mirroring Phase 8's failure-analysis format, which also
records "no defect" sections when relevant): Step 8's 37-scenario fault
matrix (`artifacts/v2/phase9_fault_matrix.json`) found **zero**
fault-handling-correctness defects. Every scenario across all 5 categories
(Cerebras tool-selection faults, the 3 LLM clients' retry policies tested
separately, per-source tool faults, 6 research-loop injection points,
state/graph edge cases) resulted in correct, bounded, disclosed behavior —
no fabricated or invalid Evidence ID, no uncaught exception, no infinite
loop, no false `sufficient_evidence` stop. The Cerebras-503-vs-zero-retry
discrepancy flagged for investigation was fully reconciled (see
`PHASE9_RELIABILITY_PERFORMANCE.md`'s Step 8 section) and resolved as a
provider-attribution mischaracterization, not a real design
inconsistency — the observed 503 was on the NVIDIA NIM client path (which
retries by design), not the Cerebras tool-selection path (which does not,
also by design).

## Concurrency and rate-limiter audits: zero correctness defects found

Step 9's concurrency audit found exactly the theoretical `BaseTool.cache`
race the initial audit flagged, now **empirically confirmed** (2 duplicate
upstream executions under a forced-simultaneous-miss barrier test) and
**confirmed to be inefficiency-only**, never a data-correctness issue (the
final cached value and both callers' returned data are always correct;
plain dict assignment is atomic under the GIL). No other race, no
cross-task state leakage, and no shared-client-safety failure was found at
concurrency=2 or concurrency=4. Step 10's rate-limiter audit found no
correctness defect: no burst above configured capacity was observed under
any tested condition (including 10 threads racing a 1-token bucket), and
retry-token-consumption behavior matches the system's own documented
design rationale (35, not 40, RPM headroom for NVIDIA specifically
accounts for retry-attempt token consumption).
