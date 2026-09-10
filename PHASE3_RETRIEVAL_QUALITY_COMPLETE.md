# Phase 3: Retrieval Quality — Complete

Two passes. **Pass 1** built a hybrid (BM25+RRF+cross-encoder) pipeline and
measured it against a dense-only baseline; the eval set turned out to have
a structural bias that capped hybrid's measurable recall, and even after
fixing one real pipeline bug found during validation, hybrid measured worse
than dense. **Pass 2** fixed that eval-set bias, found and fixed a second
real pipeline bug it exposed, then tried a stronger embedding model, two
alternative chunk sizes, and query expansion — none beat plain dense
retrieval's mean Recall@10 on the corrected eval set either.

**Final, honest result: the best-measured configuration across both passes
is plain dense retrieval (`all-MiniLM-L6-v2`, 180-word/30-overlap
chunking) — mean Recall@10 = 0.5711, well short of the 0.9 target.**
`retrieve()` now defaults to this configuration. The full hybrid pipeline
remains available (`retrieve_hybrid_reranked`) because the picture is
genuinely mixed, not a clean loss — see §6.

## Table of contents

- §1-2: Pass 1 (hybrid pipeline, original eval set) — summarized, largely superseded
- §3: Why the eval set needed fixing
- §4: Pass 2's corrected eval set
- §5: Pass 2's baseline vs hybrid (corrected eval set) + the PMID-dedup bug found and fixed
- §6: Embedding model, chunk size, and query expansion experiments
- §7: Final configuration and full progression table
- §8: What this means / recommendation
- §9: Files, requirements, scope discipline

---

## 1. Pass 1 summary (superseded numbers, kept for history)

Pass 1 built a 19-query eval set labeled by `nvidia/nemotron-3-super-120b-a12b`
against each query's **dense-only top-50** candidates, then built BM25 +
RRF fusion + cross-encoder reranking and compared:

```
Dense-only (Pass 1 eval set):  mean Recall@10 0.5426, median 0.2326,  6.4ms
Hybrid     (Pass 1 eval set):  mean Recall@10 0.3195, median 0.1915, 258.4ms
```

Hybrid measured **worse**, even after finding and fixing a real bug (the
cross-encoder was scoring bare `chunk_text` instead of `"Title: ...\n\n..."`,
inconsistent with how the dense embedder saw the same candidates — fixing
it recovered mean Recall@10 from 0.2086 to 0.3195, not all the way back).
Diagnosis at the time (confirmed and acted on in Pass 2, §3): the eval
pool was built entirely from dense retrieval's own ranking, which
structurally caps every other method's measurable recall.

Full Pass-1 detail — including the bug's discovery, per-query tables, and
the original single-relevant-chunk investigation — is preserved in git
history (commit `a11acd2` and its predecessors) rather than duplicated
here.

## 2. Pass 2's mandate

Push Recall@10 toward 0.9 through real improvements, measured honestly on
a properly fixed evaluation methodology:
1. Fix the eval set's structural bias first.
2. Re-measure dense vs. hybrid on the corrected set.
3. Try a stronger embedding model.
4. Try alternative chunk sizes.
5. Try query expansion.
6. Report the winning combination honestly, including if it falls short of
   0.9.

## 3. Why the eval set needed fixing

Pass 1's pool was dense retrieval's own top-50, so nothing outside what
dense already ranked highly could ever be labeled relevant — any other
method retrieving something genuinely good but dense-invisible got no
credit, and could even look *worse* for correctly displacing a
dense-favored labeled chunk from a fixed top-k. This is the standard
single-system pooling bias TREC-style evaluation guards against by pooling
from every system being compared.

**Fix**: pool the union of dense top-30, BM25 top-30, and full
hybrid(RRF+rerank) top-30 (`Retriever.get_pooled_candidates`) before
labeling — every method gets a fair shot at contributing to its own
scoring pool.

**Second, related fix — PMID-level ground truth, not chunk-level**: Pass
2's plan includes a chunk-size experiment (§6), and different chunk sizes
produce entirely different `chunk_id`s for the same abstracts. A
chunk-keyed eval set literally cannot score a chunk-size change. Ground
truth was rolled up to `relevant_pmids` (a query's relevant set is
abstracts, not specific chunk spans) — decided before any Recall@10 numbers
were seen from this pass, for this technical reason, not to influence a
result.

## 4. Pass 2's corrected eval set (`retrieval/eval_set.json`, schema v2)

Same 19 queries as Pass 1 (spanning oncology, cardiology, autoimmune,
infectious disease, neurology, rare disease), same "one NIM call per query"
labeling budget, same honesty standard (**LLM-assisted labeling, not
human-verified** — stated in the file's own `methodology` field).

**Labeling reliability, live**: the shared NIM endpoint was under sustained
heavy load for most of this session (frequent `503 Service Unavailable`
and 90s×3 timeouts — plausibly contended with the separate evaluator
session mentioned in this project's own operating constraints). 18 of 19
queries were eventually labeled successfully after up to 9 retry attempts
per query on the worst cases, using `build_eval_set.py`'s per-query
persistence/resume support (a query's successful label is saved
immediately, so a later failure only costs that one query's retry, not the
batch). **1 query could not be labeled** after 9 attempts over roughly 45
minutes and is recorded as `labeling_failed: true` rather than silently
dropped or faked. Of the 18 labeled, 1 has zero relevant PMIDs in its pool
(a genuine "none relevant" judgment, not a failure). **17 queries are
scored** in every measurement below.

Labeled relevant-PMID-set sizes: `[0, 1, 1, 1, 1, 1, 1, 14, 17, 18, 22, 23,
27, 28, 29, 29, 32, 34]` — 6 of the 17 scored queries have exactly 1
relevant PMID (this matters a lot for interpreting results, see §7).

## 5. Corrected baseline vs. hybrid, and the PMID-dedup bug

First re-measurement on the corrected pool:

```
Dense-only:  mean 0.5371, median 0.3043
Hybrid:      mean 0.3233, median 0.3182
```

The pooling fix alone barely moved the mean gap. Investigating why (same
approach as Pass 1's bug hunt) surfaced a **second real defect**: both
`retrieve_dense()` and `retrieve()` were returning **duplicate PMIDs** in
their top-10 — multiple chunks of the same abstract rank near each other,
so a "top 10" routinely contained only 5-9 *unique* abstracts (verified
across the whole eval set). Since ground truth is now PMID-level, this
mechanically wasted recall capacity for both methods — but it's a real
defect independent of any metric: an agent citing "10 sources" that are
actually 2 abstracts chunked 5 ways each is not 10 sources.

**Fix**: `retrieve_dense()` now over-fetches (`max(k*4, 40)` candidates)
and deduplicates by PMID down to k; `retrieve()`'s hybrid path reranks its
*full* fused pool (not just the top-k) before deduplicating down to k.
External interface unchanged.

**Re-measured after the dedup fix**:

```
Dense-only:  mean 0.5711, median 0.3448,  7.3ms   (Pass 1: 0.5426 / 0.2326)
Hybrid:      mean 0.4832, median 0.3704, 256.6ms  (Pass 1: 0.3195 / 0.1915)
```

The gap shrank substantially: mean Recall@10 delta went from -41.1%
relative (Pass 1) to -15.4% relative (Pass 2, corrected pool + dedup), and
**hybrid's median now slightly exceeds dense's** (0.3704 vs 0.3448) — on a
typical query, hybrid is at least as good.

Only 2 of 17 queries still show a full 1.00 → 0.00 drop (CFTR modulators,
gene therapy for hemophilia — both single-relevant-PMID queries). Traced
one (CFTR): the labeled PMID ranks 26th of 30 in the full reranked
candidate pool; manual inspection shows the top-3 actually returned are
clearly on-topic and arguably better matches than the one labeled PMID
(whose title is about patients **not eligible** for CFTR modulators — a
tangential angle, not a direct answer to "how do CFTR modulators treat
CF"). Read as LLM-labeling noise on a sparsely-labeled query, not a
retrieval defect — consistent with this eval set's already-documented
single-relevant-PMID noise (§7 quantifies this properly rather than
hand-waving it).

## 6. Embedding model, chunk size, and query expansion

All three experiments below reuse the **same fixed eval set** from §4 —
per this pass's explicit instruction, the pool built in §3-4 does not
change after this point, even though (see the embedding-model caveat
below) that itself introduces a smaller version of the same pool-anchoring
issue §3 fixed for BM25/hybrid vs. dense-only.

### 6a. Stronger embedding model: `BAAI/bge-base-en-v1.5`

Built a full index variant (`data/index/variants/bge_base_180_30/`, same
180/30 chunking, 768-dim vs. MiniLM's 384; embedding all 22,674 chunks took
1172.7s vs. the production build's 87.4s — reused the same BM25 index
since chunking, and therefore chunk text, is unchanged).

```
bge-base dense:  mean 0.4173, median 0.2759,  29.6ms
bge-base hybrid: mean 0.4675, median 0.3571, 274.0ms
```

**Worse than MiniLM on every axis** (MiniLM dense: 0.5711/7.3ms, MiniLM
hybrid: 0.4832/256.6ms), and slower. Caveat stated plainly: this eval
set's pool was built from MiniLM's own dense ranking (+BM25+MiniLM-hybrid),
so bge-base is partly being measured against a MiniLM-anchored yardstick —
the same structural issue §3 fixed for BM25/hybrid, now working against a
different embedding model. A fully unbiased comparison would need a pool
built from each candidate model's own top-N too, out of scope for the
fixed-eval-set instruction. Reported as measured regardless.

Not pursued: `BAAI/bge-large-en-v1.5` (the task allowed it only "if latency
allows"; bge-base already underperforms while costing more on every
latency dimension measured, so there's no reason to expect the larger,
slower model reverses that).

### 6b. Chunk size: 256/50 and 384/64 (MiniLM, the §6a winner)

```
                    dense mean / median        hybrid mean / median
180/30 (current):   0.5711 / 0.3448            0.4832 / 0.3704
256/50:              0.5541 / 0.3448            0.4792 / 0.4286
384/64:              0.5670 / 0.3636            0.4689 / 0.3704
```

180/30 has the best mean Recall@10 in both dense and hybrid mode. 256/50's
hybrid *median* (0.4286) is the highest of any chunk-size/mode
combination, but its mean is lower — a few outlier queries pull it down
more at that chunk size, not a broad win. Latency is essentially flat
across all three configurations. No chunking change earns a place in the
final configuration.

### 6c. Query expansion

`retrieval/query_expansion.py`: one NIM call per query generates 2-3
reformulations; each variant (plus the original) is dense+BM25 searched
independently, all resulting ranked lists fused via the existing RRF
(already N-list-capable, not just 2), then reranked against the
**original** query only. This is the only retrieval-*time* NIM usage in
this pass (eval labeling is the other, separate use).

```
hybrid + expansion: mean 0.3807, median 0.3333, mean latency 4783.0ms
(plain hybrid:       mean 0.4832, median 0.3704, mean latency  256.6ms)
```

Worse on every axis, and unreliable to measure cleanly: **8 of 18**
expansion calls failed outright (`503 Service temporarily overloaded`,
same contended endpoint as §4) and fell back to no-expansion, meaning this
number is diluted *toward* plain-hybrid behavior, not a clean read of
"expansion always applied." Not retried for a cleaner number: even with
that dilution working in its favor, the result is already far from
competitive — no plausible clean rerun closes a ~0.10 mean-recall gap while
also costing ~19x the latency of plain hybrid. Not adopted.

## 7. Final configuration and full progression

Full leaderboard, every configuration measured on the identical fixed eval
set (mean Recall@10, descending):

| Mean | Median | Latency | Configuration |
|---:|---:|---:|---|
| **0.5711** | 0.3448 | 7.3ms | **Dense, 180/30, MiniLM — final default** |
| 0.5670 | 0.3636 | 8.2ms | Dense, 384/64, MiniLM |
| 0.5541 | 0.3448 | 8.1ms | Dense, 256/50, MiniLM |
| 0.4832 | 0.3704 | 256.6ms | Hybrid, 180/30, MiniLM |
| 0.4792 | 0.4286 | 302.7ms | Hybrid, 256/50, MiniLM |
| 0.4689 | 0.3704 | 293.4ms | Hybrid, 384/64, MiniLM |
| 0.4675 | 0.3571 | 274.0ms | Hybrid, 180/30, bge-base |
| 0.4173 | 0.2759 | 29.6ms | Dense, 180/30, bge-base |
| 0.3807 | 0.3333 | 4783.0ms | Hybrid + query expansion, 180/30, MiniLM |

**By the same summary statistic (full-set mean Recall@10) used as the
headline number throughout this whole two-pass effort, plain dense
retrieval — unchanged from the very first Phase 3 pass — is the winner.**
`retrieve()` now defaults to it (`retrieve_dense()` internally); the full
hybrid pipeline is preserved as an explicit opt-in
(`retrieve_hybrid_reranked`).

**A necessary nuance, not a way to avoid the conclusion above**: dense's
aggregate lead is concentrated in a specific subgroup. Splitting the 17
scored queries by labeled relevant-set size:

| Subgroup (n) | Dense mean | Hybrid mean | Dense median | Hybrid median |
|---|---:|---:|---:|---:|
| Single-relevant-PMID queries (6) | **1.000** | 0.667 | — | — |
| Multi-relevant-PMID queries (11) | 0.337 | **0.383** | 0.321 | **0.357** |

On the 6 single-relevant-PMID queries — which behave as near-binary,
high-variance outcomes on a small eval set (dense went a perfect 6/6; a
single flipped result changes that subgroup's mean by 0.167) — dense wins
outright. On the 11 richer, arguably more representative multi-relevant
queries, **hybrid is actually slightly ahead on both mean and median**.
This is presented in full, not selectively: the literal, pre-committed
metric (full-set mean) says dense wins and that is what's shipped as the
default; the subgroup breakdown is why the hybrid pipeline was kept
available rather than deleted.

## 8. What this means / recommendation

**The final measured Recall@10 (0.5711, dense-only, unchanged from before
this whole two-pass effort) is well below the 0.9 target. Stated plainly,
as instructed: none of the two passes' real, honestly-measured improvement
attempts — hybrid retrieval, a stronger embedding model, chunk-size tuning,
query expansion — beat the simple baseline this project already had before
any of this work started.**

What was gained, despite not hitting 0.9:
- A materially less biased eval methodology (§3-4) — the single biggest
  lever, as anticipated: it closed most (not all) of the dense-vs-hybrid
  gap that Pass 1 had wrongly read as "hybrid retrieval doesn't work."
- Two real pipeline bugs found and fixed via that methodology (title
  context missing from reranking in Pass 1; duplicate-PMID top-k in Pass
  2) that make both dense and hybrid genuinely better, independent of
  which one "wins."
- Enough evidence to make an informed default choice (dense) while
  preserving a documented, real alternative (hybrid) for the query types
  where it measurably helps, rather than picking one blindly.

If pushing toward 0.9 continues:
- **The eval set itself is the likely limiting factor now, not the
  retrieval methods.** 17 scored queries, 6 of them single-relevant-PMID
  (near-binary), is not enough signal to reliably separate close
  configurations — most of the deltas in §6-7 are within noise range of
  each other. A larger eval set (50+ queries) with richer relevant-sets
  per query would be the highest-value next investment, likely above any
  further retrieval-method tuning.
- A genuinely unbiased embedding-model comparison needs a pool built from
  each candidate model's own retrieval, not just the production model's
  (§6a's caveat).
- Hybrid's real edge on multi-relevant-PMID queries (§7) suggests it's
  worth keeping available for query types with broad/ambiguous relevance
  (many candidate answers) even though it's not the blanket default.

## 9. Files, requirements, scope discipline

| File | Purpose |
|---|---|
| `retrieval/eval_set.json` | Fixed 19-query eval set (schema v2: 3-way pooled, PMID-level ground truth) |
| `retrieval/build_eval_set.py` | Builds the eval set; the only NIM-calling script for *labeling* in this pass |
| `retrieval/query_expansion.py` | Opt-in query expansion; the only retrieval-*time* NIM usage in this pass |
| `retrieval/measure_recall.py` | PMID-level Recall@10 + latency, works across any index variant / mode / expand flag |
| `retrieval/build_bm25.py`, `build_index.py` | Parameterized (chunk size/overlap, embed model, output dir) so index variants build without disturbing production |
| `retrieval/retriever.py` | `retrieve()`/`retrieve_dense()` (default, dense), `retrieve_hybrid_reranked()` (opt-in hybrid), RRF fusion, reranking, PMID dedup |
| `retrieval/eval_results_*.json` | Full per-query results for every configuration in §7's table |
| `data/index/variants/*/` | bge-base, 256/50, and 384/64 index variants (gitignored like all of `data/`, rebuildable via the build scripts above) |

**Requirements**: `rank_bm25==0.2.2` (Pass 1). No new dependencies in Pass
2 — the stronger embedding model uses the already-present
`sentence-transformers`.

**Scope discipline**: NIM calls in this pass are limited to (a) eval-set
labeling (`build_eval_set.py`, one call per query) and (b) query expansion
generation (`query_expansion.py`, opt-in, one call per query, not part of
the shipped default). BM25, RRF fusion, cross-encoder reranking, the
embedding-model swap, and chunk-size rebuilds are all local, no-API-call
work. No changes outside `retrieval/` and `data/`. `agent/nodes.py` and
`evaluation/` are untouched.
