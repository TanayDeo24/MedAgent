"""Unit tests for the Phase 2 Biomedical NLU package (nlu/, evaluation/v2/).

Covers: schema validation, intent taxonomy, entity-extraction parsing,
normalization (including correct abstention), unknown-entity/ambiguous-
abbreviation handling, multi-entity queries, constraint extraction,
malformed structured-output handling, fabricated-ID prevention, the
research_plan adapter's backward compatibility, the benchmark loader, the
metric implementations, and split-leakage checks.

No live LLM/API calls are made in this file - all extractor-level tests
mock config.llm_config.get_llm, matching tests/test_nodes.py's convention.
"""

import json
from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from nlu.schemas import (
    AmbiguityState,
    BiomedicalEntity,
    ConstraintSet,
    EntityType,
    NormalizationSystem,
    ResearchQuery,
    SCHEMA_VERSION,
)
from nlu.taxonomy import IntentClass, VALID_INTENT_VALUES
from nlu.normalization import (
    normalize_entity,
    normalization_coverage,
    canonicalize_trial_phase,
    canonicalize_trial_status,
)
from nlu.extractor import extract_candidate_a, extract_candidate_b
from nlu import to_legacy_research_plan
from evaluation.v2.nlu_metrics import (
    entity_prf,
    normalization_accuracy_at_1,
    intent_metrics,
    constraint_prf,
    source_set_prf,
    aggregate_micro_macro,
)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def test_research_query_minimal_valid():
    rq = ResearchQuery(original_query="What is EGFR?", normalized_query="What is EGFR?")
    assert rq.schema_version == SCHEMA_VERSION
    assert rq.entities == []
    assert rq.intent == []


def test_biomedical_entity_defaults_to_unnormalized():
    e = BiomedicalEntity(entity_type=EntityType.DISEASE, surface_form="lung cancer")
    assert e.canonical_id is None
    assert e.canonical_name is None
    assert e.normalization_system is None


def test_biomedical_entity_semantic_roles_default_empty():
    """Closure item 8: semantic_roles defaults to [] (no ambiguity claimed)
    and does not affect the required, single-valued entity_type field."""
    e = BiomedicalEntity(entity_type=EntityType.GENE, surface_form="EGFR")
    assert e.semantic_roles == []
    assert e.entity_type == EntityType.GENE


def test_biomedical_entity_semantic_roles_multi_role():
    """A gene/protein/target ambiguous mention can carry multiple
    legitimate alternate roles alongside its single primary entity_type."""
    e = BiomedicalEntity(
        entity_type=EntityType.GENE,
        surface_form="EGFR",
        semantic_roles=[EntityType.PROTEIN, EntityType.TARGET],
    )
    assert e.entity_type == EntityType.GENE
    assert set(e.semantic_roles) == {EntityType.PROTEIN, EntityType.TARGET}


def test_biomedical_entity_rejects_id_without_system():
    """Structural guard: canonical_id must never be set without naming its
    normalization_system - this is the schema-level fabricated-ID guard."""
    with pytest.raises(ValidationError):
        BiomedicalEntity(
            entity_type=EntityType.DISEASE,
            surface_form="lung cancer",
            canonical_id="MeSH:D008175",
            normalization_system=None,
        )


def test_biomedical_entity_accepts_id_with_system():
    e = BiomedicalEntity(
        entity_type=EntityType.DISEASE,
        surface_form="melanoma",
        canonical_name="Melanoma",
        canonical_id="MeSH:D008545",
        normalization_system=NormalizationSystem.MESH,
    )
    assert e.canonical_id == "MeSH:D008545"


def test_research_query_rejects_unknown_intent():
    with pytest.raises(ValidationError):
        ResearchQuery(
            original_query="x", normalized_query="x",
            intent=["Z_not_a_real_class"],
        )


def test_constraint_set_as_pairs():
    cs = ConstraintSet(trial_phases=["PHASE2", "PHASE3"], population=["adults"])
    pairs = cs.as_pairs()
    assert ("trial_phases", "PHASE2") in pairs
    assert ("trial_phases", "PHASE3") in pairs
    assert ("population", "adults") in pairs
    assert len(pairs) == 3


def test_ambiguity_state_default_not_ambiguous():
    a = AmbiguityState()
    assert a.is_ambiguous is False
    assert a.candidate_interpretations == []


# ---------------------------------------------------------------------------
# Intent taxonomy
# ---------------------------------------------------------------------------

def test_taxonomy_has_eight_query_time_classes():
    """Phase 2 CLOSURE (item 5): H_insufficient_evidence was removed from
    the query-time IntentClass enum - PRODUCT_CONTRACT.md defines H as a
    post-retrieval evidence-sufficiency outcome ("any of the above where
    sources return nothing usable"), not something determinable from query
    text alone, which is all an NLU/intent-classification stage has access
    to. See nlu/taxonomy.py's IntentClass docstring for the full rationale.
    8 query-time classes remain: A-G, I."""
    assert len(VALID_INTENT_VALUES) == 8


def test_taxonomy_values_match_product_contract_letters():
    prefixes = {v.split("_")[0] for v in VALID_INTENT_VALUES}
    assert prefixes == set("ABCDEFGI")  # H intentionally excluded, see above


def test_h_insufficient_evidence_not_a_query_time_class():
    """H must never be predictable/accepted as a query-time intent - it is
    a downstream evidence-state judgment, not an NLU output."""
    assert "H_insufficient_evidence" not in VALID_INTENT_VALUES
    assert not hasattr(IntentClass, "H_INSUFFICIENT_EVIDENCE")


# ---------------------------------------------------------------------------
# Trial phase / status canonicalization (Phase 2 closure item 7)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("surface,expected", [
    ("Phase 1", ["PHASE1"]),
    ("Phase I", ["PHASE1"]),
    ("Phase 1/2", ["PHASE1", "PHASE2"]),
    ("Phase I/II", ["PHASE1", "PHASE2"]),
    ("Phase II/2", ["PHASE2"]),
    ("Phase II/III", ["PHASE2", "PHASE3"]),
    ("Phase 2/3", ["PHASE2", "PHASE3"]),
    ("Phase III/3", ["PHASE3"]),
    ("Phase IV/4", ["PHASE4"]),
    ("Early Phase 1", ["EARLY_PHASE1"]),
    ("Not Applicable", ["NOT_APPLICABLE"]),
    ("N/A", ["NOT_APPLICABLE"]),
    ("PHASE2", ["PHASE2"]),  # already-canonical passthrough
])
def test_canonicalize_trial_phase(surface, expected):
    assert canonicalize_trial_phase(surface) == expected


def test_canonicalize_trial_phase_combined_not_collapsed():
    """A combined phase like 'Phase I/II' must preserve BOTH phases, never
    collapse to just one (closure item 7's explicit requirement)."""
    result = canonicalize_trial_phase("Phase I/II")
    assert "PHASE1" in result and "PHASE2" in result
    assert len(result) == 2


def test_canonicalize_trial_phase_unrecognized_abstains():
    assert canonicalize_trial_phase("some random text") == []
    assert canonicalize_trial_phase("") == []


@pytest.mark.parametrize("surface,expected", [
    ("Recruiting", "RECRUITING"),
    ("recruiting", "RECRUITING"),
    ("Active, not recruiting", "ACTIVE_NOT_RECRUITING"),
    ("Completed", "COMPLETED"),
    ("Terminated", "TERMINATED"),
    ("Withdrawn", "WITHDRAWN"),
    ("COMPLETED", "COMPLETED"),  # already-canonical passthrough
])
def test_canonicalize_trial_status(surface, expected):
    assert canonicalize_trial_status(surface) == expected


def test_canonicalize_trial_status_unrecognized_abstains():
    assert canonicalize_trial_status("gibberish") is None
    assert canonicalize_trial_status("") is None


# ---------------------------------------------------------------------------
# Normalization - including correct abstention on ambiguous abbreviations
# ---------------------------------------------------------------------------

def test_normalization_resolves_known_disease():
    result = normalize_entity("melanoma", "disease")
    assert result.matched is True
    assert result.canonical_id == "MeSH:D008545"
    assert result.normalization_system == NormalizationSystem.MESH


def test_normalization_resolves_known_gene_case_insensitive():
    result = normalize_entity("egfr", "gene")
    assert result.matched is True
    assert result.canonical_id == "HGNC:3236"


def test_normalization_resolves_known_compound():
    result = normalize_entity("erlotinib", "compound")
    assert result.matched is True
    assert result.canonical_id == "ChEMBL:CHEMBL553"


def test_normalization_abstains_on_ambiguous_abbreviation_ms():
    """'MS' must NOT auto-resolve to 'multiple sclerosis' without
    contextual support - task item 12's explicit example."""
    result = normalize_entity("MS", "disease")
    assert result.matched is False
    assert result.canonical_id is None


def test_normalization_abstains_on_ambiguous_abbreviation_ra():
    result = normalize_entity("RA", "disease")
    assert result.matched is False
    assert result.canonical_id is None


def test_normalization_abstains_on_unknown_entity():
    result = normalize_entity("some completely unknown compound xyz123", "compound")
    assert result.matched is False
    assert result.canonical_name is None
    assert result.canonical_id is None
    assert result.normalization_system is None


def test_normalization_abstains_on_unsupported_entity_type():
    result = normalize_entity("anything", "intervention_type_not_covered")
    assert result.matched is False


def test_normalization_coverage_nonzero():
    cov = normalization_coverage()
    assert cov["disease"] >= 8
    assert cov["gene"] >= 8
    assert cov["compound"] >= 8


# ---------------------------------------------------------------------------
# Entity extraction parsing (Candidate A and B), mocked LLM - malformed
# output handling, multi-entity, fabricated-ID prevention
# ---------------------------------------------------------------------------

@patch("nlu.extractor.get_llm")
def test_candidate_a_parses_valid_response(mock_get_llm):
    mock_llm = Mock()
    mock_llm.invoke.return_value = Mock(content=json.dumps({
        "drug_targets": ["EGFR"],
        "diseases": ["lung cancer"],
        "compounds": ["erlotinib"],
        "query_type": "drug_target_search",
        "key_constraints": [],
        "extracted_keywords": ["EGFR", "lung cancer"],
        "confidence": 0.8,
    }))
    mock_get_llm.return_value = mock_llm

    result = extract_candidate_a("Find EGFR inhibitors for lung cancer")
    assert result.schema_valid is True
    assert result.architecture == "candidate_a_baseline"
    rq = result.research_query
    assert len(rq.entities) == 3
    types = {e.entity_type for e in rq.entities}
    assert EntityType.TARGET in types
    assert EntityType.DISEASE in types
    assert EntityType.COMPOUND in types
    # Candidate A has no normalization mechanism - every entity must abstain.
    assert all(e.canonical_id is None for e in rq.entities)


@patch("nlu.extractor.get_llm")
def test_candidate_a_malformed_json_reported_as_schema_invalid(mock_get_llm):
    mock_llm = Mock()
    mock_llm.invoke.return_value = Mock(content="this is not { valid json at all")
    mock_get_llm.return_value = mock_llm

    result = extract_candidate_a("some query")
    assert result.schema_valid is False
    assert result.research_query is None
    assert result.parse_error is not None


@patch("nlu.extractor.get_llm")
def test_candidate_b_multi_entity_with_normalization(mock_get_llm):
    mock_llm = Mock()
    mock_llm.invoke.return_value = Mock(content=json.dumps({
        "intent": ["F_mechanism"],
        "intent_confidence": 0.9,
        "entities": [
            {"entity_type": "compound", "surface_form": "erlotinib"},
            {"entity_type": "target", "surface_form": "EGFR"},
            {"entity_type": "disease", "surface_form": "a totally novel undiscovered syndrome"},
        ],
        "constraints": {"trial_phases": ["PHASE3"], "trial_statuses": [], "population": [],
                         "age": [], "geography": [], "temporal": [], "study_type": [], "outcomes": []},
        "requested_evidence_types": ["pubmed", "chembl"],
        "ambiguity": {"is_ambiguous": False, "ambiguity_reason": None, "candidate_interpretations": []},
        "extraction_confidence": 0.85,
    }))
    mock_get_llm.return_value = mock_llm

    result = extract_candidate_b("What is the mechanism of erlotinib against EGFR in a totally novel undiscovered syndrome?")
    assert result.schema_valid is True
    rq = result.research_query
    assert len(rq.entities) == 3

    by_surface = {e.surface_form: e for e in rq.entities}
    # Known entities normalize correctly.
    assert by_surface["erlotinib"].canonical_id == "ChEMBL:CHEMBL553"
    assert by_surface["EGFR"].canonical_id == "HGNC:3236"
    # Unknown entity correctly abstains - no fabricated ID.
    assert by_surface["a totally novel undiscovered syndrome"].canonical_id is None
    assert by_surface["a totally novel undiscovered syndrome"].canonical_name is None


@patch("nlu.extractor.get_llm")
def test_candidate_b_never_fabricates_id_for_llm_proposed_field(mock_get_llm):
    """Even if the LLM's raw output included a canonical_id-shaped field
    (it shouldn't, per the prompt, but a broken/adversarial model response
    might), the coercion path only ever reads entity_type/surface_form -
    any canonical_id must come exclusively from nlu/normalization.py."""
    mock_llm = Mock()
    mock_llm.invoke.return_value = Mock(content=json.dumps({
        "intent": ["C_compound_target"],
        "intent_confidence": 0.5,
        "entities": [
            {"entity_type": "compound", "surface_form": "unknownium",
             "canonical_id": "ChEMBL:CHEMBL999999999", "canonical_name": "MADE UP NAME"},
        ],
        "constraints": {},
        "requested_evidence_types": ["chembl"],
        "ambiguity": {"is_ambiguous": False},
        "extraction_confidence": 0.5,
    }))
    mock_get_llm.return_value = mock_llm

    result = extract_candidate_b("Tell me about unknownium")
    assert result.schema_valid is True
    entity = result.research_query.entities[0]
    assert entity.canonical_id is None  # the LLM-proposed fabricated ID must be ignored
    assert entity.canonical_name is None


@patch("nlu.extractor.get_llm")
def test_candidate_b_malformed_output_is_schema_invalid_not_silently_defaulted(mock_get_llm):
    """A malformed/unparseable response must be reported as a genuine
    failure (schema_valid=False) - never silently converted into an empty
    'successful' ResearchQuery, which would hide the failure from
    schema_parse_success_rate."""
    mock_llm = Mock()
    mock_llm.invoke.return_value = Mock(content="I cannot help with that request.")
    mock_get_llm.return_value = mock_llm

    result = extract_candidate_b("some query")
    assert result.schema_valid is False
    assert result.research_query is None
    assert result.llm_calls == 2  # confirms the bounded retry actually ran


@patch("nlu.extractor.get_llm")
def test_candidate_b_empty_response_recovers_on_retry(mock_get_llm):
    """Phase 2 closure item 9: a genuinely empty response.content (the
    exact failure mode behind 2 of the 3 original test-split failures)
    must trigger one identical retry, and a subsequent good response must
    be used - not treated as a permanent failure."""
    good = json.dumps({
        "intent": ["A_literature_evidence"], "intent_confidence": 0.9,
        "entities": [{"entity_type": "disease", "surface_form": "melanoma"}],
        "constraints": {}, "requested_evidence_types": ["pubmed"],
        "ambiguity": {"is_ambiguous": False}, "extraction_confidence": 0.9,
    })
    mock_llm = Mock()
    mock_llm.invoke.side_effect = [Mock(content=""), Mock(content=good)]
    mock_get_llm.return_value = mock_llm

    result = extract_candidate_b("What does research say about melanoma?")
    assert result.schema_valid is True
    assert result.research_query is not None
    assert result.llm_calls == 2


@patch("nlu.extractor.get_llm")
def test_candidate_b_empty_response_exhausted_is_explicit_nlu_failure(mock_get_llm):
    """If BOTH the initial attempt and the retry return empty content, the
    result must be an explicit, clearly-labeled failure (NLU_FAILURE) -
    never a fabricated/defaulted ResearchQuery."""
    mock_llm = Mock()
    mock_llm.invoke.side_effect = [Mock(content=""), Mock(content="")]
    mock_get_llm.return_value = mock_llm

    result = extract_candidate_b("What does research say about melanoma?")
    assert result.schema_valid is False
    assert result.research_query is None
    assert result.llm_calls == 2
    assert "NLU_FAILURE" in result.parse_error


@patch("nlu.extractor.get_llm")
def test_candidate_b_unknown_enum_values_rejected_not_silently_kept(mock_get_llm):
    """An invalid intent value or entity_type from a misbehaving LLM
    response must be dropped rather than let through as an unvalidated
    string - the coercion helpers filter these explicitly."""
    mock_llm = Mock()
    mock_llm.invoke.return_value = Mock(content=json.dumps({
        "intent": ["Z_totally_made_up_class", "A_literature_evidence"],
        "intent_confidence": 0.5,
        "entities": [
            {"entity_type": "not_a_real_type", "surface_form": "whatever"},
            {"entity_type": "disease", "surface_form": "melanoma"},
        ],
        "constraints": {},
        "requested_evidence_types": ["not_a_real_source", "pubmed"],
        "ambiguity": {"is_ambiguous": False},
        "extraction_confidence": 0.5,
    }))
    mock_get_llm.return_value = mock_llm

    result = extract_candidate_b("melanoma query")
    assert result.schema_valid is True
    rq = result.research_query
    assert rq.intent == [IntentClass.A_LITERATURE_EVIDENCE]
    assert len(rq.entities) == 1
    assert rq.entities[0].surface_form == "melanoma"
    assert [s.value for s in rq.requested_evidence_types] == ["pubmed"]


@patch("nlu.extractor.get_llm")
def test_candidate_a_llm_exception_is_schema_invalid(mock_get_llm):
    mock_llm = Mock()
    mock_llm.invoke.side_effect = RuntimeError("simulated API failure")
    mock_get_llm.return_value = mock_llm

    result = extract_candidate_a("some query")
    assert result.schema_valid is False
    assert "simulated API failure" in result.parse_error


# ---------------------------------------------------------------------------
# research_plan adapter backward compatibility
# ---------------------------------------------------------------------------

def test_adapter_produces_old_shape_keys():
    rq = ResearchQuery(
        original_query="Find EGFR inhibitors for lung cancer",
        normalized_query="Find EGFR inhibitors for lung cancer",
        intent=[IntentClass.C_COMPOUND_TARGET],
        entities=[
            BiomedicalEntity(entity_type=EntityType.TARGET, surface_form="EGFR"),
            BiomedicalEntity(entity_type=EntityType.DISEASE, surface_form="lung cancer"),
            BiomedicalEntity(entity_type=EntityType.COMPOUND, surface_form="erlotinib"),
        ],
        constraints=ConstraintSet(trial_phases=["PHASE3"]),
        extraction_confidence=0.75,
    )
    legacy = to_legacy_research_plan(rq)
    assert set(legacy.keys()) == {
        "drug_targets", "diseases", "compounds", "query_type",
        "key_constraints", "extracted_keywords", "confidence",
    }
    assert legacy["drug_targets"] == ["EGFR"]
    assert legacy["diseases"] == ["lung cancer"]
    assert legacy["compounds"] == ["erlotinib"]
    assert legacy["query_type"] == "drug_target_search"
    assert "trial_phases: PHASE3" in legacy["key_constraints"]
    assert legacy["confidence"] == 0.75
    # planning_node's json.loads(state.get("research_plan", "{}")) must work
    # against this dict without error.
    json.loads(json.dumps(legacy))


def test_adapter_handles_empty_research_query():
    rq = ResearchQuery(original_query="x", normalized_query="x")
    legacy = to_legacy_research_plan(rq)
    assert legacy["drug_targets"] == []
    assert legacy["query_type"] == "general_research"


# ---------------------------------------------------------------------------
# query_analysis_node integration (LangGraph delegation + adapter)
# ---------------------------------------------------------------------------

def _mock_cerebras_response(content_dict, input_tokens=30, output_tokens=20):
    """Cerebras' chat-completions envelope shape (candidate_g_cerebras_qwen
    calls requests.post directly, not the NVIDIA get_llm() abstraction - see
    nlu/extractor.py::_invoke_cerebras_json)."""
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(content_dict)}}],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }
    return resp


@patch("nlu.extractor.requests.post")
def test_query_analysis_node_delegates_to_nlu_and_populates_research_plan(mock_post):
    """End-to-end (mocked LLM) check that query_analysis_node's delegation
    to nlu.understand_query_with_result() + to_legacy_research_plan()
    produces a research_plan planning_node can still json.loads() with the
    exact old key set.

    Mock response uses candidate_g_cerebras_qwen's JSON shape - Phase 2's
    frozen config (artifacts/v2/nlu_frozen_config.json, config_version 3)
    selects candidate_g_cerebras_qwen (see
    docs/v2/PHASE2_CEREBRAS_QWEN_EXPERIMENT.md), which is what
    _frozen_architecture() now resolves to. candidate_g calls Cerebras
    directly via requests.post (not the NVIDIA get_llm() abstraction), so
    the mock target and response envelope shape reflect that call site.
    """
    from agent.nodes import query_analysis_node

    mock_post.return_value = _mock_cerebras_response({
        "intent": ["C_compound_target"],
        "intent_confidence": 0.7,
        "entities": [
            {"entity_type": "target", "surface_form": "EGFR", "semantic_roles": []},
            {"entity_type": "disease", "surface_form": "lung cancer", "semantic_roles": []},
        ],
        "constraints": {},
        "requested_evidence_types": ["chembl", "pubmed"],
        "ambiguity": {"is_ambiguous": False, "ambiguity_reason": None, "candidate_interpretations": []},
        "extraction_confidence": 0.7,
    }, input_tokens=30, output_tokens=20)

    state = {
        "query": "Find EGFR inhibitors for lung cancer",
        "intermediate_thoughts": [],
        "errors": [],
        "messages": [],
        "total_tokens_used": 0,
    }
    result_state = query_analysis_node(state)

    assert result_state["errors"] == []
    plan = json.loads(result_state["research_plan"])
    assert set(plan.keys()) == {
        "drug_targets", "diseases", "compounds", "query_type",
        "key_constraints", "extracted_keywords", "confidence",
    }
    assert plan["drug_targets"] == ["EGFR"]
    assert result_state["confidence_score"] == 0.7
    assert result_state["total_tokens_used"] == 50


@patch("nlu.extractor.requests.post")
def test_query_analysis_node_falls_back_cleanly_on_malformed_nlu_output(mock_post):
    """A malformed/unparseable NLU response must not crash the node - the
    existing minimal-fallback behavior (query_type=general_research) must
    still trigger, exactly as it did before the Phase 2 delegation.

    Frozen architecture is candidate_g_cerebras_qwen (config_version 3, see
    docs/v2/PHASE2_CEREBRAS_QWEN_EXPERIMENT.md) - mocked at its actual call
    site, requests.post, returning a malformed content string inside the
    real Cerebras envelope shape (matches _invoke_cerebras_json's bounded
    1-retry-then-explicit-NLU_FAILURE path on both attempts)."""
    from agent.nodes import query_analysis_node

    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": "not valid json at all {{{"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    mock_post.return_value = resp

    state = {
        "query": "some query",
        "intermediate_thoughts": [],
        "errors": [],
        "messages": [],
        "total_tokens_used": 0,
    }
    result_state = query_analysis_node(state)

    assert len(result_state["errors"]) == 1
    plan = json.loads(result_state["research_plan"])
    assert plan["query_type"] == "general_research"


# ---------------------------------------------------------------------------
# Benchmark loader / versioning
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def benchmark():
    with open("evaluation/v2/nlu_benchmark_v1.json") as f:
        return json.load(f)


def test_benchmark_has_versioning_metadata(benchmark):
    for key in ("benchmark_name", "version", "creation_date", "schema_version",
                "annotation_methodology_ref", "split_seed", "split_sizes",
                "label_definition_ref", "provenance", "known_limitations"):
        assert key in benchmark, f"missing {key}"


def test_benchmark_has_at_least_150_examples(benchmark):
    total = len(benchmark["dev"]) + len(benchmark["test"])
    assert total >= 150
    assert total == benchmark["split_sizes"]["total"]


def test_benchmark_split_no_template_group_leakage(benchmark):
    dev_groups = {e["template_group"] for e in benchmark["dev"]}
    test_groups = {e["template_group"] for e in benchmark["test"]}
    assert dev_groups.isdisjoint(test_groups)


def test_benchmark_split_no_exact_text_leakage(benchmark):
    dev_texts = {e["query_text"].strip().lower() for e in benchmark["dev"]}
    test_texts = {e["query_text"].strip().lower() for e in benchmark["test"]}
    assert dev_texts.isdisjoint(test_texts)


def test_benchmark_all_intent_classes_valid(benchmark):
    for e in benchmark["dev"] + benchmark["test"]:
        assert e["intent_class"] in VALID_INTENT_VALUES


def test_benchmark_all_eight_query_time_classes_represented(benchmark):
    """nlu_benchmark_v1.1.0+: H_insufficient_evidence was migrated away
    (Phase 2 closure item 5) - all 8 remaining query-time classes must
    still have support in the benchmark."""
    all_classes = {e["intent_class"] for e in benchmark["dev"] + benchmark["test"]}
    assert all_classes == VALID_INTENT_VALUES
    assert "H_insufficient_evidence" not in all_classes


# ---------------------------------------------------------------------------
# Metric implementations
# ---------------------------------------------------------------------------

def test_entity_prf_perfect_match():
    gold = [{"text": "EGFR", "type": "target"}, {"text": "lung cancer", "type": "disease"}]
    pred = [
        BiomedicalEntity(entity_type=EntityType.TARGET, surface_form="EGFR"),
        BiomedicalEntity(entity_type=EntityType.DISEASE, surface_form="lung cancer"),
    ]
    result = entity_prf(gold, pred)
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0
    assert result["f1"] == 1.0


def test_entity_prf_partial_match():
    gold = [{"text": "EGFR", "type": "target"}, {"text": "lung cancer", "type": "disease"}]
    pred = [BiomedicalEntity(entity_type=EntityType.TARGET, surface_form="EGFR")]
    result = entity_prf(gold, pred)
    assert result["precision"] == 1.0
    assert result["recall"] == 0.5


def test_entity_prf_wrong_type_counts_as_miss():
    gold = [{"text": "EGFR", "type": "target"}]
    pred = [BiomedicalEntity(entity_type=EntityType.GENE, surface_form="EGFR")]
    result = entity_prf(gold, pred)
    assert result["precision"] == 0.0
    assert result["recall"] == 0.0


def test_normalization_accuracy_excludes_non_normalizable_gold():
    gold = [
        {"text": "melanoma", "type": "disease", "normalized_id": "MeSH:D008545"},
        {"text": "some vague phrase", "type": "disease", "normalized_id": None},
    ]
    pred = [
        BiomedicalEntity(entity_type=EntityType.DISEASE, surface_form="melanoma",
                          canonical_id="MeSH:D008545", canonical_name="Melanoma",
                          normalization_system=NormalizationSystem.MESH),
        BiomedicalEntity(entity_type=EntityType.DISEASE, surface_form="some vague phrase"),
    ]
    result = normalization_accuracy_at_1(gold, pred)
    assert result["n_normalizable"] == 1
    assert result["accuracy_at_1"] == 1.0
    assert result["fabricated_id_count"] == 0


def test_normalization_flags_fabricated_id():
    gold = [{"text": "some vague phrase", "type": "disease", "normalized_id": None}]
    pred = [BiomedicalEntity(entity_type=EntityType.DISEASE, surface_form="some vague phrase",
                              canonical_id="MeSH:MADE_UP", canonical_name="Made Up",
                              normalization_system=NormalizationSystem.MESH)]
    result = normalization_accuracy_at_1(gold, pred)
    assert result["fabricated_id_count"] == 1


def test_intent_metrics_accuracy_and_macro_f1():
    gold = ["A_literature_evidence", "B_clinical_trial_landscape", "A_literature_evidence"]
    pred = [["A_literature_evidence"], ["A_literature_evidence"], ["A_literature_evidence"]]
    result = intent_metrics(gold, pred)
    assert result["accuracy"] == pytest.approx(2 / 3)
    assert result["macro_f1"] is not None


def test_constraint_prf_case_insensitive():
    gold = [{"field": "trial_phases", "value": "PHASE3"}]
    pred_pairs = [("trial_phases", "phase3")]
    result = constraint_prf(gold, pred_pairs)
    assert result["f1"] == 1.0


def test_source_set_prf():
    result = source_set_prf(["pubmed", "chembl"], ["pubmed"])
    assert result["precision"] == 1.0
    assert result["recall"] == 0.5


def test_aggregate_micro_macro():
    per_query = [
        {"tp": 1, "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0, "f1": 1.0},
        {"tp": 0, "fp": 1, "fn": 1, "precision": 0.0, "recall": 0.0, "f1": 0.0},
    ]
    result = aggregate_micro_macro(per_query)
    assert result["n"] == 2
    assert result["macro"]["f1"] == 0.5
