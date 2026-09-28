"""Offline tests for research/models.py + research/gap_analysis.py.
Candidate B judge calls are mocked via monkeypatch (same pattern as
tests/test_grounding_eval_pipeline.py) - no live Cerebras calls here."""

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
from grounding_eval.models import CitationGroundingJudgment, CitationRelation, ClaimGroundingJudgment, SupportLabel
from research.gap_analysis import analyze_gaps
from research.models import EvidenceGap, GapType, ResearchAction, ResearchActionStatus, StopReason


def _ev(source_type, record_id, content="Some content", evidence_type=EvidenceType.COMPOUND_IDENTITY):
    return Evidence(
        evidence_id=make_evidence_id(source_type, record_id),
        source_type=source_type, source_record_id=record_id,
        source_url=make_source_url(source_type, record_id),
        evidence_type=evidence_type, content=content,
        content_format=ContentFormat.FIELD_VALUE,
        source_metadata=ChemblEvidenceMetadata(),
        provenance=Provenance(retrieval_method="test"),
    )


def _answer(claims, abstained=False):
    return GroundedAnswer(
        answer_id="ans-1", query="q", claims=claims, rendered_text="text",
        citations=[], references=[], used_evidence_ids=[], unused_evidence_ids=[],
        abstained=abstained, conflict_detected=False,
        generation_metadata=GenerationMetadata(
            architecture="candidate_b_structured", model="qwen-3.8-27b", llm_calls=1,
            provider="cerebras", latency_ms=1.0,
        ),
    )


def _mock_judge(label):
    def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
        rels = {eid: CitationRelation.SUPPORTS for eid in evidence_ids}
        return ClaimGroundingJudgment(
            claim_id=claim_id, support_label=label,
            citation_judgments=[
                CitationGroundingJudgment(evidence_id=eid, relation=rels[eid], reason_code="mocked")
                for eid in evidence_ids
            ],
            supporting_evidence_ids=list(evidence_ids),
            unsupported_fragments=[], reason_code="mocked",
        )
    return _fake


# --- models.py ---

def test_evidence_gap_schema_rejects_unknown_field():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EvidenceGap(gap_id="g1", gap_type=GapType.NO_EVIDENCE, description="x", bogus_field=1)


def test_research_action_defaults():
    a = ResearchAction(action_id="a1", gap_id="g1", iteration=1, followup_query="q", reason="r")
    assert a.status == ResearchActionStatus.PLANNED
    assert a.new_evidence_ids == []


def test_stop_reason_enum_values_exact():
    assert {s.value for s in StopReason} == {
        "sufficient_evidence", "no_productive_action", "budget_exhausted",
        "tool_failure_limit", "unresolvable_gap", "safe_abstention",
    }


# --- gap_analysis.py ---

def test_no_evidence_gap_when_evidence_empty():
    gaps = analyze_gaps({"evidence": [], "grounded_answer": None})
    assert len(gaps) == 1
    assert gaps[0].gap_type == GapType.NO_EVIDENCE


def test_no_evidence_gap_when_abstained():
    ev = _ev(SourceType.CHEMBL, "CHEMBL1")
    answer = _answer([], abstained=True)
    gaps = analyze_gaps({"evidence": [ev], "grounded_answer": answer})
    assert len(gaps) == 1
    assert gaps[0].gap_type == GapType.NO_EVIDENCE


def test_missing_source_category_gap(monkeypatch):
    ev = _ev(SourceType.CHEMBL, "CHEMBL1")
    claim = GroundedClaim(claim_id="c-0", text="Claim text", evidence_ids=[ev.evidence_id], claim_type=ClaimType.FACTUAL)
    answer = _answer([claim])
    monkeypatch.setattr("research.gap_analysis.judge_claim_semantic", _mock_judge(SupportLabel.SUPPORTED))

    state = {
        "evidence": [ev],
        "grounded_answer": answer,
        "research_query_raw": {"requested_evidence_types": ["pubmed", "chembl"]},
    }
    gaps = analyze_gaps(state)
    missing = [g for g in gaps if g.gap_type == GapType.MISSING_SOURCE_CATEGORY]
    assert len(missing) == 1
    assert missing[0].target_source_category == "pubmed"


def test_no_missing_source_gap_when_all_present(monkeypatch):
    ev = _ev(SourceType.CHEMBL, "CHEMBL1")
    claim = GroundedClaim(claim_id="c-0", text="Claim text", evidence_ids=[ev.evidence_id], claim_type=ClaimType.FACTUAL)
    answer = _answer([claim])
    monkeypatch.setattr("research.gap_analysis.judge_claim_semantic", _mock_judge(SupportLabel.SUPPORTED))

    state = {
        "evidence": [ev],
        "grounded_answer": answer,
        "research_query_raw": {"requested_evidence_types": ["chembl"]},
    }
    gaps = analyze_gaps(state)
    assert not any(g.gap_type == GapType.MISSING_SOURCE_CATEGORY for g in gaps)


def test_weakly_supported_fact_gap(monkeypatch):
    ev = _ev(SourceType.CHEMBL, "CHEMBL1")
    claim = GroundedClaim(claim_id="c-0", text="Claim text", evidence_ids=[ev.evidence_id], claim_type=ClaimType.FACTUAL)
    answer = _answer([claim])
    monkeypatch.setattr("research.gap_analysis.judge_claim_semantic", _mock_judge(SupportLabel.UNSUPPORTED))

    state = {"evidence": [ev], "grounded_answer": answer, "research_query_raw": None}
    gaps = analyze_gaps(state)
    weak = [g for g in gaps if g.gap_type == GapType.WEAKLY_SUPPORTED_FACT]
    assert len(weak) == 1
    assert weak[0].related_claim_id == "c-0"


def test_conflicting_evidence_gap(monkeypatch):
    ev = _ev(SourceType.CHEMBL, "CHEMBL1")
    claim = GroundedClaim(claim_id="c-0", text="Claim text", evidence_ids=[ev.evidence_id], claim_type=ClaimType.FACTUAL)
    answer = _answer([claim])
    monkeypatch.setattr("research.gap_analysis.judge_claim_semantic", _mock_judge(SupportLabel.CONTRADICTED))

    state = {"evidence": [ev], "grounded_answer": answer, "research_query_raw": None}
    gaps = analyze_gaps(state)
    conflict = [g for g in gaps if g.gap_type == GapType.CONFLICTING_EVIDENCE]
    assert len(conflict) == 1
    assert conflict[0].related_claim_id == "c-0"


def test_supported_claim_produces_no_gap(monkeypatch):
    ev = _ev(SourceType.CHEMBL, "CHEMBL1")
    claim = GroundedClaim(claim_id="c-0", text="Claim text", evidence_ids=[ev.evidence_id], claim_type=ClaimType.FACTUAL)
    answer = _answer([claim])
    monkeypatch.setattr("research.gap_analysis.judge_claim_semantic", _mock_judge(SupportLabel.SUPPORTED))

    state = {"evidence": [ev], "grounded_answer": answer, "research_query_raw": None}
    gaps = analyze_gaps(state)
    assert gaps == []


def test_judge_failure_is_not_fabricated_as_a_gap(monkeypatch):
    ev = _ev(SourceType.CHEMBL, "CHEMBL1")
    claim = GroundedClaim(claim_id="c-0", text="Claim text", evidence_ids=[ev.evidence_id], claim_type=ClaimType.FACTUAL)
    answer = _answer([claim])

    def _raise(*a, **kw):
        raise RuntimeError("provider down")

    monkeypatch.setattr("research.gap_analysis.judge_claim_semantic", _raise)
    state = {"evidence": [ev], "grounded_answer": answer, "research_query_raw": None}
    gaps = analyze_gaps(state)
    # No fabricated gap from a failed judge call; no crash either.
    assert gaps == []


def test_non_factual_claims_are_never_judged(monkeypatch):
    calls = []

    def _tracking_judge(claim_id, *a, **kw):
        calls.append(claim_id)
        return _mock_judge(SupportLabel.SUPPORTED)(claim_id, *a, **kw)

    monkeypatch.setattr("research.gap_analysis.judge_claim_semantic", _tracking_judge)
    ev = _ev(SourceType.CHEMBL, "CHEMBL1")
    inference_claim = GroundedClaim(claim_id="c-inf", text="An inference", evidence_ids=[], claim_type=ClaimType.INFERENCE)
    answer = _answer([inference_claim])
    state = {"evidence": [ev], "grounded_answer": answer, "research_query_raw": None}
    analyze_gaps(state)
    assert calls == []
