"""Phase 9, Step 9 - deterministic tests for the PHASE9-DEFECT-001 fix
(request-global CLAIM_EVALUATION_BUDGET on research/gap_analysis.py's
judge_claim_semantic() calls). See docs/v2/PHASE9_FAILURE_ANALYSIS.md's
PHASE9-DEFECT-001 entry and docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md's
"BOUNDEDNESS HARDENING" section for the full design writeup.

No real network call anywhere in this file - `judge_claim_semantic` is
monkeypatched throughout, following the exact pattern already used by
tests/test_research_models_and_gap_analysis.py."""

from __future__ import annotations

import pytest

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
from grounding_eval.models import CitationGroundingJudgment, CitationRelation, ClaimGroundingJudgment, SupportLabel
from research.gap_analysis import analyze_gaps
from research.loop_control import CLAIM_EVALUATION_BUDGET, decide_stop_reason
from research.models import GapType


@pytest.fixture(autouse=True)
def _pin_batch_size_to_one(monkeypatch):
    """Written before Phase-9 PAIR BATCHING existed - every test here mocks
    ONLY the single-claim judge_claim_semantic and constructs scenarios with
    many factual claims (to exercise CLAIM_EVALUATION_BUDGET). Pin
    GAP_ANALYSIS_BATCH_SIZE to its pre-batching value (1) so a claim group
    here is never silently routed to the real, unmocked judge_claims_batch
    (whose production default is now 2) - this file tests the claim BUDGET,
    not batching, and must keep doing exactly that in isolation."""
    monkeypatch.setattr("research.gap_analysis.GAP_ANALYSIS_BATCH_SIZE", 1)


@pytest.fixture(autouse=True)
def _enforce_no_network(no_network):
    """PHASE9-PROCESS-DEV-003 remediation (see
    docs/v2/PHASE9_FAILURE_ANALYSIS.md): this file has no explicit network
    isolation for ANY test, and constructs up to CLAIM_EVALUATION_BUDGET*10
    (320) real factual claims while mocking only judge_claim_semantic - if a
    future change (like the GAP_ANALYSIS_BATCH_SIZE default flip that
    triggered DEV-003) ever routes a claim group through the real,
    unmocked judge_claims_batch again, this guard fails the test loudly and
    immediately instead of silently attempting a real outbound provider
    call. Forces the opt-in `no_network` fixture (tests/conftest.py) active
    for every test in this module regardless of each test's own signature,
    by declaring it as this autouse fixture's own dependency."""
    yield


def _ev(record_id: str) -> Evidence:
    return Evidence(
        evidence_id=make_evidence_id(SourceType.CHEMBL, record_id),
        source_type=SourceType.CHEMBL,
        source_record_id=record_id,
        source_url=make_source_url(SourceType.CHEMBL, record_id),
        evidence_type=EvidenceType.COMPOUND_IDENTITY,
        content="Some content",
        content_format=ContentFormat.FIELD_VALUE,
        source_metadata=ChemblEvidenceMetadata(),
        provenance=Provenance(retrieval_method="test"),
    )


def _claim(idx: int, evidence_id: str) -> GroundedClaim:
    return GroundedClaim(
        claim_id=f"c-{idx}",
        text=f"Factual claim number {idx}.",
        evidence_ids=[evidence_id],
        claim_type=ClaimType.FACTUAL,
    )


def _answer(claims):
    return GroundedAnswer(
        answer_id="ans-1",
        query="q",
        claims=claims,
        rendered_text="text",
        citations=[],
        references=[],
        used_evidence_ids=[],
        unused_evidence_ids=[],
        abstained=False,
        conflict_detected=False,
        generation_metadata=GenerationMetadata(
            architecture="candidate_b_structured",
            model="qwen-3.8-27b",
            llm_calls=1,
            provider="cerebras",
            latency_ms=1.0,
        ),
    )


def _counting_judge(calls_log):
    """Every call is logged (claim_id, in order) and always returns a
    SUPPORTED judgment - lets tests assert both the exact COUNT and the
    exact ORDER of real judge invocations, not just the returned gaps."""

    def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
        calls_log.append(claim_id)
        rels = {eid: CitationRelation.SUPPORTS for eid in evidence_ids}
        return ClaimGroundingJudgment(
            claim_id=claim_id,
            support_label=SupportLabel.SUPPORTED,
            citation_judgments=[
                CitationGroundingJudgment(evidence_id=eid, relation=rels[eid], reason_code="mocked")
                for eid in evidence_ids
            ],
            supporting_evidence_ids=list(evidence_ids),
            unsupported_fragments=[],
            reason_code="mocked",
        )

    return _fake


def _build_state(n_claims: int, claim_judge_calls_used: int = 0):
    ev = _ev("CHEMBL1")
    claims = [_claim(i, ev.evidence_id) for i in range(n_claims)]
    answer = _answer(claims)
    state = {
        "evidence": [ev],
        "grounded_answer": answer,
        "research_query_raw": None,
    }
    if claim_judge_calls_used:
        state["claim_judge_calls_used"] = claim_judge_calls_used
    return state, claims


class TestClaimBudgetBelowAndAtBudget:
    def test_below_budget_every_claim_judged_normally(self, monkeypatch):
        calls = []
        monkeypatch.setattr("research.gap_analysis.judge_claim_semantic", _counting_judge(calls))
        n = CLAIM_EVALUATION_BUDGET - 5
        state, claims = _build_state(n)
        gaps = analyze_gaps(state)
        assert len(calls) == n
        assert calls == [c.claim_id for c in claims]
        assert not any(g.gap_type == GapType.EVALUATION_BUDGET_EXHAUSTED for g in gaps)
        assert state["claim_judge_calls_used"] == n

    def test_exactly_at_budget_all_judged_none_skipped(self, monkeypatch):
        calls = []
        monkeypatch.setattr("research.gap_analysis.judge_claim_semantic", _counting_judge(calls))
        state, claims = _build_state(CLAIM_EVALUATION_BUDGET)
        gaps = analyze_gaps(state)
        assert len(calls) == CLAIM_EVALUATION_BUDGET
        assert not any(g.gap_type == GapType.EVALUATION_BUDGET_EXHAUSTED for g in gaps)
        assert state["claim_judge_calls_used"] == CLAIM_EVALUATION_BUDGET


class TestClaimBudgetOverBudget:
    def test_one_over_budget_exactly_one_claim_unevaluated(self, monkeypatch):
        calls = []
        monkeypatch.setattr("research.gap_analysis.judge_claim_semantic", _counting_judge(calls))
        n = CLAIM_EVALUATION_BUDGET + 1
        state, claims = _build_state(n)
        gaps = analyze_gaps(state)
        # Exactly CLAIM_EVALUATION_BUDGET real judge calls - no more.
        assert len(calls) == CLAIM_EVALUATION_BUDGET
        exhausted = [g for g in gaps if g.gap_type == GapType.EVALUATION_BUDGET_EXHAUSTED]
        assert len(exhausted) == 1
        # The unevaluated claim is the LAST one (deterministic order - first
        # CLAIM_EVALUATION_BUDGET claims, in list order, get judged).
        assert exhausted[0].related_claim_id == claims[-1].claim_id
        # The claim itself is still present in the answer, completely
        # untouched (never dropped, never mutated to "supported").
        assert claims[-1].claim_id in {c.claim_id for c in claims}
        assert claims[-1].qualifier is None  # analyze_gaps never mutates claims directly
        assert state["claim_judge_calls_used"] == CLAIM_EVALUATION_BUDGET

    def test_massively_over_budget_large_excess_all_correctly_marked_no_crash(self, monkeypatch):
        calls = []
        monkeypatch.setattr("research.gap_analysis.judge_claim_semantic", _counting_judge(calls))
        n = CLAIM_EVALUATION_BUDGET * 10  # a large excess
        state, claims = _build_state(n)
        gaps = analyze_gaps(state)
        assert len(calls) == CLAIM_EVALUATION_BUDGET
        exhausted = [g for g in gaps if g.gap_type == GapType.EVALUATION_BUDGET_EXHAUSTED]
        assert len(exhausted) == n - CLAIM_EVALUATION_BUDGET
        # Every exhausted gap has zero fabricated Evidence IDs - it names
        # only a claim_id, never invents an evidence_id field of its own.
        for g in exhausted:
            assert g.related_claim_id is not None
            assert not hasattr(g, "evidence_ids")
        assert state["claim_judge_calls_used"] == CLAIM_EVALUATION_BUDGET

    def test_no_extra_judge_call_after_exhaustion_mock_call_count(self, monkeypatch):
        """Explicitly counts REAL judge invocations via the mock's own call
        log (not just inspecting returned gaps) - proving no call is made
        for a budget-exhausted claim, not merely that its result is
        discarded after the fact."""
        calls = []
        monkeypatch.setattr("research.gap_analysis.judge_claim_semantic", _counting_judge(calls))
        state, claims = _build_state(CLAIM_EVALUATION_BUDGET + 20)
        analyze_gaps(state)
        assert len(calls) == CLAIM_EVALUATION_BUDGET, (
            f"expected exactly {CLAIM_EVALUATION_BUDGET} real judge calls, got {len(calls)}"
        )


class TestClaimBudgetRequestGlobalAcrossRounds:
    def test_budget_spans_multiple_rounds_round2_cannot_use_rounds1_leftover_as_fresh(self, monkeypatch):
        """Request-global scope (this pass's chosen design, see
        docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md's "BOUNDEDNESS HARDENING"
        section for why request-global was chosen over per-cycle): claims
        judged in an earlier gap_analysis_node visit (round 1) must reduce
        the budget available to a LATER visit (round 2) in the SAME
        request - simulated here by round 2's state carrying round 1's
        `claim_judge_calls_used` total forward, exactly as
        agent/nodes.py::gap_analysis_node does across real graph rounds."""
        calls = []
        monkeypatch.setattr("research.gap_analysis.judge_claim_semantic", _counting_judge(calls))

        # Round 1: uses up all but 3 of the budget.
        round1_n = CLAIM_EVALUATION_BUDGET - 3
        state1, claims1 = _build_state(round1_n)
        analyze_gaps(state1)
        assert len(calls) == round1_n
        assert state1["claim_judge_calls_used"] == round1_n

        # Round 2: a FRESH GroundedAnswer with 10 new factual claims, but
        # carries round 1's cumulative usage forward via
        # claim_judge_calls_used (exactly what gap_analysis_node does by
        # reading/writing the same AgentState dict across research-loop
        # iterations).
        round2_n = 10
        state2, claims2 = _build_state(round2_n, claim_judge_calls_used=state1["claim_judge_calls_used"])
        gaps2 = analyze_gaps(state2)

        # Only 3 of round 2's 10 claims can be judged (32-29=3 remaining).
        remaining = CLAIM_EVALUATION_BUDGET - round1_n
        assert len(calls) == round1_n + remaining
        exhausted2 = [g for g in gaps2 if g.gap_type == GapType.EVALUATION_BUDGET_EXHAUSTED]
        assert len(exhausted2) == round2_n - remaining
        assert state2["claim_judge_calls_used"] == CLAIM_EVALUATION_BUDGET


class TestClaimBudgetPreservesAlreadyJudgedClaims:
    def test_already_judged_claims_before_exhaustion_are_unchanged(self, monkeypatch):
        """The judgments made before exhaustion (e.g. a WEAKLY_SUPPORTED_FACT
        gap for an early claim) must be identical to what analyze_gaps would
        have produced with no budget at all - the budget mechanism must be a
        pure ADDITION (new gaps for the tail), never a mutation of earlier,
        already-computed results."""
        ev = _ev("CHEMBL1")
        weak_claim = _claim(0, ev.evidence_id)
        supported_claims = [_claim(i, ev.evidence_id) for i in range(1, CLAIM_EVALUATION_BUDGET)]
        overflow_claim = _claim(CLAIM_EVALUATION_BUDGET, ev.evidence_id)
        all_claims = [weak_claim] + supported_claims + [overflow_claim]
        answer = _answer(all_claims)

        def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
            label = SupportLabel.UNSUPPORTED if claim_id == weak_claim.claim_id else SupportLabel.SUPPORTED
            rels = {eid: CitationRelation.SUPPORTS for eid in evidence_ids}
            return ClaimGroundingJudgment(
                claim_id=claim_id, support_label=label,
                citation_judgments=[
                    CitationGroundingJudgment(evidence_id=eid, relation=rels[eid], reason_code="mocked")
                    for eid in evidence_ids
                ],
                supporting_evidence_ids=list(evidence_ids),
                unsupported_fragments=[], reason_code="mocked",
            )

        monkeypatch.setattr("research.gap_analysis.judge_claim_semantic", _fake)
        state = {"evidence": [ev], "grounded_answer": answer, "research_query_raw": None}
        gaps = analyze_gaps(state)

        weak_gaps = [g for g in gaps if g.gap_type == GapType.WEAKLY_SUPPORTED_FACT]
        assert len(weak_gaps) == 1
        assert weak_gaps[0].related_claim_id == weak_claim.claim_id
        exhausted = [g for g in gaps if g.gap_type == GapType.EVALUATION_BUDGET_EXHAUSTED]
        assert len(exhausted) == 1
        assert exhausted[0].related_claim_id == overflow_claim.claim_id


class TestClaimBudgetStopReasonSafety:
    def test_no_false_sufficient_evidence_stop_when_budget_exhausted_gaps_remain(self):
        """research/loop_control.py::decide_stop_reason must never treat a
        request with an open EVALUATION_BUDGET_EXHAUSTED gap as
        SUFFICIENT_EVIDENCE, even though no other gap remains."""
        from research.models import EvidenceGap

        gaps = [
            EvidenceGap(
                gap_id="gap-budget-exhausted-c99",
                gap_type=GapType.EVALUATION_BUDGET_EXHAUSTED,
                description="not evaluated",
                related_claim_id="c-99",
                severity=0.6,
            )
        ]
        stop_reason = decide_stop_reason(
            gaps=gaps,
            planned_actions=[],  # action_planning.py excludes this gap type from candidates
            iteration=0,
            tool_calls_used=0,
            consecutive_failure_rounds=0,
            attempted_no_evidence_before=False,
        )
        assert stop_reason is not None
        assert stop_reason.value != "sufficient_evidence"

    def test_evaluation_budget_exhausted_gap_never_selected_as_a_research_action(self):
        """research/action_planning.py::plan_actions must never turn an
        EVALUATION_BUDGET_EXHAUSTED gap into a ResearchAction - no tool call
        can ever resolve "this claim's own already-cited evidence was never
        judged" (see PHASE9-DEFECT-001's fix requirement 8)."""
        from research.action_planning import plan_actions
        from research.models import EvidenceGap

        gap = EvidenceGap(
            gap_id="gap-budget-exhausted-c1",
            gap_type=GapType.EVALUATION_BUDGET_EXHAUSTED,
            description="not evaluated",
            related_claim_id="c-1",
            severity=1.0,  # deliberately highest severity, to prove it's excluded regardless
        )
        actions = plan_actions([gap], "original query", iteration=1, already_attempted_signatures=set())
        assert actions == []


class TestClaimBudgetDeterminism:
    def test_deterministic_ordering_same_claims_judged_every_run(self, monkeypatch):
        n = CLAIM_EVALUATION_BUDGET + 7
        results = []
        for _ in range(3):
            calls = []
            monkeypatch.setattr("research.gap_analysis.judge_claim_semantic", _counting_judge(calls))
            state, claims = _build_state(n)
            analyze_gaps(state)
            results.append(list(calls))
        assert results[0] == results[1] == results[2]
        assert len(results[0]) == CLAIM_EVALUATION_BUDGET


class TestClaimBudgetDormantBelowThreshold:
    def test_normal_small_answer_well_under_budget_unaffected_by_budget_mechanism(self, monkeypatch):
        """A normal answer far below CLAIM_EVALUATION_BUDGET (matching the
        real observed Phase-8 corpus, whose max single-round claim count was
        8 - see artifacts/v2/phase9_claim_and_tool_call_distributions.json)
        must produce EXACTLY the same gaps/judge-call count/order as the
        pre-existing (pre-Phase-9) code path - the budget guard is proven
        dormant by construction here: when len(claims) <= CLAIM_EVALUATION_BUDGET,
        `budget_remaining` never reaches 0, so the new `if budget_remaining <= 0`
        branch is never taken and every claim reaches judge_claim_semantic
        exactly as it always did."""
        calls = []
        monkeypatch.setattr("research.gap_analysis.judge_claim_semantic", _counting_judge(calls))
        state, claims = _build_state(8)  # real observed corpus max, well under budget=32
        gaps = analyze_gaps(state)
        assert len(calls) == 8
        assert calls == [c.claim_id for c in claims]
        assert gaps == []  # all SUPPORTED -> no gap, identical to pre-Phase-9 behavior
        assert state["claim_judge_calls_used"] == 8
