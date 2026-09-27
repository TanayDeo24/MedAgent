"""Offline tests for grounding_eval/deterministic.py (Candidate A / the
numeric precheck reused by Candidate C). No network/LLM calls."""

from evidence.models import (
    ChemblEvidenceMetadata,
    ClinicalTrialEvidenceMetadata,
    ContentFormat,
    Evidence,
    EvidenceType,
    Provenance,
    SourceType,
    make_evidence_id,
    make_source_url,
)
from grounding_eval.deterministic import (
    judge_claim_deterministic,
    judge_claim_deterministic_v2,
    numeric_mismatch_check,
)
from grounding_eval.models import CitationRelation, SupportLabel


def _trial_evidence(nct_id="NCT1", evidence_type=EvidenceType.TRIAL_STATUS, content="RECRUITING"):
    return Evidence(
        evidence_id=make_evidence_id(SourceType.CLINICAL_TRIALS, nct_id),
        source_type=SourceType.CLINICAL_TRIALS, source_record_id=nct_id,
        source_url=make_source_url(SourceType.CLINICAL_TRIALS, nct_id),
        evidence_type=evidence_type, content=content, content_format=ContentFormat.FIELD_VALUE,
        source_metadata=ClinicalTrialEvidenceMetadata(status="RECRUITING", phase="PHASE2"),
        provenance=Provenance(retrieval_method="live_api"),
    )


def _chembl_evidence(chembl_id="CHEMBL1", content="Compound X", max_phase="4.0"):
    return Evidence(
        evidence_id=make_evidence_id(SourceType.CHEMBL, chembl_id),
        source_type=SourceType.CHEMBL, source_record_id=chembl_id,
        source_url=make_source_url(SourceType.CHEMBL, chembl_id),
        evidence_type=EvidenceType.COMPOUND_IDENTITY, content=content,
        content_format=ContentFormat.FIELD_VALUE,
        source_metadata=ChemblEvidenceMetadata(max_phase=max_phase),
        provenance=Provenance(retrieval_method="get_drug_info"),
    )


def test_valid_numeric_match():
    ev = _chembl_evidence(max_phase="4.0")
    assert numeric_mismatch_check("The compound reached Phase 4", ev) is False


def test_numeric_mismatch_detected():
    ev = _chembl_evidence(max_phase="4.0")
    assert numeric_mismatch_check("The compound reached Phase 1", ev) is True


def test_no_number_in_claim_returns_none():
    ev = _chembl_evidence()
    assert numeric_mismatch_check("The compound is a small molecule", ev) is None


def test_identifier_digits_not_treated_as_numeric_claims():
    # Regression: NCT/ChEMBL identifiers embedded in claim text must not be
    # extracted as "claimed numeric facts" (real defect found in Candidate C,
    # see artifacts/v2/phase7_failure_analysis.json finding F2).
    ev = _trial_evidence(content="RECRUITING")
    result = numeric_mismatch_check("The trial NCT03535740 is recruiting", ev)
    assert result is None  # "03535740" must not be extracted as a bare number


def test_valid_entity_deterministic_judgment():
    ev = _chembl_evidence(chembl_id="CHEMBL941", content="IMATINIB")
    judgment = judge_claim_deterministic("c1", "Imatinib is CHEMBL941", [ev.evidence_id], {ev.evidence_id: ev})
    assert judgment.citation_judgments[0].relation in (CitationRelation.SUPPORTS, CitationRelation.PARTIAL_SUPPORT)


def test_wrong_entity_numeric_mismatch_contradicts():
    ev = _chembl_evidence(max_phase="4.0")
    judgment = judge_claim_deterministic("c1", "reached Phase 1", [ev.evidence_id], {ev.evidence_id: ev})
    assert judgment.support_label == SupportLabel.CONTRADICTED


def test_missing_citation_no_evidence_ids_is_unsupported():
    judgment = judge_claim_deterministic("c1", "some claim", [], {})
    assert judgment.support_label == SupportLabel.UNSUPPORTED


# --- Phase-7 hardening pass: shared numeric utility regression tests ---
# (findings F2/F4 - Candidate C's residual "PHASE2 glued to letters" defect,
# now fixed in the shared _numbers_in/_phases_in utility both v1 and v2 use)


def test_phase_equivalence_glued_vs_spaced():
    ev = _trial_evidence(content="Status update.")  # metadata phase="PHASE2"
    assert numeric_mismatch_check("This is a Phase 2 trial", ev) is False


def test_phase_equivalence_roman_numeral():
    ev = _trial_evidence(content="Status update.")  # metadata phase="PHASE2"
    assert numeric_mismatch_check("This is a phase II trial", ev) is False


def test_phase_mismatch_still_detected():
    ev = _trial_evidence(content="Status update.")  # metadata phase="PHASE2"
    assert numeric_mismatch_check("This is a Phase 3 trial", ev) is True


def test_mutation_code_digits_not_treated_as_numeric_claims():
    ev = _trial_evidence(content="Resistance to G1269A ALK mutation observed.")
    result = numeric_mismatch_check("The evidence discusses the G1269A mutation", ev)
    assert result is None  # "1269" must not be extracted as a bare number


def test_pmid_digits_not_treated_as_numeric_claims():
    ev = _chembl_evidence()
    result = numeric_mismatch_check("See PMID:29119148 for details", ev)
    assert result is None


def test_percentage_normalization():
    ev = _chembl_evidence(content="Response rate was 45%")
    assert numeric_mismatch_check("The response rate was 45", ev) is False


def test_decimal_numeric_match():
    ev = _chembl_evidence(max_phase="4.0")
    assert numeric_mismatch_check("Phase 4.0 compound", ev) is False


# --- Candidate A v2 (hardened baseline) ---


def test_v2_entity_mismatch_wrong_identifier():
    ev = _chembl_evidence(chembl_id="CHEMBL941", content="Imatinib")
    judgment = judge_claim_deterministic_v2(
        "c1", "This compound is CHEMBL999, a different molecule", [ev.evidence_id], {ev.evidence_id: ev}
    )
    assert judgment.citation_judgments[0].relation == CitationRelation.IRRELEVANT


def test_v2_structured_status_mismatch_contradicts():
    ev = _trial_evidence(content="Trial ongoing.")  # status=RECRUITING
    judgment = judge_claim_deterministic_v2(
        "c1", "This trial is COMPLETED", [ev.evidence_id], {ev.evidence_id: ev}
    )
    assert judgment.support_label == SupportLabel.CONTRADICTED


def test_v2_structured_status_match_supports():
    ev = _trial_evidence(content="Trial ongoing.")  # status=RECRUITING
    judgment = judge_claim_deterministic_v2(
        "c1", "This trial is RECRUITING", [ev.evidence_id], {ev.evidence_id: ev}
    )
    assert judgment.citation_judgments[0].relation == CitationRelation.SUPPORTS


def test_v2_numeric_mismatch_still_contradicts():
    ev = _chembl_evidence(max_phase="4.0")
    judgment = judge_claim_deterministic_v2("c1", "reached Phase 1", [ev.evidence_id], {ev.evidence_id: ev})
    assert judgment.support_label == SupportLabel.CONTRADICTED
