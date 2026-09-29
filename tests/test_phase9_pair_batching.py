"""Phase 9 FINAL optimization pass - deterministic tests for gap-analysis
PAIR BATCHING (research/loop_control.py's GAP_ANALYSIS_BATCH_SIZE,
research/gap_analysis.py's grouping/dispatch, grounding_eval/judge.py's
judge_claims_batch). See docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md's
"GAP-ANALYSIS PAIR BATCHING" section for the design writeup.

SCOPE NOTE (read before editing this file): this file is CORRECTNESS
validation only. It contains NO live Cerebras/NVIDIA/PubMed/ClinicalTrials/
ChEMBL calls, NO MedAgent.run(), and NO timing comparison. Every test uses
the `no_network` fixture from tests/conftest.py, except the handful of tests
that deliberately mock `requests.post` themselves to exercise
grounding_eval.judge's real batch-retry/ID-validation loop with zero real
network traffic (those tests still assert zero live calls occur)."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

import pytest
from pydantic import SecretStr

import research.gap_analysis as gap_analysis_module
import grounding_eval.judge as judge_module
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
from grounding_eval.judge import GroundingJudgeProviderError, judge_claims_batch
from grounding_eval.models import CitationGroundingJudgment, CitationRelation, ClaimGroundingJudgment, SupportLabel
from research.gap_analysis import analyze_gaps
from research.loop_control import CLAIM_EVALUATION_BUDGET
from research.models import GapType


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


def _claim(claim_id: str, evidence_id: str) -> GroundedClaim:
    return GroundedClaim(
        claim_id=claim_id,
        text=f"Factual claim {claim_id}.",
        evidence_ids=[evidence_id],
        claim_type=ClaimType.FACTUAL,
    )


def _answer(claims: List[GroundedClaim]) -> GroundedAnswer:
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


def _build_state(claim_ids: List[str], claim_judge_calls_used: int = 0):
    ev = _ev("CHEMBL1")
    claims = [_claim(cid, ev.evidence_id) for cid in claim_ids]
    answer = _answer(claims)
    state = {"evidence": [ev], "grounded_answer": answer, "research_query_raw": None}
    if claim_judge_calls_used:
        state["claim_judge_calls_used"] = claim_judge_calls_used
    return state, claims


def _judgment(claim_id: str, label: SupportLabel = SupportLabel.SUPPORTED) -> ClaimGroundingJudgment:
    return ClaimGroundingJudgment(
        claim_id=claim_id,
        support_label=label,
        citation_judgments=[
            CitationGroundingJudgment(
                evidence_id=make_evidence_id(SourceType.CHEMBL, "CHEMBL1"),
                relation=CitationRelation.SUPPORTS,
                reason_code=f"marker-for-{claim_id}",
            )
        ],
        supporting_evidence_ids=[make_evidence_id(SourceType.CHEMBL, "CHEMBL1")],
        unsupported_fragments=[],
        reason_code=f"marker-for-{claim_id}",
    )


def _set_batch_size(monkeypatch, value: int) -> None:
    monkeypatch.setattr(gap_analysis_module, "GAP_ANALYSIS_BATCH_SIZE", value)


def _build_fake_single(call_log: List[str], outcomes: Dict[str, SupportLabel]):
    def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
        call_log.append(claim_id)
        label = outcomes.get(claim_id, SupportLabel.SUPPORTED)
        if label is None:  # sentinel for "raise"
            raise GroundingJudgeProviderError("forced single-claim failure")
        return _judgment(claim_id, label)
    return _fake


def _build_fake_batch(call_log: List[List[str]], outcomes: Dict[str, SupportLabel], reverse_response_order: bool = False):
    def _fake(items):
        claim_ids = [ci for ci, *_ in items]
        call_log.append(list(claim_ids))
        for cid in claim_ids:
            if outcomes.get(cid) is None:
                raise GroundingJudgeProviderError("forced batch failure")
        ordered = list(reversed(claim_ids)) if reverse_response_order else claim_ids
        return {cid: _judgment(cid, outcomes.get(cid, SupportLabel.SUPPORTED)) for cid in ordered}
    return _fake


class TestDefaultBatchSizeOnePreservesBehavior:
    def test_batch_size_one_never_calls_judge_claims_batch(self, monkeypatch, no_network):
        state, claims = _build_state(["c1", "c2", "c3"])
        single_calls: List[str] = []
        batch_calls: List[List[str]] = []
        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _build_fake_single(single_calls, {}))
        monkeypatch.setattr(gap_analysis_module, "judge_claims_batch", _build_fake_batch(batch_calls, {}))
        _set_batch_size(monkeypatch, 1)

        gaps = analyze_gaps(state)

        assert batch_calls == []
        assert sorted(single_calls) == ["c1", "c2", "c3"]
        assert gaps == []
        assert state["claim_judge_calls_used"] == 3

    def test_batch_size_one_result_semantics_unchanged(self, monkeypatch, no_network):
        state, claims = _build_state(["c1", "c2"])
        outcomes = {"c1": SupportLabel.SUPPORTED, "c2": SupportLabel.CONTRADICTED}
        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _build_fake_single([], outcomes))
        _set_batch_size(monkeypatch, 1)

        gaps = analyze_gaps(state)

        assert len(gaps) == 1
        assert gaps[0].gap_type == GapType.CONFLICTING_EVIDENCE
        assert gaps[0].related_claim_id == "c2"


class TestPairBatchGrouping:
    def test_two_claims_one_logical_batch_request(self, monkeypatch, no_network):
        state, claims = _build_state(["c1", "c2"])
        batch_calls: List[List[str]] = []
        monkeypatch.setattr(
            gap_analysis_module, "judge_claims_batch",
            _build_fake_batch(batch_calls, {"c1": SupportLabel.SUPPORTED, "c2": SupportLabel.SUPPORTED}),
        )
        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _build_fake_single([], {}))
        _set_batch_size(monkeypatch, 2)

        gaps = analyze_gaps(state)

        assert len(batch_calls) == 1
        assert sorted(batch_calls[0]) == ["c1", "c2"]
        assert gaps == []
        assert state["claim_judge_calls_used"] == 2

    @pytest.mark.parametrize("claim_count,expected_batches", [(4, 2), (6, 3)])
    def test_multiple_pairs(self, monkeypatch, no_network, claim_count, expected_batches):
        claim_ids = [f"c{i}" for i in range(claim_count)]
        state, claims = _build_state(claim_ids)
        batch_calls: List[List[str]] = []
        outcomes = {cid: SupportLabel.SUPPORTED for cid in claim_ids}
        monkeypatch.setattr(gap_analysis_module, "judge_claims_batch", _build_fake_batch(batch_calls, outcomes))
        _set_batch_size(monkeypatch, 2)

        analyze_gaps(state)

        assert len(batch_calls) == expected_batches
        assert all(len(g) == 2 for g in batch_calls)
        flattened = sorted(cid for group in batch_calls for cid in group)
        assert flattened == sorted(claim_ids)

    @pytest.mark.parametrize("claim_count,expected_pairs,expected_singletons", [(3, 1, 1), (5, 2, 1)])
    def test_odd_claim_counts_never_duplicate_or_drop(
        self, monkeypatch, no_network, claim_count, expected_pairs, expected_singletons,
    ):
        claim_ids = [f"c{i}" for i in range(claim_count)]
        state, claims = _build_state(claim_ids)
        batch_calls: List[List[str]] = []
        single_calls: List[str] = []
        outcomes = {cid: SupportLabel.SUPPORTED for cid in claim_ids}
        monkeypatch.setattr(gap_analysis_module, "judge_claims_batch", _build_fake_batch(batch_calls, outcomes))
        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _build_fake_single(single_calls, outcomes))
        _set_batch_size(monkeypatch, 2)

        analyze_gaps(state)

        assert len(batch_calls) == expected_pairs
        assert all(len(g) == 2 for g in batch_calls)
        assert len(single_calls) == expected_singletons
        all_seen = sorted([cid for g in batch_calls for cid in g] + single_calls)
        assert all_seen == sorted(claim_ids)
        # No claim duplicated across groups, none dropped.
        assert len(all_seen) == claim_count


class TestOrderingAndContamination:
    def test_reversed_batch_response_order_restores_claim_order(self, monkeypatch, no_network):
        state, claims = _build_state(["c1", "c2"])
        outcomes = {"c1": SupportLabel.SUPPORTED, "c2": SupportLabel.CONTRADICTED}
        monkeypatch.setattr(
            gap_analysis_module, "judge_claims_batch",
            _build_fake_batch([], outcomes, reverse_response_order=True),
        )
        _set_batch_size(monkeypatch, 2)

        gaps = analyze_gaps(state)

        assert len(gaps) == 1
        assert gaps[0].related_claim_id == "c2"

    def test_opposite_support_states_within_pair_no_contamination(self, monkeypatch, no_network):
        """CLAIM_A supported, CLAIM_B contradicted, same pair - A must never
        inherit B's outcome and vice versa."""
        state, claims = _build_state(["claim_a", "claim_b"])
        outcomes = {"claim_a": SupportLabel.SUPPORTED, "claim_b": SupportLabel.CONTRADICTED}
        monkeypatch.setattr(gap_analysis_module, "judge_claims_batch", _build_fake_batch([], outcomes))
        _set_batch_size(monkeypatch, 2)

        gaps = analyze_gaps(state)

        assert len(gaps) == 1
        assert gaps[0].related_claim_id == "claim_b"
        assert gaps[0].gap_type == GapType.CONFLICTING_EVIDENCE

    def test_reverse_pair_ordering_also_works(self, monkeypatch, no_network):
        state, claims = _build_state(["claim_b", "claim_a"])  # b before a in GroundedAnswer
        outcomes = {"claim_a": SupportLabel.SUPPORTED, "claim_b": SupportLabel.CONTRADICTED}
        monkeypatch.setattr(gap_analysis_module, "judge_claims_batch", _build_fake_batch([], outcomes))
        _set_batch_size(monkeypatch, 2)

        gaps = analyze_gaps(state)

        assert len(gaps) == 1
        assert gaps[0].related_claim_id == "claim_b"

    def test_exact_claim_id_mapping_no_swap(self, monkeypatch, no_network):
        state, claims = _build_state(["c1", "c2", "c3", "c4"])
        outcomes = {
            "c1": SupportLabel.SUPPORTED, "c2": SupportLabel.CONTRADICTED,
            "c3": SupportLabel.SUPPORTED, "c4": SupportLabel.UNSUPPORTED,
        }
        monkeypatch.setattr(gap_analysis_module, "judge_claims_batch", _build_fake_batch([], outcomes))
        _set_batch_size(monkeypatch, 2)

        gaps = analyze_gaps(state)

        by_claim = {g.related_claim_id: g.gap_type for g in gaps}
        assert by_claim == {"c2": GapType.CONFLICTING_EVIDENCE, "c4": GapType.WEAKLY_SUPPORTED_FACT}


class TestBatchFailureAndExhaustion:
    def test_whole_batch_failure_marks_both_claims_evaluation_failed(self, monkeypatch, no_network):
        state, claims = _build_state(["c1", "c2"])
        outcomes = {"c1": None, "c2": None}  # None => forced GroundingJudgeProviderError
        monkeypatch.setattr(gap_analysis_module, "judge_claims_batch", _build_fake_batch([], outcomes))
        _set_batch_size(monkeypatch, 2)

        gaps = analyze_gaps(state)

        by_claim = {g.related_claim_id: g.gap_type for g in gaps}
        assert by_claim == {"c1": GapType.CLAIM_EVALUATION_FAILED, "c2": GapType.CLAIM_EVALUATION_FAILED}
        # Never fabricated support - no WEAKLY_SUPPORTED/CONFLICTING gap for either.
        assert all(g.gap_type == GapType.CLAIM_EVALUATION_FAILED for g in gaps)
        # Claims themselves are preserved (unmutated) - the batch failure never
        # touched grounded_answer.claims.
        assert [c.claim_id for c in claims] == ["c1", "c2"]

    def test_singleton_failure_stays_silent_matching_pre_batching_behavior(self, monkeypatch, no_network):
        """A batch_size=2 request with an ODD claim count's trailing
        singleton uses the single-claim path - its failure must be silent
        (no gap), identical to batch_size=1's pre-existing behavior, per the
        explicit requirement that only MULTI-claim batch failures get the
        new explicit CLAIM_EVALUATION_FAILED gap."""
        state, claims = _build_state(["c1", "c2", "c3"])
        outcomes_pair = {"c1": SupportLabel.SUPPORTED, "c2": SupportLabel.SUPPORTED}
        outcomes_single = {"c3": None}
        monkeypatch.setattr(gap_analysis_module, "judge_claims_batch", _build_fake_batch([], outcomes_pair))
        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _build_fake_single([], outcomes_single))
        _set_batch_size(monkeypatch, 2)

        gaps = analyze_gaps(state)

        assert gaps == []  # c3's failure is silent, matching batch_size=1 semantics
        assert state["claim_judge_calls_used"] == 3


class TestBudgetAccountingUnderBatching:
    def test_pair_consumes_two_claim_budget_units(self, monkeypatch, no_network):
        state, claims = _build_state(["c1", "c2"])
        outcomes = {"c1": SupportLabel.SUPPORTED, "c2": SupportLabel.SUPPORTED}
        monkeypatch.setattr(gap_analysis_module, "judge_claims_batch", _build_fake_batch([], outcomes))
        _set_batch_size(monkeypatch, 2)

        analyze_gaps(state)

        assert state["claim_judge_calls_used"] == 2

    def test_retry_within_one_batch_attempt_consumes_no_extra_claim_budget(self, monkeypatch, no_network):
        """A batch's internal retry (up to 2 provider attempts inside
        judge_claims_batch/_invoke_judge_batch) is invisible to
        analyze_gaps's Step A budget bookkeeping - Step A reserves exactly
        one slot per SCHEDULED CLAIM, once, regardless of how many provider
        attempts judge_claims_batch makes underneath."""
        state, claims = _build_state(["c1", "c2"])
        attempt_counter = {"n": 0}

        def _fake_batch_with_internal_retry(items):
            attempt_counter["n"] += 1
            if attempt_counter["n"] == 1:
                raise GroundingJudgeProviderError("simulated transient - but judge_claims_batch itself "
                                                    "already exhausts its OWN bounded retry before raising, "
                                                    "so from analyze_gaps's perspective this is one failed "
                                                    "group dispatch, consuming zero extra claim-budget units")
            return {ci: _judgment(ci) for ci, *_ in items}

        monkeypatch.setattr(gap_analysis_module, "judge_claims_batch", _fake_batch_with_internal_retry)
        _set_batch_size(monkeypatch, 2)
        analyze_gaps(state)
        assert state["claim_judge_calls_used"] == 2  # exactly 2 claims, never double-counted

    def test_exactly_at_budget_all_pairs_judged(self, monkeypatch, no_network):
        claim_ids = [f"c{i}" for i in range(CLAIM_EVALUATION_BUDGET)]
        state, claims = _build_state(claim_ids)
        outcomes = {cid: SupportLabel.SUPPORTED for cid in claim_ids}
        monkeypatch.setattr(gap_analysis_module, "judge_claims_batch", _build_fake_batch([], outcomes))
        _set_batch_size(monkeypatch, 2)

        gaps = analyze_gaps(state)

        assert state["claim_judge_calls_used"] == CLAIM_EVALUATION_BUDGET
        assert not any(g.gap_type == GapType.EVALUATION_BUDGET_EXHAUSTED for g in gaps)

    def test_one_over_budget_exactly_one_exhausted_even_under_pairing(self, monkeypatch, no_network):
        claim_ids = [f"c{i}" for i in range(CLAIM_EVALUATION_BUDGET + 1)]
        state, claims = _build_state(claim_ids)
        outcomes = {cid: SupportLabel.SUPPORTED for cid in claim_ids}
        monkeypatch.setattr(gap_analysis_module, "judge_claims_batch", _build_fake_batch([], outcomes))
        _set_batch_size(monkeypatch, 2)

        gaps = analyze_gaps(state)

        exhausted = [g for g in gaps if g.gap_type == GapType.EVALUATION_BUDGET_EXHAUSTED]
        assert len(exhausted) == 1
        assert exhausted[0].related_claim_id == claim_ids[-1]
        assert state["claim_judge_calls_used"] == CLAIM_EVALUATION_BUDGET

    def test_remaining_budget_one_forces_singleton_not_pair(self, monkeypatch, no_network):
        """budget_remaining=1 when Step A reaches the LAST claim of a would-be
        pair: only 1 slot exists, so only 1 claim can be scheduled - Step A
        (unchanged, per-claim) naturally produces a scheduled list whose
        final group is a singleton even under batch_size=2."""
        claim_ids = ["c1", "c2", "c3"]
        state, claims = _build_state(claim_ids, claim_judge_calls_used=CLAIM_EVALUATION_BUDGET - 1)
        single_calls: List[str] = []
        batch_calls: List[List[str]] = []
        outcomes = {"c1": SupportLabel.SUPPORTED}
        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _build_fake_single(single_calls, outcomes))
        monkeypatch.setattr(gap_analysis_module, "judge_claims_batch", _build_fake_batch(batch_calls, {}))
        _set_batch_size(monkeypatch, 2)

        gaps = analyze_gaps(state)

        assert batch_calls == []
        assert single_calls == ["c1"]
        exhausted_ids = {g.related_claim_id for g in gaps if g.gap_type == GapType.EVALUATION_BUDGET_EXHAUSTED}
        assert exhausted_ids == {"c2", "c3"}
        assert state["claim_judge_calls_used"] == CLAIM_EVALUATION_BUDGET


class TestLargeInputBatchCount:
    def test_seven_claims_exactly_four_logical_requests(self, monkeypatch, no_network):
        claim_ids = [f"c{i}" for i in range(7)]
        state, claims = _build_state(claim_ids)
        batch_calls: List[List[str]] = []
        single_calls: List[str] = []
        outcomes = {cid: SupportLabel.SUPPORTED for cid in claim_ids}
        monkeypatch.setattr(gap_analysis_module, "judge_claims_batch", _build_fake_batch(batch_calls, outcomes))
        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _build_fake_single(single_calls, outcomes))
        _set_batch_size(monkeypatch, 2)

        analyze_gaps(state)

        total_logical_requests = len(batch_calls) + len(single_calls)
        assert total_logical_requests == 4  # ceil(7/2)
        assert len(batch_calls) == 3
        assert len(single_calls) == 1
        assert state["claim_judge_calls_used"] == 7


class TestJudgeBatchIDValidation:
    """Exercises grounding_eval.judge's REAL _invoke_judge_batch retry/
    ID-validation loop with a mocked requests.post - zero real network
    traffic (no_network still active), proving the strict-validation logic
    itself, not just gap_analysis's grouping layer above it."""

    def _mock_key(self, monkeypatch):
        monkeypatch.setattr(judge_module.settings, "CEREBRAS_API_KEY", SecretStr("fake-test-key"))

    def _good_body(self, ids):
        return {
            "judgments": [
                {
                    "claim_id": cid, "support_label": "supported",
                    "citation_relations": [], "unsupported_fragments": [], "reason_code": "ok",
                }
                for cid in ids
            ]
        }

    def _resp(self, monkeypatch, status, json_body):
        class _R:
            status_code = status
            text = "err"
            def json(self):
                return {"choices": [{"message": {"content": __import__("json").dumps(json_body)}}], "usage": {}}
        return _R()

    def test_duplicate_id_exhausts_retries_and_raises(self, monkeypatch, no_network):
        self._mock_key(monkeypatch)
        bad = self._good_body(["c1", "c1"])  # duplicate, missing c2

        def _fake_post(*a, **kw):
            return self._resp(monkeypatch, 200, bad)

        monkeypatch.setattr(judge_module.requests, "post", _fake_post)
        monkeypatch.setattr(judge_module, "wait_for_rate_limit", lambda *a, **kw: None)

        ev = _ev("CHEMBL1")
        with pytest.raises(GroundingJudgeProviderError):
            judge_claims_batch([("c1", "t1", [ev.evidence_id], {ev.evidence_id: ev}),
                                 ("c2", "t2", [ev.evidence_id], {ev.evidence_id: ev})])

    def test_missing_id_exhausts_retries_and_raises(self, monkeypatch, no_network):
        self._mock_key(monkeypatch)
        bad = self._good_body(["c1"])  # missing c2

        monkeypatch.setattr(judge_module.requests, "post", lambda *a, **kw: self._resp(monkeypatch, 200, bad))
        monkeypatch.setattr(judge_module, "wait_for_rate_limit", lambda *a, **kw: None)

        ev = _ev("CHEMBL1")
        with pytest.raises(GroundingJudgeProviderError):
            judge_claims_batch([("c1", "t1", [ev.evidence_id], {ev.evidence_id: ev}),
                                 ("c2", "t2", [ev.evidence_id], {ev.evidence_id: ev})])

    def test_unknown_id_exhausts_retries_and_raises(self, monkeypatch, no_network):
        self._mock_key(monkeypatch)
        bad = self._good_body(["c1", "c99"])  # c99 unknown, c2 missing

        monkeypatch.setattr(judge_module.requests, "post", lambda *a, **kw: self._resp(monkeypatch, 200, bad))
        monkeypatch.setattr(judge_module, "wait_for_rate_limit", lambda *a, **kw: None)

        ev = _ev("CHEMBL1")
        with pytest.raises(GroundingJudgeProviderError):
            judge_claims_batch([("c1", "t1", [ev.evidence_id], {ev.evidence_id: ev}),
                                 ("c2", "t2", [ev.evidence_id], {ev.evidence_id: ev})])

    def test_malformed_json_exhausts_retries_and_raises(self, monkeypatch, no_network):
        self._mock_key(monkeypatch)

        class _R:
            status_code = 200
            text = "err"
            def json(self):
                return {"choices": [{"message": {"content": "not valid json{{"}}], "usage": {}}

        monkeypatch.setattr(judge_module.requests, "post", lambda *a, **kw: _R())
        monkeypatch.setattr(judge_module, "wait_for_rate_limit", lambda *a, **kw: None)

        ev = _ev("CHEMBL1")
        with pytest.raises(GroundingJudgeProviderError):
            judge_claims_batch([("c1", "t1", [ev.evidence_id], {ev.evidence_id: ev}),
                                 ("c2", "t2", [ev.evidence_id], {ev.evidence_id: ev})])

    def test_first_attempt_malformed_second_valid_succeeds_within_bound(self, monkeypatch, no_network):
        self._mock_key(monkeypatch)
        good = self._good_body(["c1", "c2"])
        call_count = {"n": 0}

        def _fake_post(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return self._resp(monkeypatch, 200, self._good_body(["c1"]))  # malformed: missing c2
            return self._resp(monkeypatch, 200, good)

        monkeypatch.setattr(judge_module.requests, "post", _fake_post)
        monkeypatch.setattr(judge_module, "wait_for_rate_limit", lambda *a, **kw: None)

        ev = _ev("CHEMBL1")
        result = judge_claims_batch([("c1", "t1", [ev.evidence_id], {ev.evidence_id: ev}),
                                      ("c2", "t2", [ev.evidence_id], {ev.evidence_id: ev})])

        assert call_count["n"] == 2  # bounded at exactly 2 attempts
        assert set(result.keys()) == {"c1", "c2"}

    def test_bounded_at_exactly_two_attempts_never_more(self, monkeypatch, no_network):
        self._mock_key(monkeypatch)
        call_count = {"n": 0}

        def _fake_post(*a, **kw):
            call_count["n"] += 1
            return self._resp(monkeypatch, 200, self._good_body(["c1"]))  # always malformed (missing c2)

        monkeypatch.setattr(judge_module.requests, "post", _fake_post)
        monkeypatch.setattr(judge_module, "wait_for_rate_limit", lambda *a, **kw: None)

        ev = _ev("CHEMBL1")
        with pytest.raises(GroundingJudgeProviderError):
            judge_claims_batch([("c1", "t1", [ev.evidence_id], {ev.evidence_id: ev}),
                                 ("c2", "t2", [ev.evidence_id], {ev.evidence_id: ev})])
        assert call_count["n"] == 2  # never a 3rd attempt


_FROZEN_FIXTURES_PATH = os.path.join(
    os.path.dirname(__file__), "..", "artifacts", "v2", "phase9_gap_analysis_frozen_fixtures.json",
)

# Ground-truth per-claim support labels from the ALREADY-RECORDED, real
# concurrency-experiment batch1 live results
# (artifacts/v2/phase9_gap_analysis_concurrency_experiment.json's raw_results,
# concurrency=1 runs) - reused here ONLY as a FIXED/HELD-CONSTANT judge
# response mapping for a deterministic equivalence check (Step 10 of
# docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md's "GAP-ANALYSIS PAIR BATCHING"
# section: "with judge responses held fixed, compare batch_size=1 vs
# batch_size=2"). This is NOT a live call and NOT performance evidence - it
# only proves the GROUPING/dispatch logic produces identical downstream
# gaps/budget/ordering regardless of batch_size, given the SAME per-claim
# outcome.
_RECORDED_SUPPORT_LABELS = {
    "SMALL": {"c-0": SupportLabel.SUPPORTED, "c-2": SupportLabel.SUPPORTED,
              "c-3": SupportLabel.SUPPORTED, "c-4": SupportLabel.SUPPORTED},
    "MEDIUM": {"c-0": SupportLabel.SUPPORTED, "c-1": SupportLabel.SUPPORTED, "c-2": SupportLabel.SUPPORTED,
               "c-3": SupportLabel.SUPPORTED, "c-4": SupportLabel.SUPPORTED},
    "LARGE": {"c-0": SupportLabel.PARTIALLY_SUPPORTED, "c-1": SupportLabel.SUPPORTED,
              "c-2": SupportLabel.SUPPORTED, "c-3": SupportLabel.SUPPORTED,
              "c-4": SupportLabel.SUPPORTED, "c-5": SupportLabel.SUPPORTED},
}

_EXPECTED_LOGICAL_CALLS = {
    "SMALL": {1: 4, 2: 2},
    "MEDIUM": {1: 5, 2: 3},
    "LARGE": {1: 6, 2: 3},
}


def _load_frozen_fixture_state(label: str):
    from evidence.models import Evidence as EvidenceModel
    from generation.models import GroundedAnswer as GroundedAnswerModel

    with open(_FROZEN_FIXTURES_PATH) as f:
        artifact = json.load(f)
    entry = artifact["fixtures"][label]
    evidence = [EvidenceModel.model_validate(e) for e in entry["evidence"]]
    ga = GroundedAnswerModel.model_validate(entry["grounded_answer"])
    state = {"evidence": evidence, "grounded_answer": ga, "research_query_raw": None, "claim_judge_calls_used": 0}
    return state


@pytest.mark.skipif(not os.path.exists(_FROZEN_FIXTURES_PATH), reason="frozen fixtures artifact not present")
class TestDeterministicEquivalenceOnFrozenFixtures:
    """Step 10: with judge responses HELD FIXED (per-claim support label
    identical regardless of grouping), batch_size=1 and batch_size=2 must
    produce semantically equivalent output on the SAME real, durable
    SMALL/MEDIUM/LARGE fixtures - proving batching's grouping/dispatch layer
    introduces no behavioral difference by itself, independent of any live
    provider nondeterminism (which is separately evaluated in the AC-powered
    live benchmark)."""

    @pytest.mark.parametrize("label", ["SMALL", "MEDIUM", "LARGE"])
    def test_batch1_vs_batch2_semantic_equivalence(self, monkeypatch, no_network, label):
        labels = _RECORDED_SUPPORT_LABELS[label]

        # --- batch_size=1 run ---
        state1 = _load_frozen_fixture_state(label)
        single_calls: List[str] = []
        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _build_fake_single(single_calls, labels))
        _set_batch_size(monkeypatch, 1)
        gaps1 = analyze_gaps(state1)

        # --- batch_size=2 run (fresh state, same fixture, same fixed labels) ---
        state2 = _load_frozen_fixture_state(label)
        batch_calls: List[List[str]] = []
        single_calls_b2: List[str] = []
        monkeypatch.setattr(gap_analysis_module, "judge_claims_batch", _build_fake_batch(batch_calls, labels))
        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _build_fake_single(single_calls_b2, labels))
        _set_batch_size(monkeypatch, 2)
        gaps2 = analyze_gaps(state2)

        # --- logical call count matches ceil(n/2) exactly ---
        logical_calls_b1 = len(single_calls)
        logical_calls_b2 = len(batch_calls) + len(single_calls_b2)
        assert logical_calls_b1 == _EXPECTED_LOGICAL_CALLS[label][1]
        assert logical_calls_b2 == _EXPECTED_LOGICAL_CALLS[label][2]

        # --- semantic equivalence: same claim IDs, same gap types, same
        # related_claim_id, same ordering, same budget, same evidence refs ---
        def _normalize(gaps):
            return [(g.gap_type.value, g.related_claim_id, round(g.severity, 3)) for g in gaps]

        assert _normalize(gaps1) == _normalize(gaps2)
        assert state1["claim_judge_calls_used"] == state2["claim_judge_calls_used"]
        assert state1["claim_judge_calls_used"] == len(labels)


class TestNoHiddenNetworkTraffic:
    def test_no_network_fixture_blocks_unmocked_batch_request(self, monkeypatch, no_network):
        """If judge_claims_batch's underlying requests.post is NOT mocked and
        no_network is active, a real dispatch attempt must fail loudly (via
        the no_network fixture's blocked socket/adapter), never silently
        succeed - proving these tests genuinely exercise zero real traffic
        by construction, not by accident."""
        state, claims = _build_state(["c1", "c2"])
        monkeypatch.setattr(gap_analysis_module.settings if hasattr(gap_analysis_module, "settings") else judge_module.settings,
                             "CEREBRAS_API_KEY", SecretStr("fake-test-key"))
        _set_batch_size(monkeypatch, 2)

        gaps = analyze_gaps(state)
        # The real dispatch attempt(s) failed (network blocked) -> whole
        # batch attempt invalid -> explicit CLAIM_EVALUATION_FAILED gaps,
        # never a silently-fabricated support judgment.
        assert {g.gap_type for g in gaps} == {GapType.CLAIM_EVALUATION_FAILED}
