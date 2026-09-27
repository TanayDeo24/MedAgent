"""Tests for orchestration/models.py - typed ToolCall construction, rejection
of invalid arguments, and rejection of unregistered/unknown operations at
the ToolCall boundary. No network calls."""

import pytest
from pydantic import ValidationError

from orchestration.models import (
    VALID_TRIAL_PHASES,
    VALID_TRIAL_STATUSES,
    ChEMBLGetDrugInfoArgs,
    ChEMBLGetDrugInfoCall,
    ChEMBLSearchByIndicationArgs,
    ChEMBLSearchByIndicationCall,
    ChEMBLSearchByTargetArgs,
    ChEMBLSearchByTargetCall,
    ClinicalTrialsSearchArgs,
    ClinicalTrialsSearchCall,
    ExecutionPlan,
    ExecutionStatus,
    PlanStatus,
    PubMedSearchArgs,
    PubMedSearchCall,
    ToolExecutionResult,
    ToolName,
)
from pydantic import TypeAdapter
from orchestration.models import ToolCall


# ---------------------------------------------------------------------------
# Valid construction, one per tool
# ---------------------------------------------------------------------------


def test_valid_pubmed_call_construction():
    call = PubMedSearchCall(
        call_id="c1",
        arguments=PubMedSearchArgs(query="EGFR inhibitors", max_results=10),
    )
    assert call.tool_name == ToolName.PUBMED
    assert call.operation == "search_pubmed"
    assert call.arguments.query == "EGFR inhibitors"


def test_valid_clinical_trials_call_construction():
    call = ClinicalTrialsSearchCall(
        call_id="c2",
        arguments=ClinicalTrialsSearchArgs(
            condition="lung cancer", status="RECRUITING", phase="PHASE2"
        ),
    )
    assert call.tool_name == ToolName.CLINICAL_TRIALS
    assert call.operation == "search_trials"
    assert call.arguments.status == "RECRUITING"
    assert call.arguments.phase == "PHASE2"


def test_valid_chembl_search_by_target_call_construction():
    call = ChEMBLSearchByTargetCall(
        call_id="c3",
        arguments=ChEMBLSearchByTargetArgs(target_name="EGFR", max_results=5),
    )
    assert call.tool_name == ToolName.CHEMBL
    assert call.operation == "search_by_target"


def test_valid_chembl_search_by_indication_call_construction():
    call = ChEMBLSearchByIndicationCall(
        call_id="c4",
        arguments=ChEMBLSearchByIndicationArgs(disease="lung cancer"),
    )
    assert call.operation == "search_by_indication"


def test_valid_chembl_get_drug_info_call_construction():
    call = ChEMBLGetDrugInfoCall(
        call_id="c5",
        arguments=ChEMBLGetDrugInfoArgs(chembl_id="CHEMBL941"),
    )
    assert call.operation == "get_drug_info"
    assert call.arguments.chembl_id == "CHEMBL941"


# ---------------------------------------------------------------------------
# Rejection of unregistered/unknown tool_name or operation at the ToolCall
# boundary (the discriminated union itself)
# ---------------------------------------------------------------------------


def test_discriminated_union_rejects_unknown_operation():
    adapter = TypeAdapter(ToolCall)
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "call_id": "bad1",
                "tool_name": "pubmed",
                "operation": "search_pubchem",  # not a real operation
                "arguments": {"query": "x"},
            }
        )


def test_discriminated_union_rejects_unknown_tool_name():
    adapter = TypeAdapter(ToolCall)
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "call_id": "bad2",
                "tool_name": "pubchem",  # hallucinated tool name
                "operation": "search_pubmed",
                "arguments": {"query": "x"},
            }
        )


def test_tool_name_mismatched_with_operation_rejected():
    # search_trials is a real operation, but not for CHEMBL.
    adapter = TypeAdapter(ToolCall)
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "call_id": "bad3",
                "tool_name": "chembl",
                "operation": "search_trials",
                "arguments": {"condition": "lung cancer"},
            }
        )


# ---------------------------------------------------------------------------
# Rejection of invalid ClinicalTrials status/phase (schema-level, not the
# real tool's silent-drop behavior)
# ---------------------------------------------------------------------------


def test_invalid_trial_status_rejected():
    with pytest.raises(ValidationError):
        ClinicalTrialsSearchArgs(status="NOT_A_REAL_STATUS")


def test_invalid_trial_phase_rejected():
    with pytest.raises(ValidationError):
        ClinicalTrialsSearchArgs(phase="PHASE99")


def test_valid_trial_status_and_phase_accepted():
    args = ClinicalTrialsSearchArgs(status="COMPLETED", phase="PHASE3")
    assert args.status == "COMPLETED"
    assert args.phase == "PHASE3"


def test_trial_status_none_is_allowed():
    args = ClinicalTrialsSearchArgs(status=None)
    assert args.status is None


def _enum_values(property_schema: dict) -> set:
    """Pull the `enum` list out of a JSON Schema property, whether it's a
    bare `{"enum": [...]}` or pydantic's `Optional[Literal[...]]` shape of
    `{"anyOf": [{"enum": [...], "type": "string"}, {"type": "null"}]}`."""
    if "enum" in property_schema:
        return set(property_schema["enum"])
    for option in property_schema.get("anyOf", []):
        if "enum" in option:
            return set(option["enum"])
    raise AssertionError(f"no enum found in property schema: {property_schema!r}")


def test_trial_status_and_phase_schema_has_enum_constraint():
    """Regression test for the Phase 3 defect (docs/v2/PHASE3_STATUS.md):
    `.model_json_schema()` must emit a real `enum` array for status/phase
    so the LLM tool declaration built from it (orchestration/
    candidate_b_native_tools.py) constrains generation to canonical
    values, matching tools/clinical_trials_tool.py's own VALID_STATUSES/
    VALID_PHASES exactly - not a hand-typed, driftable duplicate."""
    schema = ClinicalTrialsSearchArgs.model_json_schema()
    properties = schema["properties"]

    assert _enum_values(properties["status"]) == set(VALID_TRIAL_STATUSES)
    assert _enum_values(properties["phase"]) == set(VALID_TRIAL_PHASES)


# ---------------------------------------------------------------------------
# Rejection of missing required per-tool fields
# ---------------------------------------------------------------------------


def test_pubmed_missing_query_rejected():
    with pytest.raises(ValidationError):
        PubMedSearchArgs()


def test_pubmed_empty_query_rejected():
    with pytest.raises(ValidationError):
        PubMedSearchArgs(query="")


def test_chembl_search_by_target_missing_target_name_rejected():
    with pytest.raises(ValidationError):
        ChEMBLSearchByTargetArgs()


def test_chembl_search_by_indication_missing_disease_rejected():
    with pytest.raises(ValidationError):
        ChEMBLSearchByIndicationArgs()


def test_chembl_get_drug_info_missing_chembl_id_rejected():
    with pytest.raises(ValidationError):
        ChEMBLGetDrugInfoArgs()


def test_unknown_extra_field_rejected():
    # extra="forbid" - guards against a stray LLM-produced key silently
    # passing through into a tool call.
    with pytest.raises(ValidationError):
        PubMedSearchArgs(query="x", unexpected_field="y")


# ---------------------------------------------------------------------------
# ExecutionPlan / ToolExecutionResult basic shape
# ---------------------------------------------------------------------------


def test_execution_plan_with_calls():
    call = PubMedSearchCall(call_id="c1", arguments=PubMedSearchArgs(query="x"))
    plan = ExecutionPlan(plan_id="p1", calls=[call], status=PlanStatus.VALIDATED)
    assert plan.status == PlanStatus.VALIDATED
    assert len(plan.calls) == 1


def test_execution_plan_empty_needs_clarification():
    plan = ExecutionPlan(
        plan_id="p2",
        calls=[],
        status=PlanStatus.NO_EXECUTION_NEEDS_CLARIFICATION,
    )
    assert plan.calls == []
    assert plan.status == PlanStatus.NO_EXECUTION_NEEDS_CLARIFICATION


def test_tool_execution_result_construction():
    result = ToolExecutionResult(
        call_id="c1",
        tool_name=ToolName.PUBMED,
        status=ExecutionStatus.SUCCESS,
        records_count=3,
        latency_ms=125.4,
        retry_count=1,
        raw_result_ref=[{"pmid": "123"}],
        source_metadata={"client": "PubMedTool"},
    )
    assert result.status == ExecutionStatus.SUCCESS
    assert result.records_count == 3
