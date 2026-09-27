# MedAgent V2 — Benchmark Plan

**Status:** design contract, Phase 1. This defines the proposed benchmark
suite structure, sample-size targets, annotation methodology, split/leakage
policy, and versioning scheme. **No benchmark data is created in this
phase.** Building the actual datasets is Phase 2+ work, gated per
`V2_PHASE_GATES.md`.

---

## A. NLU Benchmark

**Purpose:** evaluate the metrics in `EVALUATION_CONTRACT.md` §1 (entity
extraction, normalization, intent classification, constraint extraction,
source-requirement prediction).

**Schema per example:**
```
{
  query_id, query_text,
  intent_class (from PRODUCT_CONTRACT.md §3 taxonomy A-I, multi-label where justified),
  entities: [{text, span, type, normalized_id (nullable)}],
  constraints: [{field, value}],
  required_sources: [pubmed|clinicaltrials|chembl],
  difficulty: easy|medium|hard|ambiguous,
  annotator_id, adjudicator_id, adjudication_notes
}
```

**Sample-size target:** ≥150 queries at first release, distributed roughly:
- ~30% class A/B/C (single-source), ~30% class D/F (dual-source/mechanism),
  ~20% class E/G (multi-hop/constraint-heavy), ~10% class H (insufficient-
  evidence), ~10% class I (ambiguous).
- This is larger than the historical 60-case end-to-end set because NLU
  labeling is per-query, not per-workflow, and the taxonomy has 9 classes
  needing meaningful per-class coverage — 150 gives ~15-45 examples per
  class depending on weight, enough for a first F1 estimate, not enough for
  tight confidence intervals; scale up in a later revision once the schema
  is validated as annotatable.

**Annotation methodology:**
1. Draft queries sourced from a mix of: (a) hand-written by someone with
   biomedical domain familiarity, covering the taxonomy deliberately, and
   (b) realistic variations of the existing 60-case `evaluation/test_cases.py`
   set (reused as query *material*, not as pre-existing "ground truth" —
   those cases have no entity/intent labels today).
2. Each query independently annotated by ≥1 human reviewer for entities,
   normalization targets, intent, constraints, and required sources.
3. **If LLM-assisted labeling is used to bootstrap draft annotations, every
   label must be independently human-reviewed and corrected before entering
   the benchmark** — LLM-drafted labels are never accepted as ground truth
   without that review step. This applies to 100% of examples, not a sample.
4. Disagreements (a second annotator disagrees with the first, or the
   reviewer flags ambiguity) go through an adjudication pass with a written
   resolution rule, logged in `adjudication_notes`.
5. Ambiguous-by-design queries (class I) are intentionally included with
   *multiple acceptable* label sets where the ambiguity is real — not forced
   into one "correct" interpretation.

**Split:** train/dev not needed for this benchmark (it's a static evaluation
target, not something a model is fine-tuned on in the near term) — a single
**dev** (for iterative prompt/pipeline development, ~30%) and **test**
(held out, touched only for final phase-gate reporting, ~70%) split, grouped
by query near-duplication (see §Leakage below).

---

## B. Source-Routing Benchmark

**Purpose:** evaluate `EVALUATION_CONTRACT.md` §2 (source selection, valid-
call rate, execution success, parameter correctness, useful-result rate).

**Relationship to A:** reuses the NLU benchmark's `required_sources` label as
its ground truth for source-selection correctness — not a separate labeled
set. What's additive here is **live execution outcomes** (did the real call
succeed, was it schema-valid, were its parameters correct), which can only be
measured by actually running the system, not by static labels.

**Sample-size target:** same query set as NLU benchmark (A), run live against
real tools.

**Annotation methodology:** parameter-correctness (§2) requires a human-
reviewed gold parameter set for a subset of queries — target ≥50 queries
covering all three tools and representative filter combinations (phase,
status, date range, etc.), reviewed by someone who can read each tool's real
API schema.

**Split:** same dev/test split as A (inherits it).

---

## C. Retrieval Benchmark(s)

**Purpose:** evaluate `EVALUATION_CONTRACT.md` §3, kept **separate per
source** because relevance means different things per source type, plus a
cross-source and multi-hop variant.

### C.1 PubMed literature retrieval
- Reuses and extends the existing methodology in `retrieval/build_eval_set*.py`
  and `retrieval/eval_set*.json` (18-query historical set) — that prior work
  is a legitimate starting point for query *material* and relevance-judgment
  *process*, but its labels are historical artifacts (Phase 0 §15) and must
  be re-validated, not silently inherited as V2 ground truth.
- **Relevant** = an abstract/chunk that a domain-competent reviewer confirms
  materially supports or addresses the query's information need (not just
  keyword overlap).
- **Sample-size target:** ≥50 queries at first release (up from 18), each
  with a pooled relevant-set built from top-K across multiple retrieval
  methods (BM25, dense, hybrid) to reduce pooling bias — a query judged
  relevant only against one method's output systematically favors that
  method.

### C.2 ClinicalTrials.gov retrieval
- **Relevant** = a trial record that actually matches the query's condition/
  intervention/constraint intent, confirmed by review of the live record
  fields (phase, status, condition, intervention), not just text similarity.
- **Sample-size target:** ≥40 queries, weighted toward constraint-heavy
  (class G) cases since that's where structured-filter correctness matters
  most.

### C.3 ChEMBL retrieval
- **Relevant** = a compound/bioactivity record that matches the query's
  target/indication/activity intent.
- **Sample-size target:** ≥30 queries — smaller because ChEMBL question
  volume is naturally lower in the taxonomy (compound/mechanism classes C/F
  only), and because Phase 0 already found ChEMBL's indication-matching to
  be sensitive to exact phrasing (worth a dedicated small diagnostic set
  specifically probing that boundary, separate from the main relevance set).

### C.4 Cross-source evidence retrieval
- Draws from class-D queries; "relevant" is evaluated per-source-per-query
  (a query can have relevant PubMed AND relevant ClinicalTrials results
  simultaneously) using the same per-source relevance definitions as C.1–C.3.
- **Sample-size target:** ≥30 queries.

### C.5 Multi-hop retrieval
- Draws from class-E queries; relevance is chained (a compound found via
  ChEMBL must correctly become the search term for the ClinicalTrials.gov
  hop, etc.) — this benchmark specifically tests hop correctness, not just
  final-hop relevance.
- **Sample-size target:** ≥20 queries — smallest, because these are the most
  annotation-expensive (each requires validating an entire chain, not one
  lookup) and least frequent in the intended query mix.

**Split (all of C):** dev (~30%, for architecture iteration) / test (~70%,
touched only at phase-gate reporting) — see `EVALUATION_CONTRACT.md` §0 rule
5: **never select architecture on the test split.**

---

## D. Multi-Source (Heterogeneous) Benchmark

**Purpose:** evaluate `EVALUATION_CONTRACT.md` §4 end-to-end (required-source
recall, cross-source completeness, multi-source answer completion, linkage
correctness) — distinct from C.4/C.5 in that this benchmark runs the *full
answer-generation pipeline*, not retrieval alone.

**Reuses:** the same class-D/E query set as C.4/C.5, run end-to-end.

**Sample-size target:** same as C.4 + C.5 (≥50 combined) — deliberately the
same queries as the retrieval-only benchmark so retrieval-stage and
generation-stage failures on the identical query can be distinguished (a
query that fails end-to-end but succeeds at C.4/C.5 retrieval indicates a
generation/synthesis problem, not a retrieval problem).

**Split:** inherits C's dev/test split for the same queries.

---

## E. Grounding / Citation Benchmark

**Purpose:** evaluate `EVALUATION_CONTRACT.md` §5 — the most safety-critical
benchmark. Unit of analysis is the **claim**, not the query.

**Schema per example:**
```
{
  answer_id, query_id, claim_id, claim_text, claim_type (evidentiary|inferential),
  cited_evidence_ids: [...],
  gold_support_status: SUPPORTED|PARTIALLY_SUPPORTED|UNSUPPORTED|CONFLICTING_EVIDENCE|INSUFFICIENT_EVIDENCE,
  gold_contradiction: bool,
  annotator_id, adjudicator_id
}
```

**Sample-size target:** ≥300 claims from ≥50 answers at first release — claim
count, not query count, is the meaningful denominator here (Phase 0's
historical hallucination-rate numbers were unreliable partly *because* they
were computed on too few successfully-judged claims — e.g., 63 claims from 6
cases, or 53 claims from 2 cases — this benchmark must not repeat that).

**Annotation methodology:**
1. Generate candidate answers from the current pipeline (or a fixed V2
   checkpoint) on a fixed query set.
2. Decompose each answer into atomic claims (this decomposition step is
   itself worth a small inter-annotator-agreement check — two people should
   mostly agree on where one claim ends and the next begins).
3. For each claim, a human reviewer checks the claim against its cited
   evidence (and, separately, against the full retrieved-evidence pool, to
   catch cases where a *better* citation existed but wasn't used) and assigns
   a gold support status.
4. **Judge-validation calibration subset carved from this benchmark**: a
   held-out slice (target ≥100 claims) used specifically to compute judge–
   human agreement (`EVALUATION_CONTRACT.md` §7) — this slice's labels are
   never shown to or reused for judge prompt-tuning, to keep the calibration
   honest.

**Split:** dev (for judge/prompt iteration) / calibration (held for judge
validation only, see above) / test (final reporting). Three-way split is
deliberate here because this benchmark serves two different purposes
(training the pipeline's grounding behavior vs. validating the judge that
measures it) that must not contaminate each other.

---

## F. End-to-End QA Benchmark

**Purpose:** evaluate `EVALUATION_CONTRACT.md` §8 workflow success and §6
answer quality, as a full-pipeline test.

**Relationship to existing work:** the existing 60-case
`evaluation/test_cases.py` set is a legitimate starting corpus of query
material and prior methodology (per-difficulty breakdown, tool-combination
coverage) — Phase 0 confirmed it is real and runnable, not fabricated. V2's
version should **extend, re-annotate, and re-validate** it against the new
component-level success gate (`EVALUATION_CONTRACT.md` §8), not simply reuse
its historical pass/fail labels, which were computed against a different
(single opaque confidence-threshold) success definition.

**Sample-size target:** ≥100 cases at first V2 release (up from 60),
preserving the existing difficulty-tier structure (easy/medium/hard/
ambiguous) and tool-combination coverage, extended with deliberate class-H
(insufficient-evidence) and class-I (ambiguous) cases, which the historical
set under-covers.

**Split:** dev (~30%, pipeline iteration) / test (~70%, phase-gate reporting
only).

---

## G. Reliability / Fault Benchmark

**Purpose:** evaluate `EVALUATION_CONTRACT.md` §10 against the fault-
injection matrix defined in `V2_PHASE_GATES.md` Phase 9.

**Schema:** not query-based — scenario-based. Each scenario = one fault type
(timeout, 429, 503, malformed response, empty source, partial outage, invalid
structured output, retriever/reranker unavailable, verifier failure) ×
injection point (which stage) × a small set of representative queries run
under that injected condition.

**Sample-size target:** every fault type × every applicable injection point,
each run against ≥5 representative queries (not 1 — a single-query fault test
can pass by chance) — total scenario count depends on the final fault matrix
size from Phase 9's design, expected on the order of 60–100 scenario-runs.

**Split:** not applicable (this is a controlled-condition test suite, not a
held-out generalization benchmark) — but scenario definitions should be
frozen/versioned the same way (§Versioning below) so results are comparable
across architecture changes.

---

## Split / Leakage Policy

Applies to every benchmark above.

**Question/query-level grouping:** near-duplicate questions (same underlying
information need, reworded) must be assigned to the **same** split — never
split across dev/test. This includes:
- templated variants of the same query pattern with different entities
  substituted (a common LLM-bootstrapped-question failure mode)
- the same fact asked from a different angle ("what trials study drug X" vs.
  "is drug X being studied in trials")

**Evidence/document-level grouping (retrieval benchmarks, C):** whether the
same PubMed abstract, trial record, or ChEMBL compound appearing in both a
dev-split query's relevant set and a test-split query's relevant set counts
as leakage depends on the task: for **retrieval ranking quality**, document
reuse across splits is fine (it's normal for the same trial to be relevant to
two different real queries) — what must never happen is the **same query**
appearing in both splits. For any future **retrieval model
training/fine-tuning** (not in scope yet), document-level overlap between
train and test would need to be controlled separately — flagged here as a
requirement for whichever future phase introduces model training, not
resolved now.

**Synthetic/templated variants:** if query generation is templated or
LLM-assisted (§A annotation methodology step 3), all variants generated from
the same template+seed-entity combination are treated as one group for
splitting purposes.

**Entity overlap:** benchmark construction should not systematically confine
a given disease/gene/compound to only one split — that would make the split
measure entity memorization rather than task generalization — but exact
per-entity balancing is not required; monitor and report entity diversity per
split, don't hard-constrain it.

**Test-set discipline:** dev splits are for all iterative development
(prompt tuning, architecture selection, threshold calibration). Test splits
are touched only to produce the number reported at a phase-gate
(`V2_PHASE_GATES.md`). Re-running the test split more than once per
architecture decision — and adjusting the architecture based on what the test
split showed — is exactly the leakage failure mode this policy exists to
prevent, and must not happen.

---

## Benchmark Versioning

Every benchmark file/dataset carries, at minimum:

```
{
  benchmark_name, version (semver),
  creation_date, schema_version,
  annotation_methodology_ref (link to the section above that defines it),
  split_seed, split_sizes,
  label_definition_ref,
  provenance (source of query material, annotator info — no PII),
  known_limitations
}
```

Any result reported in any future phase document or claim must name the
exact benchmark name + version it was measured against
(`EVALUATION_CONTRACT.md` §0 rule 4, §13). A benchmark revision (adding
examples, fixing a labeling error, changing the relevance definition) is a
new version — old results are not silently assumed comparable across
versions.

---

## Human-Review Requirements Summary

| Benchmark | Minimum human review |
|---|---|
| A. NLU | 100% of labels (LLM-assisted drafts allowed, never unreviewed) |
| B. Source-routing | inherits A; +50 queries with reviewed gold parameters |
| C. Retrieval | 100% of relevance judgments, pooled across methods |
| D. Multi-source | inherits C's relevance judgments + linkage review for multi-hop |
| E. Grounding | 100% of claim support judgments; separate ≥100-claim calibration slice never used for judge tuning |
| F. End-to-end | 100% of workflow-success component judgments where not deterministically derivable |
| G. Reliability | scenario design reviewed; pass/fail criteria fixed before running, not adjusted after seeing results (matching the discipline already demonstrated in `RESULTS_RAG_COMPARISON.md` §1) |

No benchmark in this plan treats LLM-generated labels as final ground truth
without independent human review — this is a hard requirement carried
directly from the Phase 1 instructions and from the specific failure mode
(unvalidated judge output) that the Phase 0 audit already found in the
existing codebase.
