# MedAgent V2 — Phase Gates (Phase 2 through 13)

**Before starting or advancing a phase in a local environment, check
`docs/v2/CLOUD_TO_LOCAL_GAP_CLOSURE.md`. Any blocking OPEN carryover item
there is a hard progression gate, in addition to the phase exit gates
below.**

**Status:** design contract, Phase 1. No phase below is implemented. Every
phase's exit gate must be satisfied by a **measurable artifact or executable
behavior**, referencing the metrics in `EVALUATION_CONTRACT.md` and the
benchmarks in `BENCHMARK_PLAN.md` — prose claims alone never satisfy a gate.

Old repository ceilings (Recall@10 plateau, current corpus, current judge
reliability, etc.) are baseline evidence only, per instruction — they do not
constrain what any phase below is allowed to change.

---

## Phase 2 — Biomedical NLU

**Purpose:** implement the `ResearchQuery` structured-understanding stage
(entity extraction, normalization, intent classification, constraint
extraction, source-requirement prediction) as defined conceptually in
`PRODUCT_CONTRACT.md` and evaluated per `EVALUATION_CONTRACT.md` §1.

**Input:** Phase 1 contracts; NLU benchmark (A) built per `BENCHMARK_PLAN.md`.

**Work to perform:** finalize the `ResearchQuery` schema (which fields are
required vs. optional, which entity types get normalized and to which
ontology); build the NLU benchmark (A) with human-reviewed labels; implement
extraction/normalization/intent/constraint/source-prediction; iterate on dev
split only.

**Expected artifacts:** `docs/v2/nlu/RESEARCHQUERY_SCHEMA.md`,
`evaluation/v2/nlu_benchmark_v1.json` (+ version metadata per
`BENCHMARK_PLAN.md` §Versioning), a reproducible eval script, a results
report against the test split.

**Measurements:** Entity P/R/F1, Normalization Accuracy@1/@k, Intent
Accuracy/Macro-F1, Constraint field P/R/F1, Source-set P/R/F1
(`EVALUATION_CONTRACT.md` §1), all reported with n and benchmark version.

**Exit gate:** test-split metrics reported (not dev-split — dev is for
iteration only) with defensible sample size (≥150 queries per
`BENCHMARK_PLAN.md` §A); no metric computed from unreviewed synthetic labels.

**Stop condition:** if entity/intent extraction cannot reliably beat a naive
keyword-matching baseline on the dev split after reasonable iteration, stop
and report that as a finding — do not proceed to Phase 3 on an NLU layer that
adds no measurable value over the simpler baseline without first understanding why.

**What must not be claimed yet:** end-to-end task success, grounding quality,
retrieval quality, or any claim about the full agent — Phase 2 claims are
scoped to the NLU stage in isolation.

---

## Phase 3 — Reliable Schema-Constrained Tool Orchestration

**Purpose:** replace or validate the tool-dispatch mechanism. Phase 0 found
hallucinated tool-name selection under the current free-form JSON-emit
dispatch; this phase decides and implements the mechanism (native
schema-constrained tool calling vs. a hardened JSON-emit variant) and proves
it against §2 metrics.

**Input:** Phase 2 `ResearchQuery` output; source-routing benchmark (B).

**Work to perform:** implement the chosen dispatch mechanism; wire tool
schemas for PubMed/ClinicalTrials.gov/ChEMBL; run the valid-call /
execution-success / parameter-correctness / useful-result metrics on the
live connectors (already confirmed live and working in Phase 0).

**Expected artifacts:** tool-schema definitions, a dispatch-mechanism design
note documenting the before/after comparison against the current free-form
mechanism (per `EVALUATION_CONTRACT.md` §12 baseline-comparison rules), a
results report.

**Measurements:** Source precision/recall/F1, valid-call rate,
execution-success rate, parameter-correctness rate, useful-result rate
(`EVALUATION_CONTRACT.md` §2) — each reported separately, never collapsed.

**Exit gate:** valid-call rate materially improved over the Phase 0 baseline
observation of hallucinated tool names (measured, not assumed); all three
live connectors still functioning at execution-success rates consistent with
Phase 0 smoke-test behavior (PubMed/ClinicalTrials near-100%; ChEMBL's known
exact-match sensitivity documented, not silently "fixed" by relabeling it).

**Stop condition:** if the chosen dispatch mechanism does not measurably
reduce invalid/hallucinated tool calls versus the Phase 0 baseline, do not
proceed claiming reliability improved — revisit the mechanism.

**What must not be claimed yet:** retrieval quality, grounding, or any
end-to-end claim — this phase is scoped to tool-call mechanics.

---

## Phase 4 — Heterogeneous Retrieval

**Purpose:** implement/validate retrieval per source (PubMed, ClinicalTrials.gov,
ChEMBL) and cross-source fusion, evaluated per `EVALUATION_CONTRACT.md` §3–4.
Free to change corpus, embedding model, chunking, fusion method, or keep the
current hybrid FAISS+BM25+RRF+cross-encoder pipeline if it's justified by
evaluation, not by inertia.

**Input:** Phase 2/3 outputs; retrieval benchmarks C.1–C.5, multi-source
benchmark D.

**Work to perform:** build/validate the per-source retrieval benchmarks;
measure the current pipeline against them as a real baseline (not the
historical 18-query set alone); decide whether to keep or change any
component based on that measurement; implement chosen changes; re-measure.

**Expected artifacts:** benchmark files C.1–C.5 + D (versioned), a
retrieval-architecture decision document with before/after numbers, updated
retriever code + config.

**Measurements:** Recall@K, MRR, Precision@K, (nDCG@K only where graded
labels exist), Hit@K, candidate recall, source/evidence coverage, latency
(`EVALUATION_CONTRACT.md` §3), plus §4 heterogeneous metrics.

**Exit gate:** Recall@10 (or whatever primary metric is chosen per source)
reported on the new, larger, properly-pooled benchmark, with an explicit
statement of how it compares to the Phase 0 historical figure (0.48 mean on
18 queries) and why any change occurred (architecture change vs. benchmark
change — never conflate the two).

**Stop condition:** if a proposed architecture change does not measurably
improve the primary retrieval metric on the dev split, do not adopt it merely
because it's newer/more complex.

**What must not be claimed yet:** grounding, citation correctness, or
end-to-end answer quality — retrieval finding relevant evidence is necessary
but not sufficient for those.

---

## Phase 5 — Evidence / Provenance Layer

**Purpose:** implement the canonical Evidence object
(`PRODUCT_CONTRACT.md`/conceptual schema from the Phase 1 prompt) so every
piece of retrieved information — live API result or indexed corpus chunk —
carries consistent, traceable provenance through fusion, reranking, and
generation.

**Input:** Phase 4 retrieval outputs (both live-API and indexed-corpus
paths).

**Work to perform:** finalize required vs. optional Evidence fields and
source-specific extensions; implement deduplication logic (e.g., the same
PubMed abstract appearing via both a live API call and the indexed RAG
corpus); verify provenance survives fusion/reranking (a concrete, testable
property — pick N evidence items pre-fusion, confirm their IDs/fields are
still intact post-fusion, not silently dropped or merged into an
unattributed blob).

**Expected artifacts:** `docs/v2/EVIDENCE_SCHEMA.md`, implementation, a
provenance-integrity test suite (deterministic, not judge-based — this is
exactly the kind of property that doesn't need an LLM judge).

**Measurements:** provenance-integrity test pass rate (deterministic);
deduplication precision/recall on a small labeled sample of known-duplicate
evidence pairs (e.g., same PMID from both paths).

**Exit gate:** 100% of evidence items reaching the generation stage carry
complete required-field provenance (deterministically checkable); documented
dedup behavior with measured precision/recall.

**Stop condition:** if provenance cannot be kept intact through the existing
fusion/reranking implementation, fix or replace that implementation before
proceeding — this is a hard architectural prerequisite for the citation
contract (Phase 6/7), not a nice-to-have.

**What must not be claimed yet:** citation correctness in a *generated
answer* — this phase proves evidence *can* be traced; Phase 6/7 proves it
*is* traced correctly in output.

---

## Phase 6 — Grounded Natural-Language Generation

**Purpose:** implement answer generation that produces the natural-language
answer contract (`PRODUCT_CONTRACT.md` §4) with inline citations
structurally linked to Evidence objects (Phase 5), plus the Claim object /
claim-extraction step needed for Phase 7's grounding evaluation.

**Input:** Phase 5 Evidence objects; product contract §4–5.

**Work to perform:** implement generation; implement claim decomposition
(splitting a generated answer into atomic claims); wire claim→evidence
linkage at generation time (not reconstructed after the fact by a judge) —
this is the "structural rather than merely prompt instruction" grounding
mechanism called for in the Phase 1 brief.

**Expected artifacts:** `docs/v2/CLAIM_SCHEMA.md`, generation implementation,
a small set of example answers demonstrating the format (qualitative, for
product review, not a benchmark result).

**Measurements:** answer-format compliance (structural: are citation markers
present and do they resolve to real evidence IDs — deterministic check, not
judge-based) on a dev sample.

**Exit gate:** 100% of citation markers in generated answers on the dev
sample resolve to a real Evidence object (deterministic check); claim
decomposition produces claims a human reviewer can meaningfully verify
support-status against (spot-checked, not yet the full benchmark — that's
Phase 7).

**Stop condition:** if citation markers cannot be made to reliably resolve to
real evidence structurally (i.e., the model still free-text-hallucinates
citation numbers), do not proceed to claiming grounding quality in Phase 7 —
fix the generation mechanism first.

**What must not be claimed yet:** claim support precision, unsupported-claim
rate, or any grounding *quality* number — Phase 6 proves the structural
plumbing exists; Phase 7 measures whether the claims it produces are
actually true.

---

## Phase 7 — Grounding / Citation Evaluation Harness

**Purpose:** build and run the grounding benchmark (E) and the judge
validation hierarchy (`EVALUATION_CONTRACT.md` §7), replacing the old
unreliable single-pass hallucination judge.

**Input:** Phase 6 generated answers with structural claim/evidence links;
benchmark E.

**Work to perform:** build benchmark E (≥300 claims, human-reviewed,
including the held-out calibration slice); implement the deterministic and
structured-comparison checks first (cheapest, most reliable); implement/
validate the LLM judge against the calibration slice; only then compute
headline grounding metrics on the test slice.

**Expected artifacts:** benchmark E (versioned), judge implementation +
calibration report (parse-success rate, judge–human P/R/F1, Cohen's κ), a
grounding-quality results report.

**Measurements:** Claim Support Precision, Unsupported Claim Rate, Citation
Precision/Recall/Completeness, Contradiction Rate (`EVALUATION_CONTRACT.md`
§5), each reported only after the judge clears its calibration bar (§7).

**Exit gate:** judge calibration report shows agreement high enough to trust
(exact numeric bar set once real calibration data exists — not invented here
— but the *requirement* that a bar be met and reported is the gate, not a
specific pre-chosen number); headline grounding metrics reported on test
slice with n≥300 claims, not n=2 or n=6 as occurred historically.

**Stop condition:** if the judge cannot be made reliable enough for its
agreement metrics to be defensible, headline grounding metrics must be
reported as "insufficiently validated" rather than presented as fact — same
discipline the project's own `RESULTS_RAG_COMPARISON.md` already modeled.

**What must not be claimed yet:** answer-quality dimensions beyond grounding
(completeness, relevance, directness) — those are Phase 8+/ongoing, not
gated by this phase.

---

## Phase 8 — Evidence-Driven Research Loop

**Purpose:** implement/validate the follow-up research loop so it targets
identified evidence gaps and measurably improves answer quality, replacing
the old loop's undemonstrated-convergence behavior (Phase 0: 90%+
loop-trigger rate, 37.9%/18.3% task success).

**Input:** Phase 6/7 grounded-generation pipeline; §11 loop metrics.

**Work to perform:** implement gap identification (what's missing from
current evidence relative to the query); implement targeted follow-up
querying; measure quality delta pre/post follow-up on a fixed query set.

**Expected artifacts:** loop design doc, before/after quality-delta report.

**Measurements:** Gap identification accuracy, follow-up source correctness,
additional relevant evidence gained, quality improvement after follow-up,
unnecessary-loop rate, mean loops/query, loop termination correctness
(`EVALUATION_CONTRACT.md` §11).

**Exit gate:** measured quality improvement (Claim Support Precision and/or
Completeness) after follow-up rounds, on a paired pre/post sample — not just
"the loop ran and produced *a* different answer."

**Stop condition:** if follow-up rounds do not produce a measurable quality
delta, reduce loop aggressiveness (or remove it) rather than keep it for
appearance — matches the Phase 1 design-review requirement against fake
agentic complexity.

**What must not be claimed yet:** system-wide reliability or latency
numbers under load — those are Phase 9.

---

## Phase 9 — Reliability / Concurrency / Performance

**Purpose:** implement the fault-injection matrix and measure reliability
(`EVALUATION_CONTRACT.md` §10) plus latency/cost instrumentation (§9) under
realistic concurrent load.

**Input:** full pipeline from Phases 2–8; reliability benchmark G.

**Work to perform:** design and freeze the fault-injection matrix (timeouts,
429/503, malformed responses, empty/partial source outage, invalid
structured output, retriever/reranker/verifier failure per source and
per stage); implement injected-fault test scenarios; measure recovery vs.
silent-failure rates; instrument per-stage latency; validate concurrency
safety (Phase 0's history includes a real fixed Metal/MPS concurrency crash —
confirm no regression, and test at the concurrency level actually planned for
production, not just the previously-validated worker count).

**Expected artifacts:** benchmark G (versioned scenario definitions), a
reliability report, a latency/cost report with P50/P95 per stage.

**Measurements:** recovery rate, silent-failure rate, partial-answer quality,
retry amplification, latency penalty (§10); full latency/cost table (§9).

**Exit gate:** silent-failure rate at or near zero (every injected fault
either recovers or is disclosed — never both hidden and wrong); latency
figures reported with hardware/concurrency stated, compared against but not
forced to beat the Phase 0 reference point.

**Stop condition:** any fault scenario producing a confidently-wrong,
undisclosed answer is a blocking defect — fix before proceeding, regardless
of how rare the injected condition is, because it is a product-trust failure
mode, not a performance nit.

**What must not be claimed yet:** final held-out generalization numbers —
those come from Phase 10's discipline applied across all benchmarks
together.

---

## Phase 10 — Validation Optimization + Held-Out Evaluation

**Purpose:** apply the split/leakage discipline (`BENCHMARK_PLAN.md`
§Leakage) end-to-end: all architecture/prompt/threshold decisions finalized
using dev splits only, then every benchmark's test split run exactly once
for final reporting.

**Input:** all benchmarks (A–G) and their dev splits, fully iterated on;
frozen candidate architecture.

**Work to perform:** freeze the architecture; run every test split once;
compile the full cross-benchmark results report; explicitly verify (and
document) that no test-split result influenced any prior decision.

**Expected artifacts:** `docs/v2/HELD_OUT_RESULTS.md` — one document
compiling every primary metric from every benchmark, each tagged with
benchmark name+version+split+n, per `EVALUATION_CONTRACT.md` §13.

**Measurements:** all primary metrics defined across `EVALUATION_CONTRACT.md`
§1–§11, reported once, on test splits only.

**Exit gate:** the held-out results document exists, is internally
consistent (no metric missing its n or benchmark version), and every number
in it is traceable to a specific benchmark file and eval script run.

**Stop condition:** if any test-split number looks suspiciously better than
the corresponding dev-split trend without explanation, investigate for
leakage before reporting it — do not report a number that cannot be
explained.

**What must not be claimed yet:** production deployment claims — those
require Phase 11/12 to actually exist.

---

## Phase 11 — API + Conversational UI

**Purpose:** expose the validated V2 pipeline through the product surface
defined in `PRODUCT_CONTRACT.md` (conversational answer + citations +
evidence appendix + research trace), matching the trust-model boundary in
§7 of that document.

**Input:** Phase 10's frozen, validated pipeline.

**Work to perform:** build the API layer; build the UI presenting the answer
contract exactly as specified (natural-language answer → inline citations →
source appendix → optional trace); implement the sanitized trace rendering
(no chain-of-thought, no raw prompts, no secrets — `PRODUCT_CONTRACT.md` §7).

**Expected artifacts:** working API, working UI, a manual UX walkthrough
against the product contract's example presentation format.

**Measurements:** UI/API-level smoke tests (deterministic: does the
citation-to-appendix link work, does the trace render without leaking
disallowed content); not a new accuracy benchmark — accuracy claims still
come from Phase 10's numbers, unchanged by adding a UI.

**Exit gate:** end-to-end user flow (question → answer → citations →
appendix → trace) works against the real backend, with the safety boundary
(§8 of the product contract) demonstrably enforced for a sample of boundary-
testing queries (diagnosis/dosage requests correctly redirected, not
answered).

**Stop condition:** if the trace or appendix ever leaks disallowed content
(raw prompts, chain-of-thought, secrets), that is a blocking defect, fixed
before Phase 12.

**What must not be claimed yet:** production-scale reliability under real
multi-user load — Phase 12 covers deployment infrastructure and its own
validation.

---

## Phase 12 — CI / Container / Tracing / Deployment

**Purpose:** operationalize the system — CI running the test/eval suites,
containerization, production observability (the trace/span contract from
Phase 1's observability section), and a deployment path.

**Input:** Phase 11's working API/UI.

**Work to perform:** CI pipeline (tests + a fast subset of dev-split evals
on every change; full held-out re-validation only on release candidates, per
Phase 10's discipline — never on every commit); containerize; implement the
observability spans defined conceptually in Phase 1 (query_understanding,
planning, per-source, embedding, retrieval, fusion, reranking, generation,
claim_extraction, verification, follow_up_research, citation_rendering) with
trace_id/request_id propagation.

**Expected artifacts:** CI config, Dockerfile(s), a deployed or
deployment-ready environment, an observability dashboard or equivalent
inspectable trace store.

**Measurements:** CI pass/fail on the test suite (deterministic); trace
coverage (fraction of spans actually populated on a sample of real requests).

**Exit gate:** CI green on the full test suite; a real request's full span
trace is inspectable end-to-end; container builds and runs the full pipeline
reproducibly.

**Stop condition:** do not build deployment infrastructure beyond what the
actual product needs (Phase 1 design-review failure mode I, deployment
theater) — a single-container deployment adequate for the product's real
scale is sufficient; do not over-engineer for hypothetical load this project
has no evidence it will see.

**What must not be claimed yet:** nothing further gates this phase's
scope — but claims about "production-grade at scale" still require actual
load evidence, not just that CI/containers exist.

---

## Phase 13 — Final Evaluation / Documentation / Freeze

**Purpose:** compile the final, complete, reproducible evidence chain across
every phase into one authoritative project report, matching the "project
success definition" in `PRODUCT_CONTRACT.md`'s companion sections.

**Input:** every artifact from Phases 2–12.

**Work to perform:** compile a final report cross-referencing every
benchmark, every metric, every gate's pass/fail status, and every explicitly
scoped limitation; verify reproducibility (can another engineer re-run the
eval suite from the documented commands and get consistent results); freeze
version numbers on all benchmarks and the architecture.

**Expected artifacts:** `docs/v2/FINAL_REPORT.md`, a reproducibility
checklist, frozen benchmark/version manifest.

**Measurements:** none new — this phase aggregates and verifies, it does not
generate new headline numbers under time pressure to "finish strong."

**Exit gate:** every claim in the final report traces to a specific
artifact/benchmark/metric from an earlier phase; nothing in the final report
is a number that wasn't already produced and gated in its originating phase.

**Stop condition:** if reproducibility verification fails (a documented
command doesn't actually reproduce the stated result), fix that before
declaring the project complete — a final report that can't be reproduced is
exactly the failure mode this whole V2 effort exists to correct relative to
the old repository's fabricated-then-corrected history.

**What must not be claimed yet:** nothing — this is the terminal phase. But
even here, claims remain bounded by what was actually measured; "final" does
not license rounding up.

---

## Design Review — Phase 1 Self-Audit

Required self-check against known failure modes before declaring Phase 1
complete. This is a genuine review, not a formality — each item states the
finding and, where a risk was real, the correction already made above.

**A. Metric theater** — *Checked.* `EVALUATION_CONTRACT.md` deliberately
excludes nDCG@K except where graded labels legitimately exist (explicitly
flagging that the old repo claimed it with no implementation at all), and
excludes a combined "answer quality score" that would hide which dimension
is failing. Every metric ties to a specific product or engineering decision
it would inform (e.g., Contradiction Rate exists separately from Unsupported
Claim Rate because they demand different fixes). No metric was added purely
because the source JD/prompt mentioned it.

**B. Duplicate portfolio coverage** — *Checked.* `JD_OWNERSHIP.md` explicitly
excludes ranking-feature experimentation and long-tail/click-log query
mapping from MedAgent's scope, with a stated rationale (Hybrid/SparseQuery
own those), including a split-context note for the two terms ("semantic
understanding," "information retrieval") that plausibly overlap in JD
language but are given a bounded, non-duplicating interpretation for
MedAgent.

**C. Product/benchmark mismatch** — *Checked, one real risk identified and
mitigated:* an end-to-end benchmark optimized purely for Claim Support
Precision could push the system toward refusing to answer (fewer claims =
fewer chances to be unsupported), which would technically improve the
metric while making the product worse. Mitigation: §8's workflow-success
gate is conjunctive and includes evidence retrieval/completeness alongside
grounding, and Answer-Quality (§6) separately measures Completeness and
Directness — a system that refuses too often fails those, not just passes
grounding vacuously.

**D. Judge dependency** — *Checked and directly addressed.* §7 of
`EVALUATION_CONTRACT.md` is written specifically because the Phase 0 audit
found the existing judge unreliable; no headline grounding metric may be
reported without the judge clearing a calibration bar first, and
deterministic/structured checks are required as the first line of
verification before any LLM judge is invoked at all.

**E. Test leakage** — *Checked and directly addressed.* `BENCHMARK_PLAN.md`
§Leakage defines query-grouping rules and a hard rule (repeated in
`EVALUATION_CONTRACT.md` §0) against selecting architecture based on test-
split results; Phase 10 exists specifically to enforce "test split touched
once."

**F. Synthetic-ground-truth leakage** — *Checked and directly addressed.*
Every benchmark in `BENCHMARK_PLAN.md` states LLM-assisted draft labels
require 100% human review before entering the benchmark — stated as a hard
requirement in §A methodology and repeated in the Human-Review Requirements
summary table.

**G. Black-box citations** — *Checked and directly addressed.* Phase 5
(Evidence/provenance) and Phase 6 (structural claim→evidence linkage at
generation time, not reconstructed after the fact by a judge) exist
specifically so a citation can never be displayed without a traceable
evidence relationship — this is why the product contract requires the
evidence appendix be "generated from those exact evidence records," not
regenerated independently.

**H. Fake agentic complexity** — *Checked, one real risk identified.* The
existing 6-node graph and its 90%+ historical loop-trigger rate is exactly
this failure mode already manifesting. Phase 8's exit gate is intentionally
strict — a measured quality delta pre/post follow-up, not "the loop ran" —
and its stop condition explicitly calls for reducing or removing loop
aggressiveness if no delta is found, rather than preserving loop complexity
for its own sake.

**I. Deployment theater** — *Checked and directly addressed.* Phase 12's
stop condition explicitly warns against building infrastructure beyond
actual product need and against over-engineering for hypothetical scale with
no supporting load evidence.

**J. Medical-safety overclaiming** — *Checked and directly addressed.*
`PRODUCT_CONTRACT.md` §1–2 positions MedAgent explicitly as a research
assistant, not clinical decision support, with §8 defining a proportional
(redirect, not blanket-refuse) response boundary, and Phase 11's exit gate
requires demonstrating that boundary against real boundary-testing queries
before the UI phase can close.

**Net corrections made as a result of this review:** (1) explicit exclusion
of a combined answer-quality score and of nDCG in the absence of graded
labels (A); (2) split-context note added for ambiguous JD terms (B); (3)
conjunctive workflow-success gate instead of a single optimizable metric
(C); (4) Phase 8's strict quality-delta exit gate instead of an
existence-only gate (H). No other structural changes were needed — the
remaining items were already satisfied by the contracts as drafted.
