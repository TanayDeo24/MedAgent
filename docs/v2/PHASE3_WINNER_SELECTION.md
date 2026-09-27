# Phase 3 Step 31 — Winner Selection

Full comparison data: `artifacts/v2/phase3_candidate_comparison.json`. This
document records the decision and its reasoning.

## 1. Candidate A — disqualified

Fails 2 of 7 hard safety gates (Section 3 of `docs/v2/PHASE3_GATE_PLAN.md`),
both by construction, not by chance: 28 schema-invalid calls reached the
real executor (no schema validation boundary exists), and all 107 real
tool calls lacked a traceable `call_id` (no such field exists anywhere in
`AgentState`/`tool_call_history`). Per the gate plan, a hard-gate failure
disqualifies a candidate regardless of its other metrics. Not eligible for
selection.

## 2. Candidate B vs. Candidate C

Both pass all 7 hard safety gates. Per directive Step 30's priority order
(safety > semantic correctness > reliability > failure attribution >
performance/cost, composite scoring disallowed), the deciding dimension is
**semantic correctness** — and here the two candidates' evidence is not of
equal quality:

- **Candidate B** was measured end-to-end from raw `original_query` text
  through Cerebras `qwen-3.8-27b`'s own real tool-selection decision — the
  identical measurement basis Candidate A (now disqualified) was held to.
  Its F1 0.932 / exact-match 93.2% is honest, trustworthy evidence of real
  routing quality against unseen text.
- **Candidate C** was measured with `select_sources()` reading a
  `requested_evidence_types` field that the benchmark's own author wrote
  *consistent with that same case's gold label* — not derived from
  independent, real Phase-2 NLU output. Its F1 1.0 is real evidence that
  the deterministic mapping code correctly implements its own contract; it
  is not valid evidence that Candidate C would route this well against a
  real, noisy `ResearchQuery` from the frozen Phase-2 extractor. This gap
  was found on independent review (not disclosed in the original
  measurement draft) and is now recorded in
  `docs/v2/PHASE3_CANDIDATE_C_MEASUREMENT.md` Section 0 and in
  `artifacts/v2/phase3_candidate_c_results.json`'s
  `caveats_added_on_independent_review`.

Reliability and failure attribution are comparable between B and C (both
route through `orchestration/registry.py`'s typed error taxonomy; both hit
the same pre-existing `clinical_trials` phase-filter defect on the same
handful of cases — a shared defect, not a candidate-specific one).

Candidate C is genuinely cheaper and faster (0 model calls vs. B's 1/case,
$0 vs. $0.092 for this 59-case run). This is a real architectural
advantage and is recorded as such — but the priority order explicitly
ranks performance/cost below semantic correctness, and it does not offset
an unresolved measurement-validity gap on C's central quality claim.

## 3. Decision

**Candidate B (Cerebras `qwen-3.8-27b` provider-native tool calling,
validated through `orchestration/registry.py`) is selected as the Phase 3
winner**, on the basis of trustworthy, apples-to-apples evidence: it passes
every hard safety gate, clears every quality gate with a wide margin over
the disqualified Candidate A baseline, and its central quality metric was
measured the same honest way Candidate A's was — unlike Candidate C's.

This is not a "least bad" selection (directive Step 31 prohibits that) —
Candidate B substantially and demonstrably beats the real, measured
Candidate A baseline on every dimension: F1 0.759→0.932, exact-match
57.6%→93.2%, schema-valid rate 73.8%→100% (of calls reaching execution),
2/7→7/7 hard gates, 0/6→3/6 abstention correctness, ~23.4s→~0.8s mean
selection-stage latency.

## 4. Named follow-up (not in-scope debt, does not block Phase 3 closure)

Candidate C's architecture (deterministic source selection from
`ResearchQuery.requested_evidence_types` + typed query compilers) remains
architecturally sound and worth revisiting: its individual components
(registry validation, schema rejection, abstention handling) are already
proven correct. What is missing is a fair re-measurement where
`requested_evidence_types` comes from a real run of the frozen Phase-2
extractor against each case's `original_query`, rather than a hand-authored
field. That re-measurement is recommended as future work (a natural fit
for whichever phase next revisits orchestration cost/latency, or an
explicit standalone follow-up) — it is not required to close Phase 3, since
Candidate B independently satisfies every predeclared gate on its own
trustworthy evidence.
