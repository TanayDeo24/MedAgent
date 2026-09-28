"""Integration tests for the Phase-8 research-loop nodes
(agent/nodes.py's gap_analysis_node/should_continue_research_loop/
research_action_planning_node/research_execution_node/evidence_merge_node)
and their graph wiring (agent/graph.py::build_research_loop_graph).

Live-tool network is blocked in this session (see
docs/v2/PHASE8_INITIAL_AUDIT.md Section 7), so `call_cerebras_native_tools`
and `execute_validated_call` are mocked here exactly as the pre-existing
`tests/test_nodes.py::test_hallucinated_tool_name_recorded_as_precision_miss`
already does for the same node - no real HTTP/LLM call in this file."""

import json
from unittest.mock import patch

from agent.graph import build_agent_graph, build_research_loop_graph
from agent.nodes import (
    evidence_merge_node,
    gap_analysis_node,
    research_action_planning_node,
    research_execution_node,
    should_continue_research_loop,
)
from agent.state import create_initial_state
from evidence.models import (
    ChemblEvidenceMetadata,
    ContentFormat,
    Evidence,
    EvidenceType,
    Provenance,
    SourceType,
    make_evidence_id,
    make_source_url,
)
from generation.models import ClaimType, GenerationMetadata, GroundedAnswer, GroundedClaim
from orchestration.candidate_b_native_tools import CerebrasNativeToolsResult
from research.loop_control import MAX_RESEARCH_ITERATIONS
from tools.base_tool import ToolResult


def _ev(record_id="CHEMBL1", content="Some content"):
    return Evidence(
        evidence_id=make_evidence_id(SourceType.CHEMBL, record_id),
        source_type=SourceType.CHEMBL, source_record_id=record_id,
        source_url=make_source_url(SourceType.CHEMBL, record_id),
        evidence_type=EvidenceType.COMPOUND_IDENTITY, content=content,
        content_format=ContentFormat.FIELD_VALUE,
        source_metadata=ChemblEvidenceMetadata(),
        provenance=Provenance(retrieval_method="get_drug_info"),
    )


def _answer(claims, abstained=False):
    return GroundedAnswer(
        answer_id="ans-1", query="q", claims=claims, rendered_text="text",
        citations=[], references=[], used_evidence_ids=[], unused_evidence_ids=[],
        abstained=abstained, conflict_detected=False,
        generation_metadata=GenerationMetadata(
            architecture="candidate_b_structured", model="qwen-3.8-27b", llm_calls=1,
            provider="cerebras", latency_ms=1.0,
        ),
    )


def _base_state(evidence=None, grounded_answer=None):
    state = create_initial_state(query="What is known about CHEMBL1?", max_iterations=10)
    state["evidence"] = evidence or []
    state["grounded_answer"] = grounded_answer
    state["current_step"] = 0
    return state


# --- gap_analysis_node + should_continue_research_loop wiring ---

def test_sufficient_evidence_stops_immediately(monkeypatch):
    ev = _ev()
    claim = GroundedClaim(claim_id="c-0", text="x", evidence_ids=[ev.evidence_id], claim_type=ClaimType.FACTUAL)
    monkeypatch.setattr(
        "research.gap_analysis.judge_claim_semantic",
        lambda cid, txt, eids, ebi: __import__("grounding_eval.models", fromlist=["ClaimGroundingJudgment"]).ClaimGroundingJudgment(
            claim_id=cid, support_label=__import__("grounding_eval.models", fromlist=["SupportLabel"]).SupportLabel.SUPPORTED,
            citation_judgments=[], supporting_evidence_ids=list(eids), unsupported_fragments=[], reason_code="ok",
        ),
    )
    state = _base_state(evidence=[ev], grounded_answer=_answer([claim]))
    state = gap_analysis_node(state)
    assert should_continue_research_loop(state) == "stop"
    assert state["research_stop_reason"] == "sufficient_evidence"


def test_no_evidence_gap_requests_continue_then_safe_abstains():
    state = _base_state(evidence=[], grounded_answer=None)
    state = gap_analysis_node(state)
    assert should_continue_research_loop(state) == "continue"

    # Simulate the follow-up having already been attempted once with no result.
    state["research_attempted_no_evidence"] = True
    state = gap_analysis_node(state)  # still no evidence
    assert should_continue_research_loop(state) == "stop"
    assert state["research_stop_reason"] == "safe_abstention"


def test_budget_exhausted_even_with_gaps_remaining():
    state = _base_state(evidence=[], grounded_answer=None)
    state = gap_analysis_node(state)
    state["research_iteration"] = MAX_RESEARCH_ITERATIONS
    assert should_continue_research_loop(state) == "stop"
    assert state["research_stop_reason"] == "budget_exhausted"


# --- research_action_planning_node + research_execution_node + evidence_merge_node ---

def _mock_cerebras_one_chembl_call():
    return CerebrasNativeToolsResult(
        raw_tool_calls=[{
            "id": "call_1", "type": "function",
            "function": {"name": "chembl_get_drug_info", "arguments": json.dumps({"chembl_id": "CHEMBL999"})},
        }],
        message_content=None, usage={"total_tokens": 10}, latency_ms=1.0, llm_calls=1, error=None,
    )


@patch("agent.nodes.execute_validated_call")
@patch("agent.nodes.call_cerebras_native_tools")
def test_productive_followup_adds_new_evidence_and_dedupes_on_rediscovery(mock_cerebras, mock_execute):
    mock_cerebras.return_value = _mock_cerebras_one_chembl_call()
    mock_execute.return_value = (
        ToolResult(success=True, data={
            "chembl_id": "CHEMBL999", "name": "TESTDRUG", "molecule_type": "Small molecule",
            "mechanism_of_action": "Not available", "max_phase": 4,
        }, metadata={"timestamp": None}),
        5.0,
    )

    state = _base_state(evidence=[], grounded_answer=None)
    state = gap_analysis_node(state)  # -> NO_EVIDENCE gap
    assert should_continue_research_loop(state) == "continue"
    state = research_action_planning_node(state)
    state = research_execution_node(state)
    state = evidence_merge_node(state)

    assert len(state["evidence"]) == 1
    assert state["research_actions"][-1]["status"] == "executed_productive"
    assert state["research_actions"][-1]["new_evidence_ids"] == [state["evidence"][0].evidence_id]
    assert state["evidence_duplicate_count"] == 0

    # Second iteration rediscovers the SAME record (network still mocked to
    # return the identical compound) - must be counted as a duplicate, not
    # as new research progress, and must not double the Evidence list.
    state["research_gaps"] = [{
        "gap_id": "gap-x", "gap_type": "missing_source_category", "description": "d",
        "target_source_category": "chembl", "related_claim_id": None, "severity": 0.9,
    }]
    state = research_action_planning_node(state)
    state = research_execution_node(state)
    state = evidence_merge_node(state)

    assert len(state["evidence"]) == 1  # still just one unique record
    # tool_results accumulates raw records across iterations (Phase 3's
    # existing, unmodified behavior) and Phase 5 recomputes Evidence[] from
    # scratch each time, so this rediscovery round sees 2 raw CHEMBL999
    # records (1 from each iteration's tool call), both collapsing to the
    # same evidence_id - both are correctly discarded as duplicates.
    assert state["evidence_duplicate_count"] == 2
    assert state["research_actions"][-1]["new_evidence_ids"] == []


@patch("agent.nodes.execute_validated_call")
@patch("agent.nodes.call_cerebras_native_tools")
def test_unproductive_followup_marks_tool_failure_and_increments_consecutive_rounds(mock_cerebras, mock_execute):
    mock_cerebras.return_value = _mock_cerebras_one_chembl_call()
    mock_execute.return_value = (ToolResult(success=False, data=None, error="upstream 503"), 5.0)

    state = _base_state(evidence=[], grounded_answer=None)
    state = gap_analysis_node(state)
    state = research_action_planning_node(state)
    state = research_execution_node(state)

    assert state["research_actions"][-1]["status"] == "executed_unproductive"
    assert state["research_consecutive_failure_rounds"] == 1


def test_no_planned_action_leaves_state_unchanged_when_execution_called_anyway():
    """If, for any reason, research_execution_node is invoked with no
    plannable action (e.g. every gap already attempted), it must be a
    no-op, never crash and never fabricate an action."""
    state = _base_state(evidence=[], grounded_answer=None)
    state = gap_analysis_node(state)
    state["research_actions"] = [{
        "gap_signature": "no_evidence::", "status": "executed_unproductive",
    }]
    before = dict(state)
    state = research_execution_node(state)
    assert state.get("research_tool_calls_used", 0) == before.get("research_tool_calls_used", 0)


def test_final_generation_receives_the_final_merged_evidence(monkeypatch):
    """grounded_generation_node must be called with exactly
    state["evidence"] (the post-merge set) - never a stale pre-merge copy."""
    from agent.nodes import grounded_generation_node

    captured = {}

    def _fake_generate(query, evidence, architecture):
        captured["evidence_ids"] = sorted(e.evidence_id for e in evidence)
        return _answer([])

    monkeypatch.setattr("agent.nodes.generate_grounded_answer", _fake_generate)

    ev1, ev2 = _ev("CHEMBL1"), _ev("CHEMBL2")
    state = _base_state(evidence=[ev1, ev2], grounded_answer=None)
    state = grounded_generation_node(state)
    assert captured["evidence_ids"] == sorted([ev1.evidence_id, ev2.evidence_id])


def test_pre_phase8_graph_unaffected():
    """build_agent_graph() must still compile and expose the exact
    pre-Phase-8 node set - Phase 8 is additive only."""
    graph = build_agent_graph()
    node_names = set(graph.get_graph().nodes.keys())
    assert "verification" in node_names
    assert "gap_analysis" not in node_names


def test_research_loop_graph_has_no_verification_node():
    graph = build_research_loop_graph()
    node_names = set(graph.get_graph().nodes.keys())
    assert "gap_analysis" in node_names
    assert "verification" not in node_names
