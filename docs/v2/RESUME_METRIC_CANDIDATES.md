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

## Resume-safe claims (Phase 7)

- Built a separate, independently-validated grounding/citation evaluation
  harness (`grounding_eval/`) that measures SEMANTIC support of claim text
  against cited Evidence content - not merely whether a citation resolves
  to a real Evidence ID (that was Phase 6's, purely structural, scope).
- The selected evaluator (Candidate B, semantic judge) was validated
  against independently-authored gold labels **before** being used to
  measure the frozen Phase-6 generator: 27/27 (100%) on development +
  validation, 9/9 (100%) on a held-out split run exactly once after the
  evaluator was frozen. Macro-F1 = 1.0 on both.
- Unsupported/contradicted-claim detection recall = 1.0 and citation-
  relation macro-F1 = 1.0 on both splits, both exceeding the predeclared
  thresholds (>=0.95 and >=0.90 respectively).
- Found and fixed one real evaluator defect (the judge could infer
  CONTRADICTED from outside domain knowledge instead of the Evidence's own
  stated content) via genuine development-split iteration - dev pass rate
  20/22 -> 22/22 after the fix, validation 5/5 (fresh cases, untouched
  during the fix).
- Using the validated evaluator, measured the frozen Phase-6 generator on
  a real, separate system-evaluation set (8 answers / 16 factual claims,
  explicitly excluding Phase-6's own held-out): 100% claim support rate,
  0% unsupported, 0% contradicted, citation precision 1.0, claim-citation
  coverage 1.0, 8/8 (100%) answer-level fully-grounded. No Phase-6
  production defect was found.
- Kept evaluator-quality metrics (System A) and generator-grounding
  metrics (System B) strictly separate in code, artifacts, and docs at
  every step - never blended into a single number.
- Zero hard-gate violations across all 10 predeclared hard safety gates
  (unknown/fabricated Evidence or source IDs, secret leaks, unserializable
  evaluations, uncaught schema failures, gold leakage into evaluator
  input, held-out reuse during tuning, silent failures treated as pass) -
  verified across dev+validation, held-out, and the system evaluation run.
- Verified by an explicit test (`test_evaluator_not_in_production_graph`)
  that `grounding_eval` is never imported by the production LangGraph
  (`agent/graph.py`) - the evaluator remains an offline measurement tool,
  never a production dependency.

## Not resume-safe (Phase 7)

- **Any claim that the evaluator is a cross-model or cross-provider
  independent judge.** Candidate B and the Phase-6 generator both call
  the same model (Cerebras `qwen-3.8-27b`). Evaluator accuracy is real
  and validated against gold the model never saw during generation, but
  this is same-model-family validation, not independent/adversarial
  validation - see CTL-011 in `docs/v2/CLOUD_TO_LOCAL_GAP_CLOSURE.md`.
- **Any claim of citation RECALL.** Only citation precision and claim-
  citation coverage are reported, per the Phase-7 evaluation contract;
  citation recall is explicitly never computed or reported.
- **Any claim that the 100% System-B grounding result generalizes beyond
  the 8-answer/16-claim system evaluation sample.** It is a real, honest,
  positive result on that sample - not a statistical guarantee at scale,
  and explicitly not force-inflated to a larger benchmark.
- **Any evaluator token/cost figure.** `grounding_eval/judge.py`'s
  `_invoke_judge` does not currently parse the Cerebras `usage` block -
  not measured this session, see CTL-012.
- **Any claim that Phase 7 reopened, modified, or re-froze Phase 6.** No
  Phase-6 defect was discovered; Phase 6's frozen checkpoint
  (`a4b3ae332d6bab41d99b1041015fb662b35c8025`) remains completely
  untouched.
- **Any evaluator-quality number (accuracy, macro-F1, recall) presented
  as if it were a generator-grounding number, or vice versa.** The two
  are measured on different case sets, for different purposes, and must
  always be reported under their own System A / System B label.
- **Any claim that Candidate C (hybrid) or Candidate D (independent
  model) is production-ready or was fully debugged.** Candidate C's
  residual numeric-regex defect (evidence-side digits glued to letters,
  e.g. "PHASE2") was left unfixed since Candidate C was not selected;
  Candidate D was never built at all (CTL-011).

## Resume-safe claims (Phase 7 hardening pass addendum)

- Expanded the Phase-7 claim-level benchmark from 36 to 68 real cases (32
  new, from 9 previously-unused real Phase-5 records), improving label
  balance (all 4 support labels now have double-digit representation,
  11-26 cases each) and source balance (pubmed/clinical_trials/chembl each
  now >=16 evidence references) without manufacturing low-quality cases.
- Candidate B (the selected, unchanged evaluator) scored 47/47 (100%) on
  combined development+validation (27 original + 20 new cases, including
  one case whose gold label was itself found defective and corrected
  before use).
- Hardened Candidate A into a genuine v2 baseline (entity attribution +
  structured categorical-field exact match + fixed numeric/phase
  comparison), measurably improving 46.9% -> 56.2% on the new, harder
  cases, while preserving v1's original historical measurement unmodified.
- Fixed Candidate C's residual numeric-regex defect (evidence-side
  letter-glued values like "PHASE2" were previously invisible to the
  numeric check) via identifier-masking + field-name-aware phase-token
  normalization, with 11 new regression tests.
- Expanded the frozen Phase-6 system-semantic-grounding evaluation from 8
  to 16 real answers (16 to 40 real factual claims), all still 100%
  supported, 0% unsupported/contradicted - no Phase-6 defect found at the
  larger scale either.
- Closed CTL-012: evaluator token/cost are now genuinely measured (real
  Cerebras `usage` data), and latency is now decomposed into rate-limit
  wait vs. real provider-call time vs. parsing time, rather than reported
  as one rate-limit-dominated figure.
- Ran a fresh, previously-unseen 12-case held-out supplement (not strictly
  required since the evaluator itself did not change, but run anyway):
  10/12 raw, with both misses root-caused via manual audit to gold-
  authoring defects in the newly-authored material (not evaluator
  defects) - reported as-run, per the frozen-held-out-gold rule, exactly
  like Phase 6's precedent.
- Found and transparently documented three real defects this pass: two
  gold-authoring mistakes in newly-authored cases (one fixed pre-freeze,
  two left in the frozen fresh-held-out record and reported honestly) and
  one evaluation-harness bug (a scratch-script evidence-dictionary
  collision, unrelated to any frozen Phase-6 or Phase-7 code) - found and
  fixed before being used in any reported system-eval number.

## Not resume-safe (Phase 7 hardening pass addendum)

- **Any claim that CTL-011 (a genuinely independent, distinct-provider
  evaluator) was resolved.** It was actively re-tested this session (not
  re-asserted from memory) and confirmed still blocked: no second LLM
  provider credential exists, and `huggingface.co` is explicitly denied by
  this environment's egress policy. Candidate D was NOT built. CTL-011
  remains OPEN.
- **Any claim that Phase 7 is now closed.** Per the hardening directive's
  own rule, Phase 7 remains open specifically on the independent-evaluator
  requirement - every other resolvable caveat was resolved, but this one
  requirement cannot be satisfied inside this cloud environment.
- **Any claim that the multi-source claim count (5), unsupported-label
  count (11), or system-eval answer count (16) met their respective
  aspirational targets (>=6, >=12, >=20).** All three are honest, reasoned
  shortfalls, disclosed in `docs/v2/PHASE7_HARDENING_AUDIT.md`, not force-
  padded to hit a number.
- **Any claim that the fresh 12-case held-out supplement scored a clean
  100%.** It scored 10/12 as-run; the 2 misses were root-caused to gold
  defects, not silently corrected into a "12/12" figure anywhere.

## Resume-safe claims (Phase 7 zero-caveat pass addendum)

- Resolved both remaining benchmark-balance shortfalls from the hardening
  pass: multi-source claim-level cases 5 -> 6, unsupported-label cases 11
  -> 12 (combined benchmark now 72 real cases, all 4 labels and all 3
  source types + multi-source at or above their target floors).
- Expanded the frozen Phase-6 system evaluation to the full 20-answer
  target (8+8+4, real generation, real evaluation): 66 total factual
  claims, 100% supported, 19/19 fully-grounded answers (1 correct
  abstention) - no Phase-6 defect found at this larger scale either.
- Found and fixed a second real Candidate-B evaluator defect (F4: a
  temporal/status-inference false contradiction), then re-verified the fix
  against the ENTIRE unchanged frozen gold (original 36-case benchmark:
  22/22 dev + 5/5 validation + 9/9 held-out; hardening-pass 20-case
  dev+validation) with zero regressions - not just the one case that
  exposed the defect.
- Ran a genuinely fresh, previously-unused, 2-case blind held-out
  replacement supplement (not a rerun of the spent 12-case supplement):
  2/2, replacing the statistical evidence lost to that supplement's 2
  gold-authoring misses.
- Actively re-audited the independent-evaluator requirement (CTL-011) this
  session rather than re-asserting an earlier conclusion: confirmed no
  second LLM provider credential, confirmed `huggingface.co` is still
  denied by egress policy, and explicitly considered and rejected using
  this agent itself as a "different model family" judge (it authored the
  gold labels, so it would not be blind/independent). Exact remedy (env
  var name, host to allowlist, credential type) recorded in
  `docs/v2/PHASE7_INDEPENDENT_EVALUATOR_SETUP.md`.
- Created an interim durability checkpoint commit
  (`MedAgent V2 Phase 7 hardening checkpoint - phase still open`) and
  pushed it to `origin/medagent-v2-phase7-grounding-eval` - explicitly NOT
  a freeze/closure commit, and Phase 7 was NOT reported as closed at that
  point either.

## Not resume-safe (Phase 7 zero-caveat pass addendum)

- **Any claim that CTL-011 is closed, or that a genuinely independent
  evaluator exists.** It does not. This was re-verified, not assumed, in
  this pass, and the reasons plus exact remedy are documented, not hidden.
- **Any claim that Phase 7 is closed, frozen, or ready for Phase 8.** Per
  the zero-caveat directive's own closure rule, Phase 7 cannot be called
  closed while the independence requirement is unmet - it remains
  ENGINEERING COMPLETE EXCEPT FOR CTL-011.
- **Any claim that the original 12-case fresh_heldout_supplement scored
  12/12.** It remains 10/12, preserved exactly as-run; the 2/2 replacement
  supplement is a separate, additional artifact, never blended into the
  original's number.
- **Any claim that this session created a final Phase-7 freeze commit or
  pushed unreviewed closure work.** Only the interim durability checkpoint
  was committed and pushed, per explicit authorization for that step
  alone; no further commit/push has been made since.

## Resume-safe claims (Phase 7 zero-remaining-caveat pass, final)

- Every avoidable Phase-7 engineering/evaluation caveat has been resolved:
  benchmark balance (multi-source 6, unsupported-label 12, both targets
  met), system evaluation at the full 20-answer/66-claim target (100%
  supported), a clean fresh blind held-out replacement (2/2), and a
  second real evaluator defect (F4) found, fixed, and fully regression-
  verified against all prior frozen gold with zero collateral damage.
- Performed a precise, host-by-host network re-audit of the independent-
  evaluator blocker rather than repeating a vague "environment-limited"
  conclusion: confirmed most candidate provider hosts are explicitly
  policy-blocked, but identified that Google Gemini's API host is already
  reachable from this session - the blocker there is a missing credential
  only, not network policy - and documented the exact remedy (model, env
  var, auth scheme, expected cost).
- Explicitly considered and rejected two invalid shortcuts to "close"
  CTL-011: repurposing this session's own AWS/Anthropic-platform
  infrastructure credentials for an unauthorized new purpose, and using
  this agent's own reasoning as a "different model family" judge (which
  would be contaminated by having authored the gold labels itself).

## Not resume-safe (Phase 7 zero-remaining-caveat pass, final)

- **Any claim that a Candidate D independent evaluator was built,
  validated, or compared against Candidate B.** None of this happened -
  no credential was available. Every metric that would require Candidate
  D (its own accuracy/F1, B-vs-D agreement/kappa, disagreement
  adjudication, independent system cross-check) is explicitly N/A this
  session, not omitted-but-implied.
- **Any claim that CTL-011 is closed or that Phase 7 is closed/frozen.**
  Both remain false. Phase 7 is ENGINEERING COMPLETE EXCEPT FOR CTL-011.
- **Any claim that the Gemini network-reachability finding means Gemini
  access is already usable.** It means only that no egress-policy change
  is needed IF a credential is later provided - the credential itself is
  still entirely absent this session.

## Resume-safe claims (Phase 7 Candidate D attempt, this session)

- `GEMINI_API_KEY` was provisioned and a genuinely independent Candidate D
  evaluator (Google Gemini `gemini-3.8-flash`) was built, offline-tested
  (17 tests), and its live connectivity/authentication/structured-output
  path was verified working (2 successful live batches, 21/21 = 100%
  correct on the portion judged).
- Correctly discovered the live model name via the API itself
  (`models.list` + the error message from the originally-named model)
  rather than assuming a name from training data.
- Confirmed, via progressively smaller diagnostic batches and repeated
  backoff, that a subsequent run of failures was a genuine Gemini-side
  capacity outage - not a code, schema, or content defect in Candidate D.
- Respected the free-tier quota discipline throughout: 8 of 20 daily
  requests used, all planned in advance, batches token-aware, no
  single-judgment-per-request waste.

## Not resume-safe (Phase 7 Candidate D attempt, this session)

- **Any claim that Candidate D is validated, frozen, or has passed
  held-out.** None of this happened - development is only 21/41 complete.
- **Any claim that CTL-011 is closed.** It is not. The credential blocker
  is resolved, but the evaluator is not yet validated.
- **Any claim of B-vs-D agreement, Cohen's kappa, or an independent
  Phase-6 system cross-check.** None of these were measured this session.
- **Any claim that the 21/21 = 100% partial result predicts final
  Candidate D performance.** It is real, genuine signal on a small,
  non-random subset (whatever batches happened to succeed before the
  outage) - not a completed validation.

## Resume-safe claims (Phase 7 Candidate E / CTL-011 closure)

- Built and fully validated a genuinely independent second grounding
  evaluator, Candidate E (NVIDIA NIM, Nemotron 3 Super 120B A12B) -
  distinct provider and model family from both Cerebras qwen-3.8-27b
  (Candidate B / generator) and Google Gemini (Candidate D).
- Candidate E development: 39/41 = 95.1% (macro-F1 0.945), after finding
  and fixing one real defect analogous to Candidate B's own original F1
  finding - independently discovered, independently fixed.
- Candidate E validation: 8/8 = 100%. Frozen before held-out.
- Candidate E held-out (23 cases, run exactly once): 22/23 = 95.7%
  (macro-F1 0.914), meeting every predeclared threshold.
- **Candidate B vs Candidate E agreement across the full 72-case
  benchmark: 93.1% raw, Cohen's kappa 0.904 ("almost perfect")** - real,
  measured, independent cross-model corroboration of Phase-7's grounding
  evaluator quality.
- Every one of the 5 disagreements was manually adjudicated against the
  real cited Evidence, not resolved by majority vote or by treating
  either evaluator's output as automatically correct.
- Candidate E independently cross-checked 26 real Phase-6 system-eval
  claims: 26/26 = 100% supported, exactly matching Candidate B, 0
  disagreements - real, if scope-limited, independent corroboration.
- **CTL-011 REOPENED (self-audit correction)** - see below. The
  benchmark-level Candidate E validation and B-vs-E agreement claims
  above remain safe; the system-cross-check claim does not.
- Preserved Candidate D (Gemini) exactly as a separate, unmodified,
  partial historical experiment - never merged with or overwritten by
  Candidate E's results.

## Not resume-safe (Phase 7 Candidate E / CTL-011 closure)

- **Any claim that the independent Phase-6 system cross-check covered
  all 66 original claims.** It covered only 26 (the v3 subset) - the
  other 40 (v1's 16 + v2's 24) are excluded, the latter due to a
  disclosed accidental-regeneration incident this session, the former
  for a pre-existing claim-text-not-persisted reason.
- **Any claim that the accidental Phase-6 regeneration incident didn't
  happen, or that its output was quietly used.** It happened; the
  regenerated data was identified and explicitly excluded, not used.
- **Any claim that Candidate E is flawless.** It has one disclosed,
  real, residual weakness: on compound/multi-fact claims, it sometimes
  treats one sub-fact as "the whole claim" and downgrades the verdict
  when only that sub-fact is unaddressed, rather than crediting other
  correctly-supported facts as partially_supported. Candidate B was
  correct in all 5 real disagreements found.
- **Any claim that Candidate D (Gemini) was completed, merged with
  Candidate E, or used as a tie-breaker.** None of this happened;
  Gemini's 21/41 partial dev result remains a separate, preserved,
  unfinished historical experiment.

## Self-audit correction: CTL-011 REOPENED (before freeze authorization)

- **Retracted:** "CTL-011 is closed" and "18/18 caveat rows closed."
  A dedicated audit found the Candidate E system-cross-check subset (26
  claims) has zero ChEMBL representation - a coverage gap, not a smaller
  sample of the same population. Declaring the system cross-check
  satisfied on that basis overclaimed what was verified.
- **Still resume-safe, unaffected by this correction:** Candidate E's own
  development (39/41), validation (8/8), held-out (22/23), and the
  Candidate B vs Candidate E benchmark-level agreement (n=72, kappa
  0.904, 5/5 disagreements adjudicated) - none of this required
  system-eval data.
- **Not resume-safe:** any claim that Phase 6 was independently
  cross-checked in a way representative of the original 66-claim
  population, or that CTL-011 or the full 18-row caveat matrix are
  closed. Corrected status: CTL-011 REOPENED; 17/18 closed, 1/18
  reopened.

## Fresh supplement executed: CTL-011 genuinely CLOSED (this session, latest)

- **Now resume-safe:** "CTL-011 is closed" and "18/18 caveat rows
  closed," on a genuinely complete and disclosed evidentiary basis - the
  fresh 8-answer/32-claim supplement (clinical_trials 15, pubmed 6,
  chembl 3, multi_source 8) combined with the surviving 26-claim v3
  subset gives 58 claims across all four source categories. Frozen
  Candidate B: 32/32 supported on the supplement. Frozen, unmodified
  Candidate E: 31/32 supported, 1 partially_supported. Combined raw
  B-vs-E agreement: 57/58 (~98.3%); ChEMBL-specific agreement 3/3
  (100%). The single disagreement was manually adjudicated: E_CORRECT
  (Candidate B overclaimed support for a claim with an unaddressed
  sub-fact and a source-truncated sub-fact).
- **Resume-safe caveat:** the combined 58-claim set is explicitly NOT
  the original 66-claim Phase-6 system population - do not resume by
  claiming "the original system-eval set was cross-checked." 40 of the
  original 66 claims remain permanently unrecoverable
  (`artifacts/v2/phase7_system_crosscheck_recovery_audit.json`). Always
  cite the combined set's disclosed composition
  (`artifacts/v2/phase7_system_crosscheck_combined_summary.json`) rather
  than describing it as "the 66-claim cross-check."
- **Not resume-safe:** describing Cohen's kappa on the supplement (0.0)
  as evidence of poor B-vs-E agreement - it is a degenerate artifact of
  Candidate B's zero label variance on that subset; raw agreement
  (~96.9% supplement-only, ~98.3% combined) is the informative figure.
- **Still not resume-safe (unchanged):** any claim that Candidate D
  (Gemini) was completed, merged with Candidate E, or used as a
  tie-breaker; any claim that the original 40 missing Phase-6 claims
  were recovered or reconstructed (they were not - see the recovery
  audit).

## Phase 8: Evidence-Driven Research Loop (this session)

- **Resume-safe:** the Phase-8 research loop is implemented, additive, and
  opt-in (`MedAgent(research_loop=True)`); the pre-Phase-8 graph/default
  behavior is unchanged and still passes its full original test suite
  (457 tests, all still passing after Phase 8's additions).
- **Resume-safe:** bounded-loop safety (4 independent hard limits, proven
  to terminate even for a persistently unresolved gap) - zero infinite
  loops possible via any tested path.
- **Resume-safe:** a real, measured, attributable quality delta exists
  (Completeness/source-coverage +0.5 on DEV-B, a genuine gap-driven
  recovery) - the exit gate's "measured quality improvement... not just
  the loop ran" requirement is met, not asserted from vibes.
- **Resume-safe, with the caveat stated:** Claim Support Precision showed
  no delta in this n=4 sample (ceiling in every case) - do not resume by
  claiming a CSP improvement; the honest result is "flat, exit gate met
  via Completeness instead."
- **Not resume-safe:** claiming the dev benchmark is statistically
  powered, or claiming the WEAKLY_SUPPORTED_FACT/CONFLICTING_EVIDENCE gap
  detectors were demonstrated live end-to-end (they were not, in this
  small sample - see `docs/v2/PHASE8_FAILURE_ANALYSIS.md`; they are
  verified via offline unit tests only).
- **Not resume-safe:** claiming a live, successful multi-source follow-up
  round against the real internet - live tool network is blocked in this
  session; DEV-B's follow-up evidence acquisition is disclosed as
  network-simulated (real adapters, real Phase-5 manifest records, real
  frozen generation/judge calls - only the live tool-execution network
  hop itself was substituted).

## Phase 8 Validation Pass (this session, frozen architecture, n=8)

- **Resume-safe:** the Phase-8 architecture was frozen
  (`artifacts/v2/phase8_frozen_config.json`) before an independent, fresh
  8-case validation set was built and run; zero validation-driven tuning
  occurred.
- **Resume-safe:** Completeness/source-coverage improved on a fresh
  validation set too (3/8 cases, mean +0.1875), independently confirming
  the DEV-pass finding rather than resting on it alone.
- **Resume-safe, with the caveat stated:** Claim Support Precision showed
  a genuine regression on 1/8 validation cases (VAL-C) - do not resume by
  claiming Phase 8 only improves grounding; the honest result is "usually
  flat/neutral on CSP, occasionally a real trade-off, always disclosed by
  the loop's own state rather than hidden."
- **Resume-safe:** zero fabricated/invalid Evidence IDs and zero infinite
  loops across all 8 validation cases (16 arm-runs, CONTROL+PHASE-8).
- **Not resume-safe:** claiming all 8 validation cases exercised their
  exact predicted stop reason - only 4/8 did; the other 4/8 still
  terminated safely, but for a different (still valid, still bounded)
  reason than predicted at design time. See
  `docs/v2/PHASE8_FAILURE_ANALYSIS.md`'s "Validation-pass findings."
- **Not resume-safe:** claiming the final rendered answer text is
  automatically caveated when the research loop ends with a residual,
  unresolved gap - it is not, as of this session; this is documented
  follow-up work, not yet implemented.

## Phase 8 Reopening + Fix + Validation Run 2 (this session)

- **Resume-safe:** PHASE8-DEFECT-001 (Validation Run 1's VAL-C CSP
  regression not propagated to the final answer) is root-caused, fixed
  generally (not VAL-C-specific), and regression-tested (11 new tests,
  including an exact defect-reproduction of VAL-C's recorded trace).
- **Resume-safe:** Validation Run 2 (6 fresh cases, post-fix) shows zero
  CSP regressions, zero fabricated/invalid Evidence, zero infinite loops.
- **Resume-safe, with the CTL-020 caveat stated:** do not claim
  Validation Run 2 independently demonstrated a completeness gain - it
  measured a flat 0.0 delta this run, honestly attributed to a genuine,
  disclosed ClinicalTrials.gov/ChEMBL record inventory exhaustion, not a
  regression. Validation Run 1's original +0.1875 mean completeness gain
  (3/8 cases, different records, still real and unmodified) remains the
  valid evidence for the exit gate's Completeness side.
- **Resume-safe:** 8 new CTL items (CTL-013–CTL-020) in
  `CLOUD_TO_LOCAL_GAP_CLOSURE.md` name exactly what live/local
  verification remains before Phase 13's final freeze - do not treat any
  Phase-8 metric as production-representative until those close.
- **Not resume-safe:** claiming Phase 8's numbers reflect live network
  acquisition - every DEV/Validation Run 1/Validation Run 2 follow-up used
  transport-simulated acquisition (real records, simulated network hop
  only), disclosed in every manifest and now tracked as CTL-016/CTL-019.
- **Not resume-safe:** claiming Validation Run 1 was ever a clean pass -
  it is permanently marked `VALIDATION RUN 1 — DEFECT DISCOVERED`
  (`artifacts/v2/phase8_validation_run1_status.json`), preserved
  unmodified as the historical record of the defect's discovery.

## Phase 8 Local-Closure Pass (later local session, `medagent-v2-phase8-local-verification`)

- **Resume-safe:** the research loop's PubMed, ClinicalTrials.gov, and
  ChEMBL follow-up acquisition genuinely works against real, live network
  APIs through the frozen Phase-3 dispatcher - not just against
  previously-captured records. 24+ real PMIDs, 13 distinct real NCT ids,
  and 5 distinct real CHEMBL ids acquired across 8 real end-to-end runs,
  zero fabricated/invalid Evidence IDs.
- **Resume-safe:** the ChEMBL adapter's expected-skip (`no_match`) path
  was exercised live against the real ChEMBL API (not just offline unit
  tests) and correctly produced zero fabricated/best-guess Evidence.
- **Resume-safe:** a real, live-acquired residual `weakly_supported_fact`
  gap was correctly caveated by PHASE8-DEFECT-001's fix
  (`finalize_research_answer_node`) under genuine live acquisition - the
  fix's mechanism is now verified at 3 independent levels (unit, mocked
  full-graph, live).
- **Resume-safe:** all 3 fault classes named by CTL-017 (timeout, 429,
  5xx - including all 3 biomedical source networks failing
  simultaneously) were safely reproduced and the research loop terminated
  safely in every case - zero fabrication, zero infinite loops, bounded
  retry.
- **Resume-safe:** 2 fresh, never-before-used real multi-source
  validation cases (avapritinib/GIST, repotrectinib/ROS1+NSCLC) ran
  cleanly, closing CTL-020's source-inventory-exhaustion gap and its
  associated Phase-10-validity concern.
- **Resume-safe:** PHASE8-DEFECT-002 (a real LangGraph state-threading
  defect causing `research_stop_reason` to be silently lost from every
  full-graph run's returned state) is root-caused, generally fixed, and
  regression-tested at the exact level (`build_research_loop_graph().invoke()`
  end-to-end) that let it ship undetected in the first place. Full
  regression after the fix: 507 passed, 0 failed, 7 skipped.
- **Not resume-safe:** citing this session's 8-case live metrics (mean
  loops/query=0.75, etc.) as production-representative - n is still small
  on both the cloud and local samples; CTL-019 remains a citation-time
  gate until a larger-n re-measurement exists (Phase 9/11).
- **Not resume-safe:** claiming a live 3-round multi-iteration case has
  been demonstrated - CTL-016's 2-round requirement is met live, but no
  case in this pass organically required a 3rd round; the iteration-bound
  code path itself remains covered only offline (unit tests + one new
  full-graph regression test) for that specific count.
- **Not resume-safe:** claiming whether the ORIGINAL cloud-session
  DEV/Validation Run 1/Run 2 `final_stop_reason` numbers were themselves
  affected by PHASE8-DEFECT-002 - the original (uncommitted) validation
  harness script is not present in this repository, so this cannot be
  confirmed either way and is disclosed as an open question, not asserted.

## Phase 9: Reliability/Concurrency/Performance (this session)

- **Resume-safe:** `GAP_ANALYSIS_BATCH_SIZE=2` is production-locked, backed
  by a contemporaneous, pre-registered, AC-powered live A/B benchmark (23
  live judge calls, exact planned-vs-actual match, 0 failures/retries) -
  SMALL/MEDIUM/LARGE fixtures each showed a genuine 34-50% wall-clock
  reduction with zero semantic/safety regression (0 missing/duplicate/
  wrong-association claims, 0 evidence contamination, 0 false support,
  identical support labels to the batch_size=1 control on every claim).
- **Resume-safe:** `GAP_ANALYSIS_MAX_CONCURRENCY=1` (unchanged default) is
  backed by an equally rigorous live experiment (45 live judge calls) that
  found NO meaningful benefit from concurrency=2/4 - a genuine negative
  result, not an untested assumption. Do not re-benchmark concurrency
  without new evidence the underlying Cerebras rate-limit configuration
  has changed.
- **Resume-safe:** `CLAIM_EVALUATION_BUDGET=32` and
  `MAX_TOOL_CALLS_PER_ROUND=12`/`MAX_TOOL_CALLS_PER_REQUEST=24` are
  intentional, documented, request-global application-level budgets
  (PHASE9-DEFECT-001/002 fixes), derived from real Phase-8/9 corpus
  distributions, extensively deterministically tested, and confirmed
  respected under real live traffic in the final validation pass (usage
  never approached the ceiling in any of 5 fresh live cases).
- **Resume-safe:** the pair-batching implementation's correctness (strict
  claim_id-tagged ID validation, whole-batch failure semantics via the new
  `CLAIM_EVALUATION_FAILED` gap type, per-claim not per-batch budget
  accounting, zero cross-claim contamination) is backed by 29 dedicated
  deterministic tests (`tests/test_phase9_pair_batching.py`) plus the live
  benchmark's own zero-contamination finding on real provider responses.
- **Resume-safe:** PHASE8-DEFECT-001's claim-caveat mechanism
  (`finalize_research_answer_node`) was reconfirmed firing correctly under
  live, real, end-to-end traffic with the NEW Phase-9 configuration
  (final validation case VAL9-4) - the fix remains robust across a
  configuration change, not just at the moment it was originally applied.
- **Resume-safe:** `grounded_generation`'s hard Evidence-ID gate (a
  pre-existing Phase-6/7 mechanism, not modified by Phase 9) was observed
  live, twice, correctly rejecting a malformed/fabricated Evidence-ID
  citation and triggering safe abstention rather than accepting it - fresh
  live confirmation the safety net holds, though the underlying generation
  behavior that occasionally produces such a mismatched ID is itself a
  Phase-6/7 concern, out of Phase-9's scope, and not something this phase
  fixed or was asked to fix.
- **Not resume-safe:** citing the live benchmark deltas (concurrency or
  pair-batching) as statistically robust percentile claims - both
  experiments used n=1 per (fixture, condition) cell, explicitly below the
  project's own n>=30 contract requirement for any P95/P99 claim. The raw,
  disclosed per-fixture values are the only defensible citation.
- **Not resume-safe:** claiming CTL-016 (a live 3-round multi-iteration
  case) or CTL-019 (a larger-n live re-measurement of Phase-8's own
  DEV/Validation metrics) were closed by this phase - both remain exactly
  as they stood after the Phase-8 local-closure pass; Phase 9's live
  traffic served different, narrower purposes (judge-call benchmarking,
  final configuration validation) that do not satisfy either item's
  specific criterion.
- **Not resume-safe:** claiming PHASE9-PROCESS-DEV-003 is a confirmed
  incident - it is explicitly SUSPECTED, not confirmed (no provider-side
  usage/billing confirmation was sought, and no new live call was made to
  verify it, per instruction). Treat it as a documented risk that was
  remediated (network guards added), not as proof traffic actually
  escaped.
- **Not resume-safe:** claiming the final validation run's two hard-gate
  rejections (VAL9-1, VAL9-3) indicate a Phase-9 defect - they demonstrate
  a pre-existing Phase-6/7 safety mechanism working correctly under live
  conditions, not a new failure Phase 9 introduced or is responsible for
  fixing.
