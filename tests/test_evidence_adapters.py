"""Tests for evidence/adapters.py, using realistic mocked input matching the
actual parsed shapes read from retrieval/retriever.py, tools/pubmed_tool.py,
tools/clinical_trials_tool.py, tools/chembl_tool.py. All offline/mocked, no
network calls.
"""

from dataclasses import dataclass

import pytest

from evidence.adapters import (
    chembl_resolve_compound_name_to_evidence,
    chembl_target_or_indication_result_to_evidence,
    clinical_trial_to_evidence_records,
    pubmed_live_result_to_evidence,
    pubmed_rag_document_to_evidence,
)
from evidence.models import ContentFormat, EvidenceType, SourceType
from evidence.registry import DEFAULT_ADAPTER_REGISTRY, EvidenceAdapterError


# ---------------------------------------------------------------------------
# A lightweight stand-in for retrieval.retriever.Document, matching its real
# dataclass field set exactly (retrieval/retriever.py:42-57).
# ---------------------------------------------------------------------------


@dataclass
class _FakeDocument:
    pmid: str
    title: str
    text: str
    score: float
    journal: str = ""
    year: str = ""
    pub_date: str = ""
    doi: str = ""
    url: str = ""
    chunk_index: int = 0
    num_chunks: int = 1
    chunk_id: str = ""


# ===========================================================================
# PubMed RAG
# ===========================================================================


def test_pubmed_rag_document_to_evidence_preserves_chunk_id_and_corpus_version():
    doc = _FakeDocument(
        pmid="29119148",
        title="EGFR resistance mechanisms",
        text="Osimertinib overcomes T790M-mediated resistance.",
        score=0.83,
        journal="Nature",
        year="2017",
        pub_date="2017-Aug",
        doi="10.1000/xyz",
        url="https://pubmed.ncbi.nlm.nih.gov/29119148/",
        chunk_index=1,
        num_chunks=2,
        chunk_id="29119148_1",
    )

    evidence = pubmed_rag_document_to_evidence(doc, corpus_index_version="9000-abstracts-v1")

    assert evidence.evidence_id == "pubmed:29119148:chunk:1"
    assert evidence.source_record_id == "29119148"
    assert evidence.source_type == SourceType.PUBMED
    assert evidence.evidence_type == EvidenceType.TEXT_PASSAGE
    assert evidence.content_format == ContentFormat.VERBATIM_TEXT
    assert evidence.content == doc.text
    assert evidence.provenance.chunk_index == 1
    assert evidence.provenance.num_chunks == 2
    assert evidence.provenance.corpus_index_version == "9000-abstracts-v1"
    # RAG path is not a Phase-3 tool call - call_id must never be fabricated.
    assert evidence.provenance.call_id is None
    assert evidence.source_metadata.journal == "Nature"
    assert evidence.source_metadata.doi == "10.1000/xyz"
    assert evidence.source_metadata.authors == []


def test_pubmed_rag_document_to_evidence_normalizes_empty_strings_not_placeholders():
    doc = _FakeDocument(
        pmid="1",
        title="",
        text="Some chunk text.",
        score=0.1,
        journal="",
        year="",
        pub_date="",
        doi="",
        chunk_index=0,
        num_chunks=1,
    )
    evidence = pubmed_rag_document_to_evidence(doc, corpus_index_version="v1")
    assert evidence.title is None
    assert evidence.source_metadata.journal is None
    assert evidence.source_metadata.doi is None


def test_pubmed_rag_document_to_evidence_rejects_empty_pmid():
    doc = _FakeDocument(pmid="", title="t", text="text", score=0.1)
    with pytest.raises(ValueError):
        pubmed_rag_document_to_evidence(doc, corpus_index_version="v1")


def test_pubmed_rag_ids_deterministic_across_calls():
    doc = _FakeDocument(pmid="5", title="t", text="x", score=0.1, chunk_index=2, num_chunks=3)
    e1 = pubmed_rag_document_to_evidence(doc, corpus_index_version="v1")
    e2 = pubmed_rag_document_to_evidence(doc, corpus_index_version="v1")
    assert e1.evidence_id == e2.evidence_id == "pubmed:5:chunk:2"


# ===========================================================================
# PubMed live
# ===========================================================================


def _live_pubmed_result(**overrides):
    base = {
        "pmid": "12345678",
        "title": "A real title",
        "abstract": "A real abstract about EGFR inhibitors.",
        "authors": ["Jane Doe", "John Smith"],
        "pub_date": "2020-Jan",
        "year": "2020",
        "journal": "The Lancet",
        "doi": "10.1000/abc",
        "url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
    }
    base.update(overrides)
    return base


def test_pubmed_live_result_to_evidence_normal_case():
    result = _live_pubmed_result()
    evidence = pubmed_live_result_to_evidence(result)
    assert evidence is not None
    assert evidence.evidence_id == "pubmed:12345678"
    assert evidence.content == result["abstract"]
    assert evidence.title == "A real title"
    assert evidence.source_metadata.authors == ["Jane Doe", "John Smith"]
    assert evidence.provenance.retrieval_method == "live_api"
    assert evidence.provenance.chunk_index is None


def test_pubmed_live_result_to_evidence_rejects_placeholder_abstract():
    # Exactly the literal fallback string from tools/pubmed_tool.py:142.
    result = _live_pubmed_result(abstract="No abstract available")
    assert pubmed_live_result_to_evidence(result) is None


def test_pubmed_live_result_to_evidence_rejects_empty_abstract():
    result = _live_pubmed_result(abstract="")
    assert pubmed_live_result_to_evidence(result) is None


def test_pubmed_live_result_to_evidence_normalizes_placeholder_title_without_dropping_record():
    # Exactly the literal fallback string from tools/pubmed_tool.py:124.
    result = _live_pubmed_result(title="No title available")
    evidence = pubmed_live_result_to_evidence(result)
    assert evidence is not None
    assert evidence.title is None


def test_pubmed_live_result_to_evidence_rejects_missing_pmid():
    result = _live_pubmed_result(pmid="")
    assert pubmed_live_result_to_evidence(result) is None


def test_pubmed_live_result_to_evidence_normalizes_journal_and_date_placeholders():
    result = _live_pubmed_result(journal="Unknown journal", pub_date="Date not available", doi="")
    evidence = pubmed_live_result_to_evidence(result)
    assert evidence.source_metadata.journal is None
    assert evidence.source_metadata.pub_date is None
    assert evidence.source_metadata.doi is None


# ===========================================================================
# ClinicalTrials
# ===========================================================================


def _trial_result(**overrides):
    base = {
        "nct_id": "NCT01234567",
        "title": "A Study of Drug X in NSCLC",
        "status": "RECRUITING",
        "phase": "PHASE2, PHASE3",
        "conditions": ["Non-Small Cell Lung Cancer"],
        "interventions": [{"type": "DRUG", "name": "Drug X", "description": "desc"}],
        "sponsor": "Big Pharma Inc",
        "locations": ["Hospital A, Boston, USA"],
        "enrollment": 250,
        "start_date": "2021-05",
        "completion_date": "2024-01",
        "brief_summary": "This study evaluates Drug X in NSCLC patients.",
        "url": "https://clinicaltrials.gov/study/NCT01234567",
    }
    base.update(overrides)
    return base


def test_clinical_trial_to_evidence_records_multi_field():
    trial = _trial_result()
    records = clinical_trial_to_evidence_records(trial)

    assert len(records) > 1
    for r in records:
        assert r.source_record_id == "NCT01234567"
        assert r.evidence_id == "nct:NCT01234567"

    types = {r.evidence_type for r in records}
    assert EvidenceType.TRIAL_STATUS in types
    assert EvidenceType.TRIAL_PHASE in types
    assert EvidenceType.TRIAL_FIELD in types

    status_record = next(r for r in records if r.evidence_type == EvidenceType.TRIAL_STATUS)
    assert status_record.content == "RECRUITING"
    assert status_record.provenance.field_path == "protocolSection.statusModule.overallStatus"

    phase_record = next(r for r in records if r.evidence_type == EvidenceType.TRIAL_PHASE)
    assert phase_record.content == "PHASE2, PHASE3"
    # phase is a joined/derived value in the real parser - no single fixed
    # field_path per contract Section 12.
    assert phase_record.provenance.field_path is None


def test_clinical_trial_to_evidence_records_field_path_absent_for_interventions():
    trial = _trial_result()
    records = clinical_trial_to_evidence_records(trial)
    intervention_records = [
        r for r in records if r.content.startswith("DRUG:") or r.content == "Drug X"
    ]
    assert intervention_records
    for r in intervention_records:
        assert r.provenance.field_path is None


def test_clinical_trial_to_evidence_records_skips_placeholder_only_fields():
    trial = _trial_result(
        status="Unknown",
        phase="N/A",
        sponsor="Unknown",
        enrollment="N/A",
        start_date="N/A",
        completion_date="N/A",
        brief_summary="No summary available",
        conditions=[],
        interventions=[],
    )
    records = clinical_trial_to_evidence_records(trial)
    assert records == []


def test_clinical_trial_to_evidence_records_rejects_missing_nct_id():
    trial = _trial_result(nct_id="")
    assert clinical_trial_to_evidence_records(trial) == []


def test_clinical_trial_brief_summary_truncation_marker():
    long_summary = "x" * 500  # exactly the parser's cutoff length
    trial = _trial_result(brief_summary=long_summary)
    records = clinical_trial_to_evidence_records(trial)
    summary_record = next(
        r for r in records if r.provenance.field_path == "protocolSection.descriptionModule.briefSummary"
    )
    assert summary_record.content.endswith("[TRUNCATED BY SOURCE PARSER]")


def test_clinical_trial_no_fabricated_ids_for_malformed_partial_input():
    partial = {"nct_id": "NCT99999999"}  # everything else missing
    records = clinical_trial_to_evidence_records(partial)
    for r in records:
        assert r.source_record_id == "NCT99999999"


# ===========================================================================
# ChEMBL - search_by_target / search_by_indication / get_drug_info
# ===========================================================================


def _molecule_result(**overrides):
    base = {
        "chembl_id": "CHEMBL941",
        "name": "Osimertinib",
        "molecule_type": "Small molecule",
        "molecular_weight": "499.6",
        "alogp": "3.6",
        "development_phase": "Approved",
        "max_phase": 4,
        "mechanism_of_action": "EGFR inhibitor",
        "mechanisms": [{"action": "EGFR inhibitor", "target": "EGFR"}],
        "url": "https://www.ebi.ac.uk/chembl/compound_report_card/CHEMBL941/",
    }
    base.update(overrides)
    return base


def _indication_result(**overrides):
    base = {
        "chembl_id": "CHEMBL941",
        "drug_name": "Osimertinib",
        "indication": "Non-small cell lung cancer",
        "max_phase": 4,
        "efo_term": "lung carcinoma",
    }
    base.update(overrides)
    return base


def test_chembl_molecule_result_with_mechanism_maps_to_target_relation():
    result = _molecule_result()
    evidence = chembl_target_or_indication_result_to_evidence(result, chembl_operation="search_by_target")
    assert evidence.evidence_type == EvidenceType.TARGET_RELATION
    assert evidence.content == "EGFR inhibitor"
    assert evidence.source_metadata.match_type is None
    assert evidence.source_metadata.mechanism_of_action == "EGFR inhibitor"


def test_chembl_molecule_result_without_mechanism_maps_to_compound_identity():
    result = _molecule_result(mechanism_of_action="Not available")
    evidence = chembl_target_or_indication_result_to_evidence(result, chembl_operation="get_drug_info")
    assert evidence.evidence_type == EvidenceType.COMPOUND_IDENTITY
    assert evidence.content == "Osimertinib"


def test_chembl_indication_result_maps_to_indication_type():
    result = _indication_result()
    evidence = chembl_target_or_indication_result_to_evidence(result, chembl_operation="search_by_indication")
    assert evidence.evidence_type == EvidenceType.INDICATION
    assert evidence.content == "Non-small cell lung cancer"
    assert evidence.source_record_id == "CHEMBL941"


def test_chembl_molecule_result_with_no_real_content_returns_none():
    # Well-formed record (has a real chembl_id), but both fields that could
    # supply faithful content are placeholder/absent - a legitimate "no
    # evidence here" case, not a caller error, so this must skip (None),
    # not raise - matching every other adapter's convention.
    result = _molecule_result(mechanism_of_action="Not available", name="No name")
    evidence = chembl_target_or_indication_result_to_evidence(result, chembl_operation="search_by_target")
    assert evidence is None


def test_chembl_result_rejects_missing_chembl_id():
    result = _molecule_result(chembl_id="")
    with pytest.raises(ValueError):
        chembl_target_or_indication_result_to_evidence(result, chembl_operation="search_by_target")


def test_chembl_result_rejects_unknown_operation():
    result = _molecule_result()
    with pytest.raises(ValueError):
        chembl_target_or_indication_result_to_evidence(result, chembl_operation="not_a_real_operation")


# ===========================================================================
# ChEMBL - resolve_compound_name
# ===========================================================================


def test_chembl_resolve_no_match_returns_none():
    result = {
        "input_name": "Zorblatinix-9X",
        "normalized_name": "Zorblatinix-9X",
        "matched_name": None,
        "chembl_id": None,
        "preferred_name": None,
        "match_type": "no_match",
        "candidates": [],
    }
    assert chembl_resolve_compound_name_to_evidence(result) is None


def test_chembl_resolve_ambiguous_match_returns_none_even_with_candidates():
    result = {
        "input_name": "Some Brand",
        "normalized_name": "some brand",
        "matched_name": None,
        "chembl_id": None,
        "preferred_name": None,
        "match_type": "ambiguous_match",
        "candidates": [
            {"chembl_id": "CHEMBL1", "preferred_name": "Compound A"},
            {"chembl_id": "CHEMBL2", "preferred_name": "Compound B"},
        ],
    }
    assert chembl_resolve_compound_name_to_evidence(result) is None


def test_chembl_resolve_success_preserves_match_type():
    result = {
        "input_name": "osimertinib",
        "normalized_name": "osimertinib",
        "matched_name": "Osimertinib",
        "chembl_id": "CHEMBL941",
        "preferred_name": "Osimertinib",
        "match_type": "exact_preferred_name",
        "candidates": [],
    }
    evidence = chembl_resolve_compound_name_to_evidence(result)
    assert evidence is not None
    assert evidence.source_record_id == "CHEMBL941"
    assert evidence.evidence_id == "chembl:CHEMBL941"
    assert evidence.evidence_type == EvidenceType.COMPOUND_IDENTITY
    assert evidence.source_metadata.match_type == "exact_preferred_name"


def test_chembl_resolve_fuzzy_match_preserves_match_type_and_id():
    result = {
        "input_name": "osimertnib",
        "normalized_name": "osimertnib",
        "matched_name": "Osimertinib",
        "chembl_id": "CHEMBL941",
        "preferred_name": "Osimertinib",
        "match_type": "fuzzy",
        "candidates": [{"chembl_id": "CHEMBL2", "preferred_name": "Other"}],
    }
    evidence = chembl_resolve_compound_name_to_evidence(result)
    assert evidence.source_metadata.match_type == "fuzzy"
    assert evidence.source_record_id == "CHEMBL941"


def test_chembl_resolve_never_fabricates_id_when_chembl_id_missing_despite_confirming_match_type():
    # Malformed/partial input: match_type looks "confirming" but chembl_id
    # is absent -- must still return None, never fabricate an id.
    result = {"match_type": "exact_preferred_name", "chembl_id": None, "preferred_name": "X"}
    assert chembl_resolve_compound_name_to_evidence(result) is None


# ===========================================================================
# Registry dispatch
# ===========================================================================


def test_registry_normalize_pubmed_rag_returns_list_of_one():
    doc = _FakeDocument(pmid="1", title="t", text="x", score=0.5, chunk_index=0, num_chunks=1)
    records = DEFAULT_ADAPTER_REGISTRY.normalize(
        SourceType.PUBMED, "rag", doc, corpus_index_version="v1"
    )
    assert len(records) == 1


def test_registry_normalize_pubmed_live_placeholder_returns_empty_list():
    result = _live_pubmed_result(abstract="No abstract available")
    records = DEFAULT_ADAPTER_REGISTRY.normalize(SourceType.PUBMED, "live", result)
    assert records == []


def test_registry_normalize_clinical_trials_returns_multiple():
    records = DEFAULT_ADAPTER_REGISTRY.normalize(
        SourceType.CLINICAL_TRIALS, "trial", _trial_result()
    )
    assert len(records) > 1


def test_registry_normalize_chembl_resolve_no_match_returns_empty_list():
    result = {"match_type": "no_match", "chembl_id": None}
    records = DEFAULT_ADAPTER_REGISTRY.normalize(
        SourceType.CHEMBL, "resolve_compound_name", result
    )
    assert records == []


def test_registry_unknown_key_raises_deterministic_error():
    with pytest.raises(EvidenceAdapterError):
        DEFAULT_ADAPTER_REGISTRY.normalize(SourceType.PUBMED, "not_a_real_subkey", {})


# ===========================================================================
# Cross-cutting: no fabricated IDs ever appear for malformed/partial input
# ===========================================================================


def test_no_fabricated_ids_across_all_adapters_for_empty_dicts():
    assert pubmed_live_result_to_evidence({}) is None
    assert clinical_trial_to_evidence_records({}) == []
    assert chembl_resolve_compound_name_to_evidence({}) is None
    with pytest.raises(ValueError):
        chembl_target_or_indication_result_to_evidence({}, chembl_operation="search_by_target")
