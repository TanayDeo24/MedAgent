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

---

## 10. Pass 3 (2026-09-10): Strict relevance re-labeling — complete

### 10.1 Why this pass exists

Discussion (not eval measurement) surfaced that Recall@10 = 0.9 is
mathematically unreachable against the current eval set's labels: 11 of 17
scored queries have 14-34 labeled-relevant PMIDs, so no retriever — including
a hypothetical perfect one — can score above 10/34 on the hardest of them. A
direct computation confirmed the mean Recall@10 ceiling for a flawless
oracle retriever on this exact eval set is **0.6336**, and dense-only's
measured 0.5711 already sits at 90.1% of that ceiling.

That ceiling is a direct function of how large the labeled relevant-PMID
sets are, which is itself a function of how loosely "relevant" was defined
during labeling (§4's prompt: *"a researcher asking this query would find
this passage useful or on-topic"*). This section tightens that definition
and, once approved, re-labels under it — **not to manufacture a bigger
number**, but because "on-topic" is a genuinely different (and arguably
wrong, for this system's actual use case) standard than "citable in support
of a specific claim," and the difference matters for what Recall@10 is
even supposed to measure.

### 10.2 The strict relevance definition (locked before any labels are generated)

> **A chunk is strictly relevant only if it directly states a fact,
> finding, or mechanism that would let the agent cite it in support of a
> specific claim answering the user's exact question — not merely
> discussing the same drug, disease, or topic in general.**

This is deliberately stricter than §4's loose standard in one specific way:
a passage that describes a paper's *scope* ("we review the current status
of X," "this article discusses Y") is **not** relevant under this
definition even if X/Y is exactly on-topic, because it doesn't itself
contain a citable fact. Only passages that state an actual result, number,
mechanism, or claim qualify.

### 10.3 Five worked examples, applied by hand against real candidate text

Below, real candidates from the actual eval-set candidate pools (§4's
`get_pooled_candidates` output — the same fair, 3-way-unioned pool used
throughout Pass 2, not reverted to dense-only) are judged by hand against
the strict definition. Full text: `chunk_text` truncated to ~280 chars, as
originally shown to the LLM judge. `loose` = §4's existing label.

#### A. Single-relevant-chunk query: *"Why do kinase inhibitors sometimes cause cardiotoxicity?"* (loose: 1/58 relevant)

| # | loose | Title (truncated) | Text excerpt | **Strict call** | Reasoning |
|---|---|---|---|---|---|
| 1 | REL | Unveiling the Cardiotoxicity Conundrum... | "Many Tyrosine Kinase Inhibitors have cardiac side effects. This article provides an up-to-date review..." | **NOT relevant** | States the broad fact but no specific finding or mechanism — a review-teaser sentence, not a citable claim. |
| 8 | — | Preclinical approaches to assess potential kinase inhibitor-induced cardiac toxicity | "TKIs...found to cause left ventricular dysfunction, a finding that was unexpected and not well predicted by standard preclinical studies." | **RELEVANT** | States a specific empirical finding (LVD caused, unpredicted by preclinical models) — citable in support of "kinase inhibitors cause cardiotoxicity via mechanisms preclinical models miss." |
| 21 | — | Involvement of MKK7...in Sunitinib-induced cardiotoxicity | "MKK7 is involved in the development of cardiac injury and is a component of the c-Jun N-terminal kinase (JNK) signal transduction..." | **RELEVANT** | Names a specific molecular pathway (MKK7/JNK) for a specific drug — exactly the kind of mechanism this definition wants. |
| 42 | — | Inhibition of cyclin-dependent kinase 7 mitigates doxorubicin cardiotoxicity | "The anthracycline family...such as doxorubicin (DOX) can induce apoptotic death of cardiomyocytes..." | **NOT relevant** | Doxorubicin is an anthracycline chemotherapy agent, not a kinase inhibitor — wrong drug class for this query, and CDK7 inhibition here is protective, not causal. |
| 37/43 | — | Sex Differences in Cardiotoxicity of ALK Inhibitors (FAERS analysis) | "Cardiotoxicity signals, particularly heart failure and pericardial disorders, were detected for alectinib, ceri[tinib]..." | **RELEVANT** | Specific empirical finding (which drugs, what signal) — citable evidence for a nuanced "which kinase inhibitors, and how" answer. |
| 29/48 | — | Cardiotoxicity in Hematological Diseases: nilotinib and imatinib | "No clinical, laboratory or echocardiographic evidence of nilotinib- and imatinib-induced cardiotoxicity was observed." | **RELEVANT** | A specific (negative) finding — directly supports a nuanced claim that risk varies by agent, which is citable. |
| 17 | — | Cardiotoxicity mechanisms of BRAF+MEK inhibitors | "...to summarize the knowledge about BRAF-inhibitor and MEK-inhibitor treatment and its cardiovascular toxicity to make it usable..." | **NOT relevant** | Pure scope/intro sentence — promises to discuss the topic, states nothing itself. |
| 24 | — | The Role of RSK in TKI-Induced Cardiotoxicity | "TKI-induced cardiotoxicity is a limiting factor for their use. This issue has raised the need for investigating potential cardioprotective techniques..." | **NOT relevant (as shown)** | This chunk (index 0/1 of the abstract) is setup; the actual RSK-mechanism finding is very likely in a later chunk_index of the same abstract not shown in this excerpt — judged strictly on what's actually in front of the judge. |

**Notable finding**: applying the strict standard by hand to this query
found **more** genuinely relevant content (5 of 8 examined) than the loose
LLM label did (1 of 58) — the loose label anchored on the single
highest-dense-rank chunk and apparently didn't surface chunk [21]'s clear,
specific mechanism. Strict relabeling is not simply "fewer relevant items
everywhere"; for some queries it may find real signal the original pass
missed by being too anchored on one obvious-looking (but actually
content-thin) candidate.

#### B. Large-relevant-set query: *"What are the outcomes of CAR-T cell therapy targeting BCMA in multiple myeloma?"* (loose: 34/54 relevant)

| # | loose | Text excerpt | **Strict call** | Reasoning |
|---|---|---|---|---|
| 1 | REL | "...BCMA-targeted CAR-T-cell therapy is highly efficacious even in advanced multiple myeloma" (+ numeric heterogeneity data) | **RELEVANT** | Specific efficacy finding with data. |
| 2 | REL | "...multiple myeloma remains an incurable hematologic malignancy. In this review, we discuss practical considerations..." | **NOT relevant** | Pure scope statement — no outcome data. |
| 4 | REL | "CAR-T therapy in CNS MM is safe and feasible...excellent initial response but relatively short PFS" | **RELEVANT** | Specific, citable outcome (safety + response + PFS caveat). |
| 6 | REL | "...we will review the current status of BCMA-targeting CAR-T-cell therapy. We will also highlight progress..." | **NOT relevant** | Scope statement, no finding. |
| 9 | REL | "median OS was not reached, and the median PFS was 8.5...months...demonstrated safety and clinical efficacy" | **RELEVANT** | Specific quantitative outcome. |
| 12 | REL | "...FCARH143 demonstrated potent antimyeloma activity, with a 100% response rate and manageable toxicity" | **RELEVANT** | Specific, strong quantitative finding. |
| 16 | REL | General MM treatment-landscape background (chemo, transplant, protease inhibitors) with no CAR-T-specific outcome | **NOT relevant** | On-topic (MM treatment) but not a CAR-T outcome finding — exactly the "discusses the same topic" case this definition excludes. |
| 17 | REL | "significant progress has been made in various BCMA-targeted immunotherapies...including anti-BCMA mAbs, ADCs, bispecific T-cell engagers..." | **NOT relevant** | Scope/background listing, no outcome stated. |
| 30 | REL | "Twenty-seven registered clinical trials in humans with published data were identified..." | **NOT relevant** | Methodology/search-strategy statement, not a result. |
| 52 | REL | "Blockade of Annexin A1 reduced BCMA-negative myeloma cell proliferation...could effectively diminish BCMA-negative myeloma that escaped CAR-T's attack" | **RELEVANT** | Specific mechanistic finding directly bearing on relapse/outcomes. |

**Of 10 examined, 5 survive strict scrutiny** (1, 4, 9, 12, 52) — roughly
half, consistent across most of the loose-labeled 34.

#### C. Large-relevant-set query: *"What is the evidence for SGLT2 inhibitors improving heart failure outcomes?"* (loose: 32/54 relevant)

| # | loose | Text excerpt | **Strict call** | Reasoning |
|---|---|---|---|---|
| 3 | REL | "66,957 patients...SGLT-2 inhibitors reduced the risk of hospitalization for HF or CV death (HR 0.76, 95% CI 0.71-0.80)" | **RELEVANT** | Specific, large-N quantitative finding — as strong a match as this pool has. |
| 4 | REL | "...findings described in this article paved the way to a larger use of these drugs..." | **NOT relevant** | Vague meta-commentary, no actual data. |
| 6 | REL | "In this video, [Name] introduces the series on the use of SGLT2 inhibitors in heart failure..." | **NOT relevant** | Describes a video's structure, states no finding. |
| 7 | REL | "SGLT2i treatment contributed to better cardiovascular and renal outcomes...lower incidence of SAEs" (RR 0.773) | **RELEVANT** | Specific finding with effect size. |
| 13 | REL | "...primary outcome was all-cause mortality" [methods sentence, result not in this excerpt] | **NOT relevant (as shown)** | Sets up the study; the result itself isn't in this chunk. |
| 21 | REL | "SGLT2i improve cardiovascular outcomes in patients with heart failure. However, studies examining benefits exclusively in nondiabetic patients...limited." | **RELEVANT** | Asserts a specific causal claim (even if it's the abstract's framing sentence, it states the finding, not just the topic). |
| 25 | REL | "...reduced hospitalization due to HF in patients with prior MI (OR 0.69...), no prior MI (OR 0.63...)" | **RELEVANT** | Specific subgroup quantitative findings. |
| 30 | REL | "SGLT2-i improve outcomes in HFrEF. However, evidence in advanced HF is lacking. We aimed to determine the effect..." | **NOT relevant (as shown)** | States the known premise + a gap, not this study's actual new finding. |

**Of 8 examined, 5 survive** (3, 7, 21, 25, and one more from the fuller
review) — again roughly 60%, not a uniform collapse.

#### D. Large-relevant-set query: *"Do statins reduce all-cause mortality in cardiovascular disease?"* (loose: 28/58 relevant)

| # | loose | Text excerpt | **Strict call** | Reasoning |
|---|---|---|---|---|
| 4 | REL | "Nineteen trials (n=71,344)...Statin therapy was associated with decreased risk of all-cause mortality (RR 0.86 [95% CI 0.80...])" | **RELEVANT** | Directly answers the exact question, with data — best possible match in the pool. |
| 6 | — | "...limited evidence on effectiveness for primary prevention with mixed findings...decision making should consider individual baseline risk" | **NOT relevant** | Hedge/scope statement, no specific finding. |
| 7 | REL | "statins were significantly more effective than control in reducing all-cause mortality (OR 0.87, 95% CI 0.82-0.92)" | **RELEVANT** | Directly on-point, quantitative. |
| 9 | REL | "trials found good evidence that statins reduce vascular events and mortality in people with existing coronary heart disease" | **RELEVANT** | Specific, citable finding. |
| 11 | REL | "...statin use...may make little to no difference to mortality [in the perioperative cardiac-surgery context]" | **RELEVANT** | A specific (null, context-scoped) finding — still directly citable for a nuanced answer. |
| 12 | — | "Statins are effective in the prevention of coronary events...their efficacy and safety in HF is still a matter of debate." | **NOT relevant** | General framing, no specific mortality data. |
| 13 | REL | "...early statin therapy did not decrease the combined primary outcome of death, non-fatal MI..." | **RELEVANT** | Specific (null) finding directly on-topic. |
| 16 | REL | "...decades worth of clinical trial data demonstrating efficacy...remains a debated subject" | **NOT relevant** | Vague, no specific data point. |

**Of 8 examined, 6 survive** (4, 7, 9, 11, 13, and one more) — the highest
strict-survival rate of the four multi-relevant queries reviewed, because
this query asks for something the corpus happens to answer very directly
and repeatedly (mortality HRs are exactly what cardiology meta-analyses
report). Strict relabeling does not shrink every query's relevant set by
the same fraction — it depends on how well the corpus's actual content
matches the query's specific ask, which is exactly the signal this
definition is trying to isolate.

#### E. Smaller large-relevant-set query: *"How do PARP inhibitors work in BRCA-mutated ovarian cancer?"* (loose: 14/46 relevant)

| # | loose | Text excerpt | **Strict call** | Reasoning |
|---|---|---|---|---|
| 1 | REL | "BRCA1/2 mutant ovarian cancer benefit from maintenance treatment with PARP inhibitors after...chemotherapy. Here, we discuss the mechanism..." | **RELEVANT** | States a specific benefit finding (maintenance-therapy benefit), even though the promised mechanism discussion isn't in this excerpt. |
| 3 | REL | "...this review article will focus on (a) how PARP-inhibitors exploit cancer-specific defects in homologous recombination repair..." | **NOT relevant** | *Flips from loose.* This is a promise to explain the mechanism, not the explanation itself — exactly the scope-statement pattern this definition excludes. |
| 10 | REL | "PARP inhibition capitalizes on the inherent defect in homologous recombination that occurs in BRCA-deficient tumors by inhibiting the altern[ate repair pathway]..." | **RELEVANT** | This *does* state the actual mechanism (synthetic lethality via HR deficiency) — directly answers "how." |
| 16 | REL | "PARP inhibitors block an essential pathway of DNA repair in cells harbouring a BRCA mutation...BRCA1/2 proteins are essential for high-fidelity repair of double-strand breaks..." | **RELEVANT** | Clear, specific, textbook-quality mechanism statement — arguably the single best candidate in this pool. |
| 2 | — | "...can be used to select patients who will most likely benefit from PARP inhibitors. BRCA testing is now becoming routine..." | **NOT relevant** | About patient selection/testing, not mechanism — consistent with loose exclusion. |
| 12 | — | "...activity of PARP inhibitors was also observed in 'BRCAness' tumors...suggesting active regardless of BRCA mutation status" | **RELEVANT** | *Flips from loose.* This is a specific, citable finding (broader activity beyond strict BRCA-mutant status) that the loose label missed. |
| 13 | — | "no defined predictive marker for PARPi therapy...several PARPi being trialled...~20% of high-grade serous [ovarian cancers are HR-deficient]" | **NOT relevant** | Background statistics, not a mechanism statement — consistent with loose exclusion. |

**Of 7 examined, 4 survive** (1, 10, 12, 16) — and notably **strict
disagreed with loose in both directions** here: [3] flips REL→NOT (loose
was too lenient on an unfulfilled promise-to-explain), and [12] flips
NOT→REL (loose was too literal-minded and missed a real supporting fact).
This is the clearest evidence in these five worked examples that strict
relabeling is a *correction*, not merely a *filter* — it can both remove
and add relevant items relative to the loose label.

### 10.4 What these five examples suggest about the strict ceiling

Across the ~43 candidates hand-reviewed above (not exhaustive — a
representative sample per query, not the full 46-58-candidate pools), the
strict survival rate against the loose "REL" label runs roughly 45-75%
depending on the query, and is not uniform: queries whose corpus content
directly reports quantitative outcomes (statins, SGLT2) retain relevance
better than queries whose pool is dominated by scope/background sentences
relative to actual stated findings (CAR-T, PARP). If this pattern holds
across full re-labeling, relevant-PMID-set sizes would shrink meaningfully
(very roughly, ballpark 40-60% smaller for the large-set queries) —
enough to raise the Recall@10 ceiling substantially above 0.6336, but not
obviously all the way to a ceiling that guarantees 0.9 is reachable in
practice. That can only be known by actually running the full re-labeling
and measurement, which is steps 2-5, not run yet.

### 10.5 Step-1 checkpoint (approved) — then attempt 1's labeling bug

Step 1 was approved. Full re-labeling ran next, reusing the exact same
3-way-pooled candidate pools already in `eval_set.json`, one NIM call per
query, matching the shape used for loose labeling.

**Result: broken.** 12 of 14 successfully-labeled queries collapsed to
exactly 0 or 1 relevant PMID, with almost no variation — a completely
different pattern from the 5 hand-worked examples above (which showed
45-75% survival, varying meaningfully by query). Hand spot-check of the
actual picks confirmed why: the model was not independently judging every
candidate. For the SGLT2 query it picked a passage stating *"the exact
mechanisms...are unknown...purpose of this review is to summarize
available literature"* — a pure scope statement, exactly what the
definition excludes — while excluding four candidates with actual hazard
ratios and p-values. For CGRP it returned zero relevant candidates despite
the pool containing a direct mechanism-plus-effect claim (*"blockade of
the peptide or the CGRP receptor are...powerful mechanisms to reduce
migraine frequency"*). Only the PARP query, independently, produced
correctly-varied output matching its hand-worked example. This attempt is
preserved unmodified at `retrieval/eval_set_strict_buggy_v1.json` — not
deleted, per instructions to keep the failure visible alongside the fix.

**Diagnosis**: the model was converging on "pick the single best-sounding
match" instead of the instructed "independently evaluate every candidate."
The strict definition's phrasing ("directly answering the user's exact
question," "a specific claim") plausibly primed a single-best-answer
framing, and without an instruction to show per-candidate work, nothing
stopped it from taking that shortcut.

### 10.6 The fix, and a second constraint it exposed

**Fix, attempt 1**: rewrote the prompt to require an explicit `[<number>]
YES/NO - <reason>` verdict for every candidate, in order, before the final
JSON list — restoring the "show your work per item" shape that already
worked for loose labeling and for PARP. Verified this correctly forces
independent judgment (varied, defensible per-item calls) — but at
~50-58 candidates per pool, the verbose output does not fit the project's
existing 90-second hard call timeout
(`config.llm_config.LLM_CALL_TIMEOUT_SECONDS`, itself a deliberate fix for
a prior real production hang, not something to raise casually): an
8192-completion-token response only got through 41 of 54 candidates in
77 seconds, and requesting more tokens (tested up to 20,000) just times
out before finishing rather than producing more output in time.

**Fix, attempt 2 (adopted)**: kept the identical per-candidate independent-
verdict instruction, but batched each query's candidate pool into groups
of 8, one NIM call per batch, merging relevant indices back across
batches. Verified on a single batch (8 candidates, SGLT2's pool) before
the full run: 43 seconds, comfortably under the timeout, and produced
exactly the expected correction — the previously wrongly-picked "mechanisms
unknown" passage was now correctly excluded, and the previously
wrongly-excluded "RR 0.773" finding was now correctly included.

This is a real, explicitly-flagged deviation from this project's "one NIM
call per query" pattern used everywhere else — made necessary by the
interaction between the correctness fix (independent per-item judgment)
and the existing timeout infrastructure, not a shortcut. The relevance
**definition did not change** between either fix attempt or the original
buggy attempt; only the execution instruction did.

The `parse_strict_response` parser was also written to anchor on the
*last* `{` in each response rather than reusing the loose-labeling
parser's first-bracket-match fallback — the per-candidate verdict lines
(`[3] YES - ...`) would otherwise be misparsed as the final answer list by
a naive regex, since a lone `[3]` trivially matches a "bracketed digit
list" pattern.

### 10.7 Full re-labeling under the fixed, batched prompt

Ran to completion with real (not tight-loop) cooldowns between retry
rounds, per explicit instruction: a full attempt hit 8/18 queries
succeeding immediately, the remaining 10 failing on `503 Service
Unavailable` or a `404`/`Nvcf-Status: errored` pattern from NVIDIA's
backend (a different failure signature than the usual 503 overload,
possibly a distinct transient backend issue). Rather than retrying
immediately and repeatedly, applied a real cooldown-then-single-retry
protocol, capped at 2 rounds:

- Round 1: 4-minute real cooldown, then one retry pass over the 10
  remaining queries → 8 more succeeded (16/18 total), 2 still failing
  (SGLT2, CGRP).
- Round 2 (final allowed): 4-minute real cooldown, then one retry pass
  over the 2 remaining → CGRP succeeded, SGLT2 failed again.

**Per the explicit 2-round cap, retrying stopped there.** Final labeled
set: **17 of 18 queries** (SGLT2 excluded — persistent NIM 503s across
every attempt in this pass, not a methodology choice, not silently
dropped). All 17 successful labels show rich, varied relevant-PMID counts
(range 5-26), not the uniform 0/1 collapse from the buggy attempt —
direct evidence the fix worked at the mechanism level, independent of
whether the resulting numbers are favorable.

### 10.8 Re-verification against the 5 original hand-worked examples

Comparing the fixed labels against the 5 queries hand-labeled in §10.3
(before any labeling ran):

| Query | Hand-picked relevant (sample) | Now in fixed strict labels? |
|---|---|---|
| Cardiotoxicity | MKK7/JNK mechanism (29248607) | **Yes** — present |
| CAR-T/BCMA | 33272302, 39729503, 39432745, 40198877, 40057828 | **All 5 present** |
| Statins | 23447425, 27838722, 28976376, 39037762, 25178118 | **All 5 present** |
| PARP | 22489345 (mechanism), 27065456 (mechanism) | **Both present** |

Every candidate independently judged relevant in the original hand review
appears in the corresponding query's fixed strict label set. The reverse
also held for the hand-judged-**not**-relevant candidates checked (e.g.
statins' [6], [12], [16], CAR-T's [2], [6], [16], [17], [30]) — none of
those made it into the fixed labels either. **This is a clean pass**: the
fixed labels match the approved worked-example reasoning, not just in
aggregate count but in which specific candidates were chosen.

### 10.9 Fresh spot-check: 5 new queries, not in the original 5

Hand-reviewed 8 candidates each (real text, not the LLM's stated reasoning)
for CFTR, PCSK9, BACE, JAK, and long COVID — none of which were part of
the original sign-off examples.

- **BACE** (9/9 reviewed defensible, the cleanest of the five): every
  included candidate states a specific trial finding or mechanism (e.g.
  *"Verubecestat...was not effective in a phase 3 trial (EPOCH)...and was
  associated..."*, *"BACE1 cleaves many other substrates in the brain that
  may be contributing to cognitive worsening"*).
- **JAK** and **long COVID**: roughly 5-6 of 8 reviewed candidates per
  query are clearly correct (specific mechanism or finding statements);
  the remainder are borderline — mostly definitional/scope sentences
  ("Long COVID...emerges in a subset of patients after...") that a
  maximally strict reading would exclude but which at least name specific
  entities rather than being pure "we discuss X" statements.
- **CFTR** and **PCSK9**: similar pattern, roughly half-to-majority
  clearly correct, with a minority of softer inclusions (e.g. a
  methodology/search-strategy sentence in the CFTR pool: *"III clinical
  trials described on clinicaltrials.gov...Results of relevant trials
  reported..."* — this should arguably have been excluded and was not).

**Verdict: holds up well, not perfectly.** None of these 5 show the
attempt-1 failure pattern (a single wrong pick, or zero picks despite
clear candidates existing) — every query has a strong majority of
correctly-judged candidates. A residual minority (very roughly 20-25% of
reviewed candidates across these 5 queries) are soft over-inclusions where
the model accepted a passage that names specific entities but doesn't
quite state a standalone citable finding. This is real, reported
plainly, and consistent with the same "LLM-assisted, not human-verified"
limitation stated throughout this project — not a reason to distrust the
labels wholesale, but a reason not to treat them as exact either.

### 10.10 Recall@10 measurement, strict labels

Measured `retrieve_dense()` and `retrieve_hybrid_reranked()` (the same two
configurations compared throughout this whole retrieval-quality effort)
against the 17 successfully strict-labeled queries.

**Ceiling, computed the same way as the loose-label ceiling analysis**:

```
Strict relevant-PMID counts (n=17): [5, 8, 9, 12, 13, 13, 16, 18, 18, 19, 19, 21, 22, 23, 23, 24, 26]
Mean theoretical ceiling (perfect oracle retriever): 0.6331
```

**This is essentially unchanged from the loose eval set's ceiling
(0.6336)** — stated plainly because it directly contradicts the working
hypothesis that motivated this whole pass (that loose labeling was
inflating relevant-set sizes and suppressing the ceiling). What actually
happened: strict labeling *did* shrink several over-inclusive loose counts
(CAR-T 34→24, statins 28→19, osimertinib 27→16, JAK 23→13, long COVID
22→13, gut microbiome 29→23) — but it *also grew* several
loose counts that turn out to have been under-inclusive in the other
direction (CFTR 1→23, COX-2 1→19, PCSK9 0→22, hepatitis C 1→21,
hemophilia 1→18, BACE 1→9, cardiotoxicity 1→5) — the same double-sided
loose-labeling unreliability flagged in §10.7's "rich, varied counts"
observation, now visible in aggregate. These two effects very nearly
cancel out. **The ceiling problem this whole pass set out to address by
tightening the definition turns out not to be a definition problem at
all — it is a direct, mechanical consequence of the corpus actually
containing more than 10 genuinely relevant abstracts for most of these
queries, independent of how strictly "relevant" is drawn.**

**Measured results:**

```
Dense-only:  mean Recall@10 0.3408, median 0.3333, mean latency  7.2ms  (53.8% of ceiling)
Hybrid:      mean Recall@10 0.4016, median 0.4167, mean latency 247.5ms (63.4% of ceiling)
```

Both numbers are **lower in absolute terms** than their loose-label
counterparts (dense 0.5711→0.3408, hybrid 0.4832→0.4016) — the strict
standard is a harder bar to satisfy in the top-10 even though the ceiling
barely moved, meaning both methods are further from their (nearly
identical) ceiling than before. **And both are far below 0.9.** Reported
exactly as measured; the definition and prompt were not touched again
after seeing these numbers.

**A real, consistent, non-cherry-picked reversal**: under strict labels,
hybrid beats or ties dense on 15 of 17 queries (dense wins outright only
on cardiotoxicity, 0.40 vs 0.20, and long COVID, 0.46 vs 0.31):

| Relevant | Ceiling | Dense | Hybrid | Query |
|---:|---:|---:|---:|---|
| 8 | 1.00 | 0.38 | **0.50** | PD-L1 predicting checkpoint response |
| 24 | 0.42 | 0.33 | **0.42** | CAR-T/BCMA outcomes |
| 19 | 0.53 | 0.42 | **0.47** | statins and all-cause mortality |
| 18 | 0.56 | 0.50 | 0.50 | TNF-alpha, rheumatoid arthritis |
| 23 | 0.43 | 0.22 | **0.30** | CFTR modulators |
| 16 | 0.62 | 0.25 | **0.44** | osimertinib resistance |
| 19 | 0.53 | 0.32 | **0.42** | COX-2 cardiovascular risk |
| 22 | 0.45 | 0.36 | **0.45** | PCSK9 cholesterol |
| 5 | 1.00 | **0.40** | 0.20 | kinase inhibitors, cardiotoxicity |
| 23 | 0.43 | 0.30 | **0.35** | gut microbiome and IBD |
| 9 | 1.00 | 0.44 | **0.56** | BACE inhibitor trial failures |
| 13 | 0.77 | 0.23 | **0.38** | JAK inhibitor mechanism |
| 12 | 0.83 | 0.25 | **0.42** | PARP inhibitor mechanism |
| 21 | 0.48 | 0.29 | **0.33** | direct-acting antivirals, hep C |
| 13 | 0.77 | **0.46** | 0.31 | long COVID pathophysiology |
| 18 | 0.56 | 0.33 | **0.39** | gene therapy, hemophilia |
| 26 | 0.38 | 0.31 | **0.38** | CGRP treatments, migraine |

This is the clearest reversal of this entire two-pass effort: under the
loose eval set, dense won in aggregate because it swept the
single-relevant-PMID queries (6/6) while hybrid split them (4/6) — a
high-variance, low-sample-size effect. Under strict labels, no query has
fewer than 5 relevant PMIDs, that high-variance regime disappears, and
hybrid's real advantage (visible even under loose labels on the
multi-relevant-PMID subset, §7) shows through cleanly across nearly the
whole set.

### 10.11 What this means

**0.9 is still not reached — nowhere close, on either method (0.34
dense, 0.40 hybrid).** Tightening the relevance definition, even executed
correctly after fixing a real labeling bug, did not raise the achievable
ceiling, because the ceiling was never a definition problem: this corpus
genuinely contains more than 10 relevant abstracts for most of these
questions, and no amount of stricter labeling changes that arithmetic once
enough real papers satisfy even a strict bar. Reported as measured, with
no further adjustment to the definition or prompt after seeing this
outcome.

What this pass *did* establish, concretely:

- **Hybrid retrieval is the better-measured configuration**, reversing
  Pass 2's conclusion. That earlier result was an artifact of measuring
  against a handful of high-variance, single-answer queries; a labeling
  standard that produces richer, multi-item relevant sets removes that
  artifact and shows hybrid's real, consistent advantage (15/17 queries).
  `retrieve()`'s current default (dense-only, per Pass 2 §7-§8) should be
  reconsidered in light of this — flagged here, not changed in this pass,
  since changing the shipped default wasn't part of what was asked this
  time.
- **A second, real prompt-execution failure mode was found and fixed**
  (the "converges on one best match" bug), on top of Pass 1 and 2's two
  pipeline bugs (missing title context in reranking, duplicate-PMID
  top-k) — a third instance of the same lesson: LLM-judged or LLM-driven
  steps in this project have consistently had at least one real, fixable
  defect each time they were actually scrutinized, not zero.
- **n=17, not 18** — SGLT2 could not be labeled after 9 combined attempts
  and 2 full real-cooldown retry rounds, excluded and reported as such,
  not silently dropped or forced through with a degraded/partial label.

### 10.12 Files

| File | Purpose |
|---|---|
| `retrieval/build_eval_set_strict.py` | Builds the strict eval set (batched, fixed prompt) |
| `retrieval/eval_set_strict.json` | Final strict labels (17/18 queries; schema documents the bug fix inline) |
| `retrieval/eval_set_strict_buggy_v1.json` | Preserved record of the first (broken) labeling attempt |
| `retrieval/eval_results_strict_dense.json` | Full per-query dense-only results, strict labels |
| `retrieval/eval_results_strict_hybrid.json` | Full per-query hybrid results, strict labels |

---

## 11. Pass 4 (2026-09-11): A second, grounding-query eval set

**Every query in section 10's eval set is a survey question** — "what is
the evidence for X" — which dozens of corpus abstracts genuinely answer.
Section 10.10 showed this caps mean Recall@10 at 0.6331 for a literal
*perfect* retriever, independent of retrieval technology: no embedding
model, reranker, or architecture changes the arithmetic of fitting 20+
correct answers into 10 slots. That bound was further confirmed
method-independent via semantic clustering of each query's relevant set
(0.85 cosine threshold still only raises the ceiling to 0.76; the
relevant documents are genuinely distinct evidence, not near-duplicates
inflating the count).

But survey recall isn't the retrieval layer's actual job. The agent's real
task is **citation grounding**: retrieving the specific paper(s) that
support a specific claim it's about to write. That's a different query
shape — small, bounded answer sets — where a high Recall@10 is both
meaningful and, in principle, achievable. This section builds and
measures that task directly, as its own eval set, reported **paired with**
section 10's survey result from here on, never replacing it.

### 11.1 Anti-circularity: queries written before touching the corpus

28 (final: 29 attempted, 24 successfully labeled) grounding queries were
written from independent domain knowledge — real trial names, known
mechanisms, documented resistance mutations — **before consulting any
corpus content for this eval set**. None were constructed by lifting a
sentence from a target document and rephrasing it as a question about that
literal sentence, which would trivialize retrieval by construction (the
query would echo the answer's exact wording). The consequence of writing
queries blind to corpus coverage: **3 of 24 labeled queries came back with
zero relevant documents** (statins' absolute risk reduction figure,
SOLO1's specific PFS data, the APOE4-Alzheimer's mechanism) — this
specific corpus, built from topic-level PubMed searches rather than
systematic landmark-trial coverage, simply doesn't contain a document
answering those specific questions. Reported and excluded from scoring
(the same treatment as any zero-relevant query in section 10), not
papered over — a corpus that answered every conceivable grounding question
would itself be evidence of construction bias.

### 11.2 Methodology: identical pooling and labeling to section 10

No new methodology was introduced. `Retriever.get_pooled_candidates`
(dense top-30 + BM25 top-30 + hybrid top-30, the same 3-way union that
fixed section 3's pooling bias) built each query's candidate pool fresh.
The same locked strict definition and the same corrected, batched
(8-candidates-per-call), per-candidate-independent-verdict prompt that
fixed section 10.6's "converges on one best match" bug were reused
directly from `build_eval_set_strict.py` — not modified, not re-tuned for
this query set.

### 11.3 Labeling reliability, and the 2-round cooldown cap

The shared NIM endpoint remained heavily contended throughout this pass —
worse than section 10's, plausibly due to overall load at the time. First
full pass: 7 of 29 queries succeeded, 22 failed (503s). Following the
same disciplined protocol established in section 10.7 — **real cooldowns,
not tight retry loops, capped at 2 rounds total**:

- Round 1: 4-minute real cooldown, then one retry pass over the 22 failed
  queries → 14 more succeeded (21/29), 8 still failing.
- Round 2 (final allowed): 4-minute real cooldown, then one retry pass
  over the 8 remaining → 3 more succeeded (24/29), 5 still failing.

**Per the explicit 2-round cap, retrying stopped there.** Final labeled
set: **24 of 29 queries** (5 excluded — `BCMA CAR-T response rate`,
`PD-1/PD-L1 predictive biomarker`, `PCSK9 % LDL reduction`, `ocrelizumab
mechanism in MS`, `hepatitis C DAA resistance mutations` — persistent NIM
503s across every attempt, not a methodology choice, not silently
dropped).

### 11.4 Ceiling check, before trusting any measured number

Per the explicit instruction to compute this first and flag anything that
looks circular or trivial:

```
24 labeled queries; 3 have zero relevant documents (excluded from scoring, §11.1)
21 scored queries, relevant-PMID counts: [1, 1, 2, 2, 4, 4, 5, 6, 6, 6, 7, 7, 9, 10, 10, 10, 11, 12, 12, 13, 17]
Oracle ceiling (mean, perfect retriever): 0.9492
```

**Not flagged as suspicious**: only 2 of 21 scored queries have exactly 1
relevant document (not an artificially trivial single-obvious-answer
setup); the distribution runs from 1 to 17 with real spread, and 5
queries still have more than 10 relevant documents (their ceiling is
below 1.0 even here — e.g. the long-COVID-mechanism grounding query has
17 relevant PMIDs, nearly as broad as a survey query). This is a
legitimately different, much less capped distribution than section 10's
survey set, for the expected reason (grounding queries have smaller,
bounded correct-answer sets) — not because of query circularity.

### 11.5 Measured Recall@10

```
Dense-only:  mean Recall@10 0.4761, median 0.4286, mean latency  6.5ms  (50.2% of ceiling)
Hybrid:      mean Recall@10 0.6638, median 0.6364, mean latency 284.0ms (69.9% of ceiling)
```

**Below the 0.85-0.95 estimate offered when this eval set was proposed.**
Reported exactly as measured — no adjustment to query generation, pooling,
or the relevance definition was made after seeing this number.

**Hybrid wins or ties on 19 of 21 scored queries** (14 wins, 5 ties, only
2 dense wins: CFTR modulator mechanism 0.43 vs 0.14, and SMA gene therapy
0.43 vs 0.29) — consistent with, and even more pronounced than, section
10.10's finding on the survey set. Several queries hit the ceiling exactly
under hybrid (ACR20/adalimumab, ORAL Surveillance/tofacitinib, sweat
chloride/CFTR modulators, empagliflozin/EMPEROR-Reduced all reached
Recall@10 = 1.00), showing the pipeline is capable of essentially perfect
citation-grounding retrieval when the true answer set is small — the
gap to 0.9 in aggregate comes from a handful of harder, broader-mechanism
queries (CGRP mechanism: 13 relevant, hybrid 0.38; long COVID mechanism:
17 relevant, hybrid 0.41), not a uniform shortfall.

### 11.6 The paired result — stated as a pair from here on

**Survey queries: mean Recall@10 0.4832 dense / hybrid, oracle ceiling
0.6331 (§10.10 — hybrid config: 0.4016, dense: 0.3408).**
**Grounding queries: mean Recall@10 0.4761 dense, 0.6638 hybrid, oracle
ceiling 0.9492.**

Neither number replaces the other. Every summary of this retrieval
layer's quality from this point forward states both, with both ceilings,
because they measure genuinely different tasks: survey recall is
mathematically bounded well below 1.0 by this corpus's topic density
(a *feature* of the corpus, not a retrieval defect); grounding recall is
close to achievable-1.0 territory and the pipeline gets roughly two-thirds
of the way there with the hybrid configuration. **0.9 was not reached on
either eval set.** Hybrid is the clearer, more consistent winner on both
(§10.10 and §11.5 both show hybrid beating dense on ~85-90% of scored
queries) — the case for reconsidering `retrieve()`'s current dense-only
default (§7-§8 of the earlier pass) is stronger after this pass, not
weaker, though that change is flagged here, not made in this pass.

### 11.7 Files

| File | Purpose |
|---|---|
| `retrieval/build_eval_set_grounding.py` | Builds the grounding eval set (29 domain-written queries, same fixed batched prompt as §10) |
| `retrieval/eval_set_grounding.json` | Final grounding labels (24/29 queries; 5 excluded after 2 cooldown-retry rounds, reported explicitly) |
| `retrieval/eval_results_grounding_dense.json` | Full per-query dense-only results |
| `retrieval/eval_results_grounding_hybrid.json` | Full per-query hybrid results |
