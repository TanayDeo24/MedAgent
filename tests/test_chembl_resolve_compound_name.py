"""Offline (mocked, no real ChEMBL dependency) unit tests for
ChEMBLTool.resolve_compound_name and its Phase-4 typed-orchestration wiring
(orchestration/models.py's ChEMBLResolveCompoundNameArgs/Call,
orchestration/registry.py's registration, and
orchestration/candidate_b_native_tools.py's declaration generation).

Per docs/v2/PHASE4_CHEMBL_RESOLUTION.md: this file never makes a real HTTP
call (see tests/test_chembl_resolve_compound_name_live.py, gated behind
RUN_LIVE_CHEMBL_TESTS, for the bounded live integration check). Every test
here mocks only the private HTTP-issuing helpers
(_search_molecules/_get_molecule_details/_fuzzy_search_molecules), exactly
like the existing tests/test_chembl.py pattern, so the real
@rate_limit-decorated methods and _execute_with_monitoring/parse_results
plumbing stay in the call path.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from requests.exceptions import ConnectionError as ReqConnectionError
from requests.exceptions import Timeout as ReqTimeout

from orchestration.candidate_b_native_tools import (
    DECLARED_TOOLS_BY_NAME,
    build_tool_declarations,
    parse_and_validate_tool_call,
)
from orchestration.models import (
    ChEMBLResolveCompoundNameArgs,
    ChEMBLResolveCompoundNameCall,
)
from orchestration.registry import DEFAULT_REGISTRY, RegistryError
from tools.chembl_tool import FUZZY_MATCH_MIN_SIMILARITY, ChEMBLTool


@pytest.fixture
def chembl_tool():
    return ChEMBLTool()


def _molecule(chembl_id: str, pref_name: str) -> dict:
    return {
        "molecule_chembl_id": chembl_id,
        "pref_name": pref_name,
        "molecule_type": "Small molecule",
        "max_phase": 4,
        "molecule_properties": {},
        "molecule_mechanisms": [],
    }


# ---------------------------------------------------------------------------
# Core resolve_compound_name behavior (mocked HTTP layer)
# ---------------------------------------------------------------------------


class TestResolveCompoundNameCore:
    def test_exact_preferred_name_match(self, chembl_tool, monkeypatch):
        monkeypatch.setattr(
            chembl_tool,
            "_search_molecules",
            lambda params: {"molecules": [_molecule("CHEMBL3353410", "OSIMERTINIB")]}
            if params.get("pref_name__iexact") == "osimertinib"
            else {"molecules": []},
        )

        result = chembl_tool.resolve_compound_name("osimertinib")

        assert result.success is True
        assert result.data["match_type"] == "exact_preferred_name"
        assert result.data["chembl_id"] == "CHEMBL3353410"
        assert result.data["preferred_name"] == "OSIMERTINIB"
        assert result.data["candidates"] == []

    def test_synonym_match(self, chembl_tool, monkeypatch):
        def fake_search(params):
            if "pref_name__iexact" in params:
                return {"molecules": []}
            if params.get("molecule_synonyms__molecule_synonym__iexact") == "Keytruda":
                return {"molecules": [_molecule("CHEMBL3137343", "PEMBROLIZUMAB")]}
            return {"molecules": []}

        monkeypatch.setattr(chembl_tool, "_search_molecules", fake_search)

        result = chembl_tool.resolve_compound_name("Keytruda")

        assert result.success is True
        assert result.data["match_type"] == "exact_synonym"
        assert result.data["chembl_id"] == "CHEMBL3137343"
        assert result.data["preferred_name"] == "PEMBROLIZUMAB"

    def test_chembl_id_passthrough(self, chembl_tool, monkeypatch):
        monkeypatch.setattr(
            chembl_tool,
            "_get_molecule_details",
            lambda cid: _molecule(cid, "IMATINIB"),
        )

        result = chembl_tool.resolve_compound_name("CHEMBL941")

        assert result.success is True
        assert result.data["match_type"] == "exact_id_passthrough"
        assert result.data["chembl_id"] == "CHEMBL941"

    def test_case_normalization(self, chembl_tool, monkeypatch):
        """A lowercase/mixed-case input must still resolve via
        pref_name__iexact -- the case-insensitivity is delegated to the real
        ChEMBL API parameter, not re-implemented locally, but this test
        confirms resolve_compound_name passes the normalized (whitespace-
        collapsed) string through and the case-insensitive match succeeds
        regardless of input casing."""
        monkeypatch.setattr(
            chembl_tool,
            "_search_molecules",
            lambda params: {"molecules": [_molecule("CHEMBL941", "IMATINIB")]}
            if params.get("pref_name__iexact", "").lower() == "imatinib"
            else {"molecules": []},
        )

        for variant in ["IMATINIB", "imatinib", "  Imatinib  ", "ImAtInIb"]:
            result = chembl_tool.resolve_compound_name(variant)
            assert result.data["match_type"] == "exact_preferred_name", variant
            assert result.data["chembl_id"] == "CHEMBL941", variant

    def test_no_match(self, chembl_tool, monkeypatch):
        monkeypatch.setattr(chembl_tool, "_search_molecules", lambda params: {"molecules": []})
        monkeypatch.setattr(chembl_tool, "_fuzzy_search_molecules", lambda name, limit: {"molecules": []})

        result = chembl_tool.resolve_compound_name("ZZZNOTADRUGNAME123")

        assert result.success is True
        assert result.data["match_type"] == "no_match"
        assert result.data["chembl_id"] is None
        assert result.data["candidates"] == []

    def test_ambiguous_result_not_silently_collapsed(self, chembl_tool, monkeypatch):
        """When more than one distinct molecule matches (e.g. base compound
        + salt form both carrying the same synonym), resolve_compound_name
        must NOT silently pick one -- chembl_id stays None and every
        candidate is surfaced."""

        def fake_search(params):
            if "pref_name__iexact" in params:
                return {"molecules": []}
            if "molecule_synonyms__molecule_synonym__iexact" in params:
                return {
                    "molecules": [
                        _molecule("CHEMBL941", "IMATINIB"),
                        _molecule("CHEMBL1642", "IMATINIB MESYLATE"),
                    ]
                }
            return {"molecules": []}

        monkeypatch.setattr(chembl_tool, "_search_molecules", fake_search)

        result = chembl_tool.resolve_compound_name("Gleevec")

        assert result.success is True
        assert result.data["match_type"] == "ambiguous_match"
        assert result.data["chembl_id"] is None
        candidate_ids = {c["chembl_id"] for c in result.data["candidates"]}
        assert candidate_ids == {"CHEMBL941", "CHEMBL1642"}

    def test_fuzzy_fallback_never_presented_as_exact(self, chembl_tool, monkeypatch):
        monkeypatch.setattr(chembl_tool, "_search_molecules", lambda params: {"molecules": []})
        monkeypatch.setattr(
            chembl_tool,
            "_fuzzy_search_molecules",
            lambda name, limit: {
                "molecules": [
                    _molecule("CHEMBL3545063", "OSIMERTINIB MESYLATE"),
                    _molecule("CHEMBL3353410", "OSIMERTINIB"),
                ]
            },
        )

        result = chembl_tool.resolve_compound_name("osimertinib salt")

        assert result.success is True
        assert result.data["match_type"] == "fuzzy"
        assert result.data["chembl_id"] == "CHEMBL3545063"
        assert len(result.data["candidates"]) == 1
        assert result.data["candidates"][0]["chembl_id"] == "CHEMBL3353410"

    def test_fuzzy_fallback_rejects_low_similarity_top_hit(self, chembl_tool, monkeypatch):
        """Regression test for the Phase-4 held-out defect: ChEMBL's fuzzy
        search endpoint can return a real, unrelated molecule as its top
        hit for a completely fabricated compound name (independently
        reproduced live: "Zorblatinix-9X" -> CHEMBL5875133, an unrelated
        nameless molecule). If the top hit's own pref_name/synonyms are not
        actually similar to the input, resolve_compound_name must report
        no_match, never a misleading "fuzzy" success with a real-but-wrong
        chembl_id."""
        monkeypatch.setattr(chembl_tool, "_search_molecules", lambda params: {"molecules": []})
        monkeypatch.setattr(
            chembl_tool,
            "_fuzzy_search_molecules",
            lambda name, limit: {
                "molecules": [
                    {
                        "molecule_chembl_id": "CHEMBL5875133",
                        "pref_name": None,
                        "molecule_synonyms": [],
                        "score": 30.0,
                    },
                    {
                        "molecule_chembl_id": "CHEMBL444579",
                        "pref_name": None,
                        "molecule_synonyms": [],
                        "score": 20.0,
                    },
                ]
            },
        )

        result = chembl_tool.resolve_compound_name("Zorblatinix-9X")

        assert result.success is True
        assert result.data["match_type"] == "no_match"
        assert result.data["chembl_id"] is None
        assert result.data["matched_name"] is None
        assert result.data["candidates"] == []
        serialized = json.dumps(result.data)
        assert "CHEMBL" not in serialized

    def test_fuzzy_fallback_accepts_genuine_near_miss_typo(self, chembl_tool, monkeypatch):
        """A genuine near-miss typo ("asprin" -> ASPIRIN, independently
        confirmed live against the real ChEMBL API) must still resolve via
        the fuzzy tier -- the similarity gate must not be so strict it
        breaks real typo-correction cases."""
        monkeypatch.setattr(chembl_tool, "_search_molecules", lambda params: {"molecules": []})
        monkeypatch.setattr(
            chembl_tool,
            "_fuzzy_search_molecules",
            lambda name, limit: {
                "molecules": [
                    {
                        "molecule_chembl_id": "CHEMBL25",
                        "pref_name": "ASPIRIN",
                        "molecule_synonyms": [],
                        "score": 0.0,
                    },
                ]
            },
        )

        result = chembl_tool.resolve_compound_name("asprin")

        assert result.success is True
        assert result.data["match_type"] == "fuzzy"
        assert result.data["chembl_id"] == "CHEMBL25"
        assert result.data["matched_name"] == "ASPIRIN"

    def test_fuzzy_fallback_accepts_match_via_synonym_not_just_pref_name(self, chembl_tool, monkeypatch):
        """A candidate whose pref_name doesn't match well but whose brand
        synonym does (e.g. Tagrisso -> osimertinib mesylate) should still
        clear the similarity gate via _best_name_similarity checking
        synonyms, not just pref_name."""
        monkeypatch.setattr(chembl_tool, "_search_molecules", lambda params: {"molecules": []})
        monkeypatch.setattr(
            chembl_tool,
            "_fuzzy_search_molecules",
            lambda name, limit: {
                "molecules": [
                    {
                        "molecule_chembl_id": "CHEMBL3545063",
                        "pref_name": "OSIMERTINIB MESYLATE",
                        "molecule_synonyms": [
                            {"molecule_synonym": "Tagrisso", "syn_type": "TRADE_NAME", "synonyms": "TAGRISSO"},
                        ],
                        "score": 14.0,
                    },
                ]
            },
        )

        result = chembl_tool.resolve_compound_name("Tagrisso")

        assert result.success is True
        assert result.data["match_type"] == "fuzzy"
        assert result.data["chembl_id"] == "CHEMBL3545063"

    def test_no_fabricated_id_ever_appears_when_no_real_match(self, chembl_tool, monkeypatch):
        """Explicit gate: when every upstream call finds nothing, the
        ToolResult must never contain a plausible-looking but unverified
        ChEMBL ID anywhere -- chembl_id is None and no candidate list
        contains one either."""
        monkeypatch.setattr(chembl_tool, "_search_molecules", lambda params: {"molecules": []})
        monkeypatch.setattr(chembl_tool, "_fuzzy_search_molecules", lambda name, limit: {"molecules": []})

        result = chembl_tool.resolve_compound_name("totally_fake_compound_9999")

        assert result.success is True
        data = result.data
        assert data["chembl_id"] is None
        assert data["preferred_name"] is None
        assert data["candidates"] == []
        # Sanity: serialize the whole result and confirm no "CHEMBL" token
        # (a fabricated ID) appears anywhere in the payload.
        serialized = json.dumps(data)
        assert "CHEMBL" not in serialized


# ---------------------------------------------------------------------------
# Fuzzy-match similarity gate (_best_name_similarity / FUZZY_MATCH_MIN_SIMILARITY)
# unit-tested directly, no HTTP mocking needed.
# ---------------------------------------------------------------------------


class TestFuzzyMatchSimilarityGate:
    def test_fabricated_name_scores_zero_against_unrelated_nameless_molecule(self, chembl_tool):
        molecule = {"molecule_chembl_id": "CHEMBL5875133", "pref_name": None, "molecule_synonyms": []}
        similarity = chembl_tool._best_name_similarity("Zorblatinix-9X", molecule)
        assert similarity == 0.0
        assert similarity < FUZZY_MATCH_MIN_SIMILARITY

    def test_genuine_typo_clears_threshold_via_pref_name(self, chembl_tool):
        molecule = {"molecule_chembl_id": "CHEMBL25", "pref_name": "ASPIRIN", "molecule_synonyms": []}
        similarity = chembl_tool._best_name_similarity("asprin", molecule)
        assert similarity >= FUZZY_MATCH_MIN_SIMILARITY

    def test_genuine_typo_clears_threshold_via_synonym(self, chembl_tool):
        molecule = {
            "molecule_chembl_id": "CHEMBL3545063",
            "pref_name": "OSIMERTINIB MESYLATE",
            "molecule_synonyms": [{"synonyms": "TAGRISSO"}],
        }
        similarity = chembl_tool._best_name_similarity("Tagrisso", molecule)
        assert similarity >= FUZZY_MATCH_MIN_SIMILARITY

    def test_exact_name_case_and_punctuation_insensitive_scores_one(self, chembl_tool):
        molecule = {"molecule_chembl_id": "CHEMBL941", "pref_name": "IMATINIB", "molecule_synonyms": []}
        assert chembl_tool._best_name_similarity("imatinib", molecule) == 1.0
        assert chembl_tool._best_name_similarity("  ImAtInIb  ", molecule) == 1.0

    def test_molecule_with_no_name_or_synonyms_scores_zero(self, chembl_tool):
        molecule = {"molecule_chembl_id": "CHEMBL1", "pref_name": None, "molecule_synonyms": None}
        assert chembl_tool._best_name_similarity("anything", molecule) == 0.0

    def test_best_of_multiple_synonyms_is_used(self, chembl_tool):
        molecule = {
            "molecule_chembl_id": "CHEMBL1",
            "pref_name": "SOME OTHER NAME",
            "molecule_synonyms": [
                {"synonyms": "Totally Different"},
                {"synonyms": "Amoxicillin"},
            ],
        }
        similarity = chembl_tool._best_name_similarity("Amoxicilin", molecule)
        assert similarity >= FUZZY_MATCH_MIN_SIMILARITY


# ---------------------------------------------------------------------------
# Malformed upstream response / failure handling
# ---------------------------------------------------------------------------


class TestResolveCompoundNameFailureHandling:
    def test_malformed_upstream_response(self, chembl_tool, monkeypatch):
        """An upstream response missing the expected 'molecules' key
        entirely must not crash -- treated as an empty result set, not an
        unhandled exception."""
        monkeypatch.setattr(chembl_tool, "_search_molecules", lambda params: {"unexpected_shape": True})
        monkeypatch.setattr(chembl_tool, "_fuzzy_search_molecules", lambda name, limit: {"unexpected_shape": True})

        result = chembl_tool.resolve_compound_name("somecompound")

        assert result.success is True
        assert result.data["match_type"] == "no_match"

    def test_timeout_error(self, chembl_tool, monkeypatch):
        def raise_timeout(params):
            raise ReqTimeout("Request timeout")

        monkeypatch.setattr(chembl_tool, "_search_molecules", raise_timeout)

        result = chembl_tool.resolve_compound_name("osimertinib")

        assert result.success is False
        assert "timed out" in result.error.lower()

    def test_upstream_connection_failure(self, chembl_tool, monkeypatch):
        def raise_conn_error(params):
            raise ReqConnectionError("Network error")

        monkeypatch.setattr(chembl_tool, "_search_molecules", raise_conn_error)

        result = chembl_tool.resolve_compound_name("osimertinib")

        assert result.success is False
        assert "connect" in result.error.lower()

    def test_fuzzy_step_exception_treated_as_no_match(self, chembl_tool, monkeypatch):
        """A failure specifically in the last-resort fuzzy step (after exact
        steps already found nothing) must degrade to a clean no_match, not
        propagate as an unhandled exception up through the whole call."""
        monkeypatch.setattr(chembl_tool, "_search_molecules", lambda params: {"molecules": []})

        def raise_error(name, limit):
            raise ReqConnectionError("fuzzy endpoint down")

        monkeypatch.setattr(chembl_tool, "_fuzzy_search_molecules", raise_error)

        result = chembl_tool.resolve_compound_name("somecompound")

        assert result.success is True
        assert result.data["match_type"] == "no_match"

    def test_empty_name_input(self, chembl_tool):
        result = chembl_tool.resolve_compound_name("   ")
        assert result.success is True
        assert result.data["match_type"] == "no_match"
        assert result.data["chembl_id"] is None


# ---------------------------------------------------------------------------
# Typed orchestration boundary (Phase 3 pipeline, Step C of Phase 4)
# ---------------------------------------------------------------------------


class TestTypedOrchestrationWiring:
    def test_well_formed_call_passes_validate_call(self):
        call = ChEMBLResolveCompoundNameCall(
            call_id="c1",
            arguments=ChEMBLResolveCompoundNameArgs(name="osimertinib"),
        )
        validated = DEFAULT_REGISTRY.validate_call(call)
        assert validated is call

    def test_malformed_args_rejected_before_construction(self):
        with pytest.raises(ValidationError):
            ChEMBLResolveCompoundNameArgs(name="")  # min_length=1 violated

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            ChEMBLResolveCompoundNameArgs(name="osimertinib", not_a_real_field=True)

    def test_negative_max_results_rejected(self):
        with pytest.raises(ValidationError):
            ChEMBLResolveCompoundNameArgs(name="osimertinib", max_results=0)

    def test_registered_in_default_registry(self):
        from orchestration.models import ToolName

        pairs = DEFAULT_REGISTRY.registered_pairs()
        assert (ToolName.CHEMBL, "resolve_compound_name") in pairs

    def test_execution_fn_bound_to_real_tool_method(self):
        from orchestration.models import ToolName

        fn = DEFAULT_REGISTRY.get_execution_fn(ToolName.CHEMBL, "resolve_compound_name")
        assert fn is not None

    def test_cerebras_declaration_includes_new_function(self):
        declarations = build_tool_declarations()
        names = {d["function"]["name"] for d in declarations}
        assert "chembl_resolve_compound_name" in names

        decl = next(d for d in declarations if d["function"]["name"] == "chembl_resolve_compound_name")
        params = decl["function"]["parameters"]
        assert params["additionalProperties"] is False
        assert "name" in params["properties"]
        assert params["required"] == ["name"]

    def test_invalid_provider_args_rejected_before_execution(self):
        """A well-formed function-name-recognized tool_call whose arguments
        violate the schema (missing required 'name') must fail at the
        schema-validation step, never reach registry_valid=True."""
        raw_tool_call = {
            "id": "call_abc",
            "function": {
                "name": "chembl_resolve_compound_name",
                "arguments": json.dumps({"max_results": 3}),  # missing 'name'
            },
        }
        outcome = parse_and_validate_tool_call(raw_tool_call, call_id="c1")
        assert outcome.recognized_tool is True
        assert outcome.schema_valid is False
        assert outcome.registry_valid is False
        assert outcome.failure_category == "schema_invalid"

    def test_valid_provider_args_reach_registry_valid(self):
        raw_tool_call = {
            "id": "call_def",
            "function": {
                "name": "chembl_resolve_compound_name",
                "arguments": json.dumps({"name": "osimertinib"}),
            },
        }
        outcome = parse_and_validate_tool_call(raw_tool_call, call_id="c2")
        assert outcome.recognized_tool is True
        assert outcome.schema_valid is True
        assert outcome.registry_valid is True
        assert outcome.tool_name.value == "chembl"
        assert outcome.operation == "resolve_compound_name"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
