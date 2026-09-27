"""Deterministic PubMed search-term compiler (Phase 4).

`tools/pubmed_tool.py::search_pubmed()` sends whatever string the caller
gives it directly to NCBI's `esearch` `term` parameter. Prior to the Phase 4
date-filter fix (see that module's `search_pubmed` docstring/inline note),
callers sent the raw natural-language question text, which measured
Recall@10=0.045 on the same 22-case benchmark RAG measured 0.773 on
(`docs/v2/PHASE4_BASELINE_MEASUREMENT.md` Section 2) -- independent of the
date-filter defect, PubMed's own relevance ranking over an unstructured NL
string frequently fails to surface the correct article.

This module builds a real, structured search term from the fields a
`nlu.schemas.ResearchQuery` (or an equivalent plain dict) already carries --
entities and explicit constraints -- instead of the raw question text. It is
deliberately small:

- No MeSH-term invention. No synonym expansion. No stemming/tokenization
  that would turn a multi-word phrase into disconnected stopword-adjacent
  fragments.
- Biomedical entities (`canonical_name` if normalization found one, else the
  literal `surface_form`) are preserved verbatim -- "EGFR" stays "EGFR", a
  multi-word phrase like "non-small cell lung cancer" stays intact as one
  quoted phrase, never split into separate single-word terms.
- A temporal constraint is only reflected in the output if the input
  actually carries one (`ConstraintSet.temporal`); this module never
  invents a recency filter for a query that didn't ask for one. Only two
  narrow, deterministic temporal phrasings are parsed ("last N years",
  "since/after YYYY") -- anything else is left as an unparsed, verbatim
  trace note rather than guessed at.
- Fully deterministic: the same input produces byte-identical output on
  every call (plain string/regex logic, no LLM, no randomness, no wall
  clock in the *term* string -- `date_to` in a returned date filter is
  intentionally omitted rather than filled with "now" for this same
  reason; a caller wanting an end date passes one explicitly).
- Returns a small `CompiledPubMedQuery` dataclass carrying the compiled
  term string PLUS which input concepts fed it, so the mapping from
  ResearchQuery -> PubMed term is auditable rather than opaque.

This compiler does not call `tools/pubmed_tool.py` itself -- it is a pure
function from structured input to a search term string (and an optional
date-filter recommendation); wiring its output into a live
`search_pubmed()` call is the caller's job (see
`docs/v2/PHASE4_HETEROGENEOUS_RETRIEVAL.md`'s Candidate C measurement).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

# Entity surface forms/canonical names that carry no search value on their
# own (pure stopwords or empty/whitespace-only spans). Not a stemming or
# synonym table -- just a defensive filter against degenerate extraction
# output feeding a useless term into the query. Deliberately tiny.
_DEGENERATE_ENTITY_VALUES = {
    "", "the", "a", "an", "of", "in", "for", "and", "or", "with", "to",
}

# Two narrow, deterministic temporal phrasings. Anything else in
# constraints.temporal is preserved verbatim in the trace but NOT converted
# into a date filter (no guessing at what an unrecognized phrase means).
_LAST_N_YEARS_RE = re.compile(r"\blast\s+(\d{1,2})\s+years?\b", re.IGNORECASE)
_SINCE_AFTER_YEAR_RE = re.compile(r"\b(?:since|after)\s+(\d{4})\b", re.IGNORECASE)


@dataclass
class DateFilter:
    """A deterministic, explicitly-sourced date restriction. Both fields
    stay None unless a temporal constraint in the input actually parsed to
    one -- never filled in as an implicit default (that was exactly the
    defect this module exists alongside the fix for)."""

    years_back: Optional[int] = None
    date_from: Optional[str] = None  # YYYY/MM/DD, PubMed's esearch format
    source_phrase: Optional[str] = None  # the verbatim constraint text that produced this


@dataclass
class CompiledPubMedQuery:
    """Compiled PubMed search term plus full audit trail of what produced
    it. `query` is what a caller passes as `search_pubmed(query=...)`."""

    query: str
    source_concepts: List[str] = field(default_factory=list)
    """Entity terms (canonical_name/surface_form, verbatim) actually used
    to build `query`, in the order they were incorporated."""
    unparsed_temporal_notes: List[str] = field(default_factory=list)
    """Verbatim constraints.temporal entries that did NOT match either
    recognized temporal pattern -- kept for audit, not silently dropped."""
    date_filter: DateFilter = field(default_factory=DateFilter)
    fallback_used: bool = False
    """True when there were no usable entities and `query` fell back to the
    input's own normalized_query/original_query text verbatim (not
    fabricated -- literally the caller's own text)."""
    notes: List[str] = field(default_factory=list)


def _as_dict(research_query_or_dict: Union[Any, Dict[str, Any]]) -> Dict[str, Any]:
    """Accept either a real `nlu.schemas.ResearchQuery` instance (or any
    pydantic BaseModel with a compatible shape) or a plain dict with the
    same field names (`entities`, `constraints`, `normalized_query`,
    `original_query`). Using `model_dump()` when available keeps this
    function decoupled from importing nlu.schemas directly (avoids a
    retrieval -> nlu import-cycle risk) while still accepting the real
    object."""
    if research_query_or_dict is None:
        return {}
    if isinstance(research_query_or_dict, dict):
        return research_query_or_dict
    if hasattr(research_query_or_dict, "model_dump"):
        return research_query_or_dict.model_dump()
    # Last resort: best-effort attribute access for a duck-typed object.
    out: Dict[str, Any] = {}
    for attr in ("entities", "constraints", "normalized_query", "original_query"):
        if hasattr(research_query_or_dict, attr):
            out[attr] = getattr(research_query_or_dict, attr)
    return out


def _entity_term(entity: Union[Dict[str, Any], Any]) -> Optional[str]:
    """Extract the verbatim term for one entity: canonical_name if present
    and non-empty, else surface_form. Never invents, expands, or
    normalizes beyond what the input already carries."""
    if isinstance(entity, dict):
        canonical = entity.get("canonical_name")
        surface = entity.get("surface_form")
    else:
        canonical = getattr(entity, "canonical_name", None)
        surface = getattr(entity, "surface_form", None)

    term = (canonical or surface or "").strip()
    if not term or term.lower() in _DEGENERATE_ENTITY_VALUES:
        return None
    return term


def _quote_if_multiword(term: str) -> str:
    """Preserve a multi-word phrase as one PubMed phrase-search term
    (quoted) instead of letting esearch's default term parsing silently
    split it into independently-matched single words. Single-token terms
    (e.g. 'EGFR') are left unquoted -- quoting a single token changes
    nothing functionally but adds visual noise."""
    if " " in term:
        # Don't double-quote a term that already carries embedded quotes.
        if '"' in term:
            return term
        return f'"{term}"'
    return term


def _parse_temporal(constraints: Dict[str, Any]) -> tuple[Optional[DateFilter], List[str]]:
    """Deterministically parse constraints['temporal'] entries. Returns the
    FIRST recognized date filter (constraints.temporal is a list because a
    query could theoretically name more than one; only the first
    unambiguous match is used -- combining multiple temporal phrases into
    one date range is not a deterministic operation this module attempts)
    plus the list of entries that did not match any recognized pattern."""
    temporal_entries = constraints.get("temporal") or []
    unparsed: List[str] = []

    for entry in temporal_entries:
        if not isinstance(entry, str) or not entry.strip():
            continue
        m = _LAST_N_YEARS_RE.search(entry)
        if m:
            return DateFilter(years_back=int(m.group(1)), source_phrase=entry), unparsed
        m = _SINCE_AFTER_YEAR_RE.search(entry)
        if m:
            return DateFilter(date_from=f"{m.group(1)}/01/01", source_phrase=entry), unparsed
        unparsed.append(entry)

    return None, unparsed


def compile_pubmed_query(
    research_query_or_dict: Union[Any, Dict[str, Any]],
) -> CompiledPubMedQuery:
    """Build a deterministic PubMed search term from structured fields.

    Args:
        research_query_or_dict: a `nlu.schemas.ResearchQuery` instance, or a
            plain dict with the same field names (`entities`: list of
            dicts/objects each with `canonical_name`/`surface_form`;
            `constraints`: dict with a `temporal` list among others;
            `normalized_query`/`original_query`: str, used only as a
            no-entities fallback).

    Returns:
        A `CompiledPubMedQuery` with the compiled term string, the entity
        terms that fed it (`source_concepts`), any parsed date filter, and
        any unparsed temporal notes -- everything needed to audit how the
        term was built.

    Guarantees:
        - Deterministic: identical input -> byte-identical `query` output.
        - No entity/synonym/MeSH term appears in `query` that was not
          verbatim present in the input's entities or fallback text.
        - No date filter is set unless `constraints.temporal` explicitly
          contained a recognized recency phrase.
        - Never raises on empty/malformed input -- degrades to an empty
          query string with `fallback_used=True` and an explanatory note.
    """
    data = _as_dict(research_query_or_dict)

    entities = data.get("entities") or []
    constraints = data.get("constraints") or {}
    if not isinstance(constraints, dict):
        # A real ConstraintSet BaseModel that slipped through _as_dict as
        # something other than a dict (e.g. nested model not yet dumped).
        constraints = dict(constraints) if hasattr(constraints, "keys") else (
            constraints.model_dump() if hasattr(constraints, "model_dump") else {}
        )

    source_concepts: List[str] = []
    seen_lower: set = set()
    for entity in entities:
        term = _entity_term(entity)
        if term is None:
            continue
        key = term.lower()
        if key in seen_lower:
            continue
        seen_lower.add(key)
        source_concepts.append(term)

    date_filter, unparsed_temporal = _parse_temporal(constraints)

    notes: List[str] = []
    fallback_used = False

    if source_concepts:
        query = " AND ".join(_quote_if_multiword(t) for t in source_concepts)
    else:
        fallback_text = (data.get("normalized_query") or data.get("original_query") or "").strip()
        if fallback_text:
            query = fallback_text
            fallback_used = True
            notes.append(
                "No usable entities in structured input; fell back to the "
                "input's own normalized_query/original_query text verbatim."
            )
        else:
            query = ""
            fallback_used = True
            notes.append(
                "No usable entities and no fallback query text in input; "
                "compiled query is empty. Caller must handle an empty "
                "search term (e.g. skip the search) rather than send it "
                "to esearch as-is."
            )

    return CompiledPubMedQuery(
        query=query,
        source_concepts=source_concepts,
        unparsed_temporal_notes=unparsed_temporal,
        date_filter=date_filter or DateFilter(),
        fallback_used=fallback_used,
        notes=notes,
    )
