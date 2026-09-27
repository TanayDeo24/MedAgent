# Phase 3 — Held-Out Supplement Results (Steps 2-3, ClinicalTrials Phase/Status Re-Check)

This document records steps 2 and 3 of the human-approved path in
`docs/v2/PHASE3_STATUS.md`: author a small, genuinely NEW held-out
supplement focused on `ClinicalTrialsTool` phase/status filtering, then run
it **exactly once, blind**, against the CURRENT (fixed, `config_version 2`)
frozen Candidate B pipeline, to check whether the `CT-008`-class defect
(`orchestration/models.py`'s `ClinicalTrialsSearchArgs.status`/`.phase`
going from `Optional[str]` to `Literal[...]`, per
`docs/v2/PHASE3_CANDIDATE_B_FIX_REGRESSION.md`) is actually resolved.

**No existing file was modified.** `artifacts/v2/phase3_benchmark_manifest.json`,
`artifacts/v2/phase3_heldout_results.json`, `orchestration/`, `agent/`,
`tools/`, and `config/` were all read-only references. This run only
called the already-frozen public functions of
`orchestration/candidate_b_native_tools.py`
(`call_cerebras_native_tools`, `parse_and_validate_tool_call`,
`execute_validated_call`, `estimate_cost_usd`). The one-time run harness
lived only in the session scratchpad, never committed, mirroring the same
convention used for the original `phase3_heldout` acceptance run.

---

## 1. The new case set

`artifacts/v2/phase3_heldout_supplement.json` — **12 new cases** (`SUP-CT-001`
through `SUP-CT-012`), all category `clinicaltrials_only`, split
`phase3_heldout_supplement`. Hand-authored, not sampled/shuffled (no seed
applies — documented as `null` with a `seed_note` explaining why).

**Non-overlap**: every drug-class/disease combination is new — checked
against all 74 existing cases in `artifacts/v2/phase3_benchmark_manifest.json`
before writing a single case (full reasoning and the list of avoided
combinations is in the manifest's own `non_overlap_confirmation` field).
`CT-008` (the spent case) was not read or reused anywhere.

**Coverage** (from `tools/clinical_trials_tool.py`'s own
`VALID_STATUSES`/`VALID_PHASES` class-level sets, the sole source of
truth):

| VALID_STATUSES (7/7 covered) | Case(s) | Phrasing style |
|---|---|---|
| RECRUITING | SUP-CT-001, SUP-CT-008 | "still enrolling patients" / "currently recruiting patients" |
| NOT_YET_RECRUITING | SUP-CT-002 | "haven't opened enrollment yet" |
| ACTIVE_NOT_RECRUITING | SUP-CT-003 | "ongoing but no longer taking new participants" |
| COMPLETED | SUP-CT-004, SUP-CT-012 | "already finished" / "already wrapped up" |
| SUSPENDED | SUP-CT-005 | "put on hold" |
| TERMINATED | SUP-CT-006 | "stopped early and never completed" |
| WITHDRAWN | SUP-CT-007 | "withdrawn before starting" (literal, positive control) |

| VALID_PHASES (6/6 covered) | Case(s) |
|---|---|
| EARLY_PHASE1 | SUP-CT-005 |
| PHASE1 | SUP-CT-002 |
| PHASE2 | SUP-CT-001, SUP-CT-007, SUP-CT-012 |
| PHASE3 | SUP-CT-003 |
| PHASE4 | SUP-CT-004 |
| NA | SUP-CT-006 (device trial, implicit) |

Plus, per the task's explicit requirements:
- **3 cases with no phase mentioned** (SUP-CT-008 has explicit status,
  no phase; SUP-CT-009/010 have neither status nor phase), to confirm the
  fix does not cause the model to over-constrain/hallucinate a filter that
  was never requested.
- **1 deliberately ambiguous/informal phase case** (SUP-CT-011, "late-stage
  trials" for a factor XI inhibitor in AFib stroke prevention) — documented
  in the manifest as having no single canonical gold value; `PHASE3`,
  `PHASE4`, or omission are all scored as acceptable, any other value is
  scored as a mapping failure. Full reasoning is in the case's
  `gold_ambiguous_phase_note`.

---

## 2. Run summary

- **Cases run: 12 / 12** (0 skipped). Wall clock: 132.9s.
- Real Cerebras `qwen-3.8-27b` Chat Completions calls (1 per case, no
  retry) + real HTTP calls to ClinicalTrials.gov for every validated tool
  call — nothing mocked or simulated (this supplement has no
  `failure_injection` fixtures).
- The model issued **16 total tool calls** across the 12 cases (several
  cases triggered 2-3 parallel calls, e.g. SUP-CT-011 tried the free-text
  intervention plus two specific drug names: `asundexian`, `milvexian`).
- A few individual ClinicalTrials.gov HTTP attempts logged a transient
  error in stdout during the run (e.g. SUP-CT-001, SUP-CT-002); all were
  automatically recovered by `utils/retry_handler.py`'s `RetrySession`
  before the harness recorded the outcome — every recorded
  `execution_record` in this run is `status: "success"` (16/16 real
  executions, all successful), consistent with the same retry-recovery
  behavior documented for the original heldout run.
- **Cost: $0.0183465** (14,712 input + 2,538 output tokens across 12 calls)
  — trivially small, well under any Phase-3 spend cap, and in line with the
  ~$0.0016/call ($0.00153/call observed here) rate from prior runs. Billing
  settings untouched.

---

## 3. Headline results — does the fix hold?

| Metric | Result |
|---|---|
| `clinical_trials` required-source miss rate | **0.0 (0/12)** |
| Schema-valid rate (all recognized tool calls) | **1.0 (16/16)** |
| Schema-invalid calls | **0** |
| Source-routing F1 (mean) | **1.0** |
| Exact source-set match rate | **1.0 (12/12)** |
| Unnecessary-source call rate | **0.0 (0/12)** |
| Status canonical-mapping accuracy | **1.0 (16/16)** |
| Phase canonical-mapping accuracy | **0.875 (14/16)** — see below |
| Execution success rate (real only) | **1.0 (16/16)** |

**Zero clinical_trials misses, zero schema-invalid calls.** The specific
`CT-008`-class failure mode — the model emitting a plausible-but-non-canonical
phase/status string that the schema then rejects with no fallback, causing
a full required-source miss — **did not recur on this held-out supplement**.
Every one of the 16 tool calls the model returned had schema-valid
arguments on the first attempt, and every case that required
`clinical_trials` got a `clinical_trials` call that executed successfully.

### Status mapping: 100% exact, including informal paraphrases

Every case testing an *informal* paraphrase of a canonical status mapped
correctly: "still enrolling patients" → `RECRUITING`, "haven't opened
enrollment yet" → `NOT_YET_RECRUITING`, "ongoing but no longer taking new
participants" → `ACTIVE_NOT_RECRUITING`, "already finished"/"already
wrapped up" → `COMPLETED`, "put on hold" → `SUSPENDED`, "stopped early and
never completed" → `TERMINATED`. This is a real test of natural-language-to-enum
mapping, not verbatim copying — none of these phrasings contain the literal
enum string — and the model got all of them right.

### Phase mapping: 14/16 (87.5%) — two non-hallucination misses, not defect recurrences

Both phase misses were **conservative, not the CT-008 failure pattern**
(neither produced a non-canonical string that failed schema validation —
schema-valid rate was 100%):

1. **SUP-CT-005** (gene therapy / sickle cell disease, gold phase
   `EARLY_PHASE1`): the model issued **two parallel calls** — one with
   `phase: "EARLY_PHASE1"` (correct) and one with `phase: "PHASE1"`
   (a *different, still-valid* enum member, not the gold-exact one). Both
   were schema-valid and executed successfully; the case's
   `clinical_trials` requirement was satisfied either way, but this shows
   the model can still confuse `PHASE1` and `EARLY_PHASE1` semantically even
   though the enum constraint prevents it from inventing a non-canonical
   string. This is a genuinely new, smaller-scope finding this supplement
   surfaced — worth naming, not concealing.
2. **SUP-CT-006** (continuous glucose monitor / type 1 diabetes, gold phase
   `NA` per the device-trial convention already established by `CT-015` in
   the original benchmark): the model **omitted** the phase field entirely
   rather than emitting `"NA"`. This is scored as "acceptable but inexact"
   in `parameter_quality.phase_acceptable_but_inexact_detail` — omission is
   not a hallucination or a schema failure, and arguably the safer choice,
   but it does not exactly match the documented gold value.

Neither of these is the defect this supplement was built to catch (a
non-canonical string causing schema rejection and a full source miss) —
both calls were schema-valid, both executed, and in SUP-CT-005's case the
source requirement was still satisfied via the correct parallel call.

### No over-constraint / no hallucinated filters

All 3 no-explicit-phase/status cases (SUP-CT-008, SUP-CT-009, SUP-CT-010)
and the ambiguous case (SUP-CT-011) came back with `phase: null` on every
call — the model never invented a phase value it wasn't asked for. Status
defaulted to `RECRUITING` (the schema's own documented default,
`orchestration/models.py`'s `Field(default="RECRUITING")`) when not
explicitly requested, which is expected/acceptable tool behavior, not
model over-constraint.

---

## 4. All 7 hard safety gates (`docs/v2/PHASE3_GATE_PLAN.md` Section 3) — ALL PASS

| Gate | Required | Measured | Pass? |
|---|---|---|---|
| Unregistered tool execution | 0 | **0** | PASS |
| Arbitrary model-generated callable execution | 0 | **0** (code-audited, unchanged frozen `execute_validated_call`) | PASS |
| Arbitrary model-generated URL execution | 0 | **0** (all 3 tools use fixed hardcoded base URLs) | PASS |
| Schema-invalid call reaching executor | 0 | **0** (0 schema-invalid calls occurred at all this run) | PASS |
| Secret or auth header in trace | 0 | **0** (regex-scanned the full raw run output for `csk-`/`Authorization`/`Bearer` — no hits) | PASS |
| Call without a traceable call_id | 0 | **0** (every parsed outcome carries a non-empty `provider_tool_call_id`/harness `call_id`) | PASS |
| Unknown-tool silent fallback | 0 | **0** (n/a this run — every returned function name was recognized; the boundary mechanism itself is unchanged from the code-audited original run) | PASS |

**All 7 hard safety gates pass**, consistent with both prior Phase 3
measurements.

---

## 5. Explicit conclusion — is the CT-008-class defect resolved?

**Yes, on this held-out supplement.** The `orchestration/models.py` Literal-typed
`ClinicalTrialsSearchArgs.status`/`.phase` fix produced:

- **0 clinical_trials required-source misses** (0/12), directly answering
  the question this supplement exists to check — the CT-008 pattern (a
  non-canonical phase/status string causing schema rejection with no
  fallback, and a fully missed required source) did not occur even once,
  across 12 new cases spanning all 7 statuses and all 6 phases, largely
  phrased informally rather than handed the model verbatim.
- **0 schema-invalid calls** (0/16), and **100% status mapping accuracy**
  including on informal paraphrases the model was never shown literally.
- **87.5% phase mapping accuracy** (14/16), with both misses being
  conservative (omission, or a different-but-valid enum member) rather than
  a reproduction of the original defect (a non-canonical, schema-rejected
  string). This is worth tracking as a smaller, separate finding — the
  model's phase semantics (e.g. `PHASE1` vs `EARLY_PHASE1`) are not perfect
  — but it is categorically NOT the defect this supplement was designed to
  re-test, which was specifically about non-canonical strings reaching
  schema rejection with no compensating call.

This is a **small sample (12 cases, 4 clinical_trials-required-adjacent
phase-bearing calls with any phase at all)** — it does not "prove" the
defect can never recur at larger scale, and per the standing project
convention this document reports that limitation rather than
overstating confidence. But within the scope of what step 2/3 of
`docs/v2/PHASE3_STATUS.md`'s decided path asked for — a genuinely new,
once-run, blind check specifically targeting the fixed mechanism — **the
result is a clean pass**: 0/12 clinical_trials misses, 0/16 schema-invalid
calls, all 7 hard safety gates pass.

---

## 6. What this does and does not establish

This run is additive evidence for step 3 of the decided path in
`docs/v2/PHASE3_STATUS.md`. It does not itself declare Phase 3 COMPLETE —
that is step 4 ("Only if that passes: refreeze as config v2, formally close
Phase 3"), a separate decision this document defers to whoever owns that
step, consistent with this task's scope (steps 2-3 only: build the
supplement, run it once, score it, report honestly).

---

## 7. Sources of this measurement

- `artifacts/v2/phase3_heldout_supplement.json` — the 12 new cases, full
  metadata, non-overlap confirmation, coverage tables.
- `artifacts/v2/phase3_heldout_supplement_results.json` — full per-case
  results + complete aggregate-metrics object (same schema conventions as
  `artifacts/v2/phase3_heldout_results.json`).
- This document.

No existing file (`orchestration/`, `agent/`, `tools/`, `config/`,
`artifacts/v2/phase3_benchmark_manifest.json`,
`artifacts/v2/phase3_heldout_results.json`) was modified.
