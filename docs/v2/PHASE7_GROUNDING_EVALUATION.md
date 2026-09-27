# Phase 7: Grounding + Citation Evaluation — Implementation Record

Status: **COMPLETE / FROZEN.** Historical record of what was built and
measured.

## 1. Two systems

**System A (evaluator):** `grounding_eval/` package — validated against
36 independently-authored, Evidence-backed gold claim/citation labels
before ever being used to measure System B. **System B (Phase-6
generator):** `generation/pipeline.py::generate_grounded_answer`, frozen
and unmodified — measured only after System A's own validation passed.

## 2. Architecture

- **Models** (`grounding_eval/models.py`): `SupportLabel` (4 values),
  `CitationRelation` (4 values), `ClaimGroundingJudgment`,
  `CitationGroundingJudgment`, `AnswerGroundingEvaluation`. No
  chain-of-thought field anywhere.
- **Candidate A** (`grounding_eval/deterministic.py`): numeric exact-match
  + lexical word-overlap, no LLM call. Baseline.
- **Candidate B — SELECTED** (`grounding_eval/judge.py`): one Cerebras
  `qwen-3.8-27b` strict-JSON-schema call per claim, judging the whole
  claim + all its cited Evidence together.
- **Candidate C** (`grounding_eval/pipeline.py`): deterministic numeric
  precheck (hard override) + Candidate B. Not selected — see Section 4.
- **Pipeline** (`grounding_eval/pipeline.py::evaluate_claim`/
  `evaluate_answer`): the sole entry points; isolated input signature
  (claim, evidence, architecture only — no generator prompt/gold/other
  outputs).

## 3. Real defect found and fixed (evaluator)

Candidate B's initial prompt allowed the judge to use outside biomedical/
regulatory domain knowledge to call CONTRADICTED when a claim added an
overclaiming detail the Evidence simply never addressed (e.g. "fully
validated as curative" attached to a Phase-2-only claim). Fixed by adding
an explicit CRITICAL DISTINCTION section to the prompt: CONTRADICTED
requires the Evidence's own stated content to be the source of conflict,
never an inference from outside knowledge. Verified: dev 20/22 → 22/22,
validation 5/5. Full account: `artifacts/v2/phase7_failure_analysis.json`
finding F1.

## 4. Candidate C not selected

A real, measured defect: the deterministic numeric precheck's
word-boundary regex is asymmetric between free-prose claims ("Phase 2")
and compact enum-style Evidence fields ("PHASE2"), causing false
CONTRADICTED overrides. Partially fixed (11/22 → 16/22) but not fully
— not worth further engineering since Candidate B alone already reaches
100% dev+validation. Full account: `artifacts/v2/phase7_failure_analysis.json`
finding F2, `artifacts/v2/phase7_evaluator_candidate_comparison.json`.

## 5. Same-model caveat

Both the Phase-6 generator and the selected Phase-7 evaluator use Cerebras
`qwen-3.8-27b`. This is **never** described as cross-model independent
validation — it is a separate evaluation path (isolated input, no shared
prompt/context/gold), validated against independently-authored gold. See
`docs/v2/CLOUD_TO_LOCAL_GAP_CLOSURE.md` for the recorded item on obtaining
a genuinely distinct-provider comparison locally.

## 6. Benchmark

36 claim-level cases (22 dev, 5 validation, 9 held-out), built from real
Phase-5 Evidence (brigatinib, imatinib, melanoma indications, tebentafusp
trial). Grouped by "family" (same underlying fact + its
SUPPORTED/PARTIALLY_SUPPORTED/UNSUPPORTED/CONTRADICTED variants) so no
family straddles splits. Smaller than the suggested 60-case target — a
first Phase-7 benchmark, documented honestly, not padded with
lower-quality synthetic cases.

## 7. Evaluator validation results

Dev+validation: 27/27 = 100% accuracy, macro-F1 1.0 across all 4 classes.
Held-out (run once, frozen): 9/9 = 100% accuracy, macro-F1 1.0. All
predeclared thresholds (macro-F1 ≥0.90, unsupported/contradicted recall
≥0.95, schema-valid 100%) exceeded. All 10 hard gates pass.

## 8. Phase-6 system semantic grounding results

Measured on a fresh 8-case system-evaluation set (real queries/Evidence
reused from Phase-6's dev/validation split, never its held-out split;
answers generated once under the frozen Phase-6 architecture):

- 16 total factual claims across 8 answers (2 of the 8 correctly
  abstained with 0 claims — zero/insufficient-Evidence cases)
- **Claim support rate: 16/16 = 100%**
- **Unsupported/contradicted claims: 0**
- **Citation precision: 1.0** (mean across non-abstained answers)
- **Claim citation coverage: 1.0**
- **Answer-level fully-grounded rate: 8/8 = 100%**
- Abstention grounding: 2/2 correct. Conflict grounding: 1/1 correct (the
  melanoma-phase-variation case produced 3 distinct, correctly-cited
  claims, no averaged/fabricated consensus).

**No Phase-6 defect was discovered.** This is a real, positive result on
a modest sample (16 claims) — not claimed as proof of zero hallucinations
at scale; see Section 9's caveats.

## 9. Accepted, non-blocking limitations

- Benchmark scale (36 claim-level, 8 answer-level) is smaller than the
  suggested targets (60 / 20) — a first Phase-7 benchmark.
- No genuinely distinct-provider evaluator was validated in this cloud
  session (same-model caveat, Section 5).
- Evaluator token/cost figures were not captured this session
  (`grounding_eval/judge.py::_invoke_judge` doesn't currently parse the
  Cerebras usage block) — an accepted gap, does not affect accuracy or
  any hard gate.
- The 8-case Phase-6 system-evaluation set found zero defects — a
  positive result, but with a small sample; it does not license a claim
  of "zero hallucinations globally" (explicitly excluded, see
  `docs/v2/RESUME_METRIC_CANDIDATES.md`).
- Citation-set sufficiency for genuinely multi-required-Evidence-group
  claims was validated in the evaluator's own benchmark (P7-M1/M2) but
  not separately re-measured in the smaller Phase-6 system-eval set (no
  such case happened to appear in the 8 selected cases).
