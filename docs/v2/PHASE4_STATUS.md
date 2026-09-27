# Phase 4 Status: COMPLETE

**Superseded by `docs/v2/PHASE4_FINAL_GATE_AUDIT.md`.** All gates pass,
LangGraph integration verified via real live end-to-end testing (zero code
changes needed), full test suite green (267 passed, 7 skipped, 0 failed),
metrics ledger updated. Kept for the historical record of the mid-phase
held-out-discovered defect and fix cycle below.

---

## Prior status: DEFECT RESOLVED — proceeding to integration/final gate audit

**Update (2026-09-25):** The 3-step path below is complete: the fuzzy-match
threshold defect was fixed, regression-verified against dev+validation
(0 regressions, ChEMBL Recall@10 still 1.0), and confirmed via a fresh
10-case held-out supplement never reused from the spent original 12-case
`phase4_heldout` split (10/10 correct: 4/4 fabricated names rejected, 3/3
near-misses still resolve, 2/2 synonym sanity checks unaffected, zero
misleading IDs). Refrozen as `artifacts/v2/phase4_frozen_config.json`
config_version 2. Proceeding to LangGraph integration, live end-to-end
check, full test suite, metrics ledger update, and final gate audit before
Phase 4 can be declared COMPLETE.

---

## Original status when this document was written: OPEN

**Declared OPEN, not COMPLETE**, as of the `phase4_heldout` run
(`artifacts/v2/phase4_heldout_results.json`, `docs/v2/PHASE4_HELDOUT_RESULTS.md`).

## Why

The frozen ChEMBL architecture (config v1, `artifacts/v2/phase4_frozen_config.json`)
passed all 7 hard safety gates on the held-out split, but the blind run
surfaced a real, previously-unmeasured correctness defect in
`resolve_compound_name`'s fuzzy-match fallback: a completely fabricated
compound name (`"Zorblatinix-9X"`) returns `success: True` with a real (not
fabricated) but unrelated `chembl_id`, `match_type: "fuzzy"`, and no
populated `matched_name`/`preferred_name` — independently reproduced
outside the held-out harness. This does not violate the literal
"0 fabricated source identifiers" hard gate (the ID itself is real), but it
is a genuine correctness/safety defect: a caller has no signal that the
match is unreliable, and could present a fabricated drug as having a real,
verified ChEMBL identity.

This is a defect in a capability Phase 4 itself introduced this session
(not a legacy carryover), discovered specifically because of a benchmark
category (fabricated/absent compound names) that happened to land entirely
in the held-out split. Per the project's standing rule ("a phase may NOT
close with known avoidable in-scope debt") and the Phase-3 precedent for
exactly this situation, Phase 4 is declared OPEN pending a fix.

## Constraint on the fix path

Same as Phase 3: the spent `phase4_heldout` (12 cases) cannot be reused as
blind evidence that a fix works.

## Decided path

1. Fix the root cause: add a similarity/confidence threshold to
   `resolve_compound_name`'s fuzzy-match fallback so a low-confidence match
   is reported as `no_match` or an explicit low-confidence category, not
   presented identically to a genuine match.
2. Re-verify against the already-spent `development`+`validation` splits
   (permitted — not the blind check).
3. Build a small, genuinely new held-out supplement (fabricated/absent
   compound names, not reusing the 12 spent held-out cases) for one honest
   blind check.
4. Only if that passes: refreeze as config v2, formally close Phase 4.

The separate PubMed "no relevance floor" finding (RAG always returns k=10
regardless of true relevance) is recorded as an **accepted limitation, not
a blocker**: it is pre-existing production behavior Phase 4 did not
introduce, violates no predeclared hard gate, and is a broader
retrieval-architecture question (whether/how to add a relevance threshold)
better scoped as its own future decision than patched reflexively here.
