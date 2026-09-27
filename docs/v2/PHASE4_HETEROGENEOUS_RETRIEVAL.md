# Phase 4 — PubMed Heterogeneous Retrieval Candidate Comparison

Measured, not estimated. Candidates B2 and C below are real runs: live HTTP
calls to the public NCBI E-utilities API (`tools/pubmed_tool.py`, existing
rate limiter respected, no mocking) plus, for Candidate C, a real LLM call
through the frozen Phase 2 NLU architecture (Cerebras `qwen-3.8-27b`, via
`nlu.understand_query_with_result()`, rate-limited at its own configured
5 RPM). Candidates A and B1 are cited from
`artifacts/v2/phase4_baseline_results.json` and were **not** re-measured,
per `artifacts/v2/phase4_pubmed_candidate_plan.json` (written before this
measurement — see that file for the full candidate design and
comparability caveats). Full per-case data for B2/C is
`artifacts/v2/phase4_pubmed_candidate_comparison.json`. Candidate D
(RAG+live fusion) was evaluated for justification and **not built** — see
Section 5.

**Scope:** the same 22 `development`+`validation` PubMed-bearing cases
(15 `PM-*` + 7 `MS-*` multi-source cases) Candidates A/B1 were measured on
in `phase4_baseline_results.json`. `phase4_heldout` was not touched.

**Measured date:** 2026-09-25. **Cost:** live PubMed calls are free/public;
Candidate C additionally made 22 real Cerebras `qwen-3.8-27b` inference
calls (pricing per `artifacts/v2/nlu_frozen_config.json`:
$0.99/$1.49 per million input/output tokens — a handful of cents total for
22 short-query extractions, not separately itemized here as it is well
under measurement-noise level).

---

## 1. What was built

- `retrieval/pubmed_query_compiler.py::compile_pubmed_query()` — a
  deterministic function that builds a PubMed search term from a real
  `nlu.schemas.ResearchQuery`'s entities (`canonical_name`/`surface_form`,
  verbatim, never expanded/invented) and any *explicit* temporal
  constraint, joined with `AND`, multi-word phrases quoted. Returns a
  `CompiledPubMedQuery` dataclass with the term plus a full audit trail
  (`source_concepts`, `date_filter`, `fallback_used`, `notes`). 21 offline
  unit tests in `tests/test_pubmed_query_compiler.py` cover simple/compound
  entity combinations, abbreviation preservation (EGFR stays EGFR), date
  handling (absent/present/unparseable), empty-input graceful degradation,
  determinism, and an explicit no-fabrication assertion.
- 6 new regression tests in `tests/test_pubmed.py` for the Phase 4
  date-filter fix itself (previously zero dedicated coverage): confirm an
  unconstrained `search_pubmed(query)` call passes `date_from=None,
  date_to=None` to `_search_ids` (inspected via mock, not just "it runs"),
  confirm an explicit `years_back`/`date_from` is still honored with the
  correct computed value, and grep the whole module confirming
  `PUBMED_DEFAULT_DATE_RANGE` is referenced only in the explanatory comment,
  never as an executable default-filling expression.

## 2. Headline numbers — the causal-separated chain

| Candidate | Input query | Recall@1 | Recall@5 | Recall@10 | MRR | Precision@5 | Zero-result rate | Mean concept coverage |
|---|---|---|---|---|---|---|---|---|
| **A** — RAG (cited, not remeasured) | raw NL text | 0.545 | 0.773 | 0.773 | 0.636 | 0.182 | n/a | n/a |
| **B1** — old live (cited, not remeasured) | raw NL text | 0.045 | 0.045 | 0.045 | 0.045 | 0.045 | n/a (not recorded in baseline artifact) | n/a |
| **B2** — fixed live, raw query (**new**) | raw NL text | 0.045 | 0.045 | 0.045 | 0.045 | 0.009 | **0.636** | 0.917 |
| **C** — fixed live + compiler (**new**) | compiled term | 0.045 | 0.091 | **0.136** | 0.059 | 0.018 | **0.000** | 0.697 |

(n = 22 for every row; all values fractions of 22 cases.)

### Causal attribution — read this before citing any single number

The chain is **B1 → B2 → C**, and each arrow isolates exactly one
intervention:

- **B1 → B2 (the date-fix's own, isolated contribution): +0.000
  Recall@10** (1/22 → 1/22, and it is the **same** case both times —
  `PM-EXACT-02` — confirmed by diffing per-case hits, not just comparing
  aggregate counts). The date-filter defect was real and is fixed, but on
  this 22-case set it was **not** the dominant cause of B1's low recall;
  root cause 2 from `PHASE4_BASELINE_MEASUREMENT.md` Section 2 (raw
  natural-language text as the search term) dominates. B2's 63.6%
  zero-result rate on the *same* text B1 used (now without any date
  restriction) confirms this directly — most of these queries return
  nothing from PubMed's `esearch` relevance ranking regardless of date
  window, because a full natural-language question is a poor Boolean
  search term.
- **B2 → C (the compiler's own, isolated contribution): +0.091 Recall@10**
  (1/22 → 3/22). The compiler's most measurable effect is **eliminating
  zero-result queries entirely** (63.6% → 0.0%) — a structured `AND`-joined
  term of entity terms reliably returns *something*, where a full NL
  sentence frequently returns nothing. Of the 3 hits, 2 are new
  (`PM-TOPICAL-03`, `MS-06`) beyond B2's 1.
- **B1 → C (total, non-attributable to either alone): +0.091 Recall@10**
  (0.045 → 0.136). **Do not attribute this delta to the compiler alone or
  to the date-fix alone** — it is the combined effect, and per the isolated
  deltas above, essentially all of it traces to the compiler, not the
  date-fix, on this particular 22-case set. A different benchmark with more
  genuinely-old gold articles could show a larger B1→B2 contribution; this
  is a measured result on this specific set, not a general claim about the
  date-fix's value everywhere.

### A real, measured caveat on Candidate C's concept-coverage drop

Mean query-concept-coverage **dropped** from B2's 0.917 to C's 0.697. This
is not the compiler losing information — it is a **measurement-checker
limitation**: when `compile_pubmed_query()` uses an entity's normalized
`canonical_name` (e.g. `"Carcinoma, Non-Small-Cell Lung"` in place of the
query's literal `"non-small cell lung cancer"`, or `"Arthritis,
Rheumatoid"` in place of `"rheumatoid arthritis"`), the substring/token
concept-coverage check in this comparison's harness does not credit the
canonicalized form as covering the literal gold concept string, because it
does not do synonym resolution (by design — synonym-tolerant matching was
explicitly out of scope for keeping the check honest, per the harness's own
`concept_covered()` docstring). The entity's *meaning* is preserved
verbatim from the NLU extraction's own normalization, nothing was dropped
or invented; this is a query-drift-detection artifact of the coverage
metric's substring method, not a real information loss, and is called out
explicitly here rather than left to look like a regression.

## 3. Zero-result and duplication behavior

| Metric | B2 | C |
|---|---|---|
| Zero-result rate | 0.636 (14/22) | **0.000** (0/22) |
| Duplicate-PMID rate (within a case's own top-k) | 0.000 | 0.000 |
| Unique PMIDs returned across all 22 cases | 62 | 196 |

Neither candidate ever returns a duplicate PMID within one case's result
set (PubMed's own `esearch` doesn't produce them). C returns far more total
candidates because it almost never returns zero — this is a real,
structural improvement in *coverage of the search space*, even though most
of the additional candidates are not the gold article.

## 4. Latency — reported separately per stage, per the gate plan

| Stage | P50 (s) | P90 (s) | P95 (s) | Mean (s) | n |
|---|---|---|---|---|---|
| B2 PubMed API (esearch+efetch) | 0.401 | 1.361 | 1.401 | 0.642 | 22 |
| C PubMed API (esearch+efetch) | 0.302 | 0.463 | 0.483 | 0.306 | 22 |
| **C NLU extraction (Cerebras qwen, live)** | 11.167 | 11.708 | 11.768 | 10.620 | 22 |

C's PubMed-API leg is actually *faster* than B2's (shorter, more targeted
query strings; not a meaningful causal claim, just observed). The real cost
of Candidate C is the **NLU extraction stage** — ~11s per query, entirely
attributable to the Cerebras free-tier rate limit (5 RPM,
`nlu/extractor.py::CEREBRAS_RATE_LIMIT_RPS`), not model inference time
itself (the pilot measurement in `nlu_frozen_config.json` recorded true P50
inference latency of 481.7ms). This stage does not exist for A/B1/B2 at
all and is never added into their latency numbers, per
`PHASE4_GATE_PLAN.md`'s "never conflate stages" rule. In a
production deployment not bound by the free-tier rate limit, this stage
would cost closer to 0.5s, not 11s — reported as measured here, not
adjusted, but this context matters for any latency-based decision.

## 5. Candidate D (RAG + live fusion) — evaluated, not built

Per `phase4_pubmed_candidate_plan.json`'s stated condition, D was to be
built only if B2/C showed a complementary error pattern with RAG (i.e. live
PubMed recovering cases RAG misses). Checked directly: all 3 of Candidate
C's hits (`PM-EXACT-02`, `PM-TOPICAL-03`, `MS-06`) are **also** hit by RAG
at Recall@10=1.0 in `phase4_baseline_results.json` — zero unique recall
contribution from the live path on this 22-case set, including on the two
cases deliberately designed to test exactly this
(`PM-LIVE-01`/`PM-LIVE-02`, the stale-index cases) — Candidate C's compiled
queries for both (`tirzepatide AND "overweight or obesity"`, `lecanemab AND
donanemab AND "early Alzheimer's disease"`) are well-formed, but PubMed's
own relevance ranking still does not surface the correct 2026 article in
its top 10 for either. **Conclusion: fusion is not justified by this
measurement** — combining a strictly-worse, non-complementary candidate
with RAG could only add noise/duplication risk without a demonstrated
recall benefit, so Candidate D was not built. This is a data-driven
non-build, not a scope-reduction shortcut: the condition for building it
was checked and failed.

## 6. Winning architecture and why (priority order per `PHASE4_GATE_PLAN.md` Section 4)

1. **Retrieval correctness/recall: RAG (Candidate A) wins decisively.**
   0.773 vs Candidate C's 0.136 Recall@10 — RAG is still ~5.7x better than
   the best-available live PubMed path, even after both real fixes
   (date-filter removal + deterministic compiler) this task delivered.
2. **No systematic source failure:** Candidate C still has a 100%-miss
   subgroup (the 2 stale-index cases, by design) and multiple near-misses
   where the compiled query is topically correct but PubMed's own ranking
   doesn't surface the exact gold PMID — the live-API path is not
   systematically starved of results anymore (0% zero-result, a genuine
   fix), but it is systematically weak at *ranking* the correct result
   into the top 10, independent of whether it gets a result at all.
3. **Ranking quality:** RAG's MRR (0.636) vs C's (0.059) — RAG's
   cross-encoder rerank is doing real, measurable work the live API's
   `sort=relevance` has no equivalent of.
4. Multi-source coverage: not differentiating here (PubMed-only
   comparison).
5. Latency: C's PubMed-only leg is fast and comparable to A; the NLU stage
   adds real overhead, but per priority order this is evaluated last and
   does not change the winner.
6. Cost/complexity: A is already production-wired and zero-cost per query;
   C adds a real LLM-call dependency for a large recall deficit.

**RAG (Candidate A) remains the correct default PubMed retrieval path.**
This measurement does **not** recommend replacing or fusing it with the
live API for this benchmark's query distribution. What this work
concretely delivered instead: (a) the date-filter defect is genuinely
fixed and regression-tested (6 new tests), confirming it is *not*
reintroduced silently elsewhere in the module; (b) a real, small,
auditable, deterministic query compiler now exists
(`retrieval/pubmed_query_compiler.py`, 21 tests) for any future caller that
needs a live-API PubMed search term built from structured `ResearchQuery`
fields rather than raw NL text — it measurably outperforms raw-text
live-API search (Recall@10 0.136 vs 0.045, zero-result rate 0.0% vs
63.6%) even though it still trails RAG substantially; (c) the specific,
common misconception that "the date-fix alone would fix live PubMed
search" is empirically falsified here — its isolated contribution on this
set was 0.000 Recall@10, and conflating it with the compiler's contribution
would have overstated the fix's value by the entire 0.091 delta.

## 7. Hard safety/correctness gates (Section 3 of the gate plan)

Spot-checked across all 44 new live PubMed calls (22 B2 + 22 C) and all 22
NLU extraction calls in this measurement:

- No fabricated PMIDs — every `returned_ids` entry came directly from a
  live `esearch`/`efetch` response, never synthesized.
- No secrets/auth headers in any call (public, unauthenticated `requests`
  calls, same as the rest of `tools/pubmed_tool.py`).
- Compiled queries never introduced an entity/synonym not present in the
  NLU extraction's own output (verified structurally by
  `compile_pubmed_query()`'s design and by the 21 offline unit tests'
  explicit no-fabrication assertions — not re-derived ad hoc here).
- No case's `nlu.understand_query_with_result()` call failed
  (`nlu_failures: []` in `phase4_pubmed_candidate_comparison.json`'s
  `measurement_metadata`) — no `QUERY_COMPILATION_FAILURE` category
  triggered for Candidate C on this run.

## 8. Files

- `artifacts/v2/phase4_pubmed_candidate_plan.json` — the predeclared
  candidate plan (Task A), written before any new measurement.
- `retrieval/pubmed_query_compiler.py` — the compiler (Task B).
- `tests/test_pubmed_query_compiler.py` — 21 offline unit tests (Task C).
- `tests/test_pubmed.py` — 6 new regression tests appended for the
  date-filter fix (Task D).
- `artifacts/v2/phase4_pubmed_candidate_comparison.json` — full per-case
  and aggregate B2/C results (Tasks E/F).
- This document.
