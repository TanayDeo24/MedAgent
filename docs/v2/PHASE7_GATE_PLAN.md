# Phase 7 Gate Plan

Predeclared before evaluator candidate measurement, per
`docs/v2/PHASE7_GROUNDING_EVALUATION_CONTRACT.md`.

## A. Evaluator quality metrics (System A)

Support classification: accuracy, macro precision/recall/F1, per-class
P/R/F1, confusion matrix. Unsupported detection: P/R/F1. Contradiction
detection: P/R/F1. Citation-relation classification: macro F1. Numeric
grounding: exact numeric mismatch detection accuracy. Multi-Evidence:
complete-support / missing-support / irrelevant-extra-citation detection.
Reliability: schema-valid rate, parse failures, provider errors, retries.
Performance: calls/case, tokens/case, latency mean/P50/P90/P95, cost/case,
total cost.

## B. Phase-6 system grounding metrics (System B — measured only after A validates)

Claim support rate, partial-support rate, unsupported-claim rate,
contradiction rate, citation precision, claim citation coverage,
citation-set sufficiency, irrelevant-citation rate, numeric claim support
rate, answer-level fully-grounded rate, abstention-grounding correctness,
conflict-grounding correctness.

## Predeclared quality thresholds (Step 20)

| Threshold | Target |
|---|---|
| Support-label macro F1 | >= 0.90 |
| Unsupported/contradicted detection recall | >= 0.95 |
| Citation-relation macro F1 | >= 0.90 |
| Numeric mismatch detection accuracy | >= 0.95 |
| Schema-valid evaluation rate | 100% |
| Hard safety gates | 100% |

Not lowered after seeing results (verified: all were exceeded — see
`artifacts/v2/phase7_validation_results.json` and
`artifacts/v2/phase7_heldout_results.json`).

## Hard safety gates (Step 19) — frozen, all must equal 0

| Gate | Required value |
|---|---|
| Unknown Evidence ID in evaluation output | 0 |
| Fabricated Evidence ID | 0 |
| Fabricated source ID | 0 |
| Fabricated source URL | 0 |
| Secret/auth leak | 0 |
| Unserializable evaluation | 0 |
| Uncaught evaluator schema failure | 0 |
| Gold label leak into evaluator input | 0 |
| Held-out gold used during tuning | 0 |
| Silent evaluator failure treated as pass | 0 |

Not weakened after seeing results, same discipline as Phases 2-6.
