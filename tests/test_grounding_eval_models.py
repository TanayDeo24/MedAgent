"""Offline tests for grounding_eval/models.py. No network/LLM calls."""

import pytest
from pydantic import ValidationError

from grounding_eval.models import (
    AnswerGroundingEvaluation,
    CitationGroundingJudgment,
    CitationRelation,
    ClaimGroundingJudgment,
    SupportLabel,
)


def _citation(eid="chembl:CHEMBL1", relation=CitationRelation.SUPPORTS):
    return CitationGroundingJudgment(evidence_id=eid, relation=relation, reason_code="test reason")


def test_supported_label_valid():
    j = ClaimGroundingJudgment(
        claim_id="c1", support_label=SupportLabel.SUPPORTED,
        citation_judgments=[_citation()], supporting_evidence_ids=["chembl:CHEMBL1"],
        reason_code="matches",
    )
    assert j.support_label == SupportLabel.SUPPORTED


def test_partially_supported_label_valid():
    j = ClaimGroundingJudgment(
        claim_id="c1", support_label=SupportLabel.PARTIALLY_SUPPORTED,
        citation_judgments=[_citation(relation=CitationRelation.PARTIAL_SUPPORT)],
        unsupported_fragments=["extra unsupported detail"], reason_code="partial",
    )
    assert j.support_label == SupportLabel.PARTIALLY_SUPPORTED


def test_unsupported_label_valid():
    j = ClaimGroundingJudgment(
        claim_id="c1", support_label=SupportLabel.UNSUPPORTED,
        citation_judgments=[_citation(relation=CitationRelation.IRRELEVANT)],
        reason_code="irrelevant",
    )
    assert j.support_label == SupportLabel.UNSUPPORTED


def test_contradicted_label_valid():
    j = ClaimGroundingJudgment(
        claim_id="c1", support_label=SupportLabel.CONTRADICTED,
        citation_judgments=[_citation(relation=CitationRelation.CONTRADICTS)],
        reason_code="conflict",
    )
    assert j.support_label == SupportLabel.CONTRADICTED


def test_empty_reason_code_rejected():
    with pytest.raises(ValidationError):
        ClaimGroundingJudgment(
            claim_id="c1", support_label=SupportLabel.SUPPORTED,
            citation_judgments=[_citation()], reason_code="   ",
        )


def test_no_chain_of_thought_field_exists():
    fields = ClaimGroundingJudgment.model_fields.keys()
    for forbidden in ("chain_of_thought", "reasoning", "internal_thoughts", "scratchpad"):
        assert forbidden not in fields


def test_serialization_roundtrip():
    j = ClaimGroundingJudgment(
        claim_id="c1", support_label=SupportLabel.SUPPORTED,
        citation_judgments=[_citation()], supporting_evidence_ids=["chembl:CHEMBL1"],
        reason_code="matches",
    )
    answer = AnswerGroundingEvaluation(
        answer_id="ans-1", claim_judgments=[j], factual_claim_count=1,
        supported_count=1, partially_supported_count=0, unsupported_count=0,
        contradicted_count=0, fully_grounded=True, citation_precision=1.0,
        claim_citation_coverage=1.0,
    )
    roundtripped = AnswerGroundingEvaluation.model_validate_json(answer.model_dump_json())
    assert roundtripped == answer
