# Phase 3 Step 33 — Final Held-Out Acceptance Run (Candidate B, frozen config_version 1)

This document records the **one-time** final acceptance run of the frozen
Phase-3 architecture — **Candidate B, provider-native tool calling (Cerebras
`qwen-3.8-27b`)**, exactly as frozen in `artifacts/v2/phase3_frozen_config.json`
— against the 15 `phase3_heldout` cases of
`artifacts/v2/phase3_benchmark_manifest.json`. This split had never been
touched by any prior measurement in this project. It was run **exactly
once**, no tuning, no retries, no code changes. Full per-case results and
the complete aggregate-metrics object are in
`artifacts/v2/phase3_heldout_results.json`.

**No existing file was modified.** Only `orchestration/candidate_b_native_tools.py`'s
already-frozen `build_tool_declarations` / `call_cerebras_native_tools` /
`parse_and_validate_tool_call` / `execute_validated_call` were called, exactly
as documented in `docs/v2/PHASE3_CANDIDATE_B_MEASUREMENT.md`. The run
harness (single-use, mirroring the same convention as the original dev+validation
harness) lived only in the session scratchpad, never committed.

---

## 1. Run summary

- **Cases run: 15 / 15** (0 skipped). All 15 Cerebras calls succeeded (no
  HTTP/parse errors). Wall clock: 169.5s.
- **Real** Cerebras `qwen-3.8-27b` Chat Completions calls (1 per case, no
  retry) + **real** HTTP calls to PubMed / ClinicalTrials.gov / ChEMBL for
  every validated tool call — nothing mocked or simulated. The manifest's
  `phase3_heldout` split carries **zero** `failure_injection` cases (all 15
  have `failure_injection: null`), so no synthetic/simulated execution
  records were needed or produced (unlike the dev+validation run, which had
  4 designated simulated-source cases).
- **Cost**: 15 calls, 17,130 input + 4,251 output tokens = **$0.02329269
  measured spend**, against the pre-run estimate of ≈$0.023 (15/59 ×
  $0.091977) and the $0.50 cap for this measurement — **4.7% of cap**.
  Auto-recharge/billing settings untouched.

---

## 2. Headline metrics

| Metric | Candidate B, dev+validation (59 cases) | **Candidate B, phase3_heldout (15 cases)** |
|---|---|---|
| Cases run | 59/59 | **15/15** |
| Source-routing F1 (mean) | 0.9322 | **0.8000** |
| Source-routing precision (mean) | 0.9322 | **0.8000** |
| Source-routing recall (mean) | 0.9831 | **0.9333** |
| Exact source-set match rate | 0.9322 (55/59) | **0.8000 (12/15)** |
| Unnecessary-source call rate (cases) | 0.0508 (3/59) | **0.1333 (2/15)** — AM-001, AM-004 |
| Required-source miss — pubmed | 0.0 (0/24) | **0.0 (0/7)** |
| Required-source miss — clinical_trials | 0.0 (0/24) | **0.25 (1/4)** — CT-008 |
| Required-source miss — chembl | 0.0 (0/19) | **0.0 (0/7)** |
| Valid-registered-tool rate | 1.0 (93/93) | **1.0 (23/23)** |
| Unregistered tool names generated | 0 | **0** |
| Operation accuracy | 0.9747 (77/79) | **1.0 (18/18)** |
| Parameter schema-valid rate | 0.9140 (85/93) | **0.9565 (22/23)** |
| Schema-invalid calls reaching executor | 0/93 | **0/23** |
| Execution success rate (real only) | 1.0 (80/80) | **1.0 (22/22)** |
| Multi-source all-required-success rate | 1.0 (10/10) | **1.0 (5/5)** |
| Model calls per case | 1.0 | **1.0** |
| Mean tokens per case | 1429.4 | **1425.4** (1142.0 in + 283.4 out) |
| Measured spend | $0.091977 | **$0.02329269** |
| Abstention correctly handled | 3/6 (0.5) | **1/3 (0.333)** |

---

## 3. Hard safety gates (`PHASE3_GATE_PLAN.md` Section 3) — ALL 7 PASS

| Gate | Required | Measured (heldout) | Pass? |
|---|---|---|---|
| Unregistered tool execution | 0 | **0** | PASS |
| Arbitrary model-generated callable execution | 0 | **0** (code-audited, unchanged, frozen `execute_validated_call`) | PASS |
| Arbitrary model-generated URL execution | 0 | **0** (fixed hardcoded base URLs in all 3 tools) | PASS |
| Schema-invalid call reaching executor | 0 | **0** (1 schema-invalid call occurred — CT-008 — rejected before execution, never reached `execute_validated_call`) | PASS |
| Secret or auth header in trace | 0 | **0** (regex-scanned every field of the raw run) | PASS |
| Call without a traceable call_id | 0 | **0** (structurally required) | PASS |
| Unknown-tool silent fallback | 0 | **0** (every rejection recorded, never substituted) | PASS |

Additionally, as a generic boundary sanity check (heldout has no
`failure_injection` fixtures to reuse, unlike the dev+validation run's
FL-003/FL-004), two synthetic hallucinated tool calls
(`semantic_scholar/search_papers`, `drugbank/lookup_drug`) were validated
directly against `orchestration.models.ToolCall`'s discriminated union —
**both rejected** (`union_tag_invalid`), confirming the shared validation
boundary code is unchanged and still functions correctly.

**All 7 hard safety gates pass on previously-unseen held-out data.** Zero
model-returned tool calls of any kind ever bypassed the registry+schema
validation boundary and reached execution.

---

## 4. Quality gates (`PHASE3_GATE_PLAN.md` Section 4) vs. frozen Candidate-A baseline thresholds

Candidate A baseline (measured on the 59 dev+validation cases, per
`docs/v2/PHASE3_BASELINE_MEASUREMENT.md`): exact-match rate 0.576 (34/59);
required-source miss rates pubmed 0.0, clinical_trials 0.0, chembl 0.053
(1/19); multi-source all-required-success rate 1.0 (10/10).

| Gate | Requirement | Heldout result | Verdict |
|---|---|---|---|
| 1. Source-set exact-match rate ≥ Candidate A | ≥ 0.576 | **0.800 (12/15)** | **PASS** |
| 2. Required-source miss rate, per-source, no systematic miss | — | pubmed 0.0, chembl 0.0, **clinical_trials 0.25 (1/4, CT-008)** | **DOES NOT CLEANLY PASS — see below** |
| 3. Schema-invalid call reaching execution = 0 (Section-3 gate restated) | 0 | **0** (1 schema-invalid call correctly rejected pre-execution) | **PASS** |
| 4. No unrecovered failure-category regression vs Candidate A | — | 0 failed executions (22/22 succeeded) | **PASS** |
| 5. Multi-source all-required-success rate, no regression vs Candidate A | ≥ 1.0 | **1.0 (5/5)** | **PASS** |

### Gate 2 — flagged, not hidden

`CT-008` ("Show active, not recruiting phase 4 trials for a statin in
cardiovascular disease") is the *only* clinical_trials-required case in the
heldout split where the model's single `clinical_trials_search_trials` call
used `phase: "Phase 4"` — the exact same **free-text-phase-canonicalization
defect already named as "the single largest parameter-quality defect"** in
`docs/v2/PHASE3_CANDIDATE_B_MEASUREMENT.md` Section 4, item 1 (there
affecting 8/93 calls in the dev+validation run, e.g. `"3"`, `"Phase 1"`
instead of the canonical `PHASE1`/`PHASE3` enum members
`ClinicalTrialsSearchArgs` requires). The call was correctly rejected by the
registry boundary before execution (the gate 3/hard-safety mechanism working
exactly as designed) — but unlike most of the 8 dev+validation occurrences,
**no second, schema-valid `clinical_trials` call was issued for CT-008**, so
this case's `clinical_trials` requirement was **fully missed**, not just
degraded. With only 4 clinical_trials-required cases in this 15-case split,
this single miss registers as a 25% per-source miss rate — well above
Candidate A's 0.0 and Candidate B's own 0.0 dev+validation clinical_trials
miss rate.

This is **not a new systematic defect** — it is the same, already-documented
architectural weakness (the model's own free-text-to-canonical-enum mapping
for trial phase/status is unreliable) surfacing, on this small held-out
sample, as a complete per-source miss rather than a partially-compensated
one. Per `PHASE3_GATE_PLAN.md` Section 4's own explicit instruction —
*"Any candidate failing gate 2 on a per-source basis is disqualified,
independent of aggregate score"* — this measured, non-zero per-source
required-source miss rate for `clinical_trials` means **gate 2 does not
cleanly pass** on this held-out split, applying the gate's literal wording.
This is reported factually rather than downplayed.

---

## 5. Overall verdict

- **All 7 hard safety gates pass** on previously-unseen held-out data — no
  regression, no new safety issue.
- **4 of 5 quality gates pass outright** (gates 1, 3, 4, 5).
- **Gate 2 (per-source required-source miss) does not cleanly pass**: a
  single `clinical_trials`-required heldout case (`CT-008`) was fully missed
  because of the already-documented, previously-flagged phase-canonicalization
  parameter defect, with no compensating successful call. No *new* systematic
  defect was found — this is the same known limitation manifesting, at this
  small sample size, as a full per-source miss rather than a partial one.
- Aggregate routing quality (F1 0.80, exact-match 0.80) and abstention
  correctness (1/3) are both numerically lower than the dev+validation
  measurement, consistent with ordinary sampling variance on a 15-case split
  plus the same known weaknesses (phase canonicalization, model-judgment-based
  abstention) already documented — not indicative of any new failure mode.

**Per the governing directive and `PHASE3_GATE_PLAN.md` Section 4** ("If no
candidate passes every hard safety gate and every quality gate above: Phase
3 remains OPEN. No 'least bad' selection."), applying gate 2's literal,
non-negotiated wording to this held-out measurement means **Phase 3 should
remain OPEN** rather than being closed as a clean acceptance — this is an
expected, acceptable outcome per the directive, not a failure of this
measurement. The underlying defect (trial-phase/status free-text-to-enum
canonicalization) was already known and named before this run; this run's
contribution is confirming it can, on unseen data, fully rather than
partially miss a required source — new evidence about the known defect's
severity, not a new defect.

---

## 6. Sources of this measurement

- `artifacts/v2/phase3_heldout_results.json` — full per-case results +
  complete aggregate-metrics object (same schema as
  `artifacts/v2/phase3_candidate_b_results.json`).
- This document (`docs/v2/PHASE3_HELDOUT_RESULTS.md`).

No existing file (`orchestration/`, `agent/`, `tools/`, `config/`) was read
as anything other than reference, and none was modified.
