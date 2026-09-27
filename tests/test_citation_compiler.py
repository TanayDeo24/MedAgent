"""Offline tests for generation/citation_compiler.py - deterministic
citation numbering, source grouping, and rendering. No network/LLM calls.
"""

import pytest

from evidence.models import (
    ChemblEvidenceMetadata,
    ClinicalTrialEvidenceMetadata,
    ContentFormat,
    Evidence,
    EvidenceType,
    Provenance,
    PubMedEvidenceMetadata,
    SourceType,
    make_evidence_id,
    make_source_url,
)
from generation.citation_compiler import compile_citations, render_answer_text
from generation.models import ClaimType, GroundedClaim
from generation.validation import GenerationValidationError, validate_claims


def _pubmed_chunk(pmid, chunk_index, text, title="A Title"):
    return Evidence(
        evidence_id=make_evidence_id(SourceType.PUBMED, pmid, chunk_index=chunk_index),
        source_type=SourceType.PUBMED,
        source_record_id=pmid,
        source_url=make_source_url(SourceType.PUBMED, pmid),
        evidence_type=EvidenceType.TEXT_PASSAGE,
        content=text,
        content_format=ContentFormat.VERBATIM_TEXT,
        title=title,
        source_metadata=PubMedEvidenceMetadata(journal="J Med", year="2020"),
        provenance=Provenance(retrieval_method="rag_hybrid_rerank", chunk_index=chunk_index, num_chunks=2),
    )


def _trial_field(nct_id, evidence_type, content, title="A Trial"):
    return Evidence(
        evidence_id=make_evidence_id(SourceType.CLINICAL_TRIALS, nct_id),
        source_type=SourceType.CLINICAL_TRIALS,
        source_record_id=nct_id,
        source_url=make_source_url(SourceType.CLINICAL_TRIALS, nct_id),
        evidence_type=evidence_type,
        content=content,
        content_format=ContentFormat.FIELD_VALUE,
        title=title,
        source_metadata=ClinicalTrialEvidenceMetadata(status="RECRUITING"),
        provenance=Provenance(retrieval_method="live_api"),
    )


def _chembl(chembl_id, content, evidence_type=EvidenceType.COMPOUND_IDENTITY, name="Compound X"):
    return Evidence(
        evidence_id=make_evidence_id(SourceType.CHEMBL, chembl_id),
        source_type=SourceType.CHEMBL,
        source_record_id=chembl_id,
        source_url=make_source_url(SourceType.CHEMBL, chembl_id),
        evidence_type=evidence_type,
        content=content,
        content_format=ContentFormat.FIELD_VALUE,
        title=name,
        source_metadata=ChemblEvidenceMetadata(),
        provenance=Provenance(retrieval_method="get_drug_info"),
    )


def test_deterministic_first_use_numbering():
    ev1 = _chembl("CHEMBL1", "Compound A")
    ev2 = _chembl("CHEMBL2", "Compound B")
    claims = [
        GroundedClaim(claim_id="c0", text="A does X.", evidence_ids=[ev1.evidence_id], claim_type=ClaimType.FACTUAL),
        GroundedClaim(claim_id="c1", text="B does Y.", evidence_ids=[ev2.evidence_id], claim_type=ClaimType.FACTUAL),
    ]
    by_id = {ev1.evidence_id: ev1, ev2.evidence_id: ev2}
    citations, references, mapping = compile_citations(claims, by_id)
    assert mapping[ev1.evidence_id] == 1
    assert mapping[ev2.evidence_id] == 2
    assert [c.number for c in citations] == [1, 2]


def test_repeated_evidence_reuses_same_number():
    ev1 = _chembl("CHEMBL1", "Compound A")
    claims = [
        GroundedClaim(claim_id="c0", text="A does X.", evidence_ids=[ev1.evidence_id], claim_type=ClaimType.FACTUAL),
        GroundedClaim(claim_id="c1", text="A also does Z.", evidence_ids=[ev1.evidence_id], claim_type=ClaimType.FACTUAL),
    ]
    by_id = {ev1.evidence_id: ev1}
    citations, references, mapping = compile_citations(claims, by_id)
    assert len(citations) == 1
    assert len(references) == 1
    assert citations[0].number == 1


def test_multi_evidence_single_claim_citation():
    ev1 = _chembl("CHEMBL1", "Compound A")
    ev2 = _chembl("CHEMBL2", "Compound B")
    claims = [
        GroundedClaim(
            claim_id="c0", text="Both A and B do X.",
            evidence_ids=[ev1.evidence_id, ev2.evidence_id], claim_type=ClaimType.FACTUAL,
        ),
    ]
    by_id = {ev1.evidence_id: ev1, ev2.evidence_id: ev2}
    citations, references, mapping = compile_citations(claims, by_id)
    assert len(citations) == 2
    assert len(references) == 2


def test_pubmed_multi_chunk_same_article_groups_into_one_reference():
    chunk0 = _pubmed_chunk("111", 0, "First half.")
    chunk1 = _pubmed_chunk("111", 1, "Second half.")
    claims = [
        GroundedClaim(claim_id="c0", text="First fact.", evidence_ids=[chunk0.evidence_id], claim_type=ClaimType.FACTUAL),
        GroundedClaim(claim_id="c1", text="Second fact.", evidence_ids=[chunk1.evidence_id], claim_type=ClaimType.FACTUAL),
    ]
    by_id = {chunk0.evidence_id: chunk0, chunk1.evidence_id: chunk1}
    citations, references, mapping = compile_citations(claims, by_id)
    assert len(references) == 1
    assert sorted(references[0].grouped_evidence_ids) == sorted([chunk0.evidence_id, chunk1.evidence_id])
    assert mapping[chunk0.evidence_id] == mapping[chunk1.evidence_id] == 1


def test_clinicaltrials_multi_field_same_trial_groups_into_one_reference():
    status = _trial_field("NCT1", EvidenceType.TRIAL_STATUS, "RECRUITING")
    phase = _trial_field("NCT1", EvidenceType.TRIAL_PHASE, "PHASE2")
    claims = [
        GroundedClaim(claim_id="c0", text="The trial is recruiting.", evidence_ids=[status.evidence_id], claim_type=ClaimType.FACTUAL),
        GroundedClaim(claim_id="c1", text="It is a Phase 2 study.", evidence_ids=[phase.evidence_id], claim_type=ClaimType.FACTUAL),
    ]
    by_id = {status.evidence_id: status, phase.evidence_id: phase}
    citations, references, mapping = compile_citations(claims, by_id)
    assert len(references) == 1
    assert mapping[status.evidence_id] == mapping[phase.evidence_id]


def test_unknown_evidence_id_hard_failure():
    claims = [
        GroundedClaim(claim_id="c0", text="X does Y.", evidence_ids=["chembl:NONEXISTENT"], claim_type=ClaimType.FACTUAL),
    ]
    with pytest.raises(GenerationValidationError):
        compile_citations(claims, {})


def test_validate_claims_rejects_unknown_id():
    ev1 = _chembl("CHEMBL1", "Compound A")
    claims = [
        GroundedClaim(claim_id="c0", text="X.", evidence_ids=["chembl:UNKNOWN"], claim_type=ClaimType.FACTUAL),
    ]
    with pytest.raises(GenerationValidationError):
        validate_claims(claims, {ev1.evidence_id: ev1})


def test_validate_claims_accepts_known_id():
    ev1 = _chembl("CHEMBL1", "Compound A")
    claims = [
        GroundedClaim(claim_id="c0", text="X.", evidence_ids=[ev1.evidence_id], claim_type=ClaimType.FACTUAL),
    ]
    validate_claims(claims, {ev1.evidence_id: ev1})  # must not raise


def test_duplicate_claim_id_rejected():
    ev1 = _chembl("CHEMBL1", "Compound A")
    claims = [
        GroundedClaim(claim_id="c0", text="X.", evidence_ids=[ev1.evidence_id], claim_type=ClaimType.FACTUAL),
        GroundedClaim(claim_id="c0", text="Y.", evidence_ids=[ev1.evidence_id], claim_type=ClaimType.FACTUAL),
    ]
    with pytest.raises(GenerationValidationError):
        validate_claims(claims, {ev1.evidence_id: ev1})


def test_render_answer_text_places_citation_adjacent_to_claim():
    ev1 = _chembl("CHEMBL1", "Compound A")
    claims = [
        GroundedClaim(claim_id="c0", text="A inhibits the target.", evidence_ids=[ev1.evidence_id], claim_type=ClaimType.FACTUAL),
        GroundedClaim(claim_id="c1", text="This suggests broader applicability.", evidence_ids=[], claim_type=ClaimType.INFERENCE),
    ]
    by_id = {ev1.evidence_id: ev1}
    citations, references, mapping = compile_citations(claims, by_id)
    text = render_answer_text(claims, mapping)
    assert "A inhibits the target.[1]" in text
    assert "broader applicability.[1]" not in text  # inference claim carries no marker
