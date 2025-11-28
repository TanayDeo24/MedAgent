"""Retry logic with exponential backoff for handling transient failures.

Provides decorators and utilities for automatic retry of failed operations
with configurable backoff strategies.
"""

import time
import random
from functools import wraps
from typing import Callable, Tuple, Type, Any, Optional

import requests
from requests.exceptions import (
    ConnectionError,
    Timeout,
    RequestException
)

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


# HTTP status codes that should trigger a retry
RETRYABLE_STATUS_CODES = {
    429,  # Too Many Requests
    500,  # Internal Server Error
    502,  # Bad Gateway
    503,  # Service Unavailable
    504,  # Gateway Timeout
}

# HTTP status codes that should NOT trigger a retry
NON_RETRYABLE_STATUS_CODES = {
    400,  # Bad Request
    401,  # Unauthorized
    403,  # Forbidden
    404,  # Not Found
    405,  # Method Not Allowed
    422,  # Unprocessable Entity
}


def calculate_backoff(
    attempt: int,
    base: int = None,
    max_backoff: int = None,
    jitter: bool = True
) -> float:
    """Calculate exponential backoff time with optional jitter.

    Args:
        attempt: Current attempt number (0-indexed)
        base: Base multiplier for exponential backoff
        max_backoff: Maximum backoff time in seconds
        jitter: Add random jitter to prevent thundering herd

    Returns:
        Backoff time in seconds
    """
    base = base or settings.RETRY_BACKOFF_BASE
    max_backoff = max_backoff or settings.RETRY_BACKOFF_MAX

    # Calculate exponential backoff: base^attempt
    backoff = min(base ** attempt, max_backoff)

    # Add jitter (random value between 0 and backoff)
    if jitter:
        backoff = backoff * (0.5 + random.random() * 0.5)

    return backoff


def is_retryable_error(exception: Exception) -> bool:
    """Check if an exception is retryable.

    Args:
        exception: Exception to check

    Returns:
        True if the error is retryable, False otherwise
    """
    # Network errors are always retryable
    if isinstance(exception, (ConnectionError, Timeout)):
        return True

    # Check HTTP status codes
    if isinstance(exception, RequestException):
        if hasattr(exception, "response") and exception.response is not None:
            status_code = exception.response.status_code
            return status_code in RETRYABLE_STATUS_CODES

    return False


def retry_on_failure(
    max_retries: Optional[int] = None,
    backoff_base: Optional[int] = None,
    retryable_exceptions: Tuple[Type[Exception], ...] = (
        ConnectionError,
        Timeout,
        RequestException
    )
):
    """Decorator to retry a function on failure with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        backoff_base: Base multiplier for exponential backoff
        retryable_exceptions: Tuple of exception types to retry on

    Returns:
        Decorated function

    Example:
        @retry_on_failure(max_retries=3)
        def fetch_data(url):
            return requests.get(url)
    """
    max_retries = max_retries or settings.MAX_RETRIES
    backoff_base = backoff_base or settings.RETRY_BACKOFF_BASE

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    result = func(*args, **kwargs)

                    # Log successful retry
                    if attempt > 0:
                        logger.info(
                            f"{func.__name__} succeeded after {attempt} retries"
                        )

                    return result

                except retryable_exceptions as e:
                    last_exception = e

                    # Check if this specific error is retryable
                    if not is_retryable_error(e):
                        logger.warning(
                            f"{func.__name__} failed with non-retryable error: {e}"
                        )
                        raise

                    # Don't sleep after the last attempt
                    if attempt < max_retries:
                        backoff = calculate_backoff(attempt, backoff_base)
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}), "
                            f"retrying in {backoff:.2f}s: {e}"
                        )
                        time.sleep(backoff)
                    else:
                        logger.error(
                            f"{func.__name__} failed after {max_retries + 1} attempts: {e}"
                        )

            # All retries exhausted
            raise last_exception

        return wrapper
    return decorator


class RetrySession(requests.Session):
    """Requests session with built-in retry logic.

    Example:
        session = RetrySession(max_retries=3)
        response = session.get("https://api.example.com/data")
    """

    def __init__(
        self,
        max_retries: Optional[int] = None,
        backoff_base: Optional[int] = None,
        timeout: Optional[int] = None,
        *args,
        **kwargs
    ):
        """Initialize retry session.

        Args:
            max_retries: Maximum number of retry attempts
            backoff_base: Base multiplier for exponential backoff
            timeout: Request timeout in seconds
            *args: Additional arguments for requests.Session
            **kwargs: Additional keyword arguments for requests.Session
        """
        super().__init__(*args, **kwargs)
        self.max_retries = max_retries or settings.MAX_RETRIES
        self.backoff_base = backoff_base or settings.RETRY_BACKOFF_BASE
        self.timeout = timeout or settings.API_TIMEOUT

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make HTTP request with retry logic.

        Args:
            method: HTTP method
            url: Request URL
            **kwargs: Additional arguments for requests.request

        Returns:
            Response object

        Raises:
            RequestException: If all retries are exhausted
        """
        # Set default timeout if not provided
        if "timeout" not in kwargs:
            kwargs["timeout"] = self.timeout

        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                response = super().request(method, url, **kwargs)

                # Check for retryable status codes
                if response.status_code in RETRYABLE_STATUS_CODES:
                    if attempt < self.max_retries:
                        backoff = calculate_backoff(attempt, self.backoff_base)
                        logger.warning(
                            f"Request to {url} returned {response.status_code}, "
                            f"retrying in {backoff:.2f}s"
                        )
                        time.sleep(backoff)
                        continue
                    else:
                        response.raise_for_status()

                # Check for non-retryable status codes
                if response.status_code in NON_RETRYABLE_STATUS_CODES:
                    response.raise_for_status()

                # Success
                if attempt > 0:
                    logger.info(f"Request to {url} succeeded after {attempt} retries")

                return response

            except (ConnectionError, Timeout, RequestException) as e:
                last_exception = e

                if not is_retryable_error(e):
                    raise

                if attempt < self.max_retries:
                    backoff = calculate_backoff(attempt, self.backoff_base)
                    logger.warning(
                        f"Request to {url} failed, retrying in {backoff:.2f}s: {e}"
                    )
                    time.sleep(backoff)
                else:
                    logger.error(
                        f"Request to {url} failed after {self.max_retries + 1} attempts: {e}"
                    )

        raise last_exception
