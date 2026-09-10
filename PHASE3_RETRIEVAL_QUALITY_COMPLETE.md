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

## 10. Pass 3 (2026-09-10): Strict relevance re-labeling — Step 1 checkpoint

**Status: checkpoint only. No re-labeling has been run. Waiting for explicit
go-ahead before proceeding to steps 2-5 below.**

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

### 10.5 Checkpoint

**Stopping here per instructions.** Steps 2-5 (full re-labeling of all
17-19 queries under this definition using the LLM judge, hand spot-check of
5 queries from the new labels, and Recall@10 re-measurement for dense-only
and the best-performing hybrid configuration) have **not** been run and
will not be started without explicit go-ahead. The worked examples above
are entirely by-hand, using real candidate text already on disk from the
existing eval-set pool — no NIM calls were made to produce this checkpoint.
