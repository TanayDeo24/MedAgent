"""NLU extraction architectures (Candidate A baseline, Candidate B
schema-constrained structured extraction) and the frozen `understand_query`
entry point.

See `artifacts/v2/nlu_experiment_plan.json` for why only A and B were built
(no Candidate C biomedical-NER model - not justified, see that file) and
`artifacts/v2/nlu_frozen_config.json` for which one was selected.
"""

import json
import re
import time
from typing import Any, Dict, List, Optional

import requests
from pydantic import ValidationError

from agent.prompts import QUERY_ANALYSIS_PROMPT
from config.llm_config import get_llm
from config.settings import settings
from nlu.normalization import canonicalize_trial_phase, canonicalize_trial_status, normalize_entity
from nlu.schemas import (
    AmbiguityState,
    BiomedicalEntity,
    ConstraintSet,
    EntityType,
    EvidenceSourceType,
    IntentClass,
    NLUExtractionResult,
    NormalizationSystem,
    ResearchQuery,
    SCHEMA_VERSION,
)
from nlu.taxonomy import B_VS_G_RULE, DI_VS_E_RULE, VALID_INTENT_VALUES
from utils.logger import get_logger
from utils.rate_limiter import wait_for_rate_limit

logger = get_logger(__name__)

PROMPT_VERSION_A = "candidate_a_baseline_v1_verbatim_QUERY_ANALYSIS_PROMPT"
PROMPT_VERSION_B = "candidate_b_structured_v1"


def _strip_code_fence(text: str) -> str:
    content = text.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
        content = content.replace("```json", "").replace("```", "").strip()
    return content


# ---------------------------------------------------------------------------
# Candidate A: the CURRENT, unmodified query_analysis_node/QUERY_ANALYSIS_PROMPT
# mapped onto the ResearchQuery/NLUExtractionResult shape for measurement
# purposes only. This wrapper does not change the baseline's behavior in any
# way - it calls the exact same prompt with the exact same LLM parameters
# query_analysis_node itself uses, and maps its narrow output fields onto
# whatever ResearchQuery fields are legitimately derivable from them.
# Fields the baseline architecture cannot produce (typed entities, structured
# constraints, normalization, multi-label intent, ambiguity state) are left
# at their empty/default values - reported as "not supported by this
# architecture", never force-filled.
# ---------------------------------------------------------------------------

_OLD_QUERY_TYPE_TO_INTENT = {
    "drug_target_search": IntentClass.C_COMPOUND_TARGET,
    "disease_treatment_search": IntentClass.B_CLINICAL_TRIAL_LANDSCAPE,
    "compound_information": IntentClass.C_COMPOUND_TARGET,
    "clinical_trial_search": IntentClass.B_CLINICAL_TRIAL_LANDSCAPE,
    "literature_review": IntentClass.A_LITERATURE_EVIDENCE,
    "general_research": IntentClass.A_LITERATURE_EVIDENCE,
}


def extract_candidate_a(query: str) -> NLUExtractionResult:
    """Baseline: agent/nodes.py's query_analysis_node prompt, called exactly
    as it is called in production, then mapped onto NLUExtractionResult."""
    t0 = time.time()
    llm = get_llm(temperature=0.1)
    prompt = QUERY_ANALYSIS_PROMPT.format(query=query)

    try:
        response = llm.invoke(prompt)
        raw = response.content
        usage = getattr(response, "usage_metadata", None)
        usage = usage if isinstance(usage, dict) else None
    except Exception as e:
        return NLUExtractionResult(
            schema_valid=False,
            raw_llm_output=None,
            parse_error=f"LLM call failed: {e}",
            architecture="candidate_a_baseline",
            latency_ms=(time.time() - t0) * 1000,
            llm_calls=1,
        )

    try:
        parsed = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError as e:
        return NLUExtractionResult(
            schema_valid=False,
            raw_llm_output=raw,
            parse_error=f"JSON parse failed: {e}",
            architecture="candidate_a_baseline",
            latency_ms=(time.time() - t0) * 1000,
            llm_calls=1,
            token_usage=usage,
        )

    entities: List[BiomedicalEntity] = []
    # The old schema has no entity typing - drug_targets are mapped to
    # entity_type="target", diseases to "disease", compounds to "compound".
    # No normalization is attempted here: Candidate A has no normalization
    # mechanism at all, so canonical_id/name/system stay None for every one
    # (this is architecture-honest, not a bug).
    for t in (parsed.get("drug_targets") or []):
        if isinstance(t, str) and t.strip():
            entities.append(BiomedicalEntity(entity_type=EntityType.TARGET, surface_form=t.strip(), confidence=0.5))
    for d in (parsed.get("diseases") or []):
        if isinstance(d, str) and d.strip():
            entities.append(BiomedicalEntity(entity_type=EntityType.DISEASE, surface_form=d.strip(), confidence=0.5))
    for c in (parsed.get("compounds") or []):
        if isinstance(c, str) and c.strip():
            entities.append(BiomedicalEntity(entity_type=EntityType.COMPOUND, surface_form=c.strip(), confidence=0.5))

    old_qtype = parsed.get("query_type")
    intent = [_OLD_QUERY_TYPE_TO_INTENT[old_qtype]] if old_qtype in _OLD_QUERY_TYPE_TO_INTENT else []

    try:
        rq = ResearchQuery(
            schema_version=SCHEMA_VERSION,
            original_query=query,
            normalized_query=query.strip(),
            intent=intent,
            intent_confidence=float(parsed.get("confidence", 0.0)) if old_qtype else 0.0,
            entities=entities,
            constraints=ConstraintSet(),  # Candidate A has no structured constraint extraction
            requested_evidence_types=[],  # Candidate A has no source-requirement prediction
            ambiguity=AmbiguityState(),   # Candidate A has no ambiguity detection
            extraction_confidence=float(parsed.get("confidence", 0.0)),
        )
    except ValidationError as e:
        return NLUExtractionResult(
            schema_valid=False,
            raw_llm_output=raw,
            parse_error=f"ResearchQuery validation failed: {e}",
            architecture="candidate_a_baseline",
            latency_ms=(time.time() - t0) * 1000,
            llm_calls=1,
            token_usage=usage,
        )

    return NLUExtractionResult(
        schema_valid=True,
        research_query=rq,
        raw_llm_output=raw,
        architecture="candidate_a_baseline",
        latency_ms=(time.time() - t0) * 1000,
        llm_calls=1,
        token_usage=usage,
    )


# ---------------------------------------------------------------------------
# Candidate B: schema-constrained structured LLM extraction + deterministic
# normalization (nlu/normalization.py). Full ResearchQuery fields.
# ---------------------------------------------------------------------------

STRUCTURED_EXTRACTION_PROMPT = """You are the Biomedical Query Understanding component of MedAgent, a biomedical research assistant.

Extract structured information from this research question. Be conservative - only extract what is explicitly present in the query text. Never invent entities, constraints, or IDs.

USER QUERY:
{query}

Return ONLY valid JSON with this EXACT structure (no markdown fences, no commentary):

{{
  "intent": ["A_literature_evidence"],
  "intent_confidence": 0.0,
  "entities": [
    {{"entity_type": "disease", "surface_form": "exact text span from the query", "semantic_roles": []}}
  ],
  "constraints": {{
    "trial_phases": [], "trial_statuses": [], "population": [], "age": [],
    "geography": [], "temporal": [], "study_type": [], "outcomes": []
  }},
  "requested_evidence_types": ["pubmed"],
  "ambiguity": {{"is_ambiguous": false, "ambiguity_reason": null, "candidate_interpretations": []}},
  "extraction_confidence": 0.0
}}

RULES:
- "intent": choose from this EXACT list of 8 values only, most specific applicable class(es) - normally exactly one, multi-label ONLY when the query genuinely requires both (e.g. cross-source AND chained multi-hop reasoning):
  A_literature_evidence, B_clinical_trial_landscape, C_compound_target, D_cross_source_synthesis, E_multi_hop_research, F_mechanism, G_constraint_heavy, I_ambiguous
- B vs G (Phase 2 closure fix - this is the single most common intent confusion, do not guess): {b_vs_g_rule}
- D vs E: {d_vs_e_rule}
- "entity_type": one of exactly: disease, gene, protein, target, compound, intervention - your single best-guess primary type.
  IMPORTANT default for gene/protein/drug-target mentions (e.g. "EGFR", "KRAS G12C", "BTK"): use entity_type="target" as the default/primary classification - this is the operational category for a drug-target/biomedical-research query and is what this system's own normalization table indexes them under, regardless of whether the surface form is a gene symbol or a protein name. Only use "gene" or "protein" as the PRIMARY entity_type when the query is unambiguously and specifically about that framing alone (e.g. "what gene encodes X" -> gene; "what is the crystal structure of the Y protein" -> protein) and target/drug relevance is not the point of the query.
- "semantic_roles": (usually []) ONLY for gene/protein/target mentions that are genuinely ambiguous between roles given the query's context (e.g. "EGFR" can be a gene symbol, its protein product, AND a therapeutic target all at once - list the OTHER valid types here, not the one already in entity_type). Do not populate this for entities that are not genuinely multi-role, and do not let this field change your entity_type choice above.
- EXHAUSTIVE ENTITY SCAN (Phase 2 closure fix): do entity extraction as its OWN complete pass over the ENTIRE query text, independent of and before you reason about constraints/intent. A target/gene/compound mention that appears in a trailing clause - especially "using X inhibitors", "with X", "targeting X" at the END of a long sentence already dense with phase/status/population language (e.g. "Find completed Phase 2 trials in pediatric patients with psoriasis using mTOR inhibitors") - is NOT less important than one mentioned earlier, and must NOT be dropped just because the sentence is constraint-heavy. Before finalizing your entities list, re-read the query once more specifically looking for any drug-target/gene/protein mention you may have skipped because it came after a long constraint clause.
- "surface_form": the EXACT substring as it appears in the query (do not paraphrase or expand abbreviations)
- Do NOT invent a canonical_id or canonical_name - normalization is handled separately; only output entity_type and surface_form for each entity
- "requested_evidence_types": which of pubmed, clinicaltrials, chembl a correct answer would genuinely need - only the minimum sufficient set, not all three by default
- If the query is ambiguous (e.g. underspecified abbreviation; missing disease/population/referent context needed to answer, such as "the disease", "this drug", "the treatment" with no antecedent; or a bare topic mention with no specific question, like "Tell me about X"), set ambiguity.is_ambiguous=true, explain why, list 2+ candidate_interpretations, AND set intent=["I_ambiguous"] (I_ambiguous IS the intent class for exactly this situation - do not classify an ambiguous query as if it were a well-formed A-G question just because it superficially resembles one; the missing referent/context is what makes it I, not what it would otherwise look like once resolved)
- Classify intent from the query TEXT alone (what kind of question is being asked and which source(s) it needs) - do NOT try to judge whether real-world evidence actually exists for the claim; that is a downstream evidence-sufficiency judgment made AFTER sources are queried, not a query-understanding task (Phase 2 closure decision, see nlu/taxonomy.py's H_insufficient_evidence removal note). A query about a fictional compound or an implausible claim still gets classified by its surface form (A-G/I), exactly like any other query of that shape.
- Never guess a value for a constraint field that is not explicitly stated

Return ONLY the JSON object."""


def _canonicalize_constraint_fields(constraints_raw: Dict[str, Any]) -> Dict[str, Any]:
    """Canonicalize trial_phases/trial_statuses free text into
    nlu/normalization.py's canonical codes before ConstraintSet validation
    (Phase 2 closure item 7). A combined-phase mention (e.g. "Phase I/II")
    expands into every phase it names, never collapsed to one; unrecognized
    text is dropped (abstain) rather than guessed."""
    out = dict(constraints_raw)

    raw_phases = out.get("trial_phases")
    if isinstance(raw_phases, list):
        canon_phases = []
        for v in raw_phases:
            if not isinstance(v, str):
                continue
            for code in canonicalize_trial_phase(v):
                if code not in canon_phases:
                    canon_phases.append(code)
        out["trial_phases"] = canon_phases

    raw_statuses = out.get("trial_statuses")
    if isinstance(raw_statuses, list):
        canon_statuses = []
        for v in raw_statuses:
            if not isinstance(v, str):
                continue
            code = canonicalize_trial_status(v)
            if code and code not in canon_statuses:
                canon_statuses.append(code)
        out["trial_statuses"] = canon_statuses

    return out


def _coerce_intent(raw_list) -> List[IntentClass]:
    out = []
    for v in (raw_list or []):
        if isinstance(v, str) and v in VALID_INTENT_VALUES:
            out.append(IntentClass(v))
    return out


def _coerce_entities(raw_list) -> List[BiomedicalEntity]:
    valid_types = {e.value for e in EntityType}
    out = []
    for item in (raw_list or []):
        if not isinstance(item, dict):
            continue
        etype = item.get("entity_type")
        surface = item.get("surface_form")
        if etype not in valid_types or not isinstance(surface, str) or not surface.strip():
            continue
        surface = surface.strip()
        norm = normalize_entity(surface, etype)

        raw_roles = item.get("semantic_roles")
        semantic_roles = []
        if isinstance(raw_roles, list):
            for r in raw_roles:
                if isinstance(r, str) and r in valid_types and r != etype:
                    semantic_roles.append(EntityType(r))

        out.append(BiomedicalEntity(
            entity_type=EntityType(etype),
            surface_form=surface,
            semantic_roles=semantic_roles,
            canonical_name=norm.canonical_name,
            canonical_id=norm.canonical_id,
            normalization_system=norm.normalization_system,
            confidence=0.9 if norm.matched else 0.6,
        ))
    return out


def _coerce_evidence_types(raw_list) -> List[EvidenceSourceType]:
    valid = {e.value for e in EvidenceSourceType}
    out = []
    for v in (raw_list or []):
        if isinstance(v, str) and v in valid:
            out.append(EvidenceSourceType(v))
    return out


def extract_candidate_b(query: str, model: Optional[str] = None) -> NLUExtractionResult:
    """Schema-constrained structured extraction: LLM proposes typed
    entities/intent/constraints, strict Pydantic validation enforces the
    schema, and nlu/normalization.py (deterministic, no LLM involvement)
    performs normalization - the LLM never proposes a canonical_id itself,
    structurally preventing fabricated IDs at the source."""
    t0 = time.time()
    llm_kwargs = {"temperature": 0.0}  # deterministic extraction, not creative
    if model:
        # Phase 2 closure item 12: optional model override for the
        # smaller-model comparison experiment - never used by the frozen
        # production path (agent/nodes.py never passes this), only by
        # evaluation/v2/run_nlu_eval.py's --model flag.
        llm_kwargs["model"] = model
    llm = get_llm(**llm_kwargs)
    prompt = STRUCTURED_EXTRACTION_PROMPT.format(query=query, b_vs_g_rule=B_VS_G_RULE, d_vs_e_rule=DI_VS_E_RULE)

    # Phase 2 closure item 9: bounded, structural recovery for a bad/empty
    # response - one retry with the IDENTICAL request, never a fabricated
    # fallback. Root cause of the 3 test-split failures seen in the
    # original Phase 2 pass (artifacts/v2/nlu_test_split_results.json):
    # 2 were a genuinely empty response.content ("Expecting value: line 1
    # column 1 (char 0)" - json.loads on ""), 1 was a mid-generation
    # truncation ("Unterminated string...") consistent with hitting
    # get_llm's default max_tokens=2048 before the JSON object closed - a
    # different failure mode from a true empty response, but both are
    # "the model did not return a usable structured payload" and both are
    # handled by the same bounded retry-then-fail path here.
    raw = None
    usage = None
    last_error = None
    llm_calls = 0
    parsed = None

    for attempt in range(2):  # 1 initial attempt + 1 identical retry, never more
        llm_calls += 1
        try:
            response = llm.invoke(prompt)
            raw = response.content
            usage = getattr(response, "usage_metadata", None)
            usage = usage if isinstance(usage, dict) else None
        except Exception as e:
            last_error = f"LLM call failed: {e}"
            continue

        if not raw or not raw.strip():
            last_error = "Empty LLM response (no content)"
            continue

        try:
            candidate_parsed = json.loads(_strip_code_fence(raw))
        except json.JSONDecodeError as e:
            last_error = f"JSON parse failed: {e}"
            continue

        if not isinstance(candidate_parsed, dict):
            last_error = "Top-level JSON was not an object"
            continue

        parsed = candidate_parsed
        last_error = None
        break

    if parsed is None:
        return NLUExtractionResult(
            schema_valid=False,
            raw_llm_output=raw,
            parse_error=f"NLU_FAILURE: exhausted {llm_calls} attempt(s), last error: {last_error}",
            architecture="candidate_b_structured",
            latency_ms=(time.time() - t0) * 1000,
            llm_calls=llm_calls,
            token_usage=usage,
        )

    constraints_raw = parsed.get("constraints") or {}
    constraints_raw = _canonicalize_constraint_fields(constraints_raw)
    try:
        constraints = ConstraintSet(**{
            k: v for k, v in constraints_raw.items() if k in ConstraintSet.model_fields
        })
    except ValidationError:
        constraints = ConstraintSet()

    ambig_raw = parsed.get("ambiguity") or {}
    try:
        ambiguity = AmbiguityState(
            is_ambiguous=bool(ambig_raw.get("is_ambiguous", False)),
            ambiguity_reason=ambig_raw.get("ambiguity_reason"),
            candidate_interpretations=[
                c for c in (ambig_raw.get("candidate_interpretations") or []) if isinstance(c, str)
            ],
        )
    except (ValidationError, TypeError):
        ambiguity = AmbiguityState()

    try:
        rq = ResearchQuery(
            schema_version=SCHEMA_VERSION,
            original_query=query,
            normalized_query=re.sub(r"\s+", " ", query.strip()),
            intent=_coerce_intent(parsed.get("intent")),
            intent_confidence=float(parsed.get("intent_confidence", 0.0) or 0.0),
            entities=_coerce_entities(parsed.get("entities")),
            constraints=constraints,
            requested_evidence_types=_coerce_evidence_types(parsed.get("requested_evidence_types")),
            ambiguity=ambiguity,
            extraction_confidence=float(parsed.get("extraction_confidence", 0.0) or 0.0),
        )
    except (ValidationError, ValueError, TypeError) as e:
        return NLUExtractionResult(
            schema_valid=False,
            raw_llm_output=raw,
            parse_error=f"ResearchQuery validation failed: {e}",
            architecture="candidate_b_structured",
            latency_ms=(time.time() - t0) * 1000,
            llm_calls=llm_calls,
            token_usage=usage,
        )

    return NLUExtractionResult(
        schema_valid=True,
        research_query=rq,
        raw_llm_output=raw,
        architecture="candidate_b_structured",
        token_usage=usage,
        latency_ms=(time.time() - t0) * 1000,
        llm_calls=llm_calls,
    )


# ---------------------------------------------------------------------------
# Candidate C: decomposed structured extraction (Phase 2 latency-closure
# Family C). Root cause of Candidate B's latency (profiled in
# artifacts/v2/nlu_latency_baseline.json): the underlying model
# (nvidia/nemotron-3-super-120b-a12b) emits a separate `reasoning_content`
# chain-of-thought BEFORE every JSON answer, and its LENGTH scales with the
# complexity/breadth of the single prompt, not with a fixed per-call tax - a
# live component-profiling test (same session) showed a simplified,
# single-purpose entity-only prompt producing ~1.1K reasoning chars in ~3.4s
# and a simplified intent+constraints-only prompt producing ~2.0K reasoning
# chars in ~5.6s, against ~5.3K reasoning chars / ~21-34s for Candidate B's
# single monolithic prompt asking for everything at once. Two smaller,
# single-purpose calls empirically cost LESS wall-clock than one broad call,
# even though it is 2 LLM round-trips instead of 1.
#
# Candidate C keeps ALL of Candidate B's quality-critical prompt content
# (EXHAUSTIVE ENTITY SCAN rule, target-default entity typing, semantic_roles
# rule for the entity call; B_VS_G_RULE, DI_VS_E_RULE, I_ambiguous intent
# mapping for the intent/constraint call) - it is a decomposition of the
# SAME prompt content into two focused calls, not a rewrite that risks
# losing the entity-F1 gains Candidate B fought for. Normalization
# (deterministic, no LLM) is unchanged from Candidate B.
# ---------------------------------------------------------------------------

ENTITY_EXTRACTION_PROMPT = """You are the entity-extraction component of MedAgent's Biomedical Query Understanding stage.

Extract ONLY biomedical entities from this research question. Be conservative - only extract what is explicitly present in the query text. Never invent entities.

USER QUERY:
{query}

Return ONLY valid JSON with this EXACT structure (no markdown fences, no commentary):

{{
  "entities": [
    {{"entity_type": "disease", "surface_form": "exact text span from the query", "semantic_roles": []}}
  ]
}}

RULES:
- "entity_type": one of exactly: disease, gene, protein, target, compound, intervention - your single best-guess primary type.
  IMPORTANT default for gene/protein/drug-target mentions (e.g. "EGFR", "KRAS G12C", "BTK"): use entity_type="target" as the default/primary classification - this is the operational category for a drug-target/biomedical-research query and is what this system's own normalization table indexes them under, regardless of whether the surface form is a gene symbol or a protein name. Only use "gene" or "protein" as the PRIMARY entity_type when the query is unambiguously and specifically about that framing alone (e.g. "what gene encodes X" -> gene; "what is the crystal structure of the Y protein" -> protein) and target/drug relevance is not the point of the query.
- "semantic_roles": (usually []) ONLY for gene/protein/target mentions that are genuinely ambiguous between roles given the query's context (e.g. "EGFR" can be a gene symbol, its protein product, AND a therapeutic target all at once - list the OTHER valid types here, not the one already in entity_type). Do not populate this for entities that are not genuinely multi-role, and do not let this field change your entity_type choice above.
- EXHAUSTIVE ENTITY SCAN (Phase 2 closure fix): do entity extraction as a complete pass over the ENTIRE query text. A target/gene/compound mention that appears in a trailing clause - especially "using X inhibitors", "with X", "targeting X" at the END of a long sentence already dense with phase/status/population language (e.g. "Find completed Phase 2 trials in pediatric patients with psoriasis using mTOR inhibitors") - is NOT less important than one mentioned earlier, and must NOT be dropped just because the sentence is constraint-heavy. Before finalizing your entities list, re-read the query once more specifically looking for any drug-target/gene/protein mention you may have skipped because it came after a long constraint clause.
- "surface_form": the EXACT substring as it appears in the query (do not paraphrase or expand abbreviations)
- Do NOT invent a canonical_id or canonical_name - normalization is handled separately; only output entity_type and surface_form for each entity

Return ONLY the JSON object."""

INTENT_CONSTRAINT_PROMPT = """You are the intent-classification and constraint-extraction component of MedAgent's Biomedical Query Understanding stage.

Extract structured information from this research question. Be conservative - only extract what is explicitly present in the query text. Never invent constraints or IDs.

USER QUERY:
{query}

Return ONLY valid JSON with this EXACT structure (no markdown fences, no commentary):

{{
  "intent": ["A_literature_evidence"],
  "intent_confidence": 0.0,
  "constraints": {{
    "trial_phases": [], "trial_statuses": [], "population": [], "age": [],
    "geography": [], "temporal": [], "study_type": [], "outcomes": []
  }},
  "requested_evidence_types": ["pubmed"],
  "ambiguity": {{"is_ambiguous": false, "ambiguity_reason": null, "candidate_interpretations": []}},
  "extraction_confidence": 0.0
}}

RULES:
- "intent": choose from this EXACT list of 8 values only, most specific applicable class(es) - normally exactly one, multi-label ONLY when the query genuinely requires both (e.g. cross-source AND chained multi-hop reasoning):
  A_literature_evidence, B_clinical_trial_landscape, C_compound_target, D_cross_source_synthesis, E_multi_hop_research, F_mechanism, G_constraint_heavy, I_ambiguous
- B vs G (Phase 2 closure fix - this is the single most common intent confusion, do not guess): {b_vs_g_rule}
- D vs E: {d_vs_e_rule}
- "requested_evidence_types": which of pubmed, clinicaltrials, chembl a correct answer would genuinely need - only the minimum sufficient set, not all three by default
- If the query is ambiguous (e.g. underspecified abbreviation; missing disease/population/referent context needed to answer, such as "the disease", "this drug", "the treatment" with no antecedent; or a bare topic mention with no specific question, like "Tell me about X"), set ambiguity.is_ambiguous=true, explain why, list 2+ candidate_interpretations, AND set intent=["I_ambiguous"] (I_ambiguous IS the intent class for exactly this situation - do not classify an ambiguous query as if it were a well-formed A-G question just because it superficially resembles one; the missing referent/context is what makes it I, not what it would otherwise look like once resolved)
- Classify intent from the query TEXT alone (what kind of question is being asked and which source(s) it needs) - do NOT try to judge whether real-world evidence actually exists for the claim; that is a downstream evidence-sufficiency judgment made AFTER sources are queried, not a query-understanding task. A query about a fictional compound or an implausible claim still gets classified by its surface form (A-G/I), exactly like any other query of that shape.
- Never guess a value for a constraint field that is not explicitly stated

Return ONLY the JSON object."""


def _invoke_json(llm, prompt: str, architecture_tag: str):
    """Shared bounded-retry JSON-call helper for Candidate C's two calls -
    identical recovery semantics to Candidate B (Phase 2 closure item 9): 1
    initial attempt + 1 identical retry on empty/unparseable response, never
    a fabricated fallback. Returns (parsed_dict_or_None, raw, usage,
    llm_calls, last_error)."""
    raw = None
    usage = None
    last_error = None
    llm_calls = 0
    parsed = None

    for attempt in range(2):
        llm_calls += 1
        try:
            response = llm.invoke(prompt)
            raw = response.content
            usage = getattr(response, "usage_metadata", None)
            usage = usage if isinstance(usage, dict) else None
        except Exception as e:
            last_error = f"LLM call failed: {e}"
            continue

        if not raw or not raw.strip():
            last_error = "Empty LLM response (no content)"
            continue

        try:
            candidate_parsed = json.loads(_strip_code_fence(raw))
        except json.JSONDecodeError as e:
            last_error = f"JSON parse failed: {e}"
            continue

        if not isinstance(candidate_parsed, dict):
            last_error = "Top-level JSON was not an object"
            continue

        parsed = candidate_parsed
        last_error = None
        break

    return parsed, raw, usage, llm_calls, last_error


def extract_candidate_c(query: str, model: Optional[str] = None) -> NLUExtractionResult:
    """Decomposed structured extraction: one focused LLM call for entities,
    one focused LLM call for intent/constraints/ambiguity/evidence-types,
    then the same deterministic normalization (nlu/normalization.py) as
    Candidate B. See module-level comment above for why this reduces
    latency despite being 2 calls instead of 1."""
    t0 = time.time()
    llm_kwargs = {"temperature": 0.0}
    if model:
        llm_kwargs["model"] = model
    llm = get_llm(**llm_kwargs)

    entity_prompt = ENTITY_EXTRACTION_PROMPT.format(query=query)
    entity_parsed, entity_raw, entity_usage, entity_calls, entity_err = _invoke_json(
        llm, entity_prompt, "candidate_c_decomposed"
    )

    intent_prompt = INTENT_CONSTRAINT_PROMPT.format(query=query, b_vs_g_rule=B_VS_G_RULE, d_vs_e_rule=DI_VS_E_RULE)
    intent_parsed, intent_raw, intent_usage, intent_calls, intent_err = _invoke_json(
        llm, intent_prompt, "candidate_c_decomposed"
    )

    total_calls = entity_calls + intent_calls
    combined_usage = None
    if entity_usage or intent_usage:
        combined_usage = {
            "input_tokens": (entity_usage or {}).get("input_tokens", 0) + (intent_usage or {}).get("input_tokens", 0),
            "output_tokens": (entity_usage or {}).get("output_tokens", 0) + (intent_usage or {}).get("output_tokens", 0),
            "total_tokens": (entity_usage or {}).get("total_tokens", 0) + (intent_usage or {}).get("total_tokens", 0),
        }

    if entity_parsed is None or intent_parsed is None:
        errs = []
        if entity_parsed is None:
            errs.append(f"entity call: {entity_err}")
        if intent_parsed is None:
            errs.append(f"intent call: {intent_err}")
        return NLUExtractionResult(
            schema_valid=False,
            raw_llm_output=json.dumps({"entity_raw": entity_raw, "intent_raw": intent_raw}),
            parse_error=f"NLU_FAILURE: exhausted attempts, {'; '.join(errs)}",
            architecture="candidate_c_decomposed",
            latency_ms=(time.time() - t0) * 1000,
            llm_calls=total_calls,
            token_usage=combined_usage,
        )

    constraints_raw = _canonicalize_constraint_fields(intent_parsed.get("constraints") or {})
    try:
        constraints = ConstraintSet(**{
            k: v for k, v in constraints_raw.items() if k in ConstraintSet.model_fields
        })
    except ValidationError:
        constraints = ConstraintSet()

    ambig_raw = intent_parsed.get("ambiguity") or {}
    try:
        ambiguity = AmbiguityState(
            is_ambiguous=bool(ambig_raw.get("is_ambiguous", False)),
            ambiguity_reason=ambig_raw.get("ambiguity_reason"),
            candidate_interpretations=[
                c for c in (ambig_raw.get("candidate_interpretations") or []) if isinstance(c, str)
            ],
        )
    except (ValidationError, TypeError):
        ambiguity = AmbiguityState()

    try:
        rq = ResearchQuery(
            schema_version=SCHEMA_VERSION,
            original_query=query,
            normalized_query=re.sub(r"\s+", " ", query.strip()),
            intent=_coerce_intent(intent_parsed.get("intent")),
            intent_confidence=float(intent_parsed.get("intent_confidence", 0.0) or 0.0),
            entities=_coerce_entities(entity_parsed.get("entities")),
            constraints=constraints,
            requested_evidence_types=_coerce_evidence_types(intent_parsed.get("requested_evidence_types")),
            ambiguity=ambiguity,
            extraction_confidence=float(intent_parsed.get("extraction_confidence", 0.0) or 0.0),
        )
    except (ValidationError, ValueError, TypeError) as e:
        return NLUExtractionResult(
            schema_valid=False,
            raw_llm_output=json.dumps({"entity_raw": entity_raw, "intent_raw": intent_raw}),
            parse_error=f"ResearchQuery validation failed: {e}",
            architecture="candidate_c_decomposed",
            latency_ms=(time.time() - t0) * 1000,
            llm_calls=total_calls,
            token_usage=combined_usage,
        )

    return NLUExtractionResult(
        schema_valid=True,
        research_query=rq,
        raw_llm_output=json.dumps({"entity_raw": entity_raw, "intent_raw": intent_raw}),
        architecture="candidate_c_decomposed",
        token_usage=combined_usage,
        latency_ms=(time.time() - t0) * 1000,
        llm_calls=total_calls,
    )


# ---------------------------------------------------------------------------
# Frozen entry point - set after architecture selection (task item 9).
# Do NOT import this at module scope elsewhere before nlu_frozen_config.json
# exists; nlu/__init__.py reads the frozen config to decide which candidate
# function this delegates to.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Candidate D: local Qwen2.5-1.5B-Instruct (Apache 2.0), Phase 2 latency
# experiment. Human-approved single-model download (see
# artifacts/v2/nlu_qwen_*.json) — NOT the frozen production architecture.
# Reuses candidate_b_structured's EXACT prompt (STRUCTURED_EXTRACTION_PROMPT,
# including B_VS_G_RULE/DI_VS_E_RULE and the EXHAUSTIVE ENTITY SCAN fix) and
# IDENTICAL postprocessing (constraint canonicalization, coercion,
# deterministic nlu/normalization.py lookup) as candidate_b_structured - this
# experiment swaps ONLY the extraction model (local Qwen via
# nlu/local_qwen_extractor.py, no network round-trip) for NVIDIA-hosted
# nemotron-3-super-120b-a12b, not the surrounding architecture.
# ---------------------------------------------------------------------------

def extract_candidate_d_local_qwen(query: str, model: Optional[str] = None) -> NLUExtractionResult:
    """Local-model structured extraction via `Qwen/Qwen2.5-1.5B-Instruct`
    (transformers/torch, offline, no NVIDIA API call). `model` kwarg
    accepted only for call-signature parity with candidate_b/c's --model
    override (evaluation/v2/run_nlu_eval.py); ignored here since exactly
    one local model is under test this round."""
    from nlu.local_qwen_extractor import generate as _qwen_generate

    t0 = time.time()
    prompt = STRUCTURED_EXTRACTION_PROMPT.format(query=query, b_vs_g_rule=B_VS_G_RULE, d_vs_e_rule=DI_VS_E_RULE)

    raw = None
    usage = None
    last_error = None
    llm_calls = 0
    parsed = None

    for attempt in range(2):  # identical bounded-retry semantics to candidate_b (closure item 9)
        llm_calls += 1
        try:
            raw, usage = _qwen_generate(prompt)
        except Exception as e:
            last_error = f"Local model call failed: {e}"
            continue

        if not raw or not raw.strip():
            last_error = "Empty local model response (no content)"
            continue

        try:
            candidate_parsed = json.loads(_strip_code_fence(raw))
        except json.JSONDecodeError as e:
            last_error = f"JSON parse failed: {e}"
            continue

        if not isinstance(candidate_parsed, dict):
            last_error = "Top-level JSON was not an object"
            continue

        parsed = candidate_parsed
        last_error = None
        break

    if parsed is None:
        return NLUExtractionResult(
            schema_valid=False,
            raw_llm_output=raw,
            parse_error=f"NLU_FAILURE: exhausted {llm_calls} attempt(s), last error: {last_error}",
            architecture="candidate_d_local_qwen",
            latency_ms=(time.time() - t0) * 1000,
            llm_calls=llm_calls,
            token_usage=usage,
        )

    # Identical postprocessing path to candidate_b_structured.
    constraints_raw = parsed.get("constraints") or {}
    constraints_raw = _canonicalize_constraint_fields(constraints_raw)
    try:
        constraints = ConstraintSet(**{
            k: v for k, v in constraints_raw.items() if k in ConstraintSet.model_fields
        })
    except ValidationError:
        constraints = ConstraintSet()

    ambig_raw = parsed.get("ambiguity") or {}
    try:
        ambiguity = AmbiguityState(
            is_ambiguous=bool(ambig_raw.get("is_ambiguous", False)),
            ambiguity_reason=ambig_raw.get("ambiguity_reason"),
            candidate_interpretations=[
                c for c in (ambig_raw.get("candidate_interpretations") or []) if isinstance(c, str)
            ],
        )
    except (ValidationError, TypeError):
        ambiguity = AmbiguityState()

    try:
        rq = ResearchQuery(
            schema_version=SCHEMA_VERSION,
            original_query=query,
            normalized_query=re.sub(r"\s+", " ", query.strip()),
            intent=_coerce_intent(parsed.get("intent")),
            intent_confidence=float(parsed.get("intent_confidence", 0.0) or 0.0),
            entities=_coerce_entities(parsed.get("entities")),
            constraints=constraints,
            requested_evidence_types=_coerce_evidence_types(parsed.get("requested_evidence_types")),
            ambiguity=ambiguity,
            extraction_confidence=float(parsed.get("extraction_confidence", 0.0) or 0.0),
        )
    except (ValidationError, ValueError, TypeError) as e:
        return NLUExtractionResult(
            schema_valid=False,
            raw_llm_output=raw,
            parse_error=f"ResearchQuery validation failed: {e}",
            architecture="candidate_d_local_qwen",
            latency_ms=(time.time() - t0) * 1000,
            llm_calls=llm_calls,
            token_usage=usage,
        )

    return NLUExtractionResult(
        schema_valid=True,
        research_query=rq,
        raw_llm_output=raw,
        architecture="candidate_d_local_qwen",
        token_usage=usage,
        latency_ms=(time.time() - t0) * 1000,
        llm_calls=llm_calls,
    )


# ---------------------------------------------------------------------------
# Candidate E: same single-call structured extraction as Candidate B
# (IDENTICAL prompt, schema, canonicalization, coercion, normalization -
# nothing about the task changes), but targeting a different, currently
# discoverable NVIDIA-hosted model
# (`nvidia/nemotron-3.5-lightning-30b-a3b` - a hybrid Mamba-2/MoE model with
# 3B of 30B params active per token) with reasoning explicitly disabled via
# the model's OWN documented mechanism
# (`chat_template_kwargs={"enable_thinking": False}`, confirmed against
# https://docs.nvidia.com/nim/large-language-models/2.0.10/get-started/advanced/get-started-nemotron-3.5-lightning.html
# - NOT a prompt-text trick like the previously-tried `/no_think` or
# "detailed thinking off" system message, both of which were found unreliable
# in earlier Phase 2 latency-closure rounds). Live-verified this round: with
# this kwarg, `response.additional_kwargs['reasoning_content']` is empty and
# single-call latency drops from ~12-28s (same prompt, reasoning enabled) to
# ~1.3s. See artifacts/v2/nlu_nvidia_fastmodel_experiment_plan.json for the
# full candidate-discovery record and rejection/acceptance gates.
# ---------------------------------------------------------------------------

NVIDIA_FAST_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"


def extract_candidate_e_nvidia_fast(query: str, model: Optional[str] = None) -> NLUExtractionResult:
    """Identical task/schema/prompt/postprocessing to candidate_b_structured
    - the ONLY thing that changes is which NVIDIA-hosted model answers the
    call, and that reasoning is explicitly turned off via the model's own
    `chat_template_kwargs` mechanism rather than the surrounding
    architecture. Uses the EXACT SAME STRUCTURED_EXTRACTION_PROMPT,
    ConstraintSet canonicalization, entity coercion, and
    nlu/normalization.py deterministic normalization as candidate_b -
    duplicated here (not delegated) only so this experimental path can be
    cleanly deleted if rejected without touching the frozen candidate_b
    code."""
    t0 = time.time()
    use_model = model or NVIDIA_FAST_MODEL
    llm = get_llm(temperature=0.0, model=use_model)
    prompt = STRUCTURED_EXTRACTION_PROMPT.format(query=query, b_vs_g_rule=B_VS_G_RULE, d_vs_e_rule=DI_VS_E_RULE)

    raw = None
    usage = None
    last_error = None
    llm_calls = 0
    parsed = None

    for attempt in range(2):  # identical bounded-retry semantics to candidate_b (closure item 9)
        llm_calls += 1
        try:
            response = llm.invoke(prompt, chat_template_kwargs={"enable_thinking": False})
            raw = response.content
            usage = getattr(response, "usage_metadata", None)
            usage = usage if isinstance(usage, dict) else None
        except Exception as e:
            last_error = f"LLM call failed: {e}"
            continue

        if not raw or not raw.strip():
            last_error = "Empty LLM response (no content)"
            continue

        try:
            candidate_parsed = json.loads(_strip_code_fence(raw))
        except json.JSONDecodeError as e:
            last_error = f"JSON parse failed: {e}"
            continue

        if not isinstance(candidate_parsed, dict):
            last_error = "Top-level JSON was not an object"
            continue

        parsed = candidate_parsed
        last_error = None
        break

    if parsed is None:
        return NLUExtractionResult(
            schema_valid=False,
            raw_llm_output=raw,
            parse_error=f"NLU_FAILURE: exhausted {llm_calls} attempt(s), last error: {last_error}",
            architecture="candidate_e_nvidia_fast",
            latency_ms=(time.time() - t0) * 1000,
            llm_calls=llm_calls,
            token_usage=usage,
        )

    constraints_raw = parsed.get("constraints") or {}
    constraints_raw = _canonicalize_constraint_fields(constraints_raw)
    try:
        constraints = ConstraintSet(**{
            k: v for k, v in constraints_raw.items() if k in ConstraintSet.model_fields
        })
    except ValidationError:
        constraints = ConstraintSet()

    ambig_raw = parsed.get("ambiguity") or {}
    try:
        ambiguity = AmbiguityState(
            is_ambiguous=bool(ambig_raw.get("is_ambiguous", False)),
            ambiguity_reason=ambig_raw.get("ambiguity_reason"),
            candidate_interpretations=[
                c for c in (ambig_raw.get("candidate_interpretations") or []) if isinstance(c, str)
            ],
        )
    except (ValidationError, TypeError):
        ambiguity = AmbiguityState()

    try:
        rq = ResearchQuery(
            schema_version=SCHEMA_VERSION,
            original_query=query,
            normalized_query=re.sub(r"\s+", " ", query.strip()),
            intent=_coerce_intent(parsed.get("intent")),
            intent_confidence=float(parsed.get("intent_confidence", 0.0) or 0.0),
            entities=_coerce_entities(parsed.get("entities")),
            constraints=constraints,
            requested_evidence_types=_coerce_evidence_types(parsed.get("requested_evidence_types")),
            ambiguity=ambiguity,
            extraction_confidence=float(parsed.get("extraction_confidence", 0.0) or 0.0),
        )
    except (ValidationError, ValueError, TypeError) as e:
        return NLUExtractionResult(
            schema_valid=False,
            raw_llm_output=raw,
            parse_error=f"ResearchQuery validation failed: {e}",
            architecture="candidate_e_nvidia_fast",
            latency_ms=(time.time() - t0) * 1000,
            llm_calls=llm_calls,
            token_usage=usage,
        )

    return NLUExtractionResult(
        schema_valid=True,
        research_query=rq,
        raw_llm_output=raw,
        architecture="candidate_e_nvidia_fast",
        token_usage=usage,
        latency_ms=(time.time() - t0) * 1000,
        llm_calls=llm_calls,
    )


# ---------------------------------------------------------------------------
# Candidate F: Cerebras-hosted structured extraction (Phase 2 Cerebras
# latency experiment, human-authorized under a hard $0.50 free-trial-credit
# cap - see artifacts/v2/nlu_cerebras_provider_verification.json and
# nlu_cerebras_budget_plan.json). EXPERIMENTAL ONLY - never wired into
# agent/nodes.py, never made the default in ARCHITECTURE_FUNCS lookups
# outside evaluation/v2/run_nlu_eval.py --architecture flag. Stays entirely
# behind this same extractor.py abstraction, exactly like Candidates C/D/E:
# nothing about the task, schema, taxonomy, or normalization changes -
# ONLY the model/provider and its JSON Schema strict-mode encoding differ.
#
# Uses a direct HTTPS call via `requests` (already a project dependency, no
# new package added) to Cerebras' OpenAI-compatible /v1/chat/completions
# endpoint rather than the `cerebras_cloud_sdk` package, since a single
# structured chat-completion call needs nothing the SDK provides beyond what
# `requests` + a hand-built strict JSON Schema already covers - the smallest
# implementation that fits, per the task's explicit dependency guidance.
#
# Same STRUCTURED_EXTRACTION_PROMPT text as candidate_b_structured (same
# B_VS_G_RULE/DI_VS_E_RULE/EXHAUSTIVE-ENTITY-SCAN content) - only the output
# contract is translated into Cerebras' strict JSON Schema shape
# (`additionalProperties: false` on every object, nullable fields expressed
# as a ["string","null"] union per Cerebras' documented strict-mode rules -
# see nlu_cerebras_provider_verification.json). Postprocessing (constraint
# canonicalization, entity coercion, evidence-type coercion, normalization)
# is IDENTICAL to candidate_b_structured - reused, not reimplemented, so a
# quality difference reflects the model/provider only, never a
# postprocessing drift between candidates.
# ---------------------------------------------------------------------------

CEREBRAS_API_URL = "https://api.cerebras.ai/v1/chat/completions"
CEREBRAS_MODEL_GPT_OSS_120B = "gpt-oss-120b"
CEREBRAS_MODEL_QWEN_FALLBACK = "qwen-3.8-27b"

# Free Trial tier rate limit for gpt-oss-120b is 5 RPM (see
# nlu_cerebras_provider_verification.json's rate_limits_free_trial_tier).
# capacity=1 caps burst to a single immediate call - never more than one
# request fires before the bucket has to refill, which is the conservative
# reading of a "5 RPM, no burst" limit.
CEREBRAS_RATE_LIMIT_KEY = "cerebras_free_trial"
CEREBRAS_RATE_LIMIT_RPS = 5.0 / 60.0

_ENTITY_TYPE_VALUES = [e.value for e in EntityType]
_INTENT_VALUES = [v for v in VALID_INTENT_VALUES]
_EVIDENCE_TYPE_VALUES = [e.value for e in EvidenceSourceType]
_CONSTRAINT_FIELD_NAMES = list(ConstraintSet.model_fields.keys())

# Strict-mode JSON Schema translation of STRUCTURED_EXTRACTION_PROMPT's
# output contract (see docstring above for the translation rules applied:
# additionalProperties:false on every object; nullable via a type union,
# never OpenAPI `nullable: true`; every property listed in `required`, since
# strict mode does not support "optional" properties - a field that is
# conceptually optional is instead allowed to be an empty array/null value).
# This is a 1:1 structural translation of the EXACT same fields
# STRUCTURED_EXTRACTION_PROMPT already asks for - no field added, removed,
# renamed, or narrowed in meaning.
CEREBRAS_RESEARCH_QUERY_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "intent", "intent_confidence", "entities", "constraints",
        "requested_evidence_types", "ambiguity", "extraction_confidence",
    ],
    "properties": {
        "intent": {
            "type": "array",
            "items": {"type": "string", "enum": _INTENT_VALUES},
        },
        "intent_confidence": {"type": "number"},
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["entity_type", "surface_form", "semantic_roles"],
                "properties": {
                    "entity_type": {"type": "string", "enum": _ENTITY_TYPE_VALUES},
                    "surface_form": {"type": "string"},
                    "semantic_roles": {
                        "type": "array",
                        "items": {"type": "string", "enum": _ENTITY_TYPE_VALUES},
                    },
                },
            },
        },
        "constraints": {
            "type": "object",
            "additionalProperties": False,
            "required": _CONSTRAINT_FIELD_NAMES,
            "properties": {
                field: {"type": "array", "items": {"type": "string"}}
                for field in _CONSTRAINT_FIELD_NAMES
            },
        },
        "requested_evidence_types": {
            "type": "array",
            "items": {"type": "string", "enum": _EVIDENCE_TYPE_VALUES},
        },
        "ambiguity": {
            "type": "object",
            "additionalProperties": False,
            "required": ["is_ambiguous", "ambiguity_reason", "candidate_interpretations"],
            "properties": {
                "is_ambiguous": {"type": "boolean"},
                # Nullable via type union - Cerebras strict mode does not
                # support OpenAPI `nullable: true` (see provider verification
                # artifact); this is semantically identical to Optional[str].
                "ambiguity_reason": {"type": ["string", "null"]},
                "candidate_interpretations": {"type": "array", "items": {"type": "string"}},
            },
        },
        "extraction_confidence": {"type": "number"},
    },
}


def _invoke_cerebras_json(
    prompt: str,
    model: str,
    reasoning_effort: str = "low",
    max_completion_tokens: int = 4096,
    timeout_seconds: int = 60,
):
    """Bounded-retry (1 initial + 1 identical retry, matching every other
    candidate's empty_response_handling contract) direct HTTPS call to
    Cerebras' strict-JSON-Schema chat completions endpoint. Rate-limited to
    the Free Trial tier's 5 RPM via utils.rate_limiter (never bursts, never
    exceeds the documented limit - see CEREBRAS_RATE_LIMIT_RPS above).

    The API key is read via settings.CEREBRAS_API_KEY.get_secret_value()
    ONLY at this HTTP Authorization-header construction point, and is never
    logged, printed, included in any exception message, or written to any
    return value here - `requests` exceptions are caught and stringified via
    `str(e)`, which for an auth failure names the endpoint/status, not the
    key (verified: requests never echoes request headers into its exception
    text)."""
    if not settings.CEREBRAS_API_KEY:
        raise RuntimeError("CEREBRAS_API_KEY is not configured")
    api_key = settings.CEREBRAS_API_KEY.get_secret_value()

    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "research_query_extraction",
                "strict": True,
                "schema": CEREBRAS_RESEARCH_QUERY_JSON_SCHEMA,
            },
        },
        "temperature": 0,
        "max_completion_tokens": max_completion_tokens,
        "reasoning_effort": reasoning_effort,
    }

    raw = None
    usage = None
    last_error = None
    llm_calls = 0
    parsed = None

    for attempt in range(2):
        wait_for_rate_limit(CEREBRAS_RATE_LIMIT_KEY, CEREBRAS_RATE_LIMIT_RPS, capacity=1)
        llm_calls += 1
        try:
            resp = requests.post(
                CEREBRAS_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=timeout_seconds,
            )
        except requests.RequestException as e:
            last_error = f"HTTP request failed: {e}"
            continue

        if resp.status_code != 200:
            # Never include response headers (could echo back auth-adjacent
            # data) - only status code and a truncated body snippet.
            last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
            continue

        try:
            data = resp.json()
            raw = data["choices"][0]["message"]["content"]
            usage_raw = data.get("usage") or {}
            usage = {
                "input_tokens": usage_raw.get("prompt_tokens", 0),
                "output_tokens": usage_raw.get("completion_tokens", 0),
                "total_tokens": usage_raw.get("total_tokens", 0),
                "reasoning_tokens": (usage_raw.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            }
        except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
            last_error = f"Malformed Cerebras response envelope: {e}"
            continue

        if not raw or not raw.strip():
            last_error = "Empty Cerebras response (no content)"
            continue

        try:
            candidate_parsed = json.loads(_strip_code_fence(raw))
        except json.JSONDecodeError as e:
            last_error = f"JSON parse failed: {e}"
            continue

        if not isinstance(candidate_parsed, dict):
            last_error = "Top-level JSON was not an object"
            continue

        parsed = candidate_parsed
        last_error = None
        break

    return parsed, raw, usage, llm_calls, last_error


def _build_research_query_from_parsed(parsed: Dict[str, Any], query: str) -> ResearchQuery:
    """Shared postprocessing path - IDENTICAL to candidate_b_structured's
    (constraint canonicalization, entity coercion, ambiguity coercion,
    deterministic normalization). Reused verbatim so any quality difference
    between candidate_b and a Cerebras candidate reflects the model/provider
    only, never a postprocessing divergence."""
    constraints_raw = _canonicalize_constraint_fields(parsed.get("constraints") or {})
    try:
        constraints = ConstraintSet(**{
            k: v for k, v in constraints_raw.items() if k in ConstraintSet.model_fields
        })
    except ValidationError:
        constraints = ConstraintSet()

    ambig_raw = parsed.get("ambiguity") or {}
    try:
        ambiguity = AmbiguityState(
            is_ambiguous=bool(ambig_raw.get("is_ambiguous", False)),
            ambiguity_reason=ambig_raw.get("ambiguity_reason"),
            candidate_interpretations=[
                c for c in (ambig_raw.get("candidate_interpretations") or []) if isinstance(c, str)
            ],
        )
    except (ValidationError, TypeError):
        ambiguity = AmbiguityState()

    return ResearchQuery(
        schema_version=SCHEMA_VERSION,
        original_query=query,
        normalized_query=re.sub(r"\s+", " ", query.strip()),
        intent=_coerce_intent(parsed.get("intent")),
        intent_confidence=float(parsed.get("intent_confidence", 0.0) or 0.0),
        entities=_coerce_entities(parsed.get("entities")),
        constraints=constraints,
        requested_evidence_types=_coerce_evidence_types(parsed.get("requested_evidence_types")),
        ambiguity=ambiguity,
        extraction_confidence=float(parsed.get("extraction_confidence", 0.0) or 0.0),
    )


# ---------------------------------------------------------------------------
# Cerebras intent-clarification revision (bounded follow-up experiment,
# 2026-09-24). The prior GPT-OSS pilot (artifacts/v2/nlu_cerebras_gptoss_pilot_results.json)
# was rejected at 6/8 intent accuracy: both misclassifications collapsed to
# the same generic class, A_literature_evidence. Forensic audit
# (artifacts/v2/nlu_cerebras_intent_revision_diagnosis.json) found that
# STRUCTURED_EXTRACTION_PROMPT already gives the model an explicit written
# precedence rule for B-vs-G (B_VS_G_RULE) and D-vs-E (DI_VS_E_RULE), but NO
# equivalent precedence rule exists for A versus anything, even though A's
# definition ("what does published research say about X") is the least
# structurally constrained of the 8 classes and can look like a safe,
# minimally-committal fallback whenever a query merely CONTAINS
# literature-flavored language, regardless of whether literature retrieval
# is the query's entire task.
#
# THE SINGLE ALLOWED REVISION (frozen - see nlu_cerebras_intent_revision_frozen.json,
# never touched again after this point regardless of pilot outcome): one new
# general primary-intent specificity-precedence rule, structurally parallel
# to B_VS_G_RULE/DI_VS_E_RULE - it names no entity, no query text, and no
# gold label from any benchmark example.
#
# Applied ONLY to a NEW prompt constant used exclusively by the Cerebras
# candidate functions below (extract_candidate_f_cerebras_gptoss /
# extract_candidate_g_cerebras_qwen). STRUCTURED_EXTRACTION_PROMPT itself -
# the prompt candidate_b_structured (the frozen, currently-serving PRODUCTION
# Nemotron architecture) actually calls - is NOT modified by this block, so
# the active production runtime is unaffected by this experiment.
# ---------------------------------------------------------------------------

A_PRIMARY_INTENT_RULE = (
    "A vs specific classes (primary-intent specificity precedence): "
    "A_literature_evidence applies ONLY when literature/evidence retrieval "
    "IS THE ENTIRE requested task. If the query ALSO requires "
    "identifying/filtering compounds or trials, chaining a later source's "
    "query parameters from an earlier source's result, or combining two or "
    "more independent source types into one answer, classify by that more "
    "specific structure (C/D/E/F/G as structurally applicable) instead - "
    "mentioning literature, published research, or evidence as ONE part of "
    "a larger multi-part question does not by itself make the whole query "
    "A. When more than one class could plausibly apply, select the most "
    "specific class that accounts for the query's ENTIRE request, never "
    "the broadest class that only accounts for part of it. This never "
    "overrides the ambiguity rule below: a genuinely underspecified query "
    "is still I_ambiguous even if it superficially resembles an A question."
)

_CEREBRAS_INTENT_INSERTION_ANCHOR = (
    "  A_literature_evidence, B_clinical_trial_landscape, C_compound_target, "
    "D_cross_source_synthesis, E_multi_hop_research, F_mechanism, "
    "G_constraint_heavy, I_ambiguous\n- B vs G"
)
CEREBRAS_INTENT_CLARIFIED_PROMPT = STRUCTURED_EXTRACTION_PROMPT.replace(
    _CEREBRAS_INTENT_INSERTION_ANCHOR,
    _CEREBRAS_INTENT_INSERTION_ANCHOR.replace(
        "\n- B vs G", "\n- {a_primary_intent_rule}\n- B vs G"
    ),
)
assert CEREBRAS_INTENT_CLARIFIED_PROMPT != STRUCTURED_EXTRACTION_PROMPT, (
    "Cerebras intent-revision insertion anchor not found in "
    "STRUCTURED_EXTRACTION_PROMPT - the shared prompt text changed "
    "elsewhere without updating this insertion point."
)


def _extract_via_cerebras(
    query: str,
    model: str,
    architecture_tag: str,
    prompt_template: Optional[str] = None,
    reasoning_effort: str = "low",
) -> NLUExtractionResult:
    """`prompt_template` defaults to CEREBRAS_INTENT_CLARIFIED_PROMPT (the
    GPT-OSS-only, permanently-rejected-candidate experimental revision) only
    for backward compatibility with candidate_f's historical call site.
    candidate_g (Qwen) passes the UNMODIFIED active-control
    STRUCTURED_EXTRACTION_PROMPT explicitly - see
    docs/v2/PHASE2_CEREBRAS_QWEN_EXPERIMENT.md Step 3: Qwen gets zero
    semantic/prompt tuning of any kind, including the one revision GPT-OSS
    received, since that revision was never accepted into the active
    control and was evaluated (and rejected) only within the GPT-OSS
    experiment."""
    t0 = time.time()
    template = prompt_template if prompt_template is not None else CEREBRAS_INTENT_CLARIFIED_PROMPT
    if template is CEREBRAS_INTENT_CLARIFIED_PROMPT:
        prompt = template.format(
            query=query,
            b_vs_g_rule=B_VS_G_RULE,
            d_vs_e_rule=DI_VS_E_RULE,
            a_primary_intent_rule=A_PRIMARY_INTENT_RULE,
        )
    else:
        # STRUCTURED_EXTRACTION_PROMPT (active control) - identical
        # .format() call signature to candidate_b_structured's, byte-for-byte.
        prompt = template.format(query=query, b_vs_g_rule=B_VS_G_RULE, d_vs_e_rule=DI_VS_E_RULE)

    parsed, raw, usage, llm_calls, last_error = _invoke_cerebras_json(prompt, model=model, reasoning_effort=reasoning_effort)

    if parsed is None:
        return NLUExtractionResult(
            schema_valid=False,
            raw_llm_output=raw,
            parse_error=f"NLU_FAILURE: exhausted {llm_calls} attempt(s), last error: {last_error}",
            architecture=architecture_tag,
            latency_ms=(time.time() - t0) * 1000,
            llm_calls=llm_calls,
            token_usage=usage,
        )

    try:
        rq = _build_research_query_from_parsed(parsed, query)
    except (ValidationError, ValueError, TypeError) as e:
        return NLUExtractionResult(
            schema_valid=False,
            raw_llm_output=raw,
            parse_error=f"ResearchQuery validation failed: {e}",
            architecture=architecture_tag,
            latency_ms=(time.time() - t0) * 1000,
            llm_calls=llm_calls,
            token_usage=usage,
        )

    return NLUExtractionResult(
        schema_valid=True,
        research_query=rq,
        raw_llm_output=raw,
        architecture=architecture_tag,
        token_usage=usage,
        latency_ms=(time.time() - t0) * 1000,
        llm_calls=llm_calls,
    )


def extract_candidate_f_cerebras_gptoss(query: str, model: Optional[str] = None) -> NLUExtractionResult:
    """Cerebras-hosted gpt-oss-120b, reasoning_effort='low' (the lowest
    officially-supported value - gpt-oss-120b does NOT support 'none', see
    provider verification artifact), strict JSON Schema structured output.
    `model` kwarg accepted for --model override parity with other
    candidates' evaluation-script flag; defaults to CEREBRAS_MODEL_GPT_OSS_120B."""
    return _extract_via_cerebras(query, model=model or CEREBRAS_MODEL_GPT_OSS_120B, architecture_tag="candidate_f_cerebras_gptoss")


def extract_candidate_g_cerebras_qwen(
    query: str, model: Optional[str] = None, reasoning_effort: str = "none"
) -> NLUExtractionResult:
    """Cerebras-hosted qwen-3.8-27b, a FRESH independent Phase-2 candidate
    evaluation (NOT a continuation of the permanently-rejected GPT-OSS
    round). Uses the UNMODIFIED active-control STRUCTURED_EXTRACTION_PROMPT
    - explicitly NOT CEREBRAS_INTENT_CLARIFIED_PROMPT/A_PRIMARY_INTENT_RULE,
    which were created and evaluated only within the rejected GPT-OSS
    experiment and were never accepted into the active control. Zero
    semantic/prompt tuning of any kind for this candidate. See
    docs/v2/PHASE2_CEREBRAS_QWEN_EXPERIMENT.md."""
    return _extract_via_cerebras(
        query,
        model=model or CEREBRAS_MODEL_QWEN_FALLBACK,
        architecture_tag="candidate_g_cerebras_qwen",
        prompt_template=STRUCTURED_EXTRACTION_PROMPT,
        reasoning_effort=reasoning_effort,
    )


ARCHITECTURE_FUNCS = {
    "candidate_a_baseline": extract_candidate_a,
    "candidate_b_structured": extract_candidate_b,
    "candidate_c_decomposed": extract_candidate_c,
    "candidate_d_local_qwen": extract_candidate_d_local_qwen,
    "candidate_e_nvidia_fast": extract_candidate_e_nvidia_fast,
    "candidate_f_cerebras_gptoss": extract_candidate_f_cerebras_gptoss,
    "candidate_g_cerebras_qwen": extract_candidate_g_cerebras_qwen,
}
