"""Phase 8 research-action planning: turn EvidenceGap[] into bounded,
traceable ResearchAction[] - never a generic "search for more information".

Every action's `followup_query` is a templated string built from the gap's
own fields (never free LLM brainstorming), then executed through the
FROZEN Phase-3 schema-constrained dispatcher
(`orchestration/candidate_b_native_tools.py` via
`agent.nodes.tool_orchestration_node`) - this module never calls a tool
itself and never bypasses that registry-validated path."""

from __future__ import annotations

from typing import List, Set

from research.models import EvidenceGap, GapType, ResearchAction, ResearchActionStatus

MAX_ACTIONS_PER_ITERATION = 1


def action_signature(gap: EvidenceGap) -> str:
    """Deterministic signature used to detect a repeated action across
    iterations (contract: "repeated action count" / stagnation)."""
    return f"{gap.gap_type.value}:{gap.target_source_category or ''}:{gap.related_claim_id or ''}"


def _followup_query_for(gap: EvidenceGap, original_query: str) -> str:
    if gap.gap_type == GapType.NO_EVIDENCE:
        return original_query
    if gap.gap_type == GapType.MISSING_SOURCE_CATEGORY:
        source_hint = {
            "pubmed": "peer-reviewed literature (PubMed)",
            "clinical_trials": "clinical trial records (ClinicalTrials.gov)",
            "chembl": "compound/target/indication data (ChEMBL)",
        }.get(gap.target_source_category, gap.target_source_category or "additional sources")
        return (
            f"For the research question '{original_query}', specifically look up "
            f"{source_hint} relevant to it."
        )
    if gap.gap_type in (GapType.WEAKLY_SUPPORTED_FACT, GapType.CONFLICTING_EVIDENCE):
        return (
            f"For the research question '{original_query}', find additional evidence "
            f"that specifically confirms or refutes the following claim: {gap.description}"
        )
    return original_query


def plan_actions(
    gaps: List[EvidenceGap],
    original_query: str,
    iteration: int,
    already_attempted_signatures: Set[str],
) -> List[ResearchAction]:
    """Selects the single highest-severity gap whose signature has not
    already been attempted, and turns it into one bounded ResearchAction.
    Returns an empty list when every remaining gap has already been
    attempted at least once (NO_PRODUCTIVE_ACTION territory - the caller,
    research/loop_control.py, is responsible for turning that into a stop
    reason, not this function)."""

    candidates = sorted(gaps, key=lambda g: g.severity, reverse=True)
    actions: List[ResearchAction] = []

    for gap in candidates:
        if len(actions) >= MAX_ACTIONS_PER_ITERATION:
            break
        sig = action_signature(gap)
        if sig in already_attempted_signatures:
            continue
        actions.append(
            ResearchAction(
                action_id=f"action-{iteration}-{gap.gap_id}",
                gap_id=gap.gap_id,
                iteration=iteration,
                target_source_category=gap.target_source_category,
                followup_query=_followup_query_for(gap, original_query),
                reason=gap.description,
                status=ResearchActionStatus.PLANNED,
            )
        )

    return actions
