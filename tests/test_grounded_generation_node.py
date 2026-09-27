"""Offline tests for agent.nodes.grounded_generation_node - the Phase 6
LangGraph integration point. No network/LLM calls (generate_grounded_answer
is monkeypatched)."""

import pytest

from agent.nodes import grounded_generation_node
from agent.state import create_initial_state
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
from generation.generator import GenerationProviderError
from generation.models import (
    CitationEntry,
    ClaimType,
    GenerationMetadata,
    GroundedAnswer,
    GroundedClaim,
    SourceReference,
)
from generation.validation import GenerationValidationError


def _chembl_evidence():
    return Evidence(
        evidence_id=make_evidence_id(SourceType.CHEMBL, "CHEMBL1"),
        source_type=SourceType.CHEMBL,
        source_record_id="CHEMBL1",
        source_url=make_source_url(SourceType.CHEMBL, "CHEMBL1"),
        evidence_type=EvidenceType.COMPOUND_IDENTITY,
        content="Compound A",
        content_format=ContentFormat.FIELD_VALUE,
        title="Compound A",
        source_metadata=ChemblEvidenceMetadata(),
        provenance=Provenance(retrieval_method="get_drug_info"),
    )


def _fake_answer(ev):
    claim = GroundedClaim(claim_id="c0", text="X.", evidence_ids=[ev.evidence_id], claim_type=ClaimType.FACTUAL)
    ref = SourceReference(
        number=1, source_type=ev.source_type, source_record_id=ev.source_record_id,
        source_url=ev.source_url, grouped_evidence_ids=[ev.evidence_id], display_fields={},
    )
    citation = CitationEntry(number=1, evidence_ids=[ev.evidence_id], source_reference_index=0)
    return GroundedAnswer(
        answer_id="ans-1", query="Q", claims=[claim], rendered_text="X.[1]",
        citations=[citation], references=[ref], used_evidence_ids=[ev.evidence_id],
        unused_evidence_ids=[], abstained=False, conflict_detected=False,
        generation_metadata=GenerationMetadata(
            architecture="candidate_b_structured", provider="Cerebras", model="qwen-3.8-27b",
            llm_calls=1, latency_ms=50.0,
        ),
    )


def test_node_receives_evidence_and_populates_grounded_answer(monkeypatch):
    ev = _chembl_evidence()
    captured = {}

    def _fake_generate(query, evidence, architecture="candidate_b_structured"):
        captured["query"] = query
        captured["evidence"] = evidence
        return _fake_answer(ev)

    monkeypatch.setattr("agent.nodes.generate_grounded_answer", _fake_generate)

    state = create_initial_state("What does compound A do?")
    state["evidence"] = [ev]
    result = grounded_generation_node(state)

    assert captured["evidence"] == [ev]
    assert result["grounded_answer"] is not None
    assert result["grounded_answer"].used_evidence_ids == [ev.evidence_id]


def test_node_does_not_touch_citations_or_final_report(monkeypatch):
    ev = _chembl_evidence()
    monkeypatch.setattr("agent.nodes.generate_grounded_answer", lambda q, e, architecture="candidate_b_structured": _fake_answer(ev))

    state = create_initial_state("Q")
    state["evidence"] = [ev]
    state["citations"] = [{"source": "existing"}]
    state["final_report"] = "existing report"
    result = grounded_generation_node(state)

    assert result["citations"] == [{"source": "existing"}]
    assert result["final_report"] == "existing report"


def test_node_handles_provider_error_without_crashing(monkeypatch):
    def _raise(*args, **kwargs):
        raise GenerationProviderError("simulated network failure")

    monkeypatch.setattr("agent.nodes.generate_grounded_answer", _raise)

    state = create_initial_state("Q")
    state["evidence"] = [_chembl_evidence()]
    result = grounded_generation_node(state)  # must not raise

    assert result["grounded_answer"] is None
    assert any("Grounded generation failed" in e for e in result["errors"])


def test_node_handles_validation_error_without_crashing(monkeypatch):
    def _raise(*args, **kwargs):
        raise GenerationValidationError("simulated unknown evidence id")

    monkeypatch.setattr("agent.nodes.generate_grounded_answer", _raise)

    state = create_initial_state("Q")
    state["evidence"] = [_chembl_evidence()]
    result = grounded_generation_node(state)  # must not raise

    assert result["grounded_answer"] is None
    assert any("Grounded generation failed" in e for e in result["errors"])


def test_no_secrets_in_state_after_node_runs(monkeypatch):
    ev = _chembl_evidence()
    monkeypatch.setattr("agent.nodes.generate_grounded_answer", lambda q, e, architecture="candidate_b_structured": _fake_answer(ev))

    state = create_initial_state("Q")
    state["evidence"] = [ev]
    result = grounded_generation_node(state)

    dumped = str(result["grounded_answer"].model_dump())
    assert "CEREBRAS_API_KEY" not in dumped
    assert "Bearer " not in dumped
    assert "Authorization" not in dumped


def test_legacy_report_generation_node_is_unmodified_and_separate():
    import agent.nodes as nodes_module

    # The legacy path (report_generation_node) still exists and is distinct
    # from the new V2 grounded-generation node - both must be importable
    # and separate, confirming Phase 6 did not delete or merge them.
    assert nodes_module.report_generation_node is not nodes_module.grounded_generation_node
