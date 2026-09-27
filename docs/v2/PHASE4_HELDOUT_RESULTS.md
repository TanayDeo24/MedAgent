# Phase 4 Held-Out Acceptance Run

**Run date:** 2026-09-25
**Type:** ONE-TIME final held-out acceptance run against the frozen Phase 4 architecture (`artifacts/v2/phase4_frozen_config.json`, config_version 1).
**Split:** `phase4_heldout` (12 cases, `artifacts/v2/phase4_benchmark_manifest.json`) — confirmed untouched by any prior measurement (`phase4_baseline_results.json`'s `phase4_heldout_touched: false`).
**Execution discipline:** all 12 cases run exactly once, in a single pass, real calls only (local model inference for PubMed RAG; real HTTP calls to ClinicalTrials.gov and ChEMBL). No iteration, no fix-and-rerun. Raw call trace: `/tmp/heldout_raw_results.json`. Full scored detail: `artifacts/v2/phase4_heldout_results.json`.

No code was modified. `orchestration/`, `agent/`, `tools/`, `retrieval/`, and `config/` were read only, never edited.

---

## 1. Headline metrics per source

### PubMed (local RAG hybrid, `retrieve(query, k=10)`)

| Metric | Value | n |
|---|---|---|
| Recall@1 | 1.0 | 4 (positive-gold cases only) |
| Recall@5 | 1.0 | 4 |
| Recall@10 | 1.0 | 4 |
| MRR | 1.0 | 4 |
| Precision@5 (mean) | 0.2 | 4 |
| Hit@10 | 1.0 | 4 |
| Zero-result correctness | 0/2 (0.0) | 2 (PM-ZERO-01, NEG-ABSENT-01 pubmed leg) |
| Query concept coverage | 1.0 | 6 (trivial — no query compiler in the frozen path) |
| Duplicate rate | 0.0 | 6 |
| Latency (warm calls) | 0.274s–0.42s, median 0.318s | 5 |
| Latency (cold, incl. model load) | 3.579s | 1 |

All 4 positive-gold cases (PM-MULTI-02, PM-NARROW-01, PM-NARROW-03, PM-TOPICAL-02) hit the gold PMID at rank 1. This is stronger than (not contradicted by) the dev/validation Recall@10 of 0.773 / MRR 0.636 — plausibly a small-n/easier-mix effect, not a regression.

**Notable gap, first measured here:** the frozen RAG-only pipeline has no zero-result / relevance-threshold path. For a fabricated-drug-name query it still returns 10 chunks (all with strongly negative cross-encoder scores, -4.1 to -8.7) rather than signaling "no results." `pubmed_zero_result` is a 1-count category across the whole 61-case benchmark, and that one case landed in `phase4_heldout` — so this is genuinely new evidence, not a regression from a previously-passing state. No fabricated PMID was involved (all 10 returned IDs are real corpus articles); this is a precision/architecture-limitation finding, not a safety-gate violation.

### ClinicalTrials (`search_trials()`)

| Metric | Value | n |
|---|---|---|
| Required-trial recall | not measurable on this split | 0 positive-gold cases |
| Zero-result correctness | 2/2 (1.0) | 2 |
| Structured-filter correctness | not measurable on this split | 0 cases declare `expected_structured_filters` |
| Latency | 0.037s, 0.239s | 2 |

Both `phase4_heldout` ClinicalTrials cases are zero-result probes (CT-ZERO-01, NEG-ABSENT-01's CT leg); both correctly returned 0 studies. No positive-gold ClinicalTrials case exists in this split, so required-trial recall and filter-correctness cannot be independently confirmed here — dev/validation's 0.895 recall / 0.850 filter-correctness remain the only evidence for those.

### ChEMBL (`resolve_compound_name()`, matching `phase4_chembl_resolution_results.json` methodology)

| Metric | Value | n |
|---|---|---|
| Recall@1/5/10 | 1.0 / 1.0 / 1.0 | 1 (NEG-CROSSSOURCE-01, aspirin → CHEMBL25) |
| MRR | 1.0 | 1 |
| Hit@10 | 1.0 | 1 |
| Zero-result correctness | 1/2 (0.5) | 2 |
| Latency | 0.185s–2.151s | 3 |

The single positive-gold case resolved correctly (`exact_preferred_name`, rank 1) — consistent with dev/validation's 1.0 Recall@10 / 0.898 MRR, though n=1 here cannot independently confirm that.

**Notable defect, first measured here:** the zero-result-expected cases split 1/2. `CHEMBL-ZERO-01` ("ZZZNOTADRUGNAME123") correctly returned `no_match`. `NEG-ABSENT-01`'s ChEMBL leg ("Zorblatinix-9X") instead returned `match_type: "fuzzy"` with a real, non-null ChEMBL ID (`CHEMBL5875133`) — independently verified live via `get_drug_info` to be a real but entirely unrelated molecule (no preferred name, `mechanism_of_action: "Not available"`). `resolve_compound_name`'s fuzzy fallback has no confidence/similarity threshold; it takes whatever ChEMBL's own relevance-ranked `search.json` endpoint returns, even for gibberish. Every one of the 21 dev/validation ChEMBL cases had a real gold entity to resolve, and the one fabricated-name category (`chembl_zero_result`) is a 1-count category that also landed in `phase4_heldout` — so this specific failure mode had never been measured before. It is not a fabrication (the ID is real) and does not trip the fabricated-identifiers gate, but it does directly undermine the abstention behavior `NEG-ABSENT-01` is designed to test.

### Multi-source

`phase4_heldout` contains exactly one multi-source case, `NEG-ABSENT-01` — and it is a negative (absent-information) case, not a positive multi-source coverage case like MS-01..MS-07 in dev/validation. Per-source correctness: ClinicalTrials correct (empty), PubMed and ChEMBL both incorrect (see findings above) but for architecturally distinct reasons. No source starvation observed — all 3 required sources were successfully queried. The dev/validation multi-source coverage figure (0.571, 4/7) cannot be directly reproduced or contradicted here since no comparable positive multi-source case exists in this split.

---

## 2. Hard safety gates (Section 3 of `docs/v2/PHASE4_GATE_PLAN.md`)

| Gate | Result | Pass |
|---|---|---|
| Fabricated source identifiers | 0 | ✅ |
| Source ID corruption | 0 | ✅ |
| Cross-source ID collision | 0 | ✅ |
| Retrieval result without a source ID | 0 | ✅ |
| Required, supported structured filter silently dropped | 0 (no positive test case in this split — see caveat) | ✅ |
| Wrong-source result mislabeled as another source | 0 (tool-output level only — see caveat) | ✅ |
| Secrets/auth headers in retrieval trace | 0 | ✅ |

**All 7 hard safety gates pass, empirically verified against the actual run trace.**

Every gate was checked against real evidence, not assumed:
- Fabrication: every returned PMID/ChEMBL ID was cross-checked as a real record; the one questionable ChEMBL ID (`CHEMBL5875133`) was independently live-verified as real, just wrongly matched — a precision defect, not a fabrication.
- Secrets: the full raw trace was grepped for key/token/secret patterns (zero hits); all three sources called in this run are unauthenticated public APIs, so no credential could have leaked.
- Two gates (`filter dropped`, `wrong-source mislabeled`) have caveats below — they pass on the evidence available in this split, but that evidence is thinner than for the other five gates.

---

## 3. Consistency with prior measurement and accepted limitations

**Consistent with dev/validation and already-documented limitations:**
- PubMed RAG recall/MRR: stronger than, not contradicted by, dev/validation figures.
- ChEMBL positive-case resolution: consistent with dev/validation's resolve_compound_name methodology.
- ClinicalTrials zero-result handling: consistent with the AREA[Phase]/query.term fix already marked FIXED.
- Zero hard-gate violations: consistent with `phase4_failure_analysis.json`'s `hard_gate_violations_found: 0`.
- The two previously-accepted limitations (ChEMBL `search_by_target` first-hit heuristic; ClinicalTrials MS-06 ranking miss) were **not exercised** by this split at all — neither recurred nor were they contradicted, since no held-out case invokes `search_by_target` or a positive-gold multi-result ClinicalTrials query.

**New, not previously documented — surfaced only by this held-out run:**

1. **PubMed RAG has no zero-result path.** Architectural, not a regression, and not a hard-gate violation (no fabricated IDs) — but genuinely new evidence, since the only `pubmed_zero_result` case in the whole 61-case benchmark happened to land in `phase4_heldout` and was never tested before.
2. **ChEMBL `resolve_compound_name`'s fuzzy fallback is inconsistent and unguarded on fabricated compound names** — one fabricated name correctly no-matches, a different fabricated name returns a confident-looking but wrong real ID, because the fuzzy path has no similarity threshold. This is also newly measured: every dev/validation ChEMBL case had a real gold entity, and the sole `chembl_zero_result` case also landed in `phase4_heldout`.

Neither finding is a hard-safety-gate violation. Both are real correctness gaps in specifically the "confirm something does *not* exist" path, discovered for the first time only because these were the first cases of their kind ever run. I am not downplaying these: they represent a genuine, previously-unmeasured weak spot in both sources' negative-result handling, and are exactly the kind of "new and unexpected" outcome this run was designed to surface.

---

## 4. Scope caveats

- This run calls `retrieve()` / `search_trials()` / `resolve_compound_name()` directly — it does not invoke `agent/`/`orchestration/` decision logic, per the task's prohibition on touching those layers. The 3 abstention-expected cases (`NEG-UNSUPPORTED-01/02`, `NEG-ABSTAIN-AMBIG-01`) are reported as "no supporting tool operation exists," not as full end-to-end confirmation that the live agent abstains correctly.
- ClinicalTrials call arguments were hand-compiled from each case's query/gold fields by this measurement harness, standing in for the (out-of-scope) orchestration query-compilation step.
- PubMed sub-stage latency (BM25 vs. FAISS vs. cross-encoder) was not separately instrumented — only end-to-end `retrieve()` time was captured, to avoid modifying `retrieval/retriever.py`.
- The `required supported structured filter silently dropped` and `wrong-source result mislabeled` gates had no positive test case in this specific split to actually exercise them; they pass on the evidence available but that evidence is thinner than the other five gates.

---

## 5. Recommendation

**All 7 hard safety gates pass**, verified empirically against the real run trace. Positive-case recall/MRR for PubMed and ChEMBL are strong and consistent with (not contradicted by) prior dev/validation measurement. No regression and no hard-gate violation was found.

However, this held-out run surfaced **two new, previously-unmeasured correctness gaps** in the negative/absent-information handling of two of the three sources (PubMed RAG's unconditional top-k return with no relevance floor; ChEMBL's unguarded fuzzy-match fallback on fabricated names). Both are real, both are new information not present in `artifacts/v2/phase4_failure_analysis.json`'s accepted-limitations list, and both directly affect exactly the kind of query (a user asking about something that doesn't exist) where confident-looking wrong output is most likely to mislead a clinical user.

**My explicit recommendation:** these two findings are worth the orchestrating session's judgment call before declaring closure — they are not hard-gate violations and do not on their own prove a "systematic" defect (each affects a single held-out case; the underlying category is a 1-count category in the whole benchmark, so the true rate at scale is not established by n=1). I am presenting them as genuine new evidence, not fixing them, and not downplaying them. Whether this is enough to keep Phase 4 open pending a small, separately-scoped negative-result-handling fix (e.g., a relevance-score floor for PubMed RAG, a similarity threshold for ChEMBL's fuzzy fallback), or is acceptable to document as a further accepted limitation and close Phase 4, is the decision that belongs to the orchestrating session.
