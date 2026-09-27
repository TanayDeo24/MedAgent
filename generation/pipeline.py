"""Top-level Phase 6 pipeline: query + Evidence[] -> GroundedAnswer.

Ties together candidate generation, deterministic validation, deterministic
citation compilation, and deterministic rendering. This is the ONLY
function agent.nodes should call for Phase-6 generation (contract Section 1's
hard input boundary is enforced here, not just documented)."""

from __future__ import annotations

import uuid
from typing import Dict, List

from evidence.models import Evidence
from generation.citation_compiler import compile_citations, render_answer_text
from generation.generator import (
    GenerationProviderError,
    generate_candidate_a,
    generate_candidate_b,
)
from generation.models import GroundedAnswer
from generation.validation import GenerationValidationError, validate_claims, zero_evidence_guard

_ARCHITECTURES = {
    "candidate_a_direct_prose": generate_candidate_a,
    "candidate_b_structured": generate_candidate_b,
}


def generate_grounded_answer(
    query: str,
    evidence: List[Evidence],
    architecture: str = "candidate_b_structured",
) -> GroundedAnswer:
    """Hard input boundary (contract Section 1): only `query` + `evidence`
    are accepted - no raw tool_results, no retrieved_context, no prior
    citations list can reach this function's signature at all.

    Raises GenerationProviderError (provider/network failure) or
    GenerationValidationError (structurally invalid output) rather than
    ever returning a partially-valid GroundedAnswer - directive Step 32/33's
    "do not emit the answer as successful" / "no free-form unsafe
    fallback" requirement.
    """

    if architecture not in _ARCHITECTURES:
        raise ValueError(f"Unknown Phase-6 architecture {architecture!r}")

    generate_fn = _ARCHITECTURES[architecture]
    claims, conflict_detected, metadata = generate_fn(query, evidence)

    evidence_by_id: Dict[str, Evidence] = {ev.evidence_id: ev for ev in evidence}

    # Deterministic validation - never bypassed, never soft-failed.
    validate_claims(claims, evidence_by_id)
    zero_evidence_guard(evidence, claims)

    citations, references, evidence_id_to_number = compile_citations(claims, evidence_by_id)
    rendered_text = render_answer_text(claims, evidence_id_to_number)

    used_ids = sorted({eid for claim in claims for eid in claim.evidence_ids})
    unused_ids = sorted(set(evidence_by_id.keys()) - set(used_ids))

    abstained = not evidence or all(
        c.claim_type.value != "factual" for c in claims
    )

    answer = GroundedAnswer(
        answer_id=f"ans-{uuid.uuid4().hex[:12]}",
        query=query,
        claims=claims,
        rendered_text=rendered_text,
        citations=citations,
        references=references,
        used_evidence_ids=used_ids,
        unused_evidence_ids=unused_ids,
        abstained=abstained,
        conflict_detected=conflict_detected,
        generation_metadata=metadata,
    )

    # Serialization must succeed before the answer is considered valid
    # (directive Step 32's "serialization succeeds" check, hard gate
    # "unserializable final answer object").
    answer.model_dump_json()

    return answer
