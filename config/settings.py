"""Centralized configuration settings for MedAgent.

This module defines all configuration parameters for the MedAgent system,
including API endpoints, rate limits, retry policies, and logging settings.
"""

import os
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field, SecretStr


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

    # NVIDIA NIM (for Day 2+)
    NVIDIA_API_KEY: Optional[SecretStr] = Field(
        default=None,
        description="NVIDIA NIM API key"
    )

    # Cloudflare Workers AI (Phase 2 latency experiment)
    # CLOUDFLARE_API_TOKEN is a genuine auth secret -> SecretStr, never
    # printed/logged/repr'd. CLOUDFLARE_ACCOUNT_ID is an account identifier
    # (not a bearer credential; it appears in the Workers AI URL path, not
    # an Authorization header) -> plain str, safe to include in logs/URLs.
    CLOUDFLARE_API_TOKEN: Optional[SecretStr] = Field(
        default=None,
        description="Cloudflare API token (Workers AI). Unwrap only at the "
                     "HTTP Authorization header boundary via get_secret_value()."
    )
    CLOUDFLARE_ACCOUNT_ID: Optional[str] = Field(
        default=None,
        description="Cloudflare account ID (identifier, not a secret)."
    )

    # Cerebras (Phase 2 latency experiment candidate)
    # Genuine auth secret -> SecretStr, never printed/logged/repr'd. Unwrap
    # only at the HTTP Authorization header boundary via get_secret_value().
    CEREBRAS_API_KEY: Optional[SecretStr] = Field(
        default=None,
        description="Cerebras API key. Unwrap only at the HTTP Authorization "
                     "header boundary via get_secret_value()."
    )

    # PubMed Specific
    PUBMED_DEFAULT_MAX_RESULTS: int = Field(
        default=10,
        description="Default maximum results for PubMed searches"
    )
    PUBMED_DEFAULT_DATE_RANGE: int = Field(
        default=2,
        description="Recency window (years) available for an EXPLICIT "
                     "recency-constrained PubMed search. As of the Phase 4 "
                     "fix (docs/v2/PHASE4_PUBMED_CANDIDATE_COMPARISON.md), "
                     "tools/pubmed_tool.py's search_pubmed() no longer "
                     "applies this implicitly when a caller passes neither "
                     "years_back nor date_from - doing so silently excluded "
                     "most gold-relevant (often >2-year-old) articles and "
                     "measured Recall@10=0.045 vs RAG's 0.773 on the same "
                     "22-case benchmark. No date filter is applied by "
                     "default now; this constant is kept only for callers "
                     "that explicitly opt into a recency-limited search."
    )

    # ClinicalTrials Specific
    CLINICAL_TRIALS_PAGE_SIZE: int = Field(
        default=100,
        description="Page size for ClinicalTrials.gov API pagination"
    )

    class Config:
        """Pydantic configuration.

        extra = "ignore": unrecognized .env keys (e.g. a provider var added
        to .env before its Settings field exists yet, or an unrelated var a
        developer keeps in their local .env) are silently ignored rather
        than raising ValidationError. This is a deliberate security fix:
        pydantic-settings' default ("forbid") raises a ValidationError whose
        traceback can include the *value* of the offending env var, which
        previously caused a Cloudflare token/account ID to leak into tool
        output. "ignore" means unknown vars never reach a validation error
        path in the first place. This does not weaken validation of any
        KNOWN field (type coercion/requiredness for declared fields is
        unaffected) and does not suppress errors for fields that ARE
        declared but fail to parse.
        """
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"

    def __init__(self, **kwargs):
        """Initialize settings and ensure log directory exists."""
        super().__init__(**kwargs)
        # Ensure logs directory exists
        log_dir = os.path.dirname(self.LOG_FILE)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)


# Global settings instance
settings = Settings()
