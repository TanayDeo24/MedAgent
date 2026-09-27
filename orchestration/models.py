"""Typed models for the Phase 3 orchestration boundary.

Per docs/v2/PHASE3_ORCHESTRATION_CONTRACT.md Section 5, every proposed tool
invocation must pass through, in order:

    ToolCall model validation -> registry lookup -> argument-schema
    validation -> execution

No LLM-produced string may directly choose and invoke a Python function.
This module defines the typed shapes for that pipeline; `orchestration/
registry.py` defines the lookup/validation boundary itself.

Design note - discriminated union vs. per-tool ToolCall subclasses:
    We use PER-OPERATION ToolCall subclasses (PubMedSearchCall,
    ClinicalTrialsSearchCall, ChEMBLSearchByTargetCall,
    ChEMBLSearchByIndicationCall, ChEMBLGetDrugInfoCall) combined into a
    single `ToolCall` discriminated union, discriminated on the `operation`
    field. This was chosen over a single generic `ToolCall` class holding a
    `Union[...]` `arguments` field because:
      1. Real operation names (search_pubmed, search_trials,
         search_by_target, search_by_indication, get_drug_info) are unique
         across all three registered tools today, so `operation` is a valid
         single-field pydantic discriminator with no ambiguity.
      2. Each subclass pins its own `tool_name`/`operation` as `Literal`
         defaults, so it is structurally impossible to construct e.g. a
         `ChEMBLSearchByTargetCall` with `tool_name=ToolName.PUBMED` - the
         (tool_name, operation, arguments-shape) triple is enforced by the
         type checker and by pydantic at construction time, not by a
         secondary cross-field validator that could be forgotten when a new
         operation is added later.
      3. It mirrors the registry's own (ToolName, operation) -> binding key
         structure one-to-one, keeping the "which arguments shape goes with
         which (tool, operation)" decision in exactly one place.
    The tradeoff is that adding a new operation means adding a new subclass
    and extending the union - considered acceptable since that already
    requires a new registry entry (registry.py) and a new argument schema.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Mirror the real tool's validation sets by importing them directly, so this
# module can never silently drift from tools/clinical_trials_tool.py's
# actual VALID_STATUSES/VALID_PHASES (the audit's Section C finding: the
# real tool computes these sets but never rejects an invalid value with
# them - it silently drops it. This layer rejects instead, at the schema
# boundary, before any HTTP call is possible).
from tools.clinical_trials_tool import ClinicalTrialsTool

VALID_TRIAL_STATUSES = frozenset(ClinicalTrialsTool.VALID_STATUSES)
VALID_TRIAL_PHASES = frozenset(ClinicalTrialsTool.VALID_PHASES)


# ---------------------------------------------------------------------------
# Core enums
# ---------------------------------------------------------------------------


class ToolName(str, Enum):
    """Exactly the three real tool integrations that exist in tools/ today
    (docs/v2/PHASE3_ORCHESTRATION_CONTRACT.md Section 4). Values match the
    string keys used in agent/nodes.py's `tool_instances` dict exactly, so
    this enum can later be dropped in as a typed replacement for
    `tools_to_call: List[str]` (agent/state.py) without a value-mapping
    layer."""

    PUBMED = "pubmed"
    CLINICAL_TRIALS = "clinical_trials"
    CHEMBL = "chembl"


class ToolErrorCategory(str, Enum):
    """Typed failure-attribution categories (contract Section 5, "failure
    attribution (typed ToolErrorCategory)"). Replaces today's untyped,
    dict-lookup-mapped free-text error strings (tools/base_tool.py
    `handle_errors`)."""

    VALIDATION_ERROR = "validation_error"
    UNREGISTERED_TOOL = "unregistered_tool"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    HTTP_ERROR = "http_error"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    EMPTY_RESULT = "empty_result"
    MALFORMED_RESPONSE = "malformed_response"
    PARTIAL_FAILURE = "partial_failure"
    INTERNAL_ERROR = "internal_error"


class ExecutionStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class PlanStatus(str, Enum):
    """`DRAFT` - constructed but not yet schema/registry validated.
    `VALIDATED` - every call passed ToolCall model validation + registry
    lookup + argument-schema validation (still pre-execution).
    `EXECUTED` - execution finished (results live in a separate
    List[ToolExecutionResult], correlated by call_id).
    `NO_EXECUTION_NEEDS_CLARIFICATION` - contract Section 1: when
    `ResearchQuery.ambiguity.is_ambiguous` is True, a plan with zero calls
    and this status is a valid, non-error outcome - not a best-guess
    fallback."""

    DRAFT = "draft"
    VALIDATED = "validated"
    EXECUTED = "executed"
    NO_EXECUTION_NEEDS_CLARIFICATION = "no_execution_needs_clarification"


# ---------------------------------------------------------------------------
# Per-tool typed argument schemas
#
# Each schema's fields are exactly what the real tool method accepts today
# (verified against tools/pubmed_tool.py, tools/clinical_trials_tool.py,
# tools/chembl_tool.py) - no invented/aspirational fields.
# ---------------------------------------------------------------------------


class PubMedSearchArgs(BaseModel):
    """Matches PubMedTool.search_pubmed(query, max_results, years_back,
    date_from, date_to) (tools/pubmed_tool.py:229-236)."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1)
    max_results: Optional[int] = Field(default=None, gt=0)
    years_back: Optional[int] = Field(default=None, gt=0)
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class ClinicalTrialsSearchArgs(BaseModel):
    """Matches ClinicalTrialsTool.search_trials(condition, intervention,
    status, phase, max_results, sponsor, country)
    (tools/clinical_trials_tool.py:194-203).

    Unlike the real tool (which silently drops an invalid status/phase -
    audit Section C), this schema REJECTS an invalid value at construction
    time.

    `status`/`phase` are typed as `Literal[...]` built FROM the tool's own
    class-level VALID_STATUSES/VALID_PHASES sets (derived via
    `Literal[tuple(sorted(...))]`, never hand-typed, so this can never
    silently drift from tools/clinical_trials_tool.py). This matters beyond
    runtime rejection: `.model_json_schema()` (used by
    orchestration/candidate_b_native_tools.py to build the tool declaration
    sent to the LLM) turns a `Literal` into a JSON Schema `enum` array,
    which a bare `Optional[str]` + custom validator never did. Without that
    `enum`, the model had no signal about which phase/status strings are
    valid and could (and did, in production: "Phase 4" instead of the
    canonical "PHASE4") guess a plausible-but-wrong value that the
    validator then correctly rejected with no fallback - see
    docs/v2/PHASE3_STATUS.md. The field_validators below are kept for
    defense-in-depth even though pydantic's own Literal coercion already
    rejects out-of-set values (verified empirically: Literal alone raises a
    pydantic ValidationError for an invalid value); they are harmless
    no-ops on the now-narrowed type and guard against this module's type
    annotation and the tool's VALID_* sets ever being changed
    independently."""

    model_config = ConfigDict(extra="forbid")

    condition: Optional[str] = None
    intervention: Optional[str] = None
    status: Optional[Literal[tuple(sorted(VALID_TRIAL_STATUSES))]] = Field(  # type: ignore[valid-type]
        default="RECRUITING"
    )
    phase: Optional[Literal[tuple(sorted(VALID_TRIAL_PHASES))]] = None  # type: ignore[valid-type]
    max_results: Optional[int] = Field(default=None, gt=0)
    sponsor: Optional[str] = None
    country: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_TRIAL_STATUSES:
            raise ValueError(
                f"invalid trial status {v!r}; must be one of {sorted(VALID_TRIAL_STATUSES)}"
            )
        return v

    @field_validator("phase")
    @classmethod
    def _validate_phase(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_TRIAL_PHASES:
            raise ValueError(
                f"invalid trial phase {v!r}; must be one of {sorted(VALID_TRIAL_PHASES)}"
            )
        return v


class ChEMBLSearchByTargetArgs(BaseModel):
    """Matches ChEMBLTool.search_by_target(target_name, max_results)
    (tools/chembl_tool.py:260-264)."""

    model_config = ConfigDict(extra="forbid")

    target_name: str = Field(..., min_length=1)
    max_results: int = Field(default=10, gt=0)


class ChEMBLSearchByIndicationArgs(BaseModel):
    """Matches ChEMBLTool.search_by_indication(disease, max_results)
    (tools/chembl_tool.py:335-339)."""

    model_config = ConfigDict(extra="forbid")

    disease: str = Field(..., min_length=1)
    max_results: int = Field(default=20, gt=0)


class ChEMBLGetDrugInfoArgs(BaseModel):
    """Matches ChEMBLTool.get_drug_info(chembl_id)
    (tools/chembl_tool.py:310-314)."""

    model_config = ConfigDict(extra="forbid")

    chembl_id: str = Field(..., min_length=1)


class ChEMBLResolveCompoundNameArgs(BaseModel):
    """Matches ChEMBLTool.resolve_compound_name(name, max_results)
    (tools/chembl_tool.py). Resolves a free-text drug/compound name (or a
    ChEMBL ID itself, for passthrough validation) to its real ChEMBL ID via
    exact preferred-name match, exact synonym match, or -- only as a last
    resort -- ChEMBL's own relevance-ranked search. Never fabricates an ID;
    ambiguous or absent matches are reported as such, not silently guessed."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    max_results: int = Field(default=5, gt=0)


# ---------------------------------------------------------------------------
# ToolCall - discriminated union of per-(tool, operation) call shapes
# ---------------------------------------------------------------------------


class ToolCallBase(BaseModel):
    """Fields shared by every ToolCall subclass. No hidden chain-of-thought
    field - `reason_code` is an optional short, sanitized machine code
    (e.g. "requested_evidence_types_match"), never free-text model
    reasoning."""

    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(..., min_length=1)
    dependency_ids: List[str] = Field(
        default_factory=list,
        description="call_ids of other ToolCalls in the same ExecutionPlan this call depends on, if any.",
    )
    parallelizable: bool = Field(
        default=True,
        description="Whether this call may run concurrently with sibling calls that share no dependency edge.",
    )
    reason_code: Optional[str] = Field(default=None, max_length=100)


class PubMedSearchCall(ToolCallBase):
    tool_name: Literal[ToolName.PUBMED] = ToolName.PUBMED
    operation: Literal["search_pubmed"] = "search_pubmed"
    arguments: PubMedSearchArgs


class ClinicalTrialsSearchCall(ToolCallBase):
    tool_name: Literal[ToolName.CLINICAL_TRIALS] = ToolName.CLINICAL_TRIALS
    operation: Literal["search_trials"] = "search_trials"
    arguments: ClinicalTrialsSearchArgs


class ChEMBLSearchByTargetCall(ToolCallBase):
    tool_name: Literal[ToolName.CHEMBL] = ToolName.CHEMBL
    operation: Literal["search_by_target"] = "search_by_target"
    arguments: ChEMBLSearchByTargetArgs


class ChEMBLSearchByIndicationCall(ToolCallBase):
    tool_name: Literal[ToolName.CHEMBL] = ToolName.CHEMBL
    operation: Literal["search_by_indication"] = "search_by_indication"
    arguments: ChEMBLSearchByIndicationArgs


class ChEMBLGetDrugInfoCall(ToolCallBase):
    tool_name: Literal[ToolName.CHEMBL] = ToolName.CHEMBL
    operation: Literal["get_drug_info"] = "get_drug_info"
    arguments: ChEMBLGetDrugInfoArgs


class ChEMBLResolveCompoundNameCall(ToolCallBase):
    tool_name: Literal[ToolName.CHEMBL] = ToolName.CHEMBL
    operation: Literal["resolve_compound_name"] = "resolve_compound_name"
    arguments: ChEMBLResolveCompoundNameArgs


ToolCall = Annotated[
    Union[
        PubMedSearchCall,
        ClinicalTrialsSearchCall,
        ChEMBLSearchByTargetCall,
        ChEMBLSearchByIndicationCall,
        ChEMBLGetDrugInfoCall,
        ChEMBLResolveCompoundNameCall,
    ],
    Field(discriminator="operation"),
]

# Every concrete ToolCall subclass, for callers (e.g. registry.py) that need
# to enumerate them without re-deriving the union.
TOOL_CALL_TYPES = (
    PubMedSearchCall,
    ClinicalTrialsSearchCall,
    ChEMBLSearchByTargetCall,
    ChEMBLSearchByIndicationCall,
    ChEMBLGetDrugInfoCall,
    ChEMBLResolveCompoundNameCall,
)


class ExecutionPlan(BaseModel):
    """A schema-validated, pre-execution plan (contract Section 2). `calls`
    is empty and `status` is NO_EXECUTION_NEEDS_CLARIFICATION for the valid
    "ambiguous query, do not guess" outcome (contract Section 1)."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(..., min_length=1)
    calls: List[ToolCall] = Field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT


class ToolExecutionResult(BaseModel):
    """One per executed ToolCall, correlated back to its plan entry via
    `call_id` (contract Section 2). This is a boundary placeholder for the
    tool's raw result (`raw_result_ref`) - Phase 5 evidence normalization is
    explicitly out of scope here (contract Section 3)."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    call_id: str = Field(..., min_length=1)
    tool_name: ToolName
    status: ExecutionStatus
    records_count: Optional[int] = Field(default=None, ge=0)
    latency_ms: float = Field(..., ge=0.0)
    retry_count: int = Field(default=0, ge=0)
    error_category: Optional[ToolErrorCategory] = None
    error_summary: Optional[str] = Field(
        default=None,
        description="Sanitized human-readable error summary. Must never contain secrets "
        "(API keys, auth headers) - callers populating this field are responsible for "
        "sanitizing upstream exception text before assigning it here.",
    )
    raw_result_ref: Optional[Any] = Field(
        default=None,
        description="Boundary placeholder carrying the underlying tool's raw ToolResult.data "
        "(or equivalent) through unchanged. Normalizing this into a common evidence shape is "
        "Phase 5's job, not this layer's.",
    )
    source_metadata: dict = Field(default_factory=dict)
