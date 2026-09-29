"""Phase 8 bounded-loop control: hard iteration/tool-call/repeat budgets and
the stop-reason decision function. No path through this module can run
unbounded - see docs/v2/PHASE8_RESEARCH_LOOP_CONTRACT.md."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from research.action_planning import action_signature
from research.models import EvidenceGap, GapType, ResearchAction, StopReason

# Conservative, explicitly-derived bounds (no authoritative Phase-8 numeric
# gate exists in V2_PHASE_GATES.md/EVALUATION_CONTRACT.md beyond "loops must
# be bounded" - these are this session's derived values, documented in
# docs/v2/PHASE8_RESEARCH_LOOP_CONTRACT.md):
#   - MAX_RESEARCH_ITERATIONS=3: initial pass + at most 2 targeted follow-up
#     rounds. Phase 3's single native-tool-calling round trip can already
#     select multiple tools in one call, so further iterations should be
#     rare and specifically gap-targeted, not blanket re-search.
#   - MAX_TOOL_CALLS_TOTAL=8: scaled down from the pre-existing
#     AgentState.max_iterations=10 convention (agent/state.py), since
#     Phase-8 follow-up is targeted (1 action/iteration) rather than
#     open-ended.
#   - MAX_REPEATED_ACTION=1: an identical action signature may be attempted
#     at most once, ever, for a given run.
MAX_RESEARCH_ITERATIONS = 3
MAX_TOOL_CALLS_TOTAL = 8
MAX_REPEATED_ACTION = 1
MAX_CONSECUTIVE_TOOL_FAILURE_ROUNDS = 2

# ---------------------------------------------------------------------------
# PHASE9-DEFECT-001 / PHASE9-DEFECT-002 fixes (Phase-9 "BOUNDEDNESS
# HARDENING" pass - see docs/v2/PHASE9_FAILURE_ANALYSIS.md and
# docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md for the full distribution-based
# derivation of each value below; artifacts/v2/phase9_claim_and_tool_call_distributions.json
# holds the raw extracted numbers). Both constants are intentional,
# documented, REQUEST-GLOBAL application-level budgets - not restatements of
# the incidental provider-token-derived ceilings that previously were the
# only thing bounding these call counts.
#
# CLAIM_EVALUATION_BUDGET: caps the TOTAL number of judge_claim_semantic()
# calls research/gap_analysis.py::analyze_gaps may issue across the WHOLE
# request (all G<=4 generation cycles combined), not per cycle. Chosen as
# (observed single-round-max claims in the Phase-8 dev/validation corpus, 8)
# x (the hard MAX_RESEARCH_ITERATIONS-derived cycle count, G=4) = 32 - i.e.
# exactly what a request would need if it sustained the corpus's own
# observed worst single-round rate across every one of its hard-bounded
# cycles. This is already 2x the highest actually-observed CUMULATIVE
# multi-round total in that same corpus (16, case VAL-F-tool-failure-safe-
# termination: 8+8 across its 2 real rounds), and roughly two orders of
# magnitude below the incidental max_completion_tokens=4096-derived ceiling
# (~400-600 claims/request) PHASE9-DEFECT-001 originally flagged as
# providing no meaningful reliability guarantee.
CLAIM_EVALUATION_BUDGET = 32

# MAX_TOOL_CALLS_PER_ROUND / MAX_TOOL_CALLS_PER_REQUEST: cap the number of
# LOGICAL model-emitted tool_calls[] ENTRIES (raw_tool_calls, valid or
# invalid - see the design-decision note in
# docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md's "BOUNDEDNESS HARDENING"
# section for why invalid entries also consume budget) that
# agent/nodes.py::tool_orchestration_node will process in a single round /
# across the whole request, respectively. MAX_TOOL_CALLS_PER_ROUND=12 is 2x
# DECLARED_TOOLS_COUNT=6 (orchestration/candidate_b_native_tools.py's
# DECLARED_TOOLS tuple) - enough headroom for the model to legitimately call
# the same tool twice with different arguments in one round (e.g. ChEMBL
# search-by-target AND search-by-indication) - and also happens to already
# cover the single highest REAL aggregate-per-request n_tool_calls value
# observed in artifacts/v2/phase9_baseline_results.json's 12 real baseline
# cases (12, case F5-research-loop-one-followup) even under the pessimistic
# assumption that all of it concentrated in one round. It is well below the
# soft, provider-token-budget-derived order-of-magnitude estimate of ~20-30
# valid tool_calls/round from
# artifacts/v2/phase9_boundedness_analysis.json's
# pre_optimization_consistency_audit_corrections key, so this is a genuine
# application-level tightening, not a restatement of that incidental
# ceiling. MAX_TOOL_CALLS_PER_REQUEST=24 is 2x that same observed real max
# (12) and is confirmed <= MAX_TOOL_CALLS_PER_ROUND * R (12*4=48) - the
# per-request figure is the tighter, binding constraint in practice.
MAX_TOOL_CALLS_PER_ROUND = 12
MAX_TOOL_CALLS_PER_REQUEST = 24

# ---------------------------------------------------------------------------
# Phase-9 "BOUNDEDNESS HARDENING" follow-up - SCHEDULING ONLY, not a
# performance change (see docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md's new
# "GAP-ANALYSIS JUDGE-CALL CONCURRENCY" section for the full writeup). This
# constant caps the number of SIMULTANEOUSLY RUNNING
# grounding_eval.judge.judge_claim_semantic() worker threads that
# research/gap_analysis.py::analyze_gaps may have in flight at once, via a
# bounded concurrent.futures.ThreadPoolExecutor(max_workers=GAP_ANALYSIS_MAX_CONCURRENCY).
#
# GAP_ANALYSIS_MAX_CONCURRENCY=1 is the default: it reproduces today's exact
# sequential call order and timing characteristics (one judge call in flight
# at a time, in grounded_answer.claims's own order) byte-for-byte - this pass
# ADDS the capability to raise this value, it does NOT change default runtime
# behavior. A live AC-powered benchmark pass (deferred - see
# artifacts/v2/phase9_gap_analysis_concurrency_experiment.json) is required
# before raising this default in production, since concurrency=1 is the only
# value with zero unvalidated interaction with the shared
# utils.rate_limiter.TokenBucket's real-world behavior under genuine thread
# overlap (its thread-safety was audited and is correct - see
# docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md's concurrency-audit section - but
# "correct" and "known-fast-and-safe under real provider latency/jitter" are
# different claims, and only the latter requires live timing evidence this
# pass explicitly does not collect).
GAP_ANALYSIS_MAX_CONCURRENCY = 1

# ---------------------------------------------------------------------------
# Phase-9 "PAIR BATCHING" pass (final Phase-9 optimization experiment - see
# docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md's "GAP-ANALYSIS PAIR BATCHING"
# section and artifacts/v2/phase9_pair_batching_experiment.json for the full
# pre-registered design and live A/B results). This constant caps how many
# factual claims research/gap_analysis.py::analyze_gaps groups into ONE
# logical grounding_eval.judge call.
#
# GAP_ANALYSIS_BATCH_SIZE=1 is the default: every scheduled claim is judged
# with its OWN, unmodified single-claim grounding_eval.judge.judge_claim_semantic
# call - byte-for-byte the same prompt/schema/behavior as before this pass.
# The only other supported value in this phase is 2 (grounding_eval.judge.judge_claims_batch,
# a genuinely new prompt/schema that judges 2 claims - each strictly isolated
# to its OWN cited Evidence - in one Cerebras request, explicitly tagged by
# claim_id so association is never inferred from response position). batch_size
# values other than 1/2 (4, full-answer, adaptive) are explicitly OUT OF SCOPE
# for this phase - see docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md's "explicitly
# not implemented" list.
#
# This is independent of GAP_ANALYSIS_MAX_CONCURRENCY (kept at 1): batching
# and concurrency are deliberately NOT combined in this phase, so the only
# lever this constant controls is how many claims share one logical provider
# call, never how many calls are in flight at once.
GAP_ANALYSIS_BATCH_SIZE = 2


def decide_stop_reason(
    gaps: List[EvidenceGap],
    planned_actions: List[ResearchAction],
    iteration: int,
    tool_calls_used: int,
    consecutive_failure_rounds: int,
    attempted_no_evidence_before: bool,
) -> Optional[StopReason]:
    """Returns a StopReason if the loop must stop now, else None (continue).
    Checked in a fixed, documented precedence order so the same state never
    produces two different verdicts."""

    if not gaps:
        return StopReason.SUFFICIENT_EVIDENCE

    if len(gaps) == 1 and gaps[0].gap_type == GapType.NO_EVIDENCE and attempted_no_evidence_before:
        return StopReason.SAFE_ABSTENTION

    if consecutive_failure_rounds >= MAX_CONSECUTIVE_TOOL_FAILURE_ROUNDS:
        return StopReason.TOOL_FAILURE_LIMIT

    if iteration >= MAX_RESEARCH_ITERATIONS or tool_calls_used >= MAX_TOOL_CALLS_TOTAL:
        return StopReason.BUDGET_EXHAUSTED

    if not planned_actions:
        return StopReason.NO_PRODUCTIVE_ACTION

    return None


def attempted_signatures(research_actions_history: List[Dict[str, Any]]) -> Set[str]:
    """Rebuilds the set of already-attempted action signatures from the
    accumulated, serialized action history (state["research_actions"]) -
    used both to prevent action_planning from repeating an action and to
    detect NO_PRODUCTIVE_ACTION once every remaining gap has been tried.
    Each history entry carries its own `gap_signature` (set at planning
    time via research.action_planning.action_signature), so this is a
    plain re-collection, not a reconstruction from partial fields."""

    return {
        entry["gap_signature"]
        for entry in research_actions_history
        if entry.get("gap_signature")
    }
