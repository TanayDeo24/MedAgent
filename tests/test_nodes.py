"""Unit tests for agent nodes.

Covers regressions found during manual verification passes that the
existing per-tool test suites don't exercise, since those test the tools
in isolation rather than how `agent/nodes.py` consumes their parsed output.
"""

import json
from unittest.mock import Mock, patch

from agent.nodes import report_generation_node, query_analysis_node, tool_orchestration_node
from orchestration.candidate_b_native_tools import CerebrasNativeToolsResult


def _base_state(tool_results):
    """Minimal AgentState dict sufficient for report_generation_node."""
    return {
        "query": "What drugs are approved to treat melanoma?",
        "research_plan": "{}",
        "tool_results": tool_results,
        "intermediate_thoughts": [],
        "errors": [],
    }


@patch("agent.nodes.get_llm")
def test_chembl_citations_use_parsed_field_names(mock_get_llm):
    """Regression test for the citations field-name bug (see
    CITATIONS_BUG_INVESTIGATION.md).

    report_generation_node's citations builder must read the same keys
    ChEMBLTool's parsers actually produce (`chembl_id`, `name`/`drug_name`),
    not the raw pre-parse ChEMBL API field names (`molecule_chembl_id`,
    `pref_name`) which never exist on `tool_results["chembl"]` entries by
    the time this node sees them. Before the fix, every ChEMBL citation's
    `id` and `name` silently fell through to "N/A" regardless of whether
    the underlying compound had real data - undetected across 4 prior
    verification passes because nothing checked `state["citations"]`'s
    actual field values.
    """
    mock_llm = Mock()
    mock_llm.invoke.return_value = Mock(
        content="# Research Report\n\nBody text.",
        usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
    )
    mock_get_llm.return_value = mock_llm

    tool_results = {
        "chembl": [
            # A target-search-style entry (uses "name").
            {
                "chembl_id": "CHEMBL1229517",
                "name": "VEMURAFENIB",
                "max_phase": 4,
                "development_phase": "Approved",
            },
            # An indication-search-style entry (uses "drug_name").
            {
                "chembl_id": "CHEMBL467",
                "drug_name": "HYDROXYUREA",
                "max_phase": 4,
            },
            # An entry that is still genuinely unnamed after backfill -
            # id must still be populated, name correctly stays "N/A".
            {
                "chembl_id": "CHEMBL999999",
                "name": "",
                "drug_name": "",
                "max_phase": 0,
            },
        ]
    }

    state = _base_state(tool_results)
    result_state = report_generation_node(state)

    chembl_citations = [c for c in result_state["citations"] if c["source"] == "ChEMBL"]
    assert len(chembl_citations) == 3

    by_id = {c["id"]: c for c in chembl_citations}

    # Real chembl_id must never be "N/A" - it's essentially always present
    # on a parsed ChEMBL entry, backfilled or not.
    assert "CHEMBL1229517" in by_id
    assert "CHEMBL467" in by_id
    assert "CHEMBL999999" in by_id
    assert all(c["id"] != "N/A" for c in chembl_citations)

    # Names must reflect the entry's real data, matching whichever field
    # (name for target search, drug_name for indication search) is set.
    assert by_id["CHEMBL1229517"]["name"] == "VEMURAFENIB"
    assert by_id["CHEMBL467"]["name"] == "HYDROXYUREA"

    # A compound genuinely unnamed after backfill should still show a real
    # id, with name correctly falling back to "N/A" (this is expected, not
    # a bug - see CHEMBL_BACKFILL_COMPLETE.md on ChEMBL's own data gaps).
    assert by_id["CHEMBL999999"]["name"] == "N/A"


@patch("agent.nodes.get_llm")
def test_chembl_citation_id_never_na_when_chembl_id_present(mock_get_llm):
    """Broader regression guard: for any ChEMBL citation, if the source
    tool_results entry has a non-empty chembl_id, the citation's id field
    must not be "N/A". This is the general property the field-name bug
    violated for every ChEMBL entry, regardless of name/backfill status.
    """
    mock_llm = Mock()
    mock_llm.invoke.return_value = Mock(
        content="# Research Report\n\nBody text.",
        usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
    )
    mock_get_llm.return_value = mock_llm

    tool_results = {
        "chembl": [
            {"chembl_id": f"CHEMBL{i}", "name": f"COMPOUND_{i}", "max_phase": i % 5}
            for i in range(1, 6)
        ]
    }

    state = _base_state(tool_results)
    result_state = report_generation_node(state)

    for entry, citation in zip(tool_results["chembl"], result_state["citations"]):
        if entry.get("chembl_id"):
            assert citation["id"] == entry["chembl_id"]
            assert citation["id"] != "N/A"


@patch("nlu.extractor.requests.post")
def test_token_usage_accumulates_across_calls(mock_post):
    """total_tokens_used (Phase 2, item 2) was declared on AgentState but
    never populated by any node. Verify query_analysis_node's own token
    accumulation (agent/nodes.py, reading nlu_result.token_usage) adds each
    call's real usage into the running state total, and that
    _accumulate_tokens (the separate ChatNVIDIA-response helper used by
    other, get_llm-based nodes) adds on top of that rather than overwriting
    it.

    Frozen architecture is candidate_g_cerebras_qwen (config_version 3, see
    docs/v2/PHASE2_CEREBRAS_QWEN_EXPERIMENT.md), which calls Cerebras
    directly via requests.post (not the NVIDIA get_llm() abstraction) - the
    mock target and response envelope shape reflect that call site.
    """
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps({
            "intent": ["A_literature_evidence"],
            "intent_confidence": 0.5,
            "entities": [],
            "constraints": {},
            "requested_evidence_types": [],
            "ambiguity": {"is_ambiguous": False, "ambiguity_reason": None, "candidate_interpretations": []},
            "extraction_confidence": 0.5,
        })}}],
        "usage": {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50},
    }
    mock_post.return_value = resp

    state = {
        "query": "What are EGFR inhibitors?",
        "intermediate_thoughts": [],
        "errors": [],
        "messages": [],
        "total_tokens_used": 0,
    }

    state = query_analysis_node(state)
    assert state["total_tokens_used"] == 50

    # A second, independent LLM call (simulated via _accumulate_tokens - the
    # helper other, get_llm-based nodes use for a langchain-style response
    # object) must add to the running total, not overwrite it.
    from agent.nodes import _accumulate_tokens
    fake_langchain_response = Mock(usage_metadata={"input_tokens": 40, "output_tokens": 10, "total_tokens": 50})
    _accumulate_tokens(state, fake_langchain_response)
    assert state["total_tokens_used"] == 100


@patch("agent.nodes.call_cerebras_native_tools")
def test_hallucinated_tool_name_recorded_as_precision_miss(mock_call_cerebras):
    """Regression guard for the Nemotron/hallucinated-tool-name fix (Phase 2
    item 3), rewritten for the Phase 3 integrated pipeline
    (docs/v2/PHASE3_TOOL_ORCHESTRATION.md Step 34). The OLD version of this
    test injected a hallucinated name directly into
    state["tools_to_call"] and called the (now-removed) tool_execution_node
    - a pre-injected bypass that never exercised real tool *selection*, only
    the dict-membership guard at execution time (see
    docs/v2/PHASE3_INITIAL_ORCHESTRATION_AUDIT.md Section B). This version
    mocks only the Cerebras HTTP call (same style as
    tests/test_candidate_b_native_tools.py - no real network call), so a
    hallucinated function name now flows through the REAL
    tool_orchestration_node -> parse_and_validate_tool_call() ->
    orchestration/registry.py boundary, and the test asserts on that real
    code path's outcome instead of a pre-set bypass.

    A hallucinated function name ("pubchem_search", not one of the 5
    declared tools) must never reach execution, but must still be recorded
    in tool_call_history with a call_id and a typed failure_category
    (`unregistered_tool`) so AgentMetrics.tool_precision (which reads
    tool_call_history) counts it as a miss instead of it silently
    vanishing.
    """
    mock_call_cerebras.return_value = CerebrasNativeToolsResult(
        raw_tool_calls=[
            {
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "pubchem_search",  # not a real declared tool - hallucinated
                    "arguments": json.dumps({"query": "EGFR inhibitors"}),
                },
            }
        ],
        message_content=None,
        usage={"input_tokens": 50, "output_tokens": 20, "total_tokens": 70},
        latency_ms=123.0,
        llm_calls=1,
        error=None,
    )

    state = {
        "query": "What are EGFR inhibitors?",
        "research_plan": "{}",
        "tool_results": {},
        "tool_call_history": [],
        "intermediate_thoughts": [],
        "errors": [],
        "current_step": 0,
        "max_iterations": 3,
        "total_tokens_used": 0,
    }

    result_state = tool_orchestration_node(state)

    # Recorded as a miss, with a call_id and typed failure category -
    # closing the "no call_id anywhere" hard-gate defect Candidate A failed
    # on (docs/v2/PHASE3_WINNER_SELECTION.md Section 1).
    assert len(result_state["tool_call_history"]) == 1
    entry = result_state["tool_call_history"][0]
    assert entry["tool"] == "pubchem_search"
    assert entry["success"] is False
    assert entry["error_category"] == "unregistered_tool"
    assert entry["call_id"]

    # Never reached execution: no real tool ran, so tool_results/
    # tools_to_call show no successful selection at all.
    assert result_state["tool_results"] == {}
    assert result_state["tools_to_call"] == []

    # Cerebras was called exactly once (no retry) and no other network
    # boundary was touched.
    mock_call_cerebras.assert_called_once_with(state["query"])
    assert result_state["total_tokens_used"] == 70
