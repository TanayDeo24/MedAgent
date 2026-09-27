"""Typed models for the Phase 6 grounded-generation boundary.

Grounded in docs/v2/PHASE6_GROUNDED_GENERATION_CONTRACT.md. Mirrors
evidence/models.py's conventions (str Enums, `extra="forbid"`,
field_validator for hard invariants) but defines its own, distinct
namespace - this is the generation boundary, not the evidence boundary.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from evidence.models import SourceType


class ClaimType(str, Enum):
    """Exactly the 4 types in the Phase-6 contract Section 3. FACTUAL
    requires >=1 evidence_ids; the other three are the only types allowed
    zero evidence_ids."""

    FACTUAL = "factual"
    INFERENCE = "inference"
    ABSTENTION = "abstention"
    TRANSITION = "transition"


class GroundedClaim(BaseModel):
    """One atomic factual/rhetorical unit of a generated answer. Never
    carries a fabricated numeric confidence (contract Section 2) - only
    `qualifier`, a free-text but non-numeric qualification string."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    text: str
    evidence_ids: List[str] = Field(default_factory=list)
    claim_type: ClaimType
    qualifier: Optional[str] = None

    @field_validator("text")
    @classmethod
    def _text_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("GroundedClaim.text must be non-empty")
        return v

    @model_validator(mode="after")
    def _factual_requires_support(self) -> "GroundedClaim":
        if self.claim_type == ClaimType.FACTUAL and not self.evidence_ids:
            raise ValueError(
                "GroundedClaim.claim_type=FACTUAL requires evidence_ids "
                "with at least one entry (contract Section 3) - a factual "
                "claim with no support binding is a hard gate violation, "
                "never silently permitted here."
            )
        return self


class SourceReference(BaseModel):
    """One human-facing appendix entry, grouped by source_record_id
    (contract Section 9) - NOT one entry per Evidence object. Built only
    from real Evidence.source_metadata/source_url, never LLM-authored."""

    model_config = ConfigDict(extra="forbid")

    number: int
    source_type: SourceType
    source_record_id: str
    source_url: str
    grouped_evidence_ids: List[str]
    display_fields: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("grouped_evidence_ids")
    @classmethod
    def _grouped_non_empty(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("SourceReference.grouped_evidence_ids must be non-empty")
        return v


class CitationEntry(BaseModel):
    """One compiled citation number - contract Section 10. `number` is
    NEVER assigned by the model; only by generation.citation_compiler."""

    model_config = ConfigDict(extra="forbid")

    number: int
    evidence_ids: List[str]
    source_reference_index: int


class GenerationMetadata(BaseModel):
    """Operational facts only - never provider reasoning content or a
    hidden chain-of-thought transcript (contract Section 4)."""

    model_config = ConfigDict(extra="forbid")

    architecture: str
    provider: str
    model: str
    llm_calls: int
    latency_ms: float
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


class GroundedAnswer(BaseModel):
    """The canonical Phase-6 output - contract Section 2. `claims` is the
    sole source of truth; `rendered_text` is DERIVED from `claims`, never
    the reverse (never hand-edited independently of the claims list)."""

    model_config = ConfigDict(extra="forbid")

    answer_id: str
    query: str
    claims: List[GroundedClaim]
    rendered_text: str
    citations: List[CitationEntry]
    references: List[SourceReference]
    used_evidence_ids: List[str]
    unused_evidence_ids: List[str]
    abstained: bool
    conflict_detected: bool
    generation_metadata: GenerationMetadata
