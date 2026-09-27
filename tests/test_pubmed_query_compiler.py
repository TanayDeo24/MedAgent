"""Unit tests for retrieval/pubmed_query_compiler.py.

Fully offline -- no network, no LLM, no live PubMed calls. Exercises the
deterministic compile_pubmed_query() function against both plain dicts and
real nlu.schemas.ResearchQuery/BiomedicalEntity/ConstraintSet instances.
"""

import pytest

from nlu.schemas import BiomedicalEntity, ConstraintSet, EntityType, ResearchQuery
from retrieval.pubmed_query_compiler import (
    CompiledPubMedQuery,
    DateFilter,
    compile_pubmed_query,
)


def _entity(entity_type, surface_form, canonical_name=None):
    return BiomedicalEntity(
        entity_type=entity_type,
        surface_form=surface_form,
        canonical_name=canonical_name,
    )


def _research_query(entities=None, temporal=None, query_text="test query"):
    constraints = ConstraintSet(temporal=temporal or [])
    return ResearchQuery(
        original_query=query_text,
        normalized_query=query_text,
        entities=entities or [],
        constraints=constraints,
    )


class TestSimpleDiseaseQuery:
    def test_single_disease_entity(self):
        rq = _research_query(entities=[_entity(EntityType.DISEASE, "lung cancer")])
        result = compile_pubmed_query(rq)
        assert isinstance(result, CompiledPubMedQuery)
        assert result.query == "lung cancer" or result.query == '"lung cancer"'
        assert "lung cancer" in result.source_concepts
        assert result.fallback_used is False


class TestDiseaseAndCompound:
    def test_disease_plus_compound(self):
        rq = _research_query(
            entities=[
                _entity(EntityType.COMPOUND, "brigatinib"),
                _entity(EntityType.DISEASE, "non-small cell lung cancer"),
            ]
        )
        result = compile_pubmed_query(rq)
        assert "brigatinib" in result.query
        assert '"non-small cell lung cancer"' in result.query
        assert " AND " in result.query
        assert result.source_concepts == ["brigatinib", "non-small cell lung cancer"]


class TestDiseaseAndGene:
    def test_disease_plus_gene_target(self):
        rq = _research_query(
            entities=[
                _entity(EntityType.GENE, "EGFR"),
                _entity(EntityType.DISEASE, "lung adenocarcinoma"),
            ]
        )
        result = compile_pubmed_query(rq)
        assert "EGFR" in result.source_concepts
        # EGFR must never be expanded/rewritten into something else.
        assert "EGFR" in result.query
        assert "epidermal growth factor receptor" not in result.query.lower()


class TestMultiConceptQuery:
    def test_multiple_entities_all_preserved(self):
        rq = _research_query(
            entities=[
                _entity(EntityType.GENE, "BCMA"),
                _entity(EntityType.TARGET, "CAR-T"),
                _entity(EntityType.DISEASE, "multiple myeloma"),
            ]
        )
        result = compile_pubmed_query(rq)
        assert result.source_concepts == ["BCMA", "CAR-T", "multiple myeloma"]
        for term in ["BCMA", "CAR-T", '"multiple myeloma"']:
            assert term in result.query


class TestAbbreviationPreservation:
    def test_abbreviation_not_expanded_or_invented(self):
        rq = _research_query(entities=[_entity(EntityType.GENE, "EGFR")])
        result = compile_pubmed_query(rq)
        assert result.query == "EGFR"
        assert result.source_concepts == ["EGFR"]

    def test_canonical_name_used_when_present_but_not_expanded(self):
        # canonical_name is only ever populated by a defensible normalizer
        # lookup in the real pipeline -- here we just confirm the compiler
        # uses it verbatim (preferring it over surface_form) without any
        # further rewriting.
        rq = _research_query(
            entities=[_entity(EntityType.COMPOUND, "tzp", canonical_name="tirzepatide")]
        )
        result = compile_pubmed_query(rq)
        assert result.source_concepts == ["tirzepatide"]
        assert "tzp" not in result.query


class TestNoDateConstraint:
    def test_no_temporal_constraint_present(self):
        rq = _research_query(entities=[_entity(EntityType.DISEASE, "sepsis")])
        result = compile_pubmed_query(rq)
        assert result.date_filter.years_back is None
        assert result.date_filter.date_from is None
        assert result.unparsed_temporal_notes == []


class TestExplicitDateConstraint:
    def test_last_n_years_parsed(self):
        rq = _research_query(
            entities=[_entity(EntityType.DISEASE, "obesity")],
            temporal=["last 5 years"],
        )
        result = compile_pubmed_query(rq)
        assert result.date_filter.years_back == 5
        assert result.date_filter.date_from is None
        assert result.date_filter.source_phrase == "last 5 years"

    def test_since_year_parsed(self):
        rq = _research_query(
            entities=[_entity(EntityType.DISEASE, "obesity")],
            temporal=["since 2020"],
        )
        result = compile_pubmed_query(rq)
        assert result.date_filter.date_from == "2020/01/01"
        assert result.date_filter.years_back is None

    def test_after_year_parsed(self):
        rq = _research_query(
            entities=[_entity(EntityType.DISEASE, "obesity")],
            temporal=["after 2018"],
        )
        result = compile_pubmed_query(rq)
        assert result.date_filter.date_from == "2018/01/01"

    def test_unrecognized_temporal_phrase_not_guessed(self):
        rq = _research_query(
            entities=[_entity(EntityType.DISEASE, "obesity")],
            temporal=["sometime recently"],
        )
        result = compile_pubmed_query(rq)
        assert result.date_filter.years_back is None
        assert result.date_filter.date_from is None
        assert "sometime recently" in result.unparsed_temporal_notes


class TestEmptyOrInsufficientInput:
    def test_no_entities_falls_back_to_query_text(self):
        rq = _research_query(entities=[], query_text="what treats flu")
        result = compile_pubmed_query(rq)
        assert result.query == "what treats flu"
        assert result.fallback_used is True
        assert result.source_concepts == []

    def test_completely_empty_dict_does_not_crash(self):
        result = compile_pubmed_query({})
        assert result.query == ""
        assert result.fallback_used is True
        assert result.source_concepts == []

    def test_none_input_does_not_crash(self):
        result = compile_pubmed_query(None)
        assert result.query == ""
        assert result.fallback_used is True

    def test_entities_with_only_degenerate_values_falls_back(self):
        rq = _research_query(
            entities=[_entity(EntityType.DISEASE, "the")],
            query_text="the disease",
        )
        result = compile_pubmed_query(rq)
        assert result.source_concepts == []
        assert result.fallback_used is True
        assert result.query == "the disease"


class TestDeterminism:
    def test_same_input_twice_byte_identical(self):
        rq = _research_query(
            entities=[
                _entity(EntityType.COMPOUND, "osimertinib"),
                _entity(EntityType.GENE, "EGFR"),
            ],
            temporal=["last 3 years"],
        )
        r1 = compile_pubmed_query(rq)
        r2 = compile_pubmed_query(rq)
        assert r1.query == r2.query
        assert r1.source_concepts == r2.source_concepts
        assert r1.date_filter == r2.date_filter

    def test_dict_and_model_forms_agree(self):
        rq = _research_query(entities=[_entity(EntityType.DISEASE, "sepsis")])
        as_dict = rq.model_dump()
        r_model = compile_pubmed_query(rq)
        r_dict = compile_pubmed_query(as_dict)
        assert r_model.query == r_dict.query
        assert r_model.source_concepts == r_dict.source_concepts


class TestNoFabrication:
    def test_no_synonym_or_mesh_term_invented(self):
        rq = _research_query(entities=[_entity(EntityType.COMPOUND, "metformin")])
        result = compile_pubmed_query(rq)
        # Only the literal input term appears -- no invented synonym like
        # "glucophage" (a real metformin brand name that must NOT appear
        # unless it was in the input).
        assert result.query == "metformin"
        assert "glucophage" not in result.query.lower()

    def test_duplicate_entities_not_duplicated_or_altered(self):
        rq = _research_query(
            entities=[
                _entity(EntityType.GENE, "EGFR"),
                _entity(EntityType.GENE, "EGFR"),
            ]
        )
        result = compile_pubmed_query(rq)
        assert result.source_concepts == ["EGFR"]
        assert result.query == "EGFR"

    def test_output_concepts_are_a_subset_of_input_terms(self):
        input_terms = {"upadacitinib", "Crohn's disease", "JAK"}
        rq = _research_query(
            entities=[
                _entity(EntityType.COMPOUND, "upadacitinib"),
                _entity(EntityType.DISEASE, "Crohn's disease"),
                _entity(EntityType.GENE, "JAK"),
            ]
        )
        result = compile_pubmed_query(rq)
        assert set(result.source_concepts).issubset(input_terms)


class TestPlainDictInput:
    def test_plain_dict_equivalent_to_model(self):
        d = {
            "entities": [{"surface_form": "ALK", "canonical_name": None}],
            "constraints": {"temporal": []},
            "normalized_query": "alk positive nsclc",
            "original_query": "alk positive nsclc",
        }
        result = compile_pubmed_query(d)
        assert result.query == "ALK"
        assert result.source_concepts == ["ALK"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
