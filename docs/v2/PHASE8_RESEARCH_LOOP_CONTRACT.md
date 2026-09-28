# Phase 8 — Evidence-Driven Research Loop Contract

Authoritative for the `research/` package and the Phase-8 nodes added to
`agent/nodes.py`/`agent/graph.py`. See `docs/v2/PHASE8_INITIAL_AUDIT.md` for
why each design choice was made. Machine-readable mirror:
`artifacts/v2/phase8_research_loop_contract.json`.

## Research State

Carried on the existing `AgentState` (additive fields only - see
`agent/state.py`, Section "PHASE 8 RESEARCH-LOOP FIELDS"):

| Field | Meaning |
|---|---|
| `query` | original research question (pre-existing) |
| `research_query_raw` | full `ResearchQuery` (Phase 2), incl. `requested_evidence_types` |
| `evidence` | current authoritative Evidence[] (pre-existing, Phase 5) |
| `research_gaps` | this iteration's `EvidenceGap[]` (overwritten each iteration) |
| `research_actions` | cumulative `ResearchAction[]` history (append-only) |
| `research_iteration` | loop iteration counter |
| `research_tool_calls_used` | cumulative follow-up tool-call count |
| `research_consecutive_failure_rounds` | consecutive unproductive rounds |
| `research_attempted_no_evidence` | whether a NO_EVIDENCE follow-up was already tried |
| `research_stop_reason` | the `StopReason` the loop actually stopped on |
| `evidence_seen_ids` | evidence_ids seen by any prior iteration (dedup) |
| `evidence_duplicate_count` | cumulative discarded-duplicate count |

## Research Action

`research.models.ResearchAction` - `action_id`, `gap_id` (traceability),
`iteration`, `target_source_category`, `followup_query`, `reason`,
`status` (`ResearchActionStatus`), `new_evidence_ids`,
`duplicate_evidence_ids`, `tool_names_used`, `error`.

Executed ONLY via the frozen Phase-3 dispatcher
(`agent.nodes.tool_orchestration_node`, itself unmodified) - this model
never carries an executable payload; `followup_query` is fed into that
same schema-constrained, registry-validated path. An unrecognized tool or
malformed argument still fails closed exactly as Phase 3 already
guarantees, since it is the identical code path.

## Evidence Gap

`research.models.EvidenceGap` - `gap_id`, `gap_type` (`GapType`),
`description`, `target_source_category`, `related_claim_id`, `severity`.

Detected by `research/gap_analysis.py::analyze_gaps`, from real,
already-computed state only:

1. **NO_EVIDENCE** - `state["evidence"]` is empty or `grounded_answer` is
   `None`/abstained.
2. **MISSING_SOURCE_CATEGORY** - Phase 2's `requested_evidence_types`
   names a source category not present among current Evidence's
   `source_type`s (deterministic set comparison, no LLM call).
3. **WEAKLY_SUPPORTED_FACT** - a factual claim judged `unsupported` or
   `partially_supported` by the frozen Candidate B judge
   (`grounding_eval.judge.judge_claim_semantic`) against its own cited
   Evidence.
4. **CONFLICTING_EVIDENCE** - a factual claim judged `contradicted` by the
   same judge.

No gap type is ever produced from free-form LLM "what's missing" text.

## Stop Reasons

`research.models.StopReason` - exactly:

- `SUFFICIENT_EVIDENCE` - gap analysis found zero gaps.
- `NO_PRODUCTIVE_ACTION` - gaps remain, but every one has already been
  attempted (its `action_signature` is in the run's attempted set).
- `BUDGET_EXHAUSTED` - `research_iteration >= MAX_RESEARCH_ITERATIONS` or
  `research_tool_calls_used >= MAX_TOOL_CALLS_TOTAL`.
- `TOOL_FAILURE_LIMIT` - `research_consecutive_failure_rounds >=
  MAX_CONSECUTIVE_TOOL_FAILURE_ROUNDS`.
- `SAFE_ABSTENTION` - the only remaining gap is `NO_EVIDENCE` and a
  NO_EVIDENCE follow-up has already been attempted once (a second blind
  retry on zero evidence is never attempted).
- `UNRESOLVABLE_GAP` - reserved in the enum for a gap whose
  `target_source_category` has no registered adapter/tool at all; no
  current detector produces this (all three registered sources have
  adapters), kept for forward-compatibility per the contract's own
  requirement for an explicit enum rather than inventing new ad hoc
  states later.

Checked in the fixed precedence documented in
`research/loop_control.py::decide_stop_reason` - the same inputs always
produce the same verdict.

## Bounded-Loop Numeric Limits

No authoritative numeric bound is given in `V2_PHASE_GATES.md` or
`EVALUATION_CONTRACT.md` beyond "must be bounded" - these are this
session's conservative, documented derivations (`research/loop_control.py`):

| Limit | Value | Rationale |
|---|---|---|
| `MAX_RESEARCH_ITERATIONS` | 3 | initial pass + at most 2 targeted follow-ups; Phase 3's single native-tool-calling round trip already selects multiple tools in one call, so further iterations should be rare and specifically gap-targeted |
| `MAX_TOOL_CALLS_TOTAL` | 8 | scaled down from the pre-existing `AgentState.max_iterations=10` convention, since Phase-8 follow-up is 1 targeted action/iteration, not open-ended |
| `MAX_REPEATED_ACTION` | 1 | an identical action signature (`gap_type:target_source_category:related_claim_id`) may be attempted at most once per run |
| `MAX_CONSECUTIVE_TOOL_FAILURE_ROUNDS` | 2 | two consecutive unproductive rounds (no new results) stops the loop rather than continuing to retry |

Every one of these is a hard ceiling checked in
`research.loop_control.decide_stop_reason` - there is no code path that can
loop past them (verified by `tests/test_research_loop_control.py`).

## Evidence Merge / Deduplication

`agent.nodes.evidence_merge_node` runs the frozen, unmodified
`evidence_normalization_node`, then deduplicates its from-scratch-recomputed
`Evidence[]` by `evidence_id` (first occurrence wins), diffed against the
cumulative `evidence_seen_ids` set. A rediscovered `evidence_id` increments
`evidence_duplicate_count` and is never counted in
`ResearchAction.new_evidence_ids` (i.e., never counted as research
progress).

## Final Generation

Only `agent.nodes.grounded_generation_node` (frozen Phase 6, unmodified)
ever produces the answer text/claims/citations, and only from the current,
merged, deduplicated `state["evidence"]`. The research loop produces no
separate "research summary" text at any point.
