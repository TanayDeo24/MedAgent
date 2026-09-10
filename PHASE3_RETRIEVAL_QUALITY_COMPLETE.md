# Phase 3: Retrieval Quality Pass — Complete (Honest Result: No Improvement)

Built a real Recall@10 eval set, measured a real dense-only baseline, built
BM25 + RRF fusion + cross-encoder reranking, and re-measured on the exact
same fixed eval set. **The hybrid+reranked pipeline did not improve
Recall@10 over the dense-only baseline — it measured substantially worse**,
at roughly 40x the latency. That's the real number this pipeline produces
on this eval set, reported as instructed, not adjusted after the fact.

This document explains what was built, the honest before/after numbers, and
the diagnostic work done to understand *why* — because "it got worse" is
not the same as "the components don't work," and the investigation below
matters for deciding what (if anything) to do next.

## 1. Eval set (`retrieval/eval_set.json`)

19 queries spanning the corpus's disease areas (oncology, cardiology,
autoimmune, infectious disease, neurology, rare disease), phrased
differently from `build_corpus.py`'s fetch queries so they test realistic
user-style questions, not a lexical echo of what built the corpus.

**Methodology, stated plainly**: for each query, `retrieve_dense()`'s top-50
candidates were shown to `nvidia/nemotron-3-super-120b-a12b` in a single
call, which judged which candidates are genuinely relevant. **This is
LLM-assisted labeling on a small, fixed set — not human-verified.** Same
honesty standard as this project's hallucination judge: a model judgment,
stated as such, not ground truth.

**Pooled recall, not corpus-wide recall**: relevance is only known within
each query's labeled top-50 dense pool. A chunk outside that original pool
(one only BM25 or reranking would ever surface) is treated as *not
relevant*, not as *unlabeled* — the full 22,674-chunk corpus was never
exhaustively judged, only the pool. **This is the single most important
caveat for interpreting the numbers below**, and it turned out to matter a
lot (see §5).

**Labeling reliability, live**: 2 of 19 labeling calls hit NIM's 90s×3
timeout (the endpoint was visibly contended, plausibly with the separate
evaluator session sharing the same rate budget). `build_eval_set.py`
persists after every query and supports resuming, so the retry cost was two
queries, not the whole batch. All 19 queries are successfully labeled in
the committed `eval_set.json` (0 `labeling_failed` entries).

**Labeled relevant-set sizes varied enormously**: 8 of 19 queries got
exactly 1 relevant chunk out of 50; the rest ranged from 15 to 50 out of 50
(median 37). Total: 433 labeled-relevant chunks across 19 queries. This
spread — not a bug — turned out to be the main driver of what happened
next (§5).

## 2. Baseline (dense-only) — measured before any changes

```
Mean Recall@10:   0.5426
Median Recall@10: 0.2326
Mean latency:     6.4ms
Median latency:   6.1ms
```

Full per-query breakdown: `retrieval/eval_results_baseline.json`.

## 3. What was built

- **`retrieval/build_bm25.py`**: `rank_bm25.BM25Okapi` over the same 22,674
  chunks the FAISS index covers (same row order), tokenized
  lowercase-alphanumeric over `title + chunk_text`. In-memory, persisted via
  pickle (`data/index/bm25.pkl`, 26.1MB). Build time: 1.2s. A standalone
  search engine (OpenSearch etc.) was explicitly out of scope — unnecessary
  at this scale regardless.
- **RRF fusion** (`Retriever._rrf_fuse`): top-30 FAISS + top-30 BM25 fused by
  `score = sum(1/(k + rank))` per list a chunk appears in, `k=60` (the
  standard default). RRF rather than a raw score blend because dense cosine
  similarity and BM25 scores live on incomparable scales.
- **Cross-encoder reranking** (`Retriever._rerank`): the fused top-30 pool
  reranked by `cross-encoder/ms-marco-MiniLM-L-6-v2` (local, via
  `sentence-transformers`, already a dependency — no new package). Scores
  `(query, "Title: {title}\n\n{chunk_text}")` pairs directly.
- **`retrieve()`'s external interface is unchanged**: `retrieve(query, k)`
  still returns `List[Document]`. Internally it now runs the full pipeline —
  dense + BM25 → RRF fuse → cross-encoder rerank → top-k.
- **`retrieve_dense()` is untouched and still first-class** — the exact
  pre-upgrade path, kept as the permanent, stable comparison point (used for
  both the eval-set candidate pool and the baseline measurement above).

This is a standard, widely-documented hybrid-retrieval pattern (sparse +
dense fused via RRF, then cross-encoder reranked) — not something novel to
this project. No specific prior-project lineage is claimed here beyond
that; this repository has no earlier implementation of it to point to.

## 4. Bug found and fixed during validation

While tracing why several queries went from perfect Recall@10 to a complete
miss, found that `_rerank()` was scoring candidates on bare `chunk_text`,
while the dense embedding step that originally surfaced each candidate
embeds `"Title: {title}\n\n{chunk_text}"` (see `chunking.py`). A mid-abstract
chunk can read as an off-topic fragment in isolation even when its
abstract's title makes it clearly on-topic — the cross-encoder was
demoting exactly this kind of chunk for lack of the title context the
dense encoder already had. Fixed by passing the same title-prefixed text to
the reranker (also the conventional choice for cross-encoder reranking,
e.g. BEIR-style evaluations concatenate title to passage before scoring).
This is a real pipeline consistency defect, not an eval-set adjustment —
recovered some of the loss (mean Recall@10 0.2086 → 0.3195) but not all of
it. The numbers in §5 are post-fix, i.e. the pipeline as it stands now.

No further tuning was done after this fix. The instructions were explicit
that the number is whatever the real pipeline produces on the fixed eval
set — not something to keep adjusting until it looks better.

## 5. After — hybrid + RRF + reranked, same fixed eval set

```
Mean Recall@10:   0.3195   (baseline: 0.5426,  Δ -0.2231,  -41.1% relative)
Median Recall@10: 0.1915   (baseline: 0.2326,  Δ -0.0411,  -17.7% relative)
Mean latency:     258.4ms  (baseline: 6.4ms,   ~40x slower)
Median latency:   249.0ms  (baseline: 6.1ms,   ~41x slower)
```

Full per-query breakdown: `retrieval/eval_results_hybrid.json`.

**Recall@10 got worse, not better. Latency got ~40x worse. Reported
plainly, as instructed, with no further adjustment to the eval set, k, or
anything else to change this outcome.**

Per-query, side by side (`recall_at_10`: baseline → hybrid):

| Labeled relevant | Baseline | Hybrid | Query |
|---:|---:|---:|---|
| 43 | 0.23 | 0.21 | resistance to osimertinib |
| 19 | 0.16 | 0.26 | PD-L1 expression predicting checkpoint response |
| 15 | 0.20 | 0.27 | PARP inhibitors BRCA ovarian cancer |
| 48 | 0.21 | 0.12 | CAR-T BCMA multiple myeloma outcomes |
| 1  | 1.00 | 0.00 | kinase inhibitors and cardiotoxicity |
| 47 | 0.19 | 0.15 | SGLT2 inhibitors heart failure |
| 1  | 1.00 | 1.00 | statins and all-cause mortality |
| 39 | 0.21 | 0.23 | COX-2 inhibitors cardiovascular risk |
| 50 | 0.20 | 0.16 | PCSK9 inhibitors cholesterol |
| 1  | 1.00 | 1.00 | JAK inhibitor mechanism, autoimmune |
| 1  | 1.00 | 1.00 | anti-CD20 mechanism, MS |
| 47 | 0.21 | 0.19 | gut microbiome and IBD |
| 1  | 1.00 | 0.00 | direct-acting antivirals, hepatitis C |
| 1  | 1.00 | 1.00 | why BACE inhibitors failed in Alzheimer's trials |
| 47 | 0.21 | 0.13 | CGRP treatments for migraine |
| 1  | 1.00 | 0.00 | CFTR modulators, cystic fibrosis |
| 1  | 1.00 | 0.00 | gene therapy for hemophilia, current state |
| 33 | 0.27 | 0.21 | TNF-alpha inhibitors, rheumatoid arthritis |
| 37 | 0.22 | 0.14 | long COVID pathophysiology |

### Why: two real, distinguishable effects

**(a) The eval methodology structurally favors the dense baseline.** The
labeled-relevant pool for every query *is* dense retrieval's own top-50 —
nothing outside what dense ranking already surfaced was ever eligible to be
labeled relevant. `retrieve_dense(k=10)` is therefore, by construction,
always drawing its top-10 from exactly the set the labels were built from.
The hybrid pipeline pulls in BM25 candidates that may be *genuinely good*
but were never in the labeled pool (so it gets no credit for surfacing
them) and can crowd out dense-highly-ranked, LLM-labeled-relevant chunks
from the fused top-30 before reranking ever sees them. This is a known,
structural limitation of pooled relevance evaluation when the pool comes
from only one of the methods being compared (the standard TREC-style fix —
pool from *all* systems being compared, not just one — was out of scope
given the "top-50 dense, one call" labeling budget specified for this
pass). It is not a flaw in BM25/RRF/reranking themselves; it's a
mismatch between how the eval set was built and what's being compared
against it.

**(b) For the 8 single-relevant-chunk queries, manual inspection suggests
some of the "misses" are the LLM label being narrow, not the retrieval
being wrong.** Example: for *"Why do kinase inhibitors sometimes cause
cardiotoxicity?"*, the labeled-relevant chunk's actual text is a thin review
teaser — *"Many Tyrosine Kinase Inhibitors have cardiac side effects. This
article provides an up-to-date review of these toxicities."* — with a
title that matches very well but with no mechanism explained. The
cross-encoder scored it 0.03 (near-irrelevant) and instead surfaced chunks
actually explaining mechanisms (e.g. *"Preclinical approaches to assess
potential kinase inhibitor-induced cardiac toxicity"*, *"The Role of p90
Ribosomal S6 Kinase (RSK) in TKI-Induced Cardiotoxicity"*) — arguably
*better* answers to the query than the one label credits. This doesn't
prove every single-relevant-chunk miss is a labeling artifact (some may be
real regressions), but it means the aggregate delta is not simply "hybrid
retrieval is worse at finding relevant content" — it's entangled with (a)
and with the LLM judge's own limitations on a one-shot, 50-candidate,
single-relevant-answer judgment call.

Both of these are real, and both cut against treating the -0.22 mean
Recall@10 delta as a clean verdict on hybrid retrieval's actual quality —
but neither of them is grounds to not report the number as measured. It is
reported above, unmodified.

## 6. Cost

Latency went from ~6ms to ~250ms per query — three sequential steps
(FAISS search, BM25 score-over-corpus, cross-encoder forward pass over ~30
pairs) where the baseline had one. At ~250ms, retrieval is still fast next
to an LLM call in the agent loop (seconds), so it wouldn't be the
bottleneck if wired in — but paying a real, non-trivial latency cost for a
measured recall *regression* is the core honest finding of this pass.

## 7. What this means / recommendation

**As currently built and measured, hybrid+RRF+reranking should not replace
the dense-only baseline based on this evidence.** Given §5's structural
pooling-bias caveat, this is not necessarily proof hybrid retrieval is
worse in general — but it is proof that *on the evidence gathered so far*,
it doesn't earn its ~40x latency cost. If retrieval quality work continues:

- A fairer comparison needs a pool built from *all* candidate methods
  (dense top-N ∪ BM25 top-N ∪ hybrid top-N), not just dense top-50, before
  labeling — otherwise any method that isn't dense starts at a structural
  disadvantage in recall terms by definition.
- The single-relevant-chunk queries (8/19) are low-information for this
  metric — recall on them is nearly binary and swings the mean heavily.
  A larger eval set, or multiple relevant chunks expected per query more
  consistently, would make the aggregate less noisy.
- `retrieve()` currently always runs the full hybrid+rerank pipeline; given
  this result, if `retrieve()` gets wired into the agent in a later pass,
  it's worth deciding then whether to default to `retrieve_dense()` instead
  (fast, and not shown to be worse here) until a fairer comparison exists.

## 8. Files

| File | Purpose |
|---|---|
| `retrieval/eval_set.json` | Fixed 19-query eval set, LLM-labeled, methodology documented inline |
| `retrieval/build_eval_set.py` | Builds the eval set (the only NIM-calling script in this pass) |
| `retrieval/measure_recall.py` | Computes Recall@10 + latency against the eval set for either `dense` or `hybrid` mode |
| `retrieval/eval_results_baseline.json` | Full per-query baseline (dense-only) results |
| `retrieval/eval_results_hybrid.json` | Full per-query hybrid (post-fix) results |
| `retrieval/build_bm25.py` | Builds the BM25 sparse index |
| `retrieval/retriever.py` | `retrieve()` (hybrid pipeline), `retrieve_dense()` (fixed baseline), RRF fusion, reranking |

## 9. Requirements

Added `rank_bm25==0.2.2` to `requirements.txt`. No other new dependencies —
the cross-encoder uses `sentence-transformers`, already present.

## Scope discipline

This pass made exactly 19 + a few debug NVIDIA NIM calls, all inside
`retrieval/build_eval_set.py` (labeling only) — nothing else in the
pipeline (BM25, RRF, reranking, measurement) calls NIM. No changes outside
`retrieval/` and `data/`. `agent/nodes.py` and `evaluation/` are untouched.
