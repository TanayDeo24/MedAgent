"""Phase 9, Step 10 - deterministic tests for the PHASE9-DEFECT-002 fix
(MAX_TOOL_CALLS_PER_ROUND / MAX_TOOL_CALLS_PER_REQUEST bounding the number of
LOGICAL model-emitted tool_calls[] entries agent/nodes.py::tool_orchestration_node
will process). See docs/v2/PHASE9_FAILURE_ANALYSIS.md's PHASE9-DEFECT-002
entry and docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md's "BOUNDEDNESS
HARDENING" section for the full design writeup.

Calls `tool_orchestration_node` directly (not the full graph) for speed and
determinism - `call_cerebras_native_tools` and `execute_validated_call` are
monkeypatched; no real network call anywhere in this file."""

from __future__ import annotations

import json

import pytest

from agent.nodes import tool_orchestration_node
from agent.state import create_initial_state
from orchestration.candidate_b_native_tools import CerebrasNativeToolsResult
from research.loop_control import MAX_TOOL_CALLS_PER_REQUEST, MAX_TOOL_CALLS_PER_ROUND
from tools.base_tool import ToolResult


def _raw_call(i: int, valid: bool = True) -> dict:
    """One raw Cerebras-shaped tool_calls[] entry. `valid=True` builds a
    real, registry-valid `pubmed_search_pubmed` call; `valid=False` builds a
    call to an unregistered function name (fails at the
    `parse_and_validate_tool_call` "unregistered_tool" step, before ever
    reaching execution) - used to test the invalid-calls-consume-budget
    design decision."""
    name = "pubmed_search_pubmed" if valid else "not_a_real_tool_xyz"
    args = {"query": f"query-{i}"} if valid else {"whatever": i}
    return {
        "id": f"call-{i}",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _install_stubs(monkeypatch, raw_calls, execution_log):
    monkeypatch.setattr(
        "agent.nodes.call_cerebras_native_tools",
        lambda query: CerebrasNativeToolsResult(list(raw_calls), None, {}, 1.0, 1, None),
    )

    def _fake_execute(pydantic_call):
        execution_log.append(pydantic_call)
        return ToolResult(success=True, data=[{"pmid": "1"}], metadata={"timestamp": None}), 1.0

    monkeypatch.setattr("agent.nodes.execute_validated_call", _fake_execute)


def _state():
    return create_initial_state("test query")


class TestPerRoundBudget:
    def test_below_per_round_budget_all_processed(self, monkeypatch):
        n = MAX_TOOL_CALLS_PER_ROUND - 2
        raw_calls = [_raw_call(i) for i in range(n)]
        execution_log = []
        _install_stubs(monkeypatch, raw_calls, execution_log)
        state = _state()
        state = tool_orchestration_node(state)
        assert len(execution_log) == n
        assert len(state["tool_call_history"]) == n
        assert state["tool_calls_used_this_request"] == n
        assert not any(h.get("error_category") == "tool_call_budget_exhausted" for h in state["tool_call_history"])

    def test_exactly_at_per_round_budget_all_processed(self, monkeypatch):
        n = MAX_TOOL_CALLS_PER_ROUND
        raw_calls = [_raw_call(i) for i in range(n)]
        execution_log = []
        _install_stubs(monkeypatch, raw_calls, execution_log)
        state = _state()
        state = tool_orchestration_node(state)
        assert len(execution_log) == n
        assert state["tool_calls_used_this_request"] == n

    def test_over_per_round_budget_overflow_truncated_never_executed(self, monkeypatch):
        n = MAX_TOOL_CALLS_PER_ROUND + 5
        raw_calls = [_raw_call(i) for i in range(n)]
        execution_log = []
        _install_stubs(monkeypatch, raw_calls, execution_log)
        state = _state()
        state = tool_orchestration_node(state)
        # Exactly MAX_TOOL_CALLS_PER_ROUND calls actually executed - counted
        # via the real execution mock's own call log, not just inspecting
        # final state.
        assert len(execution_log) == MAX_TOOL_CALLS_PER_ROUND
        assert state["tool_calls_used_this_request"] == MAX_TOOL_CALLS_PER_ROUND
        budget_entries = [h for h in state["tool_call_history"] if h.get("error_category") == "tool_call_budget_exhausted"]
        assert len(budget_entries) == 1
        assert "5" in budget_entries[0]["error"]  # 5 overflow calls truncated

    def test_huge_tool_call_array_correctly_truncated(self, monkeypatch):
        n = 50
        raw_calls = [_raw_call(i) for i in range(n)]
        execution_log = []
        _install_stubs(monkeypatch, raw_calls, execution_log)
        state = _state()
        state = tool_orchestration_node(state)
        assert len(execution_log) == MAX_TOOL_CALLS_PER_ROUND
        assert state["tool_calls_used_this_request"] == MAX_TOOL_CALLS_PER_ROUND

    def test_deterministic_execution_ordering(self, monkeypatch):
        n = MAX_TOOL_CALLS_PER_ROUND + 5
        raw_calls = [_raw_call(i) for i in range(n)]
        execution_log = []
        _install_stubs(monkeypatch, raw_calls, execution_log)
        state = _state()
        tool_orchestration_node(state)
        executed_queries = [c.arguments.query for c in execution_log]
        assert executed_queries == [f"query-{i}" for i in range(MAX_TOOL_CALLS_PER_ROUND)]


class TestPerRequestBudgetAcrossRounds:
    def test_total_request_budget_reached_across_multiple_rounds(self, monkeypatch):
        """Simulates 2 rounds (as research_execution_node's real call chain
        does - the SAME state dict, `tool_orchestration_node` invoked twice)
        where the per-round cap alone would allow more than the remaining
        per-REQUEST budget - the request-global cap must bind tighter."""
        per_round = min(MAX_TOOL_CALLS_PER_ROUND, MAX_TOOL_CALLS_PER_REQUEST)
        state = _state()

        # Round 1: uses up MAX_TOOL_CALLS_PER_REQUEST - 3 total (assumes
        # MAX_TOOL_CALLS_PER_REQUEST > MAX_TOOL_CALLS_PER_ROUND, so this
        # takes multiple rounds - if not, this test still holds with 1
        # round consuming as much as allowed).
        target_used_before_final_round = MAX_TOOL_CALLS_PER_REQUEST - 3
        remaining = target_used_before_final_round
        round_num = 0
        execution_log = []
        while remaining > 0:
            this_round_n = min(MAX_TOOL_CALLS_PER_ROUND, remaining)
            raw_calls = [_raw_call(1000 * round_num + i) for i in range(this_round_n)]
            _install_stubs(monkeypatch, raw_calls, execution_log)
            state = tool_orchestration_node(state)
            remaining -= this_round_n
            round_num += 1

        assert state["tool_calls_used_this_request"] == target_used_before_final_round

        # Final round: model emits MAX_TOOL_CALLS_PER_ROUND calls, but only
        # 3 slots remain in the REQUEST-global budget - the per-request cap
        # must bind, not the (looser, in this situation) per-round cap.
        raw_calls_final = [_raw_call(9000 + i) for i in range(MAX_TOOL_CALLS_PER_ROUND)]
        _install_stubs(monkeypatch, raw_calls_final, execution_log)
        before_count = len(execution_log)
        state = tool_orchestration_node(state)
        newly_executed = len(execution_log) - before_count
        assert newly_executed == 3
        assert state["tool_calls_used_this_request"] == MAX_TOOL_CALLS_PER_REQUEST

    def test_request_budget_fully_exhausted_next_round_executes_zero(self, monkeypatch):
        state = _state()
        state["tool_calls_used_this_request"] = MAX_TOOL_CALLS_PER_REQUEST
        raw_calls = [_raw_call(i) for i in range(5)]
        execution_log = []
        _install_stubs(monkeypatch, raw_calls, execution_log)
        state = tool_orchestration_node(state)
        assert execution_log == []
        assert state["tool_calls_used_this_request"] == MAX_TOOL_CALLS_PER_REQUEST
        budget_entries = [h for h in state["tool_call_history"] if h.get("error_category") == "tool_call_budget_exhausted"]
        assert len(budget_entries) == 1


class TestInvalidCallsConsumeBudget:
    def test_invalid_registry_rejected_calls_still_consume_a_budget_slot(self, monkeypatch):
        """Design decision (documented in agent/nodes.py's
        tool_orchestration_node and research/loop_control.py): the budget
        counts every raw_tool_calls[] entry the model emitted, VALID OR
        INVALID - chosen so a response padded with many registry-invalid
        junk entries cannot bypass the budget's real purpose (bounding total
        processing effort, not just HTTP-reaching calls). This test proves
        that choice is actually implemented: a mix of invalid + valid calls
        still gets truncated at MAX_TOOL_CALLS_PER_ROUND total ENTRIES, not
        MAX_TOOL_CALLS_PER_ROUND valid entries."""
        n_invalid = MAX_TOOL_CALLS_PER_ROUND - 1
        raw_calls = [_raw_call(i, valid=False) for i in range(n_invalid)] + [_raw_call(999, valid=True)]
        # n_invalid + 1 == MAX_TOOL_CALLS_PER_ROUND exactly - the one valid
        # call is last, so it fits inside the budget and should still run.
        execution_log = []
        _install_stubs(monkeypatch, raw_calls, execution_log)
        state = _state()
        state = tool_orchestration_node(state)
        assert len(execution_log) == 1  # the one valid call, executed
        rejected = [h for h in state["tool_call_history"] if h.get("error_category") == "unregistered_tool"]
        assert len(rejected) == n_invalid
        assert state["tool_calls_used_this_request"] == MAX_TOOL_CALLS_PER_ROUND

        # Now push the valid call PAST the budget by adding one more invalid
        # call before it - it should be truncated away and NEVER executed,
        # proving invalid entries really do consume slots that would
        # otherwise have gone to the valid call.
        execution_log2 = []
        raw_calls2 = [_raw_call(i, valid=False) for i in range(MAX_TOOL_CALLS_PER_ROUND)] + [_raw_call(999, valid=True)]
        _install_stubs(monkeypatch, raw_calls2, execution_log2)
        state2 = _state()
        state2 = tool_orchestration_node(state2)
        assert execution_log2 == []  # the valid call never even reached parsing


class TestRetriesNotMiscountedAsNewLogicalCalls:
    def test_a_single_logical_call_consumes_exactly_one_budget_slot_regardless_of_http_retries(self, monkeypatch):
        """RetrySession's HTTP-level retries happen INSIDE execute_validated_call
        (a single logical call) and must never be counted as multiple
        logical tool_calls entries. Simulated here by execute_validated_call
        itself performing several internal "attempts" before returning once
        - the budget must still see this as ONE logical call."""
        attempts_made = []

        def _flaky_execute(pydantic_call):
            # Simulate RetrySession's internal retry loop: several internal
            # attempts, one logical call.
            for _ in range(4):
                attempts_made.append(1)
            return ToolResult(success=True, data=[{"pmid": "1"}], metadata={"timestamp": None}), 1.0

        monkeypatch.setattr(
            "agent.nodes.call_cerebras_native_tools",
            lambda query: CerebrasNativeToolsResult([_raw_call(0)], None, {}, 1.0, 1, None),
        )
        monkeypatch.setattr("agent.nodes.execute_validated_call", _flaky_execute)
        state = _state()
        state = tool_orchestration_node(state)
        assert len(attempts_made) == 4  # 4 real HTTP-level attempts happened
        assert state["tool_calls_used_this_request"] == 1  # but exactly 1 logical call


class TestEvidencePreservedAndNoFalseSufficiency:
    def test_evidence_from_allowed_non_overflow_calls_is_preserved(self, monkeypatch):
        n = MAX_TOOL_CALLS_PER_ROUND + 3
        raw_calls = [_raw_call(i) for i in range(n)]
        execution_log = []
        _install_stubs(monkeypatch, raw_calls, execution_log)
        state = _state()
        state = tool_orchestration_node(state)
        # Every ALLOWED call's tool_results entry is preserved (data merged
        # into state["tool_results"]).
        assert state["tool_results"]["pubmed"] is not None
        assert len(state["tool_results"]["pubmed"]) == MAX_TOOL_CALLS_PER_ROUND

    def test_no_false_sufficient_evidence_with_real_gaps_remaining_after_truncation(self, monkeypatch):
        """If a MISSING_SOURCE_CATEGORY gap exists for a source whose tool
        call got truncated by the budget, gap_analysis must still report it
        as an open gap (it simply reflects reality: that source category is
        genuinely absent from state["evidence"] because its call never
        ran) - proven at the gap_analysis layer directly, since that is
        where SUFFICIENT_EVIDENCE would incorrectly fire if this were
        broken."""
        from research.gap_analysis import analyze_gaps
        from research.models import GapType

        state = {
            "evidence": [],  # the chembl/clinicaltrials call was truncated - genuinely no evidence
            "grounded_answer": None,
            "research_query_raw": {"requested_evidence_types": ["chembl"]},
        }
        gaps = analyze_gaps(state)
        assert any(g.gap_type == GapType.NO_EVIDENCE for g in gaps)
