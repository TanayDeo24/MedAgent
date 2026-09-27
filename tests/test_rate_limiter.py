"""Deterministic unit tests for utils/rate_limiter.py.

These tests inject a fake clock (monkeypatching time.time/time.sleep inside
utils.rate_limiter) instead of relying on real wall-clock timing, so they are
fast and non-flaky and actually exercise the TokenBucket / RateLimiter /
rate_limit() code paths directly (rather than through a tool method that gets
fully mocked away, which was the bug in the old
test_pubmed.py::test_rate_limit_applied and
test_chembl.py::test_rate_limit_applied — @patch on a decorated method
replaces the decorator's wrapper entirely, so the limiter is never invoked).
"""

import pytest

import utils.rate_limiter as rl_module
from utils.rate_limiter import TokenBucket, RateLimiter, rate_limit


class FakeClock:
    """Controllable fake clock: time.time() reads it, time.sleep() advances it."""

    def __init__(self, start: float = 0.0):
        self.now = start
        self.sleep_calls = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.now += seconds


@pytest.fixture
def fake_clock(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(rl_module.time, "time", clock.time)
    monkeypatch.setattr(rl_module.time, "sleep", clock.sleep)
    return clock


class TestTokenBucket:
    def test_starts_full(self, fake_clock):
        bucket = TokenBucket(rate=3, capacity=3)
        assert bucket.tokens == 3

    def test_consume_depletes_tokens(self, fake_clock):
        bucket = TokenBucket(rate=3, capacity=3)
        assert bucket.consume(1) is True
        assert bucket.tokens == pytest.approx(2)

    def test_consume_fails_when_empty(self, fake_clock):
        bucket = TokenBucket(rate=1, capacity=1)
        assert bucket.consume(1) is True
        # No time has passed, bucket is empty -> next consume must fail.
        assert bucket.consume(1) is False

    def test_tokens_refill_over_time(self, fake_clock):
        bucket = TokenBucket(rate=2, capacity=2)  # 2 tokens/sec
        assert bucket.consume(2) is True
        assert bucket.consume(1) is False
        fake_clock.now += 0.5  # 0.5s * 2/s = 1 token refilled
        assert bucket.consume(1) is True
        assert bucket.consume(1) is False

    def test_tokens_capped_at_capacity(self, fake_clock):
        bucket = TokenBucket(rate=2, capacity=2)
        fake_clock.now += 100  # huge elapsed time
        bucket.consume(0)  # trigger a refill computation
        assert bucket.tokens <= 2

    def test_wait_for_token_blocks_until_available_deterministically(self, fake_clock):
        """wait_for_token must not return before enough tokens are available,
        and must return once they are - verified via the fake clock rather
        than real elapsed wall-clock time."""
        bucket = TokenBucket(rate=1, capacity=1)  # 1 token/sec
        assert bucket.consume(1) is True  # bucket now empty

        # wait_for_token should loop, sleeping in 0.1s increments (per
        # implementation) until >=1 token has refilled.
        bucket.wait_for_token(1)

        assert fake_clock.now >= 1.0 - 0.1  # advanced roughly one refill period
        assert len(fake_clock.sleep_calls) > 0


class TestRateLimiterWait:
    def test_wait_consumes_without_blocking_when_tokens_available(self, fake_clock):
        limiter = RateLimiter()
        limiter.wait("k", rate=5, capacity=5)
        assert fake_clock.sleep_calls == []  # first call has a full bucket

    def test_wait_blocks_when_bucket_exhausted(self, fake_clock):
        limiter = RateLimiter()
        # capacity=1 so the 2nd immediate call must wait for a refill.
        limiter.wait("k2", rate=1, capacity=1)
        limiter.wait("k2", rate=1, capacity=1)
        assert len(fake_clock.sleep_calls) > 0
        assert fake_clock.now > 0

    def test_separate_keys_have_independent_buckets(self, fake_clock):
        limiter = RateLimiter()
        limiter.wait("a", rate=1, capacity=1)
        limiter.wait("b", rate=1, capacity=1)
        # Different keys shouldn't block each other even though each bucket
        # individually would be exhausted after one call.
        assert fake_clock.sleep_calls == []


class TestRateLimitDecorator:
    def test_decorator_calls_underlying_function(self, fake_clock):
        calls = []

        @rate_limit("dec_key", 5)
        def fn(x):
            calls.append(x)
            return x * 2

        assert fn(3) == 6
        assert calls == [3]

    def test_decorator_enforces_rate_across_calls(self, fake_clock):
        """4 rapid calls at rate=3/s (capacity defaults to rate=3) must incur
        at least one wait, and the fake clock must advance accordingly -
        deterministically, with no real sleeping."""
        # Use a fresh key so this test doesn't share bucket state with others.
        @rate_limit("dec_key_burst", 3)
        def fn():
            return True

        for _ in range(4):
            fn()

        # 4 calls against a 3-capacity bucket must have required at least
        # one refill wait.
        assert fake_clock.now > 0
