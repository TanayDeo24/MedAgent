"""Phase 8 research-loop schemas: EvidenceGap, ResearchAction, StopReason.

See docs/v2/PHASE8_RESEARCH_LOOP_CONTRACT.md for the authoritative contract
this module implements. Every model here is a plain, deterministic,
LLM-free data structure - no field is ever populated by treating raw model
reasoning as structured fact (contract Section "Evidence remains
authoritative")."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class GapType(str, Enum):
    """Exactly the gap categories this module can detect deterministically
    from the current AgentState. A new gap type must have a real detector
    in research/gap_analysis.py before being added here - never speculative."""

    NO_EVIDENCE = "no_evidence"
    MISSING_SOURCE_CATEGORY = "missing_source_category"
    WEAKLY_SUPPORTED_FACT = "weakly_supported_fact"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


class StopReason(str, Enum):
    """Explicit, non-vague terminal states (contract requirement - never a
    bare 'loop ended')."""

    SUFFICIENT_EVIDENCE = "sufficient_evidence"
    NO_PRODUCTIVE_ACTION = "no_productive_action"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TOOL_FAILURE_LIMIT = "tool_failure_limit"
    UNRESOLVABLE_GAP = "unresolvable_gap"
    SAFE_ABSTENTION = "safe_abstention"


class ResearchActionStatus(str, Enum):
    PLANNED = "planned"
    EXECUTED_PRODUCTIVE = "executed_productive"
    EXECUTED_UNPRODUCTIVE = "executed_unproductive"
    EXECUTED_DUPLICATE_ONLY = "executed_duplicate_only"
    FAILED = "failed"


class EvidenceGap(BaseModel):
    """A structured representation of one specific thing missing/weak in
    the CURRENT Evidence set, per contract "Evidence gaps must drive
    follow-up research". Never free-form."""

    model_config = ConfigDict(extra="forbid")

    gap_id: str
    gap_type: GapType
    description: str
    target_source_category: Optional[str] = None  # "pubmed"/"clinical_trials"/"chembl"
    related_claim_id: Optional[str] = None
    severity: float = Field(ge=0.0, le=1.0, default=0.5)


class ResearchAction(BaseModel):
    """A structured research action, always traceable back to the gap that
    produced it (contract: "A follow-up action must correspond to a
    recorded evidence gap"). Executed only through the frozen Phase-3
    schema-constrained tool-orchestration path
    (`orchestration/candidate_b_native_tools.py` +
    `orchestration.registry.DEFAULT_REGISTRY`) - this model never carries
    an executable payload of its own, only a targeted follow-up query
    string that is fed into that same frozen, validated dispatcher."""

    model_config = ConfigDict(extra="forbid")

    action_id: str
    gap_id: str
    iteration: int
    target_source_category: Optional[str] = None
    followup_query: str
    reason: str
    status: ResearchActionStatus = ResearchActionStatus.PLANNED
    new_evidence_ids: List[str] = Field(default_factory=list)
    duplicate_evidence_ids: List[str] = Field(default_factory=list)
    tool_names_used: List[str] = Field(default_factory=list)
    error: Optional[str] = None
