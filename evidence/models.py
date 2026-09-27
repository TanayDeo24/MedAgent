"""Typed models for the Phase 5 Evidence boundary.

Grounded in docs/v2/PHASE5_EVIDENCE_CONTRACT.md (the frozen contract) and
docs/v2/PHASE5_INITIAL_EVIDENCE_AUDIT.md (what data actually exists per
source today). Mirrors orchestration/models.py's conventions where sensible
(str Enums, `model_config = ConfigDict(extra="forbid")`, field_validator for
hard invariants) but defines its own, distinct types - this is the evidence
namespace, not the tool-selection namespace.

Design note - `source_metadata` discrimination:
    The contract (Section 5) requires `source_metadata` to be typed per
    source, not a generic `dict[str, Any]`. Pydantic v2's discriminated
    union requires a shared Literal "tag" field across the union members, so
    each of the three metadata models below carries a `kind` Literal field
    (`"pubmed"` / `"clinical_trials"` / `"chembl"`) purely as that
    discriminator - it is not itself part of any source's raw data, it is
    Phase 5's own tagging scheme. `Evidence.source_metadata` is declared as
    `Annotated[Union[...], Field(discriminator="kind")]`, so pydantic
    validates/deserializes to the exact correct subtype (including on
    `model_validate_json` roundtrip) without any manual isinstance dispatch
    at the call site. A `model_validator` on `Evidence` additionally checks
    that `source_metadata.kind` agrees with `source_type`, so the two can
    never silently drift apart (e.g. a ChEMBL Evidence record accidentally
    carrying PubMed metadata).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Core enums
# ---------------------------------------------------------------------------


class SourceType(str, Enum):
    """The three real evidence sources this pipeline supports today.

    Distinct from orchestration/models.py's `ToolName` (tool *selection*
    namespace) even though the values happen to overlap for PubMed/ChEMBL -
    this enum exists to tag *evidence provenance*, not to pick which Python
    callable to invoke. Kept as a separate type per the task brief rather
    than reusing ToolName, since a future evidence source need not
    correspond 1:1 with a registered tool (e.g. PubMed RAG has no
    orchestration ToolName/operation of its own - it is not a Phase-3 tool
    call at all, see `Provenance.call_id`).
    """

    PUBMED = "pubmed"
    CLINICAL_TRIALS = "clinical_trials"
    CHEMBL = "chembl"


class EvidenceType(str, Enum):
    """Exactly the 7 types in docs/v2/PHASE5_EVIDENCE_CONTRACT.md Section 6.
    No more, no less - MECHANISM and OUTCOME are deliberately excluded per
    the contract (no source in this pipeline supports them today)."""

    TEXT_PASSAGE = "text_passage"
    COMPOUND_IDENTITY = "compound_identity"
    TARGET_RELATION = "target_relation"
    INDICATION = "indication"
    TRIAL_STATUS = "trial_status"
    TRIAL_PHASE = "trial_phase"
    TRIAL_FIELD = "trial_field"


class ContentFormat(str, Enum):
    """How `Evidence.content` should be interpreted by a downstream
    consumer - per contract Section 7, content is either verbatim source
    text, or a deterministic representation of one structured field."""

    VERBATIM_TEXT = "verbatim_text"
    STRUCTURED_FIELD = "structured_field"
    FIELD_VALUE = "field_value"


# ---------------------------------------------------------------------------
# Source-specific metadata (typed, not generic dicts) - contract Section 5
# ---------------------------------------------------------------------------


class PubMedEvidenceMetadata(BaseModel):
    """journal/year/pub_date/doi are frequently genuinely absent in the real
    source data (audit A.1/A.2 - not every article has a DOI, etc.) - this
    is documented as normal, not an error, so every field here is Optional
    with no fabricated placeholder default (never "N/A"/"Unknown journal"
    style values are copied in by the adapters in evidence/adapters.py;
    those literal placeholder strings are an UNRELIABLE risk per the audit
    and are normalized to None instead, see adapters.py)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["pubmed"] = "pubmed"
    journal: Optional[str] = None
    year: Optional[str] = None
    pub_date: Optional[str] = None
    doi: Optional[str] = None
    authors: List[str] = Field(default_factory=list)


class ClinicalTrialEvidenceMetadata(BaseModel):
    """Eligibility/outcomes are intentionally absent (contract Section 5 -
    `eligibilityModule`/`outcomesModule` are never read by
    tools/clinical_trials_tool.py's `_parse_study`, so Phase 5 does not
    invent them)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["clinical_trials"] = "clinical_trials"
    status: Optional[str] = None
    phase: Optional[str] = None
    conditions: List[str] = Field(default_factory=list)
    interventions: List[dict] = Field(default_factory=list)
    sponsor: Optional[str] = None
    enrollment: Optional[str] = None
    start_date: Optional[str] = None
    completion_date: Optional[str] = None


class ChemblEvidenceMetadata(BaseModel):
    """`match_type` is only populated for resolve_compound_name-derived
    records (the audit's identified best-in-repo provenance pattern -
    deterministic category, never a fabricated confidence float)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["chembl"] = "chembl"
    molecule_type: Optional[str] = None
    max_phase: Optional[str] = None
    mechanism_of_action: Optional[str] = None
    match_type: Optional[str] = None


SourceMetadata = Annotated[
    Union[PubMedEvidenceMetadata, ClinicalTrialEvidenceMetadata, ChemblEvidenceMetadata],
    Field(discriminator="kind"),
]

_METADATA_KIND_BY_SOURCE_TYPE = {
    SourceType.PUBMED: "pubmed",
    SourceType.CLINICAL_TRIALS: "clinical_trials",
    SourceType.CHEMBL: "chembl",
}


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class Provenance(BaseModel):
    """How this Evidence record was obtained - contract Section 4.

    `call_id` is `Optional[str]` and `None` is a VALID, EXPECTED value for
    the PubMed RAG path specifically (contract Section 4 / audit Section D):
    the local retriever is not a Phase-3 orchestration tool call at all
    (there is no `ToolCall`/`ToolBinding` for it in orchestration/registry.py
    - it runs entirely inside `retrieval/retriever.py`), so there is no real
    `call_id` to thread through. This is NOT a missing-data gap for the RAG
    path; per docs/v2/PHASE5_GATE_PLAN.md Section 2 ("Trace linkage"), it is
    explicitly "N/A by design" there. Inventing a synthetic call_id for the
    RAG path would itself be a hard-gate violation (a fabricated trace
    link) - so adapters must never do that; `call_id=None` is the correct,
    honest value. For the other three sources (PubMed live, ClinicalTrials,
    ChEMBL), `call_id` should be threaded through from
    `tool_call_history` when the caller has it available, but remains
    Optional here too since Phase 5's adapters are usable standalone
    (without an orchestration call_id in hand) per the task brief.
    """

    model_config = ConfigDict(extra="forbid")

    call_id: Optional[str] = None
    retrieval_method: str
    retrieval_rank: Optional[int] = None
    retrieval_score: Optional[float] = None
    corpus_index_version: Optional[str] = None
    chunk_index: Optional[int] = None
    num_chunks: Optional[int] = None
    field_path: Optional[str] = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Evidence ID / URL generation (contract Sections 3 and 8)
# ---------------------------------------------------------------------------


def make_evidence_id(
    source_type: SourceType,
    source_record_id: str,
    chunk_index: Optional[int] = None,
) -> str:
    """Deterministic, source-namespaced evidence id per contract Section 3.

        pubmed:<pmid>:chunk:<chunk_index>   - PubMed RAG (chunk-level; chunk_index given)
        pubmed:<pmid>                       - PubMed live (article-level; chunk_index omitted)
        nct:<nct_id>                        - ClinicalTrials
        chembl:<chembl_id>                  - ChEMBL

    Pure function: same input always produces the same id. Never invokes any
    randomness/uuid - stability across serialization and across repeated
    calls is the entire point (contract Section 3, gate plan's "deterministic
    Evidence-ID stability rate" metric).
    """

    if not source_record_id:
        raise ValueError("make_evidence_id: source_record_id must be non-empty")

    if source_type == SourceType.PUBMED:
        if chunk_index is not None:
            return f"pubmed:{source_record_id}:chunk:{chunk_index}"
        return f"pubmed:{source_record_id}"
    if source_type == SourceType.CLINICAL_TRIALS:
        return f"nct:{source_record_id}"
    if source_type == SourceType.CHEMBL:
        return f"chembl:{source_record_id}"

    raise ValueError(f"make_evidence_id: unsupported source_type {source_type!r}")


def make_source_url(source_type: SourceType, source_record_id: str) -> str:
    """Deterministic source URL per contract Section 8. Derived only from a
    verified `source_record_id` - never model-generated."""

    if not source_record_id:
        raise ValueError("make_source_url: source_record_id must be non-empty")

    if source_type == SourceType.PUBMED:
        return f"https://pubmed.ncbi.nlm.nih.gov/{source_record_id}/"
    if source_type == SourceType.CLINICAL_TRIALS:
        return f"https://clinicaltrials.gov/study/{source_record_id}"
    if source_type == SourceType.CHEMBL:
        return f"https://www.ebi.ac.uk/chembl/compound_report_card/{source_record_id}/"

    raise ValueError(f"make_source_url: unsupported source_type {source_type!r}")


_SOURCE_URL_PATTERNS = {
    SourceType.PUBMED: re.compile(r"^https://pubmed\.ncbi\.nlm\.nih\.gov/[^/]+/$"),
    SourceType.CLINICAL_TRIALS: re.compile(r"^https://clinicaltrials\.gov/study/[^/]+$"),
    SourceType.CHEMBL: re.compile(
        r"^https://www\.ebi\.ac\.uk/chembl/compound_report_card/[^/]+/$"
    ),
}


# ---------------------------------------------------------------------------
# Evidence - the canonical model
# ---------------------------------------------------------------------------


class Evidence(BaseModel):
    """One retrievable factual unit, normalized from a real source record.
    Per contract Section 2 - excludes citation numbering, hidden
    chain-of-thought, and any invented numeric confidence."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source_type: SourceType
    source_record_id: str
    source_url: str
    evidence_type: EvidenceType
    content: str
    content_format: ContentFormat
    title: Optional[str] = None
    source_metadata: SourceMetadata
    provenance: Provenance

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("evidence_id must be non-empty")
        return v

    @field_validator("source_record_id")
    @classmethod
    def _source_record_id_non_empty(cls, v: str) -> str:
        # Contract is explicit: source_record_id must be real, never
        # fabricated. This validator only enforces non-emptiness (the
        # cheapest structural guarantee available at the model layer) -
        # "real" (traceable to actual source data) is enforced by the
        # adapters in evidence/adapters.py never inventing one, not by a
        # regex here.
        if not v or not v.strip():
            raise ValueError("source_record_id must be non-empty")
        return v

    @field_validator("content")
    @classmethod
    def _content_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("content must be non-empty")
        return v

    @field_validator("source_url")
    @classmethod
    def _source_url_well_formed(cls, v: str, info) -> str:
        source_type = info.data.get("source_type")
        if source_type is None:
            # source_type failed validation earlier / wasn't provided yet;
            # nothing to check against.
            return v
        pattern = _SOURCE_URL_PATTERNS[source_type]
        if not pattern.match(v):
            raise ValueError(
                f"source_url {v!r} does not match the deterministic pattern "
                f"for source_type={source_type!r}"
            )
        return v

    @model_validator(mode="after")
    def _metadata_matches_source_type(self) -> "Evidence":
        expected_kind = _METADATA_KIND_BY_SOURCE_TYPE[self.source_type]
        if self.source_metadata.kind != expected_kind:
            raise ValueError(
                f"source_metadata.kind={self.source_metadata.kind!r} does not "
                f"match source_type={self.source_type!r} (expected {expected_kind!r})"
            )
        return self
