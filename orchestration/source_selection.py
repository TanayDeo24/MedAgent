"""Deterministic source selection FROM the frozen Phase 2 `ResearchQuery` -
not from raw text, and not from a second free-form LLM call.

This is the direct fix for the audit's Section A finding: `ResearchQuery.
requested_evidence_types` is computed by the Phase 2 extractor but never
read anywhere downstream (`to_legacy_research_plan` drops it; the real
source-selection decision happens in a second, independent free-text LLM
call in `agent/nodes.py`'s `planning_node`, which can select zero, one, two,
or all three tools with no grounding in the structured query at all, and
which unconditionally falls back to "all three tools" on any planning
failure).
"""

from __future__ import annotations

from typing import List

from nlu.schemas import EvidenceSourceType, ResearchQuery
from orchestration.models import ToolName

# EvidenceSourceType (nlu/schemas.py) -> ToolName (orchestration/models.py).
# Both enums independently name the same three real integrations; this map
# is the single place that reconciles their (deliberately different -
# nlu/schemas.py's own docstring - "prediction" vs. "tool") string values.
_EVIDENCE_TYPE_TO_TOOL = {
    EvidenceSourceType.PUBMED: ToolName.PUBMED,
    EvidenceSourceType.CLINICALTRIALS: ToolName.CLINICAL_TRIALS,
    EvidenceSourceType.CHEMBL: ToolName.CHEMBL,
}


def select_sources(query: ResearchQuery) -> List[ToolName]:
    """Deterministically select which tools to call, from `query` alone.

    IMPORTANT - this is Phase 3's OWN source-selection decision, evaluated
    later by Phase 3's own Source-Set P/R/F1 metric (contract Section 1 /
    field_usage_notes). `query.requested_evidence_types` is used here as a
    deterministic INPUT SIGNAL, not treated as automatically authoritative:
    it is a Phase-2-produced *prediction* of what a correct answer would
    need (nlu/schemas.py docstring), not itself an execution/routing
    decision. Phase 3 is free to (and today does) treat it as its primary
    signal precisely because using it at all - rather than silently
    dropping it, as `agent/nodes.py` currently does - is the fix this
    module exists to make; a later Phase 3 evaluation pass is what actually
    validates whether trusting it this directly is the right call, not this
    function.

    Fallback behavior when `requested_evidence_types` is empty: returns an
    empty list ("insufficient signal"), NOT all three tools. This is a
    deliberate divergence from today's buggy `planning_node` fallback
    (audit Section A: "on any planning failure ... unconditional
    over-selection of all three sources regardless of query") - that
    fallback was flagged as a defect, not a pattern to repeat. An empty
    `requested_evidence_types` list is not evidence that all sources are
    needed; it is evidence that Phase 2 made no prediction (or, per its own
    schema default, was never populated). Silently guessing "call
    everything" in that situation would reintroduce unconditional
    over-selection under a new name. Callers that need a non-empty plan in
    this situation should consult `query.ambiguity` (contract Section 1:
    "if is_ambiguous, Phase 3 orchestration logic must be able to represent
    'no execution, needs clarification' as a valid plan outcome") or apply
    their own explicit, separately-reviewed fallback policy - that decision
    is deliberately left out of this pure function.

    Order is preserved from `query.requested_evidence_types` (stable,
    de-duplicated) rather than resorted - this function makes a set-style
    selection decision, not a priority/ranking decision (ranking, if
    needed, is a separate later step's job).
    """

    selected: List[ToolName] = []
    seen = set()
    for evidence_type in query.requested_evidence_types:
        tool_name = _EVIDENCE_TYPE_TO_TOOL.get(evidence_type)
        if tool_name is None:
            # Structurally shouldn't happen (EvidenceSourceType has exactly
            # these 3 members today), but fail closed - skip rather than
            # guess - if a future EvidenceSourceType value has no mapping
            # yet, instead of raising and aborting selection for the whole
            # query.
            continue
        if tool_name not in seen:
            selected.append(tool_name)
            seen.add(tool_name)

    return selected
