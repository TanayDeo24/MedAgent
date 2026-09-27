# ClinicalTrials.gov Phase-Filter Defect: Root Cause and Fix

## Background

While re-verifying Phase 3 supplement work, a serious production defect was
found in `tools/clinical_trials_tool.py`'s `search_trials()` method: every
phase-filtered ClinicalTrials.gov search was silently broken. This document
records the independent verification, the root cause, and the fix.

**Why this matters for prior results:** the earlier held-out supplement
measurement recorded in `artifacts/v2/phase3_heldout_supplement_results.json`
(see `docs/v2/PHASE3_HELDOUT_SUPPLEMENT_RESULTS.md`) logged a "success" for
every phase-filtered ClinicalTrials call in that run. That "success" status
was false: those calls were in fact returning HTTP 400 errors, not real
study data (see below). This document and its accompanying fix are the
direct result of finding and correcting that discrepancy. This is noted
here as confirmation of an already-established finding; it was not
re-investigated as part of this fix.

## The Defect

`search_trials()` sent trial-phase filters to the ClinicalTrials.gov v2 API
using a `filter.phase=<value>` query parameter (around the old line 257:
`query_params["filter.phase"] = phase if phase else None`). This parameter
does not exist in the real v2 API. Every phase-filtered call returned an
immediate HTTP 400 error, regardless of the phase value supplied, while the
rest of the query (condition, intervention, status, etc.) was well-formed
and would otherwise have succeeded.

### Direct verification (before the fix)

```
$ curl -s "https://clinicaltrials.gov/api/v2/studies?query.cond=cancer&filter.phase=PHASE3&pageSize=1"
`filter.phase` is unknown parameter
```

### Verification of the correct approach

```
$ curl -s "https://clinicaltrials.gov/api/v2/studies?query.term=AREA%5BPhase%5DPHASE2&pageSize=1"
{"studies":[{"protocolSection":{"identificationModule":{"nctId":"NCT00354276", ... }}}]}
```

Real study JSON is returned when the phase constraint is expressed as an
`AREA[Phase]<value>` term inside `query.term`, instead of as a `filter.phase`
query parameter.

`filter.overallStatus` (used for the `status` argument) IS a valid v2 API
parameter and was not affected by this defect — only `filter.phase` was
broken.

## Root Cause

`search_trials()` already built its `query.term` using an `AREA[...]` term
syntax for `condition`, `intervention`, `sponsor`, and `country`, joined
with `AND`. Phase, however, was handled separately: it was added to a
`filters` list alongside `status` and then written out as a *pair* of query
parameters, `filter.overallStatus` and `filter.phase`. `filter.overallStatus`
happens to be a real v2 API parameter, so status filtering worked. There is
no equivalent `filter.phase` parameter in the v2 API — phase can only be
expressed as a search term (`AREA[Phase]<value>`), which the pre-fix code
never did.

## The Fix

`tools/clinical_trials_tool.py`, `search_trials()`:

- Phase is now folded into the existing `query_parts` list (the same list
  used for condition/intervention/sponsor/country) as
  `AREA[Phase]<value>`, joined with the other terms via the existing
  `" AND ".join(query_parts)` logic — no special-casing, it follows the
  established pattern exactly.
- `query_params["filter.phase"]` is removed entirely; that query parameter
  is never sent again.
- `status` continues to be sent via `filter.overallStatus`, unchanged in
  behavior.

Diff:

```diff
--- a/tools/clinical_trials_tool.py
+++ b/tools/clinical_trials_tool.py
@@ -236,6 +236,13 @@ class ClinicalTrialsTool(BaseTool):
             query_parts.append(f"AREA[LeadSponsorName]{sponsor}")
         if country:
             query_parts.append(f"AREA[LocationCountry]{country}")
+        if phase and phase in self.VALID_PHASES:
+            # NOTE: ClinicalTrials.gov v2 API has no `filter.phase` query
+            # parameter (it returns HTTP 400 "`filter.phase` is unknown
+            # parameter"). Phase filtering must be expressed as an
+            # AREA[Phase]<value> term inside query.term, following the same
+            # pattern as condition/intervention/sponsor/country above.
+            query_parts.append(f"AREA[Phase]{phase}")
 
         query = " AND ".join(query_parts) if query_parts else "AREA[StudyType]INTERVENTIONAL"
 
@@ -244,17 +251,9 @@ class ClinicalTrialsTool(BaseTool):
             "query.term": query,
         }
 
-        # Add filters
-        filters = []
+        # Add status filter (filter.overallStatus is a valid v2 API parameter)
         if status and status in self.VALID_STATUSES:
-            filters.append(f"overallStatus:{status}")
-
-        if phase and phase in self.VALID_PHASES:
-            filters.append(f"phase:{phase}")
-
-        if filters:
-            query_params["filter.overallStatus"] = status if status else None
-            query_params["filter.phase"] = phase if phase else None
+            query_params["filter.overallStatus"] = status
 
         # Remove None values
         query_params = {k: v for k, v in query_params.items() if v is not None}
```

## Cross-Codebase Check

Searched `orchestration/`, `agent/`, and `tools/` for any other place that
independently constructs a `filter.phase`-style parameter for
ClinicalTrials.gov:

```
grep -rn "filter\.phase" orchestration agent tools
```

The only matches after the fix are the explanatory comment inside
`tools/clinical_trials_tool.py` itself. `orchestration/query_compilers.py`
(the Candidate-C compiler) does set a `phase` value
(`kwargs["phase"] = raw_phase`, from `query.constraints.trial_phases`
filtered against `VALID_TRIAL_PHASES`), but it does so only as a keyword
argument passed through to `ClinicalTrialsSearchArgs` / `search_trials()`.
It does not build its own `filter.phase` query parameter or HTTP request,
so it required no separate fix — it is corrected automatically by the fix
to `search_trials()`.

No second occurrence of the defect was found.

## Verification After the Fix

### Live re-test (real network call through the fixed tool code)

```
$ venv/bin/python -c "
from tools.clinical_trials_tool import ClinicalTrialsTool
tool = ClinicalTrialsTool()
result = tool.search_trials(condition='lung cancer', phase='PHASE3', status='RECRUITING', max_results=3)
print('success:', result.success)
"
success: True
num studies: 3
 - NCT07182682 A Phase 3, Double-Blind, Randomized, Placebo-Controlled, Mul... PHASE3
 - NCT06646276 A Randomized, Double Blind, Multicenter Phase 3 Trial of BMS... PHASE3
 - NCT05085028 A Randomised Open-label Phase III Trial of REduced Frequency... PHASE3
```

The same phase-filtered search that previously would have returned an HTTP
400 now returns a 200 with real, correctly-phased study data.

### Unit tests

`tests/test_clinical_trials.py` gained three regression tests in
`TestClinicalTrialsFiltering`:

- `test_phase_filter_uses_area_term_not_filter_phase` — asserts the built
  query params never contain `filter.phase`, that `query.term` contains
  `AREA[Phase]PHASE3` ANDed with the condition term, and that
  `filter.overallStatus` is still sent correctly.
- `test_phase_only_filter_query_term` — asserts a phase-only search (no
  condition/intervention/status) produces `query.term == "AREA[Phase]PHASE2"`
  with no `filter.phase` and no `filter.overallStatus`.
- `test_invalid_phase_omitted_from_query` — asserts an invalid phase value
  is omitted from the query entirely rather than being sent as
  `filter.phase`.

These mock the HTTP layer (`_search_trials_page`) exactly as the existing
test suite does; no real network calls are made in the pytest suite. The
one real network check is the standalone live re-test above, run manually
and reported here rather than added as a network-dependent pytest test.

Full suite result: `venv/bin/python -m pytest tests/ -q`

- Before: 206 passed
- After: 209 passed (3 new tests), 0 failures
