# Phase 8 — Failure Analysis

Per Step 17's required scenario list, with how each is actually covered.

| Scenario | Coverage | Result |
|---|---|---|
| Zero Evidence initially | Live dev case DEV-C + unit tests | `NO_EVIDENCE` gap detected, deterministic abstention (0 LLM calls per Phase 6's zero-Evidence guard), correct `SAFE_ABSTENTION` after one attempted follow-up |
| One source unavailable | `research_execution_node`'s underlying live tool network (PubMed/ClinicalTrials/ChEMBL) is genuinely blocked in this session (egress-proxy `connect_rejected`) - this IS a real, currently-occurring "source unavailable" condition, not a simulated one. `evidence_merge_node` correctly shows 0 new evidence when a follow-up round adds nothing (`test_unproductive_followup_marks_tool_failure_and_increments_consecutive_rounds`) | No crash; `research_consecutive_failure_rounds` increments; 2 consecutive unproductive rounds -> `TOOL_FAILURE_LIMIT` |
| Retrieval returns zero results | Same as above | Same as above |
| Duplicate-only retrieval | `test_productive_followup_adds_new_evidence_and_dedupes_on_rediscovery`'s second iteration | `evidence_duplicate_count` increments, `new_evidence_ids` empty, `Evidence[]` size unchanged |
| Malformed research action | `test_no_planned_action_leaves_state_unchanged_when_execution_called_anyway` | No-op, no crash, no fabricated action |
| Provider 429/5xx | Covered transitively by Phase 3's own frozen retry/error handling in `tool_orchestration_node` (unmodified) - a failed `ToolResult.success=False` is handled identically to "zero results" above |
| Timeout | Same as above (a timeout surfaces as a tool_call_history failure entry with `error_category`, per Phase 3's unmodified behavior) |
| Tool schema failure | Phase 3's frozen `parse_and_validate_tool_call`/registry validation (unmodified) already fails closed on this - `tests/test_nodes.py::test_hallucinated_tool_name_recorded_as_precision_miss` (pre-existing, still passing) covers it directly |
| Repeated action | `test_plan_actions_skips_already_attempted_signature`, `test_action_signature_is_stable_and_distinguishes_gaps` | never re-planned once attempted |
| Max iterations reached | `test_decide_stop_budget_exhausted_on_iteration_limit`, `test_budget_exhausted_even_with_gaps_remaining`, `test_decide_stop_never_infinite_for_a_persistently_unresolved_gap` | `BUDGET_EXHAUSTED`, never an infinite loop |
| Partial source success | `research_execution_node` records `tool_names_used` per action regardless of which of possibly several selected tools succeeded - Phase 3's own per-call `success`/`error` tracking (unmodified) already distinguishes this at the `tool_call_history` level |
| Unrecoverable evidence gap | DEV-C (live) - `SAFE_ABSTENTION`, never a second blind retry on the same zero-evidence gap |

## Root-caused defects found and fixed during this phase

1. **LangGraph state-threading**: an initial design stashed the planned
   `ResearchAction` on an undeclared `AgentState` key
   (`_pending_research_actions`) between the conditional-edge function and
   the next node. Caught before any live run (LangGraph filters state to
   schema-declared keys between node visits - confirmed directly, matching
   `agent/graph.py`'s pre-existing `use_rag` comment). Fixed by making
   gap -> action planning a pure, twice-invoked function
   (`agent.nodes._plan_next_actions`) instead of relying on a stash -
   verified never to diverge since both call sites share identical inputs.
2. **Evidence-merge duplicate accounting**: an early version of
   `evidence_merge_node` conflated "records new to this call" with
   "records genuinely new to the whole run," double-counting some
   duplicates and missing others. Caught by
   `test_productive_followup_adds_new_evidence_and_dedupes_on_rediscovery`
   before being treated as done; fixed to diff strictly against the
   cumulative `evidence_seen_ids` set.

## Known, disclosed limitation of the live dev benchmark

No case in the 4-case live dev sample organically produced a
`WEAKLY_SUPPORTED_FACT`/`CONFLICTING_EVIDENCE` gap - DEV-D's real, frozen
Candidate B generator produced only claims fully supported by the single
tangential article it was given, rather than the "weak, partially-relevant
claim" the case was designed to elicit. This is reported honestly rather
than iterated on to force the intended outcome (which would be exactly the
"do not benchmark-chase" violation the governing directive forbids).
Those two detectors are exercised and pass via 4 dedicated offline unit
tests with real `ClaimGroundingJudgment` fixtures
(`test_weakly_supported_fact_gap`, `test_conflicting_evidence_gap`, and
their negative counterparts) - a real, but weaker (non-live), form of
verification for that specific code path. A larger live dev sample in a
future session (once network access allows exercising more diverse
real-world evidence combinations, or once more adversarial cases are
predeclared) would give stronger live coverage of this path.

## Validation-pass findings (frozen architecture, no tuning applied)

1. **VAL-C: a genuine, disclosed Claim Support Precision regression.**
   A productive, completeness-improving follow-up (injecting real ChEMBL
   evidence) caused the frozen generator to add a new claim that the
   frozen Candidate B judge scored only `partially_supported`/
   `unsupported` on a later round (CSP 1.0 -> 0.667). The loop correctly
   detected this via a persisting `weakly_supported_fact` gap and stopped
   with `no_productive_action` - **not** `sufficient_evidence` - so the
   final state honestly records the unresolved issue rather than reporting
   false success. **Known limitation:** the final rendered `GroundedAnswer`
   text is not currently modified/caveated when the loop stops for a
   reason other than `sufficient_evidence`; this is a pre-existing
   Phase-6 rendering boundary (unchanged by Phase 8) that Phase 8 can now
   at least detect and record, but does not yet act on further. Flagged
   as explicit follow-up work, not fixed in this pass (post-freeze, no
   validation tuning).
2. **VAL-F: MAX_REPEATED_ACTION vs. MAX_CONSECUTIVE_TOOL_FAILURE_ROUNDS
   interaction.** When a case's single available gap has only one
   candidate action and that action fails once, `MAX_REPEATED_ACTION`
   (never retry an identical action) prevents any second attempt, so
   `NO_PRODUCTIVE_ACTION` fires before `TOOL_FAILURE_LIMIT` ever could.
   Both are valid, safe, bounded terminal states - this is a real,
   disclosed interaction between two independent bounds, not a defect.
   `TOOL_FAILURE_LIMIT` remains reachable when 2+ DIFFERENT actions each
   fail in immediate succession within the same run.
3. **VAL-D and VAL-H did not exercise their designed scenarios live**
   (the gap resolved, or never appeared, before the designed stress
   condition could occur) - both remain covered by dedicated offline
   tests (`test_productive_followup_adds_new_evidence_and_dedupes_on_rediscovery`,
   `test_decide_stop_never_infinite_for_a_persistently_unresolved_gap`).
   Reported honestly as a live-coverage gap in this specific 8-case
   validation run, not papered over.

## PHASE8-DEFECT-001 (VALIDATION RUN 1, reopened defect)

**Discovered:** human review of Validation Run 1's VAL-C case
(`artifacts/v2/phase8_validation_results.json`, case_id
`VAL-C-multi-source-completeness`). **Validation Run 1 is preserved
unchanged as the permanent record of this discovery** - see
`artifacts/v2/phase8_validation_run1_status.json`.

**Exact end-to-end trace (all values read directly from
`phase8_validation_results.json`, no re-run needed to root-cause this):**

1. Round 0: gap `missing_source_category(chembl)` detected (1 pubmed
   Evidence record only; Phase-2 predicted `['pubmed', 'chembl']`).
2. Research action targets that gap; follow-up acquires real Evidence
   `chembl:CHEMBL3137343` (productive, `new_evidence_ids` confirms it).
3. Round 1: `grounded_generation_node` re-runs on the merged 2-record
   Evidence[] and produces a NEW 3rd claim (`c-1`) that was not present
   in round 0's 2-claim answer. The frozen Candidate B judge scores `c-1`
   `partially_supported` - a new `weakly_supported_fact` gap, tied to
   `related_claim_id="c-1"`.
4. Round 1's follow-up finds nothing further (no more real Evidence
   available in this validation run for that specific gap).
5. Round 2: the SAME gap signature is already in the attempted set (per
   `MAX_REPEATED_ACTION`), so no action can be planned;
   `research_stop_reason` correctly becomes `no_productive_action` - the
   loop's own state accurately and honestly names the unresolved gap.
6. **The defect:** `state["grounded_answer"]` at this point is whatever
   `grounded_generation_node` last produced (round 1/2's answer, claim
   `c-1` included with NO indication that the system's own research state
   considers it unresolved). Nothing between the loop's stop and
   `report_generation_node` ever reads `research_stop_reason`/
   `research_gaps` to act on this. The final answer is therefore LESS
   safe than the state that produced it.

**Root cause, demonstrated not speculated:** `generate_grounded_answer`'s
frozen Phase-6 signature (`query`, `evidence` only - by design, contract
Section 1's hard input boundary) has no channel to receive "claim X is
currently flagged as an unresolved gap." That boundary is correct and is
NOT the defect. The actual defect is that **nothing downstream of the
loop's stop reads the loop's own final `research_gaps`/
`research_stop_reason` state to act on the `GroundedAnswer` it already
produced** - i.e., "unresolved-gap state not propagated to generation
[or its downstream consumer]," the first root-cause category in the
reopening directive's list. Ruled out: the research loop did NOT
incorrectly mark evidence sufficient (it correctly never reported
`sufficient_evidence` in this case); the final Evidence set is not
ambiguous/malformed (both records are real, valid, and correctly cited);
the claim itself does genuinely bundle content the evidence only partly
supports (matching this project's previously-documented Candidate-B
multi-fact-bundling failure mode) - the missing piece is purely the
integration gap between "the loop knows this claim is weak" and "the
final answer reflects that."

**Fix:** see "Fix implementation" below - a new, additive Phase-8 node
(`agent.nodes.finalize_research_answer_node`) that runs once, after the
loop stops, reading `research_gaps`/`research_stop_reason` and setting
`GroundedClaim.qualifier` (an existing, frozen Phase-6 schema field,
already rendered into `rendered_text` by the unmodified
`generation.citation_compiler.render_answer_text`) on exactly the
claim(s) tied to an unresolved `weakly_supported_fact`/
`conflicting_evidence` gap. General, gap-type-keyed - contains no
VAL-C-specific text, keyword, or case ID anywhere in its logic.
