"""Abstract base class for all MedAgent tools.

Provides common functionality including rate limiting, retry logic,
caching, logging, and standardized result formatting.
"""

import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict

from config.settings import settings
from utils.logger import get_logger, log_tool_call
from utils.retry_handler import RetrySession


@dataclass
class ToolResult:
    """Standardized result format for all tools."""

    success: bool
    data: Optional[Any] = None
    metadata: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary.

        Returns:
            Dictionary representation of the result
        """
        return asdict(self)


class BaseTool(ABC):
    """Abstract base class for all MedAgent tools.

    All tool implementations must inherit from this class and implement
    the required abstract methods.

    Attributes:
        name: Tool name
        base_url: API base URL
        rate_limit: Rate limit in requests per second
        logger: Logger instance
        session: HTTP session with retry logic
        cache: In-memory cache for results
    """

    def __init__(
        self,
        name: str,
        base_url: str,
        rate_limit: int,
        timeout: Optional[int] = None
    ):
        """Initialize base tool.

        Args:
            name: Tool name
            base_url: API base URL
            rate_limit: Rate limit in requests per second
            timeout: Request timeout in seconds
        """
        self.name = name
        self.base_url = base_url
        self.rate_limit = rate_limit
        self.logger = get_logger(f"tools.{name}")
        self.timeout = timeout or settings.API_TIMEOUT

        # Initialize HTTP session with retry logic
        self.session = RetrySession(
            max_retries=settings.MAX_RETRIES,
            backoff_base=settings.RETRY_BACKOFF_BASE,
            timeout=self.timeout
        )

        # In-memory cache: {cache_key: (timestamp, data)}
        self.cache: Dict[str, tuple[float, Any]] = {}

        self.logger.info(f"{name} tool initialized")

    def _get_cache_key(self, method: str, **params: Any) -> str:
        """Generate cache key from method name and parameters.

        Args:
            method: Method name
            **params: Method parameters

        Returns:
            Cache key string
        """
        # Sort params for consistent keys
        param_str = "&".join(
            f"{k}={v}" for k, v in sorted(params.items())
        )
        return f"{method}:{param_str}"

    def _get_from_cache(self, cache_key: str) -> Optional[Any]:
        """Get data from cache if not expired.

        Args:
            cache_key: Cache key

        Returns:
            Cached data or None if not found/expired
        """
        if not settings.ENABLE_CACHE:
            return None

        if cache_key in self.cache:
            timestamp, data = self.cache[cache_key]
            if time.time() - timestamp < settings.CACHE_TTL:
                self.logger.debug(f"Cache hit for {cache_key}")
                return data
            else:
                # Remove expired entry
                del self.cache[cache_key]
                self.logger.debug(f"Cache expired for {cache_key}")

        return None

    def _save_to_cache(self, cache_key: str, data: Any) -> None:
        """Save data to cache.

        Args:
            cache_key: Cache key
            data: Data to cache
        """
        if settings.ENABLE_CACHE:
            self.cache[cache_key] = (time.time(), data)
            self.logger.debug(f"Cached data for {cache_key}")

    def _execute_with_monitoring(
        self,
        method_name: str,
        query: str,
        func: callable,
        **kwargs: Any
    ) -> ToolResult:
        """Execute a function with monitoring and error handling.

        Args:
            method_name: Name of the method being executed
            query: Query string for logging
            func: Function to execute
            **kwargs: Additional arguments for the function

        Returns:
            ToolResult with success status and data or error
        """
        start_time = time.time()
        cache_key = self._get_cache_key(method_name, query=query, **kwargs)

        try:
            # Check cache first
            cached_data = self._get_from_cache(cache_key)
            if cached_data is not None:
                latency_ms = int((time.time() - start_time) * 1000)
                log_tool_call(
                    self.logger,
                    self.name,
                    query,
                    latency_ms,
                    "success",
                    cached=True
                )
                return ToolResult(
                    success=True,
                    data=cached_data,
                    metadata={
                        "query": query,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "tool": self.name,
                        "latency_ms": latency_ms,
                        "cached": True,
                        "results_count": len(cached_data) if isinstance(cached_data, list) else 1
                    }
                )

            # Execute function
            data = func(**kwargs)

            # Parse results
            parsed_data = self.parse_results(data)

            # Save to cache
            self._save_to_cache(cache_key, parsed_data)

            # Calculate latency
            latency_ms = int((time.time() - start_time) * 1000)

            # Log success
            log_tool_call(
                self.logger,
                self.name,
                query,
                latency_ms,
                "success"
            )

            return ToolResult(
                success=True,
                data=parsed_data,
                metadata={
                    "query": query,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "tool": self.name,
                    "latency_ms": latency_ms,
                    "cached": False,
                    "results_count": len(parsed_data) if isinstance(parsed_data, list) else 1
                }
            )

        except Exception as e:
            # Calculate latency
            latency_ms = int((time.time() - start_time) * 1000)

            # Log error
            error_msg = self.handle_errors(e)
            log_tool_call(
                self.logger,
                self.name,
                query,
                latency_ms,
                "error",
                error=error_msg
            )

            return ToolResult(
                success=False,
                error=error_msg,
                metadata={
                    "query": query,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "tool": self.name,
                    "latency_ms": latency_ms,
                }
            )

    @abstractmethod
    def execute(self, *args: Any, **kwargs: Any) -> ToolResult:
        """Execute the tool's main functionality.

        This method must be implemented by all subclasses.

        Args:
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            ToolResult with success status and data or error
        """
        pass

    @abstractmethod
    def parse_results(self, raw_data: Any) -> Any:
        """Parse raw API response into standardized format.

        This method must be implemented by all subclasses.

        Args:
            raw_data: Raw API response

        Returns:
            Parsed data in standardized format
        """
        pass

    def handle_errors(self, error: Exception) -> str:
        """Handle and format errors consistently.

        Args:
            error: Exception that occurred

        Returns:
            Formatted error message
        """
        error_type = type(error).__name__
        error_msg = str(error)

        # Map common errors to user-friendly messages
        error_mapping = {
            "ConnectionError": "Failed to connect to API. Please check your internet connection.",
            "Timeout": "API request timed out. Please try again.",
            "HTTPError": f"API returned an error: {error_msg}",
            "JSONDecodeError": "Failed to parse API response. The API may be experiencing issues.",
            "ValueError": f"Invalid input: {error_msg}",
            "KeyError": f"Missing expected data in API response: {error_msg}",
        }

        return error_mapping.get(error_type, f"{error_type}: {error_msg}")

    def clear_cache(self) -> None:
        """Clear the tool's cache."""
        self.cache.clear()
        self.logger.info(f"Cache cleared for {self.name}")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        return {
            "entries": len(self.cache),
            "size_bytes": sum(
                len(str(v[1])) for v in self.cache.values()
            ),
        }
