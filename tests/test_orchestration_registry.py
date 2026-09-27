"""Tests for orchestration/registry.py - registry lookup, validate_call's
lookup-then-validate boundary, and select_sources' deterministic behavior.
Uses only the module-level DEFAULT_REGISTRY (statically built from the real
tool clients at import time, no network calls) and synthetic ResearchQuery
instances."""

import pytest

from nlu.schemas import (
    AmbiguityState,
    EvidenceSourceType,
    ResearchQuery,
)
from orchestration.models import (
    ChEMBLGetDrugInfoArgs,
    ChEMBLGetDrugInfoCall,
    ChEMBLSearchByIndicationArgs,
    ChEMBLSearchByIndicationCall,
    ChEMBLSearchByTargetArgs,
    ChEMBLSearchByTargetCall,
    ClinicalTrialsSearchArgs,
    ClinicalTrialsSearchCall,
    PubMedSearchArgs,
    PubMedSearchCall,
    ToolName,
)
from orchestration.registry import DEFAULT_REGISTRY, RegistryError, ToolRegistry
from orchestration.source_selection import select_sources


# ---------------------------------------------------------------------------
# Registry lookup
# ---------------------------------------------------------------------------


def test_registry_has_exactly_six_registered_pairs():
    # Was 5 pairs prior to Phase 4's ChEMBL name-resolution work
    # (docs/v2/PHASE4_CHEMBL_RESOLUTION.md), which added
    # (ToolName.CHEMBL, "resolve_compound_name") as the 6th registered pair.
    pairs = DEFAULT_REGISTRY.registered_pairs()
    assert len(pairs) == 6
    assert (ToolName.PUBMED, "search_pubmed") in pairs
    assert (ToolName.CLINICAL_TRIALS, "search_trials") in pairs
    assert (ToolName.CHEMBL, "search_by_target") in pairs
    assert (ToolName.CHEMBL, "search_by_indication") in pairs
    assert (ToolName.CHEMBL, "get_drug_info") in pairs
    assert (ToolName.CHEMBL, "resolve_compound_name") in pairs


def test_lookup_unregistered_pair_returns_none_not_crash():
    result = DEFAULT_REGISTRY.lookup(ToolName.PUBMED, "search_pubchem")
    assert result is None


def test_require_unregistered_pair_raises_typed_error():
    with pytest.raises(RegistryError) as exc_info:
        DEFAULT_REGISTRY.require(ToolName.PUBMED, "search_pubchem")
    assert exc_info.value.category.value == "unregistered_tool"


def test_fresh_registry_has_no_bindings_until_registered():
    empty = ToolRegistry()
    assert empty.registered_pairs() == ()
    assert empty.lookup(ToolName.PUBMED, "search_pubmed") is None


# ---------------------------------------------------------------------------
# validate_call: registry lookup -> argument schema validation, no execution
# ---------------------------------------------------------------------------


def test_validate_call_accepts_valid_pubmed_call():
    call = PubMedSearchCall(call_id="c1", arguments=PubMedSearchArgs(query="EGFR"))
    validated = DEFAULT_REGISTRY.validate_call(call)
    assert validated is call


def test_validate_call_accepts_valid_clinical_trials_call():
    call = ClinicalTrialsSearchCall(
        call_id="c2",
        arguments=ClinicalTrialsSearchArgs(condition="lung cancer", status="RECRUITING"),
    )
    validated = DEFAULT_REGISTRY.validate_call(call)
    assert validated.arguments.condition == "lung cancer"


def test_validate_call_accepts_all_three_chembl_operations():
    calls = [
        ChEMBLSearchByTargetCall(
            call_id="c3", arguments=ChEMBLSearchByTargetArgs(target_name="EGFR")
        ),
        ChEMBLSearchByIndicationCall(
            call_id="c4", arguments=ChEMBLSearchByIndicationArgs(disease="lung cancer")
        ),
        ChEMBLGetDrugInfoCall(
            call_id="c5", arguments=ChEMBLGetDrugInfoArgs(chembl_id="CHEMBL941")
        ),
    ]
    for call in calls:
        assert DEFAULT_REGISTRY.validate_call(call) is call


def test_validate_call_never_executes_anything(monkeypatch):
    # Sanity guard: validate_call must not touch the network / bound
    # execute_fn. Patch the real bound method's underlying instance
    # (binding.execute_fn is a bound method of the singleton PubMedTool
    # backing the registry - ToolBinding itself is a frozen dataclass, so
    # patch the instance method it is bound to instead) and assert it is
    # never called.
    binding = DEFAULT_REGISTRY.require(ToolName.PUBMED, "search_pubmed")
    pubmed_instance = binding.execute_fn.__self__
    called = {"count": 0}

    def _boom(*args, **kwargs):
        called["count"] += 1
        raise AssertionError("search_pubmed must not be invoked by validate_call")

    monkeypatch.setattr(pubmed_instance, "search_pubmed", _boom)

    call = PubMedSearchCall(call_id="c1", arguments=PubMedSearchArgs(query="EGFR"))
    DEFAULT_REGISTRY.validate_call(call)
    assert called["count"] == 0


def test_get_execution_fn_for_unregistered_pair_raises():
    with pytest.raises(RegistryError):
        DEFAULT_REGISTRY.get_execution_fn(ToolName.PUBMED, "not_a_real_operation")


# ---------------------------------------------------------------------------
# select_sources - deterministic source selection from ResearchQuery
# ---------------------------------------------------------------------------


def _make_query(requested_evidence_types, is_ambiguous=False):
    return ResearchQuery(
        original_query="does drug X treat disease Y",
        normalized_query="does drug x treat disease y",
        requested_evidence_types=requested_evidence_types,
        ambiguity=AmbiguityState(is_ambiguous=is_ambiguous),
    )


def test_select_sources_empty_requested_evidence_types_returns_empty():
    query = _make_query([])
    assert select_sources(query) == []


def test_select_sources_single_source():
    query = _make_query([EvidenceSourceType.PUBMED])
    assert select_sources(query) == [ToolName.PUBMED]


def test_select_sources_multiple_sources_preserves_order_and_dedupes():
    query = _make_query(
        [
            EvidenceSourceType.CHEMBL,
            EvidenceSourceType.PUBMED,
            EvidenceSourceType.CHEMBL,  # duplicate, should be deduped
        ]
    )
    assert select_sources(query) == [ToolName.CHEMBL, ToolName.PUBMED]


def test_select_sources_all_three():
    query = _make_query(
        [
            EvidenceSourceType.PUBMED,
            EvidenceSourceType.CLINICALTRIALS,
            EvidenceSourceType.CHEMBL,
        ]
    )
    assert select_sources(query) == [
        ToolName.PUBMED,
        ToolName.CLINICAL_TRIALS,
        ToolName.CHEMBL,
    ]


def test_select_sources_does_not_default_to_all_three_on_empty_even_if_ambiguous():
    # Empty signal + ambiguous query: still returns [] (insufficient
    # signal), not an unconditional all-three fallback - callers decide
    # what to do with an ambiguous query separately via query.ambiguity.
    query = _make_query([], is_ambiguous=True)
    assert select_sources(query) == []
