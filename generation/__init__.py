"""Phase 6 grounded-generation layer.

Standalone package (sibling to evidence/, orchestration/, nlu/, tools/,
agent/) that transforms Phase-5 Evidence[] into a canonical, structurally
validated, citation-compiled GroundedAnswer. Per
docs/v2/PHASE6_GROUNDED_GENERATION_CONTRACT.md, the only permitted input is
(query, Evidence[]) - never raw tool_results, retrieved_context, or a prior
citations list.
"""

from generation.models import (
    CitationEntry,
    ClaimType,
    GenerationMetadata,
    GroundedAnswer,
    GroundedClaim,
    SourceReference,
)
from generation.pipeline import generate_grounded_answer
from generation.validation import GenerationValidationError

__all__ = [
    "ClaimType",
    "GroundedClaim",
    "SourceReference",
    "CitationEntry",
    "GenerationMetadata",
    "GroundedAnswer",
    "generate_grounded_answer",
    "GenerationValidationError",
]
