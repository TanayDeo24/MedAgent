# Phase 2 Reopen Analysis — Candidate A vs Candidate B

Status: written during the Phase 2 CLOSURE pass, after the human reviewer
retracted the "PHASE 2 COMPLETE" declaration. This document only re-examines
the decision already made using data already collected in
`artifacts/v2/nlu_baseline_results.json`,
`artifacts/v2/nlu_candidate_b_dev_results.json`,
`artifacts/v2/nlu_candidate_results.json`, `artifacts/v2/nlu_frozen_config.json`
and `artifacts/v2/nlu_test_split_results.json`. No new experiments were run to
produce this document — see `docs/v2/PHASE2_CLOSURE_REPORT.md` (or, if that
file does not exist yet, the closure pass's final chat report) for what
closure work was and was not completed.

## 1. What the composite score actually was

`docs/v2/PHASE2_BIOMEDICAL_NLU.md` (§13-14) and `artifacts/v2/nlu_candidate_results.json`
state the selection rule as "average across the three primary metrics" and
give scores 0.345 (A) vs 0.706 (B). This is reconstructable exactly from the
raw numbers:

```
composite = mean(entity_f1_micro, intent_macro_f1, source_set_f1_micro)
```

with **0 substituted** whenever a candidate structurally cannot produce a
metric. Verification:

- Candidate A: `mean(0.8859, 0.1497, 0) = 0.3452` ✓ matches 0.345
- Candidate B: `mean(0.7669, 0.4809, 0.8704) = 0.7061` ✓ matches 0.706

This confirms the formula, but it also exposes three problems that were not
stated plainly in the original Phase 2 writeup:

1. **The formula was never committed as code.** Neither
   `evaluation/v2/nlu_metrics.py` nor `evaluation/v2/run_nlu_eval.py` contains
   this averaging logic — it exists only as prose in the markdown doc and as
   a baked-in `selection_notes` string in the JSON artifact. The composite is
   not reproducible by re-running any script in the repo; it had to be
   reverse-engineered by hand for this analysis. That is itself a
   reproducibility defect independent of whether the formula was reasonable.

2. **Candidate A is structurally disqualified on 1 of its 3 scored metrics,
   not just weaker on it.** Candidate A (the unmodified
   `agent/nodes.py::query_analysis_node`) has no source-requirement
   prediction output at all — `source_set_f1_micro` is `null` in
   `nlu_baseline_results.json`, and the composite scores that as `0.0`,
   identical to "attempted and got everything wrong." That single
   substitution contributes `0.29` of A's `0.345` final gap to B on its own
   (removing that term: A would average `(0.8859+0.1497)/2 = 0.518` vs B's
   `(0.7669+0.4809)/2 = 0.624` — B still wins, but by a much smaller margin,
   0.62 vs 0.52 rather than 0.71 vs 0.35). The composite therefore
   overstates the gap between the architectures relative to what a
   same-capability comparison would show.

3. **Entity F1 — the metric that most directly measures whether the
   downstream retrieval/tool layer gets the right biomedical terms — and
   Normalization Accuracy@1 — the metric that most directly measures
   whether IDs handed downstream are trustworthy — were both computed
   (they appear in `nlu_candidate_results.json`) but were EXCLUDED from the
   selection formula.** Constraint F1 (0.508 for B, not computable for A)
   was also excluded. So the axis that regressed most sharply
   (Entity F1: 0.886 → 0.767, an 11.9-point drop) was measured but never
   entered the decision; the axis that improved the least meaningfully for a
   query-understanding stage (source-set prediction, essentially "which of
   {pubmed, clinicaltrials, chembl} to call," a coarse-grained routing
   signal) got full 1/3 weight and, via the `null→0` substitution, ended up
   the single largest driver of the decision margin.

## 2. Was Candidate B actually the best system?

**No — not unconditionally.** B was the best system *under this specific
3-metric composite with 0-substitution for a structurally-absent metric on
A*. Under any composite that (a) does not zero-fill a structurally-impossible
metric for one arm, or (b) includes Entity F1 and Normalization at their
already-measured values, the picture changes:

| Formula (dev split) | Candidate A | Candidate B | Winner |
|---|---|---|---|
| Actual formula used (entity, intent-macro-F1, source; A's source=0) | 0.345 | 0.706 | B, by 0.36 |
| Same 3 metrics, source term dropped entirely (2-metric avg) | 0.518 | 0.624 | B, by 0.11 |
| Equal-weight avg of ALL 5 measured metrics (entity, intent-acc, norm@1, source, constraint; null→excluded not zeroed) | (0.886+0.267+0.0)/3=0.384 | (0.767+0.556+0.785+0.870+0.508)/5=0.697 | B, by 0.31 |
| Entity-F1-gated (A's exit gate requirement, item 3 below, applied first) | disqualified (n/a) | passes | B (A never had normalization/intent/constraints at all, so it was never a viable end system either way) |

B wins under every reasonable recombination once normalization and intent are
counted, because A literally has **zero** normalization, constraint
extraction, or source prediction capability — its architecture is a bare
entity+intent LLM call with no schema enforcement and no normalization
lookups at all (`normalization_mechanism: "none - architecture has no
normalization capability"` per `nlu_experiment_plan.json`). A is not a
competitive *end system* under the Phase 2 `ResearchQuery` contract
(`PRODUCT_CONTRACT.md` requires normalized entities, structured constraints,
and source-set prediction, none of which A can produce), so "B vs A" was
never really a fair fight — A was a measurement baseline for entity/intent
quality only, not a candidate final architecture.

**So the real error was not "B beat A unfairly."** It was: **the composite
metric, by construction, could not detect that B's own entity extraction had
regressed relative to A's**, because Entity F1 was demoted to a non-decision
input despite being calculated. The Phase 2 sign-off then implicitly treated
"B is the best of the two candidates measured" as equivalent to "B's entity
extraction is fine," which the composite provided no evidence for either way
— it simply never looked.

## 3. Where B regressed, in the data already collected

From `nlu_baseline_results.json` / `nlu_candidate_b_dev_results.json` /
`nlu_test_split_results.json` (all pre-existing, not re-run here):

| Metric | A (dev) | B (dev) | B (test) |
|---|---|---|---|
| Entity F1 micro | 0.886 | 0.767 | 0.745 |
| Entity F1 macro | 0.888 | 0.744 | 0.724 |
| Entity precision (micro) | 0.805 | 0.750 | 0.712 |
| Entity recall (micro) | 0.985 | 0.785 | 0.782 |

The drop is concentrated in **recall** (0.985 → 0.785 dev, → 0.782 test), not
precision, and is stable across dev and test (0.767 → 0.745, no evidence of
dev-only overfitting making it look artificially better than it is — if
anything B's entity performance is slightly worse on test, consistent with
a genuine, non-noise regression rather than a fluke of the 45-example dev
split). A's much higher recall is partly an artifact of A being an
unconstrained free-text extraction with no schema discipline (more surface
strings proposed, more of gold recall covered, but also — per
`nlu_experiment_plan.json`'s framing of A as "measurement only," not a
validated candidate — no evidence A's precision holds up under stricter
scoring). This closure pass did **not** re-run a per-entity-type breakdown
for both candidates (that requires re-executing `nlu_metrics.py` against the
raw per-example predictions, which are present in `nlu_test_split_results.json`'s
`per_example_results` but were not present for the dev-split B/A runs in a
form this pass parsed) — that is one of the still-open closure items (see
final report, item 3/16).

## 4. Conclusion for this document

The original Phase 2 architecture decision was not fabricated or dishonest —
the numbers it cites are real and reproduce exactly — but it was **decided
on an incomplete, uncommitted, and non-obviously-motivated composite metric**
that structurally could not surface the entity-extraction regression it later
turned out to have. B remains very likely the right foundation to build on
(A has no normalization/constraint/source capability at all and cannot meet
the `PRODUCT_CONTRACT.md` `ResearchQuery` shape), but declaring B "done" on
this composite, without a corrective pass on entity extraction specifically
and without decomposed subtask gates (closure item 2 / 18), was premature.
That is the core justification for treating Phase 2 as reopened rather than
merely "B, but iterate later."
