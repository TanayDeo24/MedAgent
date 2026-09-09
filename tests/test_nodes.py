"""Unit tests for agent nodes.

Covers regressions found during manual verification passes that the
existing per-tool test suites don't exercise, since those test the tools
in isolation rather than how `agent/nodes.py` consumes their parsed output.
"""

from unittest.mock import Mock, patch

from agent.nodes import report_generation_node


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
    mock_llm.invoke.return_value = Mock(content="# Research Report\n\nBody text.")
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
    mock_llm.invoke.return_value = Mock(content="# Research Report\n\nBody text.")
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
