"""Tests for orchestration/query_compilers.py - Candidate C's source-specific
typed query compilers. Synthetic ResearchQuery inputs only (no benchmark
data needed here); confirms deterministic mapping and the abstain-don't-
guess rule. No network calls, no LLM calls."""

from nlu.schemas import (
    AmbiguityState,
    BiomedicalEntity,
    ConstraintSet,
    EntityType,
    NormalizationSystem,
    ResearchQuery,
)
from orchestration.models import (
    ChEMBLGetDrugInfoCall,
    ChEMBLSearchByIndicationCall,
    ChEMBLSearchByTargetCall,
    ClinicalTrialsSearchCall,
    PubMedSearchCall,
    ToolName,
)
from orchestration.query_compilers import (
    COMPILERS,
    compile_call,
    compile_chembl_call,
    compile_clinical_trials_call,
    compile_pubmed_call,
)


def _query(entities=None, constraints=None, ambiguous=False) -> ResearchQuery:
    return ResearchQuery(
        original_query="synthetic test query",
        normalized_query="synthetic test query",
        entities=entities or [],
        constraints=constraints or ConstraintSet(),
        ambiguity=AmbiguityState(is_ambiguous=ambiguous),
    )


def _entity(entity_type, surface_form, canonical_name=None, normalization_system=None, canonical_id=None):
    return BiomedicalEntity(
        entity_type=entity_type,
        surface_form=surface_form,
        canonical_name=canonical_name,
        normalization_system=normalization_system,
        canonical_id=canonical_id,
    )


# ---------------------------------------------------------------------------
# PubMed
# ---------------------------------------------------------------------------


def test_pubmed_joins_entity_names():
    q = _query(
        entities=[
            _entity(EntityType.COMPOUND, "pembrolizumab"),
            _entity(EntityType.DISEASE, "melanoma"),
        ]
    )
    call = compile_pubmed_call(q, "c1")
    assert isinstance(call, PubMedSearchCall)
    assert "pembrolizumab" in call.arguments.query
    assert "melanoma" in call.arguments.query


def test_pubmed_prefers_canonical_name_over_surface_form():
    q = _query(
        entities=[_entity(EntityType.COMPOUND, "asa", canonical_name="aspirin")]
    )
    call = compile_pubmed_call(q, "c1")
    assert call.arguments.query == "aspirin"


def test_pubmed_abstains_with_no_entities_or_terms():
    q = _query(entities=[])
    assert compile_pubmed_call(q, "c1") is None


def test_pubmed_includes_free_text_constraint_terms():
    q = _query(
        entities=[_entity(EntityType.DISEASE, "melanoma")],
        constraints=ConstraintSet(outcomes=["overall survival"]),
    )
    call = compile_pubmed_call(q, "c1")
    assert "overall survival" in call.arguments.query


def test_pubmed_deduplicates_terms_case_insensitively():
    q = _query(
        entities=[
            _entity(EntityType.DISEASE, "Melanoma"),
            _entity(EntityType.DISEASE, "melanoma"),
        ]
    )
    call = compile_pubmed_call(q, "c1")
    assert call.arguments.query.lower().count("melanoma") == 1


# ---------------------------------------------------------------------------
# ClinicalTrials
# ---------------------------------------------------------------------------


def test_clinical_trials_maps_condition_and_intervention():
    q = _query(
        entities=[
            _entity(EntityType.COMPOUND, "pembrolizumab"),
            _entity(EntityType.DISEASE, "melanoma"),
        ]
    )
    call = compile_clinical_trials_call(q, "c1")
    assert isinstance(call, ClinicalTrialsSearchCall)
    assert call.arguments.condition == "melanoma"
    assert call.arguments.intervention == "pembrolizumab"


def test_clinical_trials_intervention_entity_type_also_mapped():
    q = _query(
        entities=[
            _entity(EntityType.INTERVENTION, "JAK inhibitor"),
            _entity(EntityType.DISEASE, "myelofibrosis"),
        ]
    )
    call = compile_clinical_trials_call(q, "c1")
    assert call.arguments.intervention == "JAK inhibitor"
    assert call.arguments.condition == "myelofibrosis"


def test_clinical_trials_omits_invalid_status_instead_of_raising():
    # Mirrors benchmark case FL-001: raw constraint value not in
    # VALID_TRIAL_STATUSES must never reach ClinicalTrialsSearchArgs
    # verbatim - the compiler must omit the field, not crash or guess.
    q = _query(
        entities=[
            _entity(EntityType.COMPOUND, "pembrolizumab"),
            _entity(EntityType.DISEASE, "melanoma"),
        ],
        constraints=ConstraintSet(trial_statuses=["FULLY_ENROLLED"]),
    )
    call = compile_clinical_trials_call(q, "c1")
    assert call is not None
    # Schema default applies since the invalid raw value was never passed.
    assert call.arguments.status == "RECRUITING"


def test_clinical_trials_omits_invalid_phase_instead_of_raising():
    # Mirrors benchmark case FL-002: 'PHASE2.5' has no VALID_PHASES member.
    q = _query(
        entities=[
            _entity(EntityType.INTERVENTION, "JAK inhibitor"),
            _entity(EntityType.DISEASE, "myelofibrosis"),
        ],
        constraints=ConstraintSet(trial_phases=["PHASE2.5"]),
    )
    call = compile_clinical_trials_call(q, "c1")
    assert call is not None
    assert call.arguments.phase is None


def test_clinical_trials_accepts_valid_status_and_phase():
    q = _query(
        entities=[_entity(EntityType.DISEASE, "obesity")],
        constraints=ConstraintSet(trial_statuses=["RECRUITING"], trial_phases=["PHASE3"]),
    )
    call = compile_clinical_trials_call(q, "c1")
    assert call.arguments.status == "RECRUITING"
    assert call.arguments.phase == "PHASE3"


def test_clinical_trials_abstains_with_no_condition_or_intervention():
    q = _query(entities=[_entity(EntityType.TARGET, "EGFR")])
    assert compile_clinical_trials_call(q, "c1") is None


def test_clinical_trials_maps_geography_to_country():
    q = _query(
        entities=[_entity(EntityType.DISEASE, "obesity")],
        constraints=ConstraintSet(geography=["Germany"]),
    )
    call = compile_clinical_trials_call(q, "c1")
    assert call.arguments.country == "Germany"


# ---------------------------------------------------------------------------
# ChEMBL
# ---------------------------------------------------------------------------


def test_chembl_target_entity_selects_search_by_target():
    q = _query(entities=[_entity(EntityType.TARGET, "EGFR")])
    call = compile_chembl_call(q, "c1")
    assert isinstance(call, ChEMBLSearchByTargetCall)
    assert call.arguments.target_name == "EGFR"


def test_chembl_disease_entity_selects_search_by_indication():
    q = _query(entities=[_entity(EntityType.DISEASE, "type 2 diabetes")])
    call = compile_chembl_call(q, "c1")
    assert isinstance(call, ChEMBLSearchByIndicationCall)
    assert call.arguments.disease == "type 2 diabetes"


def test_chembl_canonical_id_selects_get_drug_info_over_disease():
    # Mirrors benchmark case MS-012: a canonical ChEMBL ID takes priority
    # over an accompanying disease entity with no id of its own.
    q = _query(
        entities=[
            _entity(
                EntityType.COMPOUND,
                "imatinib",
                canonical_name="imatinib",
                normalization_system=NormalizationSystem.CHEMBL,
                canonical_id="CHEMBL941",
            ),
            _entity(EntityType.DISEASE, "chronic myeloid leukemia"),
        ]
    )
    call = compile_chembl_call(q, "c1")
    assert isinstance(call, ChEMBLGetDrugInfoCall)
    assert call.arguments.chembl_id == "CHEMBL941"


def test_chembl_target_entity_takes_priority_over_disease():
    q = _query(
        entities=[
            _entity(EntityType.COMPOUND, "trastuzumab"),
            _entity(EntityType.DISEASE, "HER2 breast cancer"),
            _entity(EntityType.TARGET, "HER2"),
        ]
    )
    call = compile_chembl_call(q, "c1")
    assert isinstance(call, ChEMBLSearchByTargetCall)
    assert call.arguments.target_name == "HER2"


def test_chembl_abstains_on_bare_compound_name_with_no_id_target_or_disease():
    # Mirrors benchmark case FL-004: a drug name alone maps to none of
    # ChEMBL's three registered operations without guessing.
    q = _query(entities=[_entity(EntityType.COMPOUND, "imatinib")])
    assert compile_chembl_call(q, "c1") is None


def test_chembl_abstains_with_no_entities():
    q = _query(entities=[])
    assert compile_chembl_call(q, "c1") is None


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------


def test_compilers_dict_covers_all_tool_names():
    assert set(COMPILERS.keys()) == {ToolName.PUBMED, ToolName.CLINICAL_TRIALS, ToolName.CHEMBL}


def test_compile_call_dispatches_to_the_right_compiler():
    q = _query(entities=[_entity(EntityType.TARGET, "PCSK9")])
    call = compile_call(ToolName.CHEMBL, q, "c1")
    assert isinstance(call, ChEMBLSearchByTargetCall)
