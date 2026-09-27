"""Tests for evidence/models.py: id/url determinism, validation, roundtrip,
cross-source collision impossibility by construction."""

import pytest
from pydantic import ValidationError

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


# ---------------------------------------------------------------------------
# make_evidence_id determinism
# ---------------------------------------------------------------------------


def test_pubmed_rag_chunk_evidence_id_scheme():
    assert make_evidence_id(SourceType.PUBMED, "29119148", chunk_index=0) == "pubmed:29119148:chunk:0"
    assert make_evidence_id(SourceType.PUBMED, "29119148", chunk_index=1) == "pubmed:29119148:chunk:1"


def test_pubmed_live_article_evidence_id_scheme():
    assert make_evidence_id(SourceType.PUBMED, "29119148") == "pubmed:29119148"


def test_clinical_trials_evidence_id_scheme():
    assert make_evidence_id(SourceType.CLINICAL_TRIALS, "NCT01234567") == "nct:NCT01234567"


def test_chembl_evidence_id_scheme():
    assert make_evidence_id(SourceType.CHEMBL, "CHEMBL941") == "chembl:CHEMBL941"


def test_make_evidence_id_is_deterministic():
    a = make_evidence_id(SourceType.PUBMED, "123", chunk_index=2)
    b = make_evidence_id(SourceType.PUBMED, "123", chunk_index=2)
    assert a == b


def test_make_evidence_id_rejects_empty_source_record_id():
    with pytest.raises(ValueError):
        make_evidence_id(SourceType.PUBMED, "")


# ---------------------------------------------------------------------------
# make_source_url determinism
# ---------------------------------------------------------------------------


def test_make_source_url_pubmed():
    assert make_source_url(SourceType.PUBMED, "29119148") == "https://pubmed.ncbi.nlm.nih.gov/29119148/"


def test_make_source_url_clinical_trials():
    assert make_source_url(SourceType.CLINICAL_TRIALS, "NCT01234567") == "https://clinicaltrials.gov/study/NCT01234567"


def test_make_source_url_chembl():
    assert (
        make_source_url(SourceType.CHEMBL, "CHEMBL941")
        == "https://www.ebi.ac.uk/chembl/compound_report_card/CHEMBL941/"
    )


def test_make_source_url_rejects_empty_source_record_id():
    with pytest.raises(ValueError):
        make_source_url(SourceType.CHEMBL, "")


# ---------------------------------------------------------------------------
# Evidence construction helpers
# ---------------------------------------------------------------------------


def _pubmed_evidence(pmid="29119148", chunk_index=0, evidence_id=None):
    return Evidence(
        evidence_id=evidence_id or make_evidence_id(SourceType.PUBMED, pmid, chunk_index=chunk_index),
        source_type=SourceType.PUBMED,
        source_record_id=pmid,
        source_url=make_source_url(SourceType.PUBMED, pmid),
        evidence_type=EvidenceType.TEXT_PASSAGE,
        content="EGFR mutations drive resistance in NSCLC.",
        content_format=ContentFormat.VERBATIM_TEXT,
        title="EGFR resistance mechanisms",
        source_metadata=PubMedEvidenceMetadata(journal="Nature", year="2017"),
        provenance=Provenance(retrieval_method="rag_hybrid_rerank", chunk_index=chunk_index, num_chunks=2),
    )


def _trial_evidence(nct_id="NCT01234567"):
    return Evidence(
        evidence_id=make_evidence_id(SourceType.CLINICAL_TRIALS, nct_id),
        source_type=SourceType.CLINICAL_TRIALS,
        source_record_id=nct_id,
        source_url=make_source_url(SourceType.CLINICAL_TRIALS, nct_id),
        evidence_type=EvidenceType.TRIAL_STATUS,
        content="RECRUITING",
        content_format=ContentFormat.FIELD_VALUE,
        title="A trial of X",
        source_metadata=ClinicalTrialEvidenceMetadata(status="RECRUITING"),
        provenance=Provenance(retrieval_method="live_api", field_path="protocolSection.statusModule.overallStatus"),
    )


def _chembl_evidence(chembl_id="CHEMBL941"):
    return Evidence(
        evidence_id=make_evidence_id(SourceType.CHEMBL, chembl_id),
        source_type=SourceType.CHEMBL,
        source_record_id=chembl_id,
        source_url=make_source_url(SourceType.CHEMBL, chembl_id),
        evidence_type=EvidenceType.COMPOUND_IDENTITY,
        content="Osimertinib",
        content_format=ContentFormat.FIELD_VALUE,
        title="Osimertinib",
        source_metadata=ChemblEvidenceMetadata(match_type="exact_preferred_name"),
        provenance=Provenance(retrieval_method="resolve_compound_name"),
    )


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------


def test_evidence_constructs_successfully_for_all_three_sources():
    assert _pubmed_evidence().evidence_id == "pubmed:29119148:chunk:0"
    assert _trial_evidence().evidence_id == "nct:NCT01234567"
    assert _chembl_evidence().evidence_id == "chembl:CHEMBL941"


def test_evidence_rejects_empty_source_record_id():
    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="pubmed:x",
            source_type=SourceType.PUBMED,
            source_record_id="",
            source_url="https://pubmed.ncbi.nlm.nih.gov/x/",
            evidence_type=EvidenceType.TEXT_PASSAGE,
            content="text",
            content_format=ContentFormat.VERBATIM_TEXT,
            source_metadata=PubMedEvidenceMetadata(),
            provenance=Provenance(retrieval_method="live_api"),
        )


def test_evidence_rejects_empty_evidence_id():
    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="",
            source_type=SourceType.PUBMED,
            source_record_id="123",
            source_url="https://pubmed.ncbi.nlm.nih.gov/123/",
            evidence_type=EvidenceType.TEXT_PASSAGE,
            content="text",
            content_format=ContentFormat.VERBATIM_TEXT,
            source_metadata=PubMedEvidenceMetadata(),
            provenance=Provenance(retrieval_method="live_api"),
        )


def test_evidence_rejects_empty_content():
    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="pubmed:123",
            source_type=SourceType.PUBMED,
            source_record_id="123",
            source_url="https://pubmed.ncbi.nlm.nih.gov/123/",
            evidence_type=EvidenceType.TEXT_PASSAGE,
            content="   ",
            content_format=ContentFormat.VERBATIM_TEXT,
            source_metadata=PubMedEvidenceMetadata(),
            provenance=Provenance(retrieval_method="live_api"),
        )


def test_evidence_rejects_malformed_source_url():
    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="pubmed:123",
            source_type=SourceType.PUBMED,
            source_record_id="123",
            source_url="https://example.com/not-a-pubmed-url",
            evidence_type=EvidenceType.TEXT_PASSAGE,
            content="text",
            content_format=ContentFormat.VERBATIM_TEXT,
            source_metadata=PubMedEvidenceMetadata(),
            provenance=Provenance(retrieval_method="live_api"),
        )


def test_evidence_rejects_mismatched_source_metadata_kind():
    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="pubmed:123",
            source_type=SourceType.PUBMED,
            source_record_id="123",
            source_url="https://pubmed.ncbi.nlm.nih.gov/123/",
            evidence_type=EvidenceType.TEXT_PASSAGE,
            content="text",
            content_format=ContentFormat.VERBATIM_TEXT,
            source_metadata=ChemblEvidenceMetadata(),  # wrong kind for PUBMED
            provenance=Provenance(retrieval_method="live_api"),
        )


def test_evidence_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="pubmed:123",
            source_type=SourceType.PUBMED,
            source_record_id="123",
            source_url="https://pubmed.ncbi.nlm.nih.gov/123/",
            evidence_type=EvidenceType.TEXT_PASSAGE,
            content="text",
            content_format=ContentFormat.VERBATIM_TEXT,
            source_metadata=PubMedEvidenceMetadata(),
            provenance=Provenance(retrieval_method="live_api"),
            unexpected_field="nope",
        )


# ---------------------------------------------------------------------------
# Serialization roundtrip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("build", [_pubmed_evidence, _trial_evidence, _chembl_evidence])
def test_model_dump_roundtrip(build):
    original = build()
    dumped = original.model_dump()
    restored = Evidence.model_validate(dumped)
    assert restored == original


@pytest.mark.parametrize("build", [_pubmed_evidence, _trial_evidence, _chembl_evidence])
def test_model_dump_json_roundtrip(build):
    original = build()
    json_str = original.model_dump_json()
    restored = Evidence.model_validate_json(json_str)
    assert restored == original
    # Discriminated union must deserialize back to the exact correct subtype.
    assert type(restored.source_metadata) is type(original.source_metadata)


# ---------------------------------------------------------------------------
# Cross-source ID collision impossibility by construction
# ---------------------------------------------------------------------------


def test_cross_source_ids_cannot_collide_even_with_the_same_native_id_string():
    same_native_id = "941"
    pubmed_id = make_evidence_id(SourceType.PUBMED, same_native_id)
    nct_id = make_evidence_id(SourceType.CLINICAL_TRIALS, same_native_id)
    chembl_id = make_evidence_id(SourceType.CHEMBL, same_native_id)

    ids = {pubmed_id, nct_id, chembl_id}
    assert len(ids) == 3
    assert pubmed_id == "pubmed:941"
    assert nct_id == "nct:941"
    assert chembl_id == "chembl:941"


def test_chunk_level_and_article_level_pubmed_ids_never_collide():
    article_id = make_evidence_id(SourceType.PUBMED, "29119148")
    chunk_id = make_evidence_id(SourceType.PUBMED, "29119148", chunk_index=0)
    assert article_id != chunk_id


def test_evidence_id_stability_rate_same_input_same_id_every_time():
    ids = {make_evidence_id(SourceType.CHEMBL, "CHEMBL941") for _ in range(50)}
    assert ids == {"chembl:CHEMBL941"}


def test_provenance_call_id_none_is_valid_for_rag_path():
    # Per contract Section 4: call_id=None is expected/valid, not a
    # validation error, for the RAG path.
    prov = Provenance(retrieval_method="rag_hybrid_rerank", call_id=None)
    assert prov.call_id is None
