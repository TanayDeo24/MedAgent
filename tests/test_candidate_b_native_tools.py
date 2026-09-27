"""Offline (no-network) tests for orchestration/candidate_b_native_tools.py.

These test only the parts of the Candidate-B adapter that don't require a
real Cerebras API call: the tool-declaration schema generation (must stay
in lockstep with orchestration/models.py by construction, since it's
generated from the same pydantic classes via .model_json_schema()) and the
parse/validate boundary (`parse_and_validate_tool_call`), fed synthetic
provider-shaped `tool_calls` dicts exactly as Cerebras' Chat Completions
response would contain them. No network call, no CEREBRAS_API_KEY
required.
"""

from __future__ import annotations

import json

from orchestration.candidate_b_native_tools import (
    DECLARED_TOOLS,
    DECLARED_TOOLS_BY_NAME,
    build_tool_declarations,
    estimate_cost_usd,
    parse_and_validate_tool_call,
)
from orchestration.models import ToolName
from orchestration.registry import DEFAULT_REGISTRY


def test_declared_tools_match_registry_exactly():
    """Every (ToolName, operation) pair declared to the model must be
    exactly the set orchestration/registry.py registers -- no more (which
    would let the model select something we can't validate) and no fewer
    (which would silently make a real registered tool unreachable)."""

    declared_pairs = {(t.tool_name, t.operation) for t in DECLARED_TOOLS}
    registered_pairs = set(DEFAULT_REGISTRY.registered_pairs())
    assert declared_pairs == registered_pairs


def test_build_tool_declarations_shape_and_schema_source():
    declarations = build_tool_declarations()
    assert len(declarations) == len(DECLARED_TOOLS)
    names = {d["function"]["name"] for d in declarations}
    assert names == set(DECLARED_TOOLS_BY_NAME.keys())
    for d in declarations:
        assert d["type"] == "function"
        params = d["function"]["parameters"]
        # Generated directly from the pydantic model -- additionalProperties
        # must be forbidden (matches ConfigDict(extra="forbid") on every
        # orchestration/models.py argument schema).
        assert params.get("additionalProperties") is False
        assert "properties" in params


def test_pubmed_declaration_matches_pubmed_search_args_schema():
    from orchestration.models import PubMedSearchArgs

    declarations = build_tool_declarations()
    pubmed_decl = next(d for d in declarations if d["function"]["name"] == "pubmed_search_pubmed")
    expected = PubMedSearchArgs.model_json_schema()
    expected.pop("title", None)
    expected.pop("description", None)
    assert pubmed_decl["function"]["parameters"] == expected


def test_clinical_trials_declaration_has_status_and_phase_enum():
    """Regression test for the Phase 3 defect (docs/v2/PHASE3_STATUS.md):
    the tool declaration actually sent to Cerebras for
    clinical_trials_search_trials must expose an `enum` for status/phase,
    not just an untyped string, so the model is constrained to canonical
    values (e.g. "PHASE4", not "Phase 4") instead of guessing."""
    from orchestration.models import VALID_TRIAL_PHASES, VALID_TRIAL_STATUSES

    declarations = build_tool_declarations()
    ct_decl = next(
        d for d in declarations if d["function"]["name"] == "clinical_trials_search_trials"
    )
    properties = ct_decl["function"]["parameters"]["properties"]

    def enum_values(property_schema: dict) -> set:
        if "enum" in property_schema:
            return set(property_schema["enum"])
        for option in property_schema.get("anyOf", []):
            if "enum" in option:
                return set(option["enum"])
        raise AssertionError(f"no enum found in property schema: {property_schema!r}")

    assert enum_values(properties["status"]) == set(VALID_TRIAL_STATUSES)
    assert enum_values(properties["phase"]) == set(VALID_TRIAL_PHASES)


def _raw_tool_call(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def test_parse_and_validate_valid_pubmed_call():
    raw = _raw_tool_call("tc1", "pubmed_search_pubmed", {"query": "EGFR resistance NSCLC"})
    outcome = parse_and_validate_tool_call(raw, call_id="case1-0")
    assert outcome.recognized_tool is True
    assert outcome.arguments_json_valid is True
    assert outcome.schema_valid is True
    assert outcome.registry_valid is True
    assert outcome.failure_category is None
    assert outcome.tool_name == ToolName.PUBMED
    assert outcome.pydantic_call is not None
    assert outcome.pydantic_call.arguments.query == "EGFR resistance NSCLC"


def test_parse_and_validate_unregistered_tool_name():
    raw = _raw_tool_call("tc2", "semantic_scholar_search", {"query": "x"})
    outcome = parse_and_validate_tool_call(raw, call_id="case2-0")
    assert outcome.recognized_tool is False
    assert outcome.registry_valid is False
    assert outcome.failure_category == "unregistered_tool"
    assert outcome.tool_name is None


def test_parse_and_validate_malformed_json_arguments():
    raw = {
        "id": "tc3",
        "type": "function",
        "function": {"name": "pubmed_search_pubmed", "arguments": "{not valid json"},
    }
    outcome = parse_and_validate_tool_call(raw, call_id="case3-0")
    assert outcome.recognized_tool is True
    assert outcome.arguments_json_valid is False
    assert outcome.registry_valid is False
    assert outcome.failure_category == "arguments_json_invalid"


def test_parse_and_validate_schema_invalid_arguments():
    # ClinicalTrialsSearchArgs.status must be one of VALID_TRIAL_STATUSES --
    # an arbitrary status string must be rejected at typed-construction
    # time (the same rejection FL-001's gold rationale requires), never
    # silently coerced or passed through to registry.validate_call as if
    # valid.
    raw = _raw_tool_call(
        "tc4",
        "clinical_trials_search_trials",
        {"condition": "melanoma", "intervention": "pembrolizumab", "status": "FULLY_ENROLLED"},
    )
    outcome = parse_and_validate_tool_call(raw, call_id="case4-0")
    assert outcome.recognized_tool is True
    assert outcome.arguments_json_valid is True
    assert outcome.schema_valid is False
    assert outcome.registry_valid is False
    assert outcome.failure_category == "schema_invalid"


def test_parse_and_validate_missing_required_field():
    raw = _raw_tool_call("tc5", "chembl_get_drug_info", {})
    outcome = parse_and_validate_tool_call(raw, call_id="case5-0")
    assert outcome.schema_valid is False
    assert outcome.failure_category == "schema_invalid"


def test_estimate_cost_usd_matches_frozen_pricing():
    # 1,000,000 input + 1,000,000 output tokens at the frozen Phase-2
    # Cerebras qwen-3.8-27b pricing ($0.99/1M in, $1.49/1M out).
    cost = estimate_cost_usd(1_000_000, 1_000_000)
    assert round(cost, 6) == round(0.99 + 1.49, 6)


def test_estimate_cost_usd_zero_tokens():
    assert estimate_cost_usd(0, 0) == 0.0
