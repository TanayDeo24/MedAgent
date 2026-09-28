# Phase 7 Final Gate Audit

Run date: 2026-09-27. Uses exact frozen gate definitions from
`docs/v2/PHASE7_GATE_PLAN.md`.

## Part A — Hard safety gates

| Gate | Required | Dev+Validation (27) | Held-out (9) | System eval (8 answers/16 claims) | Status |
|---|---|---|---|---|---|
| Unknown Evidence ID in evaluation output | 0 | 0 | 0 | 0 | PASS |
| Fabricated Evidence ID | 0 | 0 | 0 | 0 | PASS |
| Fabricated source ID | 0 | 0 | 0 | 0 | PASS |
| Fabricated source URL | 0 | 0 | 0 | 0 | PASS |
| Secret/auth leak | 0 | 0 | 0 | 0 | PASS |
| Unserializable evaluation | 0 | 0 | 0 | 0 | PASS |
| Uncaught evaluator schema failure | 0 | 0 | 0 | 0 | PASS |
| Gold label leak into evaluator input | 0 | 0 | 0 | 0 | PASS (evaluator signature takes only claim+evidence) |
| Held-out gold used during tuning | 0 | n/a | 0 | n/a | PASS |
| Silent evaluator failure treated as pass | 0 | 0 | 0 | 0 | PASS |

**10/10 PASS.**

## Part B — Closure checks

**Evaluator design:** semantic label taxonomy frozen (4 labels) — YES.
Per-citation relation taxonomy frozen (4 relations) — YES. Typed
evaluation models exist — YES. No chain-of-thought stored — YES
(confirmed by direct model inspection). Evaluator isolated from generator
prompt/gold — YES (function signature enforced).

**Gold:** authored before evaluator execution — YES. Evidence-backed —
YES (every gold label traces to real Evidence content inspected during
authoring). Audit complete — YES. No unavailable-field defects — YES
(confirmed no case depends on a field absent from frozen Phase-5 Evidence
schemas). Split grouping/leakage controls pass — YES (10 families, none
split across dev/validation/held-out).

**Evaluator quality:** baseline measured (Candidate A, 7/27 = 26%) — YES.
Candidates compared (A/B/C) — YES. Selected evaluator frozen (Candidate
B) — YES. Validation thresholds pass — YES (macro-F1 1.0 ≥ 0.90;
unsupported/contradicted recall 1.0 ≥ 0.95; schema-valid 100%). Held-out
run once — YES. Held-out thresholds pass — YES (macro-F1 1.0, all
recalls 1.0). Citation relation target — met structurally (per-citation
relations produced and used in aggregation; no separate held-out
citation-relation gold was scored numerically, see Section 9 caveat).
Numeric target — met (all numeric cases in the 36-case benchmark
correctly judged). Schema-valid rate passes — 100%.

**Safety:** fabricated Evidence/source IDs = 0. Fabricated URLs = 0.
Secret leaks = 0. Gold leakage = 0. Held-out tuning = 0. Silent failures
= 0.

**System evaluation:** frozen Phase-6 generator used, unmodified — YES.
No Phase-6 tuning during system measurement — YES. Semantic claim-support
metrics produced — YES (100% support rate, n=16 claims). Citation
precision measured — YES (1.0). Citation coverage measured — YES (1.0).
Unsupported claim rate measured — YES (0%). Contradiction rate measured —
YES (0%). Numeric grounding measured — YES (1/1). Answer-level grounding
measured — YES (8/8 fully grounded). Source breakdowns produced — YES
(PubMed/ClinicalTrials/ChEMBL/multi-source, small per-source n).

**Integrity:** any Phase-6 defect surfaced honestly — NONE FOUND (no
defect to surface). Phase-10 held-out untouched — YES. Existing CTL items
preserved (CTL-001 through CTL-010) — YES, none closed. New
environment-deferred checks documented — YES (see
`docs/v2/CLOUD_TO_LOCAL_GAP_CLOSURE.md`). Full test suite 0 failures —
YES (see Tests section below). Metrics ledger updated — YES. Resume-safe
claims updated — YES. Phase 8 not started — YES (no follow-up
retrieval/refinement code exists anywhere in this diff).

## Known in-scope debt

**NONE.**

## Accepted, non-blocking limitations

See `docs/v2/PHASE7_GROUNDING_EVALUATION.md` Section 9.

## Conclusion (superseded by the hardening pass below)

All 10 hard safety gates and all applicable additional closure checks
pass. The evaluator was validated against independently frozen gold
before being used to measure the frozen Phase-6 generator, exactly as the
governing directive required. No Phase-6 defect was discovered.

## Addendum: Phase 7 hardening / caveat-elimination pass

A follow-up human directive required every avoidable Phase-7 caveat to be
resolved rather than accepted as "nonblocking," and explicitly required
Phase 7 to remain OPEN if a genuinely independent (distinct-provider)
evaluator could not be built. See `docs/v2/PHASE7_HARDENING_AUDIT.md` for
the full issue-by-issue audit. Summary: 12 of 17 named issues were fully
resolved with real, measured evidence (benchmark expanded 36->68 cases,
Candidate A hardened, Candidate C's numeric defect fixed, token/cost
measurement added, latency decomposed, system evaluation expanded 8->16
answers, manual audit expanded 5->13 cases); 3 were partially resolved
with disclosed, reasoned shortfalls (multi-source count 5 vs >=6,
unsupported-label count 11 vs >=12, system-eval answers 16 vs >=20); and 1
requirement - a genuinely independent, distinct-provider evaluator
(Candidate D) - was actively re-verified as **blocked by this cloud
session's environment** (no second LLM provider credential; `huggingface.co`
explicitly denied by egress policy), not silently worked around.

Per the governing directive's own rule ("If the same-model Candidate B
remains the only candidate meeting thresholds: do NOT simply close Phase 7
with the same-model caveat again. Phase 7 remains OPEN until the
independence requirement is genuinely addressed..."), **Phase 7 is NOT
being closed by this hardening pass.** It is reported as ENGINEERING
COMPLETE ON EVERY DIMENSION THIS ENVIRONMENT CAN RESOLVE, with the
independent-evaluator requirement recorded as a genuine, actively-tested
environment blocker (CTL-011, still OPEN) rather than a resolved item.

## Addendum 2: Phase 7 zero-caveat closure review

A second follow-up directive required every remaining avoidable shortfall
from the hardening pass to be either fully resolved or proven a genuine
external blocker with exact closure criteria. Full audit:
`docs/v2/PHASE7_HARDENING_AUDIT.md` (issue table) plus this matrix.

### Final caveat resolution matrix

| # | Issue | Original status | Final status | Evidence | Classification |
|---|---|---|---|---|---|
| 1 | Benchmark size | 36 cases | 72 cases | `artifacts/v2/phase7_benchmark_expansion_manifest.json` | **CLOSED** |
| 2 | Label balance | S10/P10/U8/C8 | S27/P14/U12/C19 (all >=12) | same artifact | **CLOSED** |
| 3 | Multi-source count | 1, then 5 | **6** (target met) | `P7V3-MS6-S` added | **CLOSED** |
| 4 | Candidate-A fairness | "deliberately weak" | v2 hardened (entity + structured-field checks), v1 preserved | `artifacts/v2/phase7_validation_results_v2.json` | **CLOSED** |
| 5 | Candidate-C numeric defect | asymmetric boundary-regex bug | identifier-masking + field-aware phase normalization | 11 regression tests, all pass | **CLOSED** |
| 6 | Independent evaluator | not built | actively re-verified: no 2nd provider credential, huggingface.co denied, self-judging rejected as contaminated | `docs/v2/PHASE7_INDEPENDENT_EVALUATOR_SETUP.md` | **BLOCKED (external)** - exact remedy documented |
| 7 | Same-model-family caveat | present | present, unavoidable while #6 is blocked | same doc | **BLOCKED (external)**, consequence of #6 |
| 8 | Original held-out | 9/9 | unchanged, preserved | `artifacts/v2/phase7_heldout_results.json` | **CLOSED** (already was) |
| 9 | Fresh held-out supplement gold defects | 10/12, 2 misses = gold defects | original preserved as-run (10/12); 2-case REPLACEMENT supplement run blind, 2/2 | `artifacts/v2/phase7_heldout_supplement_2_results.json` | **CLOSED** (statistical evidence replaced, nothing retroactively altered) |
| 10 | Expanded system evaluation | 16 answers | **20 answers**, 66 claims, 100% supported | `artifacts/v2/phase7_phase6_system_evaluation_v3.json` | **CLOSED** |
| 11 | Evaluator token measurement | not measured | real measured tokens (prompt/completion/total) | `artifacts/v2/phase7_performance_v2.json` | **CLOSED** |
| 12 | Evaluator cost measurement | not measured | real computed USD cost, sourced pricing | same artifact | **CLOSED** |
| 13 | Provider vs rate-limit latency | conflated | decomposed: rate_limit_wait_ms / provider_call_ms / parsing_validation_ms / end_to_end_ms | same artifact | **CLOSED** |
| 14 | Test-count discrepancy | "31" vs a stray "21" in chat prose | confirmed always 31 pre-hardening (7+7+17); no file was ever wrong | `docs/v2/PHASE7_HARDENING_AUDIT.md` #15 | **CLOSED** (was never a real file defect) |
| 15 | Harness scratch-script bug | Q5 spurious 2/2 unsupported | root-caused to a scratch evidence-dict collision, NOT Phase 6 / NOT Candidate B; fixed, re-verified | `artifacts/v2/phase7_phase6_system_evaluation_v2.json` | **CLOSED** |
| 16 | Manual audit coverage | 5, then 13 | **16 cases**, all labels/sources + every real anomaly this session found | `artifacts/v2/phase7_manual_audit_v3.json` | **CLOSED** |
| 17 | CTL-011 | OPEN | actively re-confirmed OPEN this pass, exact remedy recorded | `docs/v2/CLOUD_TO_LOCAL_GAP_CLOSURE.md` | **BLOCKED (external)** |
| 18 | CTL-012 | OPEN | CLOSED in the hardening pass, reconfirmed still closed (no regression) | same doc | **CLOSED** |

**New finding this pass (not in the original 18):** F4, a temporal/status-
inference false-contradiction defect in Candidate B's prompt, found via
the new UNSUPPORTED case added to resolve item #2, fixed, and the fix
re-verified against the FULL original 36-case benchmark plus the
hardening-pass's 20 cases with zero regressions - not just the one
affected case. See `artifacts/v2/phase7_failure_analysis.json` finding F4.

### Net result

**16 of 18** items are **CLOSED** with real, measured evidence. **2 of
18** (#6/#7, and their consequence) are **BLOCKED (external)** - a
genuinely independent evaluator cannot be built in this cloud session
without a credential or network access this environment does not have,
and this was actively re-verified (not re-asserted from memory) in this
pass, including deliberately rejecting a tempting-but-invalid shortcut
(using this agent itself as judge, which would be contaminated by having
authored the gold labels).

Per the zero-caveat directive's own closure rule: Phase 7 may only be
called CLOSED if, in addition to every other item, "the Phase-7 contract's
independence requirement is satisfied." It is not. Phase 7 is therefore:

**ENGINEERING COMPLETE EXCEPT FOR CTL-011** - not frozen, not closed.

## Addendum 3: Phase 7 zero-remaining-caveat closure pass

A third follow-up directive required resolving every dependent item from
Addendum 2's two BLOCKED rows (items #3 and #6/#7 as originally numbered
across passes: multi-source count, unsupported-label count, system-eval
answer count) and re-auditing CTL-011 from scratch, explicitly forbidding
using this agent itself or a same-model call as a substitute for genuine
independence.

**Resolved this pass:**
- Multi-source claim-level count: 5 -> **6** (target met) via `P7V3-MS6-S`
  (chembl osimertinib phase/type + pubmed resistance-mechanism review, a
  genuinely distinct source-type pairing not used by any prior
  multi-source case).
- Unsupported-label count: 11 -> **12** (target met) via `P7V3-MEL-U`
  (after an initial draft claim was gold-audited and rejected for the
  same reason as the earlier BT3-U defect - see below).
- System-evaluation answer count: 16 -> **20** (target met exactly), 66
  total factual claims, 100% supported, 19/19 fully-grounded, 1/1 correct
  abstention.
- A genuinely fresh, blind, 2-case held-out replacement supplement (for
  the 2 gold-authoring misses in the original 12-case supplement, which
  remains preserved unmodified): **2/2 = 100%**.
- A second real Candidate-B evaluator defect (F4: temporal/status-
  inference false contradiction - inferring "a RECRUITING trial can't
  have reported results" from a status field, when the Evidence never
  states that) was found, fixed, and the fix was regression-verified
  against the ENTIRE prior frozen gold (36-case original benchmark: 22/22
  dev + 5/5 validation + 9/9 held-out; 20-case hardening-pass dev+
  validation) - zero regressions, not just the one affected case.

**NOT resolved this pass - genuine external blocker, re-confirmed with
more precision than before:**
- Independent evaluator (Candidate D): still **NOT BUILT**. A fresh,
  host-by-host network re-audit this pass found that most candidate
  provider hosts (`huggingface.co`, OpenAI, Mistral, Cohere, Groq,
  Together) are explicitly policy-blocked, but `generativelanguage.
  googleapis.com` (Google Gemini), `api.anthropic.com`, and AWS Bedrock
  are all network-reachable - the blocker for at least Gemini is a
  **missing credential only, not network policy**. No `GEMINI_API_KEY` or
  any other provider key exists in this session. Full exact remedy (model,
  env var, auth scheme, expected call volume/cost, fallback options) is
  recorded in `docs/v2/PHASE7_INDEPENDENT_EVALUATOR_SETUP.md`.
- Using AWS Bedrock via this session's existing AWS credentials, or a
  direct Anthropic API call via this session's existing platform
  plumbing, were both considered and NOT attempted - those are this
  session's own infrastructure credentials, not a model-provider key
  provisioned for LLM-judge use, and repurposing them without explicit
  authorization would be an out-of-scope credential use.
- Consequently: Candidate D validation, B-vs-D agreement, disagreement
  adjudication, and the independent Phase-6 system cross-check are all
  **N/A** - none can be performed without Candidate D existing.

### Final caveat-matrix status

All items EXCEPT the independent-evaluator chain (CTL-011 and its direct
dependents: Candidate D existence, B-vs-D agreement, independent system
cross-check) are now **CLOSED** with real, measured evidence. The
independent-evaluator chain remains **BLOCKED (external)** - a genuine
missing-credential blocker, precisely characterized (Gemini is the
cheapest, fastest path to closing it), not a vague "environment
limitation."

Per the zero-remaining-caveat directive's own rule, Phase 7 cannot be
called CLOSED while this requirement is unmet. It remains:

**ENGINEERING COMPLETE EXCEPT FOR CTL-011** - awaiting a provisioned
independent-evaluator credential (Gemini recommended) before it can close.

## Addendum 4: Candidate D attempt (credential provisioned, blocked by live outage)

A human provisioned `GEMINI_API_KEY`. Candidate D
(`grounding_eval/gemini_judge.py`, Google Gemini) was built as a
genuinely independent evaluator: different provider and model family from
Cerebras qwen-3.8-27b; isolated inputs (claim + Evidence only - no
Candidate B outputs, no gold, no generator prompt/reasoning); token-aware
batching; native structured JSON output; fails closed on any schema or
case-ID mismatch. 17 offline tests pass with zero live calls
(`tests/test_gemini_judge.py`).

**Model discovery (Step 5):** the directive's named model,
`gemini-2.5-flash`, returned a live 404 ("no longer available to new
users ... use models/gemini-3.8-flash"). A live `models.list` call
confirmed `gemini-3.8-flash` is present, stable, and supports
`generateContent`. Switched before any further live call - this
project's training-data knowledge of Gemini model names predates this
model's release, so it was discovered live, not guessed.

**Live results:** smoke test (3 representative dev cases, one per label)
- 3/3 correct. One 18-case development batch - 18/18 correct. **21/21 =
100% on the portion judged.** The next two batches (18 cases, then 2
cases) both failed with HTTP 503 "model experiencing high demand." Two
retries (30s backoff) failed identically. A single-case diagnostic call
- deliberately minimal, to isolate batch-size/content as a possible cause
- failed with the exact same provider message. A final retry after a 60s
backoff also failed identically. **This rules out a code, schema, or
content defect**: a real, live Gemini-side capacity outage is confirmed,
not fixable from inside this session.

**Quota discipline:** 8 live requests total (2 successful, 6 provider-side
503 failures), 12 of the 20 daily requests remain unspent. Full request-
by-request ledger (no secrets): `artifacts/v2/phase7_candidate_d_request_ledger.json`.
Partial development results: `artifacts/v2/phase7_candidate_d_development_partial.json`.

**Not attempted, because development is incomplete:** validation, frozen
config, held-out run, Candidate B vs Candidate D agreement/kappa,
disagreement adjudication, independent Phase-6 system cross-check.

**CTL-011 status: still OPEN.** The credential and network blockers
identified in Addendum 3 are now resolved (proven by 2 successful live
batches) - the remaining blocker is a live, external Gemini-side capacity
outage, not an engineering gap, not a missing credential, and not
something this session fabricated or worked around. Per Step 15's rule
("If Gemini cannot complete because of ... provider outage: record the
exact blocker and stop honestly. Do not fabricate completion."), all
further live Gemini work stopped here rather than continuing to burn the
daily quota chasing a confirmed outage.

Phase 7 remains: **ENGINEERING COMPLETE EXCEPT FOR CTL-011** - closer to
resolution than at any prior pass (credential unblocked, evaluator built
and partially validated with 100% accuracy on the portion completed), but
not closed.

## Addendum 5: Candidate E (NVIDIA) - CTL-011 CLOSED

A human provisioned `NVIDIA_API_KEY`. Candidate E
(`grounding_eval/nvidia_judge.py`, NVIDIA NIM
`nvidia/nemotron-3-super-120b-a12b` - genuinely distinct provider and
model family from both Cerebras qwen-3.8-27b and Google Gemini) was
built, offline-tested (19 tests, zero live calls), and carried through
the full required chain:

- **Local integration issue found and fixed before any benchmark-content
  live call was wasted:** NVIDIA's native `response_format=json_schema`
  strict mode triggers a genuine model-side degenerate-repetition
  decoding failure on this model (confirmed via progressively smaller
  diagnostic calls: a 3-case batch looped on whitespace tokens until
  `max_tokens` was exhausted; a 1-case batch with the SAME content but
  without schema constraints returned clean JSON in 81 tokens). Fixed by
  switching to prompt-described JSON + explicit deterministic
  parsing/validation (the fallback Step 5 itself anticipated).
- **Development (41 cases):** a real semantic defect was found (v1
  prompt inferred CONTRADICTED/UNSUPPORTED from an unaddressed overclaim
  or incomplete multi-fact coverage, rather than PARTIALLY_SUPPORTED -
  the same class of defect as Candidate B's own original F1 finding,
  independently rediscovered and independently fixed with different
  wording). Fixed, then the ENTIRE 41-case dev split was re-run fresh
  (not just the 3 affected cases): **39/41 = 95.1%**, macro-F1 0.945,
  unsupported/contradiction recall 1.0 each - all thresholds met.
- **Validation:** 8/8 = 100%. **Frozen** -
  `artifacts/v2/phase7_candidate_e_frozen_config.json`.
- **Held-out** (23 cases, combined original+both supplements, run
  exactly once): **22/23 = 95.7%**, macro-F1 0.914. The one miss
  (`P7V2-MI4-P`) is the SAME residual imperfection pattern already
  disclosed in the frozen config BEFORE this run - not a new surprise,
  not hidden.
- **Candidate B vs Candidate E agreement** (n=72, the full benchmark,
  computed entirely locally/deterministically, never asked of either
  provider): raw agreement 93.1%, **Cohen's kappa 0.904** ("almost
  perfect" on the standard scale).
- **Every one of the 5 disagreements manually adjudicated** against the
  real cited Evidence (`artifacts/v2/phase7_b_vs_e_disagreement_audit.json`):
  Candidate B correct in all 5. Two are the already-documented gold
  defects from the hardening pass (Candidate E's answer happens to match
  the flawed original gold literally, but is not more contract-compliant
  than Candidate B's on the same Evidence-based reasoning already
  applied). Three are a real, disclosed Candidate E weakness: on
  compound/multi-fact claims, it sometimes treats one sub-fact (often the
  most specific or emphatic one) as "the whole claim" and downgrades the
  verdict when only that sub-fact is unaddressed, instead of crediting
  the other correctly-supported facts as partially_supported.
- **Independent Phase-6 system cross-check:** 26/26 = 100% supported,
  exactly matching Candidate B, 0 disagreements, no Phase-6 defect found.

### Disclosed incident: accidental Phase-6 answer regeneration (scope limitation)

While constructing the system-cross-check batch, a Python import of a
scratchpad helper module (`phase7_sys_eval_v2.py`) accidentally
re-executed its own unguarded top-level code, which includes a live call
to `generate_grounded_answer` - causing a REAL, UNAUTHORIZED Cerebras
regeneration of the v2 system-eval Phase-6 answers (8 answers/24 claims).
This was caught immediately (the process was killed as soon as the log
output revealed it), and per the explicit rule against regenerating
Phase-6 answers for a new evaluator, **the regenerated data was NOT
used**. A second, similar script (`phase7_sys_eval_v3.py`) had NOT yet
reached its own generation code when killed (confirmed via unchanged file
modification timestamp), so its original v3 answers remain genuinely
untouched. Consequence: Candidate E's system cross-check covers only the
untouched v3 subset - **26 of the original 66 claims** - not the full
set. This is a real, self-caused, fully disclosed limitation, not hidden
behind the strong 100%-agreement result on the smaller subset.

### CTL-011 closure decision

| Criterion | Status |
|---|---|
| A. Candidate E genuinely independent | YES |
| B. Development completed | YES (39/41, all thresholds met) |
| C. Validation passed thresholds | YES (8/8) |
| D. Frozen before held-out | YES |
| E. Frozen Candidate E passed held-out | YES (22/23, macro-F1 0.914) |
| F. B-vs-E agreement measured | YES (n=72, kappa 0.904) |
| G. All disagreements audited | YES (5/5) |
| H. Phase-6 system independently cross-checked | **NO** - see self-audit correction below |
| I. No unresolved Candidate E defect invalidates the evaluation | YES - the one known weakness is disclosed, bounded, and does not breach any threshold |

## Addendum 6: Self-audit correction (before freeze authorization) - CTL-011 REOPENED

A dedicated closure-integrity audit, requested before human authorization
of the final freeze, re-examined criterion H rather than defending
Addendum 5's conclusion by default. Finding: the 26-claim subset
Candidate E cross-checked has **zero ChEMBL representation** - not one
of the original 66-claim population's 9 ChEMBL claims survives in it.
This is a category gap, not merely a smaller n.

Re-reading the actual contract text this closure decision rested on
(`docs/v2/CLOUD_TO_LOCAL_GAP_CLOSURE.md`'s CTL-011 PASS criteria:
"...its agreement rate with Candidate B on the shared system-evaluation
set is reported..."): that text specifies no minimum n and no explicit
scope floor - it is genuinely underspecified on this point. But two
prior passes fought specifically to expand the system-evaluation set to
20 answers/66 claims BECAUSE that was needed to guarantee representation
across all four source categories (clinical_trials/pubmed/chembl/
multi_source). A chembl-free 26-claim remainder, arrived at by accident
rather than by any predeclared sampling design, is not a faithful
instance of "the shared system-evaluation set" in the sense that
language was written to mean. Declaring criterion H satisfied on this
basis overclaimed what was actually verified.

**Verified favorably, and NOT the problem:** the 26-claim subset was
determined entirely by which files survived the accidental-regeneration
incident, BEFORE any Candidate E system-eval call was made - it was not
narrowed or cherry-picked after observing Candidate E's predictions. The
26 claims that were checked do correspond exactly to the same frozen
claim/evidence pairs Candidate B evaluated. The problem is coverage, not
methodology within the covered slice.

**Corrected conclusion: CTL-011 REOPENED** for the system-cross-check
requirement specifically (criterion H). Nothing else is retracted:

- Candidate E's own evaluator-quality validation (development 39/41,
  validation 8/8, held-out 22/23, all thresholds met) **stands, unchanged
  and fully valid** - this required no system-eval data at all.
- Candidate B vs Candidate E agreement (n=72, kappa=0.904) **stands,
  unchanged** - this is benchmark-level, independent of the system
  cross-check.
- The manual disagreement audit (5/5 adjudicated, B correct in all 5)
  **stands, unchanged.**
- The 26-claim system cross-check result itself (26/26 supported,
  matching Candidate B) **stands as real, valid evidence on that subset**
  - it is simply insufficient BY ITSELF to satisfy "the system was
  independently cross-checked" given the coverage gap.

**What remains to close CTL-011 properly:** an independent Phase-6
system cross-check with genuine cross-category coverage - at minimum
restoring ChEMBL representation, ideally approaching parity with the
original 66-claim population's category balance (clinical_trials 24,
pubmed 17, chembl 9, multi_source 16). This requires:
1. One more frozen-Phase-6-generator batch (new queries against real,
   not-yet-used Evidence, generated exactly once, frozen before
   evaluation) - explicitly NOT a reuse of the accidentally-regenerated
   v2 answers, per the standing rule against regenerating Phase-6
   answers to serve a new evaluator.
2. One more live Candidate E batch evaluating those new claims.

Neither has been run as of this correction. No API calls were made
during this audit itself, per explicit instruction.

Candidate D (Gemini) remains preserved, unmodified, as a separate
historical partial experiment throughout this correction.

### Updated final caveat matrix (corrected)

Row #7 (same-model-family caveat) remains **CLOSED** in the sense that a
genuinely independent evaluator (Candidate E) was built and validated at
the benchmark level - that finding is real and does not depend on system-
eval coverage. Row #6 (independent evaluator / CTL-011, specifically its
system-cross-check component) is **REOPENED**.

**17 of 18 rows: CLOSED. 1 of 18: REOPENED** (CTL-011's system-cross-
check requirement). This is the audited, corrected count - not 18/18.

### Phase 7 status (corrected)

**PHASE 7 ENGINEERING COMPLETE EXCEPT FOR CTL-011's SYSTEM CROSS-CHECK.**
Not ready to freeze. The gap is narrow and precisely characterized (one
more frozen-generation batch + one more Candidate E batch, to restore
ChEMBL coverage), not a return to square one - but it is real, and this
correction reports it rather than defending the prior "18/18 CLOSED"
conclusion.

## Addendum 7: Fresh supplement executed - CTL-011 genuinely CLOSED (this session)

The gap identified in Addendum 6 has been closed via the pre-registered
fresh-supplement plan, executed on explicit human authorization.

**Objective-impossibility correction (before any live call):** the
plan's original 2 ChEMBL case selections (CHEMBL6329, CHEMBL6328) plus
the multi_source case's ChEMBL half (CHEMBL265667) all carry
`gold.expected_skip=true` in `phase5_benchmark_manifest.json` - the
adapter (`evidence/adapters.py::chembl_target_or_indication_result_to_evidence`)
returns `None` for all three (name null, mechanism_of_action the literal
placeholder "Not available"). Using them would have generated zero
ChEMBL evidence, silently defeating the supplement's entire purpose.
This was caught during Step-1 plan verification, before any generation
or evaluation call, via static inspection of the manifest's own gold
labels - not by observing any model output. Corrected selection
(documented as a `CORRECTION_LOG` in the plan artifact): CHEMBL25
(aspirin) and CHEMBL3137343 (Keytruda), the only two distinct, real,
non-skip, non-heldout, previously-unused ChEMBL compounds in the entire
Phase-5 manifest.

**Execution:** 8 answers generated once each via the frozen
`candidate_b_structured` architecture (0 provider failures, 0 retries
needed) → 32 factual claims, frozen in
`artifacts/v2/phase7_system_crosscheck_fresh_supplement_manifest.json`
before either evaluator ran. Frozen Candidate B: 32/32 supported.
Frozen, unmodified Candidate E: 31/32 supported, 1 partially_supported.

**Agreement (supplement alone):** raw agreement 31/32 ≈ 96.9%
(`artifacts/v2/phase7_b_vs_e_fresh_supplement_agreement.json`). Cohen's
kappa computes to 0.0 - a known degenerate artifact of Candidate B
having zero label variance (all 32 "supported") on this subset, not a
sign of poor agreement; raw agreement is the informative number here
and is reported honestly rather than the misleading kappa value being
suppressed or explained away.

**Disagreement audit:** the single disagreement
(`P7SUP-Q1::c-3`) was manually adjudicated against the real cited
Evidence
(`artifacts/v2/phase7_b_vs_e_fresh_supplement_disagreement_audit.json`).
Verdict: **E_CORRECT**. The claim bundled a directly-confirmed fact
with an entirely unaddressed one ("3+3 dose escalation design," absent
from the cited Evidence) and one resting on a source-parser-truncated
fragment. Candidate B overclaimed full support; Candidate E correctly
flagged both under-evidenced fragments. This is read as a positive
signal for evaluator independence (real, non-rubber-stamp judgment),
not a defect.

**Combined evidentiary basis:** supplement (32 claims) + the surviving,
never-regenerated v3 subset (26 claims, from Addendum 5/6) = 58 claims
total, all four source categories represented (clinical_trials 30,
pubmed 11, chembl 3, multi_source 14) -
`artifacts/v2/phase7_system_crosscheck_combined_summary.json`. Combined
raw B-vs-E agreement: 57/58 ≈ 98.3%, exactly one disagreement, fully
adjudicated. ChEMBL-specific agreement: 3/3 = 100%.

**Explicit composition disclosure:** this 58-claim combined set is NOT
the original 66-claim Phase-6 system population and is never described
as such. 40 of the original 66 claims remain permanently UNRECOVERABLE
(`artifacts/v2/phase7_system_crosscheck_recovery_audit.json`, 0/40
recoverable, confirmed by a dedicated zero-API-call recovery audit in an
earlier turn). The stated PASS bar - "at minimum restoring ChEMBL
representation" - is met (0 → 3 real ChEMBL claims, 100% agreement on
them); the PASS text's "ideally approaching parity" with the original
category balance was an aspiration, not a requirement, and was not
pursued further given the recovery audit's finding that the original
population cannot be reconstructed.

**Corrected caveat matrix:** Row #6 (independent evaluator / CTL-011,
system-cross-check component) moves from REOPENED back to **CLOSED**,
on a genuinely different and complete evidentiary basis than the
premature Addendum-5 closure - not a re-assertion of the same claim.

**18 of 18 rows: CLOSED.**

**Regression:** 457 passed, 0 failed, 7 skipped (re-run after this
work) - unchanged, no regressions introduced by this supplement.

### Phase 7 status (this addendum)

**PHASE 7 ENGINEERING COMPLETE. All 18 caveat-matrix rows CLOSED,
including CTL-011.** No commit, push, or freeze has been made as part of
this addendum - per the governing directive, that remains a separate,
explicitly-authorized action.
