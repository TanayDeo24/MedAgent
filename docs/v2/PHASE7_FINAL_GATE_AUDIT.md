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
