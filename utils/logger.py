"""Structured logging utility for MedAgent.

Provides consistent logging across all tools with support for both
console and file output, JSON formatting, and contextual information.
"""

import logging
import json
import sys
from datetime import datetime
from typing import Any, Dict, Optional
from pathlib import Path

from config.settings import settings


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.

        Args:
            record: Log record to format

        Returns:
            JSON-formatted log string
        """
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields if present
        if hasattr(record, "tool_name"):
            log_data["tool_name"] = record.tool_name
        if hasattr(record, "query"):
            log_data["query"] = record.query
        if hasattr(record, "latency_ms"):
            log_data["latency_ms"] = record.latency_ms
        if hasattr(record, "status"):
            log_data["status"] = record.status
        if hasattr(record, "error"):
            log_data["error"] = record.error

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


class ConsoleFormatter(logging.Formatter):
    """Human-readable console formatter with colors."""

    # ANSI color codes
    COLORS = {
        "DEBUG": "\033[36m",      # Cyan
        "INFO": "\033[32m",       # Green
        "WARNING": "\033[33m",    # Yellow
        "ERROR": "\033[31m",      # Red
        "CRITICAL": "\033[35m",   # Magenta
        "RESET": "\033[0m",       # Reset
    }

    def format(self, record: logging.LogRecord) -> str:
        """Format log record for console with colors.

        Args:
            record: Log record to format

        Returns:
            Formatted log string with color codes
        """
        color = self.COLORS.get(record.levelname, self.COLORS["RESET"])
        reset = self.COLORS["RESET"]

        # Format timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")

        # Build message
        parts = [
            f"{color}{record.levelname:8}{reset}",
            f"[{timestamp}]",
            f"{record.name}:",
            record.getMessage()
        ]

        # Add extra context if available
        if hasattr(record, "tool_name"):
            parts.insert(3, f"[{record.tool_name}]")
        if hasattr(record, "latency_ms"):
            parts.append(f"({record.latency_ms}ms)")

        message = " ".join(parts)

        # Add exception if present
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)

        return message


def get_logger(name: str) -> logging.Logger:
    """Get or create a logger with consistent configuration.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Only configure if not already configured
    if not logger.handlers:
        logger.setLevel(getattr(logging, settings.LOG_LEVEL))
        logger.propagate = False

        # Console handler with human-readable format
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, settings.LOG_LEVEL))
        console_handler.setFormatter(ConsoleFormatter())
        logger.addHandler(console_handler)

        # File handler with JSON format
        try:
            log_file = Path(settings.LOG_FILE)
            log_file.parent.mkdir(parents=True, exist_ok=True)

            file_handler = logging.FileHandler(settings.LOG_FILE)
            file_handler.setLevel(logging.DEBUG)  # Log everything to file
            file_handler.setFormatter(JSONFormatter())
            logger.addHandler(file_handler)
        except Exception as e:
            logger.warning(f"Failed to set up file logging: {e}")

    return logger


def log_tool_call(
    logger: logging.Logger,
    tool_name: str,
    query: str,
    latency_ms: int,
    status: str,
    error: Optional[str] = None,
    **kwargs: Any
) -> None:
    """Log a tool call with structured metadata.

    Args:
        logger: Logger instance
        tool_name: Name of the tool
        query: Query string
        latency_ms: Request latency in milliseconds
        status: Status (success/error)
        error: Error message if status is error
        **kwargs: Additional context to log
    """
    level = logging.INFO if status == "success" else logging.ERROR

    extra = {
        "tool_name": tool_name,
        "query": query,
        "latency_ms": latency_ms,
        "status": status,
    }

    if error:
        extra["error"] = error

    extra.update(kwargs)

    message = f"Tool call {'succeeded' if status == 'success' else 'failed'}: {query[:50]}"
    logger.log(level, message, extra=extra)
