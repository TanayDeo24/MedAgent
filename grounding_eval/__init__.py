"""Phase 7 grounding-evaluation harness.

Standalone package (sibling to evidence/, generation/, orchestration/,
nlu/, tools/, agent/) that judges whether Phase-6 GroundedClaims are
semantically supported by their cited Phase-5 Evidence. Offline/diagnostic
only - never inserted into the production LangGraph (see
docs/v2/PHASE7_GROUNDING_EVALUATION_CONTRACT.md Section 11).
"""

from grounding_eval.models import (
    AnswerGroundingEvaluation,
    CitationGroundingJudgment,
    CitationRelation,
    ClaimGroundingJudgment,
    SupportLabel,
)
from grounding_eval.pipeline import evaluate_answer, evaluate_claim

__all__ = [
    "SupportLabel",
    "CitationRelation",
    "CitationGroundingJudgment",
    "ClaimGroundingJudgment",
    "AnswerGroundingEvaluation",
    "evaluate_claim",
    "evaluate_answer",
]
