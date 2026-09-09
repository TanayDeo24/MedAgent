"""Rate limiting utility using token bucket algorithm.

Provides thread-safe rate limiting for API calls with configurable
limits per API endpoint.
"""

import time
import threading
from functools import wraps
from typing import Callable, Dict, Any
from collections import defaultdict

from utils.logger import get_logger

logger = get_logger(__name__)


class TokenBucket:
    """Thread-safe token bucket for rate limiting.

    Implements the token bucket algorithm to limit the rate of operations.
    Tokens are added at a constant rate and consumed by operations.
    """

    def __init__(self, rate: float, capacity: float = None):
        """Initialize token bucket.

        Args:
            rate: Token refill rate (tokens per second)
            capacity: Maximum tokens in bucket (defaults to rate)
        """
        self.rate = rate
        self.capacity = capacity or rate
        self.tokens = self.capacity
        self.last_update = time.time()
        self.lock = threading.Lock()

    def consume(self, tokens: int = 1) -> bool:
        """Attempt to consume tokens from the bucket.

        Args:
            tokens: Number of tokens to consume

        Returns:
            True if tokens were consumed, False if insufficient tokens
        """
        with self.lock:
            now = time.time()
            elapsed = now - self.last_update

            # Add new tokens based on elapsed time
            self.tokens = min(
                self.capacity,
                self.tokens + elapsed * self.rate
            )
            self.last_update = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def wait_for_token(self, tokens: int = 1) -> None:
        """Wait until tokens are available and consume them.

        Args:
            tokens: Number of tokens to consume
        """
        while not self.consume(tokens):
            time.sleep(0.1)  # Sleep briefly before trying again


class RateLimiter:
    """Global rate limiter managing multiple token buckets."""

    def __init__(self):
        """Initialize rate limiter."""
        self.buckets: Dict[str, TokenBucket] = {}
        self.lock = threading.Lock()

    def get_bucket(self, key: str, rate: float) -> TokenBucket:
        """Get or create a token bucket for the given key.

        Args:
            key: Unique identifier for the bucket
            rate: Token refill rate

        Returns:
            Token bucket instance
        """
        with self.lock:
            if key not in self.buckets:
                self.buckets[key] = TokenBucket(rate)
            return self.buckets[key]

    def wait(self, key: str, rate: float, tokens: int = 1) -> None:
        """Wait for and consume tokens.

        Args:
            key: Bucket identifier
            rate: Token refill rate
            tokens: Number of tokens to consume
        """
        bucket = self.get_bucket(key, rate)
        if not bucket.consume(tokens):
            logger.debug(f"Rate limit reached for {key}, waiting...")
            bucket.wait_for_token(tokens)


# Global rate limiter instance
_rate_limiter = RateLimiter()


def rate_limit(key: str, rate: float):
    """Decorator to rate limit function calls.

    Args:
        key: Unique identifier for this rate limit
        rate: Maximum calls per second

    Returns:
        Decorated function

    Example:
        @rate_limit("pubmed_api", 3)
        def search_pubmed(query):
            # This function will be limited to 3 calls per second
            pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            _rate_limiter.wait(key, rate)
            return func(*args, **kwargs)
        return wrapper
    return decorator


def wait_for_rate_limit(key: str, rate: float) -> None:
    """Manually wait for rate limit.

    Useful when you need to rate limit without using a decorator.

    Args:
        key: Unique identifier for this rate limit
        rate: Maximum calls per second

    Example:
        wait_for_rate_limit("pubmed_api", 3)
        response = requests.get(url)
    """
    _rate_limiter.wait(key, rate)
