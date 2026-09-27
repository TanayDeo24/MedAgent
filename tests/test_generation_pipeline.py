"""Offline tests for generation/pipeline.py. Network-dependent Cerebras
calls are mocked via monkeypatch - no real HTTP calls in this file.
"""

import pytest

from evidence.models import (
    ChemblEvidenceMetadata,
    ContentFormat,
    Evidence,
    EvidenceType,
    Provenance,
    SourceType,
    make_evidence_id,
    make_source_url,
)
from generation.models import ClaimType, GenerationMetadata, GroundedClaim
from generation.pipeline import generate_grounded_answer
from generation.validation import GenerationValidationError


def _chembl(chembl_id, content, name="Compound X"):
    return Evidence(
        evidence_id=make_evidence_id(SourceType.CHEMBL, chembl_id),
        source_type=SourceType.CHEMBL,
        source_record_id=chembl_id,
        source_url=make_source_url(SourceType.CHEMBL, chembl_id),
        evidence_type=EvidenceType.COMPOUND_IDENTITY,
        content=content,
        content_format=ContentFormat.FIELD_VALUE,
        title=name,
        source_metadata=ChemblEvidenceMetadata(),
        provenance=Provenance(retrieval_method="get_drug_info"),
    )


def test_zero_evidence_abstains_with_no_llm_call(monkeypatch):
    def _forbidden(*args, **kwargs):
        raise AssertionError("must not call Cerebras when Evidence[] is empty")

    monkeypatch.setattr("generation.generator._invoke_cerebras_claims", _forbidden)

    answer = generate_grounded_answer("What treats X?", [], architecture="candidate_b_structured")
    assert answer.abstained is True
    assert all(c.claim_type == ClaimType.ABSTENTION for c in answer.claims)
    assert answer.citations == []
    assert answer.references == []
    assert answer.generation_metadata.llm_calls == 0


def test_insufficient_evidence_still_grounds_what_it_can(monkeypatch):
    ev = _chembl("CHEMBL1", "Compound A")

    def _fake_invoke(query, evidence, **kwargs):
        return (
            [
                {"text": "Compound A is known.", "evidence_ids": [ev.evidence_id], "claim_type": "factual", "qualifier": None},
                {"text": "No evidence addresses the specific mechanism asked about.", "evidence_ids": [], "claim_type": "abstention", "qualifier": None},
            ],
            False,
            {"input_tokens": 10, "output_tokens": 10},
            1,
            None,
        )

    monkeypatch.setattr("generation.generator._invoke_cerebras_claims", _fake_invoke)

    answer = generate_grounded_answer("What is the mechanism?", [ev], architecture="candidate_b_structured")
    assert answer.abstained is False
    assert any(c.claim_type == ClaimType.ABSTENTION for c in answer.claims)
    assert any(c.claim_type == ClaimType.FACTUAL for c in answer.claims)


def test_conflicting_evidence_preserves_both_sides(monkeypatch):
    ev1 = _chembl("CHEMBL1", "Compound A shows response in trial 1.")
    ev2 = _chembl("CHEMBL2", "Compound A shows no response in trial 2.")

    def _fake_invoke(query, evidence, **kwargs):
        return (
            [
                {"text": "Trial 1 reported a response.", "evidence_ids": [ev1.evidence_id], "claim_type": "factual", "qualifier": None},
                {"text": "Trial 2 reported no response.", "evidence_ids": [ev2.evidence_id], "claim_type": "factual", "qualifier": None},
                {"text": "The evidence disagrees on efficacy.", "evidence_ids": [], "claim_type": "inference", "qualifier": None},
            ],
            True,
            {"input_tokens": 10, "output_tokens": 10},
            1,
            None,
        )

    monkeypatch.setattr("generation.generator._invoke_cerebras_claims", _fake_invoke)

    answer = generate_grounded_answer("Does compound A work?", [ev1, ev2], architecture="candidate_b_structured")
    assert answer.conflict_detected is True
    factual_texts = [c.text for c in answer.claims if c.claim_type == ClaimType.FACTUAL]
    assert len(factual_texts) == 2  # both sides preserved, not averaged


def test_unknown_evidence_id_from_model_rejected(monkeypatch):
    ev = _chembl("CHEMBL1", "Compound A")

    def _fake_invoke(query, evidence, **kwargs):
        return (
            [{"text": "X.", "evidence_ids": ["chembl:FABRICATED"], "claim_type": "factual", "qualifier": None}],
            False, {"input_tokens": 1, "output_tokens": 1}, 1, None,
        )

    monkeypatch.setattr("generation.generator._invoke_cerebras_claims", _fake_invoke)

    with pytest.raises(GenerationValidationError):
        generate_grounded_answer("Q", [ev], architecture="candidate_b_structured")


def test_used_and_unused_evidence_ids_tracked(monkeypatch):
    ev1 = _chembl("CHEMBL1", "Used compound")
    ev2 = _chembl("CHEMBL2", "Unused compound")

    def _fake_invoke(query, evidence, **kwargs):
        return (
            [{"text": "X uses compound 1.", "evidence_ids": [ev1.evidence_id], "claim_type": "factual", "qualifier": None}],
            False, {"input_tokens": 1, "output_tokens": 1}, 1, None,
        )

    monkeypatch.setattr("generation.generator._invoke_cerebras_claims", _fake_invoke)

    answer = generate_grounded_answer("Q", [ev1, ev2], architecture="candidate_b_structured")
    assert answer.used_evidence_ids == [ev1.evidence_id]
    assert answer.unused_evidence_ids == [ev2.evidence_id]


def test_answer_serializes_successfully(monkeypatch):
    ev = _chembl("CHEMBL1", "Compound A")

    def _fake_invoke(query, evidence, **kwargs):
        return (
            [{"text": "X.", "evidence_ids": [ev.evidence_id], "claim_type": "factual", "qualifier": None}],
            False, {"input_tokens": 1, "output_tokens": 1}, 1, None,
        )

    monkeypatch.setattr("generation.generator._invoke_cerebras_claims", _fake_invoke)

    answer = generate_grounded_answer("Q", [ev], architecture="candidate_b_structured")
    assert answer.model_dump_json()  # must not raise
