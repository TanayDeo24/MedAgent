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
