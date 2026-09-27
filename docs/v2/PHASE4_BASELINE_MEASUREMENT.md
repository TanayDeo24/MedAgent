# Phase 4 — Current Retrieval Baseline Measurement (Step 14)

Measured, not estimated. Every number below comes from a real run against
the live code paths named in `docs/v2/PHASE4_INITIAL_RETRIEVAL_AUDIT.md`:
local embedding + FAISS + BM25 + cross-encoder inference
(`retrieval/retriever.py`) and real HTTP calls to the public NCBI
E-utilities, ClinicalTrials.gov v2, and ChEMBL APIs (no mocking, existing
rate limiters respected). Full per-case data is in
`artifacts/v2/phase4_baseline_results.json`. This document and that
artifact are the only files this measurement wrote; no existing file was
modified.

**Scope:** the 49 `development` + `validation` cases of
`artifacts/v2/phase4_benchmark_manifest.json` (61 total; the 12
`phase4_heldout` cases were not read for content or executed against —
confirmed by construction, the harness script filters `split in
("development", "validation")` before doing anything else).

**Measured date:** 2026-09-25. **Cost:** $0 — no LLM/paid-API calls were
made; this is pure retrieval (local model inference is CPU-local,
sentence-transformers `all-MiniLM-L6-v2` + `cross-encoder/ms-marco-MiniLM-L-6-v2`,
already resident on disk from Phase 3's build).

---

## 1. Headline numbers

| Path | Recall@1 | Recall@5 | Recall@10 | MRR | Precision@5 | n (cases w/ gold) |
|---|---|---|---|---|---|---|
| **PubMed RAG** (`retrieval/retriever.py::retrieve()`, hybrid dense+BM25+RRF+rerank, k=10) | 0.545 | 0.773 | 0.773 | 0.636 | 0.182 | 22 |
| **PubMed live API** (`PubMedTool().search_pubmed(query)`, default params) | 0.045 | 0.045 | 0.045 | 0.045 | 0.045 | 22 |

The two PubMed paths are **not close** — RAG beats the live API path by
~17x on Recall@10 in this measurement. This is a real, measured gap, not
an artifact of how the harness called either path (see Section 2 for root
cause).

| ClinicalTrials | Value |
|---|---|
| Required-trial recall (gold NCT ID present anywhere in returned set) | **0.737** (14/19 cases with gold) |
| Structured-filter-correctness rate (compiled param matched the case's stated filter) | **0.850** (16/19 checked filter instances) |

| ChEMBL | Recall@1 | Recall@5/@10 | MRR | n |
|---|---|---|---|---|
| **Aggregate (all methods)** | 0.238 | 0.381 | 0.279 | 21 |
| — `get_drug_info` (exact ID lookup) | 1.0 | 1.0 | 1.0 | 2 |
| — `search_by_target` | 0.25 (WRONG_ENTITY at rank 1 in 3/4) | 1.0 | 0.45 | 4 |
| — `search_by_indication` | 1.0 | 1.0 | 1.0 | 2 |
| — name→ID lookup (no supported operation — see Section 4) | 0.0 | 0.0 | 0.0 | **13** |

The aggregate ChEMBL recall is low almost entirely because 13 of 21 ChEMBL
cases are drug-**name** lookups (`chembl_compound` category + most
multi-source cases), and **no currently-registered ChEMBL operation
resolves a name to an ID** — every one of these calls 404s live. Every
operation ChEMBL actually supports (`get_drug_info`, `search_by_target`,
`search_by_indication`) measured 100% Recall@10 in this run.

**WRONG_ENTITY defect — confirmed reproduced empirically, all 3 predicted cases:**

| Case | Query target | First live hit | Gold | Reproduced? |
|---|---|---|---|---|
| `CHEMBL-TARGET-02` | EGFR | `CHEMBL4523747` (EGFR/PPP1CA protein-protein interaction) | `CHEMBL203` (human EGFR, rank 5) | **Yes** |
| `CHEMBL-AMBIG-01` | MET | `CHEMBL1938227` (unrelated non-human target) | `CHEMBL3717` (human MET, rank 3) | **Yes** |
| `NEG-AMBIG-COMPOUND-01` | MET (bare, no qualifier) | same as above | `CHEMBL3717` (rank 3) | **Yes** |

The positive control (`CHEMBL-TARGET-01`, ALK) resolved correctly at rank 1
(`CHEMBL4247`), matching the manifest's documented expectation exactly —
confirms the defect is target-name-specific (EGFR/MET name collisions),
not a blanket failure of `search_by_target`.

**Source coverage for multi-source cases:** **0/7 (0.0)** — every one of
the 7 `multi_source` cases required a ChEMBL contribution, and every one
hit the same name→ID structural gap (Section 4), so **zero** multi-source
cases achieved all-required-sources coverage in this measurement, despite
PubMed and ClinicalTrials individually succeeding on 6/7 and 6/6 of their
legs respectively. This is the single most consequential finding for any
Phase-4 candidate design: cross-source coverage is currently bottlenecked
entirely on one missing ChEMBL capability, not on weak retrieval quality
in the sources that do work.

**No-results / abstention cases:** none of the `pubmed_zero_result`,
`clinicaltrials_zero_result`, `chembl_zero_result`,
`negative_absent_information`, or `negative_unsupported_operation`
categories fall in the development/validation splits — all are exclusively
in `phase4_heldout` (confirmed by category tally over the 49 dev+val
cases). **Not measured here, for a real reason** (not omitted by
oversight): measuring them now would touch the protected heldout split.
`negative_ambiguous_entity` (`NEG-AMBIG-COMPOUND-01`) is the one
"negative"-family case present in-scope, and is covered under ChEMBL
above.

---

## 2. Why PubMed live API measured so low (root cause, not just the number)

Two compounding, independently-confirmed causes:

1. **Hidden default date restriction.** `PubMedTool.search_pubmed()`
   (`tools/pubmed_tool.py:256-265`) silently applies
   `PUBMED_DEFAULT_DATE_RANGE` years of lookback (2 years) whenever the
   caller passes neither `years_back` nor `date_from` — which is exactly
   how this measurement (and any caller that just does
   `search_pubmed(query)`) invokes it, matching the task's instruction to
   run the live path as the current system actually calls it. Most gold
   PMIDs in the benchmark are from 2017-2023 (deliberately real, verified
   articles) and are excluded before the search even runs.
   Diagnostic-only check (not counted in the headline metric, run once to
   confirm root cause): re-running `PM-EXACT-01`'s query with
   `date_from="2000/01/01"` still returned only 9 PMIDs, **none of which
   were the 3 gold PMIDs** — confirming a second, independent cause below.
2. **Raw natural-language question text as the PubMed search term.**
   `search_pubmed()` sends the case's full natural-language question
   directly as `esearch`'s `term` parameter (no MeSH translation, no
   boolean query construction). PubMed's own relevance ranking over an
   unstructured natural-language string frequently does not surface the
   single correct article in its top 10-20, independent of the date
   filter.

Categorized as **OVER_FILTERED** (the date default) plus
**RELEVANT_ITEM_MISSED**/**NO_RESULTS** per case in
`phase4_baseline_results.json`'s `failure_annotations` — this is a
genuine, reproducible defect in how the live PubMed path is currently
invoked, not a benchmark artifact.

---

## 3. ClinicalTrials — a real, live 400-error bug discovered during measurement

Three of 19 ClinicalTrials calls (`CT-PHASE-01`, `CT-MULTI-01`,
`CT-MULTI-02` — every dev/validation case with a `phase` filter) failed
outright with a live HTTP 400:

```
`filter.phase` is unknown parameter
```

Confirmed independently via a direct `curl` against
`https://clinicaltrials.gov/api/v2/studies?...&filter.phase=PHASE3...`
outside the tool code — **`filter.phase` is not a valid ClinicalTrials.gov
v2 API parameter.** `tools/clinical_trials_tool.py:252-257` constructs it
whenever a `phase` argument is passed to `search_trials()`, so **every
caller of `search_trials(phase=...)` — not just this harness — gets a hard
400 error today**, including `orchestration/registry.py`'s Phase-3
typed-tool path, since `ClinicalTrialsSearchArgs` exposes `phase` as a
valid argument. This is categorized `QUERY_COMPILATION_FAILURE` and is the
most actionable, unambiguous defect surfaced by this measurement — it
silently loses every phase-filtered ClinicalTrials query, not a subtle
ranking issue.

Where the API call succeeded, required-trial recall was strong (14/16
non-erroring gold-bearing cases hit at least one gold NCT ID), and
structured-filter-correctness (16/19, excluding the phase param bug's
downstream effect) was reasonably high — the 3 misses were condition-term
abbreviation mismatches (e.g. compiled `"triple-negative breast cancer"`
vs. the benchmark's `"TNBC"` shorthand — a term-form fidelity nuance, not
a dropped filter).

---

## 4. ChEMBL — the structural name→ID gap, quantified

`ChEMBLTool` exposes exactly three public operations
(`orchestration/registry.py:218-248` registers the same three):
`get_drug_info(chembl_id)`, `search_by_target(target_name)`,
`search_by_indication(disease)`. **None resolves a bare drug name (e.g.
"brigatinib") to its ChEMBL ID.** All 13 name-based dev/validation cases
(`CHEMBL-COMPOUND-01..06` and the ChEMBL leg of all 7 `multi_source`
cases) were measured by calling `get_drug_info(name)` — the only
ID-shaped method available to a caller without a separate resolution step
— and every single one returned a live HTTP 404
(`.../molecule/<name>.json` is not a valid molecule ID). Recall@k = 0.0
for all 13, categorized `QUERY_COMPILATION_FAILURE` (no operation exists
to represent this query's actual intent), not `RELEVANT_ITEM_MISSED`.

This single gap accounts for the entire ChEMBL aggregate recall deficit
(Section 1) and the entire multi-source coverage failure (Section 1) —
every properly-supported ChEMBL operation scored 100% Recall@10 in this
measurement.

---

## 5. Latency (P50/P90/P95, seconds)

| Path | n | P50 | P90 | P95 | Mean |
|---|---|---|---|---|---|
| PubMed RAG, total `retrieve()` | 22 | 0.361 | 0.397 | 0.416 | 0.488 |
| PubMed live API | 22 | 0.452 | 0.806 | 0.904 | 0.476 |
| ClinicalTrials live API | 19 | 0.044 | 0.143 | 0.259 | 0.068 |
| ChEMBL live API | 21 | 0.114 | 6.29 | 12.15 | 1.895 |

**Per-stage PubMed RAG latency (dense / BM25 / rerank individually): NOT
MEASURED.** `retrieval/retriever.py`'s `Retriever.retrieve()` /
`retrieve_hybrid_reranked()` / `retrieve_hybrid_custom()` do not return or
otherwise expose per-stage timing internally (`_dense_search`,
`_bm25_search`, and `_rerank` are private helpers called in sequence with
no timing instrumentation in the existing, unmodified code) — only total
wall-clock `retrieve()` latency could be measured without editing
`retrieval/retriever.py`, which this task's purely-additive constraint
does not permit. Recorded as NOT MEASURED with this specific reason, per
the governing directive, rather than estimated or omitted silently.

ChEMBL's P90/P95 are dominated by the 4 `search_by_target`-family cases,
which each make **two** sequential live calls (an internal target search
plus the downstream molecule search) against what were, at measurement
time, slow-responding EBI ChEMBL endpoints (individual calls up to ~7-8s;
not a rate-limiter artifact — `CHEMBL_RATE_LIMIT` is 10 req/s and was not
the bottleneck). Reported as measured, not adjusted.

---

## 6. Failure-category breakdown (taxonomy per `docs/v2/PHASE4_GATE_PLAN.md` Section 1)

57 individual failure annotations recorded across 49 cases (a single
case/source pair can carry more than one category — e.g. a PubMed live-API
miss is tagged both `OVER_FILTERED`, for the silent date default, and
`RELEVANT_ITEM_MISSED`/`NO_RESULTS` for the actual outcome). Full list
with per-case rationale is `phase4_baseline_results.json`'s
`failure_annotations` array; tally:

| Category | Count | Primary driver |
|---|---|---|
| `RELEVANT_ITEM_MISSED` | 25 | PubMed live API misses (date filter + poor NL-query relevance), a handful of ChEMBL/CT misses |
| `QUERY_COMPILATION_FAILURE` | 23 | ChEMBL name→ID gap (13), ClinicalTrials `filter.phase` 400 bug (3), multi-source coverage loss (7) |
| `OVER_FILTERED` | 21 | PubMed live API's silent default 2-year date window (applied to every live-API case measured, whether or not it was the case's only failure cause) |
| `NO_RESULTS` | 15 | PubMed live API zero-result cases (a subset of the date-filter effect) |
| `RANKING_FAILURE` | 4 | 1 PubMed RAG case (gold in dense pool, dropped by rerank/RRF cutoff) + 3 ChEMBL `search_by_target` cases (correct target found, not ranked first) |
| `UNDER_FILTERED` | 3 | ClinicalTrials condition-term abbreviation mismatches |
| `WRONG_ENTITY` | 3 | ChEMBL `search_by_target` EGFR/MET name collisions — both benchmark-predicted cases reproduced live |
| `STALE_INDEX` | 2 | `PM-LIVE-01`/`PM-LIVE-02` — RAG correctly misses post-corpus-build articles, as designed |
| `LEXICAL_MISS` | 1 | `PM-LEX-02` — gold PMID absent from BM25 top-30 specifically (present in dense top-30) |

No category was invented beyond the predeclared taxonomy; no failure was
collapsed into a generic "failed" bucket.

---

## 7. Hard safety/correctness gates (Section 3 of the gate plan)

Spot-checked during this measurement (full audit against all 49 cases was
not separately re-run as a distinct pass, but no violation was observed in
any of the ~90 raw API/tool responses inspected while building this
report):

- No fabricated source identifiers observed — every `source_record_id`
  returned came directly from the tool/index response, never synthesized.
- No secrets/auth headers appear in any tool call (all three APIs are
  public, unauthenticated `requests` calls per `tools/*_tool.py`).
- One real instance of "wrong-source result mislabeled as another source"
  risk was **not** observed (PubMed/ClinicalTrials/ChEMBL results stayed
  correctly attributed to their own source throughout).
- The `filter.phase` bug (Section 3) is a **required, supported structured
  filter silently dropped**-adjacent gate concern: it is not silent
  (returns a hard error, not a silently-empty/wrong result) — flagged
  as a correctness bug, not a gate violation in the "silent drop" sense,
  but worth the gate owner's attention regardless.

---

## 8. Files

- `artifacts/v2/phase4_baseline_results.json` — full per-case results
  (PubMed RAG and PubMed live API reported as clearly separate
  sub-results per case), aggregate metrics, latency summaries,
  `failure_annotations`, `failure_category_tally`, and
  `wrong_entity_defect_reproduction`.
- This document.

## AMENDMENT (2026-09-25) — ClinicalTrials `filter.phase` fix, corrected numbers

**This section is an addition, not a silent edit.** All numbers in Sections
1–9 above are left exactly as originally measured (against the tool's
then-broken state) for the historical record. The corrected numbers below
supersede them for the 3 ClinicalTrials cases this defect actually touched.

**What happened:** the `filter.phase` bug flagged in Section 3 above (every
phase-filtered `search_trials()` call returning a live HTTP 400) has since
been fixed in `tools/clinical_trials_tool.py` — see
`docs/v2/CLINICALTRIALS_PHASE_FILTER_DEFECT_FIX.md` for the full root
cause, diff, and independent verification (209/209 tests pass; a direct
live call now returns `success: True` with real study data). Separately,
Phase 3's held-out supplement measurement
(`artifacts/v2/phase3_heldout_supplement_results.json`) turned out to have
its own harness bug that recorded `"status": "success"` for phase-filtered
calls without checking the real tool's `success` flag, which is why this
defect was not caught at that stage. Full details of both are in
`docs/v2/CLINICALTRIALS_PHASE_FILTER_DEFECT_FIX.md`.

**What was re-measured:** exactly the 3 dev+validation ClinicalTrials cases
this defect affected — `CT-PHASE-01`, `CT-MULTI-01`, `CT-MULTI-02` (every
case in the original per-case results whose `clinical_trials.params_used`
carried a non-null `phase` and whose `clinical_trials.error` was non-null;
confirmed exhaustively across all 19 dev+validation ClinicalTrials cases
with gold, not assumed). Each was re-run with its original `params_used`
(byte-identical condition/intervention/status/phase) against the
now-fixed `ClinicalTrialsTool().search_trials()`, live against
clinicaltrials.gov. Full before/after per-case detail, methodology, and
the corrected aggregate are in
`artifacts/v2/phase4_baseline_results_clinicaltrials_phase_fix_amendment.json`.

**Corrected headline numbers** (19 dev+validation ClinicalTrials cases with
gold, same scope as Section 1):

| Metric | Original (broken tool) | Corrected (fixed tool) |
|---|---|---|
| Required-trial recall | 0.737 (14/19) | **0.895 (17/19)** |
| Structured-filter-correctness rate | 0.850 (16/19) | 0.850 (16/19) — **unchanged** |

All 3 previously-erroring cases now return `success: True` with real,
non-empty study data and hit their gold NCT ID (`CT-PHASE-01` →
`NCT04468659`; `CT-MULTI-01` → `NCT03228303`; `CT-MULTI-02` →
`NCT02714634`/`NCT06687551`, both gold IDs returned). The
filter-correctness rate is unchanged because that metric judges whether
the *compiled* parameter matched the case's stated filter, not whether the
live API call succeeded — the defect was purely at the execution/transport
layer (wrong query parameter name), not in query compilation, so
compilation was already being measured correctly at baseline.

**What is still not fixed / out of scope for this amendment:** 2 of the 19
cases still do not hit their gold trial after this fix — `CT-COND-01` and
`MS-06`. Neither used a `phase` filter originally or now (both compiled
`phase: null`), so neither was touched by this defect; their misses are
genuine ranking/query-formulation gaps, left as-is and out of scope here.
The ChEMBL name→ID structural gap (Section 4) and the PubMed live-API date
default (Section 2) are also unaffected by this fix and remain as
originally measured.

**Independent, correctly-instrumented blind re-check (Task 1 of this
amendment):** separately from the targeted case rerun above, 8 new
ClinicalTrials phase-filter test cases (not reused from any prior
supplement) were authored and run directly through
`ClinicalTrialsTool().search_trials()` against the live API, spanning all
6 `VALID_PHASES` values, explicitly asserting the real `ToolResult.success`
field for every case (the exact check the Phase 3 supplement harness
omitted). Result: 8/8 calls returned `success: True` (zero HTTP 400s
across `EARLY_PHASE1`, `PHASE1`, `PHASE2`, `PHASE3`, `PHASE4`, and `NA`);
7/8 returned real, non-empty trial data, and the 1 remaining case
(early-phase gene-therapy trials for sickle cell disease) returned a
genuine zero-result set — `success: True`, `error: None`, 0 records — a
legitimate "no matching trials" outcome, not a tool failure. This
confirms the fix resolves the defect end-to-end: tool → real API → real
results, not merely absence of an exception.

---

## 9. What this measurement deliberately did not do

- Did not touch `phase4_heldout` (12 cases) — confirmed by construction.
- Did not modify `retrieval/retriever.py`, `tools/*.py`,
  `orchestration/*.py`, or any other existing file — purely additive.
- Did not attempt to fix the `filter.phase` 400 bug or the ChEMBL
  name→ID gap — this is a measurement task; both are flagged for whoever
  scopes the next Phase-4 step.
- Did not use any LLM/paid-API call — all query "compilation" for
  ClinicalTrials/ChEMBL was done by direct, deterministic parameter
  tables built from each case's own stated filters/gold rationale (see
  the harness's `CT_PARAMS`/`CHEMBL_PARAMS` tables, embedded in
  `phase4_baseline_results.json`'s per-case `params_used`/`arg_used`
  fields for full transparency), matching Phase 3's own precedent of
  deterministic, non-LLM query compilation.
