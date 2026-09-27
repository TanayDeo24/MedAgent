# Phase 3 Candidate B — Fix Regression Verification

This document records step 1 of the human-approved path in
`docs/v2/PHASE3_STATUS.md`: fix the enum-constraint defect that Phase 3's
held-out run surfaced, then **regression-verify** (not a fresh blind check)
against the already-spent `development`+`validation` 59-case split. It does
**not** close Phase 3 — a fresh held-out supplement is still required (see
`docs/v2/PHASE3_STATUS.md` Section "Decided path", steps 3-4).

## 1. The defect (recap)

`orchestration/models.py`'s `ClinicalTrialsSearchArgs.status`/`.phase` were
typed `Optional[str]` with a custom `@field_validator` that correctly
*rejected* an out-of-set value at construction time — but because the
Python type was plain `str`, `.model_json_schema()` (used by
`orchestration/candidate_b_native_tools.py::build_tool_declarations()` to
build the tool declaration sent to Cerebras) emitted no `enum` constraint.
The model had no signal about which phase/status strings are canonical and
could guess a plausible-but-wrong one — observed on `phase3_heldout` case
`CT-008`: it emitted `"Phase 4"` instead of `"PHASE4"`, which was correctly
rejected with no fallback, causing a full required-source miss.

## 2. The fix

`orchestration/models.py`: `status`/`phase` changed from `Optional[str]` to
`Optional[Literal[tuple(sorted(VALID_TRIAL_STATUSES))]]` /
`Optional[Literal[tuple(sorted(VALID_TRIAL_PHASES))]]` — derived directly
from `tools/clinical_trials_tool.ClinicalTrialsTool`'s own
`VALID_STATUSES`/`VALID_PHASES` sets (already imported into this module as
`VALID_TRIAL_STATUSES`/`VALID_TRIAL_PHASES`), never hand-typed, so it can
never drift from the real tool's validation sets.

```diff
     condition: Optional[str] = None
     intervention: Optional[str] = None
-    status: Optional[str] = Field(default="RECRUITING")
-    phase: Optional[str] = None
+    status: Optional[Literal[tuple(sorted(VALID_TRIAL_STATUSES))]] = Field(
+        default="RECRUITING"
+    )
+    phase: Optional[Literal[tuple(sorted(VALID_TRIAL_PHASES))]] = None
     max_results: Optional[int] = Field(default=None, gt=0)
     sponsor: Optional[str] = None
     country: Optional[str] = None
```

The existing `field_validator`s for `status`/`phase` were **kept** for
defense-in-depth, not removed. Empirically verified which layer now
rejects an invalid value first:

```
>>> ClinicalTrialsSearchArgs(phase="Phase 4")
ValidationError: 1 validation error for ClinicalTrialsSearchArgs
phase
  Input should be 'EARLY_PHASE1', 'NA', 'PHASE1', 'PHASE2', 'PHASE3' or
  'PHASE4' [type=literal_error, input_value='Phase 4', input_type=str]
```

Pydantic's own `Literal` coercion now rejects the value first (`literal_error`,
not the custom validator's `value_error`) — the hand-written validators are
now empirically redundant but harmless, and were left in place as a second
line of defense against `models.py`'s `Literal` type and the tool's
`VALID_*` sets ever being changed independently of each other.

Confirmed `.model_json_schema()` now emits a real `enum`:

```json
"status": {"anyOf": [{"enum": ["ACTIVE_NOT_RECRUITING", "COMPLETED",
  "NOT_YET_RECRUITING", "RECRUITING", "SUSPENDED", "TERMINATED",
  "WITHDRAWN"], "type": "string"}, {"type": "null"}], "default": "RECRUITING"}
"phase":  {"anyOf": [{"enum": ["EARLY_PHASE1", "NA", "PHASE1", "PHASE2",
  "PHASE3", "PHASE4"], "type": "string"}, {"type": "null"}], "default": null}
```

`orchestration/candidate_b_native_tools.py::build_tool_declarations()`
builds the Cerebras tool declaration directly from `.model_json_schema()`
with no changes required — it inherits the fix automatically, exactly as
its own docstring intends ("never hand-written, so the declared schema...
can never silently drift").

## 3. Tests

- `tests/test_orchestration_models.py`: existing
  `test_invalid_trial_status_rejected` / `test_invalid_trial_phase_rejected`
  / `test_valid_trial_status_and_phase_accepted` /
  `test_trial_status_none_is_allowed` all still pass unchanged (they assert
  `pytest.raises(ValidationError)` / accepted values, which holds whether
  the rejection comes from `Literal` coercion or the custom validator).
  Added `test_trial_status_and_phase_schema_has_enum_constraint`, asserting
  `ClinicalTrialsSearchArgs.model_json_schema()`'s `status`/`phase`
  properties carry an `enum` equal to `VALID_TRIAL_STATUSES`/
  `VALID_TRIAL_PHASES` exactly.
- `tests/test_candidate_b_native_tools.py`: added
  `test_clinical_trials_declaration_has_status_and_phase_enum`, asserting
  the actual tool declaration built by `build_tool_declarations()` (i.e.
  what is sent to Cerebras) carries the same `enum` for
  `clinical_trials_search_trials`'s `status`/`phase` parameters.

`venv/bin/python -m pytest tests/ -q` → **206 passed** (204 pre-existing +
2 new), 0 failures.

## 4. Regression measurement methodology

Re-ran Candidate B's real measurement pipeline
(`orchestration/candidate_b_native_tools.py`, now built on the fixed
`orchestration/models.py`) against the exact same 59
`development`+`validation` cases of
`artifacts/v2/phase3_benchmark_manifest.json` used for the original
measurement (`artifacts/v2/phase3_candidate_b_results.json`,
`docs/v2/PHASE3_CANDIDATE_B_MEASUREMENT.md`). Same methodology: one real,
un-retried Cerebras `qwen-3.8-27b` Chat Completions call per case
(`tools`/`tool_choice="auto"`/`parallel_tool_calls=true`, raw
`original_query` text), every returned `tool_call` run through
`parse_and_validate_tool_call()`, every `registry_valid` call either
executed for real against PubMed/ClinicalTrials.gov/ChEMBL or, for the 4
manifest cases with `failure_injection.simulate_live_call == false`
(`FL-005` pubmed timeout, `FL-006` clinical_trials 429, `FL-007` chembl
5xx, `FL-008` chembl empty-result), recorded as a synthetic
execution — no live HTTP request for those, matching the original run.
`phase3_heldout` (15 cases) and `artifacts/v2/phase3_heldout_results.json`
were **not touched**.

Full per-case output:
`artifacts/v2/phase3_candidate_b_regression_after_fix.json`.

## 5. Results — before (config v1) vs. after (config v2 fix)

| Metric | Before (`phase3_candidate_b_results.json`) | After (this run) |
|---|---|---|
| `schema_valid_rate` | 0.9140 (85/93) | **1.0000** (93/93) |
| `schema_invalid_count` | 8 | **0** |
| — of which clinical_trials phase/status format mismatches | 8 / 8 | **0** |
| `clinical_trials` required-source miss rate (dev+validation) | 0.0 | 0.0 (unchanged) |
| `pubmed` required-source miss rate (dev+validation) | 0.0417 (1/24, `PM-012`) | 0.0417 (1/24, `PM-012`, unchanged — model returned zero tool_calls after a long free-text answer that hit `max_completion_tokens`; unrelated to this fix) |
| `chembl` required-source miss rate (dev+validation) | 0.0 | 0.0 (unchanged) |
| Cerebras cost | $0.091977 | $0.095467 |

**Every one of the original run's 8 `schema_invalid` failures was a
clinical_trials `phase`/`status` value the model got wrong in exactly the
way the defect predicts** (`"3"`, `"Phase 1"`, `"2"`, `"Phase 3"`, `"1"`
(x2), `"FULLY_ENROLLED"`, `"2.5"` — cases CT-001, CT-003, CT-005, CT-011,
CT-012 (x2), FL-001, FL-002). With the `enum` now present in the tool
declaration, **all 93 tool calls the model returned across all 59 cases
had valid, schema-passing arguments on the first attempt** — 0 schema
failures of any kind, not just clinical_trials ones.

**Yes — the enum constraint measurably improved the model's own
phase/status value generation.** `clinical_trials`-specific schema-invalid
count went from 8 to 0 on this split. `clinical_trials`'s own
required-source miss rate was already 0.0 on `development`+`validation` in
the original run (the miss that triggered this fix, `CT-008`, was specific
to `phase3_heldout` and is not in this split), so this run cannot show a
`clinical_trials`-miss-rate improvement on dev+validation — it confirms
instead that the mechanism the held-out miss depended on (an ungrounded
phase/status guess reaching schema rejection) no longer occurs on this
split, which is the regression check this step was scoped to.

## 6. Cost

**$0.095467** measured Cerebras spend for this regression run (67 real
Chat Completions calls' worth of tokens across 59 cases plus the token
overhead of the now-larger enum-carrying schema) — comparable to the
original run's $0.091977, both trivially small against Phase 3's Candidate
B $0.50 measurement cap. Auto-recharge and billing settings were not
touched.

## 7. What this does and does not establish

This run confirms **no regression** from the fix on the two already-spent,
non-blind splits, and that the specific failure mode (schema-invalid
clinical_trials phase/status) that caused `CT-008`'s miss is gone on this
split. Per directive Step 33, it does **not** and cannot stand in for a
genuine held-out check — `phase3_heldout` stays spent and untouched, and
Phase 3 remains **OPEN** until a fresh held-out supplement (new cases,
focused on ClinicalTrials phase/status coverage) is authored and run once,
per `docs/v2/PHASE3_STATUS.md`.

`artifacts/v2/phase3_frozen_config.json` was updated to `config_version: 2`
with a `config_version_history` entry describing this fix (freeze-tracking
metadata, not benchmark data — permitted to edit per the governing
directive).
