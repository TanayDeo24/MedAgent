"""ResearchQuery / BiomedicalEntity schema - Phase 2 structured-understanding
output.

Frozen contract per `docs/v2/V2_PHASE_GATES.md` Phase 2 and
`docs/v2/PRODUCT_CONTRACT.md` Section 3. Versioned explicitly
(SCHEMA_VERSION) - a breaking field change is a new version, not a silent
edit; every benchmark file and frozen-config artifact records which schema
version it was built/measured against.

Design rules this module enforces structurally (not just by convention):
- canonical_id / canonical_name / normalization_system on a BiomedicalEntity
  MUST default to None and are NEVER auto-filled with a guess - the
  normalizer (nlu/normalization.py) is the only thing allowed to populate
  them, and only from a defensible, provenanced lookup. Abstention (all
  three None) is the correct behavior when no defensible mapping exists.
- `intent` is a list (not a single field) because PRODUCT_CONTRACT.md
  Section 3 explicitly allows multi-label "only where a query genuinely
  spans classes" (e.g. D and E) - single-label is just len(intent) == 1.
- `requested_evidence_types` is a PREDICTION of what sources a correct
  answer would need, produced by the NLU stage alone, before any tool is
  actually called. It is deliberately named differently from anything
  Phase 3 (tool dispatch) or Phase 4 (retrieval) will build, to keep this
  phase's claim scoped to "the NLU stage predicted X" rather than "the
  system routed to X" - EVALUATION_CONTRACT.md 1.5 is explicit that this is
  a *prediction*, evaluated as such (Source-Set P/R/F1), not an execution
  metric (that's EVALUATION_CONTRACT.md Section 2, Phase 3's territory).
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from nlu.taxonomy import VALID_INTENT_VALUES, IntentClass

# 2.1.0 (Phase 2 CLOSURE): IntentClass.H_INSUFFICIENT_EVIDENCE removed -
# H is a post-retrieval evidence-sufficiency outcome, not a query-time
# intent (see nlu/taxonomy.py's IntentClass docstring). Any consumer that
# serialized/compared against the old 9-value enum must be updated; this is
# a breaking change to ResearchQuery.intent's valid value set, hence a
# minor version bump (structurally compatible field, incompatible value
# domain) rather than a patch.
SCHEMA_VERSION = "2.1.0"


class EntityType(str, Enum):
    DISEASE = "disease"
    GENE = "gene"
    PROTEIN = "protein"
    TARGET = "target"
    COMPOUND = "compound"
    INTERVENTION = "intervention"


class NormalizationSystem(str, Enum):
    """What `canonical_id` means, per entity type. Documented explicitly so
    a consumer never has to guess which ontology an ID belongs to."""

    MESH = "MeSH"               # disease - NLM Medical Subject Headings descriptor ID (e.g. D002289)
    HGNC = "HGNC"                # gene/protein/target - HGNC gene symbol ID (e.g. HGNC:3236)
    CHEMBL = "ChEMBL"            # compound/intervention - ChEMBL molecule ID (e.g. CHEMBL553)
    NONE = "none"                # entity type has no normalization target defined in this phase


class BiomedicalEntity(BaseModel):
    """One extracted entity mention. Normalization fields default to None
    and stay None unless nlu/normalization.py found a defensible match -
    never fabricated to fill a plausible-looking value."""

    entity_type: EntityType
    surface_form: str = Field(..., min_length=1, description="Exact text span as it appeared in the query")
    semantic_roles: List[EntityType] = Field(
        default_factory=list,
        description=(
            "Phase 2 CLOSURE item 8: gene/protein/target ambiguity representation. "
            "`entity_type` remains the single primary/best-guess type (required, "
            "backward compatible - downstream code that only reads entity_type is "
            "unaffected). `semantic_roles` is an OPTIONAL list of every type this "
            "surface form legitimately has in context, when more than one applies "
            "(e.g. 'EGFR' can simultaneously be read as a gene symbol, its protein "
            "product, and a therapeutic target - all three are valid, not one "
            "'true' answer). Empty list (the default) means 'only entity_type "
            "applies, no legitimate ambiguity here' - it is NOT populated for "
            "every entity, only ones with genuine multi-role ambiguity, so a "
            "consumer distinguishes 'this type is certain' from 'this type is one "
            "of several valid readings.' Evaluation note: an extraction whose "
            "entity_type differs from a benchmark's gold type but appears in that "
            "gold entity's own semantic_roles (once the benchmark carries gold "
            "semantic_roles annotations - not yet true of nlu_benchmark_v1.1.0, "
            "a known limitation, see docs/v2/PHASE2_CLOSURE_REPORT.md) should be "
            "scored as a VALID ALTERNATE ROLE, not a wrong-type error."
        ),
    )
    canonical_name: Optional[str] = Field(default=None)
    # normalization_system MUST be declared (and therefore validated) before
    # canonical_id - pydantic v2's field_validator only exposes
    # already-validated fields via info.data, in declaration order, so
    # _id_requires_system below depends on this ordering to see it.
    normalization_system: Optional[NormalizationSystem] = Field(default=None)
    canonical_id: Optional[str] = Field(default=None)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("canonical_id")
    @classmethod
    def _id_requires_system(cls, v, info):
        # Structural guard against the exact failure mode task item 8 warns
        # about: an ID present without a named system is unattributable and
        # untrustworthy by construction, so it's rejected at validation
        # time rather than allowed to reach a benchmark or a caller.
        if v is not None and info.data.get("normalization_system") in (None, NormalizationSystem.NONE):
            raise ValueError(
                "canonical_id set without a normalization_system - every "
                "canonical_id must name the ontology it comes from"
            )
        return v


class ConstraintSet(BaseModel):
    """Structured constraint fields (EVALUATION_CONTRACT.md 1.4). Each field
    is a list because a query can name more than one value for the same
    field (e.g. trial_phases=["PHASE2","PHASE3"]). Empty list = "not
    mentioned in the query", never an implicit wildcard filled in later."""

    trial_phases: List[str] = Field(default_factory=list, description="e.g. PHASE1, PHASE2, PHASE3, PHASE4")
    trial_statuses: List[str] = Field(default_factory=list, description="e.g. RECRUITING, COMPLETED, ACTIVE_NOT_RECRUITING, TERMINATED")
    population: List[str] = Field(default_factory=list, description="e.g. adults, pediatric, elderly")
    age: List[str] = Field(default_factory=list, description="e.g. '18+', 'pediatric'")
    geography: List[str] = Field(default_factory=list)
    temporal: List[str] = Field(default_factory=list, description="e.g. 'published after 2020', 'last 5 years'")
    study_type: List[str] = Field(default_factory=list, description="e.g. randomized controlled trial, observational")
    outcomes: List[str] = Field(default_factory=list, description="e.g. overall survival, progression-free survival")

    def as_pairs(self) -> List[tuple]:
        """Flatten to (field, value) pairs - the unit of analysis
        EVALUATION_CONTRACT.md 1.4 defines for Constraint Field P/R/F1."""
        pairs = []
        for field_name in self.model_fields:
            for value in getattr(self, field_name):
                pairs.append((field_name, value))
        return pairs


class EvidenceSourceType(str, Enum):
    PUBMED = "pubmed"
    CLINICALTRIALS = "clinicaltrials"
    CHEMBL = "chembl"


class AmbiguityState(BaseModel):
    """Explicit ambiguity/clarification state (task item 12). A query is
    never silently guessed through - if genuinely ambiguous, this is
    populated and `is_ambiguous` is True; downstream behavior (ask for
    clarification vs. answer under a stated assumption) is a product
    decision (PRODUCT_CONTRACT.md Section 9), not this schema's concern."""

    is_ambiguous: bool = False
    ambiguity_reason: Optional[str] = None
    candidate_interpretations: List[str] = Field(default_factory=list)


class ResearchQuery(BaseModel):
    """The Phase 2 structured-understanding output. One instance per query."""

    schema_version: str = Field(default=SCHEMA_VERSION)

    original_query: str
    normalized_query: str = Field(description="Whitespace/casing-normalized query text; no semantic rewriting")

    intent: List[IntentClass] = Field(
        default_factory=list,
        description="Multi-label only where genuinely justified (e.g. D+E); usually length 1",
    )
    intent_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    entities: List[BiomedicalEntity] = Field(default_factory=list)

    constraints: ConstraintSet = Field(default_factory=ConstraintSet)

    requested_evidence_types: List[EvidenceSourceType] = Field(
        default_factory=list,
        description=(
            "PREDICTION of which sources a correct answer needs, produced by "
            "the NLU stage alone. NOT the same as actual tool routing "
            "(Phase 3) or retrieval execution (Phase 4)."
        ),
    )

    ambiguity: AmbiguityState = Field(default_factory=AmbiguityState)

    extraction_confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Overall confidence in this ResearchQuery's extraction quality")

    @field_validator("intent")
    @classmethod
    def _validate_intent_values(cls, v):
        for item in v:
            if item.value not in VALID_INTENT_VALUES:
                raise ValueError(f"Unknown intent class: {item}")
        return v


class NLUExtractionResult(BaseModel):
    """Wraps a ResearchQuery with extraction-process metadata (parse
    success, schema validity, raw-output diagnostics) - kept separate from
    ResearchQuery itself so the product schema stays clean, and so
    extractor.py can report an honest failure (schema_valid=False,
    research_query=None) instead of ever returning a corrupted fallback
    dict silently disguised as a successful extraction."""

    schema_valid: bool
    research_query: Optional[ResearchQuery] = None
    raw_llm_output: Optional[str] = None
    parse_error: Optional[str] = None
    architecture: str = Field(description="e.g. 'candidate_a_baseline', 'candidate_b_structured'")
    latency_ms: float = 0.0
    llm_calls: int = 0
    token_usage: Optional[dict] = Field(
        default=None,
        description="Raw usage_metadata dict from the underlying LLM response (input_tokens/output_tokens/total_tokens), when available - lets callers (e.g. agent/nodes.py) accumulate token counts the same way every other node does.",
    )
