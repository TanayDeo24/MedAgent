"""Centralized configuration settings for MedAgent.

This module defines all configuration parameters for the MedAgent system,
including API endpoints, rate limits, retry policies, and logging settings.
"""

import os
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    # API Configuration
    PUBMED_BASE_URL: str = Field(
        default="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
        description="Base URL for PubMed E-utilities API"
    )
    CLINICAL_TRIALS_BASE_URL: str = Field(
        default="https://clinicaltrials.gov/api/v2/",
        description="Base URL for ClinicalTrials.gov API"
    )
    CHEMBL_BASE_URL: str = Field(
        default="https://www.ebi.ac.uk/chembl/api/data/",
        description="Base URL for ChEMBL API"
    )

    # Rate Limits (requests per second)
    PUBMED_RATE_LIMIT: int = Field(
        default=3,
        description="PubMed API rate limit (requests per second)"
    )
    CLINICAL_TRIALS_RATE_LIMIT: int = Field(
        default=10,
        description="ClinicalTrials.gov API rate limit (requests per second)"
    )
    CHEMBL_RATE_LIMIT: int = Field(
        default=10,
        description="ChEMBL API rate limit (requests per second)"
    )

    # Retry Configuration
    MAX_RETRIES: int = Field(
        default=3,
        description="Maximum number of retry attempts for failed API calls"
    )
    RETRY_BACKOFF_BASE: int = Field(
        default=2,
        description="Base multiplier for exponential backoff (seconds)"
    )
    RETRY_BACKOFF_MAX: int = Field(
        default=60,
        description="Maximum backoff time in seconds"
    )

    # Timeouts (seconds)
    API_TIMEOUT: int = Field(
        default=30,
        description="API request timeout in seconds"
    )

    # Logging
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    LOG_FILE: str = Field(
        default="logs/medagent.log",
        description="Path to log file"
    )
    LOG_FORMAT: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log message format"
    )

    # Cache Configuration
    CACHE_TTL: int = Field(
        default=3600,
        description="Cache time-to-live in seconds (1 hour)"
    )
    ENABLE_CACHE: bool = Field(
        default=True,
        description="Enable in-memory caching"
    )

    # Google Gemini (for Day 2+)
    GOOGLE_API_KEY: Optional[str] = Field(
        default=None,
        description="Google Gemini API key"
    )

    # PubMed Specific
    PUBMED_DEFAULT_MAX_RESULTS: int = Field(
        default=10,
        description="Default maximum results for PubMed searches"
    )
    PUBMED_DEFAULT_DATE_RANGE: int = Field(
        default=2,
        description="Default date range in years for PubMed searches"
    )

    # ClinicalTrials Specific
    CLINICAL_TRIALS_PAGE_SIZE: int = Field(
        default=100,
        description="Page size for ClinicalTrials.gov API pagination"
    )

    class Config:
        """Pydantic configuration."""
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True

    def __init__(self, **kwargs):
        """Initialize settings and ensure log directory exists."""
        super().__init__(**kwargs)
        # Ensure logs directory exists
        log_dir = os.path.dirname(self.LOG_FILE)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)


# Global settings instance
settings = Settings()
