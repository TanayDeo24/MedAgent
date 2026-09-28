"""Phase 8 gap detection: decide what is missing/weak in the CURRENT
Evidence[] + GroundedAnswer, deterministically where possible.

Two detectors:
1. Source-coverage gap - compares Phase 2's own `requested_evidence_types`
   prediction (already computed, previously discarded downstream - see
   agent/state.py's `research_query_raw`) against the source types actually
   present in `state["evidence"]`. Purely deterministic set comparison, no
   LLM call.
2. Claim-support gap - reuses the FROZEN, validated Phase-7 Candidate B
   evaluator (`grounding_eval.judge.judge_claim_semantic`) to check each
   factual claim in the current `grounded_answer` against its own cited
   Evidence. This is the same evaluator Phase 7 froze and validated; Phase 8
   does not modify it, only calls it as a quality signal. A claim judged
   UNSUPPORTED/PARTIALLY_SUPPORTED/CONTRADICTED becomes a gap tied to that
   claim's `claim_id` - never inferred from raw model reasoning.

Neither detector ever fabricates a gap: NO_EVIDENCE and both detectors above
only fire from real, already-computed state (Evidence[], GroundedAnswer,
ResearchQuery) - never from asking an LLM "what's missing?" in free form."""

from __future__ import annotations

from typing import Any, Dict, List

from evidence.models import Evidence, SourceType
from grounding_eval.judge import judge_claim_semantic
from grounding_eval.models import SupportLabel
from research.models import EvidenceGap, GapType

_WEAK_LABELS = {SupportLabel.UNSUPPORTED, SupportLabel.PARTIALLY_SUPPORTED}


def analyze_gaps(state: Dict[str, Any]) -> List[EvidenceGap]:
    """Pure function over the current AgentState snapshot - no mutation, no
    LLM call of its own beyond judge_claim_semantic (frozen Phase-7 code,
    not modified here)."""

    gaps: List[EvidenceGap] = []
    evidence: List[Evidence] = state.get("evidence", []) or []
    grounded_answer = state.get("grounded_answer")

    if not evidence or grounded_answer is None or grounded_answer.abstained:
        gaps.append(
            EvidenceGap(
                gap_id="gap-no-evidence",
                gap_type=GapType.NO_EVIDENCE,
                description="No usable Evidence yet, or the current answer abstained "
                            "for lack of evidence.",
                severity=1.0,
            )
        )
        # No evidence at all means claim-level/source-coverage analysis has
        # nothing to work with yet - report only this gap this round.
        return gaps

    # --- Detector 1: source-category coverage vs Phase-2's own prediction ---
    present_categories = {ev.source_type.value for ev in evidence}
    research_query_raw = state.get("research_query_raw")
    if research_query_raw:
        requested = research_query_raw.get("requested_evidence_types") or []
        _EVIDENCE_SOURCE_TO_SOURCE_TYPE = {
            "pubmed": SourceType.PUBMED.value,
            "clinicaltrials": SourceType.CLINICAL_TRIALS.value,
            "chembl": SourceType.CHEMBL.value,
        }
        for req in requested:
            mapped = _EVIDENCE_SOURCE_TO_SOURCE_TYPE.get(req)
            if mapped and mapped not in present_categories:
                gaps.append(
                    EvidenceGap(
                        gap_id=f"gap-missing-source-{mapped}",
                        gap_type=GapType.MISSING_SOURCE_CATEGORY,
                        description=f"Phase-2 predicted {mapped!r} evidence is relevant "
                                    "to this query, but no Evidence of that source type "
                                    "has been retrieved yet.",
                        target_source_category=mapped,
                        severity=0.7,
                    )
                )

    # --- Detector 2: claim-level support, via the frozen Candidate B judge ---
    evidence_by_id = {ev.evidence_id: ev for ev in evidence}
    for claim in grounded_answer.claims:
        if claim.claim_type.value != "factual" or not claim.evidence_ids:
            continue
        cited = {eid: evidence_by_id[eid] for eid in claim.evidence_ids if eid in evidence_by_id}
        if not cited:
            continue
        try:
            judgment = judge_claim_semantic(claim.claim_id, claim.text, list(cited.keys()), cited)
        except Exception:
            # Judge itself failed (provider error) - not a gap this round;
            # do not fabricate a support judgment from a failed call.
            continue

        if judgment.support_label == SupportLabel.CONTRADICTED:
            gaps.append(
                EvidenceGap(
                    gap_id=f"gap-conflict-{claim.claim_id}",
                    gap_type=GapType.CONFLICTING_EVIDENCE,
                    description=f"Claim {claim.claim_id!r} is contradicted by its own "
                                "cited Evidence per the frozen Candidate B judge.",
                    related_claim_id=claim.claim_id,
                    severity=0.9,
                )
            )
        elif judgment.support_label in _WEAK_LABELS:
            gaps.append(
                EvidenceGap(
                    gap_id=f"gap-weak-{claim.claim_id}",
                    gap_type=GapType.WEAKLY_SUPPORTED_FACT,
                    description=f"Claim {claim.claim_id!r} is only "
                                f"{judgment.support_label.value} per the frozen Candidate B "
                                "judge - additional evidence may resolve it.",
                    related_claim_id=claim.claim_id,
                    severity=0.6 if judgment.support_label == SupportLabel.PARTIALLY_SUPPORTED else 0.8,
                )
            )

    return gaps
