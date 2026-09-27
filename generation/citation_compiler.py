"""Deterministic citation compilation and answer rendering - contract
Sections 9-11. Pure functions, no LLM calls, no randomness. Given the same
claims + Evidence[], always produces the same citation numbering and the
same rendered text.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from evidence.models import Evidence
from generation.models import CitationEntry, ClaimType, GroundedClaim, SourceReference
from generation.reference_renderer import display_fields_for_source_group
from generation.validation import GenerationValidationError


def _group_key(ev: Evidence) -> Tuple[str, str]:
    return (ev.source_type.value, ev.source_record_id)


def compile_citations(
    claims: List[GroundedClaim],
    evidence_by_id: Dict[str, Evidence],
) -> Tuple[List[CitationEntry], List[SourceReference], Dict[str, int]]:
    """Deterministic first-use numbering over `claims`, grouped by source
    record (contract Section 9) - never per raw Evidence ID, never
    model-assigned (contract Section 10).

    Returns (citations, references, claim_evidence_id_to_number) where the
    third value maps every cited evidence_id to its compiled citation
    number, for the renderer's use.

    Raises GenerationValidationError if any claim's evidence_ids reference
    an Evidence ID not in evidence_by_id (should already have been caught
    by generation.validation.validate_claims - this is a second,
    independent check, since the compiler must never trust an unvalidated
    input to build citation numbers from).
    """

    group_order: List[Tuple[str, str]] = []
    group_number: Dict[Tuple[str, str], int] = {}
    group_evidence_ids: Dict[Tuple[str, str], List[str]] = {}
    evidence_id_to_number: Dict[str, int] = {}

    for claim in claims:
        for eid in claim.evidence_ids:
            ev = evidence_by_id.get(eid)
            if ev is None:
                raise GenerationValidationError(
                    f"compile_citations: claim {claim.claim_id!r} references "
                    f"unknown Evidence ID {eid!r}"
                )
            key = _group_key(ev)
            if key not in group_number:
                group_order.append(key)
                group_number[key] = len(group_order)
                group_evidence_ids[key] = []
            if eid not in group_evidence_ids[key]:
                group_evidence_ids[key].append(eid)
            evidence_id_to_number[eid] = group_number[key]

    references: List[SourceReference] = []
    citations: List[CitationEntry] = []

    for key in group_order:
        number = group_number[key]
        eids = group_evidence_ids[key]
        group_evs = [evidence_by_id[e] for e in eids]
        display_fields = display_fields_for_source_group(group_evs)
        references.append(
            SourceReference(
                number=number,
                source_type=group_evs[0].source_type,
                source_record_id=group_evs[0].source_record_id,
                source_url=group_evs[0].source_url,
                grouped_evidence_ids=eids,
                display_fields=display_fields,
            )
        )
        citations.append(
            CitationEntry(
                number=number,
                evidence_ids=eids,
                source_reference_index=len(references) - 1,
            )
        )

    return citations, references, evidence_id_to_number


def render_answer_text(
    claims: List[GroundedClaim],
    evidence_id_to_number: Dict[str, int],
) -> str:
    """Deterministically assemble `rendered_text` from `claims` - contract
    Section 11 (inline placement, adjacent to the supporting claim, never
    a bulk end-of-paragraph dump). ABSTENTION/TRANSITION claims render
    without a citation marker unless they happen to carry evidence_ids."""

    lines: List[str] = []
    for claim in claims:
        marker = ""
        if claim.evidence_ids:
            numbers = sorted({evidence_id_to_number[e] for e in claim.evidence_ids})
            marker = "".join(f"[{n}]" for n in numbers)
        qualifier_text = f" ({claim.qualifier})" if claim.qualifier else ""
        lines.append(f"{claim.text}{qualifier_text}{marker}")

    return " ".join(lines)
