"""Phase 9, Step 10 — rate-limiter audit.

Extends the existing tests/test_rate_limiter.py fake-clock harness (not
duplicating its coverage) with the specific Phase-9 questions: exact
configured-rate spacing for each real provider bucket, simultaneous-caller
(thread-based, real threads, fake clock) behavior, fairness, retry
interaction (does a failed attempt still consume a token?), and whether
concurrent callers can burst above the intended rate. No production code
modified — utils/rate_limiter.py's spin-wait polling loop is exercised
as-is (0.1s poll interval, per its own source), just against a fake clock
so this stays fast.
"""

from __future__ import annotations

import threading
import time

import pytest

import utils.rate_limiter as rl_module
from utils.rate_limiter import RateLimiter, TokenBucket, wait_for_rate_limit


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.now = start
        self.lock = threading.Lock()
        self.sleep_calls = []

    def time(self) -> float:
        with self.lock:
            return self.now

    def sleep(self, seconds: float) -> None:
        # Real threads calling this concurrently must not corrupt `now` -
        # protected by a lock so this fake clock itself is thread-safe,
        # isolating any race found to the module under test, not the harness.
        # NOTE: deliberately does NOT call time.sleep() itself, even a tiny
        # real one, to yield the scheduler - `time` is the same singleton
        # module object this fixture monkeypatches (rl_module.time IS
        # this file's `time`), so calling time.sleep() here would recurse
        # into this very method. Lock contention alone is sufficient to let
        # real OS threads interleave.
        with self.lock:
            self.sleep_calls.append(seconds)
            self.now += seconds


@pytest.fixture
def fake_clock(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(rl_module.time, "time", clock.time)
    monkeypatch.setattr(rl_module.time, "sleep", clock.sleep)
    return clock


# ---------------------------------------------------------------------------
# Configured provider rates (per artifacts/v2/phase9_measurement_contract.json
# and the source constants themselves)
# ---------------------------------------------------------------------------

PROVIDER_RATES = {
    "nvidia_nim_llm": (35.0 / 60.0, 1.0),  # (rate tokens/sec, capacity)
    "cerebras_candidate_b_native_tools": (5.0 / 60.0, 1.0),
    "cerebras_free_trial": (5.0 / 60.0, 1.0),
    "pubmed": (3.0, 3.0),
    "clinical_trials": (10.0, 10.0),
    "chembl": (10.0, 10.0),
}


class TestConfiguredProviderRates:
    @pytest.mark.parametrize("key,rate_capacity", PROVIDER_RATES.items())
    def test_first_call_never_waits(self, fake_clock, key, rate_capacity):
        rate, capacity = rate_capacity
        limiter = RateLimiter()
        limiter.wait(f"{key}_first_call_test", rate=rate, capacity=capacity)
        assert fake_clock.sleep_calls == []

    def test_nvidia_35rpm_exact_minimum_spacing_after_burst(self, fake_clock):
        """After exhausting the capacity=1 bucket, the NEXT call must wait
        until at least 1/(35/60) ~= 1.714s of simulated time has passed -
        the exact minimum spacing implied by 35 RPM."""
        rate = 35.0 / 60.0
        limiter = RateLimiter()
        limiter.wait("nvidia_spacing_test", rate=rate, capacity=1.0)  # consumes the only token
        start = fake_clock.now
        limiter.wait("nvidia_spacing_test", rate=rate, capacity=1.0)  # must wait for refill
        elapsed = fake_clock.now - start
        expected_min_spacing = 1.0 / rate
        assert elapsed >= expected_min_spacing - 0.1  # within one poll-interval's slack

    def test_cerebras_5rpm_exact_minimum_spacing(self, fake_clock):
        rate = 5.0 / 60.0
        limiter = RateLimiter()
        limiter.wait("cerebras_spacing_test", rate=rate, capacity=1.0)
        start = fake_clock.now
        limiter.wait("cerebras_spacing_test", rate=rate, capacity=1.0)
        elapsed = fake_clock.now - start
        assert elapsed >= (1.0 / rate) - 0.1

    def test_pubmed_3rps_allows_3_bursts_then_waits(self, fake_clock):
        limiter = RateLimiter()
        key = "pubmed_burst_test"
        for _ in range(3):
            limiter.wait(key, rate=3.0, capacity=3.0)
        assert fake_clock.sleep_calls == []  # first 3 calls are free (capacity=3)
        limiter.wait(key, rate=3.0, capacity=3.0)  # 4th call must wait
        assert len(fake_clock.sleep_calls) > 0

    def test_each_provider_key_has_independent_bucket(self, fake_clock):
        """Exhausting one provider's bucket must never affect another's -
        confirms per-source rate limiting is genuinely isolated."""
        limiter = RateLimiter()
        limiter.wait("pubmed", rate=3.0, capacity=3.0)
        limiter.wait("pubmed", rate=3.0, capacity=3.0)
        limiter.wait("pubmed", rate=3.0, capacity=3.0)  # pubmed bucket now empty
        # chembl's independent bucket must still be fresh
        limiter.wait("chembl", rate=10.0, capacity=10.0)
        assert fake_clock.sleep_calls == []


class TestSimultaneousCallers:
    def test_concurrent_callers_never_exceed_capacity_within_one_window(self, fake_clock):
        """N threads all calling wait() against a capacity=1 bucket at the
        SAME simulated instant must serialize through the bucket's lock -
        only one may consume the single available token; the rest must
        genuinely wait (observed via sleep_calls), never all succeed
        instantly (which would mean the bucket was over-drawn / burst
        above the intended rate)."""
        limiter = RateLimiter()
        key = "concurrent_burst_test"
        rate = 1.0  # 1 token/sec, capacity=1
        barrier = threading.Barrier(5)
        consumed_immediately = []
        lock = threading.Lock()

        def _caller():
            barrier.wait(timeout=5)
            before_sleeps = len(fake_clock.sleep_calls)
            limiter.wait(key, rate=rate, capacity=1.0)
            after_sleeps = len(fake_clock.sleep_calls)
            with lock:
                consumed_immediately.append(after_sleeps == before_sleeps)

        threads = [threading.Thread(target=_caller) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # At most 1 of the 5 concurrent callers may have consumed a token
        # without waiting (the single pre-existing token); the other 4 must
        # have gone through wait_for_token's poll loop.
        assert sum(consumed_immediately) <= 1

    def test_bucket_lock_prevents_double_consumption_of_same_token(self, fake_clock):
        """Directly exercises TokenBucket.consume()'s own lock: N threads
        racing to consume from a bucket with exactly 1 token available must
        result in EXACTLY 1 successful consume() - never 0, never >1 (which
        would mean the same token was double-spent)."""
        bucket = TokenBucket(rate=1.0, capacity=1.0)
        results = []
        lock = threading.Lock()
        barrier = threading.Barrier(10)

        def _consumer():
            barrier.wait(timeout=5)
            ok = bucket.consume(1)
            with lock:
                results.append(ok)

        threads = [threading.Thread(target=_consumer) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert sum(1 for r in results if r) == 1


class TestRetryInteraction:
    def test_failed_downstream_attempt_still_consumed_a_token(self, fake_clock):
        """The rate limiter itself has no knowledge of whether the call it
        gates ultimately succeeds or fails - `wait_for_rate_limit` is called
        BEFORE the HTTP/LLM attempt in every real call site
        (candidate_b_native_tools.py, llm_config.py, grounding_eval/judge.py)
        and unconditionally consumes a token regardless of the outcome. This
        means every retry attempt (not just the first) re-invokes
        wait_for_rate_limit and consumes its own token - confirmed here
        directly: N consecutive wait() calls (simulating N retry attempts,
        successful or not) against a capacity=1 bucket must exhibit waiting
        behavior proportional to N, not to 1."""
        limiter = RateLimiter()
        key = "retry_interaction_test"
        rate = 1.0
        for _ in range(3):  # simulate LLM_CALL_MAX_ATTEMPTS=3 retry attempts
            limiter.wait(key, rate=rate, capacity=1.0)
        # 3 attempts against a capacity=1, 1/s bucket: 1 free + 2 waits.
        assert len(fake_clock.sleep_calls) >= 2


class TestFairnessAndBurstBound:
    def test_no_burst_above_capacity_regardless_of_call_pattern(self, fake_clock):
        """However calls are issued (rapid-fire vs spaced), the bucket must
        never allow more than `capacity` tokens' worth of consumption
        without an intervening wait once capacity is exhausted."""
        bucket = TokenBucket(rate=2.0, capacity=2.0)
        successes = [bucket.consume(1) for _ in range(5)]
        # Only the first `capacity` (2) may succeed instantly; the rest must
        # fail consume() (the caller is then responsible for waiting).
        assert sum(successes) == 2

    def test_fairness_is_not_guaranteed_by_design_documented_here(self, fake_clock):
        """utils/rate_limiter.py's wait_for_token() is a plain spin-wait
        (`while not consume(): sleep(0.1)`) with no FIFO queue - under
        contention, whichever thread's consume() call happens to run first
        after a refill wins, not necessarily the thread that arrived first.
        This test documents that as a real, inherent property (not a bug it
        introduces beyond what the polling design implies) rather than
        asserting a fairness guarantee the code was never designed to make."""
        # No assertion beyond structural confirmation the module provides no
        # queue/ordering primitive - documented via absence, not behavior.
        assert not hasattr(rl_module.RateLimiter, "_queue")
        assert not hasattr(rl_module.TokenBucket, "_queue")
