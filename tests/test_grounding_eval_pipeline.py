"""Offline tests for grounding_eval/pipeline.py (evaluate_claim/evaluate_answer)
and Phase-7 boundary checks. Cerebras calls are mocked via monkeypatch -
no real HTTP calls in this file."""

import os

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
from generation.models import ClaimType, GenerationMetadata, GroundedAnswer, GroundedClaim
from grounding_eval.models import CitationRelation, SupportLabel
from grounding_eval.pipeline import evaluate_answer, evaluate_claim


def _ev(chembl_id="CHEMBL1", content="Compound X"):
    return Evidence(
        evidence_id=make_evidence_id(SourceType.CHEMBL, chembl_id),
        source_type=SourceType.CHEMBL, source_record_id=chembl_id,
        source_url=make_source_url(SourceType.CHEMBL, chembl_id),
        evidence_type=EvidenceType.COMPOUND_IDENTITY, content=content,
        content_format=ContentFormat.FIELD_VALUE,
        source_metadata=ChemblEvidenceMetadata(),
        provenance=Provenance(retrieval_method="get_drug_info"),
    )


def _mock_judge(label, relations=None, unsupported_fragments=None):
    def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
        from grounding_eval.models import CitationGroundingJudgment, ClaimGroundingJudgment

        rels = relations or {eid: CitationRelation.SUPPORTS for eid in evidence_ids}
        return ClaimGroundingJudgment(
            claim_id=claim_id, support_label=label,
            citation_judgments=[
                CitationGroundingJudgment(evidence_id=eid, relation=rels[eid], reason_code="mocked")
                for eid in evidence_ids
            ],
            supporting_evidence_ids=[eid for eid in evidence_ids if rels[eid] in (CitationRelation.SUPPORTS, CitationRelation.PARTIAL_SUPPORT)],
            unsupported_fragments=unsupported_fragments or [],
            reason_code="mocked judge",
        )
    return _fake


def test_supported_paraphrase(monkeypatch):
    ev = _ev()
    monkeypatch.setattr("grounding_eval.pipeline.judge_claim_semantic", _mock_judge(SupportLabel.SUPPORTED))
    j = evaluate_claim("c1", "Compound X exists", [ev.evidence_id], {ev.evidence_id: ev}, architecture="candidate_b_semantic_judge")
    assert j.support_label == SupportLabel.SUPPORTED


def test_partial_overclaim(monkeypatch):
    ev = _ev()
    monkeypatch.setattr("grounding_eval.pipeline.judge_claim_semantic", _mock_judge(SupportLabel.PARTIALLY_SUPPORTED))
    j = evaluate_claim("c1", "Compound X is the best in class", [ev.evidence_id], {ev.evidence_id: ev}, architecture="candidate_b_semantic_judge")
    assert j.support_label == SupportLabel.PARTIALLY_SUPPORTED


def test_unsupported_claim(monkeypatch):
    ev = _ev()
    monkeypatch.setattr("grounding_eval.pipeline.judge_claim_semantic", _mock_judge(SupportLabel.UNSUPPORTED, {ev.evidence_id: CitationRelation.IRRELEVANT}))
    j = evaluate_claim("c1", "Compound X causes weight gain", [ev.evidence_id], {ev.evidence_id: ev}, architecture="candidate_b_semantic_judge")
    assert j.support_label == SupportLabel.UNSUPPORTED


def test_contradiction(monkeypatch):
    ev = _ev()
    monkeypatch.setattr("grounding_eval.pipeline.judge_claim_semantic", _mock_judge(SupportLabel.CONTRADICTED, {ev.evidence_id: CitationRelation.CONTRADICTS}))
    j = evaluate_claim("c1", "Compound X does not exist", [ev.evidence_id], {ev.evidence_id: ev}, architecture="candidate_b_semantic_judge")
    assert j.support_label == SupportLabel.CONTRADICTED


def test_irrelevant_citation(monkeypatch):
    ev = _ev()
    monkeypatch.setattr("grounding_eval.pipeline.judge_claim_semantic", _mock_judge(SupportLabel.UNSUPPORTED, {ev.evidence_id: CitationRelation.IRRELEVANT}))
    j = evaluate_claim("c1", "unrelated assertion", [ev.evidence_id], {ev.evidence_id: ev}, architecture="candidate_b_semantic_judge")
    assert j.citation_judgments[0].relation == CitationRelation.IRRELEVANT


def test_multiple_citations(monkeypatch):
    ev1, ev2 = _ev("CHEMBL1"), _ev("CHEMBL2")
    monkeypatch.setattr("grounding_eval.pipeline.judge_claim_semantic", _mock_judge(SupportLabel.SUPPORTED))
    j = evaluate_claim("c1", "both compounds exist", [ev1.evidence_id, ev2.evidence_id], {ev1.evidence_id: ev1, ev2.evidence_id: ev2}, architecture="candidate_b_semantic_judge")
    assert len(j.citation_judgments) == 2


def test_numeric_mismatch_via_deterministic():
    ev = _ev()
    j = evaluate_claim("c1", "reached Phase 1", [ev.evidence_id], {ev.evidence_id: ev}, architecture="candidate_a_deterministic")
    assert j.support_label in (SupportLabel.UNSUPPORTED, SupportLabel.CONTRADICTED)


def test_candidate_a_v2_dispatchable_via_pipeline():
    ev = _ev()
    j = evaluate_claim("c1", "reached Phase 1", [ev.evidence_id], {ev.evidence_id: ev}, architecture="candidate_a_v2_deterministic")
    assert j.support_label in (SupportLabel.UNSUPPORTED, SupportLabel.CONTRADICTED)


def test_complete_multi_evidence_support(monkeypatch):
    ev1, ev2 = _ev("CHEMBL1"), _ev("CHEMBL2")
    monkeypatch.setattr("grounding_eval.pipeline.judge_claim_semantic", _mock_judge(SupportLabel.SUPPORTED))
    j = evaluate_claim("c1", "claim needing both", [ev1.evidence_id, ev2.evidence_id], {ev1.evidence_id: ev1, ev2.evidence_id: ev2}, architecture="candidate_b_semantic_judge")
    assert all(r.relation == CitationRelation.SUPPORTS for r in j.citation_judgments)


def test_missing_one_required_support(monkeypatch):
    ev1, ev2 = _ev("CHEMBL1"), _ev("CHEMBL2")
    monkeypatch.setattr(
        "grounding_eval.pipeline.judge_claim_semantic",
        _mock_judge(SupportLabel.PARTIALLY_SUPPORTED, {ev1.evidence_id: CitationRelation.SUPPORTS, ev2.evidence_id: CitationRelation.IRRELEVANT}),
    )
    j = evaluate_claim("c1", "claim needing both", [ev1.evidence_id, ev2.evidence_id], {ev1.evidence_id: ev1, ev2.evidence_id: ev2}, architecture="candidate_b_semantic_judge")
    assert j.support_label == SupportLabel.PARTIALLY_SUPPORTED


def _answer(claims, evidence_list):
    return GroundedAnswer(
        answer_id="ans-1", query="Q", claims=claims, rendered_text="text",
        citations=[], references=[], used_evidence_ids=[e.evidence_id for e in evidence_list],
        unused_evidence_ids=[], abstained=False, conflict_detected=False,
        generation_metadata=GenerationMetadata(architecture="candidate_b_structured", provider="Cerebras", model="qwen-3.8-27b", llm_calls=1, latency_ms=1.0),
    )


def test_answer_fully_grounded(monkeypatch):
    ev = _ev()
    monkeypatch.setattr("grounding_eval.pipeline.judge_claim_semantic", _mock_judge(SupportLabel.SUPPORTED))
    claim = GroundedClaim(claim_id="c1", text="X", evidence_ids=[ev.evidence_id], claim_type=ClaimType.FACTUAL)
    result = evaluate_answer(_answer([claim], [ev]), {ev.evidence_id: ev}, architecture="candidate_b_semantic_judge")
    assert result.fully_grounded is True


def test_answer_one_unsupported_claim_not_fully_grounded(monkeypatch):
    ev = _ev()
    monkeypatch.setattr("grounding_eval.pipeline.judge_claim_semantic", _mock_judge(SupportLabel.UNSUPPORTED, {ev.evidence_id: CitationRelation.IRRELEVANT}))
    claim = GroundedClaim(claim_id="c1", text="X", evidence_ids=[ev.evidence_id], claim_type=ClaimType.FACTUAL)
    result = evaluate_answer(_answer([claim], [ev]), {ev.evidence_id: ev}, architecture="candidate_b_semantic_judge")
    assert result.fully_grounded is False
    assert result.unsupported_count == 1


def test_answer_one_contradicted_claim_not_fully_grounded(monkeypatch):
    ev = _ev()
    monkeypatch.setattr("grounding_eval.pipeline.judge_claim_semantic", _mock_judge(SupportLabel.CONTRADICTED, {ev.evidence_id: CitationRelation.CONTRADICTS}))
    claim = GroundedClaim(claim_id="c1", text="X", evidence_ids=[ev.evidence_id], claim_type=ClaimType.FACTUAL)
    result = evaluate_answer(_answer([claim], [ev]), {ev.evidence_id: ev}, architecture="candidate_b_semantic_judge")
    assert result.fully_grounded is False
    assert result.contradicted_count == 1


def test_answer_mixed_support(monkeypatch):
    ev1, ev2 = _ev("CHEMBL1"), _ev("CHEMBL2")
    calls = {"n": 0}

    def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
        calls["n"] += 1
        label = SupportLabel.SUPPORTED if calls["n"] == 1 else SupportLabel.UNSUPPORTED
        rel = CitationRelation.SUPPORTS if calls["n"] == 1 else CitationRelation.IRRELEVANT
        return _mock_judge(label, {evidence_ids[0]: rel})(claim_id, claim_text, evidence_ids, evidence_by_id)

    monkeypatch.setattr("grounding_eval.pipeline.judge_claim_semantic", _fake)
    c1 = GroundedClaim(claim_id="c1", text="X", evidence_ids=[ev1.evidence_id], claim_type=ClaimType.FACTUAL)
    c2 = GroundedClaim(claim_id="c2", text="Y", evidence_ids=[ev2.evidence_id], claim_type=ClaimType.FACTUAL)
    result = evaluate_answer(_answer([c1, c2], [ev1, ev2]), {ev1.evidence_id: ev1, ev2.evidence_id: ev2}, architecture="candidate_b_semantic_judge")
    assert result.supported_count == 1
    assert result.unsupported_count == 1
    assert result.fully_grounded is False


# --- Security ---


def test_no_secrets_in_serialized_output(monkeypatch):
    ev = _ev()
    monkeypatch.setattr("grounding_eval.pipeline.judge_claim_semantic", _mock_judge(SupportLabel.SUPPORTED))
    j = evaluate_claim("c1", "X", [ev.evidence_id], {ev.evidence_id: ev}, architecture="candidate_b_semantic_judge")
    dumped = j.model_dump_json()
    assert "CEREBRAS_API_KEY" not in dumped
    assert "Bearer " not in dumped
    assert "Authorization" not in dumped


def test_env_not_dumped_anywhere_in_module():
    import grounding_eval.judge as judge_module
    import inspect
    src = inspect.getsource(judge_module)
    assert "os.environ" not in src
    assert ".env" not in src


# --- Phase boundary ---


def test_evaluator_not_in_production_graph():
    import agent.graph as graph_module
    import inspect
    src = inspect.getsource(graph_module)
    assert "grounding_eval" not in src


def test_no_phase8_module_exists():
    import importlib
    for mod_name in ("research_loop", "phase8", "evidence_gap", "follow_up_research"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(mod_name)
