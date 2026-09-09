"""LLM configuration for MedAgent using NVIDIA NIM (Nemotron).

This module provides utilities to initialize and configure the NVIDIA NIM-hosted
Nemotron LLM for use in the MedAgent autonomous research assistant.
"""

import os
import threading
from typing import Optional
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from dotenv import load_dotenv

from utils.rate_limiter import wait_for_rate_limit

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

_llm_call_lock = threading.Lock()
_llm_call_count = 0


def get_llm_call_count() -> int:
    """Return the total number of rate-limited LLM invocations made in this
    process since the last reset (see reset_llm_call_count()).

    This is the single source of truth for "how many LLM calls did this run
    actually make" - every get_llm() caller's invoke() passes through
    _RateLimitedChatNVIDIA, so this counts every real call, not an estimate
    reconstructed from node structure.
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


class _RateLimitedChatNVIDIA:
    """Wraps a ChatNVIDIA instance so every invoke() call is rate-limited
    and counted.

    Applied here, at the point get_llm() constructs the client, rather than
    at each node's call site - so the limit is a permanent, global safeguard
    for every current and future caller of get_llm(), not just evaluation
    runs (though that's where it matters most in practice).
    """

    def __init__(self, llm: ChatNVIDIA):
        self._llm = llm

    def invoke(self, *args, **kwargs):
        global _llm_call_count
        # capacity=1.0 (no burst allowance) is required, not optional, here:
        # TokenBucket's default capacity equals `rate`, and 35 RPM as a
        # per-second rate is 0.583 - a bucket capped at 0.583 tokens can
        # never reach the 1 token a single call consumes, so consume(1)
        # would fail forever without an explicit capacity >= 1.
        wait_for_rate_limit(NVIDIA_RATE_LIMIT_KEY, NVIDIA_RATE_LIMIT_RPM / 60.0, capacity=1.0)
        with _llm_call_lock:
            _llm_call_count += 1
        return self._llm.invoke(*args, **kwargs)

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

    # Initialize the LLM, wrapped so every invoke() is rate-limited and
    # counted (see _RateLimitedChatNVIDIA above)
    llm = ChatNVIDIA(
        model=model,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    return _RateLimitedChatNVIDIA(llm)


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
