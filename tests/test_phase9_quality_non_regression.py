"""Phase 9, Step 11 - quality non-regression: proves the two new Phase-9
BOUNDEDNESS HARDENING budgets (CLAIM_EVALUATION_BUDGET,
MAX_TOOL_CALLS_PER_ROUND/MAX_TOOL_CALLS_PER_REQUEST) are DORMANT no-ops for
an ordinary workload well below both thresholds - i.e. a normal request's
claims/Evidence-IDs/citations/provenance/stop-reason/grounding-status/
research-iteration-count behavior is byte-for-byte/field-for-field identical
to what the pre-existing (pre-Phase-9) code path would have produced.

Two complementary angles, per the governing directive's own suggestion:
1. A full stubbed `MedAgent(research_loop=True).run()` (mirrors
   tests/test_phase9_concurrency_audit.py's `_install_rich_state_stubs_once`
   pattern) asserting every relevant field, PLUS asserting the two new
   budget counters stay far below their thresholds and never produce any
   budget-related gap/history entry - i.e. the guard conditions are never
   even reached, not just "reached but harmless".
2. A direct code-level demonstration (not just a comment) that when
   len(claims) <= CLAIM_EVALUATION_BUDGET and
   len(raw_tool_calls) <= MAX_TOOL_CALLS_PER_ROUND, analyze_gaps's
   `if budget_remaining <= 0` branch and tool_orchestration_node's
   `if total_emitted > round_budget` branch are provably never entered -
   asserted via the same call-count/history-entry checks used everywhere
   else in this pass (mock call counts, not just returned state), so this
   is a real passing test, not a prose assertion.

No real network call anywhere in this file."""

from __future__ import annotations

import json

import pytest

from agent.graph import MedAgent
from agent.nodes import tool_orchestration_node
from agent.state import create_initial_state
from orchestration.candidate_b_native_tools import CerebrasNativeToolsResult
from research.gap_analysis import analyze_gaps
from research.loop_control import CLAIM_EVALUATION_BUDGET, MAX_TOOL_CALLS_PER_ROUND
from tools.base_tool import ToolResult


@pytest.fixture(autouse=True)
def _pin_batch_size_to_one(monkeypatch):
    """Written before Phase-9 PAIR BATCHING existed - the claim-budget guard
    test here mocks ONLY the single-claim judge_claim_semantic across many
    factual claims. Pin GAP_ANALYSIS_BATCH_SIZE to its pre-batching value
    (1) so this file (which tests budget-guard non-regression, not
    batching) never silently routes a claim group to the real, unmocked
    judge_claims_batch (production default now 2)."""
    monkeypatch.setattr("research.gap_analysis.GAP_ANALYSIS_BATCH_SIZE", 1)


@pytest.fixture(autouse=True)
def _enforce_no_network(no_network):
    """PHASE9-PROCESS-DEV-003 remediation (see
    docs/v2/PHASE9_FAILURE_ANALYSIS.md): this file's claim-budget guard test
    constructs CLAIM_EVALUATION_BUDGET-1 (31) real factual claims while
    mocking only judge_claim_semantic, with no explicit network isolation.
    Forces the opt-in `no_network` fixture (tests/conftest.py) active for
    every test in this module regardless of each test's own signature, by
    declaring it as this autouse fixture's own dependency - so any future
    change that routes a claim group through the real, unmocked
    judge_claims_batch fails loudly instead of attempting a real call."""
    yield


# ---------------------------------------------------------------------------
# Angle 1: full stubbed graph run, well under both budgets
# ---------------------------------------------------------------------------


def _install_normal_workload_stubs(monkeypatch):
    """A single, non-concurrent, realistic-shaped stub: 1 tool call
    selected, 1 factual claim produced with real Evidence, zero gaps (clean
    sufficient_evidence stop) - deliberately far under both
    CLAIM_EVALUATION_BUDGET (32) and MAX_TOOL_CALLS_PER_ROUND (12)."""
    from evidence.models import (
        ChemblEvidenceMetadata, ContentFormat, Evidence, EvidenceType,
        Provenance, SourceType, make_evidence_id, make_source_url,
    )
    from generation.models import (
        CitationEntry, ClaimType, GenerationMetadata, GroundedAnswer,
        GroundedClaim, SourceReference,
    )
    from nlu.schemas import NLUExtractionResult, ResearchQuery

    source_record_id = "CHEMBL999"
    evidence_id = make_evidence_id(SourceType.CHEMBL, source_record_id)

    def _fake_nlu(query):
        return NLUExtractionResult(
            schema_valid=True,
            research_query=ResearchQuery(original_query=query, normalized_query=query),
            architecture="mock",
        )

    class _FakeLLMResp:
        content = '{"key_findings": [], "connections": [], "gaps": [], "completeness_assessment": "n/a"}'

    class _FakeLLM:
        def invoke(self, *a, **k):
            return _FakeLLMResp()

    def _fake_evidence_normalization_node(state):
        ev = Evidence(
            evidence_id=evidence_id,
            source_type=SourceType.CHEMBL,
            source_record_id=source_record_id,
            source_url=make_source_url(SourceType.CHEMBL, source_record_id),
            evidence_type=EvidenceType.COMPOUND_IDENTITY,
            content="Normal single-evidence content.",
            content_format=ContentFormat.VERBATIM_TEXT,
            title="Title",
            source_metadata=ChemblEvidenceMetadata(),
            provenance=Provenance(call_id="call1", retrieval_method="tool_call"),
        )
        state["evidence"] = [ev]
        return state

    def _fake_grounded_generation_node(state):
        claim = GroundedClaim(
            claim_id="claim-1",
            text="A single well-supported claim.",
            evidence_ids=[evidence_id],
            claim_type=ClaimType.FACTUAL,
            qualifier=None,
        )
        answer = GroundedAnswer(
            answer_id="answer-1",
            query=state["query"],
            claims=[claim],
            rendered_text="Rendered text for claim-1.",
            citations=[CitationEntry(number=1, evidence_ids=[evidence_id], source_reference_index=0)],
            references=[
                SourceReference(
                    number=1, source_type=SourceType.CHEMBL, source_record_id=source_record_id,
                    source_url=make_source_url(SourceType.CHEMBL, source_record_id),
                    grouped_evidence_ids=[evidence_id],
                )
            ],
            used_evidence_ids=[evidence_id],
            unused_evidence_ids=[],
            abstained=False,
            conflict_detected=False,
            generation_metadata=GenerationMetadata(
                architecture="mock", provider="mock", model="mock", llm_calls=0, latency_ms=1.0,
            ),
        )
        state["grounded_answer"] = answer
        return state

    judge_calls = []

    def _real_judge_supported(claim_id, claim_text, evidence_ids, evidence_by_id):
        judge_calls.append(claim_id)
        from grounding_eval.models import CitationGroundingJudgment, CitationRelation, ClaimGroundingJudgment, SupportLabel
        rels = {eid: CitationRelation.SUPPORTS for eid in evidence_ids}
        return ClaimGroundingJudgment(
            claim_id=claim_id, support_label=SupportLabel.SUPPORTED,
            citation_judgments=[
                CitationGroundingJudgment(evidence_id=eid, relation=rels[eid], reason_code="mocked")
                for eid in evidence_ids
            ],
            supporting_evidence_ids=list(evidence_ids), unsupported_fragments=[], reason_code="mocked",
        )

    monkeypatch.setattr("nlu.understand_query_with_result", _fake_nlu)
    monkeypatch.setattr("agent.nodes.get_llm", lambda *a, **k: _FakeLLM())
    monkeypatch.setattr("agent.nodes.retrieve_passages", lambda *a, **k: [])
    monkeypatch.setattr(
        "agent.nodes.call_cerebras_native_tools",
        lambda *a, **k: CerebrasNativeToolsResult([], None, {}, 1.0, 1, None),
    )
    monkeypatch.setattr("agent.nodes.execute_validated_call", lambda *a, **k: (ToolResult(success=False, error="none"), 1.0))
    # agent/graph.py imports node functions by name at module-load time and
    # binds those references into the compiled graph - both agent.nodes.*
    # and agent.graph.* must be patched for a NODE (see
    # tests/test_phase9_concurrency_audit.py's _install_rich_state_stubs_once
    # docstring for the full explanation of why this is required).
    monkeypatch.setattr("agent.nodes.evidence_normalization_node", _fake_evidence_normalization_node)
    monkeypatch.setattr("agent.nodes.grounded_generation_node", _fake_grounded_generation_node)
    monkeypatch.setattr("agent.graph.evidence_normalization_node", _fake_evidence_normalization_node)
    monkeypatch.setattr("agent.graph.grounded_generation_node", _fake_grounded_generation_node)
    monkeypatch.setattr("research.gap_analysis.judge_claim_semantic", _real_judge_supported)
    return judge_calls, evidence_id


class TestNormalWorkloadUnaffectedByNewBudgets:
    def test_normal_small_request_reaches_expected_terminal_state_unaffected_by_budgets(self, monkeypatch):
        judge_calls, evidence_id = _install_normal_workload_stubs(monkeypatch)
        agent = MedAgent(research_loop=True)
        state = agent.run("normal query well under both budgets")

        # Core outcome fields - what a normal request has always produced.
        assert state.get("research_stop_reason") == "sufficient_evidence"
        assert state.get("research_iteration") == 0
        ga = state.get("grounded_answer")
        assert ga is not None
        assert [c.claim_id for c in ga.claims] == ["claim-1"]
        assert ga.claims[0].qualifier is None  # never caveated - nothing exhausted
        assert [e.evidence_id for e in state.get("evidence", [])] == [evidence_id]
        assert [c.evidence_ids for c in ga.claims] == [[evidence_id]]
        assert state.get("errors") == []

        # The budget mechanisms ran (real code path, not skipped), but were
        # PROVABLY DORMANT: exactly 1 real judge call (the single factual
        # claim), nowhere near CLAIM_EVALUATION_BUDGET=32, and the budget
        # counter reflects that - never anywhere near exhaustion.
        assert len(judge_calls) == 1
        assert judge_calls == ["claim-1"]
        assert state.get("claim_judge_calls_used", 0) == 1
        assert state["claim_judge_calls_used"] < CLAIM_EVALUATION_BUDGET

        # No tool calls were even selected in this stub (empty raw_tool_calls
        # from call_cerebras_native_tools), so the tool-call budget guard's
        # `if total_emitted > round_budget` branch was never true either.
        assert state.get("tool_calls_used_this_request", 0) == 0
        assert not any(
            h.get("error_category") == "tool_call_budget_exhausted"
            for h in state.get("tool_call_history", [])
        )
        # No EVALUATION_BUDGET_EXHAUSTED gap anywhere - the new gap type is
        # never produced for a normal, well-under-budget request.
        assert not any(
            g.get("gap_type") == "evaluation_budget_exhausted"
            for g in state.get("research_gaps", [])
        )


# ---------------------------------------------------------------------------
# Angle 2: direct, code-level proof the new guard branches are genuinely
# no-ops when under-budget - not by construction/comment, but by an actual
# passing assertion against real call counts.
# ---------------------------------------------------------------------------


class TestGuardBranchesProvablyNeverEnteredUnderBudget:
    def test_claim_budget_guard_branch_never_entered_when_under_budget(self, monkeypatch):
        from evidence.models import (
            ChemblEvidenceMetadata, ContentFormat, Evidence, EvidenceType,
            Provenance, SourceType, make_evidence_id, make_source_url,
        )
        from generation.models import ClaimType, GenerationMetadata, GroundedAnswer, GroundedClaim

        ev = Evidence(
            evidence_id=make_evidence_id(SourceType.CHEMBL, "C1"),
            source_type=SourceType.CHEMBL, source_record_id="C1",
            source_url=make_source_url(SourceType.CHEMBL, "C1"),
            evidence_type=EvidenceType.COMPOUND_IDENTITY, content="x",
            content_format=ContentFormat.FIELD_VALUE,
            source_metadata=ChemblEvidenceMetadata(), provenance=Provenance(retrieval_method="test"),
        )
        claims = [
            GroundedClaim(claim_id=f"c-{i}", text=f"t{i}", evidence_ids=[ev.evidence_id], claim_type=ClaimType.FACTUAL)
            for i in range(CLAIM_EVALUATION_BUDGET - 1)  # strictly under budget
        ]
        answer = GroundedAnswer(
            answer_id="a1", query="q", claims=claims, rendered_text="t", citations=[], references=[],
            used_evidence_ids=[], unused_evidence_ids=[], abstained=False, conflict_detected=False,
            generation_metadata=GenerationMetadata(architecture="x", provider="x", model="x", llm_calls=1, latency_ms=1.0),
        )
        calls = []

        def _judge(claim_id, *a, **k):
            calls.append(claim_id)
            from grounding_eval.models import CitationGroundingJudgment, CitationRelation, ClaimGroundingJudgment, SupportLabel
            return ClaimGroundingJudgment(
                claim_id=claim_id, support_label=SupportLabel.SUPPORTED,
                citation_judgments=[CitationGroundingJudgment(evidence_id=ev.evidence_id, relation=CitationRelation.SUPPORTS, reason_code="x")],
                supporting_evidence_ids=[ev.evidence_id], unsupported_fragments=[], reason_code="x",
            )

        monkeypatch.setattr("research.gap_analysis.judge_claim_semantic", _judge)
        state = {"evidence": [ev], "grounded_answer": answer, "research_query_raw": None}
        gaps = analyze_gaps(state)
        # Every claim judged, none skipped - the exhaustion branch never ran.
        assert len(calls) == len(claims)
        assert not any(g.gap_type.value == "evaluation_budget_exhausted" for g in gaps)

    def test_tool_call_budget_guard_branch_never_entered_when_under_budget(self, monkeypatch):
        n = MAX_TOOL_CALLS_PER_ROUND - 1  # strictly under the per-round budget
        raw_calls = [
            {"id": f"call-{i}", "function": {"name": "pubmed_search_pubmed", "arguments": json.dumps({"query": f"q{i}"})}}
            for i in range(n)
        ]
        execution_log = []
        monkeypatch.setattr(
            "agent.nodes.call_cerebras_native_tools",
            lambda query: CerebrasNativeToolsResult(list(raw_calls), None, {}, 1.0, 1, None),
        )

        def _fake_execute(pydantic_call):
            execution_log.append(pydantic_call)
            return ToolResult(success=True, data=[{"pmid": "1"}], metadata={"timestamp": None}), 1.0

        monkeypatch.setattr("agent.nodes.execute_validated_call", _fake_execute)
        state = create_initial_state("q")
        state = tool_orchestration_node(state)
        assert len(execution_log) == n  # every call processed, none truncated
        assert not any(h.get("error_category") == "tool_call_budget_exhausted" for h in state["tool_call_history"])
        assert state["tool_calls_used_this_request"] == n
