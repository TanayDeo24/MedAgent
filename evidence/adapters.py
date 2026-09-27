"""Pure, deterministic source -> Evidence adapters.

No LLM calls anywhere in this module (per the governing directive's
"Phase 5 should preferably be model-free" instruction, echoed in
docs/v2/PHASE5_EVIDENCE_CONTRACT.md Section 0/10). Every function here is a
plain, synchronous, side-effect-free transformation from a real parsed
source shape (read directly from retrieval/retriever.py, tools/pubmed_tool.py,
tools/clinical_trials_tool.py, tools/chembl_tool.py - not guessed) into
`evidence.models.Evidence` records.

Placeholder-as-data handling (shared policy across adapters):
    Several source parsers substitute a literal human-readable string (e.g.
    "No title available", "Unknown journal", "N/A") when a field is
    genuinely absent, instead of `None`/omission (documented as an
    UNRELIABLE risk in docs/v2/PHASE5_INITIAL_EVIDENCE_AUDIT.md Sections
    A.2/C). Every adapter below normalizes those exact known placeholder
    strings back to `None` (for optional metadata fields) or, where the
    placeholder would otherwise become `Evidence.content` itself (PubMed
    live's abstract), causes the adapter to return `None`/skip that record
    entirely rather than let a fallback string masquerade as real source
    text. See `pubmed_live_result_to_evidence` for the specific policy on
    the abstract placeholder.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from evidence.models import (
    ChemblEvidenceMetadata,
    ClinicalTrialEvidenceMetadata,
    ContentFormat,
    Evidence,
    EvidenceType,
    Provenance,
    PubMedEvidenceMetadata,
    SourceType,
    make_evidence_id,
    make_source_url,
)

# ---------------------------------------------------------------------------
# Shared placeholder-normalization helpers
# ---------------------------------------------------------------------------


def _none_if_placeholder(value: Optional[str], *placeholders: str) -> Optional[str]:
    """Normalize a source parser's known literal fallback string(s) (and
    plain empty string / None) to None. Never mutates a real value."""

    if value is None:
        return None
    if value in placeholders or value == "":
        return None
    return value


# ===========================================================================
# PubMed RAG (chunk-level) - retrieval/retriever.py's Document
# ===========================================================================


def pubmed_rag_document_to_evidence(
    doc: Any,
    corpus_index_version: str,
    retrieval_method: str = "rag_hybrid_rerank",
    retrieval_rank: Optional[int] = None,
) -> Evidence:
    """Convert one `retrieval.retriever.Document` into a chunk-level
    Evidence record.

    Preserves `chunk_index`/`num_chunks` (via `provenance`) and the compound
    `chunk_id` identity (via the evidence id itself, `pubmed:<pmid>:chunk:
    <chunk_index>`) - the audit's #1 "stop dropping this" finding
    (`agent/nodes.py`'s `_retrieve_rag_context` currently discards it before
    it reaches `AgentState`; this adapter is what a future wiring step would
    call instead of that lossy path).

    `doc.doi`/`doc.journal`/`doc.year`/`doc.pub_date` are `""` by dataclass
    default when genuinely absent from `chunks.jsonl` (audit A.1) - not an
    error, so they are stored as `None` in `PubMedEvidenceMetadata`, never
    fabricated as a placeholder string.

    `doc.score` is intentionally NOT treated as an absolute confidence value
    (audit A.1: its scale depends on which retrieval method produced it) -
    it is stored as `provenance.retrieval_score` tagged with
    `retrieval_method`, per contract Section 9's no-invented-confidence rule.

    `retrieval.retriever.Document` has no `authors` field at all (unlike the
    live-API path) - `PubMedEvidenceMetadata.authors` is always `[]` here,
    which is a real, documented limitation of the RAG path, not a bug in
    this adapter.

    `call_id` is deliberately left `None` - the RAG path is not a Phase-3
    orchestration tool call (see `Provenance.call_id`'s docstring); inventing
    one here would be a fabricated trace link, a hard-gate violation.
    """

    pmid = getattr(doc, "pmid", "")
    if not pmid:
        raise ValueError(
            "pubmed_rag_document_to_evidence: Document.pmid must be non-empty "
            "(never fabricate a source_record_id)"
        )

    chunk_index = getattr(doc, "chunk_index", 0)
    text = getattr(doc, "text", "")

    metadata = PubMedEvidenceMetadata(
        journal=_none_if_placeholder(getattr(doc, "journal", "") or None),
        year=_none_if_placeholder(getattr(doc, "year", "") or None),
        pub_date=_none_if_placeholder(getattr(doc, "pub_date", "") or None),
        doi=_none_if_placeholder(getattr(doc, "doi", "") or None),
        authors=[],
    )

    provenance = Provenance(
        call_id=None,
        retrieval_method=retrieval_method,
        retrieval_rank=retrieval_rank,
        retrieval_score=getattr(doc, "score", None),
        corpus_index_version=corpus_index_version,
        chunk_index=chunk_index,
        num_chunks=getattr(doc, "num_chunks", None),
        field_path=None,
    )

    title = getattr(doc, "title", "") or None

    return Evidence(
        evidence_id=make_evidence_id(SourceType.PUBMED, pmid, chunk_index=chunk_index),
        source_type=SourceType.PUBMED,
        source_record_id=pmid,
        source_url=make_source_url(SourceType.PUBMED, pmid),
        evidence_type=EvidenceType.TEXT_PASSAGE,
        content=text,
        content_format=ContentFormat.VERBATIM_TEXT,
        title=title,
        source_metadata=metadata,
        provenance=provenance,
    )


# ===========================================================================
# PubMed live-API (article-level) - tools/pubmed_tool.py's parsed dict
# ===========================================================================

_PUBMED_TITLE_PLACEHOLDER = "No title available"
_PUBMED_ABSTRACT_PLACEHOLDER = "No abstract available"
_PUBMED_JOURNAL_PLACEHOLDER = "Unknown journal"
_PUBMED_PUBDATE_PLACEHOLDER = "Date not available"


def pubmed_live_result_to_evidence(
    result: Dict[str, Any],
    call_id: Optional[str] = None,
    retrieval_rank: Optional[int] = None,
) -> Optional[Evidence]:
    """Convert one parsed dict from `tools/pubmed_tool.py`'s
    `_parse_xml_article`/`parse_results` output into an article-level
    Evidence record, or `None` if there is no real content to build one
    from.

    Placeholder-abstract policy (audit A.2's identified UNRELIABLE risk):
    `_parse_xml_article` substitutes the literal string "No abstract
    available" when `<AbstractText>` is absent, rather than `None`/"". If
    that placeholder (or a genuinely empty string) reaches this adapter, it
    is NOT treated as real source content - this adapter returns `None`
    (no Evidence record created at all) rather than either (a) silently
    storing the placeholder string as `Evidence.content` as if it were real
    abstract text, or (b) inventing a distinct "no abstract available" flag
    field on Evidence (the contract's `Evidence` model has no such field,
    and adding one would blur `content_format`'s meaning). Skipping is the
    conservative choice: an Evidence record with no real content is not
    useful evidence, and the contract requires `content` to be non-empty and
    source-faithful (never a tool-internal fallback string standing in for
    real text). The literal title placeholder ("No title available") is
    treated more leniently - it only blocks `title`, not the whole record,
    since a real abstract can exist even when the title element was
    unparseable.

    `pmid` is required and never fabricated - an empty `pmid` also yields
    `None` (no real source_record_id to build an id/url from).
    """

    pmid = result.get("pmid") or ""
    if not pmid:
        return None

    abstract = result.get("abstract") or ""
    if abstract in ("", _PUBMED_ABSTRACT_PLACEHOLDER):
        return None

    title = _none_if_placeholder(result.get("title"), _PUBMED_TITLE_PLACEHOLDER)

    metadata = PubMedEvidenceMetadata(
        journal=_none_if_placeholder(result.get("journal"), _PUBMED_JOURNAL_PLACEHOLDER),
        year=_none_if_placeholder(result.get("year")),
        pub_date=_none_if_placeholder(result.get("pub_date"), _PUBMED_PUBDATE_PLACEHOLDER),
        doi=_none_if_placeholder(result.get("doi")),
        authors=list(result.get("authors") or []),
    )

    provenance = Provenance(
        call_id=call_id,
        retrieval_method="live_api",
        retrieval_rank=retrieval_rank,
        retrieval_score=None,
        corpus_index_version=None,
        chunk_index=None,
        num_chunks=None,
        field_path=None,
    )

    return Evidence(
        evidence_id=make_evidence_id(SourceType.PUBMED, pmid),
        source_type=SourceType.PUBMED,
        source_record_id=pmid,
        source_url=make_source_url(SourceType.PUBMED, pmid),
        evidence_type=EvidenceType.TEXT_PASSAGE,
        content=abstract,
        content_format=ContentFormat.VERBATIM_TEXT,
        title=title,
        source_metadata=metadata,
        provenance=provenance,
    )


# ===========================================================================
# ClinicalTrials.gov - tools/clinical_trials_tool.py's parsed dict
# ===========================================================================

_TRIAL_STATUS_PLACEHOLDER = "Unknown"
_TRIAL_PHASE_PLACEHOLDER = "N/A"
_TRIAL_TITLE_PLACEHOLDER = "No title"
_TRIAL_ENROLLMENT_PLACEHOLDER = "N/A"
_TRIAL_DATE_PLACEHOLDER = "N/A"
_TRIAL_SUMMARY_PLACEHOLDER = "No summary available"
_TRIAL_SPONSOR_PLACEHOLDER = "Unknown"

# field_path values verified directly against tools/clinical_trials_tool.py's
# `_parse_study` (lines cited in docs/v2/PHASE5_INITIAL_EVIDENCE_AUDIT.md
# Section B / re-read in this task). Recorded ONLY where the parser reads a
# single fixed key path with no join/derivation:
#   status              <- protocolSection.statusModule.overallStatus            (fixed)
#   phase               <- ", ".join(protocolSection.designModule.phases)        (DERIVED - joined; no single field_path, contract Section 12)
#   conditions          <- protocolSection.conditionsModule.conditions           (fixed)
#   sponsor             <- protocolSection.sponsorCollaboratorsModule.leadSponsor.name (fixed)
#   enrollment          <- protocolSection.designModule.enrollmentInfo.count     (fixed)
#   start_date          <- protocolSection.statusModule.startDateStruct.date     (fixed)
#   completion_date     <- protocolSection.statusModule.completionDateStruct.date (fixed)
#   brief_summary       <- protocolSection.descriptionModule.briefSummary[:500]  (fixed path, but VALUE is truncated by the parser - flagged in content, see below)
#   interventions       <- protocolSection.armsInterventionsModule.interventions (list of dicts assembled per-item - no single scalar field_path, left None)
#   locations           <- protocolSection.contactsLocationsModule.locations (collapsed to capped strings - no single scalar field_path, left None)
_FIELD_PATHS = {
    "status": "protocolSection.statusModule.overallStatus",
    "conditions": "protocolSection.conditionsModule.conditions",
    "sponsor": "protocolSection.sponsorCollaboratorsModule.leadSponsor.name",
    "enrollment": "protocolSection.designModule.enrollmentInfo.count",
    "start_date": "protocolSection.statusModule.startDateStruct.date",
    "completion_date": "protocolSection.statusModule.completionDateStruct.date",
    "brief_summary": "protocolSection.descriptionModule.briefSummary",
}


def _trial_field_evidence(
    nct_id: str,
    evidence_type: EvidenceType,
    content: str,
    field_path: Optional[str],
    metadata: ClinicalTrialEvidenceMetadata,
    retrieval_rank: Optional[int],
    call_id: Optional[str],
    title: Optional[str],
    content_format: ContentFormat = ContentFormat.FIELD_VALUE,
) -> Evidence:
    provenance = Provenance(
        call_id=call_id,
        retrieval_method="live_api",
        retrieval_rank=retrieval_rank,
        retrieval_score=None,
        corpus_index_version=None,
        chunk_index=None,
        num_chunks=None,
        field_path=field_path,
    )
    return Evidence(
        evidence_id=make_evidence_id(SourceType.CLINICAL_TRIALS, nct_id),
        source_type=SourceType.CLINICAL_TRIALS,
        source_record_id=nct_id,
        source_url=make_source_url(SourceType.CLINICAL_TRIALS, nct_id),
        evidence_type=evidence_type,
        content=content,
        content_format=content_format,
        title=title,
        source_metadata=metadata,
        provenance=provenance,
    )


def clinical_trial_to_evidence_records(
    trial: Dict[str, Any],
    call_id: Optional[str] = None,
    retrieval_rank: Optional[int] = None,
) -> List[Evidence]:
    """Convert one parsed dict from `tools/clinical_trials_tool.py`'s
    `_parse_study` output into MULTIPLE field-level Evidence records (one
    per meaningful structured field), per contract Section 6's TRIAL_STATUS
    / TRIAL_PHASE / TRIAL_FIELD taxonomy. Never collapses a whole trial into
    one blob record.

    Every `Evidence.evidence_id` for the same trial is
    `nct:<nct_id>` (Section 3 does not define a per-field sub-id scheme;
    `evidence_type` + `provenance.field_path` together disambiguate which
    field a given record represents, since multiple Evidence records for
    the same NCT id is expected/normal here).

    Known parser fallback placeholders ("Unknown", "N/A", "No title",
    "No summary available") are normalized away - a field whose only value
    is its own placeholder default produces no Evidence record for that
    field (never cited as if it were real trial data).

    `brief_summary` is truncated to 500 characters by the parser itself with
    no truncation marker (audit finding) - this adapter appends an explicit
    `" [TRUNCATED BY SOURCE PARSER]"` marker when the stored value is
    exactly 500 characters (the parser's cutoff length), so a truncated
    excerpt is never presented as if it were the complete summary; content
    remains the source parser's own verbatim (truncated) text otherwise.
    """

    nct_id = trial.get("nct_id") or ""
    if not nct_id:
        return []

    title = _none_if_placeholder(trial.get("title"), _TRIAL_TITLE_PLACEHOLDER)

    metadata = ClinicalTrialEvidenceMetadata(
        status=_none_if_placeholder(trial.get("status"), _TRIAL_STATUS_PLACEHOLDER),
        phase=_none_if_placeholder(trial.get("phase"), _TRIAL_PHASE_PLACEHOLDER),
        conditions=list(trial.get("conditions") or []),
        interventions=list(trial.get("interventions") or []),
        sponsor=_none_if_placeholder(trial.get("sponsor"), _TRIAL_SPONSOR_PLACEHOLDER),
        enrollment=_none_if_placeholder(
            str(trial.get("enrollment")) if trial.get("enrollment") is not None else None,
            _TRIAL_ENROLLMENT_PLACEHOLDER,
        ),
        start_date=_none_if_placeholder(trial.get("start_date"), _TRIAL_DATE_PLACEHOLDER),
        completion_date=_none_if_placeholder(
            trial.get("completion_date"), _TRIAL_DATE_PLACEHOLDER
        ),
    )

    records: List[Evidence] = []

    status = _none_if_placeholder(trial.get("status"), _TRIAL_STATUS_PLACEHOLDER)
    if status:
        records.append(
            _trial_field_evidence(
                nct_id, EvidenceType.TRIAL_STATUS, status,
                _FIELD_PATHS["status"], metadata, retrieval_rank, call_id, title,
            )
        )

    phase = _none_if_placeholder(trial.get("phase"), _TRIAL_PHASE_PLACEHOLDER)
    if phase:
        records.append(
            _trial_field_evidence(
                nct_id, EvidenceType.TRIAL_PHASE, phase,
                None,  # derived/joined - no single fixed field_path (contract Section 12)
                metadata, retrieval_rank, call_id, title,
            )
        )

    conditions = trial.get("conditions") or []
    if conditions:
        records.append(
            _trial_field_evidence(
                nct_id, EvidenceType.TRIAL_FIELD, ", ".join(conditions),
                _FIELD_PATHS["conditions"], metadata, retrieval_rank, call_id, title,
            )
        )

    sponsor = _none_if_placeholder(trial.get("sponsor"), _TRIAL_SPONSOR_PLACEHOLDER)
    if sponsor:
        records.append(
            _trial_field_evidence(
                nct_id, EvidenceType.TRIAL_FIELD, sponsor,
                _FIELD_PATHS["sponsor"], metadata, retrieval_rank, call_id, title,
            )
        )

    enrollment = trial.get("enrollment")
    if enrollment is not None and str(enrollment) != _TRIAL_ENROLLMENT_PLACEHOLDER:
        records.append(
            _trial_field_evidence(
                nct_id, EvidenceType.TRIAL_FIELD, str(enrollment),
                _FIELD_PATHS["enrollment"], metadata, retrieval_rank, call_id, title,
            )
        )

    start_date = _none_if_placeholder(trial.get("start_date"), _TRIAL_DATE_PLACEHOLDER)
    if start_date:
        records.append(
            _trial_field_evidence(
                nct_id, EvidenceType.TRIAL_FIELD, start_date,
                _FIELD_PATHS["start_date"], metadata, retrieval_rank, call_id, title,
            )
        )

    completion_date = _none_if_placeholder(trial.get("completion_date"), _TRIAL_DATE_PLACEHOLDER)
    if completion_date:
        records.append(
            _trial_field_evidence(
                nct_id, EvidenceType.TRIAL_FIELD, completion_date,
                _FIELD_PATHS["completion_date"], metadata, retrieval_rank, call_id, title,
            )
        )

    for intervention in trial.get("interventions") or []:
        name = (intervention or {}).get("name")
        itype = (intervention or {}).get("type")
        if not name:
            continue
        content = f"{itype}: {name}" if itype else name
        records.append(
            _trial_field_evidence(
                nct_id, EvidenceType.TRIAL_FIELD, content,
                None,  # per-item dict assembled by the parser - no single scalar field_path
                metadata, retrieval_rank, call_id, title,
            )
        )

    brief_summary = _none_if_placeholder(trial.get("brief_summary"), _TRIAL_SUMMARY_PLACEHOLDER)
    if brief_summary:
        content = brief_summary
        if len(brief_summary) == 500:
            content = brief_summary + " [TRUNCATED BY SOURCE PARSER]"
        records.append(
            _trial_field_evidence(
                nct_id, EvidenceType.TRIAL_FIELD, content,
                _FIELD_PATHS["brief_summary"], metadata, retrieval_rank, call_id, title,
                content_format=ContentFormat.VERBATIM_TEXT,
            )
        )

    return records


# ===========================================================================
# ChEMBL - tools/chembl_tool.py's four parsed shapes
# ===========================================================================

_CHEMBL_MOA_PLACEHOLDER = "Not available"
_CHEMBL_NAME_PLACEHOLDER = "No name"
_CHEMBL_NUMERIC_PLACEHOLDER = "N/A"


def chembl_target_or_indication_result_to_evidence(
    result: Dict[str, Any],
    chembl_operation: str,
    call_id: Optional[str] = None,
    retrieval_rank: Optional[int] = None,
) -> Optional[Evidence]:
    """Convert one parsed dict from `search_by_target` / `search_by_indication`
    / `get_drug_info` into a single Evidence record.

    EvidenceType mapping rule (per contract Section 6, applied to the two
    distinct parsed shapes these three operations actually produce -
    `tools/chembl_tool.py`'s `_parse_molecule` vs `_parse_drug_indication`):

      - `chembl_operation == "search_by_indication"` -> the record is
        `_parse_drug_indication`'s shape (`chembl_id, drug_name, indication,
        max_phase, efo_term`) -> `EvidenceType.INDICATION`. `content` is the
        indication value itself (`result["indication"]`, the MeSH heading),
        the field-faithful value this record actually represents.

      - `chembl_operation in ("search_by_target", "get_drug_info")` -> the
        record is `_parse_molecule`'s shape. Both a compound-identity claim
        (name/molecule_type) and a target/mechanism claim
        (mechanism_of_action/mechanisms) can live in the same dict, so the
        rule picks the more specific type when real data supports it: if
        `mechanism_of_action` is present and not the parser's own
        `"Not available"` placeholder, the record represents a
        target/mechanism relation -> `EvidenceType.TARGET_RELATION`,
        `content` = the mechanism_of_action text (never truncated/paraphrased
        - the parser's own first-available-mechanism string). Otherwise the
        record only supports a compound-identity claim ->
        `EvidenceType.COMPOUND_IDENTITY`, `content` = the compound's name.

    Raises `ValueError` for an unrecognized `chembl_operation` or an empty
    `chembl_id` (both indicate a caller contract violation, not a
    legitimate "no evidence here" case) rather than silently guessing. When
    the input is well-formed but genuinely carries no real field value to
    make faithful Evidence content from (e.g. both `mechanism_of_action`
    and `name` are placeholder/absent), returns `None` - matching every
    other adapter's skip convention - instead of raising, so callers (see
    `evidence/registry.py::normalize`) can treat "valid record, nothing
    worth citing" uniformly across all ChEMBL operations rather than
    needing a special except-clause for this one function.
    """

    chembl_id = result.get("chembl_id") or ""
    if not chembl_id:
        raise ValueError(
            "chembl_target_or_indication_result_to_evidence: chembl_id must be "
            "non-empty (never fabricate a source_record_id)"
        )

    if chembl_operation == "search_by_indication":
        indication = result.get("indication") or ""
        name = _none_if_placeholder(result.get("drug_name"))
        max_phase = result.get("max_phase")
        metadata = ChemblEvidenceMetadata(
            molecule_type=None,
            max_phase=str(max_phase) if max_phase is not None else None,
            mechanism_of_action=None,
            match_type=None,
        )
        evidence_type = EvidenceType.INDICATION
        content = indication or None
    elif chembl_operation in ("search_by_target", "get_drug_info"):
        name = _none_if_placeholder(result.get("name"), _CHEMBL_NAME_PLACEHOLDER)
        moa = _none_if_placeholder(result.get("mechanism_of_action"), _CHEMBL_MOA_PLACEHOLDER)
        max_phase = result.get("max_phase")
        metadata = ChemblEvidenceMetadata(
            molecule_type=_none_if_placeholder(result.get("molecule_type")),
            max_phase=str(max_phase) if max_phase is not None else None,
            mechanism_of_action=moa,
            match_type=None,
        )
        if moa:
            evidence_type = EvidenceType.TARGET_RELATION
            content = moa
        else:
            evidence_type = EvidenceType.COMPOUND_IDENTITY
            content = name
    else:
        raise ValueError(
            f"chembl_target_or_indication_result_to_evidence: unrecognized "
            f"chembl_operation {chembl_operation!r}"
        )

    if not content:
        # No real field value to make faithful Evidence content from -
        # never substitute a placeholder here either. This is a legitimate
        # "nothing to cite" outcome for a well-formed record, not a caller
        # error, so it's a skip (None), matching every other adapter's
        # convention - not an exception.
        return None

    provenance = Provenance(
        call_id=call_id,
        retrieval_method=chembl_operation,
        retrieval_rank=retrieval_rank,
        retrieval_score=None,
        corpus_index_version=None,
        chunk_index=None,
        num_chunks=None,
        field_path=None,
    )

    return Evidence(
        evidence_id=make_evidence_id(SourceType.CHEMBL, chembl_id),
        source_type=SourceType.CHEMBL,
        source_record_id=chembl_id,
        source_url=make_source_url(SourceType.CHEMBL, chembl_id),
        evidence_type=evidence_type,
        content=content,
        content_format=ContentFormat.FIELD_VALUE,
        title=name,
        source_metadata=metadata,
        provenance=provenance,
    )


def chembl_resolve_compound_name_to_evidence(
    result: Dict[str, Any],
    call_id: Optional[str] = None,
) -> Optional[Evidence]:
    """Convert `resolve_compound_name`'s output dict into a single
    COMPOUND_IDENTITY Evidence record, or `None` when no confirmed real ID
    exists.

    Per contract Section 3 and re-confirmed directly against
    `tools/chembl_tool.py`'s `resolve_compound_name` implementation
    (`_no_match`/`_ambiguous` helpers): BOTH `match_type == "no_match"` and
    `match_type == "ambiguous_match"` leave `chembl_id` as `None` in the
    real tool output - `ambiguous_match` surfaces its alternatives only via
    `candidates` (each itself just a free-text `{chembl_id, preferred_name}`
    pair, none of them "the" answer), never a single confirmed id. Since
    `Evidence.source_record_id` must be a real, confirmed id and never
    fabricated, this adapter returns `None` for both cases - there is no
    partial/best-guess Evidence record built from `candidates` either,
    since picking one would itself be an invented match.

    For the four confirming match types (`exact_id_passthrough`,
    `exact_preferred_name`, `exact_synonym`, `fuzzy`), returns one
    `COMPOUND_IDENTITY` Evidence record with `match_type` preserved verbatim
    in `ChemblEvidenceMetadata.match_type` - reusing the audit's identified
    best-in-repo provenance pattern rather than reinventing a confidence
    scheme.
    """

    match_type = result.get("match_type")
    chembl_id = result.get("chembl_id")

    if match_type in ("no_match", "ambiguous_match") or not chembl_id:
        return None

    preferred_name = result.get("preferred_name") or result.get("matched_name")

    metadata = ChemblEvidenceMetadata(
        molecule_type=None,
        max_phase=None,
        mechanism_of_action=None,
        match_type=match_type,
    )

    provenance = Provenance(
        call_id=call_id,
        retrieval_method="resolve_compound_name",
        retrieval_rank=None,
        retrieval_score=None,
        corpus_index_version=None,
        chunk_index=None,
        num_chunks=None,
        field_path=None,
    )

    content = preferred_name or result.get("input_name") or chembl_id

    return Evidence(
        evidence_id=make_evidence_id(SourceType.CHEMBL, chembl_id),
        source_type=SourceType.CHEMBL,
        source_record_id=chembl_id,
        source_url=make_source_url(SourceType.CHEMBL, chembl_id),
        evidence_type=EvidenceType.COMPOUND_IDENTITY,
        content=content,
        content_format=ContentFormat.FIELD_VALUE,
        title=preferred_name,
        source_metadata=metadata,
        provenance=provenance,
    )
