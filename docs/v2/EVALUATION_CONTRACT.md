# MedAgent V2 — Evaluation Contract

**Status:** design contract, Phase 1. Defines every metric family MedAgent V2
will be evaluated against. No benchmark data exists yet (`BENCHMARK_PLAN.md`
defines how it will be built, not this document). No metric here has been
computed against V2 — Phase 0's historical numbers (`PHASE0_BASELINE.md`) are
explicitly **not** V2 targets and must never be quoted as if they were.

For every metric: **NAME, FORMULA, UNIT OF ANALYSIS, REQUIRED LABEL, SPLIT,
PRIMARY/SECONDARY, KNOWN LIMITATION.**

---

## 0. Cross-cutting rules

1. **No metric is reported without stating its denominator and sample size.**
   A percentage with no n is not a result.
2. **No headline metric may rely solely on an unvalidated LLM judge.** See
   §7 Judge Validation — a judge must clear a calibration bar before its
   output can be cited as evidence for anything beyond internal development
   iteration.
3. **Primary metrics gate phase completion; secondary metrics are diagnostic.**
   A phase is not "done" because a secondary metric looks good.
4. **All benchmark-based metrics must name benchmark name + version**
   (`BENCHMARK_PLAN.md` §Versioning) in every report.
5. **Test-set metrics are reported once per architecture decision, not
   iterated against.** Development/tuning happens on dev splits only (see
   §Split Policy below and `BENCHMARK_PLAN.md` §Leakage).

---

## 1. Query-Understanding (NLU) Metrics

Unit of analysis throughout this section: **one query**, unless stated
otherwise.

### 1.1 Entity Extraction

| | |
|---|---|
| **Name** | Entity Precision / Recall / F1 |
| **Formula** | Precision = correctly extracted entity spans / all extracted entity spans. Recall = correctly extracted entity spans / all gold entity spans. F1 = harmonic mean. A span counts as correct if it matches a gold span's text and entity type (exact span match; a separate partial-match variant may be reported as secondary). |
| **Unit of analysis** | entity span, aggregated per query then macro-averaged across the NLU benchmark |
| **Required label** | human-reviewed gold entity spans + types (disease, gene/protein, compound, intervention, etc.) per query |
| **Split** | NLU benchmark test split |
| **Primary/Secondary** | Primary |
| **Known limitation** | Entity boundary disagreement (e.g., "KRAS G12C" vs. "G12C") is a real, recurring adjudication problem — the annotation spec (`BENCHMARK_PLAN.md`) must fix a boundary convention before this number means anything comparable across runs. |

### 1.2 Entity Normalization

| | |
|---|---|
| **Name** | Normalization Accuracy@1, Accuracy@k |
| **Formula** | Accuracy@1 = queries where the extracted entity's normalized identifier (MeSH ID / gene ID / ChEMBL ID / disease-ontology ID, as applicable) exactly matches gold / total normalizable entities. Accuracy@k = gold identifier appears in the top-k candidate identifiers returned by the normalizer. |
| **Unit of analysis** | entity mention |
| **Required label** | gold normalized identifier per entity mention (only for entities where normalization is well-defined — free-text descriptive phrases are excluded, not force-normalized) |
| **Split** | NLU benchmark test split |
| **Primary/Secondary** | Primary |
| **Known limitation** | Multiple valid identifier systems can apply to the same entity (e.g., a gene has both a HGNC symbol and an Entrez ID); the annotation spec must pick one target ontology per entity type up front. |

### 1.3 Intent Classification

| | |
|---|---|
| **Name** | Intent Accuracy, Intent Macro-F1 |
| **Formula** | Accuracy = correctly classified queries / total queries, over the question taxonomy classes A–I in `PRODUCT_CONTRACT.md` §3. Macro-F1 = unweighted mean of per-class F1 (protects against the class-imbalance a real query mix will have). |
| **Unit of analysis** | query |
| **Required label** | single gold taxonomy class per query (multi-label allowed only where a query genuinely spans classes, e.g. D and E — annotation spec must define when multi-label is permitted) |
| **Split** | NLU benchmark test split |
| **Primary/Secondary** | Primary |
| **Known limitation** | Class boundaries between D (cross-source) and E (multi-hop) are inherently fuzzy; adjudication guidelines must give concrete disambiguation rules. |

### 1.4 Constraint Extraction

| | |
|---|---|
| **Name** | Constraint Field Precision / Recall / F1 |
| **Formula** | Per constraint field (trial phase, trial status, population, temporal, geographic): precision/recall/F1 computed the same way as entity extraction, but over structured field-value pairs rather than free spans. |
| **Unit of analysis** | (field, value) pair |
| **Required label** | gold structured constraints per query (class G queries in the taxonomy are the primary source of these) |
| **Split** | NLU benchmark test split |
| **Primary/Secondary** | Secondary (primary specifically for class-G–heavy evaluation slices) |
| **Known limitation** | Small expected sample size for constraint-heavy queries unless the benchmark deliberately oversamples class G. |

### 1.5 Source Requirement Prediction

| | |
|---|---|
| **Name** | Source-Set Precision / Recall / F1 |
| **Formula** | Precision = correctly predicted required sources / all predicted sources. Recall = correctly predicted required sources / all gold-required sources. Micro (pooled over all query-source pairs) and macro (averaged per query) both reported. |
| **Unit of analysis** | (query, source) pair |
| **Required label** | gold required source set per query (which of PubMed/ClinicalTrials.gov/ChEMBL a correct answer genuinely needs) |
| **Split** | NLU benchmark test split |
| **Primary/Secondary** | Primary — this is the input to tool-routing evaluation (§2) and the clearest measurable proxy for "did the system understand what kind of evidence this question needs." |
| **Known limitation** | "Required" is itself a judgment call for borderline queries (e.g., a mechanism question could be answered from PubMed alone or PubMed+ChEMBL) — annotation guidelines must define a minimum-sufficient-source-set convention. |

---

## 2. Tool / Source-Routing Metrics

Unit of analysis: **one tool-call decision** unless noted. These metrics are
deliberately **not collapsed into one "tool reliability" percentage** — each
answers a different question about a different failure mode.

| Metric | Formula | Unit | Label | Primary/Secondary |
|---|---|---|---|---|
| **Source precision/recall/F1** | see §1.5 (same metric, reported again here as it gates this stage) | query | gold source set | Primary |
| **Valid-call rate** | schema-valid tool calls / total tool-call attempts | tool call | tool schema (deterministic, no human label needed) | Primary |
| **Execution-success rate** | tool calls returning a successful (non-error) response from the real external API / valid-call attempts | tool call | none (observed live) | Primary |
| **Parameter-correctness rate** | tool calls whose filter/argument values match the query's actual constraints / total valid calls | tool call | human-reviewed gold parameters for a query subset | Secondary |
| **Useful-result rate** | tool calls returning ≥1 result later used as cited Evidence / total successful calls | tool call | derived from claim-evidence links (§4), no separate label needed | Primary |

**Known limitation (whole section):** valid-call rate and execution-success
rate are architecture-dependent — under the current free-form JSON-emit
dispatch (Phase 0 finding: hallucinated tool names observed), valid-call rate
partly measures a mechanism V2 may replace entirely (schema-constrained
native tool calling, Phase 3 gate). Comparing valid-call rate before/after
that architecture change is a legitimate ablation (see `BENCHMARK_PLAN.md`
§Baselines), not a like-for-like historical comparison.

---

## 3. Retrieval Metrics

Defined **separately per source-specific benchmark** (`BENCHMARK_PLAN.md`
§C): PubMed literature retrieval, ClinicalTrials.gov retrieval, ChEMBL
retrieval, plus a cross-source evidence-retrieval benchmark and a multi-hop
benchmark. "Relevant" is defined per-benchmark (see `BENCHMARK_PLAN.md`) since
what counts as a relevant literature abstract, a relevant trial record, and a
relevant compound record are genuinely different judgments.

| Metric | Formula | Unit | Label | Primary/Secondary | Known limitation |
|---|---|---|---|---|---|
| **Recall@K** (K∈{1,5,10,20}) | relevant docs retrieved in top-K / total relevant docs for the query | query | graded or binary relevance judgments per query | Primary | Requires a genuinely complete-enough relevant set per query, or recall is systematically underestimated — pooling methodology must be documented (`BENCHMARK_PLAN.md`). |
| **MRR** | mean of 1/rank-of-first-relevant-result across queries | query | binary relevance | Primary | Only meaningful when "first relevant result" is a well-defined product need (true for single-answer-style queries, less so for evidence-aggregation queries). |
| **Precision@K** | relevant docs in top-K / K | query | binary/graded relevance | Secondary | Penalizes queries with few true relevant docs, even at perfect recall. |
| **nDCG@K** | standard DCG/IDCG formula | query | **graded** relevance labels (not binary) | Secondary, **only reported where graded labels legitimately exist** — never computed from binarized labels dressed up as graded | Do not include this metric on any benchmark that only has binary judgments; that was an explicit failure mode flagged by the Phase 0 audit (nDCG previously claimed with no metric implementation at all). |
| **Hit@K** | queries with ≥1 relevant doc in top-K / total queries | query | binary relevance | Secondary | Coarser than Recall@K; useful mainly for multi-hop where "did retrieval find the right entry point at all" matters more than completeness. |
| **Candidate recall (pre-rerank)** | Recall@K computed on the fusion-stage candidate set, before cross-encoder reranking | query | same as Recall@K | Secondary, diagnostic — isolates retrieval-stage from rerank-stage contribution | Only meaningful as a paired comparison against post-rerank Recall@K on the same queries. |
| **Source coverage** | benchmark queries for which the correct source type was even searchable / total queries requiring that source | query | gold required source set (§1.5) | Secondary | Measures corpus/connector coverage gaps, not ranking quality — don't conflate with Recall@K. |
| **Evidence coverage** | distinct gold-relevant facts represented in the retrieved set / total gold-relevant facts for the query | query | fact-level gold annotation (heavier than doc-level relevance) | Secondary — only for benchmarks that annotate at fact granularity | Expensive to label; reserve for the multi-hop/cross-source benchmark where doc-level recall alone under-captures "did we get the actual pieces needed." |
| **Retrieval latency** | wall-clock ms per query, per stage (dense, sparse, fusion, rerank) | query | none | Secondary (see §9 for the full latency contract) | Machine-dependent; report hardware alongside any number. |

---

## 4. Heterogeneous-Source Evaluation

Specifically targets class-D/E queries (`PRODUCT_CONTRACT.md` §3) where a
**complete** answer requires evidence from more than one source type.

| Metric | Formula | Unit | Label | Primary/Secondary | Known limitation |
|---|---|---|---|---|---|
| **Required-source recall** | gold-required sources actually queried and contributing ≥1 used Evidence object / gold-required sources | query | gold required source set + which sources actually contributed cited evidence | Primary | Requires the claim-evidence link (§5) to already exist to compute "contributing." |
| **Cross-source evidence completeness** | distinct gold facts covered across all contributing sources / total gold facts for the query | query | fact-level gold annotation | Primary for the multi-source benchmark specifically | Same labeling cost caveat as "evidence coverage" above. |
| **Multi-source answer completion** | queries where the final answer actually synthesizes evidence from ≥2 sources (not just retrieves from 2 but only cites 1) / total multi-source-required queries | query | derived from citation source-type diversity in the produced answer | Primary | A model can retrieve from multiple sources but still write an answer that ignores one — this metric specifically catches that failure mode; retrieval-only metrics (§3) cannot. |
| **Cross-source linkage correctness** | for multi-hop queries, entity linkage between hops (e.g., compound identified from ChEMBL correctly used as the search term for ClinicalTrials.gov) verified correct / total linkage points | query (multi-hop only) | human-reviewed linkage correctness | Secondary | Only applicable to class-E queries; small expected n. |

---

## 5. Claim Grounding & Citation Metrics

**This is the critical V2 benchmark family.** Unit of analysis is the
**claim**, not the whole answer — an answer with 9 well-grounded claims and 1
fabricated one is a different (and worse) result than an answer with no
claims at all, and answer-level pass/fail metrics cannot distinguish them.

Every material factual sentence in a generated answer is decomposed into one
or more atomic claims (a claim-extraction step, itself evaluable — see
`V2_PHASE_GATES.md` Phase 6/7). Each claim is then checked against its cited
Evidence object(s).

| Metric | Formula | Unit | Label | Primary/Secondary | Known limitation |
|---|---|---|---|---|---|
| **Claim Support Precision** | claims judged SUPPORTED / total material factual claims | claim | claim→evidence support judgment (see §Judge Validation, §7) | Primary | Directly dependent on judge quality — must clear calibration bar in §7 before being reported as a headline number. |
| **Unsupported Claim Rate** | claims judged UNSUPPORTED / total material factual claims | claim | same as above | Primary | Same dependency. |
| **Citation Precision** | citations whose linked evidence actually supports the claim it's attached to / total citations used | citation | claim→evidence support judgment | Primary | Distinct from claim support precision: a claim can be true but cite the *wrong* evidence for it — this metric specifically catches that. |
| **Citation Recall** | claims requiring a citation that have ≥1 correctly-supporting citation / total claims that should be cited | claim | which claims are "citable" (i.e., factual, not the system's own inferential framing) must be labeled | Primary | Requires a prior labeling step distinguishing evidentiary claims from inferential/summarizing sentences — that distinction itself needs an annotation guideline. |
| **Citation Completeness** | material factual claims carrying adequate (not just present, but sufficient) evidence / total material factual claims | claim | graded adequacy judgment, not just binary presence | Secondary | "Adequate" is a judgment call; define a concrete rubric (e.g., single-source anecdote vs. corroborated finding) in the annotation spec before using this as a gating metric. |
| **Contradiction Rate** | claims directly contradicted by their own cited evidence / total factual claims | claim | contradiction judgment | Primary | The most safety-relevant metric in this section — a citation that contradicts its own claim is worse than an uncited claim, and must be tracked separately, never averaged into a generic "hallucination rate" blob as the old system did. |

**Explicit rule, replacing the old system's approach:** none of the metrics
in this section may be reported from a single unreliable LLM-judge pass with
no calibration. See §7.

---

## 6. Answer-Quality Metrics

Deliberately **separate from grounding** (§5) — a perfectly grounded answer
can still fail to actually answer the question, and grounding metrics alone
cannot catch that.

| Dimension | Definition | Measurement approach | Primary/Secondary |
|---|---|---|---|
| **Correctness** | Does the answer's central claim match the actual state of evidence? | Human/expert-reviewed on a calibration subset; not fully automatable | Primary (on reviewed subset only) |
| **Completeness** | Does the answer cover the material evidence available, not just the first result found? | Compare cited evidence set against a curated "should have been found" reference set (from the retrieval benchmark's gold relevant set) | Primary |
| **Relevance** | Does the answer address what was actually asked? | Human-reviewed rubric (1–5 scale) on a sample | Secondary (diagnostic; not deterministic) |
| **Directness** | Is the direct answer stated early/clearly rather than buried? | Structural check (rubric or automatic: is there a direct-answer sentence in the first N sentences) | Secondary |
| **Source coverage** | Are all gold-required source types (per §1.5) represented in the final answer's citations, not just retrieved-and-discarded? | Same signal as Multi-source answer completion (§4), reused here for single-source-sufficient queries too | Primary |
| **Uncertainty calibration** | When evidence is thin/conflicting, does the answer say so, versus stating unwarranted confidence? | Rubric-based human review against known-insufficient-evidence benchmark cases (taxonomy class H) | Primary |

**No combined single "answer quality score."** A blended score would hide
which dimension is actually failing, and different failure modes require
different fixes (a completeness problem needs better retrieval; a calibration
problem needs prompt/generation changes) — collapsing them destroys that
diagnostic value.

---

## 7. Judge Validation Requirements

The Phase 0 baseline established that the existing `hallucination_judge.py`
is unreliable (historically ~10–40% successful-judgment rate depending on
context size) and **must not define V2 ground truth** on its own.

**Validation hierarchy, in order of trust:**
1. **Deterministic checks** where possible (e.g., does a cited NCT ID
   actually exist in the retrieved ClinicalTrials.gov result set at all —
   this needs no judge).
2. **Structured claim/evidence comparison** where the claim and evidence are
   both reducible to comparable structured fields (e.g., a trial-phase claim
   checked against the trial record's actual phase field).
3. **Independent LLM judge**, used only for claims that require genuine
   natural-language entailment judgment (e.g., "does this abstract support
   this synthesized clinical conclusion") — and only after passing
   calibration (below).
4. **Human-reviewed calibration subset** — the source of truth the judge is
   validated against, not a rubber stamp.

**Before any LLM-judge output may be used as a headline metric (§5, §6):**
- **Judge parse success rate** must be reported and must be high enough that
  failures aren't silently dropped from the denominator (the old system's
  documented failure mode).
- **Judge–human agreement** on a held-out calibration sample: report
  precision, recall, F1 against human labels, and **Cohen's κ** for
  inter-rater-style agreement.
- **Minimum calibration bar** (to be finalized when the calibration sample is
  built, `BENCHMARK_PLAN.md` §E): the judge must be evaluated at a sample
  size large enough to produce a defensible confidence interval — a n=2 or
  n=6 judged sample, as occurred historically, is explicitly insufficient
  and must never again be reported as a headline percentage.
- Any run where the judge's parse/verdict failure rate is high must report
  metrics **only over the successfully-judged subset**, with that subset
  size stated prominently, not silently backfilled or excluded from view.

---

## 8. Workflow / End-to-End Task Success

Old "task success" (Phase 0: 37.9%/18.3% depending on subset) is not
V2's definition. V2's success gate must be built from **observable,
component-level requirements** already defined above, not a single opaque
pass/fail judgment.

**Proposed V2 workflow-success definition** (an answer counts as a successful
workflow only if *all* of the following hold — each individually measured by
metrics already defined above):
1. Query understanding produced a usable `ResearchQuery` (intent + entities
   extracted above a minimum confidence/coverage bar — §1)
2. All gold-required sources were actually queried (§1.5, §4 required-source
   recall)
3. At least the minimum sufficient evidence was retrieved (§3 Recall@K above
   a floor, per-benchmark)
4. A final answer was generated (not a hard failure/exception)
5. Claim Support Precision and Unsupported Claim Rate for the answer meet a
   floor (§5) — **not** just "some claims were supported"
6. No critical tool failure went undisclosed (§9 Reliability — a disclosed
   partial failure with a complete answer from remaining sources can still
   count as success; a silent one cannot)

This is a **conjunctive gate**, deliberately stricter than a single
confidence-threshold check (the mechanism the old system used, and which
Phase 0's own end-to-end run showed converging on "Stop" via a coverage +
confidence threshold that never validated claim-level grounding at all). The
exact numeric floors for steps 3 and 5 are **not set in Phase 1** — they will
be calibrated from measured baseline distributions once V2's NLU/retrieval/
grounding components exist and produce real score distributions to calibrate
against (a floor set blindly now would be exactly the "arbitrary threshold to
look good" failure mode this project must avoid).

---

## 9. Latency / Cost / System Metrics

Phase 0 baseline (**not a V2 target, reference point only**): one real
end-to-end run took 461s, 26 LLM calls, 11 tool calls; historical batch
average ~177–210s/case.

| Metric | Definition | Reporting requirement |
|---|---|---|
| End-to-end latency P50 / P95 | wall-clock per query, full pipeline | report both, never P50 alone — tail latency is where loop/retry behavior shows up |
| Query-understanding latency | NLU stage wall-clock | per-stage breakdown required, not just total |
| Source-call latency (per source) | PubMed / ClinicalTrials.gov / ChEMBL wall-clock, reported separately | separate because they have genuinely different latency profiles (Phase 0 observed ChEMBL sub-call latency varying 100ms–3.6s) |
| Retrieval latency | dense + sparse + fusion, separately and combined | |
| Reranking latency | cross-encoder stage | |
| Generation latency | synthesis/report LLM calls | |
| Verification latency | claim-grounding stage | |
| LLM calls / query | count | |
| Tool calls / query | count | |
| Tokens / query | prompt + completion, combined and by stage | |
| Retries / query | count, by cause (timeout / 429 / 503 / other) | |
| API error rate | errors / total external calls, by source and by error type | |
| Cost / query | if measurable (token-based estimate at minimum) | |

**Reporting methodology:** all latency/cost numbers must state hardware,
concurrency setting, and sample size (single-run numbers, as in Phase 0's one
end-to-end run, are illustrative only — not a benchmark until run at n≥30
under fixed conditions, matching the historical evaluation batch convention
in `RESULTS.md`). **No arbitrary aggressive thresholds are set in Phase 1** —
targets will be set from measured feasibility once a V2 baseline exists,
exactly as instructed; this document defines what gets measured, not what
number counts as "good."

---

## 10. Reliability Metrics

See `V2_PHASE_GATES.md` Phase 9 for the fault-injection matrix this section's
metrics are computed against (PubMed/ClinicalTrials/ChEMBL timeouts, 429,
503, malformed response, empty source, partial outage, invalid structured
LLM output, retriever/reranker unavailable, verifier failure, LLM timeout).

| Metric | Formula | Primary/Secondary |
|---|---|---|
| Recovery rate | fault scenarios where the system produced a correct disclosed-partial or full answer / total injected fault scenarios | Primary |
| Silent-failure rate | fault scenarios where the system produced an answer with no disclosure of the failure / total injected fault scenarios | Primary — this is the most product-damaging failure mode and must be tracked even if recovery rate looks good |
| Partial-answer quality | for disclosed-partial answers, Answer-Quality metrics (§6) computed on the reduced-evidence answer | Secondary |
| Retry amplification | mean additional latency/calls caused by retry logic per fault event | Secondary |
| Latency penalty | added wall-clock from fault handling vs. clean-path baseline | Secondary |

---

## 11. Follow-up / Research-Loop Metrics

Phase 0 observed the historical loop converging via a coverage+confidence
threshold with a 90%+ self-correction (loop-triggering) rate but only
37.9%/18.3% task success — i.e., looping a lot without demonstrated
convergence toward success. V2's loop must justify its cost with measured
evidence gain, not just iterate.

| Metric | Formula | Primary/Secondary |
|---|---|---|
| Gap identification accuracy | follow-up queries that correctly target a genuine evidence gap (human-reviewed) / total follow-up queries issued | Primary |
| Follow-up source correctness | follow-up tool calls that select an appropriate source for the identified gap / total follow-up calls | Primary |
| Additional relevant evidence gained | new cited Evidence objects added after a follow-up round / total evidence in final answer | Primary |
| Quality improvement after follow-up | delta in Claim Support Precision (§5) and Answer Completeness (§6) between pre- and post-follow-up draft | Primary — this is the metric that actually justifies the loop's cost |
| Unnecessary-loop rate | follow-up rounds that added no new used evidence and no quality-metric improvement / total follow-up rounds | Primary |
| Mean loops/query | count | Secondary |
| Loop termination correctness | loops that stopped for a valid reason (evidence sufficient, or genuinely exhausted) vs. stopped for an invalid reason (hit max_iterations, or stopped despite an identifiable, findable gap) — human-reviewed subset | Primary |

---

## 12. Baseline Comparisons (defined now, run later)

Legitimate before/after comparisons future phases may make, **not run in
Phase 1**:

- Retrieval: BM25-only vs. dense-only vs. current hybrid vs. future
  architecture (all on the same retrieval benchmark, §3)
- Answering: no-RAG vs. current RAG vs. V2 grounded generation (on the same
  end-to-end benchmark, §8, using the RAG-comparison methodology already
  validated in `RESULTS_RAG_COMPARISON.md` — same fixed parameters, same
  case set, judge-reliability caveat applied)
- Tool routing: free-form JSON dispatch (current) vs. schema-constrained
  native tool calling (future, Phase 3 gate) — on §2 metrics
- Agent loop: current confidence-threshold verification loop vs. future
  evidence-gap-driven loop — on §11 metrics

Every comparison must run on the **same benchmark version** (`BENCHMARK_PLAN.md`
§Versioning) for both arms, with the same fixed parameters, to be reportable
as a legitimate delta.

## 13. Statistical Reporting Requirements

- Every reported metric states: benchmark name + version, split, sample
  size (n), and — where the benchmark size supports it — a confidence
  interval or explicit statement that n is too small for one (as
  `RESULTS_RAG_COMPARISON.md` already correctly did for its n=2 judged
  subset; that discipline carries forward as a hard requirement, not a
  one-off).
- Metrics computed from a judge (§7) additionally state the judge's
  parse-success rate and calibration-agreement figures alongside the metric
  itself, every time it is reported — not just in a separate methodology
  document.
- Comparisons between two arms (baseline vs. variant) must use paired
  samples (identical query set) wherever possible, matching the existing
  `RESULTS_RAG_COMPARISON.md` convention.
