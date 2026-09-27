# Resume-Safe Metric Candidates

Pulled from `docs/v2/PHASE_METRICS_LEDGER.md` / `artifacts/v2/phase_metrics_ledger.json`.
These are the only claims from Phase 2 that are directly reproducible from
committed artifacts, each with its raw values preserved alongside the
percentage. Do not use a number from this file without also carrying its
caveat when the caveat exists — an unqualified version of several of these
would be misleading (see "Not resume-safe" at the bottom).

## Phase 2 — Biomedical NLU (Cerebras qwen-3.8-27b vs. NVIDIA Nemotron control)

- Reduced P50 NLU-stage latency from **19.150s to 0.471s** (throttle-corrected
  true inference latency, dev n=45) — a **97.54% reduction**.
- Reduced P95 NLU-stage latency from **66.983s to 1.176s** (throttle-corrected)
  — a **98.24% reduction**.
- Improved entity extraction F1 from **0.9008 to 0.9718** — a **7.89%
  relative improvement** (dev n=45).
- Improved intent classification Macro-F1 from **0.848 to 0.888** — a
  **4.77% relative improvement** (dev n=45).
- Improved intent classification accuracy from **86.7% to 91.1%** — a
  **5.09% relative improvement**.
- Improved constraint-extraction F1 from **0.788 to 0.844** — a **7.07%
  relative improvement** (primary control value; a secondary, less
  favorable comparison against an alternate control value of 0.818 yields
  **3.15%** — cite both, never only the larger one).
- Improved entity-normalization accuracy from **85.5% to 100%** — a **16.95%
  relative improvement**.
- Improved structured-output schema-parse success from **91.1% to 100%** —
  a **9.77% relative improvement**.
- Maintained **0 fabricated canonical identifiers** across both the prior
  and new configuration (not a percentage claim — always state as "zero,
  maintained," never "improved by X%").
- Achieved **0 provider errors and 0 schema failures** across all 54 real
  inference calls made during the winning-candidate evaluation round.
- Measured a real per-call cost of **$0.002446** on the winning
  configuration, from a 45-call measured dev run (not an estimate).

## Framing note for future summaries

This work changed the active Phase-2 NLU model from NVIDIA's
`nemotron-3-super-120b-a12b` to Cerebras' `qwen-3.8-27b`, using the
identical, unmodified production prompt — the quality improvements above are
therefore attributable to the model swap alone, not to any prompt
engineering done specifically for the new model. That is itself worth
stating plainly in any external summary: it strengthens the claim, since
nothing was tuned in Qwen's favor.

## Known unresolved caveat to carry forward into any external-facing claim

The active runtime depends on a Cerebras **Free Trial** balance ($5.00,
expiring **2026-10-25 UTC**, auto-recharge OFF). This is a real engineering
result for Phase 2's evaluation purposes, but it is **not yet a resolved
permanent production/deployment decision** — that question is out of Phase
2's scope and should be revisited (Phase 9 or a dedicated deployment
decision) before this dependency is treated as permanent.

## Phase 3 — Tool Orchestration (legacy dispatch vs. Cerebras native tool calling)

Both the before (Candidate A) and after (Candidate B) numbers below were
measured on the identical basis — raw query text through each system's own
real, end-to-end tool-selection mechanism (n=59, `phase3_benchmark_manifest.json`
development+validation splits) — making this a directly comparable
before/after pair, unlike some of the other Phase-3 candidate data (see
"Not resume-safe" below).

- Replaced a legacy free-text LLM dispatch pipeline with zero schema
  validation and zero call-level traceability with a typed, registry-
  validated, provider-native tool-calling architecture (Cerebras
  `qwen-3.8-27b`) — closing 2 of 7 predeclared hard safety gates that the
  prior system failed **by construction** (schema-invalid calls could reach
  the real executor; no tool call carried a traceable ID).
- Improved source-routing F1 from **0.759 to 0.9322** — a **22.82%
  relative improvement** (n=59).
- Improved exact source-set match rate from **57.6% to 93.2%** — a
  **61.81% relative improvement**.
- Improved the parameter schema-valid rate (of calls reaching execution)
  from **73.8% to 100%** — a **35.50% relative improvement**; the after
  value is structural (0 schema-invalid calls can reach execution by
  construction of the typed registry boundary), not merely an observed
  rate.
- Reduced orchestration-stage model calls per query from **2.81 to 1.0
  exactly** — a **64.41% relative reduction**.
- Added abstention capability where none existed: the legacy system never
  abstained on any of 6 known-ambiguous benchmark cases (0/6, structurally
  incapable of it); the new system correctly abstained on 3/6.
- Found and fixed one genuine parameter-mapping defect during final
  held-out acceptance testing (a ClinicalTrials trial-phase value the model
  guessed non-canonically because the JSON schema didn't constrain it to an
  enum) — root-caused, fixed, and reconfirmed via a fresh 12-case
  held-out supplement (never reused from the original held-out split):
  **0/12 misses, 100% schema-valid** after the fix.
- Measured total Cerebras spend across all Phase-3 candidate evaluation,
  defect-fix regression, and held-out acceptance work: **$0.229** (a
  separate, independently-capped budget from Phase 2's own ~$0.166
  cumulative Cerebras spend — do not sum the two).

## Not resume-safe (do not state these without the qualifier, or at all)

- A constraint-F1 improvement percentage with no stated control-value basis
  (0.788 vs. 0.818 — the two documented Nemotron measurements disagree).
- Any latency number without "throttle-corrected" attached — the raw
  wall-clock figure (~12.07s at P50) is roughly 25x larger and would
  misrepresent true model latency if quoted instead.
- Any $/call-at-scale figure presented as measured rather than projected.
- Any claim that GPT-OSS-120B was usable — it was rejected permanently
  across 3 separate rounds for a systemic generic-intent-collapse defect.
- Any claim that this project's current inference cost or provider
  arrangement is finalized for production.
- Any Phase-3 "source-routing F1 of 1.0" or "100% exact source-set match"
  claim attributed to the hybrid/deterministic candidate (Candidate C) —
  that number was measured against a hand-authored input field written
  consistent with its own gold label, not a real Phase-2 NLU extraction,
  and does not constitute valid evidence of equivalent real-world routing
  quality. It was explicitly not selected as the Phase-3 winner partly for
  this reason.
- Any single relative-latency-reduction percentage for Phase 3's
  orchestration stage — the before and after latency figures were recorded
  in different aggregation shapes and were not re-derived onto an identical
  basis before this ledger was written.

## Phase 4 — Heterogeneous Retrieval (PubMed RAG validated; ClinicalTrials and ChEMBL fixed/extended)

- Fixed a real, pre-existing production defect: `tools/clinical_trials_tool.py`
  sent an invalid `filter.phase` API parameter, causing every phase-filtered
  ClinicalTrials.gov query to fail with a live HTTP 400. Improved required-
  trial recall from **0.737 to 0.895 (14/19 → 17/19)** — a **21.44% relative
  improvement** (n=19).
- Added drug-name-to-ChEMBL-ID resolution (`resolve_compound_name`), a
  capability that didn't exist before — improved ChEMBL Recall@10 from
  **0.381 to 1.000** (a **162.47% relative improvement**) and MRR from
  **0.279 to 0.898** (a **221.86% relative improvement**), n=21. Live-
  verified against 7 real drug names.
- Improved multi-source (2+ source) retrieval coverage from **0.0 to 0.571
  (4/7)**, n=7 — direct result of the ChEMBL fix, since every multi-source
  benchmark case had a ChEMBL leg.
- Found a second real defect during final held-out testing — the new
  `resolve_compound_name`'s fuzzy-match tier had no confidence threshold and
  could return a real-but-wrong ChEMBL ID for a completely fabricated drug
  name. Fixed with a similarity gate; confirmed on a fresh, never-reused
  10-case held-out supplement: **0/4 fabricated names produced a misleading
  match**, while genuine near-miss typos and synonym lookups were
  unaffected (5/5 still correct).
- Evaluated the existing local RAG PubMed pipeline against a live-API
  alternative (with a date-range-defect fix and a new deterministic query
  compiler) and **kept RAG as the production PubMed architecture** — RAG's
  Recall@10 (0.773) beats the best live-API candidate (0.136) by 5.7x, and
  fusion was tested and found to add zero unique recall.
- All 7 Phase-4 hard safety gates (fabricated/corrupted source IDs, cross-
  source ID collisions, dropped required filters, mislabeled sources,
  secrets in trace) pass, verified empirically on held-out data — not
  assumed.

## Not resume-safe (Phase 4)

- **The PubMed date-range fix, cited alone, as a retrieval-quality
  improvement.** Measured in causal isolation, it contributed exactly
  0.000 Recall@10 improvement. It is a real, regression-tested defect fix,
  but the credit for the 0.045→0.136 combined live-API improvement belongs
  to the query compiler, not the date fix.
- **Any claim that Phase 4 replaced or upgraded PubMed retrieval.** The
  existing RAG pipeline was validated, not changed — it was already the
  production architecture before Phase 4 began.
- **The multi-source coverage figure (0.571) as a final number** — 2 of
  the 3 remaining misses were scored against the non-selected PubMed
  live-API path and are expected to improve once re-scored against the
  frozen RAG architecture (not yet re-measured, so not claimed here).
- Any claim that ChEMBL's `search_by_target` wrong-entity behavior (3/21
  dev+validation cases) or PubMed RAG's lack of a relevance floor has been
  fixed — both are explicitly named, accepted limitations, not addressed
  in Phase 4.

## Resume-safe claims (Phase 5)

- Normalized heterogeneous PubMed (local RAG + live API), ClinicalTrials.gov,
  and ChEMBL outputs into a single canonical, typed `Evidence` object
  (`evidence/models.py`), replacing an ad hoc per-source citation shape with
  one deterministic, model-free transformation layer.
- **100% provenance completeness** on the frozen Phase-5 evaluation
  population — 152/152 dev+validation Evidence records, 45/45 held-out
  Evidence records (72 real source records total, never synthetic-only).
- **100% source-ID integrity** — 0 fabricated source IDs, 0 corrupted
  source IDs, across all 197 real Evidence records produced (dev+
  validation + held-out).
- **Complete trace linkage** from Evidence back to its retrieval/source
  lineage — 100% Evidence→RetrievalCandidate and Evidence→source-record
  link success; PubMed RAG's `call_id=None` is a correct, N/A-by-design
  value (no Phase-3 tool call produced it), not a missing-data gap.
- **Zero fabricated IDs inside Evidence**, verified empirically on
  genuinely held-out data (14 cases, one-shot, never reused).
- Source-faithful Evidence normalization across all three heterogeneous
  sources, with all 10 predeclared hard safety gates (fabricated/corrupted
  IDs, source mislabeling, secret leaks, cross-source ID collisions, etc.)
  passing at 0 on both dev+validation and held-out.
- 4/4 fresh, bounded live integration checks passed in this session
  (`artifacts/v2/phase5_live_integration_results.json`), confirming the
  frozen adapter/registry code path against real source data (network
  access constraints in this cloud session required using
  previously-captured real records for 3 of the 4 checks — documented
  transparently, not fabricated).
- Sub-millisecond normalization overhead (P50 0.0155ms, P95 0.125ms across
  1160 real-record adapter calls), measured separately from and never
  conflated with retrieval/API/LLM latency.

## Not resume-safe (Phase 5)

- **Any claim that Phase 5 fixed the citation/reference detachment.** The
  audit found `state["citations"]` and the LLM-written `## References`
  section have zero structural connection — Phase 5 makes that
  detachment fixable (via the typed `Evidence[]` collection) but does
  NOT fix it. That closure is explicitly deferred to Phase 6/7.
- **Any citation faithfulness, citation correctness, or claim-grounding
  claim.** No claim-to-evidence verification system exists yet.
- **Any grounded-answer accuracy, hallucination-reduction, or final
  answer-reliability claim.** Phase 5 produces typed Evidence only; no
  answer generation exists in this phase.
- **Any end-to-end task-completion claim.** Phase 5's scope stops at
  `Evidence[]` in `AgentState`; report generation and final citations are
  explicitly unmodified (verified: `state["citations"]`/
  `state["final_report"]` are set only by the pre-existing
  `report_generation_node`, never by `evidence_normalization_node`).
- **Any claim that Phase 5 improved retrieval quality or reduced
  network/Cerebras latency.** It is a pure downstream, model-free
  normalization layer; measured normalization latency is separate from
  and additive to (not a replacement for) retrieval/LLM latency.
- **Any claim that the original 14-case `phase5_heldout` split was rerun
  as blind evidence in this session.** It was not — only current *code*
  was inspected for the documented ChEMBL adapter consistency item; no
  code change was needed since the fix was already present.

## Resume-safe claims (Phase 6)

- Built a structured, grounded natural-language generation layer over
  heterogeneous Phase-5 Evidence, replacing free-form LLM prose with a
  typed `GroundedClaim`/`GroundedAnswer` model whose citations are
  deterministically compiled, never model-numbered.
- **Zero invalid/unknown Evidence-ID citations** across all 16 real
  benchmark cases (dev + validation + held-out).
- **100% deterministic citation-compilation success** and **100% answer
  serialization success**, measured on real Cerebras-generated output.
- **Zero reference entries without real Evidence**, **zero fabricated
  source IDs/URLs** - Evidence data flows through unmodified from Phase 5.
- **Zero-Evidence abstention correctness**: 0 factual claims ever produced
  when Evidence[] is empty, verified both in isolated tests and in a real
  graph run.
- Found and fixed one real generation defect (evidence prompt silently
  dropping `source_metadata`) via genuine development-split iteration -
  dev pass rate 7/10 → 10/10 after the fix, validation 3/3.
- Measured a real, reproducible qualitative advantage of the selected
  structured architecture (Candidate B) over a simpler free-form
  baseline (Candidate A): Candidate A leaked an internal evidence-ID
  string into user-facing prose on real data; Candidate B did not.

## Not resume-safe (Phase 6)

- **Any citation-faithfulness, claim-to-evidence entailment, unsupported-
  claim-rate, or hallucination-reduction claim.** Phase 6 measures
  structural grounding only (does a citation resolve to a real Evidence
  object) - not whether the claim's content is semantically true of that
  Evidence. That is Phase 7's job entirely.
- **Any claim that the legacy citation/reference detachment is fixed.**
  `report_generation_node` is unmodified and remains structurally
  disconnected from Evidence - Phase 6 built a new, separate,
  Evidence-authoritative path alongside it, not a replacement.
- **Any generation-latency number without noting it is dominated by the
  Cerebras Free Trial 5RPM rate limit**, not true model inference time.
- **Any claim of a nonzero-Evidence, real, end-to-end Phase-2→6 pipeline
  run in this cloud session.** Only a zero-Evidence real-graph run (safe,
  correct abstention) and a mocked-Evidence unit-level pipeline test were
  achieved - see CTL-009 in `docs/v2/CLOUD_TO_LOCAL_GAP_CLOSURE.md`.
- **The 2/3 held-out gold-match rate as a quality regression.** The one
  miss is a benchmark gold-authoring error (asked about a ChEMBL field -
  `alogp` - the frozen Phase-5 Evidence schema doesn't capture), not a
  generation defect; the underlying safety behavior (correct abstention,
  zero fabrication) was exactly contract-compliant on that case. A fresh,
  independent, pre-frozen blind supplement (`P6-SUPP-01`, on a genuinely
  unused real ClinicalTrials.gov record) subsequently passed 1/1 with all
  10 hard gates intact and zero code changes - confirming the generation
  system itself, not the invalid gold, was the issue.
- **"100% held-out required-fact coverage" as a blended claim across the
  original held-out and the supplement.** Never state this. The correct,
  resume-safe phrasing is: original held-out 2/3 (one invalid-gold miss,
  zero fabrication), fresh independent supplement 1/1 - reported
  separately, never combined into a single ratio.
