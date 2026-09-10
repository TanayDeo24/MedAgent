"""LLM configuration for MedAgent using NVIDIA NIM (Nemotron).

This module provides utilities to initialize and configure the NVIDIA NIM-hosted
Nemotron LLM for use in the MedAgent autonomous research assistant.
"""

import os
import threading
import time
from typing import Optional
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from dotenv import load_dotenv

from utils.rate_limiter import wait_for_rate_limit
from utils.retry_handler import calculate_backoff
from utils.logger import get_logger

logger = get_logger(__name__)

# Load environment variables from .env file
load_dotenv()

NVIDIA_MODEL = "nvidia/nemotron-3-super-120b-a12b"

# NVIDIA NIM's free tier caps requests at 40/minute with no daily cap. A
# single agent run already makes 7-15+ sequential LLM calls; running dozens
# of evaluation test cases back-to-back would blow past 40 RPM in minutes
# without this. Capped at 35 (not 40) to leave headroom for retries - a
# burst of retries after a transient 503 could otherwise tip a run over the
# hard limit even though steady-state usage was fine.
NVIDIA_RATE_LIMIT_RPM = 35
NVIDIA_RATE_LIMIT_KEY = "nvidia_nim_llm"

# Hard per-call timeout, enforced independently of ChatNVIDIA's own
# `timeout` constructor parameter. That parameter was observed live to NOT
# bound an already-open connection that stops sending data (a real 60-case
# evaluation batch hung for 90+ minutes on a single call, ChatNVIDIA's
# timeout=30 never firing) - see EVAL_HANG_FIX_COMPLETE.md for the full
# incident. 90s is generous enough for Nemotron's known long internal
# reasoning_content chains on synthesis/report/hallucination-judge calls
# (observed 15-55s for legitimate large-prompt calls in this same incident's
# own logs) while still being a real, enforced ceiling instead of an
# advisory one.
LLM_CALL_TIMEOUT_SECONDS = 90
# 1 initial attempt + 2 retries. Not infinite - if the endpoint is reliably
# unresponsive, failing fast (and letting the calling node's existing
# try/except handle it like any other LLM error) beats stalling the batch
# again just with extra steps first.
LLM_CALL_MAX_ATTEMPTS = 3

# langchain_nvidia_ai_endpoints raises transient provider errors (429 rate
# limits, 503 overloaded) as a plain Exception with the status embedded in
# the message text (see _common.py's _try_raise) - there's no dedicated
# exception subclass or .status_code attribute to catch by type. Matched by
# substring against both the numeric code and NVIDIA's own wording, since
# real observed messages vary in exact shape (e.g. "[429] Too Many Requests"
# vs "[###] {'code': 503, ...}"). These were observed live and repeatedly in
# real evaluation runs (see PHASE3_CONCURRENCY_VALIDATION.md and
# EVAL_HANG_FIX_COMPLETE.md) with no retry at this layer previously - only
# timeouts were retried, so every 429/503 failed its call outright.
_RETRYABLE_ERROR_MARKERS = (
    "429", "503", "Too Many Requests", "Service Unavailable", "temporarily overloaded"
)


def _is_retryable_llm_error(exc: Exception) -> bool:
    """True if `exc` looks like a transient provider error (429/503) worth
    retrying with a fresh client, rather than a real, non-retryable failure
    (e.g. a 400/401/404) that should propagate immediately as before."""
    text = str(exc)
    return any(marker in text for marker in _RETRYABLE_ERROR_MARKERS)


class LLMCallTimeoutError(Exception):
    """Raised when an LLM call exceeds LLM_CALL_TIMEOUT_SECONDS on every
    retry attempt (each attempt made with a freshly-constructed client)."""


def _invoke_with_hard_timeout(llm: ChatNVIDIA, args: tuple, kwargs: dict, timeout: float):
    """Run llm.invoke(*args, **kwargs) with a real, enforced wall-clock cap.

    Uses a daemon `threading.Thread` rather than
    `concurrent.futures.ThreadPoolExecutor` deliberately: if the underlying
    call truly never returns (as observed - a stuck socket read that
    outlived ChatNVIDIA's own `timeout=30` entirely), ThreadPoolExecutor
    registers an atexit handler that joins every worker thread from every
    pool ever created before the interpreter can exit. A stuck worker there
    would silently reproduce this exact hang at process-exit time instead of
    mid-batch - trading a visible hang for an invisible one. A daemon thread
    carries no such join-at-exit obligation: if it never finishes, the OS
    simply reclaims it when the process ends, and this function has already
    moved on because it only waits up to `timeout` via `thread.join()`.

    Returns:
        (completed: bool, result: Any) - completed=False means the timeout
        was hit and the thread was abandoned (still possibly running, but
        no longer waited on).

    Raises:
        Whatever exception `llm.invoke()` itself raised, if it completed
        within the timeout but failed (e.g. a real 503) - re-raised here so
        callers see the same exception type they always would.
    """
    outcome: dict = {}

    def _target():
        try:
            outcome["value"] = llm.invoke(*args, **kwargs)
        except Exception as e:
            outcome["error"] = e

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        return False, None

    if "error" in outcome:
        raise outcome["error"]

    return True, outcome.get("value")

_llm_call_lock = threading.Lock()
_llm_call_count = 0

# Per-thread call counter, in addition to the global one above. Needed for
# evaluation/evaluator.py's case-level concurrency (Phase 3): when multiple
# test cases run in parallel threads, each one's own "how many LLM calls did
# THIS case make" can no longer be computed as a before/after delta on the
# single global counter, since other concurrently-running cases would be
# incrementing it in between. threading.local() gives each thread (and, in
# this codebase's usage, each concurrently-running test case) its own
# isolated count with no locking needed - no other thread can ever see or
# mutate another thread's local storage.
_thread_local = threading.local()


def get_llm_call_count() -> int:
    """Return the total number of rate-limited LLM invocations made in this
    process since the last reset (see reset_llm_call_count()).

    This is the single source of truth for "how many LLM calls did this run
    actually make" - every get_llm() caller's invoke() passes through
    _RateLimitedChatNVIDIA, so this counts every real call, not an estimate
    reconstructed from node structure. Under concurrent execution (multiple
    threads calling invoke() at once) this global count is still accurate in
    total, but a before/after delta on it is NOT a reliable per-task count -
    use get_thread_llm_call_count() for that instead.
    """
    return _llm_call_count


def reset_llm_call_count() -> None:
    """Reset the global LLM call counter to 0.

    Call before starting a batch (e.g. an evaluation run) to get an
    accurate count scoped to just that batch.
    """
    global _llm_call_count
    with _llm_call_lock:
        _llm_call_count = 0


def get_thread_llm_call_count() -> int:
    """Return the number of LLM invocations made by the CURRENT thread only,
    since that thread's last reset_thread_llm_call_count() call.

    Use this (not a delta on get_llm_call_count()) to measure a single
    task's own LLM usage when multiple tasks may be running concurrently in
    different threads.
    """
    return getattr(_thread_local, "count", 0)


def reset_thread_llm_call_count() -> None:
    """Reset the current thread's local LLM call counter to 0."""
    _thread_local.count = 0


class _RateLimitedChatNVIDIA:
    """Wraps a ChatNVIDIA instance so every invoke() call is rate-limited,
    counted, and bounded by a real hard timeout with fresh-connection retry.

    Applied here, at the point get_llm() constructs the client, rather than
    at each node's call site - so all of this is a permanent, global
    safeguard for every current and future caller of get_llm(), not just
    evaluation runs (though that's where it matters most in practice).
    """

    def __init__(self, llm: ChatNVIDIA, construct_kwargs: dict):
        self._llm = llm
        # Kept so a timed-out attempt can discard this client and build a
        # genuinely fresh one for the retry, rather than reusing whatever
        # connection/session state made the original call hang - the 8
        # stale CLOSE_WAIT sockets observed during the incident this fixes
        # suggest connection reuse may itself have been part of what went
        # stale, not just an unlucky single request.
        self._construct_kwargs = construct_kwargs

    def invoke(self, *args, **kwargs):
        global _llm_call_count
        last_exc: Optional[Exception] = None

        for attempt in range(LLM_CALL_MAX_ATTEMPTS):
            # capacity=1.0 (no burst allowance) is required, not optional,
            # here: TokenBucket's default capacity equals `rate`, and 35 RPM
            # as a per-second rate is 0.583 - a bucket capped at 0.583
            # tokens can never reach the 1 token a single call consumes, so
            # consume(1) would fail forever without an explicit capacity >= 1.
            wait_for_rate_limit(NVIDIA_RATE_LIMIT_KEY, NVIDIA_RATE_LIMIT_RPM / 60.0, capacity=1.0)
            with _llm_call_lock:
                _llm_call_count += 1
            _thread_local.count = getattr(_thread_local, "count", 0) + 1
            # Precise per-dispatch timestamp + thread id, logged at request
            # time (not just on failure) - added to investigate whether
            # concurrent workers can be released from the token bucket in a
            # tight cluster rather than evenly spaced, which an aggregate
            # calls/min figure alone can't reveal. See
            # PHASE3_CONCURRENCY_VALIDATION.md for what this found.
            dispatch_time = time.time()
            thread_id = threading.get_ident()
            logger.info(f"[LLM DISPATCH] thread={thread_id} t={dispatch_time:.4f}")

            try:
                completed, result = _invoke_with_hard_timeout(
                    self._llm, args, kwargs, LLM_CALL_TIMEOUT_SECONDS
                )
            except Exception as e:
                logger.info(
                    f"[LLM DISPATCH RESULT] thread={thread_id} t={time.time():.4f} "
                    f"error={type(e).__name__}: {str(e)[:100]}"
                )
                if not _is_retryable_llm_error(e):
                    # A real, non-retryable error (e.g. a 400/401/404) - let
                    # it propagate immediately exactly as before, so existing
                    # per-node try/except handling for anything outside the
                    # 429/503 case is unaffected.
                    raise
                last_exc = e
                logger.warning(
                    f"[LLM RETRY] Call failed with a retryable provider error "
                    f"(attempt {attempt + 1}/{LLM_CALL_MAX_ATTEMPTS}): {e} - "
                    f"discarding client and retrying with a fresh connection"
                )
                # Same fresh-client-and-backoff pattern as the timeout path
                # below, sharing the same attempt budget - a 429/503 no
                # longer fails the call outright on the very first sight of
                # it (previously the only retry that ever happened here was
                # for a hang, never for a real transient provider error).
                self._llm = ChatNVIDIA(**self._construct_kwargs)
                if attempt < LLM_CALL_MAX_ATTEMPTS - 1:
                    time.sleep(calculate_backoff(attempt))
                continue

            if completed:
                logger.info(f"[LLM DISPATCH RESULT] thread={thread_id} t={time.time():.4f} status=success")
                return result

            last_exc = LLMCallTimeoutError(
                f"LLM call did not return within {LLM_CALL_TIMEOUT_SECONDS}s "
                f"(attempt {attempt + 1}/{LLM_CALL_MAX_ATTEMPTS})"
            )
            logger.warning(
                f"[LLM TIMEOUT] Call exceeded {LLM_CALL_TIMEOUT_SECONDS}s "
                f"(attempt {attempt + 1}/{LLM_CALL_MAX_ATTEMPTS}) - discarding "
                f"client and retrying with a fresh connection"
            )
            # Discard the stale client/session entirely rather than retrying
            # on it - see _construct_kwargs comment above.
            self._llm = ChatNVIDIA(**self._construct_kwargs)

            if attempt < LLM_CALL_MAX_ATTEMPTS - 1:
                time.sleep(calculate_backoff(attempt))

        raise last_exc

    def __getattr__(self, name):
        return getattr(self._llm, name)


def get_llm(
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout: int = 30,
    model: str = NVIDIA_MODEL
) -> "_RateLimitedChatNVIDIA":
    """Initialize NVIDIA NIM Nemotron LLM with specified parameters.

    Uses NVIDIA's hosted NIM endpoint for the Nemotron model family.

    Args:
        temperature: Controls randomness (0.0 = deterministic, 1.0 = creative).
                    Default 0.3 for balanced reasoning.
        max_tokens: Maximum tokens in response. Default 2048.
        timeout: Request timeout in seconds. Default 30.
        model: NVIDIA NIM model name. Default "nvidia/nemotron-3-super-120b-a12b".

    Returns:
        Configured ChatNVIDIA instance ready for use.

    Raises:
        ValueError: If NVIDIA_API_KEY environment variable is not set.

    Example:
        >>> from config.llm_config import get_llm
        >>> llm = get_llm(temperature=0.5)
        >>> response = llm.invoke("What are EGFR inhibitors?")
        >>> print(response.content)

    Note:
        To get an NVIDIA API key:
        1. Visit https://build.nvidia.com/
        2. Sign in / create an account
        3. Generate an API key for NIM endpoints
        4. Add to .env file as: NVIDIA_API_KEY=your_key_here
    """
    # Get API key from environment
    api_key = os.getenv("NVIDIA_API_KEY")

    if not api_key:
        raise ValueError(
            "NVIDIA_API_KEY not found in environment variables.\n"
            "Please add your API key to the .env file:\n"
            "  NVIDIA_API_KEY=your_key_here\n\n"
            "Get an API key from: https://build.nvidia.com/"
        )

    # Initialize the LLM, wrapped so every invoke() is rate-limited, counted,
    # and hard-timeout-bounded with fresh-client retry (see
    # _RateLimitedChatNVIDIA above). construct_kwargs is kept by the wrapper
    # so it can build a genuinely fresh ChatNVIDIA client if a call hangs.
    construct_kwargs = dict(
        model=model,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    llm = ChatNVIDIA(**construct_kwargs)
    return _RateLimitedChatNVIDIA(llm, construct_kwargs)


def test_llm_connection() -> bool:
    """Test if LLM connection is working.

    Returns:
        True if connection successful, False otherwise.
    """
    try:
        llm = get_llm()
        response = llm.invoke("Say 'Connection successful' and nothing else.")
        return "successful" in response.content.lower()
    except Exception as e:
        print(f"LLM connection test failed: {e}")
        return False


if __name__ == "__main__":
    # Quick test when run directly
    print("Testing NVIDIA NIM (Nemotron) LLM connection...")

    if test_llm_connection():
        print("✓ LLM connection successful!")

        # Show example usage
        llm = get_llm()
        response = llm.invoke("What is an EGFR inhibitor in one sentence?")
        print(f"\nExample response:\n{response.content}")
    else:
        print("✗ LLM connection failed. Check your API key.")
