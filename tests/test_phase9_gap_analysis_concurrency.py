"""Phase 9 scheduling-only follow-up - deterministic tests for the bounded
worker-pool concurrency mechanism added to
research/gap_analysis.py::analyze_gaps (research/loop_control.py's new
GAP_ANALYSIS_MAX_CONCURRENCY constant). See
docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md's new "GAP-ANALYSIS JUDGE-CALL
CONCURRENCY" section for the design writeup.

SCOPE NOTE (read before editing this file): this file is SCHEDULING-
CORRECTNESS validation only. It contains NO live Cerebras/NVIDIA/PubMed/
ClinicalTrials/ChEMBL calls, NO MedAgent.run(), and NO P50/P95/P99 or
before/after timing comparison. Every test uses the `no_network` fixture
from tests/conftest.py. A handful of tests assert `analyze_gaps` returns
"promptly" (under a generous wall-clock bound) purely as a HANG/DEADLOCK
correctness check - this is explicitly NOT Phase-9 performance evidence and
must never be read or cited as such.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List

import pytest

import research.gap_analysis as gap_analysis_module
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
from research.loop_control import CLAIM_EVALUATION_BUDGET
from research.models import GapType

# A generous, deliberately loose bound used ONLY to detect a hang/deadlock in
# an all-fake, no-real-sleep test - not a performance assertion.
_HANG_GUARD_SECONDS = 5.0


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
    """Every judgment echoes an unmistakable marker derived from its OWN
    input claim_id (the reason_code) - used by the claim-association tests
    to prove no cross-claim contamination."""
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


class _PeakConcurrencyTracker:
    """Thread-safe counter of currently-in-flight fake judge calls, tracking
    the historical peak. Used to prove GAP_ANALYSIS_MAX_CONCURRENCY is
    actually respected (never exceeded) and, where forced via a Barrier,
    actually reached (genuine overlap, not accidentally-serialized)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.current = 0
        self.peak = 0

    def enter(self) -> None:
        with self._lock:
            self.current += 1
            self.peak = max(self.peak, self.current)

    def exit(self) -> None:
        with self._lock:
            self.current -= 1


def _set_concurrency(monkeypatch, value: int) -> None:
    monkeypatch.setattr(gap_analysis_module, "GAP_ANALYSIS_MAX_CONCURRENCY", value)


@pytest.fixture(autouse=True)
def _pin_batch_size_to_one(monkeypatch):
    """This file is SCHEDULING-CONCURRENCY validation only (see module
    docstring) - written BEFORE Phase-9 PAIR BATCHING existed, and every
    test here mocks ONLY the single-claim judge_claim_semantic. Pin
    GAP_ANALYSIS_BATCH_SIZE to its pre-batching value (1) for every test in
    this file so batching - now a separate, independent, and separately
    tested dimension (see tests/test_phase9_pair_batching.py) - never
    silently activates here and routes an unmocked claim group to the real
    judge_claims_batch (which, since GAP_ANALYSIS_BATCH_SIZE's production
    default is now 2, would otherwise attempt a real, rate-limited provider
    call from what must remain a fully offline test file). This keeps every
    test here exercising exactly what it was designed to exercise:
    concurrency, in isolation from batching."""
    monkeypatch.setattr(gap_analysis_module, "GAP_ANALYSIS_BATCH_SIZE", 1)


class TestConcurrencyEqualsOne:
    def test_peak_concurrency_never_exceeds_one(self, monkeypatch, no_network):
        tracker = _PeakConcurrencyTracker()

        def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
            tracker.enter()
            try:
                time.sleep(0.01)
                return _judgment(claim_id)
            finally:
                tracker.exit()

        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _fake)
        _set_concurrency(monkeypatch, 1)
        state, claims = _build_state(["c-1", "c-2", "c-3"])
        gaps = analyze_gaps(state)
        assert tracker.peak == 1
        assert gaps == []  # all SUPPORTED
        assert state["claim_judge_calls_used"] == 3

    def test_result_semantics_match_pre_concurrency_sequential_behavior(self, monkeypatch, no_network):
        """Fixed fixture: claim c-2 is weakly supported, others supported -
        identical gaps to what the pre-concurrency sequential code produced."""

        def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
            label = SupportLabel.PARTIALLY_SUPPORTED if claim_id == "c-2" else SupportLabel.SUPPORTED
            return _judgment(claim_id, label)

        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _fake)
        _set_concurrency(monkeypatch, 1)
        state, claims = _build_state(["c-1", "c-2", "c-3"])
        gaps = analyze_gaps(state)
        assert [g.gap_type for g in gaps] == [GapType.WEAKLY_SUPPORTED_FACT]
        assert gaps[0].related_claim_id == "c-2"


class TestConcurrencyEqualsTwo:
    def test_peak_concurrency_at_most_two_and_genuinely_overlaps(self, monkeypatch, no_network):
        tracker = _PeakConcurrencyTracker()
        barrier = threading.Barrier(2, timeout=_HANG_GUARD_SECONDS)

        def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
            tracker.enter()
            try:
                # Forces BOTH workers to be simultaneously in-flight before
                # either can return - proves genuine overlap, not merely
                # "never observed exceeding 2 by luck".
                barrier.wait()
                return _judgment(claim_id)
            finally:
                tracker.exit()

        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _fake)
        _set_concurrency(monkeypatch, 2)
        state, claims = _build_state(["c-1", "c-2"])
        gaps = analyze_gaps(state)
        assert tracker.peak == 2
        assert gaps == []


class TestConcurrencyEqualsFour:
    def test_peak_concurrency_bounded_at_four_with_more_work_available(self, monkeypatch, no_network):
        """6 claims need judging (more than GAP_ANALYSIS_MAX_CONCURRENCY=4) -
        proves the pool never exceeds 4 simultaneously-running workers even
        though there is enough work for more."""
        tracker = _PeakConcurrencyTracker()
        # Only the first wave (4 workers) rendezvous together; this proves
        # concurrency actually reaches 4, not merely "stays under an
        # unreachable ceiling".
        first_wave_barrier = threading.Barrier(4, timeout=_HANG_GUARD_SECONDS)
        first_wave_done = threading.Event()
        lock = threading.Lock()
        seen = {"count": 0}

        def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
            tracker.enter()
            try:
                with lock:
                    seen["count"] += 1
                    is_first_wave = seen["count"] <= 4
                if is_first_wave:
                    first_wave_barrier.wait()
                    first_wave_done.set()
                else:
                    first_wave_done.wait(timeout=_HANG_GUARD_SECONDS)
                return _judgment(claim_id)
            finally:
                tracker.exit()

        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _fake)
        _set_concurrency(monkeypatch, 4)
        state, claims = _build_state([f"c-{i}" for i in range(6)])
        start = time.monotonic()
        gaps = analyze_gaps(state)
        elapsed = time.monotonic() - start
        assert tracker.peak == 4
        assert elapsed < _HANG_GUARD_SECONDS
        assert gaps == []
        assert state["claim_judge_calls_used"] == 6


class TestOrderingIndependentOfCompletionOrder:
    def test_scrambled_completion_order_still_yields_claim_order_gaps(self, monkeypatch, no_network):
        """Forces completion order c-3, c-1, c-4, c-2 (via a per-claim
        release-event chain driven from a background controller thread) but
        every claim is judged CONTRADICTED (so every claim produces a gap) -
        the returned gaps list must still be in claim-1-then-2-then-3-then-4
        order, never completion order."""
        release = {cid: threading.Event() for cid in ("c-1", "c-2", "c-3", "c-4")}

        def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
            assert release[claim_id].wait(timeout=_HANG_GUARD_SECONDS), f"{claim_id} never released"
            return _judgment(claim_id, SupportLabel.CONTRADICTED)

        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _fake)
        _set_concurrency(monkeypatch, 4)
        state, claims = _build_state(["c-1", "c-2", "c-3", "c-4"])

        completion_order = ["c-3", "c-1", "c-4", "c-2"]

        def _driver():
            for cid in completion_order:
                time.sleep(0.01)  # scheduling control only, not perf evidence
                release[cid].set()

        driver_thread = threading.Thread(target=_driver)
        driver_thread.start()
        try:
            gaps = analyze_gaps(state)
        finally:
            driver_thread.join(timeout=_HANG_GUARD_SECONDS)

        assert [g.related_claim_id for g in gaps] == ["c-1", "c-2", "c-3", "c-4"]
        assert [g.gap_type for g in gaps] == [GapType.CONFLICTING_EVIDENCE] * 4


class TestClaimAssociationNoCrossContamination:
    def test_each_gap_carries_only_its_own_claims_marker(self, monkeypatch, no_network):
        def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
            # c-B is weak, others supported - only c-B should produce a gap,
            # and it must reference only claim_id "c-B", never any other.
            label = SupportLabel.UNSUPPORTED if claim_id == "c-B" else SupportLabel.SUPPORTED
            return _judgment(claim_id, label)

        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _fake)
        _set_concurrency(monkeypatch, 4)
        state, claims = _build_state(["c-A", "c-B", "c-C", "c-D"])
        gaps = analyze_gaps(state)
        assert len(gaps) == 1
        assert gaps[0].related_claim_id == "c-B"
        assert "c-A" not in gaps[0].description
        assert "c-C" not in gaps[0].description
        assert "c-D" not in gaps[0].description


class TestBudgetUnderConcurrency:
    def test_exactly_at_budget_all_judged(self, monkeypatch, no_network):
        calls: List[str] = []
        lock = threading.Lock()

        def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
            with lock:
                calls.append(claim_id)
            return _judgment(claim_id)

        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _fake)
        _set_concurrency(monkeypatch, 4)
        state, claims = _build_state([f"c-{i}" for i in range(CLAIM_EVALUATION_BUDGET)])
        analyze_gaps(state)
        assert len(calls) == CLAIM_EVALUATION_BUDGET
        assert state["claim_judge_calls_used"] == CLAIM_EVALUATION_BUDGET

    def test_one_over_budget_exactly_one_exhausted(self, monkeypatch, no_network):
        calls: List[str] = []
        lock = threading.Lock()

        def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
            with lock:
                calls.append(claim_id)
            return _judgment(claim_id)

        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _fake)
        _set_concurrency(monkeypatch, 4)
        n = CLAIM_EVALUATION_BUDGET + 1
        state, claims = _build_state([f"c-{i}" for i in range(n)])
        gaps = analyze_gaps(state)
        assert len(calls) == CLAIM_EVALUATION_BUDGET
        exhausted = [g for g in gaps if g.gap_type == GapType.EVALUATION_BUDGET_EXHAUSTED]
        assert len(exhausted) == 1
        assert exhausted[0].related_claim_id == claims[-1].claim_id
        assert state["claim_judge_calls_used"] == CLAIM_EVALUATION_BUDGET

    def test_concurrent_scheduling_never_overshoots_remaining_budget(self, monkeypatch, no_network):
        """GAP_ANALYSIS_MAX_CONCURRENCY=4, only 2 budget slots remain, 10
        claims need judging - exactly 2 real judge calls must be made,
        counted via the fake's own invocation log (never more), proving
        Step A's sequential pre-reservation prevents any concurrent
        overshoot."""
        calls: List[str] = []
        lock = threading.Lock()

        def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
            with lock:
                calls.append(claim_id)
            return _judgment(claim_id)

        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _fake)
        _set_concurrency(monkeypatch, 4)
        state, claims = _build_state(
            [f"c-{i}" for i in range(10)],
            claim_judge_calls_used=CLAIM_EVALUATION_BUDGET - 2,
        )
        gaps = analyze_gaps(state)
        assert len(calls) == 2, f"expected exactly 2 real judge calls, got {len(calls)}: {calls}"
        exhausted = [g for g in gaps if g.gap_type == GapType.EVALUATION_BUDGET_EXHAUSTED]
        assert len(exhausted) == 8
        assert state["claim_judge_calls_used"] == CLAIM_EVALUATION_BUDGET


class TestFailureIsolation:
    def test_single_worker_failure_does_not_propagate_or_fabricate_gap(self, monkeypatch, no_network):
        def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
            if claim_id == "c-2":
                raise RuntimeError("simulated provider failure")
            return _judgment(claim_id)

        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _fake)
        _set_concurrency(monkeypatch, 4)
        state, claims = _build_state(["c-1", "c-2", "c-3"])
        gaps = analyze_gaps(state)  # must not raise
        assert gaps == []
        assert state["claim_judge_calls_used"] == 3

    def test_multiple_worker_failures_isolated_from_each_other(self, monkeypatch, no_network):
        def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
            if claim_id in ("c-1", "c-3"):
                raise RuntimeError(f"simulated failure for {claim_id}")
            return _judgment(claim_id)

        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _fake)
        _set_concurrency(monkeypatch, 4)
        state, claims = _build_state(["c-1", "c-2", "c-3", "c-4"])
        gaps = analyze_gaps(state)
        assert gaps == []
        assert state["claim_judge_calls_used"] == 4

    def test_all_workers_fail_no_exception_escapes(self, monkeypatch, no_network):
        def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
            raise RuntimeError("simulated failure for all")

        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _fake)
        _set_concurrency(monkeypatch, 4)
        state, claims = _build_state(["c-1", "c-2", "c-3"])
        gaps = analyze_gaps(state)  # must not raise
        assert gaps == []
        assert state["claim_judge_calls_used"] == 3

    def test_mixed_failure_and_success_preserves_successful_results(self, monkeypatch, no_network):
        def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
            if claim_id == "c-2":
                raise RuntimeError("simulated failure")
            if claim_id == "c-3":
                return _judgment(claim_id, SupportLabel.CONTRADICTED)
            return _judgment(claim_id, SupportLabel.SUPPORTED)

        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _fake)
        _set_concurrency(monkeypatch, 4)
        state, claims = _build_state(["c-1", "c-2", "c-3", "c-4"])
        gaps = analyze_gaps(state)
        assert len(gaps) == 1
        assert gaps[0].related_claim_id == "c-3"
        assert gaps[0].gap_type == GapType.CONFLICTING_EVIDENCE
        assert state["claim_judge_calls_used"] == 4


class TestRetryNotDoubleCounted:
    def test_scheduling_layer_calls_judge_exactly_once_per_scheduled_claim(self, monkeypatch, no_network):
        """judge_claim_semantic's own internal retry (bounded retry=2 inside
        _invoke_judge - untouched here) is invisible to the scheduling
        layer: from analyze_gaps's point of view, each scheduled claim
        results in exactly ONE call to judge_claim_semantic, regardless of
        how many HTTP-level attempts happened inside it. This test proves
        the NEW scheduling code does not itself double-dispatch a claim."""
        call_count: Dict[str, int] = {}
        lock = threading.Lock()

        def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
            with lock:
                call_count[claim_id] = call_count.get(claim_id, 0) + 1
            return _judgment(claim_id)

        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _fake)
        _set_concurrency(monkeypatch, 4)
        claim_ids = ["c-1", "c-2", "c-3", "c-4", "c-5"]
        state, claims = _build_state(claim_ids)
        analyze_gaps(state)
        assert call_count == {cid: 1 for cid in claim_ids}
        assert state["claim_judge_calls_used"] == len(claim_ids)


class TestRateLimiterPassThroughUnderConcurrency:
    def test_every_dispatched_claim_passes_through_shared_rate_limiter(self, monkeypatch, no_network):
        """Does NOT mock judge_claim_semantic itself - instead mocks
        `requests.post` (so no real HTTP happens) and the Cerebras API key,
        and spies on grounding_eval.judge.wait_for_rate_limit, to prove the
        REAL judge_claim_semantic -> _invoke_judge -> wait_for_rate_limit
        call chain is exercised once per dispatched claim, from whichever
        worker thread, under concurrency=4."""
        import json as _json

        import grounding_eval.judge as judge_module
        from pydantic import SecretStr

        monkeypatch.setattr(judge_module.settings, "CEREBRAS_API_KEY", SecretStr("fake-test-key"))

        rate_limit_calls: List[str] = []
        rate_limit_lock = threading.Lock()
        real_wait_for_rate_limit = judge_module.wait_for_rate_limit

        def _spy_wait_for_rate_limit(*args, **kwargs):
            with rate_limit_lock:
                rate_limit_calls.append(threading.current_thread().name)
            # Do NOT call the real limiter's sleep behavior in a way that
            # could serialize/slow the test meaningfully - the real
            # TokenBucket is thread-safe (Phase-9 audited) and cheap for a
            # capacity=1 bucket at this tiny call volume; call through to
            # keep this a genuine pass-through spy, not a stub replacement.
            return real_wait_for_rate_limit(*args, **kwargs)

        monkeypatch.setattr(judge_module, "wait_for_rate_limit", _spy_wait_for_rate_limit)

        # Pre-fill the SHARED production token bucket (keyed by the real
        # CEREBRAS_RATE_LIMIT_KEY) so this test observes the pass-through
        # behavior instantly instead of genuinely throttling to the real
        # 5-calls/minute rate (which would make this deterministic-
        # correctness test take real wall-clock minutes for no benefit - the
        # rate limiter's OWN correctness/rate/config is explicitly out of
        # scope and untouched; this only seeds the token COUNT for test
        # speed, exactly like freezing a clock, and is restored by
        # monkeypatch's teardown since we snapshot and restore it manually
        # below rather than mutating the module's rate/capacity/logic).
        from utils.rate_limiter import _rate_limiter as _real_rate_limiter

        bucket = _real_rate_limiter.get_bucket(
            judge_module.CEREBRAS_RATE_LIMIT_KEY, judge_module.CEREBRAS_RATE_LIMIT_RPS, capacity=1
        )
        original_tokens = bucket.tokens
        original_capacity = bucket.capacity

        class _FakeResponse:
            status_code = 200

            def json(self):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": _json.dumps(
                                    {
                                        "support_label": "supported",
                                        "citation_relations": [],
                                        "unsupported_fragments": [],
                                        "reason_code": "fake",
                                    }
                                )
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }

            text = "{}"

        def _fake_post(*args, **kwargs):
            return _FakeResponse()

        monkeypatch.setattr(judge_module.requests, "post", _fake_post)
        _set_concurrency(monkeypatch, 4)

        # NOTE: TokenBucket.consume() clamps `tokens` to `capacity` on every
        # refill step (`min(self.capacity, self.tokens + elapsed*rate)`), so
        # seeding `.tokens` alone is not enough - it snaps back down to
        # `capacity` (1) on the very first consume() call. Both must be
        # raised together, and both are restored in `finally` below, so the
        # SHARED production bucket's real capacity/rate/logic is unchanged
        # once this test ends - this is a test-local, temporary seed of one
        # in-memory instance's state, not a change to the rate limiter
        # module or its configured rates.
        bucket.capacity = 100.0
        bucket.tokens = 100.0  # enough for every call this test dispatches
        try:
            claim_ids = ["c-1", "c-2", "c-3", "c-4"]
            state, claims = _build_state(claim_ids)
            gaps = analyze_gaps(state)

            assert len(rate_limit_calls) == len(claim_ids)
            assert gaps == []
            assert state["claim_judge_calls_used"] == len(claim_ids)
        finally:
            bucket.capacity = original_capacity
            bucket.tokens = original_tokens


class TestDeadlockAndCleanup:
    def test_returns_promptly_and_leaves_no_dangling_threads(self, monkeypatch, no_network):
        """Correctness check for hanging/hung workers - NOT a performance
        measurement. Asserts analyze_gaps returns within a generous bound
        and that thread count returns to its pre-call baseline (no worker
        threads survive the ThreadPoolExecutor context manager)."""

        def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
            return _judgment(claim_id)

        monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _fake)
        _set_concurrency(monkeypatch, 4)
        state, claims = _build_state([f"c-{i}" for i in range(8)])

        baseline_threads = threading.active_count()
        start = time.monotonic()
        gaps = analyze_gaps(state)
        elapsed = time.monotonic() - start
        assert elapsed < _HANG_GUARD_SECONDS
        assert gaps == []
        # Give the executor's internal thread bookkeeping a moment to settle
        # (shutdown(wait=True) already blocked until worker functions
        # returned, but OS thread teardown can lag microseconds) - polling
        # a hang-guard bound, not measuring performance.
        deadline = time.monotonic() + _HANG_GUARD_SECONDS
        while threading.active_count() > baseline_threads and time.monotonic() < deadline:
            time.sleep(0.01)
        assert threading.active_count() <= baseline_threads


class TestSemanticEquivalenceAcrossConcurrencyLevels:
    """Step 6 of the concurrency pass: proves concurrency=1/2/4 produce
    IDENTICAL results on a frozen, fixed fixture - a scheduling-equivalence
    proof, NOT a benchmark (the judge responses are fixed/fake here, not
    real judgments being compared for quality)."""

    def test_identical_results_across_concurrency_1_2_4(self, monkeypatch, no_network):
        def _build_fake():
            def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
                labels = {
                    "c-1": SupportLabel.SUPPORTED,
                    "c-2": SupportLabel.PARTIALLY_SUPPORTED,
                    "c-3": SupportLabel.CONTRADICTED,
                    "c-4": SupportLabel.UNSUPPORTED,
                    "c-5": SupportLabel.SUPPORTED,
                }
                return _judgment(claim_id, labels[claim_id])

            return _fake

        claim_ids = ["c-1", "c-2", "c-3", "c-4", "c-5"]
        outcomes = {}
        for concurrency in (1, 2, 4):
            monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _build_fake())
            _set_concurrency(monkeypatch, concurrency)
            state, claims = _build_state(claim_ids)
            gaps = analyze_gaps(state)
            outcomes[concurrency] = (
                [(g.gap_type, g.related_claim_id) for g in gaps],
                state["claim_judge_calls_used"],
            )

        assert outcomes[1] == outcomes[2] == outcomes[4]
        # Sanity: the fixture actually produces a non-trivial mix of gap
        # types, so "identical" is a meaningful assertion, not vacuously true.
        gap_types_seen = {gt for gt, _ in outcomes[1][0]}
        assert GapType.CONFLICTING_EVIDENCE in gap_types_seen
        assert GapType.WEAKLY_SUPPORTED_FACT in gap_types_seen

    def test_identical_budget_exhaustion_pattern_across_concurrency_levels(self, monkeypatch, no_network):
        """Same over-budget scenario at concurrency 1/2/4 must exhaust the
        SAME claim (deterministic, position-based, not completion-order-
        based) and consume the SAME cumulative budget."""

        def _fake(claim_id, claim_text, evidence_ids, evidence_by_id):
            return _judgment(claim_id)

        n = CLAIM_EVALUATION_BUDGET + 3
        claim_ids = [f"c-{i}" for i in range(n)]
        outcomes = {}
        for concurrency in (1, 2, 4):
            monkeypatch.setattr(gap_analysis_module, "judge_claim_semantic", _fake)
            _set_concurrency(monkeypatch, concurrency)
            state, claims = _build_state(claim_ids)
            gaps = analyze_gaps(state)
            exhausted_ids = sorted(
                g.related_claim_id for g in gaps if g.gap_type == GapType.EVALUATION_BUDGET_EXHAUSTED
            )
            outcomes[concurrency] = (exhausted_ids, state["claim_judge_calls_used"])

        assert outcomes[1] == outcomes[2] == outcomes[4]
        assert len(outcomes[1][0]) == 3
        assert outcomes[1][1] == CLAIM_EVALUATION_BUDGET
