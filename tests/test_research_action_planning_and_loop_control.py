"""Offline, deterministic tests for research/action_planning.py and
research/loop_control.py - no LLM/network calls anywhere in this file."""

from research.action_planning import action_signature, plan_actions
from research.loop_control import (
    MAX_CONSECUTIVE_TOOL_FAILURE_ROUNDS,
    MAX_RESEARCH_ITERATIONS,
    MAX_TOOL_CALLS_TOTAL,
    attempted_signatures,
    decide_stop_reason,
)
from research.models import EvidenceGap, GapType, ResearchActionStatus, StopReason


def _gap(gap_id="g1", gap_type=GapType.MISSING_SOURCE_CATEGORY, target="pubmed", claim=None, severity=0.7):
    return EvidenceGap(gap_id=gap_id, gap_type=gap_type, description="d",
                        target_source_category=target, related_claim_id=claim, severity=severity)


# --- action_planning.py ---

def test_plan_actions_picks_highest_severity_gap():
    low = _gap(gap_id="g-low", target="chembl", severity=0.3)
    high = _gap(gap_id="g-high", target="pubmed", severity=0.9)
    actions = plan_actions([low, high], "orig query", iteration=1, already_attempted_signatures=set())
    assert len(actions) == 1
    assert actions[0].gap_id == "g-high"


def test_plan_actions_skips_already_attempted_signature():
    gap = _gap(gap_id="g1", target="pubmed", severity=0.9)
    sig = action_signature(gap)
    actions = plan_actions([gap], "orig query", iteration=2, already_attempted_signatures={sig})
    assert actions == []


def test_plan_actions_bounded_to_one_per_iteration():
    gaps = [_gap(gap_id=f"g{i}", target="pubmed", claim=f"c-{i}", severity=0.9) for i in range(5)]
    actions = plan_actions(gaps, "q", iteration=1, already_attempted_signatures=set())
    assert len(actions) == 1


def test_followup_query_for_no_evidence_gap_uses_original_query():
    gap = _gap(gap_id="gap-no-evidence", gap_type=GapType.NO_EVIDENCE, target=None)
    actions = plan_actions([gap], "What is EGFR?", iteration=1, already_attempted_signatures=set())
    assert actions[0].followup_query == "What is EGFR?"


def test_followup_query_for_missing_source_names_the_source():
    gap = _gap(target="chembl")
    actions = plan_actions([gap], "orig", iteration=1, already_attempted_signatures=set())
    assert "ChEMBL" in actions[0].followup_query


def test_action_signature_is_stable_and_distinguishes_gaps():
    a = _gap(gap_id="g1", target="pubmed", claim="c-1")
    b = _gap(gap_id="g2", target="pubmed", claim="c-1")
    c = _gap(gap_id="g3", target="chembl", claim="c-1")
    assert action_signature(a) == action_signature(b)  # same type/target/claim -> same signature
    assert action_signature(a) != action_signature(c)


# --- loop_control.py ---

def test_decide_stop_sufficient_evidence_when_no_gaps():
    assert decide_stop_reason([], [], iteration=0, tool_calls_used=0,
                               consecutive_failure_rounds=0, attempted_no_evidence_before=False) == StopReason.SUFFICIENT_EVIDENCE


def test_decide_stop_safe_abstention_on_repeated_no_evidence():
    gap = _gap(gap_id="gap-no-evidence", gap_type=GapType.NO_EVIDENCE, target=None)
    result = decide_stop_reason([gap], [], iteration=1, tool_calls_used=1,
                                 consecutive_failure_rounds=0, attempted_no_evidence_before=True)
    assert result == StopReason.SAFE_ABSTENTION


def test_decide_stop_none_when_no_evidence_not_yet_attempted():
    gap = _gap(gap_id="gap-no-evidence", gap_type=GapType.NO_EVIDENCE, target=None)
    actions = plan_actions([gap], "q", 1, set())
    result = decide_stop_reason([gap], actions, iteration=0, tool_calls_used=0,
                                 consecutive_failure_rounds=0, attempted_no_evidence_before=False)
    assert result is None


def test_decide_stop_tool_failure_limit():
    gap = _gap()
    result = decide_stop_reason([gap], [], iteration=0, tool_calls_used=0,
                                 consecutive_failure_rounds=MAX_CONSECUTIVE_TOOL_FAILURE_ROUNDS,
                                 attempted_no_evidence_before=False)
    assert result == StopReason.TOOL_FAILURE_LIMIT


def test_decide_stop_budget_exhausted_on_iteration_limit():
    gap = _gap()
    result = decide_stop_reason([gap], [], iteration=MAX_RESEARCH_ITERATIONS, tool_calls_used=0,
                                 consecutive_failure_rounds=0, attempted_no_evidence_before=False)
    assert result == StopReason.BUDGET_EXHAUSTED


def test_decide_stop_budget_exhausted_on_tool_call_limit():
    gap = _gap()
    result = decide_stop_reason([gap], [], iteration=0, tool_calls_used=MAX_TOOL_CALLS_TOTAL,
                                 consecutive_failure_rounds=0, attempted_no_evidence_before=False)
    assert result == StopReason.BUDGET_EXHAUSTED


def test_decide_stop_no_productive_action_when_gaps_remain_but_all_attempted():
    gap = _gap()
    result = decide_stop_reason([gap], [], iteration=0, tool_calls_used=0,
                                 consecutive_failure_rounds=0, attempted_no_evidence_before=False)
    assert result == StopReason.NO_PRODUCTIVE_ACTION


def test_decide_stop_none_when_productive_action_available():
    gap = _gap()
    actions = plan_actions([gap], "q", 1, set())
    result = decide_stop_reason([gap], actions, iteration=0, tool_calls_used=0,
                                 consecutive_failure_rounds=0, attempted_no_evidence_before=False)
    assert result is None


def test_decide_stop_never_infinite_for_a_persistently_unresolved_gap():
    """A gap that keeps re-appearing every iteration (e.g. the judge keeps
    flagging the same claim) must still terminate within
    MAX_RESEARCH_ITERATIONS - the loop must never depend on the gap itself
    resolving to stop."""
    gap = _gap(gap_id="persistent", target="pubmed")
    already = set()
    for iteration in range(MAX_RESEARCH_ITERATIONS + 2):
        actions = plan_actions([gap], "q", iteration + 1, already)
        result = decide_stop_reason([gap], actions, iteration=iteration, tool_calls_used=iteration,
                                     consecutive_failure_rounds=0, attempted_no_evidence_before=False)
        if result is not None:
            assert result in (StopReason.BUDGET_EXHAUSTED, StopReason.NO_PRODUCTIVE_ACTION)
            return
        already.add(action_signature(gap))
    raise AssertionError("loop never terminated within MAX_RESEARCH_ITERATIONS+2")


def test_attempted_signatures_reads_gap_signature_field():
    history = [{"gap_signature": "sig-a"}, {"gap_signature": "sig-b"}, {"other": "x"}]
    assert attempted_signatures(history) == {"sig-a", "sig-b"}


def test_attempted_signatures_empty_for_empty_history():
    assert attempted_signatures([]) == set()
