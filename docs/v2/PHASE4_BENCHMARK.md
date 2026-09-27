# Phase 4 Retrieval-Quality Benchmark

`artifacts/v2/phase4_benchmark_manifest.json` (benchmark_version 1.0.0,
created 2026-09-25). Built per directive Steps 10-13, grounded in
`docs/v2/PHASE4_RETRIEVAL_CONTRACT.md`, `docs/v2/PHASE4_GATE_PLAN.md`, and
`docs/v2/PHASE4_INITIAL_RETRIEVAL_AUDIT.md`. This is a new, purpose-built
retrieval-quality benchmark — it is not a reuse or extension of Phase 3's
tool-orchestration-correctness benchmark
(`artifacts/v2/phase3_benchmark_manifest.json`), though it follows the same
`group_key`-based split-leakage discipline.

## 1. What this benchmark tests

Retrieval quality — whether the right `source_record_id` (PMID / NCT ID /
ChEMBL ID) is actually found — not orchestration correctness (which source/
operation/parameters to call, already covered by Phase 3's benchmark). Gold
labels are expressed against `RetrievalCandidate.source_record_id` per
`docs/v2/PHASE4_RETRIEVAL_CONTRACT.md` Section 2-3, and category coverage
maps onto the failure taxonomy predeclared in `docs/v2/PHASE4_GATE_PLAN.md`
Section 1 (no new failure category invented here).

## 2. Totals

| | |
|---|---|
| Total cases | **61** |
| development | 37 |
| validation | 12 |
| phase4_heldout | 12 |
| Distinct group_keys (leakage-prevention units) | 29 |
| Cases with exact-ID gold | 37 |
| Cases with concept-based gold (any-of-N verified IDs, or required-concept list) | 17 |
| Cases with `no_results_expected` gold | 4 |
| Cases with `abstention_expected` gold | 3 |
| Cases touching PubMed | 28 |
| Cases touching ClinicalTrials | 21 |
| Cases touching ChEMBL | 24 |

## 3. Category coverage table

| Category | Count | Source(s) |
|---|---|---|
| pubmed_exact_entity | 2 | pubmed |
| pubmed_lexical_gap | 2 | pubmed |
| pubmed_mechanism | 2 | pubmed |
| pubmed_multi_concept | 2 | pubmed |
| pubmed_narrow_constraint | 5 | pubmed |
| pubmed_topical | 4 | pubmed |
| pubmed_live_api | 2 | pubmed (live API only — deliberately absent from local RAG corpus) |
| pubmed_zero_result | 1 | pubmed |
| clinicaltrials_condition | 3 | clinical_trials |
| clinicaltrials_intervention | 2 | clinical_trials |
| clinicaltrials_phase | 1 | clinical_trials |
| clinicaltrials_status | 2 | clinical_trials |
| clinicaltrials_multi_filter | 3 | clinical_trials |
| clinicaltrials_low_result | 2 | clinical_trials |
| clinicaltrials_zero_result | 1 | clinical_trials |
| chembl_compound | 6 | chembl |
| chembl_exact_identifier | 2 | chembl |
| chembl_target | 1 | chembl |
| chembl_indication | 2 | chembl |
| chembl_ambiguous | 2 | chembl |
| chembl_zero_result | 1 | chembl |
| multi_source | 7 | 2 or 3 sources |
| negative_absent_information | 1 | all 3 (checked, all zero) |
| negative_unsupported_operation | 2 | none (no operation exists) |
| negative_wrong_source_trap | 1 | chembl (not clinical_trials, despite surface phrasing) |
| negative_ambiguous_entity | 2 | chembl |

Three cases (`CHEMBL-TARGET-02`, `CHEMBL-AMBIG-01`, `NEG-AMBIG-COMPOUND-01`)
carry `expected_failure_category: WRONG_ENTITY`; one
(`CT-OVERFILTER-01`) carries `OVER_FILTERED`; one (`NEG-CROSSSOURCE-01`)
carries `WRONG_SOURCE` — all three discovered/confirmed via live API calls
during construction, not hypothesized in advance.

## 4. Gold-label provenance (verified, not predicted)

Every gold label was produced by one of three verification methods, each
recorded per-case in that case's `verification` field in the manifest:

1. **`local_corpus_inspection`** — for PubMed RAG cases, the actual
   title+abstract text of the candidate PMID was read directly out of
   `data/corpus/abstracts.jsonl` (the exact corpus `retrieval/retriever.py`
   indexes — confirmed via `retrieval/retriever.py`'s `Document`
   dataclass/`retrieve()` signature) before labeling it gold.
2. **`live_pubmed_api` / `live_clinicaltrials_v2_api` / `live_chembl_api`**
   — for ClinicalTrials/ChEMBL cases (no local index exists for either, per
   `docs/v2/PHASE4_INITIAL_RETRIEVAL_AUDIT.md` Sections B/C) and for PubMed
   cases needing content plausibly newer than the local corpus, the real
   public API (NCBI E-utilities, ClinicalTrials.gov API v2, ChEMBL web
   services) was called live on 2026-09-25 and the actual returned record
   was read to judge relevance.
3. **`tool_signature_inspection` / `orchestration_models_inspection`** —
   for abstention/unsupported-operation cases, the real tool method
   signatures (`tools/pubmed_tool.py`, `tools/clinical_trials_tool.py`,
   `tools/chembl_tool.py`) and typed argument schemas
   (`orchestration/models.py`) were read in full to confirm no operation
   exists, rather than assumed.

**Concrete evidence this was verification, not prediction:**

- `CHEMBL-COMPOUND-02` (osimertinib): an initial guessed ID
  (`CHEMBL1743081`) was checked live against
  `https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL1743081.json` and
  turned out to be **TRALOKINUMAB** — a completely unrelated drug. That
  guess was discarded; the correct ID (`CHEMBL3353410`) was then found via
  a live name search and used instead. The rejected guess is recorded in
  the case's `verification.evidence`.
- `CHEMBL-TARGET-02` / `CHEMBL-AMBIG-01` (EGFR / MET target search): live
  calls to `target/search.json?q=EGFR` and `q=MET` showed the ChEMBL tool's
  first-hit heuristic (noted as a risk, not yet demonstrated, in
  `docs/v2/PHASE4_INITIAL_RETRIEVAL_AUDIT.md`) actually returning a
  protein-protein-interaction record ahead of the true human EGFR protein,
  and an unrelated *E. coli* transcriptional repressor ahead of the true
  human MET/HGFR oncogene target, respectively — both discovered
  empirically while building this benchmark.
- `CT-MULTI-02` (upadacitinib RA, recruiting + Phase 4): before labeling
  gold, the combined status+phase filter was checked live to confirm it
  genuinely returns non-empty results (`NCT02714634`, `NCT06687551`),
  ruling out a false `NO_RESULTS` assumption.
- `PM-LIVE-01` / `PM-LIVE-02`: both gold PMIDs were confirmed **absent**
  from `data/corpus/abstracts.jsonl` by direct string search, before being
  confirmed present via a live PubMed `esearch`/`esummary` call — these
  cases specifically exercise the `STALE_INDEX` failure category the gate
  plan predeclares for the local RAG corpus's known 13,115→9,000
  non-reproducible-subsample gap.

## 5. Splits and leakage prevention

Every case carries a `group_key`, usually a drug/target/disease-family tag
(e.g. `family_osimertinib_egfr`, `family_tirzepatide`). Cases about the
same entity family across different sources — e.g. a PubMed case, a
ClinicalTrials case, a ChEMBL case, and a multi-source case all about
tirzepatide — share one `group_key`, so a group is **never** split across
`development`/`validation`/`phase4_heldout` (same discipline as
`artifacts/v2/phase3_benchmark_manifest.json`).

Because group sizes here are uneven (a multi-source drug family can hold
up to 6 cases; a single fact-lookup case is its own 1-case group), the
generator (`seed 20260925`) shuffles the 29 distinct group_keys with that
fixed seed, then greedily assigns each group, in shuffled order, to
whichever split is currently furthest below its 60%/20%/20% **case-count**
target — verified: no `group_key` appears in more than one split, and the
resulting case-count split (37/12/12) lands close to 60/20/20 despite
uneven group sizes.

## 6. Protected data — confirmed not touched

- **Phase 2 consumed test split** (`evaluation/v2/nlu_benchmark_v1.json`
  and its archive) — not read for content or labels.
- **Phase 3's spent held-out data**
  (`artifacts/v2/phase3_benchmark_manifest.json`'s `phase3_heldout` split,
  `artifacts/v2/phase3_heldout_results.json`,
  `artifacts/v2/phase3_heldout_supplement*.json`) — `phase3_benchmark_manifest.json`
  was read only to learn its case-format/grouping convention (explicitly
  permitted); no Phase 3 query text, `group_key`, or gold label was reused.
  All 61 query strings here are newly authored and were checked for
  verbatim/near-verbatim overlap against Phase 3's `original_query`
  strings — none found.
- **Phase 10** — does not exist in this repository yet (no
  `docs/v2/PHASE10_*`, no `artifacts/v2/phase10_*`); confirmed by directory
  listing, nothing under that name was read or touched.

## 7. What this benchmark deliberately does not do

Per `docs/v2/PHASE4_RETRIEVAL_CONTRACT.md` Section 4, this benchmark scores
retrieval-candidate identification only (Recall/MRR/Precision/Hit@k, source
coverage, duplication, query-quality per `docs/v2/PHASE4_GATE_PLAN.md`
Section 2) — it does not carry graded relevance labels (all labels are
binary: relevant/not, present/absent — no nDCG is implied or required, per
the gate plan's explicit prohibition on inventing graded relevance), and it
does not evaluate final answer synthesis, citation compilation, or
claim-level evidence verification (Phase 5's job).

## 8. Files

- `artifacts/v2/phase4_benchmark_manifest.json` — full case set, splits,
  and methodology metadata.
- This document.
