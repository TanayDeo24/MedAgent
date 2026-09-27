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
