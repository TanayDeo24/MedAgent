"""Offline tests for the Phase 6 typed models (generation/models.py).

No network, no LLM calls anywhere in this file.
"""

import pytest
from pydantic import ValidationError

from generation.models import (
    CitationEntry,
    ClaimType,
    GenerationMetadata,
    GroundedAnswer,
    GroundedClaim,
    SourceReference,
)
from evidence.models import SourceType


def _metadata():
    return GenerationMetadata(
        architecture="candidate_b_structured",
        provider="Cerebras",
        model="qwen-3.8-27b",
        llm_calls=1,
        latency_ms=100.0,
    )


def test_valid_grounded_claim():
    claim = GroundedClaim(
        claim_id="c-0", text="Aspirin inhibits COX.", evidence_ids=["chembl:CHEMBL25"],
        claim_type=ClaimType.FACTUAL,
    )
    assert claim.evidence_ids == ["chembl:CHEMBL25"]


def test_factual_claim_with_no_evidence_ids_rejected():
    with pytest.raises(ValidationError):
        GroundedClaim(claim_id="c-0", text="X causes Y.", evidence_ids=[], claim_type=ClaimType.FACTUAL)


def test_abstention_claim_allows_empty_evidence_ids():
    claim = GroundedClaim(
        claim_id="c-0", text="Evidence is insufficient.", evidence_ids=[], claim_type=ClaimType.ABSTENTION,
    )
    assert claim.evidence_ids == []


def test_empty_text_rejected():
    with pytest.raises(ValidationError):
        GroundedClaim(claim_id="c-0", text="   ", evidence_ids=[], claim_type=ClaimType.TRANSITION)


def test_grounded_answer_serialization_roundtrip():
    claim = GroundedClaim(
        claim_id="c-0", text="Aspirin inhibits COX.", evidence_ids=["chembl:CHEMBL25"],
        claim_type=ClaimType.FACTUAL,
    )
    ref = SourceReference(
        number=1, source_type=SourceType.CHEMBL, source_record_id="CHEMBL25",
        source_url="https://www.ebi.ac.uk/chembl/compound_report_card/CHEMBL25/",
        grouped_evidence_ids=["chembl:CHEMBL25"], display_fields={"name": "Aspirin"},
    )
    citation = CitationEntry(number=1, evidence_ids=["chembl:CHEMBL25"], source_reference_index=0)
    answer = GroundedAnswer(
        answer_id="ans-1", query="What does aspirin do?", claims=[claim],
        rendered_text="Aspirin inhibits COX.[1]", citations=[citation], references=[ref],
        used_evidence_ids=["chembl:CHEMBL25"], unused_evidence_ids=[], abstained=False,
        conflict_detected=False, generation_metadata=_metadata(),
    )
    roundtripped = GroundedAnswer.model_validate_json(answer.model_dump_json())
    assert roundtripped == answer


def test_source_reference_requires_nonempty_group():
    with pytest.raises(ValidationError):
        SourceReference(
            number=1, source_type=SourceType.CHEMBL, source_record_id="CHEMBL25",
            source_url="https://www.ebi.ac.uk/chembl/compound_report_card/CHEMBL25/",
            grouped_evidence_ids=[], display_fields={},
        )
