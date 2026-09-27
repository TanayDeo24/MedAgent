"""Typed models for the Phase 7 grounding-evaluation harness.

Grounded in docs/v2/PHASE7_GROUNDING_EVALUATION_CONTRACT.md. Mirrors
evidence/models.py and generation/models.py's conventions - own, distinct
namespace (the evaluation namespace, not the evidence or generation
namespace).
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SupportLabel(str, Enum):
    """Contract Section 3 - exactly these 4 labels, no more."""

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"


class CitationRelation(str, Enum):
    """Contract Section 4."""

    SUPPORTS = "supports"
    PARTIAL_SUPPORT = "partial_support"
    IRRELEVANT = "irrelevant"
    CONTRADICTS = "contradicts"


class CitationGroundingJudgment(BaseModel):
    """One claim x one cited Evidence relation - contract Section 4."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    relation: CitationRelation
    reason_code: str

    @field_validator("reason_code")
    @classmethod
    def _reason_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("reason_code must be non-empty")
        return v


class ClaimGroundingJudgment(BaseModel):
    """One claim's overall semantic support judgment - contract Section 1.
    No chain-of-thought field exists here (contract Section 9) - only a
    short, Evidence-grounded reason string."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    support_label: SupportLabel
    citation_judgments: List[CitationGroundingJudgment]
    supporting_evidence_ids: List[str] = Field(default_factory=list)
    unsupported_fragments: List[str] = Field(default_factory=list)
    numeric_mismatch: bool = False
    reason_code: str
    evaluator_metadata: dict = Field(default_factory=dict)

    @field_validator("reason_code")
    @classmethod
    def _reason_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("reason_code must be non-empty")
        return v


class AnswerGroundingEvaluation(BaseModel):
    """Aggregate answer-level result - contract Section 7."""

    model_config = ConfigDict(extra="forbid")

    answer_id: str
    claim_judgments: List[ClaimGroundingJudgment]
    factual_claim_count: int
    supported_count: int
    partially_supported_count: int
    unsupported_count: int
    contradicted_count: int
    fully_grounded: bool
    citation_precision: Optional[float] = None
    claim_citation_coverage: Optional[float] = None
