# Phase Metrics Ledger

**Purpose:** the single authoritative, artifact-traced record of every
defensible before/after quantitative result produced by MedAgent V2 so far.
This ledger exists specifically so that future phases (and any resume/report
writing) pull numbers from here — verified, dated, and source-linked — rather
than re-deriving or re-rounding them from scratch each time.

**Status as of this entry:** Phase 2 complete (23/23 gates pass, human
authorization for Phase 3 pending separately). Only Phase 2 metrics are
recorded below; this file will gain a new dated section per phase as later
phases complete.

**Every number below was independently recomputed from the raw artifact
files during this ledger-freeze step** (not copied from prior prose reports
verbatim) — see the "recomputation note" under each metric.

---

## Phase 2 — Biomedical NLU

**Final winner:** Cerebras `qwen-3.8-27b`, `reasoning_effort=none`, frozen
config version 3 (`artifacts/v2/nlu_frozen_config.json`). Uses the
**unmodified active-control prompt** (`STRUCTURED_EXTRACTION_PROMPT`) — zero
Qwen-specific semantic tuning was applied. Prior control:
`candidate_b_structured` (NVIDIA `nemotron-3-super-120b-a12b`), config
version 2, archived at `artifacts/v2/nlu_frozen_config_v2_pre_qwen_archive.json`.

**Benchmark:** `nlu_benchmark` v1.1.0, dev split, n=45 (both before and after
values below come from dev-split evaluations — see per-metric source; the
consumed 105-example Phase-2 test split and the not-yet-built Phase-10
held-out benchmark were never used for either value).

### Entity F1

| | |
|---|---|
| Before (Nemotron) | 0.9008 |
| After (Qwen) | 0.971830985915493 |
| Absolute delta | +0.071031 |
| Relative improvement | **+7.8853%** |
| Benchmark / n | nlu_benchmark v1.1.0, dev, n=45 |
| Before source | `artifacts/v2/nlu_frozen_config.json` → `gate_comparison_vs_prior_control_candidate_b_structured.entity_f1_micro.control` |
| After source | `artifacts/v2/nlu_cerebras_qwen_candidate_results.json` → `entity_prf.micro.f1` |
| Before configuration | candidate_b_structured / NVIDIA nemotron-3-super-120b-a12b |
| After configuration | candidate_g_cerebras_qwen / Cerebras qwen-3.8-27b, reasoning_effort=none |
| Recomputation note | recomputed directly: `(0.971830985915493 - 0.9008) / 0.9008 * 100` |
| Caveat | micro F1; per-type breakdown available in the same source artifact (target 1.0, compound 1.0, disease 0.9286 — one type, disease, carries all 4 FPs) |
| resume_safe | **true** |

### Intent Macro-F1

| | |
|---|---|
| Before (Nemotron) | 0.848 |
| After (Qwen) | 0.8884262796027502 |
| Absolute delta | +0.040426 |
| Relative improvement | **+4.7672%** |
| Benchmark / n | nlu_benchmark v1.1.0, dev, n=45 |
| Before source | `nlu_frozen_config.json` → `gate_comparison...intent_macro_f1.control` |
| After source | `nlu_cerebras_qwen_candidate_results.json` → `intent.macro_f1` |
| Before configuration | candidate_b_structured / NVIDIA nemotron-3-super-120b-a12b |
| After configuration | candidate_g_cerebras_qwen / Cerebras qwen-3.8-27b, unmodified prompt |
| Recomputation note | recomputed directly: `(0.8884262796027502 - 0.848) / 0.848 * 100` |
| Caveat | no class shows ≥80% one-directional misclassification in either configuration; Qwen's 4/45 errors include a pre-existing E→D boundary pattern already documented in the GPT-OSS round, not a new defect |
| resume_safe | **true** |

### Intent Accuracy (secondary, reported alongside Macro-F1)

| | |
|---|---|
| Before | 0.867 | After | 0.9111111111111111 |
| Absolute delta | +0.044111 | Relative improvement | **+5.0878%** |
| Source | same artifacts as Intent Macro-F1 above |
| resume_safe | true |

### Constraint F1

**Control-value ambiguity, disclosed rather than resolved by cherry-picking:**
the Phase 2 closure record contains two constraint-F1 values for the
Nemotron control depending on which closure-round dev rerun is cited:
**0.788** (micro), explicitly labeled "Post-closure (final dev rerun)" in
`docs/v2/PHASE2_CLOSURE_REPORT.md` §9 — treated as **primary** here because
it is the one explicitly designated "final" — and **0.818**, appearing in
`artifacts/v2/nlu_frozen_config.json`'s gate-comparison range from an earlier
closure-round measurement. Both are reported; the smaller-percentage (0.818)
comparison is included specifically so the range isn't read as inflated by
picking the lower bound.

| | Using 0.788 (primary) | Using 0.818 (alternate) |
|---|---|---|
| Before (Nemotron) | 0.788 | 0.818 |
| After (Qwen) | 0.84375 | 0.84375 |
| Absolute delta | +0.055750 | +0.025750 |
| Relative improvement | **+7.0749%** | **+3.1479%** |

| | |
|---|---|
| Benchmark / n | nlu_benchmark v1.1.0, dev, n=45 |
| Before source | `docs/v2/PHASE2_CLOSURE_REPORT.md` §9 (0.788) and `nlu_frozen_config.json` gate-comparison range (0.818) |
| After source | `nlu_cerebras_qwen_candidate_results.json` → `constraint_prf.micro.f1` |
| Recomputation note | both deltas recomputed directly from the stated before/after values |
| Caveat | per-field breakdown shows `trial_phases` F1 1.0, `trial_statuses` 0.8421; `geography`/`age`/`temporal`/`outcomes` show FP-only noise at support=0 in the Qwen run (minor over-extraction on fields with zero gold instances in this particular dev split, not a broken field — `formatting_mismatches: 0, semantic_misses: 4` per the same artifact) |
| resume_safe | **true, only when both the metric value AND the control-value ambiguity are disclosed together — do not state a single unqualified "control F1" number** |

### Normalization Accuracy@1 (secondary)

| | |
|---|---|
| Before | 0.8551 | After | 1.0 |
| Absolute delta | +0.1449 | Relative improvement | **+16.9454%** |
| Benchmark / n | dev, n=69 normalizable gold entities (Qwen side; before value from control artifact) |
| Source | `nlu_frozen_config.json` gate comparison; `nlu_cerebras_qwen_candidate_results.json` → `normalization` |
| resume_safe | true |

### Schema Parse Success Rate (secondary)

| | |
|---|---|
| Before | 0.911 | After | 1.0 |
| Absolute delta | +0.089 | Relative improvement | **+9.7695%** |
| Source | `nlu_frozen_config.json` gate comparison; `nlu_cerebras_qwen_candidate_results.json` → `schema_parse_success_rate` (45/45, 0 schema_parse_failures) |
| resume_safe | true |

### P50 NLU Latency

| | |
|---|---|
| Before (Nemotron) | 19,150 ms |
| After (Qwen) | 471.01902961730957 ms |
| Absolute reduction | 18,678.98097 ms |
| Relative reduction | **97.5404%** |
| Benchmark / n | dev, n=45 (Qwen); n=45 (Nemotron control, per `nlu_latency_baseline.json`) |
| Before source | `nlu_frozen_config.json` gate comparison → `latency_p50_ms.control`, traced to `artifacts/v2/nlu_latency_baseline.json` |
| After source | `nlu_cerebras_qwen_candidate_results.json` → `latency_ms.p50` |
| Measurement methodology | throttle-corrected — excludes the deliberate 5-RPM rate-limiter self-throttle wait; the same file also preserves `latency_ms_raw_including_throttle.p50` (12,068.8ms) for transparency, which must NOT be quoted as model latency |
| Recomputation note | `(19150 - 471.01902961730957) / 19150 * 100` |
| resume_safe | **true — but always state "throttle-corrected / true inference latency" when citing this number, since the raw wall-clock figure is ~25x larger and would be misleading if conflated** |

### P95 NLU Latency

| | |
|---|---|
| Before (Nemotron) | 66,983 ms |
| After (Qwen) | 1,175.8742332458496 ms |
| Absolute reduction | 65,807.126 ms |
| Relative reduction | **98.2445%** |
| Benchmark / n | dev, n=45 |
| Before source | `nlu_frozen_config.json` gate comparison → `latency_p95_ms.control` |
| After source | `nlu_cerebras_qwen_candidate_results.json` → `latency_ms.p95` |
| Measurement methodology | throttle-corrected, same caveat as P50 above |
| Recomputation note | `(66983 - 1175.8742332458496) / 66983 * 100` |
| resume_safe | **true, with the same throttle-corrected caveat as P50** |

### Fabricated Canonical IDs

| | |
|---|---|
| Before | 0 | After | 0 |
| Change | **maintained at zero** — this is not a percentage improvement and must never be reported as one |
| Source | `nlu_frozen_config.json` gate comparison → `fabricated_id_count`; `nlu_cerebras_qwen_candidate_results.json` → `normalization.fabricated_id_count` |
| resume_safe | true, stated exactly as "0 fabricated IDs, both before and after" |

### Reliability (Qwen full dev run, no "before" comparison — new measurement)

| | |
|---|---|
| Evaluation n | 45 |
| Total real inference calls this round (smoke + pilot + dev) | 54 (1 + 8 + 45) |
| Provider errors | 0 |
| Schema failures | 0 |
| Retries needed | 0 |
| Source | `nlu_cerebras_qwen_candidate_results.json`; `nlu_frozen_config.json` → `final_acceptance_step31_check.provider_reliability_acceptable` |
| resume_safe | true |

### Cost (measured, plus clearly-labeled projections)

| | |
|---|---|
| Qwen dev-run measured cost | **$0.11006** (computed from measured token usage × official Cerebras pricing: 93,628 input tokens × $0.99/1M + 11,654 output tokens × $1.49/1M) |
| Measured cost per call (dev run) | **$0.002446** (= $0.11006 / 45) |
| Pilot cost (8 calls) | $0.01955 |
| Smoke-test cost (1 call) | $0.00093 |
| **Total Qwen-round spend** | **$0.13054** |
| Prior GPT-OSS-round cumulative spend (all 3 rounds, permanently rejected candidate) | $0.03507 |
| **Cumulative Cerebras Phase-2 experiment spend** | **$0.16561** (33.12% of the $0.50 experiment cap) |
| Remaining experiment cap | $0.33440 |
| Source | token counts from `nlu_cerebras_qwen_candidate_results.json` → `token_accounting`; pricing from `nlu_frozen_config.json` → `pricing_per_million_tokens_usd`; prior spend from `artifacts/v2/nlu_cerebras_intent_revision_pilot_results.json` and `nlu_cerebras_gptoss_pilot_results.json` usage/cost fields |
| resume_safe (measured figures) | **true** |

**Projections — explicitly NOT measured, must always be labeled as projections:**

| Projected call volume | Projected cost (Phase-2-NLU-call-only, at $0.002446/call) |
|---|---|
| 100 calls | ~$0.245 |
| 1,000 calls | ~$2.446 |
| 10,000 calls | ~$24.46 |

resume_safe for projections: **true only when explicitly labeled "projection, Phase-2-NLU-call cost only, not full end-to-end MedAgent cost, extrapolated from a 45-call measured sample."** Never state as a measured result.

---

## Final Frozen Winner (Phase 2)

| Field | Value |
|---|---|
| Provider | Cerebras |
| Model | `qwen-3.8-27b` |
| Reasoning effort | `none` (verified via live smoke test: `reasoning_tokens=0`) |
| Frozen config version | 3 (`artifacts/v2/nlu_frozen_config.json`) |
| Semantic Qwen-specific tuning | **NONE** — uses the byte-identical unmodified active-control `STRUCTURED_EXTRACTION_PROMPT` |
| Prior control (archived, not deleted) | candidate_b_structured / NVIDIA nemotron-3-super-120b-a12b, config v2, `artifacts/v2/nlu_frozen_config_v2_pre_qwen_archive.json` |
| Historical rejected candidates (preserved) | NVIDIA Lightning fast-model (generic-intent collapse), local Qwen2.5-1.5B-Instruct (catastrophic semantic quality), Cerebras GPT-OSS-120B (generic-A-collapse, 3 rounds), Cloudflare Workers AI (blocked pre-inference on billing risk) |
| Full test suite at freeze time | 139 passed, 0 failed, 0 skipped |
| Phase-2 gates at freeze time | 23/23 PASS (`docs/v2/PHASE2_FINAL_GATE_AUDIT.md`) |

---

## PHASE 2 RESUME-SAFE METRIC CANDIDATES

Only claims below are directly reproducible from the artifacts cited above.
Each includes the exact percentage (not rounded aggressively) alongside the
raw before/after values, per the instruction not to present a percentage
without its source numbers.

- Reduced P50 NLU-stage latency from 19.150s to 0.471s (throttle-corrected
  true inference latency) — a **97.5404% reduction**.
- Reduced P95 NLU-stage latency from 66.983s to 1.176s (throttle-corrected)
  — a **98.2445% reduction**.
- Improved Entity F1 from 0.9008 to 0.9718 — a **7.8853% relative
  improvement** (dev split, n=45).
- Improved Intent Macro-F1 from 0.848 to 0.8884 — a **4.7672% relative
  improvement** (dev split, n=45).
- Improved Intent Accuracy from 0.867 to 0.9111 — a **5.0878% relative
  improvement**.
- Improved Constraint F1 from 0.788 to 0.84375 — a **7.0749% relative
  improvement** (primary control value; using the alternate 0.818 control
  value from an earlier closure-round measurement, the improvement is
  3.1479% — report the range, not a single cherry-picked figure).
- Improved entity-normalization accuracy@1 from 0.8551 to 1.0 — a **16.9454%
  relative improvement**.
- Improved schema-parse success rate from 0.911 to 1.0 — a **9.7695%
  relative improvement**.
- Maintained 0 fabricated canonical IDs across both the prior control and the
  new candidate (not a percentage claim).
- Achieved 0 provider errors and 0 schema failures across all 54 real
  Cerebras inference calls made during the Qwen evaluation round.
- Measured cost of $0.002446 per Phase-2 NLU call on the winning
  configuration (Cerebras qwen-3.8-27b), derived from a 45-call measured dev
  run — any per-100/1,000/10,000-call figures derived from this are
  projections, not additional measurements.

**Not resume-safe as unqualified claims:** any constraint-F1 improvement
percentage stated without disclosing which control value (0.788 or 0.818) it
was computed against; any latency figure that doesn't specify
"throttle-corrected"; any cost-per-N-calls figure not labeled a projection;
any claim that GPT-OSS-120B was viable (it was permanently rejected); any
claim that the current Cerebras Free Trial billing arrangement is a
permanent production deployment decision (it is a $5/30-day trial, expiring
2026-10-25 UTC, not yet a resolved long-term provider decision).

---

## Phase 3 — Reliable Schema-Constrained Tool Orchestration

**Status:** Complete (see `docs/v2/PHASE3_STATUS.md` for the mid-phase
defect-and-fix cycle this entry reflects). **Final winner:** Cerebras
`qwen-3.8-27b` provider-native tool calling, validated through our own
typed registry (`orchestration/candidate_b_native_tools.py` +
`orchestration/registry.py` + `orchestration/models.py`), frozen config
version 2 (`artifacts/v2/phase3_frozen_config.json`). Replaced the legacy
free-text-dispatch pipeline (`planning_node` + `tool_execution_node`) in
`agent/nodes.py`, now collapsed into a single `tool_orchestration_node`.

**Benchmark:** `phase3_benchmark_manifest.json` v1 (74 cases: 44 dev / 15
validation / 15 held-out). Before/after values below use the 59
development+validation cases; the held-out split and its fresh supplement
(12 cases) were used only for the final blind acceptance check, never for
candidate selection or tuning.

**BEFORE system (Candidate A, the legacy pipeline) and AFTER system
(Candidate B, the selected winner) were both measured on the identical
basis**: raw `original_query` text through each system's own real,
end-to-end selection mechanism — no hand-authored structured input for
either. This is what makes the deltas below genuinely comparable (see the
non-comparable note below for why Candidate C's numbers are excluded from
this section).

### Source-routing F1

| | |
|---|---|
| Before (Candidate A, legacy) | 0.759 (mean, n=59) |
| After (Candidate B, winner) | 0.9322 (mean, n=59) |
| Absolute delta | +0.1732 |
| Relative improvement | **+22.8195%** |
| Source | `artifacts/v2/phase3_baseline_results.json`, `artifacts/v2/phase3_candidate_b_results.json` |
| resume_safe | true |

### Exact source-set match rate

| | |
|---|---|
| Before | 0.576 (34/59) |
| After | 0.932 (55/59) |
| Absolute delta | +0.356 |
| Relative improvement | **+61.8056%** |
| resume_safe | true |

### Parameter schema-valid rate (of calls reaching execution)

| | |
|---|---|
| Before | 0.738 — legacy has no schema-validation boundary at all; this is a retrospective check of legacy-generated params against the new typed schemas |
| After | 1.0 — structural: `orchestration/registry.py::validate_call()` makes a schema-invalid call reaching execution impossible by construction |
| Relative improvement | **+35.5014%** |
| resume_safe | true |

### Hard safety gates passed (of 7, `docs/v2/PHASE3_GATE_PLAN.md` Section 3)

| | |
|---|---|
| Before | 5/7 (fails: schema-invalid-call-reaching-executor, call-without-traceable-call-id — both by construction) |
| After | 7/7 |
| Not a percentage claim | stated as gate counts, not "improved by X%" |
| resume_safe | true |

### Abstention correctness (n=6 known abstention-expected cases, dev+validation)

| | |
|---|---|
| Before | 0/6 — legacy has no abstention concept; planning always selects tools, defaulting to all three on any failure |
| After | 3/6 |
| Not a percentage claim | small-n count, stated as a ratio |
| resume_safe | true |

### Model calls per case (orchestration stage only)

| | |
|---|---|
| Before | 2.81 (mean) |
| After | 1.0 (exact, every case) |
| Relative reduction | **64.4128%** |
| resume_safe | true |

### Total orchestration-stage latency (mean, ms)

| | |
|---|---|
| Before | ~23446.9 (planning 9066.7 + tool-execution 14380.2) |
| After | Cerebras call 792.1 + tool execution (not separately summed in the same field shape as the before measurement — see `artifacts/v2/phase3_candidate_b_results.json` for the full breakdown) |
| resume_safe | false — the two latency measurements use different aggregation shapes; do not compute a single relative-reduction percentage from this row without re-deriving both on the same basis first |

### Final held-out acceptance (after defect fix, config v2)

- Original held-out run (15 cases, config v1): found 1 genuine
  `clinical_trials` miss (case `CT-008`) caused by a non-canonical trial
  phase value the model guessed because the JSON schema didn't constrain
  it to an enum. **Phase 3 was declared OPEN, not closed, on this basis** —
  see `docs/v2/PHASE3_STATUS.md`.
- Fix: `orchestration/models.py`'s `ClinicalTrialsSearchArgs.status`/`.phase`
  changed from `Optional[str]` to `Optional[Literal[...]]` derived directly
  from `tools/clinical_trials_tool.py`'s own `VALID_TRIAL_STATUSES`/
  `VALID_TRIAL_PHASES` sets, so `.model_json_schema()` now exposes a real
  `enum` to the model.
- Regression check (dev+validation, 59 cases, same split used for candidate
  selection, not held-out): schema-valid rate 0.9140 → **1.0000**, all 8
  prior schema failures (all `clinical_trials` phase/status format
  mismatches) → 0.
- **Fresh held-out supplement** (12 new cases, never used anywhere else in
  this project, built specifically to re-test this defect without reusing
  the spent original held-out split): `clinical_trials` required-source
  miss rate **0/12**, schema-valid rate **16/16 (100%)**, all 7 hard safety
  gates pass. Source: `artifacts/v2/phase3_heldout_supplement_results.json`.
- **Conclusion:** the fix is confirmed effective on genuinely unseen data.
  Phase 3 closed on this basis.

### NOT resume-safe / explicitly non-comparable

- **Candidate C's source-routing F1 (1.0) and exact-match rate (1.0) are
  NOT included above and must never be cited as a Phase-3
  before/after improvement figure.** They were measured with
  `select_sources()` reading a `requested_evidence_types` field that the
  benchmark's own author hand-wrote consistent with that same case's gold
  label — not derived from a real Phase-2 NLU extraction. This is a
  measurement-validity gap, not a property of Candidate A or B, and mixing
  it into a "before/after" claim would misrepresent what was actually
  shown. See `docs/v2/PHASE3_CANDIDATE_C_MEASUREMENT.md` Section 0 and
  `docs/v2/PHASE3_WINNER_SELECTION.md` Section 2.
- Any Phase-3 latency figure without specifying which stage(s) it covers
  (orchestration-only vs. total including tool-execution HTTP time) —
  the two candidates' latency fields are not aggregated identically; see
  the "Total orchestration-stage latency" row above.
- Any claim that `get_drug_info` was "fixed" for Candidate A — it remains
  structurally unreachable in the legacy architecture (never wired into
  `tool_execution_node`'s dispatch); Candidate B/the new integration made
  it reachable for the first time, which is a capability added, not a bug
  fixed in the old system.
- Measured Cerebras spend for Phase 3 candidate/fix/held-out work
  ($0.091977 + $0.095467 + $0.02329 + $0.0183465 ≈ **$0.229** total across
  all Phase-3 Cerebras runs) is a separate, freshly-bounded budget from
  Phase 2's own cumulative Cerebras spend (~$0.1656) — do not sum the two
  phases' spend together and present it as a single "total Cerebras cost,"
  since they were authorized and capped independently.

---

## Phase 4 — Heterogeneous Retrieval

**Status:** Complete (see `docs/v2/PHASE4_STATUS.md` for the mid-phase
defect-and-fix cycle). **Winner:** local RAG hybrid pipeline for PubMed
(`retrieval/retriever.py`, unchanged architecture — Phase 4 validated it,
did not replace it), live ClinicalTrials.gov API with a fixed phase-filter
query construction, live ChEMBL API with a new `resolve_compound_name`
operation (config version 2, `artifacts/v2/phase4_frozen_config.json`).

**Benchmark:** `phase4_benchmark_manifest.json` v1 (61 cases: 37 dev / 12
validation / 12 held-out). Before/after values below use the 49
development+validation cases unless stated otherwise; the held-out split
and its fuzzy-match-focused supplement (10 cases) were used only for final
blind acceptance, never for candidate selection or tuning.

### Real production defect found and fixed: ClinicalTrials phase filter

`tools/clinical_trials_tool.py` sent trial-phase filters as an invalid
`filter.phase` API parameter — every phase-filtered ClinicalTrials.gov
query failed with a live HTTP 400, a defect that predated Phase 3 and
Phase 4. Fixed by moving phase filtering into `query.term` via
`AREA[Phase]<value>` syntax, matching the existing condition/intervention
pattern.

| | |
|---|---|
| Before (invalid `filter.phase` param) | Required-trial recall 0.737 (14/19) |
| After (fixed `AREA[Phase]` term) | Required-trial recall 0.895 (17/19) |
| Absolute delta | +0.158 |
| Relative improvement | **+21.44%** |
| Structured-filter-correctness rate | 0.850, unchanged (the defect was purely transport-layer, not query-compilation) |
| Benchmark | dev+validation, n=19 clinicaltrials-relevant cases |
| Source | `docs/v2/CLINICALTRIALS_PHASE_FILTER_DEFECT_FIX.md`, `artifacts/v2/phase4_baseline_results_clinicaltrials_phase_fix_amendment.json` |
| Caveat | Phase 3's own held-out supplement had a separate harness bug that masked this exact defect during what was meant to be its final blind confirmation — see `docs/v2/PHASE3_FINAL_GATE_AUDIT.md` addendum. |
| resume_safe | true |

### New capability: ChEMBL compound-name resolution

`ChEMBLTool.resolve_compound_name()` added — 13 of 21 ChEMBL benchmark
cases previously failed purely because no drug-name→ID resolution
operation existed (every such call 404'd).

| | |
|---|---|
| Before (no resolution operation) | Recall@10 0.381, MRR 0.279 (n=21) |
| After (resolve_compound_name added) | Recall@10 1.000, MRR 0.898 (n=21) |
| Absolute delta | Recall@10 +0.619, MRR +0.619 |
| Relative improvement | Recall@10 **+162.47%**, MRR **+221.86%** |
| Multi-source coverage | 0.0 → 0.571 (4/7) — remaining 3 misses attributed to the non-selected PubMed live-API path and one unrelated ClinicalTrials ranking miss, not ChEMBL |
| Benchmark | dev+validation, n=21 (ChEMBL), n=7 (multi-source) |
| Source | `docs/v2/PHASE4_CHEMBL_RESOLUTION.md`, `artifacts/v2/phase4_chembl_resolution_results.json` |
| Caveat | Live-verified against 7 real drug names (including the previously-confirmed osimertinib→CHEMBL3353410); wired end-to-end through Phase 3's typed registry and confirmed Cerebras-reachable (6th declared tool). |
| resume_safe | true |

### Real defect found and fixed: ChEMBL fuzzy-match false positives

Found during the Phase-4 held-out run (not dev/validation): the new
`resolve_compound_name`'s fuzzy-match tier had no similarity threshold, so
a completely fabricated compound name (`"Zorblatinix-9X"`) returned a
confident, real-but-unrelated ChEMBL ID instead of failing safely. Phase 4
was declared OPEN on this basis (not closed with known debt), fixed with a
`difflib`-based similarity gate (threshold 0.6), and reconfirmed via a
fresh, never-before-used 10-case held-out supplement.

| | |
|---|---|
| Before | Fuzzy-match tier: 0 similarity gate — 1 confirmed false-positive (fabricated name → real-but-wrong ID) |
| After | Fuzzy-match tier: similarity-gated — 0/4 fabricated names in the fresh supplement returned a misleading ID; 3/3 genuine near-miss typos and 2/2 synonym-tier cases still resolved correctly |
| Not a percentage claim | stated as "0 misleading matches, held-out-confirmed," not "improved by X%" — this is a safety/correctness fix, not a recall metric |
| Benchmark | Fresh 10-case supplement, never reused from the spent 12-case `phase4_heldout` split |
| Source | `docs/v2/CHEMBL_FUZZY_MATCH_THRESHOLD_FIX.md`, `docs/v2/PHASE4_CHEMBL_FUZZY_THRESHOLD_SUPPLEMENT_RESULTS.md` |
| resume_safe | true |

### PubMed: RAG vs. live API (causally-separated comparison)

The existing local RAG hybrid pipeline was validated as the correct
PubMed architecture — not replaced. A live-API alternative was built and
measured for comparison, with causal attribution kept separate per metric
(date-fix alone vs. compiler alone), and explicitly not selected.

| Candidate | Recall@10 | MRR | vs. RAG |
|---|---|---|---|
| RAG (existing, validated) | 0.773 | 0.636 | — |
| Old live API (implicit 2yr filter) | 0.045 | 0.045 | 17.2x worse |
| Fixed live API, raw query (date-fix isolated) | 0.045 | 0.045 | **+0.000 from the date-fix alone** — not the dominant cause |
| Fixed live API + query compiler | 0.136 | 0.059 | Still 5.7x worse than RAG |

- The date-range fix (removing an implicit 2-year lookback) is real and
  regression-tested, but **contributed 0.000 absolute Recall@10 on its
  own** on this benchmark — do not attribute the 0.045→0.136 combined
  improvement to the date fix; the query compiler drove the entire
  measured gain (+0.091 absolute, +202.22% relative, isolated to the
  compiler alone).
- Fusion (RAG + fixed live API) was evaluated for justification and
  explicitly **not built**: all 3 of the live path's hits were already
  hit by RAG, including on the 2 cases specifically designed to test
  whether the live path could recover RAG's stale-index misses — zero
  unique recall contribution found.
- Benchmark: dev+validation, n=22.
- Source: `docs/v2/PHASE4_HETEROGENEOUS_RETRIEVAL.md`, `artifacts/v2/phase4_pubmed_candidate_comparison.json`, `artifacts/v2/phase4_pubmed_candidate_plan.json`.
- resume_safe: true, with the causal-attribution caveat above always attached.

### Held-out acceptance (config v2, final)

- PubMed (RAG): Recall@1/5/10 = 1.0, MRR = 1.0 (n=4 positive-gold cases) — consistent with, not contradicted by, dev/validation.
- ClinicalTrials: 0 positive-gold cases in this split; zero-result correctness 2/2.
- ChEMBL: Recall@10/MRR = 1.0 (n=1 positive case); fuzzy-match supplement (separate, 10 cases): 10/10 correct.
- All 7 hard safety gates pass, verified empirically.
- Two accepted limitations documented, not blocking: ChEMBL `search_by_target`'s first-hit heuristic on ambiguous target names (3/21 dev+validation cases), and PubMed RAG's lack of a relevance floor (always returns k=10) — both pre-existing or architecturally out-of-scope for Phase 4, named explicitly rather than concealed.

### NOT resume-safe / explicitly non-comparable

- Any claim that the PubMed live-API date-range fix alone improved
  Recall@10 — it did not, measured in isolation (+0.000). The compiler
  drove the entire gain, and even then the resulting architecture was not
  selected (RAG remains the production path).
- Any claim that Phase 4 "replaced" or "upgraded" PubMed retrieval — RAG
  was validated, not changed. What Phase 4 added for PubMed is a
  tested-but-unused query compiler (`retrieval/pubmed_query_compiler.py`)
  available for future callers, not a production architecture change.
- The multi-source coverage figure (0.571) without noting it predates
  re-scoring the PubMed leg against the now-frozen RAG architecture — 2 of
  the 3 remaining misses were scored against the non-selected live-API
  path and are expected to improve, not yet re-measured.
- Any claim that the ChEMBL `search_by_target` wrong-entity behavior or
  the PubMed RAG relevance-floor gap has been fixed — both are named,
  accepted limitations, explicitly not addressed in Phase 4.

## Phase 5: Evidence + Provenance

Final architecture: `evidence/adapters.py` + `evidence/registry.py`, a
model-free, deterministic layer that normalizes real PubMed (RAG + live),
ClinicalTrials.gov, and ChEMBL source outputs into the canonical, typed
`Evidence` object (`evidence/models.py`). Wired into the LangGraph pipeline
as `agent.nodes.evidence_normalization_node`, inserted
`synthesis -> evidence_normalization -> verification` in `agent/graph.py`.
Frozen config: `artifacts/v2/phase5_frozen_config.json`.

Same 72 real records used for both the old-pipeline baseline
(`artifacts/v2/phase5_baseline_results.json`) and the new Evidence layer
(dev+validation 58 + held-out 14), so before/after deltas below are
population-comparable, not just directionally suggestive.

| Metric | Before (old `citations`) | After (Evidence) | Delta | Comparability |
|---|---|---|---|---|
| Provenance completeness (overall) | 0% (no combined definition existed) | 100% (152/152 dev+val, 45/45 held-out) | +100pp | COMPARABLE |
| Source URL construction rate | 27.8% (72 replayed citations) | 100% | +72.2pp | COMPARABLE |
| Content retention at citation level | 0.0% | 100% | +100pp | COMPARABLE |
| Trace linkage (call_id) | 0.0% | 100% (tool-backed); RAG's `call_id=None` is N/A-by-design | +100pp | COMPARABLE |
| Fabricated source IDs | not measured | 0 | — | NON-COMPARABLE (new gate, no prior baseline) |
| Normalization coverage | no equivalent concept | 100% (72/72) | — | NON-COMPARABLE |
| Serialization success | no defined contract | 100% (197/197) | — | NON-COMPARABLE |
| Normalization latency P50 | N/A | 0.0155ms (pure adapter cost, excludes network/LLM) | — | NON-COMPARABLE |

Full metric-by-metric detail (n, definitions, caveats): `artifacts/v2/phase_metrics_ledger.json`'s `phase_5_evidence_provenance` key.

### Hard safety gates

All 10 gates (`docs/v2/PHASE5_GATE_PLAN.md` Section 3) measured 0 on both
dev+validation and held-out (`docs/v2/PHASE5_HELDOUT_RESULTS.md`,
`docs/v2/PHASE5_FINAL_GATE_AUDIT.md`). Zero fabricated/corrupted IDs, zero
secret leaks, zero cross-source collisions, across 197 real Evidence
records.

### Live integration (this cloud session)

4/4 bounded fresh integration checks passed
(`artifacts/v2/phase5_live_integration_results.json`): PubMed local RAG,
ClinicalTrials, ChEMBL, and the legitimate PubMed placeholder/skip path.
`clinicaltrials.gov`/`ebi.ac.uk`/`eutils.ncbi.nlm.nih.gov` were not
allowlisted in this cloud session's network policy (only `api.cerebras.ai`
was added for the Phase-2 verification), so all 4 checks used real,
previously-captured raw records from the benchmark's development split
rather than fresh network calls — documented transparently, not
fabricated.

### Adapter consistency reconciliation

The documented `chembl_target_or_indication_result_to_evidence` empty-content
behavior was inspected directly in current code: it already returns `None`
(canonical skip), not `ValueError` — the amendment described in
`docs/v2/PHASE5_HELDOUT_RESULTS.md` is already present, with a passing
regression test (`test_chembl_molecule_result_with_no_real_content_returns_none`).
No code change was required or made.

### NOT resume-safe / explicitly non-comparable

- Any claim that Phase 5 fixed the citation/reference detachment
  (`state["citations"]` vs. `## References`) — it did not; that closure is
  explicitly Phase 6/7's job (`docs/v2/PHASE5_EVIDENCE_CONTRACT.md` Section 0).
- Any claim of citation faithfulness, claim grounding, verified-claim
  accuracy, or hallucination reduction — none of these exist yet.
- Any claim that Phase 5 improved retrieval quality or network/LLM
  latency — it is a pure downstream normalization layer.
- Any claim that the original 14-case `phase5_heldout` split was rerun as
  blind evidence in this session — it was not; only current *code* was
  inspected for the adapter consistency check.
