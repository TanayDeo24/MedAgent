# Phase 8 — Evidence-Driven Research Loop: Implementation

See `docs/v2/PHASE8_RESEARCH_LOOP_CONTRACT.md` for the authoritative
contract this implements, and `docs/v2/PHASE8_INITIAL_AUDIT.md` for the
architecture audit that motivated each design choice.

## New code

- `research/models.py` - `EvidenceGap`, `ResearchAction`, `GapType`,
  `StopReason`, `ResearchActionStatus`.
- `research/gap_analysis.py::analyze_gaps` - deterministic gap detection
  (NO_EVIDENCE, MISSING_SOURCE_CATEGORY) plus one frozen-Candidate-B-judge
  call per factual claim (WEAKLY_SUPPORTED_FACT, CONFLICTING_EVIDENCE).
- `research/action_planning.py::plan_actions` - turns gaps into at most one
  `ResearchAction`/iteration, templated `followup_query`, never a repeated
  signature.
- `research/loop_control.py` - `MAX_RESEARCH_ITERATIONS=3`,
  `MAX_TOOL_CALLS_TOTAL=8`, `MAX_REPEATED_ACTION=1`,
  `MAX_CONSECUTIVE_TOOL_FAILURE_ROUNDS=2`, `decide_stop_reason`.
- `agent/nodes.py` (additive, end of file) - `gap_analysis_node`,
  `should_continue_research_loop`, `research_action_planning_node`,
  `research_execution_node`, `evidence_merge_node`.
- `agent/graph.py::build_research_loop_graph` - new, separate graph
  builder; `MedAgent(research_loop=True)` opts in. `build_agent_graph()`
  and the default `MedAgent()` are unchanged.
- `agent/state.py` - 10 new, additive, defaulted `AgentState` fields (see
  file for the full list); `agent/nodes.py::query_analysis_node` gained one
  additive line storing the full `ResearchQuery` (`research_query_raw`)
  alongside the pre-existing lossy legacy projection.

## State / graph changes

`build_research_loop_graph()`:

```
query_analysis -> tool_orchestration -> synthesis -> evidence_normalization
  -> grounded_generation -> gap_analysis
       -[continue]-> research_action_planning -> research_execution
                      -> evidence_merge -> grounded_generation (loop)
       -[stop]------> report_generation -> END
```

`verification_node` (the old confidence-threshold loop) is absent from
this graph - present, unmodified, and still used by `build_agent_graph()`.

A LangGraph implementation constraint discovered while building this: a
node cannot stash an ad hoc key on `AgentState` for a later node to read -
only schema-declared `TypedDict` keys survive between node visits. Gap ->
action planning is therefore a pure function
(`agent.nodes._plan_next_actions`) invoked identically at both points that
need the same plan (the conditional edge and the node that acts on it),
rather than relying on a cross-node stash - verified never to diverge
because both calls take literally the same inputs.

## Bounded-loop safety

Every stop-reason check lives in one function
(`research.loop_control.decide_stop_reason`), evaluated in a fixed
precedence order, so the same inputs always produce the same verdict.
`tests/test_research_action_planning_and_loop_control.py::
test_decide_stop_never_infinite_for_a_persistently_unresolved_gap`
explicitly drives a gap that never resolves for
`MAX_RESEARCH_ITERATIONS+2` synthetic rounds and asserts the loop still
terminates within budget - the loop's termination does not depend on the
gap itself ever going away.

## Gap-detection behavior

Two deterministic detectors (evidence emptiness, Phase-2 source-category
coverage) plus one detector backed by the frozen, already-validated
Candidate B judge (per-claim support). No detector ever infers a gap from
free-form LLM text. Verified by
`tests/test_research_models_and_gap_analysis.py` (11 tests, all Candidate B
calls mocked - no live calls in this file).

## Follow-up research behavior

Every `ResearchAction` carries `gap_id` and is executed only via the
FROZEN Phase-3 dispatcher (`agent.nodes.tool_orchestration_node`, called
unmodified with a gap-targeted `followup_query` substituted for
`state["query"]`, then restored). No hand-rolled tool call exists anywhere
in `research/`.

## Evidence merge / deduplication

`evidence_merge_node` re-runs the frozen `evidence_normalization_node`
(Phase 5, unmodified - it recomputes `Evidence[]` from scratch every
visit, by design), then deduplicates by `evidence_id`, first occurrence
wins, diffed against a cumulative `evidence_seen_ids` set. A rediscovered
record increments `evidence_duplicate_count` and is excluded from
`new_evidence_ids` - never counted as research progress. Verified live in
`tests/test_research_integration.py::
test_productive_followup_adds_new_evidence_and_dedupes_on_rediscovery`.

## Stopping behavior

See the contract doc's Stop Reasons table. Every stop reason is recorded
on `state["research_stop_reason"]` before routing (never left implicit).

## Failure handling

See `docs/v2/PHASE8_FAILURE_ANALYSIS.md`.

## Benchmark methodology and results

See `docs/v2/PHASE8_GATE_PLAN.md` (predeclared design, including the
disclosed live-tool-network constraint) and the Dev Results section of
`docs/v2/PHASE8_FINAL_GATE_AUDIT.md` for the actual measured numbers.

## Validation pass (frozen architecture, fresh n=8 set)

See `docs/v2/PHASE8_FINAL_GATE_AUDIT.md`'s "Validation Results" section for
full detail. Summary: architecture frozen
(`artifacts/v2/phase8_frozen_config.json`) before this pass; 8 fresh,
previously-unused-in-Phase-8-development cases
(`artifacts/v2/phase8_validation_manifest.json`); CONTROL (frozen
single-pass) vs PHASE-8 (research loop) compared on identical cases
(`artifacts/v2/phase8_validation_results.json`,
`phase8_validation_metrics.json`). Zero fabricated/invalid Evidence IDs,
zero infinite loops, across all 8 cases. Completeness/source-coverage
improved in 3/8 cases (mean delta +0.1875); Claim Support Precision was
flat in 6/8 measurable cases and regressed in 1/8 (VAL-C) - a real
finding, disclosed rather than hidden (the loop's own state correctly
recorded the residual gap rather than reporting false success). No
validation-driven tuning was performed.
