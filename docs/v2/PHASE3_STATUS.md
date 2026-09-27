# Phase 3 Status: COMPLETE

**Superseded by `docs/v2/PHASE3_FINAL_GATE_AUDIT.md`.** The 3-step path
below was completed in full: defect fixed (config v2), regression-verified,
and reconfirmed via a fresh 12-case held-out supplement (0/12 misses, all 7
safety gates pass) that never reused the spent original held-out split.
Phase 3 is now integrated into `agent/nodes.py`/`agent/graph.py`, the full
206-test suite passes, and the metrics ledger has been updated. This
document is kept for the historical record of why Phase 3 did not close on
the first held-out attempt.

---

## Original status when this document was written: OPEN

**Declared OPEN, not COMPLETE**, as of the `phase3_heldout` run
(`artifacts/v2/phase3_heldout_results.json`, `docs/v2/PHASE3_HELDOUT_RESULTS.md`).

## Why

The frozen Candidate B architecture (config v1,
`artifacts/v2/phase3_frozen_config.json`) passed all 7 hard safety gates on
the held-out split, but missed one required source
(`clinical_trials`, case `CT-008`, 1 of 4 held-out cases requiring it)
because the model emitted a non-canonical trial-phase value (`"Phase 4"`)
that our schema correctly rejected but had no fallback for. Root cause:
`orchestration/models.py`'s `ClinicalTrialsSearchArgs.phase`/`status`
fields are typed `Optional[str]` with a custom validator, not
`Literal`/`Enum` — so the JSON schema handed to Cerebras via
`.model_json_schema()` never told the model which phase/status values are
actually valid, and it guessed.

Per this project's standing rule ("a phase may NOT close with known
avoidable in-scope debt") and directive Step 33 ("if a serious defect
appears: Phase 3 remains OPEN... do not conceal it, do not move to Phase
4"), Phase 3 is declared OPEN pending this fix.

## Constraint on the fix path

Directive Step 33 also forbids tuning based on held-out results and
re-running the same held-out set — doing so would invalidate it as a blind
check. The already-spent `phase3_heldout` (15 cases) cannot be reused to
validate this fix.

## Decided path (human-directed, 2026-09-24)

1. Fix the enum-constraint gap in `orchestration/models.py` (config v2).
2. Re-verify no regression against the already-spent `development`+
   `validation` splits (permitted — those are not the blind check).
3. Author a small, genuinely new held-out supplement (fresh cases, not
   reusing the spent 15), focused on ClinicalTrials phase/status coverage,
   for one honest blind check of the fix.
4. Only if that passes: refreeze as config v2, formally close Phase 3.

This document will be updated (or superseded by a
`PHASE3_FINAL_GATE_AUDIT.md` declaring COMPLETE) once that sequence
finishes.
