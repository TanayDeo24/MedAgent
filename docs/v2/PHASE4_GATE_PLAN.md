# Phase 4 Gate Plan

Predeclared, BEFORE any candidate benchmarking, per directive Steps 7-9.

---

## 1. Retrieval failure taxonomy (Step 7)

Categories actually supported by this architecture (per
`docs/v2/PHASE4_INITIAL_RETRIEVAL_AUDIT.md` /
`artifacts/v2/phase4_retrieval_inventory.json` — not invented ahead of
evidence):

| Category | Applies to |
|---|---|
| `NO_RESULTS` | Any source; query produced zero candidates |
| `RELEVANT_ITEM_MISSED` | PubMed (gold PMID absent from top-k); ClinicalTrials (gold NCT absent); ChEMBL (gold compound/target/indication record absent) |
| `WRONG_ENTITY` | ChEMBL mainly (e.g. `search_by_target` resolves to a different, similarly-named target than intended — audit noted the tool's first-hit heuristic) |
| `WRONG_SOURCE` | Cross-source: a query needing PubMed got only ClinicalTrials results or vice versa |
| `OVER_FILTERED` | ClinicalTrials (a real, relevant trial excluded by an overly strict phase/status/condition filter) |
| `UNDER_FILTERED` | ClinicalTrials (a structured constraint from `ResearchQuery.constraints` wasn't applied, returning irrelevant trials) |
| `LEXICAL_MISS` | PubMed BM25 path: synonym/paraphrase not lexically matched |
| `SEMANTIC_MISS` | PubMed dense path: relevant passage embedded too far from query embedding |
| `RANKING_FAILURE` | Relevant item retrieved but ranked outside a useful top-k (present in the candidate pool, wrong position) |
| `DUPLICATE_DOMINANCE` | Multiple near-identical chunks/records crowding out distinct relevant ones |
| `STALE_INDEX` | PubMed RAG only: the corpus's known non-reproducibility gap (13,115→9,000 subsample) means the indexed corpus may not reflect the live PubMed API's current content |
| `UPSTREAM_PAGINATION_LOSS` | ClinicalTrials: audit noted no cap on pagination other than `max_results`/absence of `nextPageToken` — a real record could be lost across pages |
| `METADATA_LOSS` | Any source: `source_metadata` fields dropped between the tool's raw result and the `RetrievalCandidate` |
| `QUERY_COMPILATION_FAILURE` | Any source: the query sent to the source failed to represent `ResearchQuery`'s actual constraints |

Not used: a generic catch-all "retrieval failed" — every failure recorded
in benchmark/candidate results must map to one of the above or be named as
a new, justified category (not silently bucketed).

## 2. Predeclared metrics (Step 8)

**Recall:** Recall@1, @5, @10 for PubMed and ChEMBL (where multiple
candidate records legitimately exist); ClinicalTrials uses required-trial
recall (gold NCT IDs present in returned set) since k is typically small
and filter-driven, not a ranked-list-depth question in the same sense.
Recall@20 only where a source's benchmark cases genuinely have that many
plausible relevant items (do not manufacture depth PubMed doesn't need).

**Ranking:** MRR where each case has one/few relevant targets (PubMed,
ChEMBL exact-entity cases). **nDCG is NOT used unless a benchmark case
genuinely carries graded (not binary) relevance labels** — per directive
Step 13's explicit prohibition on inventing graded relevance to justify
nDCG. If all labels end up binary, only binary metrics (Recall, MRR,
Precision@k, Hit@k) are reported.

**Precision:** Precision@k for PubMed and ChEMBL, where a source can return
many loosely-related items (ClinicalTrials' structured filtering usually
makes precision@k less informative — reported only if the data supports
it, not forced).

**Hit rate:** Hit@k / success@k for all three sources — did any correct
item appear in the top-k at all.

**Source coverage:** all-required-source retrieval success (for
multi-source benchmark cases), per-source retrieval success rate,
cross-source coverage (did each *required* source contribute at least one
non-empty result).

**Query quality:** required-concept coverage (reusing the same
substring/synonym-tolerant concept-match approach Phase 3's benchmark used
for PubMed query strings — `gold_query_must_contain_concepts`-style),
structured-constraint preservation rate (ClinicalTrials), query drift rate
(compiled query loses/distorts a constraint present in `ResearchQuery`).

**Duplication:** duplicate-candidate rate, redundant-result rate (near-
identical chunks/records within the same source's top-k).

**Efficiency:** P50/P90/P95 for: lexical (BM25) lookup, dense (FAISS)
lookup, reranker, live-API call, and total per-source retrieval latency —
reported separately, never conflated into one "retrieval latency" number
the way Phase 3's own baseline measurement initially had to flag as a
limitation for its own latency fields.

**Cost:** model-assisted retrieval calls (query expansion, if used) per
query, tokens, $/query where applicable — same measured-vs-projected
discipline as Phases 2 and 3.

No composite score. Per directive Step 30 priority order (restated below
in Section 4), correctness/recall dominates; latency/cost matter last.

## 3. Hard safety/correctness gates (Step 9) — frozen, all must equal 0

| Gate | Required value |
|---|---|
| Fabricated source identifiers | 0 |
| Source ID corruption | 0 |
| Cross-source ID collision | 0 |
| Retrieval result without a source ID (where the source exposes one) | 0 |
| Required, supported structured filter silently dropped | 0 |
| Wrong-source result mislabeled as another source | 0 |
| Secrets/auth headers in retrieval trace | 0 |

Not weakened after seeing results, same discipline as Phase 3.

## 4. Priority order for candidate/winner selection (restated from directive Step 30)

1. Retrieval correctness/recall
2. No systematic source failure (a candidate with great aggregate recall
   but one starved source fails this, same logic as Phase 3's per-source
   miss gate)
3. Ranking quality
4. Multi-source coverage
5. Latency
6. Cost/complexity

No single composite score decides a winner.
