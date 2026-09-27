# ChEMBL Fuzzy-Match Threshold Fix: Held-Out Supplement Results

Status: **CONFIRMED** -- the fix generalizes. This closes step 3 ("build a
small, genuinely new held-out supplement... for one honest blind check") of
the fix path declared in `docs/v2/PHASE4_STATUS.md`. Step 4 (refreeze as
config v2, formally close Phase 4) is a separate follow-on action, not done
here.

## What this is

`docs/v2/PHASE4_STATUS.md` declared Phase 4 OPEN because the spent
`phase4_heldout` blind run found that `ChEMBLTool.resolve_compound_name()`'s
fuzzy-match tier had no similarity threshold, so a completely fabricated
compound name (`"Zorblatinix-9X"`) returned a confident-looking `success:
True` / `match_type: "fuzzy"` result with a real (but unrelated) ChEMBL ID.
`docs/v2/CHEMBL_FUZZY_MATCH_THRESHOLD_FIX.md` fixed the root cause (a
`difflib`-based name-similarity gate, `FUZZY_MATCH_MIN_SIMILARITY = 0.6`) and
re-verified it against the already-spent `development`+`validation` splits,
but explicitly could not use the single `Zorblatinix-9X` example -- or the
spent `phase4_heldout` split -- as blind evidence that the fix generalizes.

This document records that missing evidence: a brand-new 10-case supplement,
authored to target the fuzzy-match confidence boundary specifically, run
blind exactly once against the fixed tool with real live ChEMBL API calls
(no mocking), with nothing tuned afterward regardless of outcome.

## Independence from spent artifacts

Checked directly against `artifacts/v2/phase4_benchmark_manifest.json`
before authoring any case: none of this supplement's compound-name strings
overlap the 12 `phase4_heldout`-split query strings (including
`Zorblatinix-9X`, `ZZZNOTADRUGNAME123`, `xyzxyzqqnonexistentdrugname12345`).
They were also deliberately kept distinct from the fix doc's own calibration
examples (`Zorblatinix-9X`, `Fake Compound XYZ123`, `asprin`, `Amoxicilin`,
`Keytruda`, `Ketruda`, `Osimertinibb`, `Ibuprofin`, `Paracetmol`,
`Tagrisso`), even though those aren't formally "spent," to keep this
evidence unambiguously independent of anything seen while building the fix
itself. Full detail and the exact excluded-string list: see
`not_reused_from` in `artifacts/v2/phase4_chembl_fuzzy_threshold_supplement.json`.

## Case set (10 cases)

Gold `chembl_id`/`preferred_name` for every real-drug case was established
by a live call to `resolve_compound_name()` against the drug's *correctly
spelled* canonical name before its typo/brand/punctuation variant was chosen
for the set -- never a guessed ID, same discipline as the original
benchmark's `gold_label_process`.

| case_id | category | query | gold match_type | gold chembl_id |
|---|---|---|---|---|
| SUPP-FAB-01 | fabricated_name (invented syllables) | `Velbotracine` | no_match | None |
| SUPP-FAB-02 | fabricated_name (brand-style fake word) | `Nuravex-XR` | no_match | None |
| SUPP-FAB-03 | fabricated_name (fake chemical-ish) | `Trimoxaphenidol` | no_match | None |
| SUPP-FAB-04 | fabricated_name (invented + alnum suffix) | `Quindarolix-B7` | no_match | None |
| SUPP-NEARMISS-01 | genuine near-miss typo | `Sertralin` (sertraline) | fuzzy | CHEMBL809 |
| SUPP-NEARMISS-02 | genuine near-miss typo | `Metoprolo` (metoprolol) | fuzzy | CHEMBL13 |
| SUPP-NEARMISS-03 | genuine near-miss typo | `Duloxetin` (duloxetine) | fuzzy | CHEMBL1200328 |
| SUPP-SYN-01 | synonym/brand name | `Ozempic` (semaglutide) | exact_synonym | CHEMBL2108724 |
| SUPP-SYN-02 | synonym/brand name | `Eliquis` (apixaban) | exact_synonym | CHEMBL231779 |
| SUPP-NORM-01 | capitalization/punctuation | `Atorvastatin.` (trailing period) | fuzzy | CHEMBL1487 |

Note on SUPP-NEARMISS-03: `Duloxetin` resolves via the fuzzy tier to
`CHEMBL1200328` (DULOXETINE HYDROCHLORIDE, the salt form) rather than the
base compound's own exact-match ID (`CHEMBL1175`, from `duloxetine`) --
still a genuine, directly name-related real record, not a fabricated or
unrelated one, so it is scored correct against that gold.

Note on SUPP-NORM-01: a trailing period breaks the `pref_name__iexact` exact
match, routing `Atorvastatin.` through the fuzzy tier -- this case exercises
input normalization and the new similarity gate together, not normalization
alone.

## Blind run

Executed once, live, no mocking:

```
venv/bin/python .../run_supplement.py
```

against `ChEMBLTool().resolve_compound_name()` as it exists now (with the
0.6 similarity gate in place). Full request/response detail for all 10
cases -- including every candidate list ChEMBL returned -- is recorded
verbatim in `artifacts/v2/phase4_chembl_fuzzy_threshold_supplement.json`
under `official_blind_run`. No case was re-run, and no code was touched
between designing the case set and recording this run.

## Results

| Metric | Result |
|---|---|
| Fabricated-name correct-rejection rate | **4/4 (100%)** |
| Genuine-near-miss correct-resolution rate | **3/3 (100%)** |
| Synonym-tier correct-resolution rate | **2/2 (100%)** |
| Capitalization/punctuation correct rate | **1/1 (100%)** |
| **Overall** | **10/10 (100%)** |
| Misleading fabricated-name IDs returned (the exact defect class) | **0** |

All 4 fabricated names (`Velbotracine`, `Nuravex-XR`, `Trimoxaphenidol`,
`Quindarolix-B7` -- four different invented styles: plain invented
syllables, a brand-style coined word, a chemical-ish-sounding coinage, and
an invented word with an alphanumeric suffix) returned `match_type:
"no_match"` and `chembl_id: None`. None returned a real-but-unrelated ID --
zero recurrences of the defect that opened Phase 4.

All 3 genuine near-miss typos of real drugs (`Sertralin`, `Metoprolo`,
`Duloxetin`) still correctly resolved through the fuzzy tier to the correct
real ChEMBL ID, confirming the 0.6 threshold does not reject legitimate
near-misses.

Both brand-name/synonym cases (`Ozempic` -> semaglutide, `Eliquis` ->
apixaban) resolved via `exact_synonym` exactly as before -- the threshold
fix (which only touches the fuzzy tier) did not regress the synonym tier.

The capitalization/punctuation case (`Atorvastatin.`) correctly resolved via
the fuzzy tier to `CHEMBL1487` / ATORVASTATIN, confirming normalization
still functions correctly alongside the new gate.

## Conclusion

**This supplement confirms the fix generalizes.** Zero fabricated/misleading
ChEMBL IDs were produced across every fabricated-name case in this fresh,
independently-verified, single blind run, while every genuine near-miss
typo and every genuine synonym/brand name still resolved correctly. This is
one honest blind check (10 new cases, none reused from spent artifacts) and
does not prove the gate is flawless against every conceivable adversarial
string, but it directly re-tests the exact defect class that opened Phase 4
and finds no recurrence.

Per `docs/v2/PHASE4_STATUS.md`'s decided path, this clears step 3. Step 4
(refreeze as config v2, formally close Phase 4) is left as a separate,
explicit follow-on action -- not performed as part of this task.

## Regression check

`venv/bin/python -m pytest tests/ -q`: **267 passed, 7 skipped**, 0 failed
-- unchanged from `docs/v2/CHEMBL_FUZZY_MATCH_THRESHOLD_FIX.md`'s reported
result. No source file was modified while producing this supplement
(`tools/chembl_tool.py` untouched); only new, additive artifacts were
created: `artifacts/v2/phase4_chembl_fuzzy_threshold_supplement.json` and
this document.
