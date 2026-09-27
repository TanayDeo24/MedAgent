"""Source-specific typed query compilers for Candidate C ("ResearchQuery-
driven hybrid" - `docs/v2/PHASE3_GATE_PLAN.md` Section 1).

Each compiler is a PURE function: `ResearchQuery -> Optional[ToolCall]`.
Input is the frozen Phase-2 `ResearchQuery` (`nlu/schemas.py`) - this module
never re-runs the NLU extractor and never makes an LLM call. Output is one
of the typed `ToolCall` subclasses in `orchestration/models.py`, already
schema-validated by pydantic construction, ready to be handed to
`orchestration/registry.py::ToolRegistry.validate_call` (registry lookup +
defensive re-validation) and then to execution.

Design rule - ABSTAIN, NEVER GUESS: every compiler returns `None` instead
of constructing a `ToolCall` whenever `query` does not carry enough
structured signal (entities/constraints) to fill that tool's arguments
without inventing a value. A `None` return is a first-class, expected
outcome - it means "this source's compiler had nothing safe to say for
this query", not an error. Callers (the Candidate C measurement harness)
must treat it as a per-source abstention, not silently drop it and not
treat it as a bug.

Determinism note (PubMed): per `PHASE3_GATE_PLAN.md` Section 1, PubMed's
free-text `query` string is "the one field allowed to need semantic
free-text construction; constrained-model assistance only for genuinely
free-text fields". This module deliberately does NOT use an LLM for it -
per the governing directive's Step 19 instruction to prefer deterministic
logic where sufficient, `compile_pubmed_call` below builds the query string
by simple, deterministic joining of entity names and select constraint
terms. This keeps the Candidate C measurement fully reproducible and
attributable to code, not to a non-deterministic model call (this module
reports `model_calls_per_case == 0` as a direct consequence). A real
production compiler MAY choose constrained-LLM assistance for this one
field later; that tradeoff is out of scope for this measurement.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from nlu.schemas import EntityType, NormalizationSystem, ResearchQuery
from orchestration.models import (
    VALID_TRIAL_PHASES,
    VALID_TRIAL_STATUSES,
    ChEMBLGetDrugInfoArgs,
    ChEMBLGetDrugInfoCall,
    ChEMBLSearchByIndicationArgs,
    ChEMBLSearchByIndicationCall,
    ChEMBLSearchByTargetArgs,
    ChEMBLSearchByTargetCall,
    ClinicalTrialsSearchArgs,
    ClinicalTrialsSearchCall,
    PubMedSearchArgs,
    PubMedSearchCall,
    ToolCall,
    ToolName,
)

# Entity types treated as naming a molecular/protein target for ChEMBL's
# search_by_target operation. GENE and PROTEIN are included alongside
# TARGET because, per nlu/schemas.py's own semantic_roles docstring, the
# same surface form (e.g. "EGFR") can legitimately be read as any of the
# three - all three are valid signals for "this is a target-shaped query",
# not just the literal TARGET enum member.
_TARGET_LIKE_ENTITY_TYPES = (EntityType.TARGET, EntityType.PROTEIN, EntityType.GENE)

# Entity types treated as naming a drug/compound for ClinicalTrials'
# `intervention` field.
_INTERVENTION_LIKE_ENTITY_TYPES = (EntityType.COMPOUND, EntityType.INTERVENTION)


def _entity_name(entity) -> str:
    """Prefer the normalizer's canonical_name when present (it is only ever
    populated by a defensible, provenanced lookup - nlu/schemas.py), fall
    back to the raw surface_form otherwise. Never fabricates a name."""

    name = entity.canonical_name or entity.surface_form
    return name.strip()


# ---------------------------------------------------------------------------
# PubMed
# ---------------------------------------------------------------------------


def compile_pubmed_call(query: ResearchQuery, call_id: str) -> Optional[PubMedSearchCall]:
    """Deterministic PubMed query-string construction.

    Joins every entity's canonical_name/surface_form plus a handful of
    concept-bearing constraint fields (outcomes, study_type, temporal) that
    are themselves already free text in ConstraintSet - never re-parses
    original_query. Abstains (returns None) when there is nothing to join,
    since a query built from zero terms would be meaningless (PubMed would
    either error or return the site's generic/most-recent results, not a
    signal-driven search).
    """

    terms: List[str] = []
    seen = set()

    def _add(term: str) -> None:
        term = term.strip()
        key = term.lower()
        if term and key not in seen:
            terms.append(term)
            seen.add(key)

    for entity in query.entities:
        _add(_entity_name(entity))

    # Constraint fields that are themselves free-text concept strings (not
    # coded values like trial_phases/trial_statuses) - safe to fold into a
    # literature query without guessing a mapping.
    for field_name in ("outcomes", "study_type", "temporal"):
        for value in getattr(query.constraints, field_name):
            _add(value)

    if not terms:
        return None

    query_string = " AND ".join(terms)
    args = PubMedSearchArgs(query=query_string)
    return PubMedSearchCall(
        call_id=call_id,
        arguments=args,
        reason_code="entities_and_free_text_constraints_joined",
    )


# ---------------------------------------------------------------------------
# ClinicalTrials
# ---------------------------------------------------------------------------


def compile_clinical_trials_call(
    query: ResearchQuery, call_id: str
) -> Optional[ClinicalTrialsSearchCall]:
    """Deterministic field mapping from ResearchQuery.entities/constraints
    onto ClinicalTrialsSearchArgs.

    - condition <- first DISEASE-typed entity's name.
    - intervention <- first COMPOUND/INTERVENTION-typed entity's name.
    - status <- first `constraints.trial_statuses` value that is a member
      of VALID_TRIAL_STATUSES; an unmappable raw value (e.g. the
      benchmark's deliberately-injected 'FULLY_ENROLLED', FL-001) is
      OMITTED rather than passed through, letting ClinicalTrialsSearchArgs'
      own schema default ("RECRUITING") apply. This is a deliberate
      abstention on the single field, not a whole-call abstention -
      passing the raw value through would raise a pydantic ValidationError
      at construction, which would either crash this compiler or (worse)
      have to be silently swallowed; omitting is the documented gold
      behavior for exactly this failure-injection case.
    - phase <- same omit-if-unmappable rule against VALID_TRIAL_PHASES
      (FL-002's 'PHASE2.5' has no valid member and is omitted).
    - country <- first `constraints.geography` value, if any.

    Abstains (returns None) only when neither a condition nor an
    intervention could be determined - a bare status/phase/geography
    filter with no subject is not a usable clinical-trials query.
    """

    condition: Optional[str] = None
    intervention: Optional[str] = None
    for entity in query.entities:
        if condition is None and entity.entity_type == EntityType.DISEASE:
            condition = _entity_name(entity)
        elif intervention is None and entity.entity_type in _INTERVENTION_LIKE_ENTITY_TYPES:
            intervention = _entity_name(entity)

    if condition is None and intervention is None:
        return None

    kwargs: Dict[str, object] = {}
    if condition:
        kwargs["condition"] = condition
    if intervention:
        kwargs["intervention"] = intervention

    for raw_status in query.constraints.trial_statuses:
        if raw_status in VALID_TRIAL_STATUSES:
            kwargs["status"] = raw_status
            break
    # else: leave `status` unset entirely so ClinicalTrialsSearchArgs'
    # own field default ("RECRUITING") applies - never pass the raw,
    # unmappable value through.

    for raw_phase in query.constraints.trial_phases:
        if raw_phase in VALID_TRIAL_PHASES:
            kwargs["phase"] = raw_phase
            break

    if query.constraints.geography:
        kwargs["country"] = query.constraints.geography[0]

    args = ClinicalTrialsSearchArgs(**kwargs)
    return ClinicalTrialsSearchCall(
        call_id=call_id,
        arguments=args,
        reason_code="deterministic_entity_and_constraint_field_mapping",
    )


# ---------------------------------------------------------------------------
# ChEMBL
# ---------------------------------------------------------------------------


def compile_chembl_call(query: ResearchQuery, call_id: str) -> Optional[ToolCall]:
    """Deterministic operation selection among ChEMBL's three registered
    operations. Priority order (highest first), each a distinct, unambiguous
    structured signal - never a guess between two equally-plausible ops:

    1. get_drug_info: an entity carries a ChEMBL-normalized canonical_id
       (normalization_system == NormalizationSystem.CHEMBL and
       canonical_id is set). This field is ONLY ever populated by
       nlu/normalization.py's defensible, provenanced lookup (nlu/schemas.py
       docstring) - never fabricated - so treating its presence as a
       certain signal for "the user named/resolved to one specific
       compound" is itself deterministic, not a guess.
    2. search_by_target: an entity's type is TARGET/PROTEIN/GENE (a
       molecular target, not a disease or a bare compound name).
    3. search_by_indication: an entity's type is DISEASE.

    A compound-typed entity with no canonical_id and no accompanying
    target/disease entity (e.g. "look up imatinib in ChEMBL") is NOT
    resolvable to search_by_target(target_name=<drug name>) or
    search_by_indication(disease=<drug name>) without guessing - neither
    operation means "look up this drug by name" (tools/chembl_tool.py has
    no such operation at all). Per this module's abstain-don't-guess rule,
    that case returns None rather than picking one arbitrarily.
    """

    for entity in query.entities:
        if (
            entity.normalization_system == NormalizationSystem.CHEMBL
            and entity.canonical_id
        ):
            args = ChEMBLGetDrugInfoArgs(chembl_id=entity.canonical_id)
            return ChEMBLGetDrugInfoCall(
                call_id=call_id,
                arguments=args,
                reason_code="canonical_chembl_id_present",
            )

    for entity in query.entities:
        if entity.entity_type in _TARGET_LIKE_ENTITY_TYPES:
            args = ChEMBLSearchByTargetArgs(target_name=_entity_name(entity))
            return ChEMBLSearchByTargetCall(
                call_id=call_id,
                arguments=args,
                reason_code="target_like_entity_present",
            )

    for entity in query.entities:
        if entity.entity_type == EntityType.DISEASE:
            args = ChEMBLSearchByIndicationArgs(disease=_entity_name(entity))
            return ChEMBLSearchByIndicationCall(
                call_id=call_id,
                arguments=args,
                reason_code="disease_entity_present",
            )

    return None


# ---------------------------------------------------------------------------
# Dispatch table - the harness selects by ToolName, matching
# orchestration/source_selection.py::select_sources' own output type.
# ---------------------------------------------------------------------------

QueryCompiler = Callable[[ResearchQuery, str], Optional[ToolCall]]

COMPILERS: Dict[ToolName, QueryCompiler] = {
    ToolName.PUBMED: compile_pubmed_call,
    ToolName.CLINICAL_TRIALS: compile_clinical_trials_call,
    ToolName.CHEMBL: compile_chembl_call,
}


def compile_call(tool_name: ToolName, query: ResearchQuery, call_id: str) -> Optional[ToolCall]:
    """Convenience dispatcher: look up and invoke the right compiler for
    `tool_name`. Raises KeyError for a ToolName with no registered compiler
    (structurally shouldn't happen - COMPILERS covers all three ToolName
    members - fails loudly rather than silently skipping if it ever does)."""

    return COMPILERS[tool_name](query, call_id)
